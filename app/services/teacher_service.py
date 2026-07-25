"""教师服务 — 返回前端兼容的 camelCase 字段"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Assignment, Course, Enrollment, PeerReview, PublishedActivity, Submission, User,
)
from app.schemas.assignment import CourseCreate, CourseUpdate, GradeRequest
from app.services.assignment_service import AssignmentService
from app.services.course_service import CourseService


class TeacherService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.course_service = CourseService(db)
        self.assignment_service = AssignmentService(db)

    async def get_dashboard(self, teacher: User) -> Dict[str, Any]:
        """返回前端兼容的教师仪表盘"""
        courses = await self.course_service.get_teacher_courses(teacher.id)
        course_ids = [c.id for c in courses]

        total_students = 0
        if course_ids:
            total_students = (await self.db.execute(
                select(func.count(func.distinct(Enrollment.student_id)))
                .where(Enrollment.course_id.in_(course_ids))
            )).scalar() or 0

        # 课程趋势（每门课选课人数）
        course_trend = []
        for c in courses:
            enrolled = (await self.db.execute(
                select(func.count(Enrollment.id)).where(Enrollment.course_id == c.id)
            )).scalar() or 0
            course_trend.append({"name": c.name, "value": enrolled})

        # 近期活动
        activities_raw = await self.db.execute(
            select(PublishedActivity)
            .order_by(PublishedActivity.created_at.desc())
            .limit(10)
        )
        recent_activities = [
            {"title": a.title, "content": a.content, "createdAt": a.created_at.isoformat() if a.created_at else None,
             "publishedAt": a.published_at.isoformat() if a.published_at else None}
            for a in activities_raw.scalars().all()
        ]

        # 已开启互评的作业数
        peer_enabled = (await self.db.execute(
            select(func.count(Assignment.id)).where(
                Assignment.course_id.in_(course_ids),
                Assignment.peer_review_enabled == True,
            )
        )).scalar() or 0

        # 有学生的课程数
        active_courses = 0
        if course_ids:
            active_courses = len(set(
                (await self.db.execute(
                    select(Enrollment.course_id).distinct()
                    .where(Enrollment.course_id.in_(course_ids))
                )).scalars().all()
            ))

        return {
            "total_courses": len(courses),
            "total_students": total_students,
            "peer_enabled_count": peer_enabled,
            "active_courses": active_courses,
            "course_trend": course_trend,
            "recent_activities": recent_activities,
        }

    async def get_my_courses(self, teacher: User) -> List[Dict]:
        courses = await self.course_service.get_teacher_courses(teacher.id)
        result = []
        for c in courses:
            resp = await self.course_service.to_response(c)
            result.append(resp.model_dump())
        return result

    async def create_course(self, req: CourseCreate, teacher: User) -> Dict:
        course = await self.course_service.create(req, teacher)
        resp = await self.course_service.to_response(course)
        return resp.model_dump()

    async def update_course(self, course_id: int, req: CourseUpdate, teacher: User) -> Dict:
        course = await self.course_service.update(course_id, req, teacher)
        resp = await self.course_service.to_response(course)
        return resp.model_dump()

    async def delete_course(self, course_id: int):
        await self.course_service.delete(course_id)

    async def get_course_students(self, course_id: int) -> List[Dict]:
        result = await self.db.execute(
            select(User).join(Enrollment, Enrollment.student_id == User.id)
            .where(Enrollment.course_id == course_id)
        )
        return [
            {"id": s.id, "username": s.username, "display_name": s.display_name, "email": s.email}
            for s in result.scalars().all()
        ]

    async def create_assignment(self, req, teacher: User) -> Dict:
        from app.schemas.assignment import AssignmentCreate
        assignment = await self.assignment_service.create(req if isinstance(req, AssignmentCreate) else AssignmentCreate(**req), teacher)
        return await self._to_assignment_dict(assignment)

    async def get_course_assignments(self, course_id: int) -> List[Dict]:
        assignments = await self.assignment_service.get_course_assignments(course_id)
        return [await self._to_assignment_dict(a) for a in assignments]

    async def get_submissions(self, assignment_id: int) -> List[Dict]:
        submissions = await self.assignment_service.get_submissions(assignment_id)
        return [await self.assignment_service.to_submission_response(s) for s in submissions]

    async def grade_submission(self, submission_id: int, req: GradeRequest, teacher: User) -> Dict:
        submission = await self.assignment_service.grade(submission_id, req, teacher)
        resp = await self.assignment_service.to_submission_response(submission)
        return resp.model_dump()

    async def get_assignment_analysis(self, assignment_id: int) -> Dict:
        return (await self.assignment_service.get_assignment_analysis(assignment_id)).model_dump()

    async def get_peer_review_overview(self, assignment_id: int) -> Dict:
        return await self.assignment_service.get_peer_review_overview(assignment_id)

    async def _to_assignment_dict(self, assignment):
        return {
            "id": assignment.id, "title": assignment.title,
            "description": assignment.description,
            "dueDate": assignment.due_date.isoformat() if assignment.due_date else None,
            "totalPoints": assignment.total_points,
            "courseId": assignment.course_id,
            "teacherId": assignment.teacher_id,
            "createdAt": assignment.created_at.isoformat() if assignment.created_at else None,
            "peerReviewEnabled": assignment.peer_review_enabled,
        }
