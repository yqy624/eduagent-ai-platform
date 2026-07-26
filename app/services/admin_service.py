"""管理员服务 — 返回前端兼容的 camelCase 字段"""
from datetime import datetime, timedelta
import csv
import io
from typing import Any, Dict, List, Optional
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Assignment,
    AuditLog,
    Course,
    Enrollment,
    PeerReview,
    PublishedActivity,
    Submission,
    StoredFile,
    TeacherCommentUsageHistory,
    User,
)
from app.schemas.auth import RegisterRequest, UserResponse
from app.middleware.auth import hash_password
from app.services.notification_service import NotificationService


SERVICE_STARTED_AT = datetime.now()


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
                "teacherId": c.teacher_id,
                "teacher": {
                    "id": t.id,
                    "username": t.username,
                    "displayName": t.display_name or t.username,
                } if t else None,
                "description": c.description,
                "schedule": c.schedule,
                "category": c.category,
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

    async def create_activity(
        self,
        title: str,
        content: str,
        audience: str,
        created_by: str,
        link: Optional[str] = None,
    ) -> PublishedActivity:
        if not title:
            raise ValueError("Activity title is required")
        if not content:
            raise ValueError("Activity content is required")
        if audience not in ("ALL", "TEACHERS", "STUDENTS"):
            raise ValueError("Invalid activity audience")
        activity = PublishedActivity(title=title, content=content, audience=audience,
                                      status="PUBLISHED", created_by=created_by,
                                      created_at=datetime.now(), published_at=datetime.now(),
                                      publish_version=1, link=link)
        self.db.add(activity)
        await self.db.flush()
        await self._notify_activity(activity)
        return activity

    async def list_activities(self, limit: int = 20) -> List[Dict[str, Any]]:
        result = await self.db.execute(
            select(PublishedActivity).order_by(PublishedActivity.created_at.desc()).limit(limit)
        )
        return [self._activity_dict(item) for item in result.scalars().all()]

    async def update_activity(
        self,
        activity_id: int,
        data: Dict[str, Any],
        updated_by: str,
    ) -> PublishedActivity:
        activity = await self._get_activity(activity_id)
        title = str(data.get("title") or "").strip()
        content = str(data.get("content") or "").strip()
        audience = data.get("audience") or activity.audience
        if not title:
            raise ValueError("Activity title is required")
        if not content:
            raise ValueError("Activity content is required")
        if audience not in ("ALL", "TEACHERS", "STUDENTS"):
            raise ValueError("Invalid activity audience")
        activity.title = title
        activity.content = content
        activity.audience = audience
        activity.link = data.get("link")
        activity.updated_by = updated_by
        activity.updated_at = datetime.now()
        await self.db.flush()
        return activity

    async def republish_activity(self, activity_id: int, updated_by: str) -> PublishedActivity:
        activity = await self._get_activity(activity_id)
        activity.status = "PUBLISHED"
        activity.publish_version = (activity.publish_version or 1) + 1
        activity.published_at = datetime.now()
        activity.updated_by = updated_by
        activity.updated_at = activity.published_at
        await self.db.flush()
        await self._notify_activity(activity)
        return activity

    async def delete_activity(self, activity_id: int) -> None:
        activity = await self._get_activity(activity_id)
        await self.db.delete(activity)
        await self.db.flush()

    async def export_users_csv(self) -> str:
        result = await self.db.execute(select(User).order_by(User.id.asc()))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "username", "display_name", "email", "role",
            "enabled", "last_login", "created_at",
        ])
        for user in result.scalars().all():
            writer.writerow([
                user.id,
                user.username,
                user.display_name or "",
                user.email or "",
                user.role,
                "true" if user.enabled else "false",
                user.last_login.isoformat() if user.last_login else "",
                user.created_at.isoformat() if user.created_at else "",
            ])
        return output.getvalue()

    async def update_course(self, course_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        course = await self._get_course(course_id)
        was_visible = bool(course.visible)
        teacher_id = data.get("teacher_id", data.get("teacherId"))
        if teacher_id is not None:
            teacher = await self._get_teacher(int(teacher_id))
            course.teacher_id = teacher.id

        for key in ("name", "description", "schedule", "category"):
            if key in data:
                setattr(course, key, data.get(key))
        if "credits" in data and data.get("credits") is not None:
            course.credits = max(0, int(data["credits"]))
        if "max_students" in data or "maxStudents" in data:
            max_students = int(data.get("max_students", data.get("maxStudents")) or 0)
            if max_students < course.enrolled_count:
                raise ValueError("Course capacity cannot be lower than enrolled students")
            course.max_students = max_students
        if "visible" in data:
            course.visible = bool(data["visible"])
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
        return await self._course_detail(course)

    async def delete_course(self, course_id: int) -> Dict[str, Any]:
        course = await self._get_course(course_id)
        name = course.name
        await self._delete_course_graph(course_id)
        await self.db.flush()
        return {"courseId": course_id, "name": name, "status": "deleted"}

    async def batch_hide_courses(self, course_ids: List[int]) -> Dict[str, Any]:
        results = []
        for course_id in self._normalize_ids(course_ids):
            try:
                async with self.db.begin_nested():
                    course = await self._get_course(course_id)
                    course.visible = False
                    await self.db.flush()
                results.append({"courseId": course_id, "success": True, "status": "hidden"})
            except Exception as exc:
                results.append({"courseId": course_id, "success": False, "error": str(exc)})
        return self._batch_summary(results)

    async def batch_delete_courses(self, course_ids: List[int]) -> Dict[str, Any]:
        results = []
        for course_id in self._normalize_ids(course_ids):
            try:
                async with self.db.begin_nested():
                    await self._get_course(course_id)
                    await self._delete_course_graph(course_id)
                    await self.db.flush()
                results.append({"courseId": course_id, "success": True, "status": "deleted"})
            except Exception as exc:
                results.append({"courseId": course_id, "success": False, "error": str(exc)})
        return self._batch_summary(results)

    async def get_course_enrollments(self, course_id: int) -> Dict[str, Any]:
        course = await self._get_course(course_id)
        selected_result = await self.db.execute(
            select(User, Enrollment.enrolled_at)
            .join(Enrollment, Enrollment.student_id == User.id)
            .where(Enrollment.course_id == course_id)
            .order_by(User.id.asc())
        )
        all_result = await self.db.execute(
            select(User).where(User.role == "STUDENT", User.enabled.is_(True)).order_by(User.id.asc())
        )
        students = [
            {
                "id": student.id,
                "username": student.username,
                "displayName": student.display_name or student.username,
                "email": student.email,
                "enrolledAt": enrolled_at.isoformat() if enrolled_at else None,
            }
            for student, enrolled_at in selected_result.all()
        ]
        all_students = [
            {
                "id": student.id,
                "username": student.username,
                "displayName": student.display_name or student.username,
                "email": student.email,
            }
            for student in all_result.scalars().all()
        ]
        return {
            "courseId": course.id,
            "maxStudents": course.max_students,
            "students": students,
            "allStudents": all_students,
        }

    async def update_course_enrollments(
        self,
        course_id: int,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        course = await self._get_course(course_id)
        max_students = data.get("max_students", data.get("maxStudents"))
        remove_ids = set(self._normalize_ids(data.get("remove_student_ids", data.get("removeStudentIds", []))))
        add_ids = set(self._normalize_ids(data.get("add_student_ids", data.get("addStudentIds", []))))

        if remove_ids:
            await self.db.execute(
                Enrollment.__table__.delete().where(
                    Enrollment.course_id == course_id,
                    Enrollment.student_id.in_(remove_ids),
                )
            )

        current_ids = set(
            (await self.db.execute(
                select(Enrollment.student_id).where(Enrollment.course_id == course_id)
            )).scalars().all()
        )
        add_ids = add_ids - current_ids - remove_ids
        target_capacity = int(max_students) if max_students is not None else course.max_students
        if len(current_ids) + len(add_ids) > target_capacity:
            raise ValueError("Course capacity is not enough for selected students")

        if add_ids:
            valid_students = set(
                (await self.db.execute(
                    select(User.id).where(
                        User.id.in_(add_ids),
                        User.role == "STUDENT",
                        User.enabled.is_(True),
                    )
                )).scalars().all()
            )
            missing = add_ids - valid_students
            if missing:
                raise ValueError(f"Invalid student ids: {sorted(missing)}")
            now = datetime.now()
            self.db.add_all([
                Enrollment(
                    course_id=course_id,
                    student_id=student_id,
                    enrolled_at=now,
                    score=0,
                    base_score=0,
                    peer_review_bonus=0,
                )
                for student_id in valid_students
            ])

        course.max_students = target_capacity
        await self._refresh_course_enrolled_count(course)
        await self.db.flush()
        return await self.get_course_enrollments(course_id)

    async def get_monitor(self, health_check: bool = False) -> Dict[str, Any]:
        now = datetime.now()
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        total_files_size = (
            await self.db.execute(select(func.coalesce(func.sum(StoredFile.size), 0)))
        ).scalar() or 0
        total_users = (await self.db.execute(select(func.count(User.id)))).scalar() or 0
        active_users = (
            await self.db.execute(
                select(func.count(User.id)).where(User.last_login >= day_ago)
            )
        ).scalar() or 0
        pending_submissions = (
            await self.db.execute(
                select(func.count(Submission.id)).where(Submission.status == "SUBMITTED")
            )
        ).scalar() or 0
        total_submissions = (
            await self.db.execute(select(func.count(Submission.id)))
        ).scalar() or 0
        recent_uploads = (
            await self.db.execute(
                select(func.count(StoredFile.id)).where(StoredFile.created_at >= week_ago)
            )
        ).scalar() or 0
        total_uploads = (
            await self.db.execute(select(func.count(StoredFile.id)))
        ).scalar() or 0
        audit_count = (
            await self.db.execute(select(func.count(AuditLog.id)).where(AuditLog.timestamp >= day_ago))
        ).scalar() or 0

        storage_pct = min(100, round((float(total_files_size) / (1024 * 1024 * 1024)) * 100, 2))
        active_pct = round((active_users / total_users) * 100, 2) if total_users else 0
        pending_pct = round((pending_submissions / total_submissions) * 100, 2) if total_submissions else 0
        upload_pct = round((recent_uploads / total_uploads) * 100, 2) if total_uploads else 0

        resource_metrics = [
            {"name": "active_user_ratio", "value": active_pct, "threshold": 80, "alert": active_pct > 80},
            {"name": "pending_submission_ratio", "value": pending_pct, "threshold": 70, "alert": pending_pct > 70},
            {"name": "storage_usage_ratio", "value": storage_pct, "threshold": 90, "alert": storage_pct > 90},
            {"name": "recent_upload_ratio", "value": upload_pct, "threshold": 85, "alert": upload_pct > 85},
        ]

        db_metrics = [
            {"name": "users", "value": str(total_users), "threshold": "100000"},
            {"name": "audit_logs_24h", "value": str(audit_count), "threshold": "5000"},
            {"name": "storage_mb", "value": str(round(float(total_files_size) / (1024 * 1024), 2)), "threshold": "1024"},
        ]

        labels = []
        success_rate = []
        load_index = []
        qps = []
        active_trend = []
        submitted_trend = []
        upload_size_trend = []
        audit_trend = []
        for offset in range(11, -1, -1):
            start = now - timedelta(hours=offset + 1)
            end = now - timedelta(hours=offset)
            labels.append(end.strftime("%H:%M"))
            total = (
                await self.db.execute(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.timestamp >= start,
                        AuditLog.timestamp < end,
                    )
                )
            ).scalar() or 0
            errors = (
                await self.db.execute(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.timestamp >= start,
                        AuditLog.timestamp < end,
                        or_(AuditLog.action.ilike("%error%"), AuditLog.details.ilike("%error%")),
                    )
                )
            ).scalar() or 0
            active_user_total = (
                await self.db.execute(
                    select(func.count(func.distinct(AuditLog.username))).where(
                        AuditLog.timestamp >= start,
                        AuditLog.timestamp < end,
                        AuditLog.username.is_not(None),
                    )
                )
            ).scalar() or 0
            submitted_total = (
                await self.db.execute(
                    select(func.count(Submission.id)).where(
                        Submission.submitted_at >= start,
                        Submission.submitted_at < end,
                    )
                )
            ).scalar() or 0
            upload_size_total = (
                await self.db.execute(
                    select(func.coalesce(func.sum(StoredFile.size), 0)).where(
                        StoredFile.created_at >= start,
                        StoredFile.created_at < end,
                    )
                )
            ).scalar() or 0
            success_rate.append(round(((total - errors) / total) * 100, 2) if total else 100)
            load_index.append(total + errors * 3)
            qps.append(total)
            active_trend.append(active_user_total)
            submitted_trend.append(submitted_total)
            upload_size_trend.append(float(upload_size_total))
            audit_trend.append(total)

        def scale_series(values: List[float]) -> List[float]:
            peak = max(values) if values else 0
            if not peak:
                return [0 for _ in values]
            return [round((value / peak) * 100, 2) for value in values]

        active_user_series = [
            round((value / total_users) * 100, 2) if total_users else 0
            for value in active_trend
        ]

        error_rows = await self.db.execute(
            select(AuditLog.action, func.count(AuditLog.id))
            .where(or_(AuditLog.action.ilike("%error%"), AuditLog.details.ilike("%error%")))
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
            .limit(5)
        )
        error_types = [
            {"name": action or "unknown", "value": count}
            for action, count in error_rows.all()
        ]

        alerts = [
            {
                "level": "WARNING",
                "title": metric["name"],
                "message": metric["name"],
                "value": metric["value"],
                "time": now.isoformat(timespec="seconds"),
                "status": "OPEN",
            }
            for metric in resource_metrics
            if metric["alert"]
        ]
        status = "WARNING" if alerts else "HEALTHY"
        uptime_delta = now - SERVICE_STARTED_AT
        uptime = f"{uptime_delta.days}d {uptime_delta.seconds // 3600}h {(uptime_delta.seconds % 3600) // 60}m"
        abnormal_items = [alert["message"] for alert in alerts]
        health_report = {
            "status": status,
            "score": max(60, 100 - len(alerts) * 10),
            "abnormalItems": abnormal_items,
            "services": [
                {"name": "API", "status": "up"},
                {"name": "database", "status": "up"},
                {"name": "notification", "status": "up"},
                {"name": "storage", "status": "warning" if storage_pct > 90 else "up"},
            ],
        }
        if health_check:
            health_report["checkedAt"] = now.isoformat(timespec="seconds")

        return {
            "resourceMetrics": resource_metrics,
            "dbMetrics": db_metrics,
            "status": status,
            "uptime": uptime,
            "resourceTrend": [
                {"name": "active_user_ratio", "labels": labels, "values": active_user_series},
                {"name": "submission_activity", "labels": labels, "values": scale_series(submitted_trend)},
                {"name": "upload_activity", "labels": labels, "values": scale_series(upload_size_trend)},
                {"name": "audit_activity", "labels": labels, "values": scale_series(audit_trend)},
            ],
            "serviceTrend": {
                "labels": labels,
                "successRate": success_rate,
                "responseTime": load_index,
                "qps": qps,
            },
            "errorStats": {"types": error_types},
            "alerts": alerts,
            "healthReport": health_report,
        }

    async def _get_activity(self, activity_id: int) -> PublishedActivity:
        result = await self.db.execute(select(PublishedActivity).where(PublishedActivity.id == activity_id))
        activity = result.scalar_one_or_none()
        if activity is None:
            raise ValueError("Activity not found")
        return activity

    async def _get_course(self, course_id: int) -> Course:
        result = await self.db.execute(select(Course).where(Course.id == course_id))
        course = result.scalar_one_or_none()
        if course is None:
            raise ValueError("Course not found")
        return course

    async def _get_teacher(self, teacher_id: int) -> User:
        result = await self.db.execute(
            select(User).where(User.id == teacher_id, User.role == "TEACHER", User.enabled.is_(True))
        )
        teacher = result.scalar_one_or_none()
        if teacher is None:
            raise ValueError("Teacher not found")
        return teacher

    async def _course_detail(self, course: Course) -> Dict[str, Any]:
        teacher = None
        if course.teacher_id:
            teacher = (await self.db.execute(select(User).where(User.id == course.teacher_id))).scalar_one_or_none()
        return {
            "id": course.id,
            "name": course.name,
            "description": course.description,
            "schedule": course.schedule,
            "category": course.category,
            "credits": course.credits,
            "teacherId": course.teacher_id,
            "teacher": {
                "id": teacher.id,
                "username": teacher.username,
                "displayName": teacher.display_name or teacher.username,
            } if teacher else None,
            "enrolledCount": course.enrolled_count,
            "maxStudents": course.max_students,
            "visible": course.visible,
            "createdAt": course.created_at.isoformat() if course.created_at else None,
        }

    async def _delete_course_graph(self, course_id: int) -> None:
        assignment_ids = list(
            (await self.db.execute(select(Assignment.id).where(Assignment.course_id == course_id))).scalars().all()
        )
        submission_ids: List[int] = []
        if assignment_ids:
            submission_ids = list(
                (await self.db.execute(
                    select(Submission.id).where(Submission.assignment_id.in_(assignment_ids))
                )).scalars().all()
            )
        peer_conditions = []
        if assignment_ids:
            peer_conditions.append(PeerReview.assignment_id.in_(assignment_ids))
        if submission_ids:
            peer_conditions.append(PeerReview.target_submission_id.in_(submission_ids))
        if peer_conditions:
            await self.db.execute(PeerReview.__table__.delete().where(or_(*peer_conditions)))
        if submission_ids:
            await self.db.execute(
                TeacherCommentUsageHistory.__table__.delete().where(
                    TeacherCommentUsageHistory.submission_id.in_(submission_ids)
                )
            )
            await self.db.execute(
                Submission.__table__.delete().where(Submission.id.in_(submission_ids))
            )
        if assignment_ids:
            await self.db.execute(
                Assignment.__table__.delete().where(Assignment.id.in_(assignment_ids))
            )
        await self.db.execute(Enrollment.__table__.delete().where(Enrollment.course_id == course_id))
        await self.db.execute(Course.__table__.delete().where(Course.id == course_id))

    async def _refresh_course_enrolled_count(self, course: Course) -> None:
        course.enrolled_count = (
            await self.db.execute(
                select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id)
            )
        ).scalar() or 0

    async def _notify_activity(self, activity: PublishedActivity) -> None:
        audience_roles = {
            "ALL": ["TEACHER", "STUDENT"],
            "TEACHERS": ["TEACHER"],
            "STUDENTS": ["STUDENT"],
        }.get(activity.audience, [])
        if not audience_roles:
            return
        await NotificationService(self.db).create_for_roles(
            audience_roles,
            activity.title,
            activity.content,
            category="ACTIVITY",
            type_="INFO",
            link=activity.link,
        )

    @staticmethod
    def _activity_dict(activity: PublishedActivity) -> Dict[str, Any]:
        return {
            "id": activity.id,
            "title": activity.title,
            "content": activity.content,
            "audience": activity.audience,
            "status": activity.status,
            "link": activity.link,
            "createdBy": activity.created_by,
            "createdAt": activity.created_at.isoformat() if activity.created_at else None,
            "updatedBy": activity.updated_by,
            "updatedAt": activity.updated_at.isoformat() if activity.updated_at else None,
            "publishedAt": activity.published_at.isoformat() if activity.published_at else None,
            "publishVersion": activity.publish_version or 1,
        }

    @staticmethod
    def _normalize_ids(values: Any) -> List[int]:
        if not values:
            return []
        return [int(value) for value in values if value is not None]

    @staticmethod
    def _batch_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        success = [item for item in results if item.get("success")]
        failed = [item for item in results if not item.get("success")]
        return {
            "results": results,
            "successCount": len(success),
            "failedCount": len(failed),
        }
