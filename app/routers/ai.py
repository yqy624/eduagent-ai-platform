"""AI 路由 — RAG 问答、学情诊断、学习计划、批改建议"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PROJECT_ROOT, settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_teacher
from app.models.models import Assignment, Course, Enrollment, Notification, StoredFile, Submission, User
from app.models.ai_models import AiDocumentChunk, AiGradingSuggestion, AiIndexJob, AiQaLog
from app.schemas.assignment import GradeRequest
from app.schemas.ai import (
    AgentChatRequest,
    AgentChatResponse,
    DiagnosisResponse,
    FeedbackUpdateRequest,
    GradingSuggestionResponse,
    LearningPlanResponse,
    QAResponse,
    QARequest,
)
from app.schemas.common import ApiResponse
from app.services.teacher_service import TeacherService
from app.services.ai_tool_service import AiToolService
from ai.llm import get_llm
from ai.rag.loader import DocumentLoader, TextSplitter
from ai.rag.vector_store import VectorStoreManager
from ai.workflows.learning_plan_graph import build_learning_plan_graph, LearningPlanState
from ai.workflows.grading_graph import build_grading_graph, GradingState

router = APIRouter(prefix="/api/ai", tags=["AI 智能助手"])


async def _ensure_course_access(db: AsyncSession, course_id: int, user: User) -> Course:
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if user.role == "ADMIN":
        return course
    if user.role == "TEACHER" and course.teacher_id == user.id:
        return course
    if user.role == "STUDENT":
        enrolled = await db.execute(
            select(Enrollment.id).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == user.id,
            )
        )
        if enrolled.scalar_one_or_none() is not None:
            return course
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this course")


async def _ensure_student_ai_access(
    db: AsyncSession,
    student_id: int,
    user: User,
    course_id: Optional[int] = None,
) -> None:
    if user.role == "ADMIN":
        return
    if user.role == "STUDENT":
        if student_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this student")
        if course_id is not None:
            await _ensure_course_access(db, course_id, user)
        return
    if user.role == "TEACHER":
        if course_id is not None:
            course = await _ensure_course_access(db, course_id, user)
            enrolled = await db.execute(
                select(Enrollment.id).where(
                    Enrollment.course_id == course.id,
                    Enrollment.student_id == student_id,
                )
            )
        else:
            enrolled = await db.execute(
                select(Enrollment.id)
                .join(Course, Course.id == Enrollment.course_id)
                .where(Enrollment.student_id == student_id, Course.teacher_id == user.id)
                .limit(1)
            )
        if enrolled.scalar_one_or_none() is not None:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this student")


async def _ensure_teacher_submission_access(
    db: AsyncSession,
    submission_id: int,
    user: User,
) -> None:
    result = await db.execute(
        select(Submission, Assignment, Course)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .where(Submission.id == submission_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    _, _, course = row
    if user.role != "ADMIN" and course.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this submission")


async def _ensure_teacher_feedback_access(
    db: AsyncSession,
    suggestion_id: int,
    user: User,
) -> AiGradingSuggestion:
    result = await db.execute(
        select(AiGradingSuggestion)
        .where(AiGradingSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    await _ensure_teacher_submission_access(db, suggestion.submission_id, user)
    return suggestion


def _resolve_material_path(file: StoredFile) -> Optional[Path]:
    raw = Path(file.storage_path)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(PROJECT_ROOT / raw)
        candidates.append(settings.upload_path / file.object_key)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


async def _search_course_chunks(
    db: AsyncSession,
    course_id: int,
    question: str,
    max_citations: int = 5,
    threshold: float = 0.18,
) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(AiDocumentChunk)
        .where(AiDocumentChunk.course_id == course_id, AiDocumentChunk.content.isnot(None))
        .order_by(AiDocumentChunk.file_id, AiDocumentChunk.chunk_index)
    )
    chunks = list(result.scalars().all())
    chunk_lookup = {
        (chunk.file_id, chunk.chunk_index): chunk
        for chunk in chunks
    }

    def citation_from_chunk(chunk: AiDocumentChunk, similarity: float) -> Dict[str, Any]:
        return {
            "document_id": chunk.file_id,
            "chunk_index": chunk.chunk_index,
            "content": (chunk.content or "")[:800],
            "score": similarity,
            "similarity": similarity,
            "source": chunk.source or "课程资料",
            "file_name": chunk.source or None,
        }

    try:
        vector_hits = VectorStoreManager().similarity_search(
            question,
            k=max_citations * 3,
            collection_name=f"course_{course_id}",
            filter={"course_id": course_id},
        )
    except RuntimeError:
        vector_hits = []

    vector_scored = []
    for doc, distance in vector_hits:
        metadata = doc.metadata or {}
        if metadata.get("course_id") != course_id:
            continue
        key = (
            metadata.get("file_id") or metadata.get("document_id"),
            metadata.get("chunk_index"),
        )
        chunk = chunk_lookup.get(key)
        if chunk is None:
            continue
        similarity = round(1 / (1 + max(float(distance or 0), 0)), 4)
        similarity = _boost_course_material_similarity(question, chunk, similarity)
        if similarity >= threshold:
            vector_scored.append((similarity, chunk))

    if vector_scored:
        vector_scored.sort(key=lambda item: item[0], reverse=True)
        return [
            citation_from_chunk(chunk, similarity)
            for similarity, chunk in vector_scored[:max_citations]
        ]

    scored = []
    for chunk in chunks:
        similarity = VectorStoreManager.lexical_similarity(question, chunk.content or "")
        similarity = _boost_course_material_similarity(question, chunk, similarity)
        if similarity >= threshold:
            scored.append((similarity, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        citation_from_chunk(chunk, similarity)
        for similarity, chunk in scored[:max_citations]
    ]


def _build_rag_context(citations: List[Dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{idx}. {item['source']} / chunk {item['chunk_index']} / similarity {item['similarity']:.2f}]\n{item['content']}"
        for idx, item in enumerate(citations, 1)
    )


def _assignment_material_text(assignment: Assignment) -> str:
    due_date = assignment.due_date.isoformat() if assignment.due_date else "未设置"
    total_points = assignment.total_points if assignment.total_points is not None else "未设置"
    description = (assignment.description or "暂无要求").strip()
    detail = (assignment.detail or "暂无详情").strip()
    return (
        f"作业标题：{assignment.title}\n"
        f"作业要求：{description}\n"
        f"作业详情：{detail}\n"
        f"截止时间：{due_date}\n"
        f"总分：{total_points}"
    )


def _boost_course_material_similarity(question: str, chunk: AiDocumentChunk, similarity: float) -> float:
    question_text = (question or "").strip()
    if not question_text:
        return similarity
    assignment_intents = ("作业", "任务", "提交", "截止", "截止时间", "总分", "分数", "要求")
    if chunk.source_type == "assignment" and any(keyword in question_text for keyword in assignment_intents):
        return max(similarity, 0.82)
    return similarity


def _classify_agent_mode(question: str, course_id: Optional[int]) -> str:
    text = (question or "").strip().lower()
    material_keywords = (
        "资料", "课件", "文档", "讲义", "教材", "知识点", "概念", "原理", "解释",
        "根据材料", "课程内容", "索引", "rag",
    )
    business_keywords = (
        "我的", "个人", "我", "作业", "成绩", "分数", "通知", "待办",
        "提交", "截止", "批改", "评语", "互评", "学生", "选课", "未读", "班级",
        "待批改", "已批改", "未提交", "已提交",
    )
    advice_keywords = (
        "建议", "计划", "怎么学", "如何学", "复习", "安排", "薄弱", "提升", "总结",
        "规划", "优先",
    )
    wants_rag = bool(course_id) and any(keyword in text for keyword in material_keywords)
    wants_business = any(keyword in text for keyword in business_keywords)
    wants_advice = any(keyword in text for keyword in advice_keywords)
    if wants_advice and course_id:
        return "hybrid"
    if wants_rag and wants_business:
        return "hybrid"
    if wants_rag:
        return "rag"
    if wants_business:
        return "business"
    return "general"


def _json_context(data: Dict[str, Any], max_chars: int = 9000) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...（上下文过长，已截断）"


AGENT_MODE_CONFIG = {
    "course_material": {"label": "课程资料", "needs_rag": True, "needs_business": False},
    "assignment_submission": {"label": "作业提交", "needs_rag": False, "needs_business": True},
    "teaching_advice": {"label": "教学建议", "needs_rag": True, "needs_business": True},
    "other": {"label": "其他问题", "needs_rag": False, "needs_business": False},
}


async def _collect_agent_memory(
    db: AsyncSession,
    user: User,
    course_id: Optional[int],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """读取当前用户最近的对话，作为跨请求的长期记忆。"""
    filters = [AiQaLog.user_id == user.id]
    if course_id:
        filters.append(AiQaLog.course_id.in_([0, course_id]))
    result = await db.execute(
        select(AiQaLog)
        .where(*filters)
        .order_by(AiQaLog.created_at.desc(), AiQaLog.id.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return [
        {
            "question": item.question,
            "answer": item.answer,
            "course_id": item.course_id,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in rows
    ]


def _build_agent_memory_context(memory: List[Dict[str, Any]]) -> str:
    if not memory:
        return "暂无历史对话。"
    return "\n\n".join(
        f"用户：{item['question']}\n助手：{item.get('answer') or ''}"
        for item in memory
    )


async def _collect_recent_notifications(db: AsyncSession, user: User) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Notification)
        .where(Notification.recipient == user.username)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(8)
    )
    return [
        {
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "category": item.category,
            "is_read": item.is_read,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in result.scalars().all()
    ]


async def _collect_student_agent_context(
    db: AsyncSession,
    user: User,
    course_id: Optional[int],
) -> Dict[str, Any]:
    course_filter = [Enrollment.student_id == user.id]
    if course_id:
        course_filter.append(Enrollment.course_id == course_id)
    course_rows = await db.execute(
        select(Course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(*course_filter)
        .order_by(Course.created_at.desc(), Course.id.desc())
    )
    courses = list(course_rows.scalars().all())
    course_ids = [course.id for course in courses]

    assignments: List[Dict[str, Any]] = []
    if course_ids:
        assignment_rows = await db.execute(
            select(Assignment, Course, Submission)
            .join(Course, Course.id == Assignment.course_id)
            .outerjoin(
                Submission,
                (Submission.assignment_id == Assignment.id)
                & (Submission.student_id == user.id),
            )
            .where(Assignment.course_id.in_(course_ids))
            .order_by(Assignment.due_date.asc(), Assignment.created_at.desc())
            .limit(12)
        )
        for assignment, course, submission in assignment_rows:
            assignments.append({
                "id": assignment.id,
                "course_id": course.id,
                "course_name": course.name,
                "title": assignment.title,
                "description": assignment.description,
                "detail": assignment.detail,
                "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
                "total_points": assignment.total_points,
                "submission_status": submission.status if submission else "NOT_SUBMITTED",
                "score": submission.score if submission else None,
                "teacher_comment": submission.teacher_comment if submission else None,
            })

    grade_filters = [Submission.student_id == user.id, Submission.score.isnot(None)]
    if course_id:
        grade_filters.append(Course.id == course_id)
    grade_rows = await db.execute(
        select(Submission, Assignment, Course)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .where(*grade_filters)
        .order_by(Submission.graded_at.desc(), Submission.id.desc())
        .limit(10)
    )
    grades = [
        {
            "course_name": course.name,
            "assignment_title": assignment.title,
            "score": submission.score,
            "total_points": assignment.total_points,
            "teacher_comment": submission.teacher_comment,
            "graded_at": submission.graded_at.isoformat() if submission.graded_at else None,
        }
        for submission, assignment, course in grade_rows
    ]

    return {
        "role": "STUDENT",
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "courses": [
            {
                "id": course.id,
                "name": course.name,
                "description": course.description,
                "schedule": course.schedule,
                "credits": course.credits,
                "category": course.category,
            }
            for course in courses
        ],
        "assignments": assignments,
        "grades": grades,
        "notifications": await _collect_recent_notifications(db, user),
    }


async def _collect_teacher_agent_context(
    db: AsyncSession,
    user: User,
    course_id: Optional[int],
) -> Dict[str, Any]:
    course_filter = []
    if user.role != "ADMIN":
        course_filter.append(Course.teacher_id == user.id)
    if course_id:
        course_filter.append(Course.id == course_id)
    course_rows = await db.execute(
        select(Course)
        .where(*course_filter)
        .order_by(Course.created_at.desc(), Course.id.desc())
    )
    courses = list(course_rows.scalars().all())
    course_ids = [course.id for course in courses]

    assignments: List[Dict[str, Any]] = []
    teaching_summary: Dict[str, Any] = {"student_count": 0, "pending_grading": 0, "graded_count": 0, "average_score": None}
    recent_submissions: List[Dict[str, Any]] = []
    if course_ids:
        student_count = await db.execute(
            select(func.count(func.distinct(Enrollment.student_id)))
            .where(Enrollment.course_id.in_(course_ids))
        )
        pending_grading = await db.execute(
            select(func.count(Submission.id))
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Assignment.course_id.in_(course_ids), Submission.status == "SUBMITTED")
        )
        graded_count = await db.execute(
            select(func.count(Submission.id))
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Assignment.course_id.in_(course_ids), Submission.status == "GRADED")
        )
        average_score = await db.execute(
            select(func.avg(Submission.score))
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Assignment.course_id.in_(course_ids), Submission.score.isnot(None))
        )
        average_value = average_score.scalar()
        teaching_summary = {
            "student_count": student_count.scalar() or 0,
            "pending_grading": pending_grading.scalar() or 0,
            "graded_count": graded_count.scalar() or 0,
            "average_score": float(average_value) if average_value is not None else None,
        }

        assignment_rows = await db.execute(
            select(Assignment, Course)
            .join(Course, Course.id == Assignment.course_id)
            .where(Assignment.course_id.in_(course_ids))
            .order_by(Assignment.created_at.desc(), Assignment.id.desc())
            .limit(12)
        )
        for assignment, course in assignment_rows:
            submit_count = await db.execute(
                select(func.count(Submission.id)).where(Submission.assignment_id == assignment.id)
            )
            graded = await db.execute(
                select(func.count(Submission.id)).where(
                    Submission.assignment_id == assignment.id,
                    Submission.status == "GRADED",
                )
            )
            assignments.append({
                "id": assignment.id,
                "course_id": course.id,
                "course_name": course.name,
                "title": assignment.title,
                "description": assignment.description,
                "detail": assignment.detail,
                "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
                "total_points": assignment.total_points,
                "submission_count": submit_count.scalar() or 0,
                "graded_count": graded.scalar() or 0,
            })

        submission_rows = await db.execute(
            select(Submission, Assignment, Course, User)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Course, Course.id == Assignment.course_id)
            .join(User, User.id == Submission.student_id)
            .where(Assignment.course_id.in_(course_ids))
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            .limit(10)
        )
        recent_submissions = [
            {
                "course_name": course.name,
                "assignment_title": assignment.title,
                "student_name": student.display_name or student.username,
                "status": submission.status,
                "score": submission.score,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
            }
            for submission, assignment, course, student in submission_rows
        ]

    return {
        "role": user.role,
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "courses": [
            {
                "id": course.id,
                "name": course.name,
                "description": course.description,
                "schedule": course.schedule,
                "credits": course.credits,
                "category": course.category,
                "enrolled_count": course.enrolled_count,
            }
            for course in courses
        ],
        "teaching_summary": teaching_summary,
        "assignments": assignments,
        "recent_submissions": recent_submissions,
        "notifications": await _collect_recent_notifications(db, user),
    }


async def _collect_agent_business_context(
    db: AsyncSession,
    user: User,
    course_id: Optional[int],
) -> Dict[str, Any]:
    if course_id:
        await _ensure_course_access(db, course_id, user)
    if user.role == "STUDENT":
        return await _collect_student_agent_context(db, user, course_id)
    return await _collect_teacher_agent_context(db, user, course_id)


def _fallback_agent_answer(
    question: str,
    mode: str,
    business_context: Optional[Dict[str, Any]],
    citations: List[Dict[str, Any]],
) -> str:
    parts: List[str] = []
    if business_context:
        courses = business_context.get("courses") or []
        assignments = business_context.get("assignments") or []
        grades = business_context.get("grades") or []
        notifications = business_context.get("notifications") or []
        summary = business_context.get("teaching_summary") or {}
        if courses:
            parts.append("课程：" + "、".join(str(item.get("name")) for item in courses[:5]))
        if assignments:
            parts.append("近期作业：" + "；".join(
                f"{item.get('course_name', '')}/{item.get('title', '')}（{item.get('submission_status') or item.get('submission_count', '-') }）"
                for item in assignments[:5]
            ))
        if grades:
            parts.append("近期成绩：" + "；".join(
                f"{item.get('course_name', '')}/{item.get('assignment_title', '')}: {item.get('score')}"
                for item in grades[:5]
            ))
        if summary:
            parts.append(
                f"教学概览：学生 {summary.get('student_count', 0)} 人，待批改 {summary.get('pending_grading', 0)} 份，已评分 {summary.get('graded_count', 0)} 份。"
            )
        if notifications:
            parts.append("近期通知：" + "；".join(item.get("title") or "" for item in notifications[:5]))
    if citations:
        parts.append("课程资料引用：" + "；".join(
            f"{item.get('source', '课程资料')} chunk {item.get('chunk_index', 0)}"
            for item in citations[:3]
        ))
    if parts:
        return "我先根据系统里能查到的数据整理如下：\n" + "\n".join(f"- {part}" for part in parts)
    if mode == "course_material":
        return "请先选择一门课程，或先为该课程建立 RAG 索引后再提问课程资料。"
    return "我是校园学习助手，可以回答学习方法、课程安排建议、作业推进思路等问题；我不能实时联网查询外部信息。"


@router.post("/courses/{course_id}/documents/index")
async def index_course_documents(
    course_id: int,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Index uploaded course materials into DB chunks and optional vector store."""
    await _ensure_course_access(db, course_id, user)
    if user.role not in {"ADMIN", "TEACHER"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only teachers or admins can index documents")

    result = await db.execute(
        select(StoredFile)
        .where(StoredFile.course_id == course_id)
        .order_by(StoredFile.created_at.desc(), StoredFile.id.desc())
    )
    files = list(result.scalars().all())
    assignment_result = await db.execute(
        select(Assignment)
        .where(Assignment.course_id == course_id)
        .order_by(Assignment.created_at.desc(), Assignment.id.desc())
    )
    assignments = list(assignment_result.scalars().all())

    loader = DocumentLoader()
    splitter = TextSplitter(chunk_size=700, chunk_overlap=80)
    vector_store = VectorStoreManager()
    vector_store.delete_collection(f"course_{course_id}")
    await db.execute(delete(AiDocumentChunk).where(AiDocumentChunk.course_id == course_id))
    indexed_files = []
    total_chunks = 0

    for file in files:
        job = AiIndexJob(
            file_id=file.id,
            course_id=course_id,
            status="RUNNING",
            created_at=datetime.now(),
        )
        db.add(job)
        await db.flush()

        path = _resolve_material_path(file)
        if path is None:
            job.status = "FAILED"
            job.error_message = "文件不存在"
            job.finished_at = datetime.now()
            indexed_files.append({"file_id": file.id, "name": file.original_name, "status": "FAILED", "error": job.error_message})
            continue

        text = loader.load(str(path))
        if not text:
            job.status = "FAILED"
            job.error_message = "无法解析文件内容"
            job.finished_at = datetime.now()
            indexed_files.append({"file_id": file.id, "name": file.original_name, "status": "FAILED", "error": job.error_message})
            continue

        chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk and chunk.strip()]
        doc_chunks = []
        for index, content in enumerate(chunks):
            chunk = AiDocumentChunk(
                course_id=course_id,
                file_id=file.id,
                chunk_index=index,
                content=content,
                content_hash=VectorStoreManager.compute_content_hash(content),
                source=file.original_name,
                source_type=file.extension or "unknown",
                char_count=len(content),
                vector_id=f"course:{course_id}:file:{file.id}:chunk:{index}",
                created_at=datetime.now(),
            )
            db.add(chunk)
            doc_chunks.append(chunk)

        vector_status = "SKIPPED"
        vector_error = None
        if doc_chunks:
            from langchain_core.documents import Document
            docs = [
                Document(
                    page_content=chunk.content or "",
                    metadata={
                        "course_id": course_id,
                        "document_id": file.id,
                        "file_id": file.id,
                        "chunk_index": chunk.chunk_index,
                        "source": chunk.source,
                    },
                )
                for chunk in doc_chunks
            ]
            try:
                vector_store.add_documents(docs, collection_name=f"course_{course_id}")
                vector_status = "INDEXED"
            except RuntimeError as exc:
                vector_error = str(exc)

        job.status = "COMPLETED"
        job.total_chunks = len(doc_chunks)
        job.finished_at = datetime.now()
        total_chunks += len(doc_chunks)
        indexed_files.append({
            "file_id": file.id,
            "name": file.original_name,
            "status": "COMPLETED",
            "chunk_count": len(doc_chunks),
            "vector_status": vector_status,
            "vector_error": vector_error,
        })

    for assignment in assignments:
        text = _assignment_material_text(assignment)
        chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk and chunk.strip()]
        doc_chunks = []
        document_id = -assignment.id
        for index, content in enumerate(chunks):
            chunk = AiDocumentChunk(
                course_id=course_id,
                file_id=document_id,
                chunk_index=index,
                content=content,
                content_hash=VectorStoreManager.compute_content_hash(content),
                source=f"作业：{assignment.title}",
                source_type="assignment",
                char_count=len(content),
                vector_id=f"course:{course_id}:assignment:{assignment.id}:chunk:{index}",
                created_at=datetime.now(),
            )
            db.add(chunk)
            doc_chunks.append(chunk)

        vector_status = "SKIPPED"
        vector_error = None
        if doc_chunks:
            from langchain_core.documents import Document
            docs = [
                Document(
                    page_content=chunk.content or "",
                    metadata={
                        "course_id": course_id,
                        "document_id": document_id,
                        "file_id": document_id,
                        "assignment_id": assignment.id,
                        "chunk_index": chunk.chunk_index,
                        "source": chunk.source,
                        "source_type": "assignment",
                    },
                )
                for chunk in doc_chunks
            ]
            try:
                vector_store.add_documents(docs, collection_name=f"course_{course_id}")
                vector_status = "INDEXED"
            except RuntimeError as exc:
                vector_error = str(exc)

        total_chunks += len(doc_chunks)
        indexed_files.append({
            "file_id": document_id,
            "assignment_id": assignment.id,
            "name": f"作业：{assignment.title}",
            "status": "COMPLETED",
            "chunk_count": len(doc_chunks),
            "vector_status": vector_status,
            "vector_error": vector_error,
        })

    if not indexed_files:
        return ApiResponse.ok(data={
            "course_id": course_id,
            "file_count": 0,
            "assignment_count": 0,
            "chunk_count": 0,
            "indexed_files": [],
            "message": "该课程暂无可索引的上传资料或作业内容",
        })

    return ApiResponse.ok(data={
        "course_id": course_id,
        "file_count": len(files),
        "assignment_count": len(assignments),
        "chunk_count": total_chunks,
        "indexed_files": indexed_files,
    })


@router.post("/courses/{course_id}/qa")
async def course_qa(
    course_id: int,
    req: QARequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """课程 RAG 问答：仅基于当前课程已索引资料回答。"""
    await _ensure_course_access(db, course_id, user)
    service = AiToolService(db)
    start = time.time()
    run = await service.create_run(
        user_id=user.id,
        role=user.role,
        workflow="rag_qa",
        input_summary=f"课程 {course_id} 问答: {req.question[:120]}",
    )

    try:
        citations = await _search_course_chunks(db, course_id, req.question)
        await service.log_tool_call_json(
            run.id,
            "retrieve_course_chunks",
            {"course_id": course_id, "question": req.question, "threshold": 0.18, "max_citations": 5},
            {"hit_count": len(citations), "citations": citations},
        )

        if not citations:
            latency = int((time.time() - start) * 1000)
            answer = "当前课程资料无法支持该问题"
            await service.log_qa(course_id=course_id, user_id=user.id,
                question=req.question,
                answer=answer,
                confidence=0.0, latency_ms=latency)
            await service.complete_run(run.id, output_summary=answer, latency_ms=latency)
            return ApiResponse.ok(data=QAResponse(
                answer=answer,
                citations=[],
                confidence=0.0,
                needs_clarification=True,
                run_id=run.id,
            ))

        context = _build_rag_context(citations)
        try:
            llm = get_llm(temperature=0.3)
            prompt = f"""你是课程资料问答助手。只能依据给定资料回答，不要使用课程简介或外部知识。
如果给定资料不能支持回答，请只回答：当前课程资料无法支持该问题

资料：
{context}

问题：{req.question}

请用中文回答，并尽量点明引用的资料编号。"""
            llm_start = time.time()
            response = await llm.ainvoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
            await service.log_tool_call_json(
                run.id,
                "llm_answer",
                {"question": req.question, "context_count": len(citations)},
                {"answer": answer},
                latency_ms=int((time.time() - llm_start) * 1000),
            )
        except Exception as e:
            answer = "根据当前课程资料：\n" + "\n".join(
                f"{idx}. {item['content'][:220]}" for idx, item in enumerate(citations[:3], 1)
            )
            await service.log_tool_call_json(
                run.id,
                "llm_answer",
                {"question": req.question, "context_count": len(citations)},
                {"fallback_answer": answer},
                error=str(e),
            )

        latency = int((time.time() - start) * 1000)
        await service.log_qa(course_id=course_id, user_id=user.id,
            question=req.question, answer=answer,
            citations=json.dumps(citations, ensure_ascii=False),
            confidence=citations[0]["similarity"] if citations else 0, latency_ms=latency)
        await service.complete_run(run.id, output_summary=answer[:500], latency_ms=latency)

        return ApiResponse.ok(data=QAResponse(
            answer=answer, citations=citations,
            confidence=citations[0]["similarity"] if citations else 0,
            needs_clarification=False,
            run_id=run.id,
        ))
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        await service.fail_run(run.id, error=str(e), latency_ms=latency)
        return ApiResponse.error(message=f"AI 问答失败: {str(e)}", code=500)


@router.post("/agent/chat")
async def agent_chat(
    req: AgentChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """统一 Agent 对话：RAG、业务 API、综合建议、校园学习问答。"""
    question = req.question.strip()
    course_id = req.course_id
    mode = req.mode
    mode_config = AGENT_MODE_CONFIG[mode]
    memory = await _collect_agent_memory(db, user, course_id)
    service = AiToolService(db)
    start = time.time()
    run = await service.create_run(
        user_id=user.id,
        role=user.role,
        workflow="agent_chat",
        input_summary=f"{mode}: {question[:120]}",
    )

    business_context: Optional[Dict[str, Any]] = None
    citations: List[Dict[str, Any]] = []
    confidence = 0.0

    try:
        if mode_config["needs_business"]:
            tool_start = time.time()
            business_context = await _collect_agent_business_context(db, user, course_id)
            await service.log_tool_call_json(
                run.id,
                "business_api_context",
                {"course_id": course_id, "role": user.role},
                business_context,
                latency_ms=int((time.time() - tool_start) * 1000),
            )

        if mode_config["needs_rag"] and course_id:
            await _ensure_course_access(db, course_id, user)
            tool_start = time.time()
            citations = await _search_course_chunks(db, course_id, question)
            confidence = citations[0]["similarity"] if citations else 0.0
            await service.log_tool_call_json(
                run.id,
                "retrieve_course_chunks",
                {"course_id": course_id, "question": question, "threshold": 0.18, "max_citations": 5},
                {"hit_count": len(citations), "citations": citations},
                latency_ms=int((time.time() - tool_start) * 1000),
            )
        elif mode == "course_material" and not course_id:
            answer = "请先选择一门课程，再提问课程资料相关问题。"
            latency = int((time.time() - start) * 1000)
            await service.log_qa(
                course_id=0,
                user_id=user.id,
                question=question,
                answer=answer,
                citations="[]",
                confidence=0.0,
                latency_ms=latency,
            )
            await service.complete_run(run.id, output_summary=answer, latency_ms=latency)
            return ApiResponse.ok(data=AgentChatResponse(
                answer=answer,
                mode=mode,
                citations=[],
                confidence=0.0,
                run_id=run.id,
                memory_count=len(memory),
            ))

        if mode == "course_material" and not citations:
            answer = "当前课程资料无法支持该问题。你可以先让教师索引课程资料，或换一个更贴近已上传资料的问题。"
        else:
            rag_context = _build_rag_context(citations) if citations else "无"
            api_context = _json_context(business_context or {}) if business_context else "无"
            try:
                llm = get_llm(temperature=0.25)
                memory_context = _build_agent_memory_context(memory)
                prompt = f"""你是 EduAgent 的校园学习对话助手。你正在和一名{('学生' if user.role == 'STUDENT' else '教师')}连续对话。
当前对话类型：{mode_config['label']}。

回答规则：
1. 直接回答当前问题，不要让用户重新解释已经在历史对话中说明过的内容。
2. 保持自然对话风格：先给结论，再给必要的解释或步骤；信息不足时只追问最关键的一点。
3. 课程资料类问题优先依据 RAG_CONTEXT；作业提交类问题优先依据 BUSINESS_API_CONTEXT。
4. 教学建议可以结合课程资料、教学数据和历史对话，但不能编造系统中没有的数据。
5. 其他问题可以直接回答；不要假装实时联网，也不要声称查到了互联网最新信息。
6. 历史对话只用于理解用户偏好、学习目标和上下文；若与当前业务数据冲突，以当前业务数据为准。

当前问题：
{question}

历史对话记忆：
{memory_context}

业务数据：
{api_context}

课程资料：
{rag_context}

请用中文回答，像一位耐心、连续跟进的老师，保持具体、简洁、可执行。"""
                llm_start = time.time()
                response = await llm.ainvoke(prompt)
                answer = response.content if hasattr(response, "content") else str(response)
                await service.log_tool_call_json(
                    run.id,
                    "llm_answer",
                    {"mode": mode, "question": question},
                    {"answer": answer},
                    latency_ms=int((time.time() - llm_start) * 1000),
                )
            except Exception as e:
                answer = _fallback_agent_answer(question, mode, business_context, citations)
                await service.log_tool_call_json(
                    run.id,
                    "llm_answer",
                    {"mode": mode, "question": question},
                    {"fallback_answer": answer},
                    error=str(e),
                )

        latency = int((time.time() - start) * 1000)
        await service.log_qa(
            course_id=course_id or 0,
            user_id=user.id,
            question=question,
            answer=answer,
            citations=json.dumps(citations, ensure_ascii=False),
            confidence=confidence,
            latency_ms=latency,
        )
        await service.complete_run(run.id, output_summary=answer[:500], latency_ms=latency)
        return ApiResponse.ok(data=AgentChatResponse(
            answer=answer,
            mode=mode,
            citations=citations,
            confidence=confidence,
            run_id=run.id,
            memory_count=len(memory),
        ))
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        await service.fail_run(run.id, error=str(e), latency_ms=latency)
        return ApiResponse.error(message=f"Agent 对话失败: {str(e)}", code=500)


@router.post("/students/{student_id}/diagnosis")
async def diagnose_student(
    student_id: int,
    course_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """学情诊断"""
    await _ensure_student_ai_access(db, student_id, user, course_id)
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
    await _ensure_student_ai_access(db, student_id, user, course_id)
    service = AiToolService(db)
    start = time.time()
    run = None

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
            "run_id": run.id,
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
        weakness_data = final_report.get("weakness", {})
        return ApiResponse.ok(data=LearningPlanResponse(
            student_id=student_id,
            course_id=course_id,
            weakness_summary=plan_data.get("weakness_summary", ""),
            daily_tasks=plan_data.get("daily_tasks", []),
            materials=plan_data.get("materials", []),
            exercises=final_report.get("exercises") or [],
            total_hours=plan_data.get("total_hours", 0),
            plan_id=final_report.get("report_id"),
            run_id=run.id,
            basis=[
                {"name": "成绩记录", "value": weakness_data.get("graded_count", 0)},
                {"name": "薄弱点", "value": len(weakness_data.get("weakness_areas", []))},
                {"name": "课程资料", "value": len(result.get("retrieved_materials") or [])},
            ],
        ))

    except Exception as e:
        if run is not None:
            await service.fail_run(run.id, error=str(e), latency_ms=int((time.time() - start) * 1000))
        return ApiResponse.error(message=f"生成学习计划失败: {str(e)}", code=500)


@router.post("/me/learning-plan")
async def generate_my_learning_plan(
    course_id: int = Query(..., description="课程 ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前学生重新生成学习计划。"""
    if user.role != "STUDENT":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students can use this endpoint")
    return await generate_learning_plan(
        student_id=user.id,
        course_id=course_id,
        user=user,
        db=db,
    )


@router.post("/teacher/submissions/{submission_id}/grade-suggestion")
async def grade_suggestion(
    submission_id: int,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """AI 批改建议（LangGraph Agent）"""
    await _ensure_teacher_submission_access(db, submission_id, user)
    service = AiToolService(db)
    start = time.time()
    run = None

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
            "run_id": run.id,
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
            "suggestion_id": None,
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
            id=result.get("suggestion_id"),
            run_id=run.id,
            submission_id=submission_id,
            suggested_score=result.get("suggested_score", 0),
            rubric=result.get("rubric", {}),
            comment=result.get("comment", ""),
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            risks=result.get("risks", []),
        ))

    except Exception as e:
        if run is not None:
            await service.fail_run(run.id, error=str(e), latency_ms=int((time.time() - start) * 1000))
        return ApiResponse.error(message=f"生成批改建议失败: {str(e)}", code=500)


@router.get("/runs/{run_id}", include_in_schema=False)
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


@router.get("/runs/{run_id}/tool-calls", include_in_schema=False)
async def get_run_tool_calls(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查看 Agent 工具调用轨迹。"""
    service = AiToolService(db)
    detail = await service.get_run_detail(run_id)
    if detail is None:
        return ApiResponse.error(message="运行记录不存在", code=404)
    if detail["user_id"] != user.id and user.role != "ADMIN":
        return ApiResponse.error(message="无权查看此运行记录", code=403)
    calls = await service.get_tool_calls(run_id)
    return ApiResponse.ok(data=calls)


@router.post("/feedback/{suggestion_id}/approve")
async def approve_feedback(
    suggestion_id: int,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """教师采用 AI 批改建议。"""
    suggestion = await _ensure_teacher_feedback_access(db, suggestion_id, user)
    teacher_service = TeacherService(db)
    grade = GradeRequest(score=suggestion.suggested_score, comment=suggestion.comment or "")
    await teacher_service.grade_submission(suggestion.submission_id, grade, user)
    suggestion.teacher_action = "ACCEPTED"
    suggestion.teacher_score = suggestion.suggested_score
    await db.flush()
    return ApiResponse.ok(data={
        "id": suggestion.id,
        "submission_id": suggestion.submission_id,
        "teacher_action": suggestion.teacher_action,
        "teacher_score": suggestion.teacher_score,
    }, message="AI 建议已采用")


@router.put("/feedback/{suggestion_id}")
async def update_feedback(
    suggestion_id: int,
    req: FeedbackUpdateRequest,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """教师修改或拒绝 AI 批改建议。"""
    suggestion = await _ensure_teacher_feedback_access(db, suggestion_id, user)
    action = req.action or "MODIFIED"

    if action == "REJECTED":
        suggestion.teacher_action = "REJECTED"
        await db.flush()
        return ApiResponse.ok(data={
            "id": suggestion.id,
            "submission_id": suggestion.submission_id,
            "teacher_action": suggestion.teacher_action,
        }, message="AI 建议已拒绝")

    final_score = req.score if req.score is not None else suggestion.suggested_score
    final_comment = req.comment if req.comment is not None else (suggestion.comment or "")
    if req.rubric is not None:
        suggestion.rubric_json = json.dumps(req.rubric, ensure_ascii=False)
    suggestion.comment = final_comment
    suggestion.teacher_action = "MODIFIED"
    suggestion.teacher_score = final_score

    teacher_service = TeacherService(db)
    await teacher_service.grade_submission(
        suggestion.submission_id,
        GradeRequest(score=final_score, comment=final_comment),
        user,
    )
    await db.flush()
    return ApiResponse.ok(data={
        "id": suggestion.id,
        "submission_id": suggestion.submission_id,
        "teacher_action": suggestion.teacher_action,
        "teacher_score": suggestion.teacher_score,
    }, message="AI 建议已修改并应用")


@router.post("/feedback/{suggestion_id}/regenerate")
async def regenerate_feedback(
    suggestion_id: int,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """基于同一提交重新生成 AI 批改建议，保留旧历史。"""
    suggestion = await _ensure_teacher_feedback_access(db, suggestion_id, user)
    return await grade_suggestion(suggestion.submission_id, user=user, db=db)
