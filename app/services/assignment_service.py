"""作业与提交服务"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Assignment,
    Course,
    Enrollment,
    PeerReview,
    Submission,
    User,
)
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentResponse,
    GradeRequest,
    PeerReviewResponse,
    PeerReviewSubmit,
    SubmissionResponse,
    AssignmentAnalysis,
)


class AssignmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, assignment_id: int) -> Optional[Assignment]:
        result = await self.db.execute(
            select(Assignment).where(Assignment.id == assignment_id)
        )
        return result.scalar_one_or_none()

    async def create(self, req: AssignmentCreate, teacher: User) -> Assignment:
        course = await self.db.execute(
            select(Course).where(Course.id == req.course_id)
        )
        course_obj = course.scalar_one_or_none()
        if course_obj is None:
            raise ValueError("课程不存在")
        if course_obj.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权为此课程发布作业")

        due_date = None
        if req.due_date:
            try:
                due_date = datetime.fromisoformat(req.due_date.replace("Z", "+00:00"))
            except ValueError:
                due_date = datetime.strptime(req.due_date, "%Y-%m-%dT%H:%M:%S")

        peer_review_open = None
        peer_review_close = None
        if req.peer_review_open_at:
            peer_review_open = datetime.fromisoformat(
                req.peer_review_open_at.replace("Z", "+00:00")
            )
        if req.peer_review_close_at:
            peer_review_close = datetime.fromisoformat(
                req.peer_review_close_at.replace("Z", "+00:00")
            )

        assignment = Assignment(
            course_id=req.course_id,
            title=req.title,
            description=req.description,
            due_date=due_date,
            total_points=req.total_points,
            teacher_id=teacher.id,
            created_at=datetime.now(),
            attachment_paths=req.attachment_paths,
            peer_review_enabled=req.peer_review_enabled,
            peer_review_open_at=peer_review_open,
            peer_review_close_at=peer_review_close,
            peer_review_required_count=req.peer_review_required_count,
            peer_review_bonus_per_review=req.peer_review_bonus_per_review,
            peer_review_bonus_cap=req.peer_review_bonus_cap,
            peer_review_prompt=req.peer_review_prompt,
        )
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def get_course_assignments(self, course_id: int) -> List[Assignment]:
        result = await self.db.execute(
            select(Assignment)
            .where(Assignment.course_id == course_id)
            .order_by(Assignment.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_submission(self, submission_id: int) -> Optional[Submission]:
        result = await self.db.execute(
            select(Submission).where(Submission.id == submission_id)
        )
        return result.scalar_one_or_none()

    async def get_submissions(self, assignment_id: int) -> List[Submission]:
        result = await self.db.execute(
            select(Submission).where(Submission.assignment_id == assignment_id)
        )
        return list(result.scalars().all())

    async def submit(
        self,
        assignment_id: int,
        student: User,
        content: Optional[str] = None,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> Submission:
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")

        # 检查是否已选课
        enrollment = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == assignment.course_id,
                Enrollment.student_id == student.id,
            )
        )
        if enrollment.scalar_one_or_none() is None and student.role != "ADMIN":
            raise ValueError("未选修此课程，无法提交作业")

        # 检查是否已提交
        existing = await self.db.execute(
            select(Submission).where(
                Submission.assignment_id == assignment_id,
                Submission.student_id == student.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("已提交过此作业，请勿重复提交")

        stored = None
        if file_path:
            stored = file_path + ("::" + file_name if file_name else "")

        submission = Submission(
            assignment_id=assignment_id,
            student_id=student.id,
            content=content,
            file_name=file_name,
            file_paths=stored,
            status="SUBMITTED",
            submitted_at=datetime.now(),
        )
        self.db.add(submission)
        await self.db.flush()
        return submission

    async def grade(
        self, submission_id: int, req: GradeRequest, teacher: User
    ) -> Submission:
        submission = await self.get_submission(submission_id)
        if submission is None:
            raise ValueError("提交记录不存在")

        assignment = await self.get_by_id(submission.assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")

        course = await self.db.execute(
            select(Course).where(Course.id == assignment.course_id)
        )
        course_obj = course.scalar_one_or_none()
        if course_obj is None:
            raise ValueError("课程不存在")
        if course_obj.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权批改此作业")

        submission.score = req.score
        submission.teacher_comment = req.comment
        submission.status = "GRADED"
        submission.graded_at = datetime.now()
        await self.db.flush()

        # 更新选课表的 base_score
        await self._update_enrollment_score(submission.student_id, assignment.course_id)
        return submission

    async def _update_enrollment_score(self, student_id: int, course_id: int):
        """更新学生某门课程的总分"""
        result = await self.db.execute(
            select(func.coalesce(func.sum(Submission.score), 0)).where(
                Submission.student_id == student_id,
                Submission.assignment_id.in_(
                    select(Assignment.id).where(Assignment.course_id == course_id)
                ),
                Submission.status == "GRADED",
            )
        )
        total = result.scalar() or 0

        pr_result = await self.db.execute(
            select(Enrollment).where(
                Enrollment.student_id == student_id,
                Enrollment.course_id == course_id,
            )
        )
        enrollment = pr_result.scalar_one_or_none()
        if enrollment:
            enrollment.base_score = float(total)
            await self.db.flush()

    async def get_assignment_analysis(
        self, assignment_id: int
    ) -> AssignmentAnalysis:
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")

        submissions = await self.get_submissions(assignment_id)
        graded = [s for s in submissions if s.status == "GRADED" and s.score is not None]

        avg_score = None
        max_score = None
        min_score = None
        pass_rate = None
        if graded:
            scores = [s.score for s in graded]
            avg_score = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            pass_count = sum(1 for s in scores if s >= (assignment.total_points or 100) * 0.6)
            pass_rate = pass_count / len(scores) * 100 if scores else 0

        return AssignmentAnalysis(
            assignment_id=assignment_id,
            title=assignment.title,
            total_submissions=len(submissions),
            graded_count=len(graded),
            average_score=avg_score,
            max_score=max_score,
            min_score=min_score,
            pass_rate=pass_rate,
        )

    async def get_peer_review_overview(self, assignment_id: int) -> Dict[str, Any]:
        """获取互评概览（前端兼容字段）"""
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")

        result = await self.db.execute(
            select(func.count(PeerReview.id)).where(PeerReview.assignment_id == assignment_id)
        )
        total = result.scalar() or 0

        submitted = await self.db.execute(
            select(func.count(PeerReview.id)).where(
                PeerReview.assignment_id == assignment_id,
                PeerReview.status == "SUBMITTED",
            )
        )
        submitted_count = submitted.scalar() or 0

        granted = await self.db.execute(
            select(func.count(PeerReview.id)).where(
                PeerReview.assignment_id == assignment_id,
                PeerReview.status == "BONUS_GRANTED",
            )
        )
        granted_count = granted.scalar() or 0

        return {
            "enabled": assignment.peer_review_enabled,
            "openAt": assignment.peer_review_open_at.isoformat() if assignment.peer_review_open_at else None,
            "closeAt": assignment.peer_review_close_at.isoformat() if assignment.peer_review_close_at else None,
            "requiredCount": assignment.peer_review_required_count or 1,
            "bonusPerReview": assignment.peer_review_bonus_per_review or 1.0,
            "bonusCap": assignment.peer_review_bonus_cap or 3.0,
            "totalReviews": submitted_count,
            "grantedCount": granted_count,
            "totalAssignments": total,
            "submittedCount": submitted_count,
            "pendingCount": total - submitted_count,
        }

    async def to_submission_response(
        self, submission: Submission
    ) -> SubmissionResponse:
        assignment = await self.get_by_id(submission.assignment_id)
        student = await self.db.execute(
            select(User).where(User.id == submission.student_id)
        )
        stu = student.scalar_one_or_none()
        return SubmissionResponse(
            id=submission.id,
            assignment_id=submission.assignment_id,
            assignment_title=assignment.title if assignment else None,
            student_id=submission.student_id,
            student_name=stu.display_name or stu.username if stu else None,
            content=submission.content,
            file_name=submission.file_name,
            file_paths=submission.file_paths,
            status=submission.status,
            score=submission.score,
            teacher_comment=submission.teacher_comment,
            submitted_at=submission.submitted_at.isoformat()
            if submission.submitted_at
            else None,
            graded_at=submission.graded_at.isoformat()
            if submission.graded_at
            else None,
        )
