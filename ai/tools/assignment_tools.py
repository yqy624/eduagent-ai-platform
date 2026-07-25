"""作业读取工具（Agent 可用）"""
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Assignment, Submission, PeerReview


class AssignmentTools:
    """Agent 可调用的作业相关工具"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_assignment(self, assignment_id: int) -> Optional[Dict[str, Any]]:
        """获取作业详情"""
        result = await self.db.execute(
            select(Assignment).where(Assignment.id == assignment_id)
        )
        a = result.scalar_one_or_none()
        if a is None:
            return None
        return {
            "id": a.id,
            "course_id": a.course_id,
            "title": a.title,
            "description": a.description,
            "due_date": a.due_date.isoformat() if a.due_date else None,
            "total_points": a.total_points,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }

    async def get_course_assignments(self, course_id: int) -> List[Dict[str, Any]]:
        """获取课程所有作业"""
        result = await self.db.execute(
            select(Assignment)
            .where(Assignment.course_id == course_id)
            .order_by(Assignment.created_at.desc())
        )
        assignments = list(result.scalars().all())
        return [
            {
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "total_points": a.total_points,
            }
            for a in assignments
        ]

    async def get_student_submissions(
        self, student_id: int, course_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取学生的提交记录"""
        query = select(Submission).where(Submission.student_id == student_id)
        if course_id:
            query = query.where(
                Submission.assignment_id.in_(
                    select(Assignment.id).where(Assignment.course_id == course_id)
                )
            )
        result = await self.db.execute(query)
        submissions = list(result.scalars().all())
        return [
            {
                "id": s.id,
                "assignment_id": s.assignment_id,
                "content": s.content,
                "score": s.score,
                "status": s.status,
                "submitted_at": s.submitted_at.isoformat()
                if s.submitted_at else None,
            }
            for s in submissions
        ]

    async def get_peer_reviews_for_submission(
        self, submission_id: int
    ) -> List[Dict[str, Any]]:
        """获取某个提交收到的互评"""
        result = await self.db.execute(
            select(PeerReview).where(
                PeerReview.target_submission_id == submission_id,
                PeerReview.status == "SUBMITTED",
            )
        )
        reviews = list(result.scalars().all())
        return [
            {
                "id": r.id,
                "rating": r.rating,
                "comment": r.comment,
            }
            for r in reviews
        ]
