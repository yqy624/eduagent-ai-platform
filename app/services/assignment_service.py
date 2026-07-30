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
    StoredFile,
    Submission,
    User,
)
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentUpdate,
    AssignmentResponse,
    GradeRequest,
    PeerReviewConfigUpdate,
    PeerReviewResponse,
    PeerReviewSubmit,
    SubmissionResponse,
    AssignmentAnalysis,
)
from app.services.notification_service import NotificationService


class AssignmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, assignment_id: int) -> Optional[Assignment]:
        result = await self.db.execute(
            select(Assignment).where(Assignment.id == assignment_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)

    @staticmethod
    def assignment_status(assignment: Assignment) -> str:
        if assignment.due_date and assignment.due_date < datetime.now():
            return "CLOSED"
        return "PUBLISHED"

    async def ensure_teacher_can_access(
        self, assignment_id: int, teacher: User
    ) -> Assignment:
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")

        course_result = await self.db.execute(
            select(Course).where(Course.id == assignment.course_id)
        )
        course = course_result.scalar_one_or_none()
        if course is None:
            raise ValueError("课程不存在")
        if course.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权访问此作业")
        return assignment

    async def create(self, req: AssignmentCreate, teacher: User) -> Assignment:
        course = await self.db.execute(
            select(Course).where(Course.id == req.course_id)
        )
        course_obj = course.scalar_one_or_none()
        if course_obj is None:
            raise ValueError("课程不存在")
        if course_obj.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权为此课程发布作业")

        duplicate = await self.db.execute(
            select(Assignment).where(
                Assignment.course_id == req.course_id,
                Assignment.title == req.title,
            )
        )
        if duplicate.scalar_one_or_none() is not None:
            raise ValueError("同一课程下已存在同名作业，请勿重复发布")

        due_date = self._parse_datetime(req.due_date)
        if due_date and due_date < datetime.now():
            raise ValueError("截止时间不能早于当前时间")

        peer_review_open = self._parse_datetime(req.peer_review_open_at)
        peer_review_close = self._parse_datetime(req.peer_review_close_at)
        if peer_review_open and peer_review_close and peer_review_close <= peer_review_open:
            raise ValueError("互评截止时间必须晚于开放时间")
        if req.peer_review_required_count is not None and req.peer_review_required_count < 1:
            raise ValueError("每人互评次数至少为 1")

        assignment = Assignment(
            course_id=req.course_id,
            title=req.title,
            description=req.description,
            detail=req.detail,
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
        if assignment.peer_review_enabled:
            await self._generate_peer_reviews(assignment)
        await NotificationService(self.db).create_for_course_students(
            assignment.course_id,
            "新作业已发布",
            f"《{course_obj.name}》发布了作业《{assignment.title}》。",
            category="ASSIGNMENT",
            type_="INFO",
            link=f"/static/student/dashboard.html#assignment-{assignment.id}",
        )
        if assignment.peer_review_enabled:
            await NotificationService(self.db).create_for_course_students(
                assignment.course_id,
                "互评任务已开启",
                f"作业《{assignment.title}》已开启同伴互评。",
                category="PEER_REVIEW",
                type_="INFO",
                link=f"/static/student/dashboard.html#peer-review-{assignment.id}",
            )
        return assignment

    async def update(
        self, assignment_id: int, req: AssignmentUpdate, teacher: User
    ) -> Assignment:
        assignment = await self.ensure_teacher_can_access(assignment_id, teacher)
        update_data = req.model_dump(exclude_unset=True)

        if "title" in update_data and update_data["title"]:
            duplicate = await self.db.execute(
                select(Assignment).where(
                    Assignment.course_id == assignment.course_id,
                    Assignment.title == update_data["title"],
                    Assignment.id != assignment_id,
                )
            )
            if duplicate.scalar_one_or_none() is not None:
                raise ValueError("同一课程下已存在同名作业")

        if "due_date" in update_data:
            assignment.due_date = self._parse_datetime(update_data.pop("due_date"))
            if assignment.due_date and assignment.due_date < datetime.now():
                raise ValueError("截止时间不能早于当前时间")

        for key, value in update_data.items():
            setattr(assignment, key, value)
        await self.db.flush()
        return assignment

    async def delete(self, assignment_id: int, teacher: User):
        assignment = await self.ensure_teacher_can_access(assignment_id, teacher)
        submission_count = (
            await self.db.execute(
                select(func.count(Submission.id)).where(
                    Submission.assignment_id == assignment_id
                )
            )
        ).scalar() or 0
        if submission_count:
            raise ValueError("已有学生提交，不能删除该作业")

        await self.db.execute(
            PeerReview.__table__.delete().where(PeerReview.assignment_id == assignment_id)
        )
        await self.db.delete(assignment)
        await self.db.flush()

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

    async def _get_submission_file(
        self,
        file_ref: Optional[str],
        assignment: Assignment,
        student: User,
        existing_submission: Optional[Submission],
    ) -> Optional[StoredFile]:
        if not file_ref:
            return None
        raw_file_id = str(file_ref).split("::", 1)[0].strip()
        if not raw_file_id.isdecimal():
            raise ValueError("Only file_id is accepted for submission attachments")

        result = await self.db.execute(
            select(StoredFile).where(StoredFile.id == int(raw_file_id))
        )
        stored_file = result.scalar_one_or_none()
        if stored_file is None:
            raise ValueError("File does not exist")
        if student.role != "ADMIN" and stored_file.uploader_user_id != student.id:
            raise ValueError("No permission to use this file")
        if stored_file.category == "ASSIGNMENT_ATTACHMENT":
            raise ValueError("Assignment attachment cannot be used as a submission")
        if stored_file.course_id is not None and stored_file.course_id != assignment.course_id:
            raise ValueError("File does not belong to this course")
        if stored_file.assignment_id is not None and stored_file.assignment_id != assignment.id:
            raise ValueError("File does not belong to this assignment")
        if stored_file.submission_id is not None:
            if existing_submission is None or stored_file.submission_id != existing_submission.id:
                raise ValueError("File is already bound to another submission")
        return stored_file

    async def _bind_submission_file(
        self,
        stored_file: Optional[StoredFile],
        assignment: Assignment,
        submission: Submission,
    ) -> Optional[str]:
        if stored_file is None:
            return None
        stored_file.category = "SUBMISSION_ATTACHMENT"
        stored_file.course_id = assignment.course_id
        stored_file.assignment_id = assignment.id
        stored_file.submission_id = submission.id
        await self.db.flush()
        return f"{stored_file.id}::{stored_file.original_name}"

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
        if assignment.due_date and assignment.due_date < datetime.now():
            raise ValueError("作业已截止，不能提交")

        # 检查是否已选课
        enrollment = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == assignment.course_id,
                Enrollment.student_id == student.id,
            )
        )
        if enrollment.scalar_one_or_none() is None and student.role != "ADMIN":
            raise ValueError("未选修此课程，无法提交作业")

        existing = await self.db.execute(
            select(Submission).where(
                Submission.assignment_id == assignment_id,
                Submission.student_id == student.id,
            )
        )
        existing_submission = existing.scalar_one_or_none()
        stored_file = await self._get_submission_file(
            file_path, assignment, student, existing_submission
        )

        if not content and stored_file is None and not (
            existing_submission and existing_submission.file_paths
        ):
            raise ValueError("提交内容或附件至少填写一项")

        if existing_submission is not None:
            if existing_submission.status == "GRADED":
                raise ValueError("作业已评分，不能重复提交")
            existing_submission.content = content
            existing_submission.status = "SUBMITTED"
            existing_submission.submitted_at = datetime.now()
            stored = await self._bind_submission_file(
                stored_file, assignment, existing_submission
            )
            if stored:
                existing_submission.file_name = stored_file.original_name
                existing_submission.file_paths = stored
            await self.db.flush()
            if assignment.peer_review_enabled:
                await self._generate_peer_reviews(assignment)
            return existing_submission

        submission = Submission(
            assignment_id=assignment_id,
            student_id=student.id,
            content=content,
            file_name=stored_file.original_name if stored_file else file_name,
            file_paths=None,
            status="SUBMITTED",
            submitted_at=datetime.now(),
        )
        self.db.add(submission)
        await self.db.flush()
        stored = await self._bind_submission_file(stored_file, assignment, submission)
        if stored:
            submission.file_paths = stored
            submission.file_name = stored_file.original_name
            await self.db.flush()
        if assignment.peer_review_enabled:
            await self._generate_peer_reviews(assignment)
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
        if req.score > (assignment.total_points or 100):
            raise ValueError("评分不能超过作业满分")

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
        await NotificationService(self.db).create_for_user_ids(
            [submission.student_id],
            "作业评分已完成",
            f"《{course_obj.name}》的作业《{assignment.title}》已完成评分。",
            category="GRADE",
            type_="INFO",
            link=f"/static/student/dashboard.html#grade-{submission.id}",
        )
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
            enrollment.score = float(total) + float(enrollment.peer_review_bonus or 0)
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
            score_distribution=self._score_distribution(
                [float(s.score) for s in graded if s.score is not None],
                assignment.total_points or 100,
            ),
        )

    @staticmethod
    def _score_distribution(scores: List[float], total_points: int) -> Dict[str, int]:
        if not scores:
            return {}
        buckets = {
            "0-59%": 0,
            "60-69%": 0,
            "70-79%": 0,
            "80-89%": 0,
            "90-100%": 0,
        }
        total = total_points or 100
        for score in scores:
            pct = score / total * 100 if total else 0
            if pct < 60:
                buckets["0-59%"] += 1
            elif pct < 70:
                buckets["60-69%"] += 1
            elif pct < 80:
                buckets["70-79%"] += 1
            elif pct < 90:
                buckets["80-89%"] += 1
            else:
                buckets["90-100%"] += 1
        return buckets

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
                PeerReview.status.in_(["SUBMITTED", "BONUS_GRANTED"]),
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
            "prompt": assignment.peer_review_prompt,
            "totalReviews": submitted_count,
            "grantedCount": granted_count,
            "totalAssignments": total,
            "submittedCount": submitted_count,
            "pendingCount": total - submitted_count,
        }

    async def update_peer_review(
        self,
        assignment_id: int,
        req: PeerReviewConfigUpdate,
        teacher: User,
    ) -> Dict[str, Any]:
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")

        course_result = await self.db.execute(
            select(Course).where(Course.id == assignment.course_id)
        )
        course = course_result.scalar_one_or_none()
        if course is None:
            raise ValueError("课程不存在")
        if course.teacher_id != teacher.id and teacher.role != "ADMIN":
            raise ValueError("无权配置此作业的互评")

        was_peer_review_enabled = bool(assignment.peer_review_enabled)
        assignment.peer_review_enabled = req.peer_review_enabled
        assignment.peer_review_open_at = self._parse_datetime(req.peer_review_open_at)
        assignment.peer_review_close_at = self._parse_datetime(req.peer_review_close_at)
        if (
            assignment.peer_review_open_at
            and assignment.peer_review_close_at
            and assignment.peer_review_close_at <= assignment.peer_review_open_at
        ):
            raise ValueError("互评截止时间必须晚于开放时间")
        assignment.peer_review_required_count = req.peer_review_required_count or 1
        assignment.peer_review_bonus_per_review = req.peer_review_bonus_per_review
        assignment.peer_review_bonus_cap = req.peer_review_bonus_cap
        assignment.peer_review_prompt = req.peer_review_prompt
        await self.db.flush()
        if assignment.peer_review_enabled:
            await self._generate_peer_reviews(assignment)
        if assignment.peer_review_enabled and not was_peer_review_enabled:
            await NotificationService(self.db).create_for_course_students(
                assignment.course_id,
                "互评任务已开启",
                f"作业《{assignment.title}》已开启同伴互评。",
                category="PEER_REVIEW",
                type_="INFO",
                link=f"/static/student/dashboard.html#peer-review-{assignment.id}",
            )
        return await self.get_peer_review_overview(assignment_id)

    async def _generate_peer_reviews(self, assignment: Assignment):
        required = max(1, assignment.peer_review_required_count or 1)
        result = await self.db.execute(
            select(Submission)
            .where(
                Submission.assignment_id == assignment.id,
                Submission.status.in_(["SUBMITTED", "GRADED"]),
            )
            .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        )
        submissions = list(result.scalars().all())
        if len(submissions) < 2:
            return

        existing_result = await self.db.execute(
            select(PeerReview).where(PeerReview.assignment_id == assignment.id)
        )
        existing_reviews = list(existing_result.scalars().all())
        existing_pairs = {
            (review.reviewer_id, review.target_submission_id)
            for review in existing_reviews
        }
        existing_counts: Dict[int, int] = {}
        for review in existing_reviews:
            existing_counts[review.reviewer_id] = (
                existing_counts.get(review.reviewer_id, 0) + 1
            )

        max_targets = min(required, len(submissions) - 1)
        for index, reviewer_submission in enumerate(submissions):
            created = existing_counts.get(reviewer_submission.student_id, 0)
            offset = 1
            while created < max_targets and offset < len(submissions):
                target = submissions[(index + offset) % len(submissions)]
                offset += 1
                if target.student_id == reviewer_submission.student_id:
                    continue
                pair = (reviewer_submission.student_id, target.id)
                if pair in existing_pairs:
                    continue
                self.db.add(
                    PeerReview(
                        assignment_id=assignment.id,
                        reviewer_id=reviewer_submission.student_id,
                        target_submission_id=target.id,
                        status="ASSIGNED",
                        assigned_at=datetime.now(),
                    )
                )
                existing_pairs.add(pair)
                created += 1
        await self.db.flush()

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
