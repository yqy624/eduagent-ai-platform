"""
SQLAlchemy 模型 — 映射 student_db 所有表
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Float, DateTime,
    Boolean, Enum, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# ============================================================
# 用户
# ============================================================
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    display_name: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(Enum("ADMIN", "TEACHER", "STUDENT"))
    username: Mapped[str] = mapped_column(String(50), unique=True)

    # 关系
    courses_taught: Mapped[List["Course"]] = relationship(back_populates="teacher")
    enrollments: Mapped[List["Enrollment"]] = relationship(
        back_populates="student", foreign_keys="[Enrollment.student_id]"
    )
    submissions: Mapped[List["Submission"]] = relationship(back_populates="student")


# ============================================================
# 课程
# ============================================================
class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    credits: Mapped[int] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    enrolled_count: Mapped[int] = mapped_column(Integer, default=0)
    max_students: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    schedule: Mapped[Optional[str]] = mapped_column(String(50))
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    visible: Mapped[bool] = mapped_column(Boolean, default=True)

    # 关系
    teacher: Mapped["User"] = relationship(back_populates="courses_taught")
    enrollments: Mapped[List["Enrollment"]] = relationship(back_populates="course")
    assignments: Mapped[List["Assignment"]] = relationship(back_populates="course")


# ============================================================
# 选课
# ============================================================
class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    score: Mapped[float] = mapped_column(Float, default=0)
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("courses.id"))
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    base_score: Mapped[float] = mapped_column(Float, default=0)
    peer_review_bonus: Mapped[float] = mapped_column(Float, default=0)

    # 关系
    course: Mapped["Course"] = relationship(back_populates="enrollments")
    student: Mapped["User"] = relationship(
        back_populates="enrollments", foreign_keys=[student_id]
    )


# ============================================================
# 作业
# ============================================================
class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attachment_paths: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    description: Mapped[Optional[str]] = mapped_column(Text)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    title: Mapped[str] = mapped_column(String(200))
    total_points: Mapped[Optional[int]] = mapped_column(Integer)
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("courses.id"))
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    # 互评功能字段
    peer_review_bonus_cap: Mapped[Optional[float]] = mapped_column(Float)
    peer_review_bonus_per_review: Mapped[Optional[float]] = mapped_column(Float)
    peer_review_close_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    peer_review_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    peer_review_open_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    peer_review_prompt: Mapped[Optional[str]] = mapped_column(Text)
    peer_review_required_count: Mapped[Optional[int]] = mapped_column(Integer)

    # 关系
    course: Mapped["Course"] = relationship(back_populates="assignments")
    submissions: Mapped[List["Submission"]] = relationship(back_populates="assignment")
    peer_reviews: Mapped[List["PeerReview"]] = relationship(
        back_populates="assignment", foreign_keys="[PeerReview.assignment_id]"
    )


# ============================================================
# 作业提交
# ============================================================
class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    content: Mapped[Optional[str]] = mapped_column(Text)
    file_name: Mapped[Optional[str]] = mapped_column(String(50))
    file_paths: Mapped[Optional[str]] = mapped_column(String(500))
    graded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    score: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[Optional[str]] = mapped_column(
        Enum("PENDING", "SUBMITTED", "GRADED")
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    teacher_comment: Mapped[Optional[str]] = mapped_column(Text)
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("assignments.id"))
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    # 关系
    assignment: Mapped["Assignment"] = relationship(back_populates="submissions")
    student: Mapped["User"] = relationship(back_populates="submissions")
    peer_reviews_as_target: Mapped[List["PeerReview"]] = relationship(
        back_populates="target_submission",
        foreign_keys="[PeerReview.target_submission_id]",
    )
    teacher_comment_histories: Mapped[List["TeacherCommentUsageHistory"]] = relationship(
        back_populates="submission"
    )


# ============================================================
# 互评
# ============================================================
class PeerReview(Base):
    __tablename__ = "peer_reviews"
    __table_args__ = (
        UniqueConstraint("assignment_id", "reviewer_id", "target_submission_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    bonus_granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[Optional[str]] = mapped_column(
        Enum("ASSIGNED", "SUBMITTED", "BONUS_GRANTED")
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("assignments.id"))
    reviewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    target_submission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("submissions.id")
    )

    # 关系
    assignment: Mapped["Assignment"] = relationship(
        back_populates="peer_reviews", foreign_keys=[assignment_id]
    )
    target_submission: Mapped["Submission"] = relationship(
        back_populates="peer_reviews_as_target", foreign_keys=[target_submission_id]
    )


# ============================================================
# 通知
# ============================================================
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    content: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    link: Mapped[Optional[str]] = mapped_column(String(100))
    is_read: Mapped[Optional[bool]] = mapped_column(Boolean)
    recipient: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[Optional[str]] = mapped_column(String(20))


# ============================================================
# 审计日志
# ============================================================
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(String(500))
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    role: Mapped[Optional[str]] = mapped_column(String(20))
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    username: Mapped[Optional[str]] = mapped_column(String(50))


# ============================================================
# 学生（旧版遗留表）
# ============================================================
class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    age: Mapped[int] = mapped_column(Integer)
    grade: Mapped[float] = mapped_column(Float)


# ============================================================
# 发布活动
# ============================================================
class PublishedActivity(Base):
    __tablename__ = "published_activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audience: Mapped[str] = mapped_column(Enum("ALL", "TEACHERS", "STUDENTS"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    link: Mapped[Optional[str]] = mapped_column(String(255))
    publish_version: Mapped[Optional[int]] = mapped_column(Integer)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    status: Mapped[str] = mapped_column(Enum("DRAFT", "PUBLISHED", "ARCHIVED"))
    title: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))


# ============================================================
# 存储文件
# ============================================================
class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assignment_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    bucket: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(
        Enum("TEMP_UPLOAD", "SUBMISSION_ATTACHMENT", "ASSIGNMENT_ATTACHMENT")
    )
    content_type: Mapped[Optional[str]] = mapped_column(String(120))
    course_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    extension: Mapped[Optional[str]] = mapped_column(String(20))
    object_key: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[Optional[int]] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    submission_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    uploader_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)


# ============================================================
# 教师评语记忆
# ============================================================
class TeacherCommentMemory(Base):
    __tablename__ = "teacher_comment_memories"
    __table_args__ = (
        Index("idx_teacher_comment_teacher_usage", "teacher_id", "usage_count", "last_used_at"),
        Index("idx_teacher_comment_teacher_category", "teacher_id", "category"),
        Index("idx_teacher_comment_teacher_normalized", "teacher_id", "normalized_text"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(
        Enum("ENCOURAGEMENT", "CORRECTION", "SCORE_IMPROVEMENT")
    )
    comment_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    normalized_text: Mapped[str] = mapped_column(String(500))
    usage_count: Mapped[int] = mapped_column(BigInteger, default=0)
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))


# ============================================================
# 教师评语使用历史
# ============================================================
class TeacherCommentUsageHistory(Base):
    __tablename__ = "teacher_comment_usage_history"
    __table_args__ = (
        Index("idx_teacher_comment_usage_teacher_used", "teacher_id", "used_at"),
        Index("idx_teacher_comment_usage_memory_used", "memory_id", "used_at"),
        Index("idx_teacher_comment_usage_submission", "submission_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_snapshot: Mapped[str] = mapped_column(
        Enum("ENCOURAGEMENT", "CORRECTION", "SCORE_IMPROVEMENT")
    )
    comment_snapshot: Mapped[str] = mapped_column(Text)
    score_snapshot: Mapped[Optional[float]] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(Enum("MANUAL", "REUSE"))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(6))
    memory_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("teacher_comment_memories.id")
    )
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submissions.id"))
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    # 关系
    submission: Mapped["Submission"] = relationship(
        back_populates="teacher_comment_histories"
    )
