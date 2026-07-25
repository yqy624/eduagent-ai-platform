"""教师路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_teacher
from app.models.models import User
from app.schemas.assignment import (
    AssignmentCreate,
    CourseCreate,
    CourseUpdate,
    GradeRequest,
    PeerReviewConfigUpdate,
)
from app.schemas.common import ApiResponse
from app.services.teacher_service import TeacherService

router = APIRouter(
    prefix="/api/teacher",
    tags=["教师"],
    dependencies=[Depends(require_teacher)],
)


@router.get("/dashboard")
async def dashboard(
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """教师首页数据"""
    service = TeacherService(db)
    data = await service.get_dashboard(user)
    return ApiResponse.ok(data=data)


@router.get("/courses")
async def my_courses(
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """我的课程列表"""
    service = TeacherService(db)
    data = await service.get_my_courses(user)
    return ApiResponse.ok(data=data)


@router.post("/courses")
async def create_course(
    req: CourseCreate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """创建课程"""
    service = TeacherService(db)
    course = await service.create_course(req, user)
    return ApiResponse.ok(data=course, message="课程创建成功")


@router.put("/courses/{course_id}")
async def update_course(
    course_id: int,
    req: CourseUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """更新课程"""
    service = TeacherService(db)
    try:
        course = await service.update_course(course_id, req, user)
        return ApiResponse.ok(data=course, message="课程更新成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除课程"""
    service = TeacherService(db)
    await service.delete_course(course_id)
    return ApiResponse.ok(message="课程已删除")


@router.get("/courses/{course_id}/students")
async def course_students(
    course_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查看课程学生名单"""
    service = TeacherService(db)
    data = await service.get_course_students(course_id)
    return ApiResponse.ok(data=data)


@router.post("/assignments")
async def create_assignment(
    req: AssignmentCreate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """发布作业"""
    service = TeacherService(db)
    try:
        assignment = await service.create_assignment(req, user)
        return ApiResponse.ok(data=assignment, message="作业发布成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/courses/{course_id}/assignments")
async def course_assignments(
    course_id: int,
    db: AsyncSession = Depends(get_db),
):
    """课程作业列表"""
    service = TeacherService(db)
    data = await service.get_course_assignments(course_id)
    return ApiResponse.ok(data=data)


@router.get("/assignments/{assignment_id}/submissions")
async def pending_submissions(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查看作业提交记录"""
    service = TeacherService(db)
    data = await service.get_submissions(assignment_id)
    return ApiResponse.ok(data=data)


@router.post("/submissions/{submission_id}/grade")
async def grade_submission(
    submission_id: int,
    req: GradeRequest,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """批改作业"""
    service = TeacherService(db)
    try:
        data = await service.grade_submission(submission_id, req, user)
        return ApiResponse.ok(data=data, message="评分成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/assignments/{assignment_id}/analysis")
async def assignment_analysis(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """作业成绩分析"""
    service = TeacherService(db)
    try:
        data = await service.get_assignment_analysis(assignment_id)
        return ApiResponse.ok(data=data)
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/assignments/{assignment_id}/peer-review")
async def peer_review_overview(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """互评概览"""
    service = TeacherService(db)
    data = await service.get_peer_review_overview(assignment_id)
    return ApiResponse.ok(data=data)


async def _update_peer_review(
    assignment_id: int,
    req: PeerReviewConfigUpdate,
    user: User,
    db: AsyncSession,
):
    service = TeacherService(db)
    try:
        data = await service.update_peer_review(assignment_id, req, user)
        return ApiResponse.ok(data=data, message="互评配置已更新")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.post("/assignments/{assignment_id}/peer-review")
async def create_peer_review_config(
    assignment_id: int,
    req: PeerReviewConfigUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _update_peer_review(assignment_id, req, user, db)


@router.put("/assignments/{assignment_id}/peer-review")
async def update_peer_review_config(
    assignment_id: int,
    req: PeerReviewConfigUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _update_peer_review(assignment_id, req, user, db)


@router.get("/comment-memories", include_in_schema=False)
async def comment_memories(db: AsyncSession = Depends(get_db), user: User = Depends(require_teacher)):
    """评语记忆列表"""
    from app.models.models import TeacherCommentMemory as _T
    from sqlalchemy import select
    r = await db.execute(
        select(_T).where(_T.teacher_id == user.id)
        .order_by(_T.usage_count.desc())
        .limit(50)
    )
    items = []
    for m in r.scalars().all():
        items.append({
            "id": m.id, "category": m.category, "commentText": m.comment_text,
            "usageCount": m.usage_count, "lastUsedAt": m.last_used_at.isoformat() if m.last_used_at else None,
            "createdAt": m.created_at.isoformat() if m.created_at else None,
        })
    return ApiResponse.ok(data=items)
