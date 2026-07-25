"""管理员服务 — 返回前端兼容的 camelCase 字段"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Assignment,
    AuditLog,
    Course,
    Enrollment,
    PublishedActivity,
    Submission,
    User,
)
from app.schemas.auth import RegisterRequest, UserResponse
from app.middleware.auth import hash_password


class AdminService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard(self) -> Dict[str, Any]:
        """返回管理仪表盘数据"""
        total_users = (await self.db.execute(select(func.count(User.id)))).scalar() or 0
        total_teachers = (await self.db.execute(select(func.count(User.id)).where(User.role == "TEACHER"))).scalar() or 0
        total_students = (await self.db.execute(select(func.count(User.id)).where(User.role == "STUDENT"))).scalar() or 0
        total_courses = (await self.db.execute(select(func.count(Course.id)))).scalar() or 0
        total_enrollments = (await self.db.execute(select(func.count(Enrollment.id)))).scalar() or 0
        week_ago = datetime.now() - timedelta(days=7)
        weekly_new_courses = (await self.db.execute(select(func.count(Course.id)).where(Course.created_at >= week_ago))).scalar() or 0
        weekly_new_users = (await self.db.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )).scalar() or 0

        # 热门课程 Top5
        top_courses_raw = await self.db.execute(
            select(Course.name, User.display_name, Course.enrolled_count)
            .outerjoin(User, Course.teacher_id == User.id)
            .order_by(Course.enrolled_count.desc())
            .limit(5)
        )
        top_courses = [
            {"name": row[0], "teacher": row[1] or "未知", "value": row[2] or 0}
            for row in top_courses_raw
        ]

        # 角色分布
        role_data = await self.db.execute(
            select(User.role, func.count(User.id))
            .group_by(User.role)
        )
        role_distribution = [
            {"name": {"ADMIN": "管理员", "TEACHER": "教师", "STUDENT": "学生"}.get(row[0], row[0]),
             "value": row[1]}
            for row in role_data
        ]

        # 近期活动
        activities_raw = await self.db.execute(
            select(PublishedActivity)
            .order_by(PublishedActivity.created_at.desc())
            .limit(10)
        )
        activities = [
            {
                "id": a.id, "title": a.title, "content": a.content,
                "audience": a.audience, "status": a.status,
                "createdBy": a.created_by or "系统",
                "createdAt": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities_raw.scalars().all()
        ]

        # 待办事项
        pending_submissions = (await self.db.execute(
            select(func.count(Submission.id)).where(Submission.status == "SUBMITTED")
        )).scalar() or 0

        todo_items = []
        if pending_submissions > 0:
            todo_items.append({"key": "submissions", "value": pending_submissions, "tab": "courses"})

        return {
            "total_users": total_users,
            "total_students": total_students,
            "total_teachers": total_teachers,
            "total_courses": total_courses,
            "total_enrollments": total_enrollments,
            "today_active_users": 0,
            "weekly_new_courses": weekly_new_courses,
            "weekly_new_users": weekly_new_users,
            "pending_review_count": pending_submissions,
            "todo_items": todo_items,
            "top_courses": top_courses,
            "recent_visits": [],
            "role_distribution": role_distribution,
            "activities": activities,
        }

    async def list_users(
        self, role: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """返回前端兼容的用户列表"""
        query = select(User)
        if role:
            query = query.where(User.role == role)
        query = query.order_by(User.id).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        users = list(result.scalars().all())

        count_query = select(func.count(User.id))
        if role:
            count_query = count_query.where(User.role == role)
        total = (await self.db.execute(count_query)).scalar() or 0

        return {
            "content": [
                {
                    "id": u.id,
                    "username": u.username,
                    "displayName": u.display_name,
                    "email": u.email,
                    "role": u.role,
                    "enabled": u.enabled,
                    "lastLogin": u.last_login.isoformat() if u.last_login else None,
                    "createdAt": u.created_at.isoformat() if u.created_at else None,
                }
                for u in users
            ],
            "totalElements": total,
            "number": page - 1,
            "size": page_size,
            "totalPages": (total + page_size - 1) // page_size,
        }

    async def create_user(self, req: RegisterRequest) -> UserResponse:
        result = await self.db.execute(
            select(User).where(User.username == req.username)
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("用户名已存在")
        if req.role not in ("ADMIN", "TEACHER", "STUDENT"):
            raise ValueError("无效角色")
        user = User(
            username=req.username, password=hash_password(req.password),
            display_name=req.display_name or req.username,
            email=req.email, role=req.role, enabled=True,
            created_at=datetime.now(),
        )
        self.db.add(user)
        await self.db.flush()
        return UserResponse(
            id=user.id, username=user.username,
            display_name=user.display_name,
            email=user.email, role=user.role,
            enabled=user.enabled,
            created_at=user.created_at.isoformat() if user.created_at else None,
        )

    async def toggle_user_enabled(self, user_id: int) -> bool:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        user.enabled = not user.enabled
        await self.db.flush()
        return user.enabled

    async def get_audit_logs(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        query = select(AuditLog).order_by(AuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        logs = list(result.scalars().all())
        total = (await self.db.execute(select(func.count(AuditLog.id)))).scalar() or 0
        return {
            "content": [
                {"id": log.id, "action": log.action, "details": log.details,
                 "username": log.username, "role": log.role,
                 "ipAddress": log.ip_address, "timestamp": log.timestamp.isoformat() if log.timestamp else None}
                for log in logs
            ],
            "totalElements": total,
            "number": page - 1,
            "size": page_size,
            "totalPages": (total + page_size - 1) // page_size,
        }

    async def list_courses(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        query = select(Course).order_by(Course.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        courses = list(result.scalars().all())
        total = (await self.db.execute(select(func.count(Course.id)))).scalar() or 0

        items = []
        for c in courses:
            t = (await self.db.execute(select(User).where(User.id == c.teacher_id))).scalar_one_or_none()
            items.append({
                "id": c.id, "name": c.name,
                "teacher": t.display_name or t.username if t else None,
                "enrolledCount": c.enrolled_count, "maxStudents": c.max_students,
                "visible": c.visible, "credits": c.credits,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
            })
        return {
            "content": items,
            "totalElements": total,
            "number": page - 1,
            "size": page_size,
            "totalPages": (total + page_size - 1) // page_size,
        }

    async def create_activity(self, title: str, content: str, audience: str, created_by: str) -> PublishedActivity:
        activity = PublishedActivity(title=title, content=content, audience=audience,
                                      status="PUBLISHED", created_by=created_by,
                                      created_at=datetime.now(), published_at=datetime.now())
        self.db.add(activity)
        await self.db.flush()
        return activity
