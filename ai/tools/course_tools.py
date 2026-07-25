"""课程检索工具（Agent 可用）"""
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Assignment, Course, User
from app.services.course_service import CourseService


class CourseTools:
    """Agent 可调用的课程相关工具"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.course_service = CourseService(db)

    async def get_student_courses(self, student_id: int) -> List[Dict[str, Any]]:
        """获取学生已选课程列表"""
        courses = await self.course_service.get_student_courses(student_id)
        return [
            {"id": c.id, "name": c.name, "credits": c.credits, "category": c.category}
            for c in courses
        ]

    async def get_course_info(self, course_id: int) -> Optional[Dict[str, Any]]:
        """获取课程基本信息"""
        course = await self.course_service.get_by_id(course_id)
        if course is None:
            return None
        teacher_name = None
        if course.teacher_id:
            tr = await self.db.execute(
                select(User).where(User.id == course.teacher_id)
            )
            t = tr.scalar_one_or_none()
            teacher_name = t.display_name or t.username if t else None
        return {
            "id": course.id,
            "name": course.name,
            "description": course.description,
            "schedule": course.schedule,
            "credits": course.credits,
            "teacher_name": teacher_name,
            "enrolled_count": course.enrolled_count,
            "max_students": course.max_students,
            "category": course.category,
        }

    async def get_student_context(self, student_id: int, course_id: int) -> Dict[str, Any]:
        """获取学生在某门课程中的完整上下⽂"""
        course = await self.get_course_info(course_id)
        if course is None:
            return {"error": "课程不存在"}
        return {
            "course": course,
            "student_id": student_id,
        }
