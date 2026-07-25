"""AI 相关 Schema"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """RAG 问答请求"""
    question: str = Field(..., min_length=1, max_length=2000)


class Citation(BaseModel):
    """引用来源"""
    chunk_index: Optional[int] = 0
    content: str
    score: float
    source: str
    file_name: Optional[str] = None


class QAResponse(BaseModel):
    answer: str
    citations: List[Citation] = []
    confidence: float
    needs_clarification: bool = False


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


class GradingSuggestionResponse(BaseModel):
    """AI 批改建议"""
    submission_id: int
    suggested_score: float
    rubric: Dict[str, Any] = {}
    comment: str
    strengths: List[str] = []
    weaknesses: List[str] = []
    risks: List[str] = []


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
