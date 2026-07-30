"""成绩查询工具（Agent 可用）"""
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Assignment,
    Course,
    Enrollment,
    Submission,
    PeerReview,
    User,
)


class GradeTools:
    """Agent 可调用的成绩相关工具"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_student_grades(self, student_id: int) -> List[Dict[str, Any]]:
        """获取学生所有成绩"""
        result = await self.db.execute(
            select(Submission).where(Submission.student_id == student_id)
        )
        submissions = list(result.scalars().all())
        grades = []
        for sub in submissions:
            if sub.score is not None:
                ass = await self.db.execute(
                    select(Assignment).where(Assignment.id == sub.assignment_id)
                )
                assignment = ass.scalar_one_or_none()
                grades.append({
                    "assignment_id": sub.assignment_id,
                    "assignment_title": assignment.title if assignment else None,
                    "score": sub.score,
                    "total_points": assignment.total_points if assignment else 100,
                    "status": sub.status,
                    "submitted_at": sub.submitted_at.isoformat()
                    if sub.submitted_at else None,
                })
        return grades

    async def get_course_grades(
        self, student_id: int, course_id: int
    ) -> List[Dict[str, Any]]:
        """获取学生在某门课程的成绩"""
        result = await self.db.execute(
            select(Submission).where(
                Submission.student_id == student_id,
                Submission.assignment_id.in_(
                    select(Assignment.id).where(Assignment.course_id == course_id)
                ),
            )
        )
        submissions = list(result.scalars().all())
        grades = []
        for sub in submissions:
            ass = await self.db.execute(
                select(Assignment).where(Assignment.id == sub.assignment_id)
            )
            assignment = ass.scalar_one_or_none()
            grades.append({
                "assignment_id": sub.assignment_id,
                "assignment_title": assignment.title if assignment else None,
                "score": sub.score,
                "total_points": assignment.total_points if assignment else 100,
                "status": sub.status,
            })
        return grades

    async def get_course_average(self, course_id: int) -> Optional[float]:
        """获取课程平均分"""
        result = await self.db.execute(
            select(func.avg(Submission.score)).where(
                Submission.status == "GRADED",
                Submission.score.isnot(None),
                Submission.assignment_id.in_(
                    select(Assignment.id).where(Assignment.course_id == course_id)
                ),
            )
        )
        val = result.scalar()
        return float(val) if val is not None else None

    async def get_low_score_assignments(
        self, student_id: int, threshold: float = 60.0
    ) -> List[Dict[str, Any]]:
        """获取低分作业（薄弱点识别）"""
        grades = await self.get_student_grades(student_id)
        low = [
            g for g in grades
            if g["score"] is not None
            and (g["score"] / g["total_points"] * 100) < threshold
        ]
        return low

    async def get_submission_detail(self, submission_id: int) -> Optional[Dict[str, Any]]:
        """获取提交详情"""
        result = await self.db.execute(
            select(Submission).where(Submission.id == submission_id)
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            return None
        return {
            "id": sub.id,
            "assignment_id": sub.assignment_id,
            "content": sub.content,
            "file_name": sub.file_name,
            "file_paths": sub.file_paths,
            "score": sub.score,
            "status": sub.status,
            "teacher_comment": sub.teacher_comment,
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
        }
