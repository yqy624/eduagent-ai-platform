"""课程服务"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Assignment, Course, User, Enrollment
from app.schemas.assignment import CourseCreate, CourseUpdate, CourseResponse
from app.services.notification_service import NotificationService


class CourseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, course_id: int) -> Optional[Course]:
        result = await self.db.execute(
            select(Course).where(Course.id == course_id)
        )
        return result.scalar_one_or_none()

    async def create(self, req: CourseCreate, teacher: User) -> Course:
        course = Course(
            name=req.name,
            description=req.description,
            schedule=req.schedule,
            credits=req.credits,
            max_students=req.max_students,
            category=req.category,
            teacher_id=teacher.id,
            enrolled_count=0,
            visible=True,
            created_at=datetime.now(),
        )
        self.db.add(course)
        await self.db.flush()
        await NotificationService(self.db).create_for_roles(
            ["STUDENT"],
            "新课程已发布",
            f"课程《{course.name}》已开放选课。",
            category="COURSE",
            type_="INFO",
            link=f"/static/student/dashboard.html#course-{course.id}",
        )
        return course

    async def update(
        self, course_id: int, req: CourseUpdate, teacher: User
    ) -> Course:
        course = await self.get_by_id(course_id)
        if course is None:
            raise ValueError("课程不存在")
        if course.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权修改此课程")

        was_visible = bool(course.visible)
        update_data = req.model_dump(exclude_none=True)
        if "max_students" in update_data and update_data["max_students"] < course.enrolled_count:
            raise ValueError("课程容量不能小于当前选课人数")
        for key, value in update_data.items():
            setattr(course, key, value)
        await self.db.flush()
        if not was_visible and course.visible:
            await NotificationService(self.db).create_for_roles(
                ["STUDENT"],
                "课程重新上架",
                f"课程《{course.name}》已重新开放。",
                category="COURSE",
                type_="INFO",
                link=f"/static/student/dashboard.html#course-{course.id}",
            )
        return course

    async def delete(self, course_id: int, teacher: User):
        course = await self.get_by_id(course_id)
        if course is None:
            raise ValueError("课程不存在")
        if course.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权删除此课程")

        enrollment_count = (
            await self.db.execute(
                select(func.count(Enrollment.id)).where(Enrollment.course_id == course_id)
            )
        ).scalar() or 0
        assignment_count = (
            await self.db.execute(
                select(func.count(Assignment.id)).where(Assignment.course_id == course_id)
            )
        ).scalar() or 0
        if enrollment_count or assignment_count:
            course.visible = False
        else:
            await self.db.delete(course)
        await self.db.flush()

    async def get_teacher_courses(self, teacher_id: int) -> List[Course]:
        result = await self.db.execute(
            select(Course).where(
                Course.teacher_id == teacher_id,
                Course.visible == True,
            )
        )
        return list(result.scalars().all())

    async def get_all_visible(self) -> List[Course]:
        result = await self.db.execute(
            select(Course).where(Course.visible == True)
        )
        courses = list(result.scalars().all())
        # 填充教师名称
        for c in courses:
            if c.teacher_id:
                tr = await self.db.execute(
                    select(User).where(User.id == c.teacher_id)
                )
                teacher = tr.scalar_one_or_none()
                if teacher:
                    c.teacher_name = teacher.display_name or teacher.username
        return courses

    async def get_student_courses(self, student_id: int) -> List[Course]:
        result = await self.db.execute(
            select(Course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .where(Enrollment.student_id == student_id)
        )
        return list(result.scalars().all())

    async def to_response(self, course: Course) -> CourseResponse:
        teacher_name = None
        if course.teacher_id:
            tr = await self.db.execute(
                select(User).where(User.id == course.teacher_id)
            )
            t = tr.scalar_one_or_none()
            if t:
                teacher_name = t.display_name or t.username
        return CourseResponse(
            id=course.id,
            name=course.name,
            description=course.description,
            schedule=course.schedule,
            credits=course.credits,
            max_students=course.max_students,
            enrolled_count=course.enrolled_count,
            teacher_id=course.teacher_id,
            teacher_name=teacher_name,
            category=course.category,
            visible=course.visible,
            created_at=course.created_at.isoformat() if course.created_at else None,
        )
