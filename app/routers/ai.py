"""AI 路由 — RAG 问答、学情诊断、学习计划、批改建议"""
import json
import time
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_teacher, require_student
from app.models.models import User
from app.models.ai_models import AiRun
from app.schemas.ai import (
    DiagnosisResponse,
    GradingSuggestionResponse,
    LearningPlanResponse,
    QAResponse,
    QARequest,
    AgentRunResponse,
)
from app.schemas.common import ApiResponse
from app.services.ai_tool_service import AiToolService
from ai.llm import get_llm, get_embeddings
from ai.prompts import COURSE_QA_SYSTEM_PROMPT, LEARNING_PLAN_SYSTEM_PROMPT
from ai.rag.vector_store import VectorStoreManager
from ai.workflows.learning_plan_graph import build_learning_plan_graph, LearningPlanState
from ai.workflows.grading_graph import build_grading_graph, GradingState

router = APIRouter(prefix="/api/ai", tags=["AI 智能助手"])


@router.post("/courses/{course_id}/qa")
async def course_qa(
    course_id: int,
    req: QARequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """课程 RAG 问答（使用 Ollama LLM + 数据库文档切片）"""
    service = AiToolService(db)
    start = time.time()

    try:
        # 从数据库读取课程文档切片
        from app.models.ai_models import AiDocumentChunk
        from sqlalchemy import select
        result = await db.execute(
            select(AiDocumentChunk)
            .where(AiDocumentChunk.course_id == course_id, AiDocumentChunk.content.isnot(None))
            .limit(20)
        )
        chunks = list(result.scalars().all())

        context = ""
        citations = []
        if chunks:
            for c in chunks[:5]:
                ctx = c.content or ""
                if ctx:
                    context += f"[来源: {c.source or '课程资料'}]\n{ctx}\n\n"
                    citations.append({
                        "source": c.source or "课程资料",
                        "content": ctx[:200],
                        "score": 1.0,
                    })

        # 如果资料库为空，使用课程信息作为兜底
        if not context:
            from app.models.models import Course
            cr = await db.execute(select(Course).where(Course.id == course_id))
            course = cr.scalar_one_or_none()
            if course and course.description:
                context = f"[课程简介]\n{course.description}\n\n课程名称：{course.name}\n学分：{course.credits}\n"
                citations.append({"source": "课程简介", "content": course.description[:200], "score": 0.8})
            
        if not context:
            latency = int((time.time() - start) * 1000)
            await service.log_qa(course_id=course_id, user_id=user.id,
                question=req.question,
                answer="该课程暂无已索引的资料。请教师上传课程资料后再提问。",
                confidence=0.0, latency_ms=latency)
            return ApiResponse.ok(data=QAResponse(
                answer="该课程暂无已索引的资料。请教师上传课程资料后再提问。",
                citations=[], confidence=0.0, needs_clarification=True,
            ))

        # 用 LLM 回答问题
        try:
            llm = get_llm(temperature=0.3)
            prompt = f"""你是一个课程助教。基于以下课程资料回答学生的问题。
如果资料不足以回答问题，请明确说明「资料中未找到相关信息」。

课程资料：
{context}

学生问题：{req.question}

请用中文回答，并引用资料来源。"""
            response = await llm.ainvoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            answer = f"AI 回答暂时不可用（{e}），以下是相关资料：\n\n{context[:500]}..."

        latency = int((time.time() - start) * 1000)
        await service.log_qa(course_id=course_id, user_id=user.id,
            question=req.question, answer=answer,
            citations=json.dumps(citations, ensure_ascii=False),
            confidence=0.8 if citations else 0, latency_ms=latency)

        return ApiResponse.ok(data=QAResponse(
            answer=answer, citations=citations,
            confidence=0.8 if citations else 0,
            needs_clarification=not bool(citations),
        ))
    except Exception as e:
        return ApiResponse.error(message=f"AI 问答失败: {str(e)}", code=500)


@router.post("/students/{student_id}/diagnosis")
async def diagnose_student(
    student_id: int,
    course_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """学情诊断"""
    service = AiToolService(db)
    start = time.time()

    try:
        profile = await service.get_student_profile(student_id)
        weakness = await service.get_weakness_analysis(student_id)

        latency = int((time.time() - start) * 1000)

        # 记录运行
        run = await service.create_run(
            user_id=user.id, role=user.role,
            workflow="diagnosis",
            input_summary=f"诊断学生 {student_id} 学情",
        )
        await service.complete_run(run.id, latency_ms=latency)

        return ApiResponse.ok(data=DiagnosisResponse(
            student_id=student_id,
            course_id=course_id or 0,
            weakness=weakness.get("weakness_areas", []),
            evidence=[
                {"metric": "总作业数", "value": profile.get("grade_count", 0)},
                {"metric": "平均分", "value": round(profile.get("average_score", 0), 1)},
                {"metric": "通过率", "value": f"{weakness.get('pass_rate', 0)}%"},
            ],
            trend=weakness.get("summary", ""),
        ))

    except Exception as e:
        return ApiResponse.error(message=f"诊断失败: {str(e)}", code=500)


@router.post("/students/{student_id}/learning-plan")
async def generate_learning_plan(
    student_id: int,
    course_id: int = Query(..., description="课程 ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """生成学习计划（LangGraph Agent）"""
    service = AiToolService(db)
    start = time.time()

    try:
        # 创建运行记录
        run = await service.create_run(
            user_id=user.id, role=user.role,
            workflow="learning_plan",
            input_summary=f"为学生 {student_id} 生成课程 {course_id} 的学习计划",
        )

        # 构建 Agent 并执行
        graph = build_learning_plan_graph(service)

        initial_state: LearningPlanState = {
            "user_id": user.id,
            "student_id": student_id,
            "course_id": course_id,
            "role": user.role,
            "profile": None,
            "grades": None,
            "submissions": None,
            "weakness": None,
            "retrieved_materials": None,
            "plan": None,
            "exercises": None,
            "validation_errors": None,
            "tool_trace": None,
            "final_report": None,
            "error": None,
        }

        # 执行 Graph
        result = await graph.ainvoke(initial_state)

        latency = int((time.time() - start) * 1000)
        token_usage = None

        final_report = result.get("final_report", {}) or result
        error = result.get("error")

        if error:
            await service.fail_run(run.id, error=error, latency_ms=latency)
            return ApiResponse.error(message=f"生成计划失败: {error}", code=500)

        await service.complete_run(
            run.id,
            output_summary=json.dumps(final_report.get("plan", {}), ensure_ascii=False)[:500],
            latency_ms=latency,
            token_usage=token_usage,
        )

        plan_data = final_report.get("plan", {})
        return ApiResponse.ok(data=LearningPlanResponse(
            student_id=student_id,
            course_id=course_id,
            weakness_summary=plan_data.get("weakness_summary", ""),
            daily_tasks=plan_data.get("daily_tasks", []),
            materials=plan_data.get("materials", []),
            exercises=final_report.get("exercises") or [],
            total_hours=plan_data.get("total_hours", 0),
            plan_id=final_report.get("report_id"),
        ))

    except Exception as e:
        return ApiResponse.error(message=f"生成学习计划失败: {str(e)}", code=500)


@router.post("/teacher/submissions/{submission_id}/grade-suggestion")
async def grade_suggestion(
    submission_id: int,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """AI 批改建议（LangGraph Agent）"""
    service = AiToolService(db)
    from ai.tools.assignment_tools import AssignmentTools
    from ai.tools.grade_tools import GradeTools
    start = time.time()

    try:
        # 创建运行记录
        run = await service.create_run(
            user_id=user.id, role=user.role,
            workflow="grading",
            input_summary=f"为提交 {submission_id} 生成批改建议",
        )

        # 构建 Agent 并执行
        graph = build_grading_graph(service)

        initial_state: GradingState = {
            "user_id": user.id,
            "submission_id": submission_id,
            "role": user.role,
            "submission": None,
            "assignment": None,
            "peer_reviews": None,
            "suggested_score": None,
            "rubric": None,
            "comment": None,
            "strengths": None,
            "weaknesses": None,
            "risks": None,
            "teacher_action": None,
            "teacher_score": None,
            "tool_trace": None,
            "error": None,
        }

        result = await graph.ainvoke(initial_state)

        latency = int((time.time() - start) * 1000)
        error = result.get("error")

        if error:
            await service.fail_run(run.id, error=error, latency_ms=latency)
            return ApiResponse.error(message=f"生成批改建议失败: {error}", code=500)

        await service.complete_run(run.id, latency_ms=latency)

        return ApiResponse.ok(data=GradingSuggestionResponse(
            submission_id=submission_id,
            suggested_score=result.get("suggested_score", 0),
            rubric=result.get("rubric", {}),
            comment=result.get("comment", ""),
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            risks=result.get("risks", []),
        ))

    except Exception as e:
        return ApiResponse.error(message=f"生成批改建议失败: {str(e)}", code=500)


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查看 Agent 运行轨迹"""
    service = AiToolService(db)
    detail = await service.get_run_detail(run_id)
    if detail is None:
        return ApiResponse.error(message="运行记录不存在", code=404)
    # 权限检查：只能查看自己的运行记录
    if detail["user_id"] != user.id and user.role != "ADMIN":
        return ApiResponse.error(message="无权查看此运行记录", code=403)
    return ApiResponse.ok(data=detail)
