"""
AI 辅助数据表 — 在 student_db 外新增的旁路表
原业务表保持兼容，AI 相关数据使用 ai_* 前缀
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Float, DateTime,
    Boolean, JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AiDocumentChunk(Base):
    """课程文档切片元数据"""
    __tablename__ = "ai_document_chunks"
    __table_args__ = (
        Index("idx_ai_doc_course", "course_id"),
        Index("idx_ai_doc_file", "file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[Optional[str]] = mapped_column(Text)  # 切片文本内容
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(255))  # 文件名或路径
    source_type: Mapped[str] = mapped_column(String(50), default="pdf")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiIndexJob(Base):
    """文档索引任务"""
    __tablename__ = "ai_index_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    course_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING"
    )  # PENDING, RUNNING, COMPLETED, FAILED
    total_chunks: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiRun(Base):
    """Agent 运行主记录"""
    __tablename__ = "ai_runs"
    __table_args__ = (
        Index("idx_ai_run_user", "user_id"),
        Index("idx_ai_run_workflow", "workflow"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(20))
    workflow: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), default="RUNNING"
    )  # RUNNING, COMPLETED, FAILED, CANCELLED
    input_summary: Mapped[Optional[str]] = mapped_column(Text)
    output_summary: Mapped[Optional[str]] = mapped_column(Text)
    plan_json: Mapped[Optional[str]] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    token_usage: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiToolCall(Base):
    """工具调用追踪"""
    __tablename__ = "ai_tool_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ai_runs.id"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(100))
    input_json: Mapped[Optional[str]] = mapped_column(Text)
    output_json: Mapped[Optional[str]] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiAgentMemory(Base):
    """Durable memory used by the controlled Agent runtime."""
    __tablename__ = "ai_agent_memories"
    __table_args__ = (
        Index("idx_ai_memory_user_session", "user_id", "session_id"),
        Index("idx_ai_memory_user_course", "user_id", "course_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    course_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(30), default="interaction")
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiQaLog(Base):
    """RAG 问答日志"""
    __tablename__ = "ai_qa_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[Optional[str]] = mapped_column(Text)
    citations_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiLearningReport(Base):
    """学情诊断报告"""
    __tablename__ = "ai_learning_reports"
    __table_args__ = (
        Index("idx_ai_report_student", "student_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    course_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("ai_runs.id"))
    weakness_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    plan_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiGradingSuggestion(Base):
    """批改建议"""
    __tablename__ = "ai_grading_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("submissions.id"), nullable=False
    )
    run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("ai_runs.id"))
    suggested_score: Mapped[float] = mapped_column(Float)
    rubric_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    comment: Mapped[Optional[str]] = mapped_column(Text)
    strengths: Mapped[Optional[str]] = mapped_column(Text)
    weaknesses: Mapped[Optional[str]] = mapped_column(Text)
    teacher_action: Mapped[Optional[str]] = mapped_column(
        String(20)
    )  # PENDING, ACCEPTED, MODIFIED, REJECTED
    teacher_score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AiEvalResult(Base):
    """离线评测结果"""
    __tablename__ = "ai_eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    eval_name: Mapped[str] = mapped_column(String(100))
    case_id: Mapped[str] = mapped_column(String(100))
    metric_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    passed: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[Optional[float]] = mapped_column(Float)
    details: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
