"""学生路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_student
from app.models.models import User
from app.schemas.assignment import PeerReviewSubmit, SubmissionSubmit
from app.schemas.common import ApiResponse
from app.services.student_service import StudentService

router = APIRouter(
    prefix="/api/student",
    tags=["学生"],
    dependencies=[Depends(require_student)],
)


@router.get("/dashboard")
async def dashboard(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """学生首页数据"""
    service = StudentService(db)
    data = await service.get_dashboard(user)
    return ApiResponse.ok(data=data)


@router.get("/courses")
async def all_courses(db: AsyncSession = Depends(get_db)):
    """全部可选课程"""
    service = StudentService(db)
    data = await service.get_all_courses()
    return ApiResponse.ok(data=data)


@router.get("/my-courses")
async def my_courses(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """我的课程"""
    service = StudentService(db)
    data = await service.get_my_courses(user)
    return ApiResponse.ok(data=data)


@router.post("/enroll/{course_id}")
async def enroll(
    course_id: int,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """选课"""
    service = StudentService(db)
    try:
        await service.enroll(course_id, user)
        return ApiResponse.ok(message="选课成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.post("/drop/{course_id}")
async def drop(
    course_id: int,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """退选课程"""
    service = StudentService(db)
    try:
        await service.drop(course_id, user)
        return ApiResponse.ok(message="退课成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/courses/{course_id}/assignments")
async def course_assignments(
    course_id: int,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """课程作业列表"""
    service = StudentService(db)
    try:
        data = await service.get_my_assignments(course_id, user)
        return ApiResponse.ok(data=data)
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.post("/assignments/{assignment_id}/submit")
async def submit_assignment(
    assignment_id: int,
    req: SubmissionSubmit,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """提交作业"""
    service = StudentService(db)
    try:
        data = await service.submit_assignment(
            assignment_id, user, req.content, req.file_path, req.file_name
        )
        return ApiResponse.ok(data=data, message="提交成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/peer-reviews")
async def peer_reviews(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """我的互评任务"""
    service = StudentService(db)
    data = await service.get_my_peer_reviews(user)
    return ApiResponse.ok(data=data)


@router.post("/peer-reviews/{assignment_id}/{target_submission_id}")
async def submit_peer_review(
    assignment_id: int,
    target_submission_id: int,
    req: PeerReviewSubmit,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """提交匿名互评"""
    service = StudentService(db)
    try:
        data = await service.submit_peer_review(
            user, assignment_id, target_submission_id, req.rating, req.comment
        )
        return ApiResponse.ok(data=data, message="互评提交成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/grades")
async def grades(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """我的成绩"""
    service = StudentService(db)
    data = await service.get_my_grades(user)
    return ApiResponse.ok(data=data)


@router.get("/courses/{course_id}/average")
async def course_average(
    course_id: int,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """课程平均分"""
    service = StudentService(db)
    try:
        avg = await service.get_course_average(course_id, user)
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)
    if avg < 0:
        return ApiResponse.error(message="暂无成绩数据")
    return ApiResponse.ok(data={"course_id": course_id, "average": avg})
