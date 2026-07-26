"""AI 相关 Schema"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """RAG 问答请求"""
    question: str = Field(..., min_length=1, max_length=2000)


class Citation(BaseModel):
    """引用来源"""
    document_id: Optional[int] = None
    chunk_index: Optional[int] = 0
    content: str
    score: float
    similarity: Optional[float] = None
    source: str
    file_name: Optional[str] = None


class QAResponse(BaseModel):
    answer: str
    citations: List[Citation] = []
    confidence: float
    needs_clarification: bool = False
    run_id: Optional[int] = None


class AgentChatRequest(BaseModel):
    """Agent 对话请求"""
    question: str = Field(..., min_length=1, max_length=2000)
    course_id: Optional[int] = None
    mode: str = Field(
        default="other",
        pattern="^(course_material|assignment_submission|teaching_advice|other)$",
    )


class AgentChatResponse(BaseModel):
    """Agent 对话响应"""
    answer: str
    mode: str
    citations: List[Citation] = []
    confidence: float = 0.0
    run_id: Optional[int] = None
    memory_count: int = 0


class DiagnosisResponse(BaseModel):
    """学情诊断结果"""
    student_id: int
    course_id: int
    weakness: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    trend: Optional[str] = None


class LearningPlanResponse(BaseModel):
    """学习计划"""
    student_id: int
    course_id: int
    weakness_summary: str
    daily_tasks: List[Dict[str, Any]] = []
    materials: List[str] = []
    exercises: List[Dict[str, Any]] = []
    total_hours: float = 0
    plan_id: Optional[int] = None
    run_id: Optional[int] = None
    basis: List[Dict[str, Any]] = []


class GradingSuggestionResponse(BaseModel):
    """AI 批改建议"""
    id: Optional[int] = None
    run_id: Optional[int] = None
    submission_id: int
    suggested_score: float
    rubric: Dict[str, Any] = {}
    comment: str
    strengths: List[str] = []
    weaknesses: List[str] = []
    risks: List[str] = []


class FeedbackUpdateRequest(BaseModel):
    score: Optional[float] = Field(None, ge=0)
    comment: Optional[str] = None
    rubric: Optional[Dict[str, Any]] = None
    action: Optional[str] = Field(None, pattern="^(MODIFIED|REJECTED)$")


class AgentRunResponse(BaseModel):
    """Agent 运行记录"""
    id: int
    user_id: int
    role: str
    workflow: str
    status: str
    latency_ms: int
    token_usage: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = []
