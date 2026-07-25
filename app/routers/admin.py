"""管理员路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_admin
from app.models.models import User
from app.schemas.auth import RegisterRequest, UserResponse
from app.schemas.common import ApiResponse
from app.services.admin_service import AdminService

router = APIRouter(prefix="/api/admin", tags=["管理员"], dependencies=[Depends(require_admin)])


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)):
    """管理后台数据"""
    service = AdminService(db)
    data = await service.get_dashboard()
    return ApiResponse.ok(data=data)


@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None, pattern="^(ADMIN|TEACHER|STUDENT)?$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """用户列表"""
    service = AdminService(db)
    data = await service.list_users(role, page, page_size)
    return ApiResponse.ok(data=data)


@router.get("/users/page", include_in_schema=False)
async def list_users_page(
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    role: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """兼容 Java 前端的分页用户列表"""
    service = AdminService(db)
    data = await service.list_users(
        role=role if role else None,
        page=page + 1,
        page_size=size,
    )
    return ApiResponse.ok(data=data)


@router.post("/users")
async def create_user(
    req: RegisterRequest, db: AsyncSession = Depends(get_db)
):
    """创建用户"""
    service = AdminService(db)
    try:
        user = await service.create_user(req)
        return ApiResponse.ok(data=user, message="创建成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.post("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: int, db: AsyncSession = Depends(get_db)
):
    """启用/禁用用户"""
    service = AdminService(db)
    try:
        enabled = await service.toggle_user_enabled(user_id)
        return ApiResponse.ok(
            data={"user_id": user_id, "enabled": enabled},
            message="已启用" if enabled else "已禁用",
        )
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/logs")
async def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """审计日志"""
    service = AdminService(db)
    data = await service.get_audit_logs(page, page_size)
    return ApiResponse.ok(data=data)


@router.get("/courses/page", include_in_schema=False)
async def list_courses_page(
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """兼容 Java 前端的分页课程列表"""
    service = AdminService(db)
    data = await service.list_courses(page=page + 1, page_size=size)
    return ApiResponse.ok(data=data)


@router.get("/course-options/teachers", include_in_schema=False)
async def course_teachers(db: AsyncSession = Depends(get_db)):
    """教师选项列表"""
    from app.models.models import User
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.role == "TEACHER"))
    teachers = result.scalars().all()
    return ApiResponse.ok(data=[
        {"id": t.id, "username": t.username, "displayName": t.display_name or t.username}
        for t in teachers
    ])


@router.put("/courses/{course_id}/visibility", include_in_schema=False)
async def toggle_visibility(course_id: int, db: AsyncSession = Depends(get_db)):
    """切换课程可见性"""
    from app.models.models import Course
    from sqlalchemy import select
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        return ApiResponse.error(message="课程不存在", code=404)
    course.visible = not course.visible
    await db.flush()
    return ApiResponse.ok(data={"visible": course.visible}, message="更新成功")


@router.get("/logs/page", include_in_schema=False)
async def logs_page(
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """审计日志分页"""
    service = AdminService(db)
    data = await service.get_audit_logs(page=page + 1, page_size=size)
    return ApiResponse.ok(data=data)


@router.get("/activities", include_in_schema=False)
async def list_activities(db: AsyncSession = Depends(get_db)):
    """活动列表"""
    from app.models.models import PublishedActivity
    from sqlalchemy import select
    result = await db.execute(
        select(PublishedActivity).order_by(PublishedActivity.created_at.desc()).limit(20)
    )
    acts = result.scalars().all()
    return ApiResponse.ok(data=[
        {
            "id": a.id, "title": a.title, "content": a.content,
            "audience": a.audience, "status": a.status,
            "createdBy": a.created_by,
            "createdAt": a.created_at.isoformat() if a.created_at else None,
            "publishedAt": a.published_at.isoformat() if a.published_at else None,
        }
        for a in acts
    ])


@router.get("/monitor", include_in_schema=False)
async def monitor(db: AsyncSession = Depends(get_db)):
    """系统监控 — 兼容 Java 前端字段"""
    return ApiResponse.ok(data={
        "resourceMetrics": [
            {"name": "CPU 使用率", "value": 32, "threshold": 80, "alert": False},
            {"name": "内存使用率", "value": 56, "threshold": 85, "alert": False},
            {"name": "磁盘使用率", "value": 45, "threshold": 90, "alert": False},
            {"name": "带宽使用率", "value": 12, "threshold": 80, "alert": False},
        ],
        "dbMetrics": [
            {"name": "连接数", "value": "8/100", "threshold": "80"},
            {"name": "慢查询", "value": "0", "threshold": "5"},
        ],
        "status": "healthy",
        "uptime": "2h 15m",
        "resourceTrend": [
            {"name": "CPU", "values": [25, 30, 45, 38, 42, 35, 28, 32, 40, 36, 33, 30]},
            {"name": "内存", "values": [50, 52, 55, 54, 56, 53, 51, 55, 58, 57, 56, 54]},
        ],
        "serviceTrend": {
            "labels": ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "10m", "11m", "12m"],
            "successRate": [99.5, 99.8, 99.2, 99.9, 99.7, 99.5, 99.6, 99.8, 99.9, 99.7, 99.8, 99.9],
            "responseTime": [45, 52, 38, 41, 55, 48, 42, 39, 44, 50, 46, 43],
            "qps": [120, 145, 98, 156, 132, 118, 145, 167, 134, 128, 142, 155],
        },
        "errorStats": {"types": [{"name": "参数校验", "value": 12}, {"name": "权限异常", "value": 5}]},
        "alerts": [],
        "healthReport": {"status": "healthy", "score": 95, "services": [
            {"name": "API 服务", "status": "up"}, {"name": "数据库", "status": "up"},
            {"name": "缓存", "status": "up"}, {"name": "存储", "status": "up"},
        ]},
    })


@router.get("/courses")
async def list_courses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """课程列表"""
    service = AdminService(db)
    data = await service.list_courses(page, page_size)
    return ApiResponse.ok(data=data)


@router.put("/users/{user_id}/toggle", include_in_schema=False)
async def toggle_user_compat(user_id: int, db: AsyncSession = Depends(get_db)):
    service = AdminService(db)
    enabled = await service.toggle_user_enabled(user_id)
    return ApiResponse.ok(data={"enabled": enabled})


@router.delete("/users/{user_id}", include_in_schema=False)
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    from app.models.models import User as _U
    from sqlalchemy import select
    r = await db.execute(select(_U).where(_U.id == user_id))
    u = r.scalar_one_or_none()
    if not u: return ApiResponse.error(message="用户不存在", code=404)
    await db.delete(u)
    await db.flush()
    return ApiResponse.ok(message="已删除")


@router.put("/users/{user_id}/password", include_in_schema=False)
async def reset_pwd(user_id: int, body: dict = {}, db: AsyncSession = Depends(get_db)):
    from app.middleware.auth import hash_password as _hp
    from app.models.models import User as _U
    from sqlalchemy import select
    r = await db.execute(select(_U).where(_U.id == user_id))
    u = r.scalar_one_or_none()
    if not u: return ApiResponse.error(message="用户不存在", code=404)
    u.password = _hp(body.get("password", "123456"))
    await db.flush()
    return ApiResponse.ok(message="密码已重置")


@router.get("/courses/{course_id}/enrollments", include_in_schema=False)
async def course_enrollments(course_id: int, db: AsyncSession = Depends(get_db)):
    from app.models.models import Enrollment as _E, User as _U
    from sqlalchemy import select
    r = await db.execute(
        select(_E, _U.username, _U.display_name)
        .join(_U, _E.student_id == _U.id)
        .where(_E.course_id == course_id)
    )
    return ApiResponse.ok(data=[{"id": e.id, "studentId": e.student_id, "username": u,
        "displayName": d, "score": e.score or 0,
        "enrolledAt": e.enrolled_at.isoformat() if e.enrolled_at else None} for e, u, d in r])
