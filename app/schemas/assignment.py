"""课程、作业相关 Schema"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ===== 课程 =====
class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    schedule: Optional[str] = None
    credits: int = Field(..., ge=0)
    max_students: int = Field(..., ge=1)
    category: Optional[str] = None


class CourseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule: Optional[str] = None
    credits: Optional[int] = None
    max_students: Optional[int] = None
    category: Optional[str] = None
    visible: Optional[bool] = None


class CourseResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    schedule: Optional[str] = None
    credits: int
    max_students: int
    enrolled_count: int
    teacher_id: int
    teacher_name: Optional[str] = None
    category: Optional[str] = None
    visible: bool
    created_at: Optional[str] = None


# ===== 选课 =====
class EnrollmentResponse(BaseModel):
    id: int
    course_id: int
    course_name: Optional[str] = None
    student_id: int
    student_name: Optional[str] = None
    enrolled_at: Optional[str] = None
    score: float


# ===== 作业 =====
class AssignmentCreate(BaseModel):
    course_id: int
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    due_date: Optional[str] = None
    total_points: Optional[int] = None
    attachment_paths: Optional[str] = None
    peer_review_enabled: bool = False
    peer_review_open_at: Optional[str] = None
    peer_review_close_at: Optional[str] = None
    peer_review_required_count: Optional[int] = None
    peer_review_bonus_per_review: Optional[float] = None
    peer_review_bonus_cap: Optional[float] = None
    peer_review_prompt: Optional[str] = None


class AssignmentResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    total_points: Optional[int] = None
    course_id: int
    course_name: Optional[str] = None
    teacher_id: int
    created_at: Optional[str] = None
    peer_review_enabled: bool


# ===== 作业提交 =====
class SubmissionResponse(BaseModel):
    id: int
    assignment_id: int
    assignment_title: Optional[str] = None
    student_id: int
    student_name: Optional[str] = None
    content: Optional[str] = None
    file_name: Optional[str] = None
    file_paths: Optional[str] = None
    status: Optional[str] = None
    score: Optional[float] = None
    teacher_comment: Optional[str] = None
    submitted_at: Optional[str] = None
    graded_at: Optional[str] = None


class SubmissionSubmit(BaseModel):
    content: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None


class GradeRequest(BaseModel):
    score: float = Field(..., ge=0)
    comment: Optional[str] = None


# ===== 互评 =====
class PeerReviewResponse(BaseModel):
    id: int
    assignment_id: int
    reviewer_id: int
    reviewer_name: Optional[str] = None
    target_submission_id: int
    rating: Optional[int] = None
    comment: Optional[str] = None
    status: str
    submitted_at: Optional[str] = None


class PeerReviewSubmit(BaseModel):
    rating: int = Field(..., ge=1, le=10)
    comment: Optional[str] = None


# ===== 仪表盘 =====
class TeacherDashboard(BaseModel):
    total_courses: int
    total_assignments: int
    pending_grading: int
    total_students: int


class StudentDashboard(BaseModel):
    enrolled_courses: int
    pending_assignments: int
    graded_assignments: int
    average_score: Optional[float] = None


class AdminDashboard(BaseModel):
    total_users: int
    total_teachers: int
    total_students: int
    total_courses: int
    total_assignments: int
    total_submissions: int


# ===== 成绩分析 =====
class AssignmentAnalysis(BaseModel):
    assignment_id: int
    title: str
    total_submissions: int
    graded_count: int
    average_score: Optional[float] = None
    max_score: Optional[float] = None
    min_score: Optional[float] = None
    pass_rate: Optional[float] = None
    score_distribution: Optional[Dict[str, int]] = None


class StudentGradeResponse(BaseModel):
    course_id: int
    course_name: Optional[str] = None
    assignments: List[Dict[str, Any]] = []
    course_average: Optional[float] = None
    peer_review_bonus: float = 0
