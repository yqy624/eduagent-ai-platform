"""AI 工具服务 — 封装 AI Agent 可调用的业务逻辑"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Assignment, Course, Submission, User
from app.models.ai_models import (
    AiRun,
    AiToolCall,
    AiQaLog,
    AiLearningReport,
    AiGradingSuggestion,
    AiEvalResult,
    AiIndexJob,
    AiDocumentChunk,
)
from ai.tools.course_tools import CourseTools
from ai.tools.grade_tools import GradeTools
from ai.tools.assignment_tools import AssignmentTools
from ai.tools.notification_tools import NotificationTools


class AiToolService:
    """AI 工具服务 — 供 Agent 调用"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.course_tools = CourseTools(db)
        self.grade_tools = GradeTools(db)
        self.assignment_tools = AssignmentTools(db)
        self.notification_tools = NotificationTools(db)

    # ===== Agent 运行记录 =====
    async def create_run(
        self, user_id: int, role: str, workflow: str, input_summary: Optional[str] = None
    ) -> AiRun:
        run = AiRun(
            user_id=user_id,
            role=role,
            workflow=workflow,
            status="RUNNING",
            input_summary=input_summary,
            created_at=datetime.now(),
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def complete_run(
        self, run_id: int, output_summary: Optional[str] = None,
        latency_ms: int = 0, token_usage: Optional[int] = None
    ):
        result = await self.db.execute(select(AiRun).where(AiRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "COMPLETED"
            run.output_summary = output_summary
            run.latency_ms = latency_ms
            run.token_usage = token_usage
            run.finished_at = datetime.now()
            await self.db.flush()

    async def fail_run(self, run_id: int, error: str, latency_ms: int = 0):
        result = await self.db.execute(select(AiRun).where(AiRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "FAILED"
            run.error = error
            run.latency_ms = latency_ms
            run.finished_at = datetime.now()
            await self.db.flush()

    async def log_tool_call(
        self, run_id: int, tool_name: str,
        input_data: str, output_data: str,
        latency_ms: int = 0, error: Optional[str] = None
    ):
        call = AiToolCall(
            run_id=run_id,
            tool_name=tool_name,
            input_json=input_data,
            output_json=output_data,
            latency_ms=latency_ms,
            error=error,
            created_at=datetime.now(),
        )
        self.db.add(call)
        await self.db.flush()

    async def log_tool_call_json(
        self, run_id: Optional[int], tool_name: str,
        input_data: Any = None, output_data: Any = None,
        latency_ms: int = 0, error: Optional[str] = None
    ):
        if not run_id:
            return
        await self.log_tool_call(
            run_id=run_id,
            tool_name=tool_name,
            input_data=json.dumps(input_data or {}, ensure_ascii=False, default=str),
            output_data=json.dumps(output_data or {}, ensure_ascii=False, default=str),
            latency_ms=latency_ms,
            error=error,
        )

    # ===== RAG 问答日志 =====
    async def log_qa(
        self, course_id: int, user_id: int, question: str,
        answer: Optional[str] = None, citations: Optional[str] = None,
        confidence: float = 0.0, latency_ms: int = 0
    ) -> AiQaLog:
        log = AiQaLog(
            course_id=course_id,
            user_id=user_id,
            question=question,
            answer=answer,
            citations_json=citations,
            confidence=confidence,
            latency_ms=latency_ms,
            created_at=datetime.now(),
        )
        self.db.add(log)
        await self.db.flush()
        return log

    # ===== 学习报告 =====
    async def save_learning_report(
        self, student_id: int, course_id: int, run_id: int,
        weakness_json: str, plan_json: str
    ) -> AiLearningReport:
        report = AiLearningReport(
            student_id=student_id,
            course_id=course_id,
            run_id=run_id,
            weakness_json=weakness_json,
            plan_json=plan_json,
            created_at=datetime.now(),
        )
        self.db.add(report)
        await self.db.flush()
        return report

    # ===== 批改建议 =====
    async def save_grading_suggestion(
        self, submission_id: int, run_id: int,
        suggested_score: float, rubric_json: str, comment: str,
        strengths: Optional[str] = None, weaknesses: Optional[str] = None
    ) -> AiGradingSuggestion:
        suggestion = AiGradingSuggestion(
            submission_id=submission_id,
            run_id=run_id,
            suggested_score=suggested_score,
            rubric_json=rubric_json,
            comment=comment,
            strengths=strengths,
            weaknesses=weaknesses,
            teacher_action="PENDING",
            created_at=datetime.now(),
        )
        self.db.add(suggestion)
        await self.db.flush()
        return suggestion

    # ===== 索引作业 =====
    async def create_index_job(
        self, file_id: int, course_id: int
    ) -> AiIndexJob:
        job = AiIndexJob(
            file_id=file_id,
            course_id=course_id,
            status="PENDING",
            created_at=datetime.now(),
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get_run_detail(self, run_id: int) -> Optional[Dict[str, Any]]:
        """获取 Agent 运行详情"""
        result = await self.db.execute(select(AiRun).where(AiRun.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            return None

        calls = await self.get_tool_calls(run_id)

        return {
            "id": run.id,
            "user_id": run.user_id,
            "role": run.role,
            "workflow": run.workflow,
            "status": run.status,
            "input_summary": run.input_summary,
            "output_summary": run.output_summary,
            "latency_ms": run.latency_ms,
            "token_usage": run.token_usage,
            "error": run.error,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "tool_calls": calls,
        }

    async def get_tool_calls(self, run_id: int) -> List[Dict[str, Any]]:
        result = await self.db.execute(
            select(AiToolCall)
            .where(AiToolCall.run_id == run_id)
            .order_by(AiToolCall.created_at)
        )
        calls = list(result.scalars().all())
        return [
            {
                "id": c.id,
                "run_id": c.run_id,
                "tool_name": c.tool_name,
                "input": c.input_json,
                "output": c.output_json,
                "latency_ms": c.latency_ms,
                "error": c.error,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in calls
        ]

    # ===== Agent 工具暴露 =====
    async def get_student_profile(self, student_id: int) -> Dict[str, Any]:
        """获取学生画像（用于 Agent）"""
        courses = await self.course_tools.get_student_courses(student_id)
        grades = await self.grade_tools.get_student_grades(student_id)
        low_scores = await self.grade_tools.get_low_score_assignments(student_id)

        return {
            "student_id": student_id,
            "courses": courses,
            "grades": grades,
            "low_score_assignments": low_scores,
            "grade_count": len(grades),
            "average_score": (
                sum(g["score"] for g in grades if g["score"] is not None) / len(grades)
                if grades else 0
            ),
        }

    async def get_weakness_analysis(self, student_id: int) -> Dict[str, Any]:
        """分析薄弱点"""
        profile = await self.get_student_profile(student_id)
        return profile

    async def get_course_materials_summary(
        self, course_id: int
    ) -> List[Dict[str, Any]]:
        """获取课程资料摘要"""
        result = await self.db.execute(
            select(AiDocumentChunk).where(AiDocumentChunk.course_id == course_id)
        )
        chunks = list(result.scalars().all())
        sources = set(c.source for c in chunks)
        return [
            {"source": s, "chunk_count": sum(1 for c in chunks if c.source == s)}
            for s in sources
        ]
