"""学生服务"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import func, or_, select
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
    AssignmentResponse,
    CourseResponse,
    PeerReviewResponse,
    PeerReviewSubmit,
    StudentDashboard,
    StudentGradeResponse,
    SubmissionResponse,
)
from app.services.course_service import CourseService
from app.services.assignment_service import AssignmentService


class StudentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.course_service = CourseService(db)
        self.assignment_service = AssignmentService(db)

    async def get_dashboard(self, student: User) -> Dict[str, Any]:
        """返回前端兼容的学生仪表盘"""
        courses = await self.course_service.get_student_courses(student.id)
        course_ids = [c.id for c in courses]

        # 已选课程中尚未提交且未截止的作业
        pending = 0
        if course_ids:
            pending = (await self.db.execute(
                select(func.count(Assignment.id)).where(
                    Assignment.course_id.in_(course_ids),
                    or_(Assignment.due_date.is_(None), Assignment.due_date >= datetime.now()),
                    Assignment.id.not_in(
                        select(Submission.assignment_id).where(
                            Submission.student_id == student.id
                        )
                    ),
                )
            )).scalar() or 0

        submitted_pending = (await self.db.execute(
            select(func.count(Submission.id)).where(
                Submission.student_id == student.id,
                Submission.status == "SUBMITTED",
            )
        )).scalar() or 0

        # 已评分
        graded = (await self.db.execute(
            select(func.count(Submission.id)).where(
                Submission.student_id == student.id, Submission.status == "GRADED"
            )
        )).scalar() or 0

        # 互评加分
        bonus = (await self.db.execute(
            select(func.coalesce(func.sum(Enrollment.peer_review_bonus), 0))
            .where(Enrollment.student_id == student.id)
        )).scalar() or 0

        # 最近成绩
        recent_raw = await self.db.execute(
            select(Submission, Assignment, Course)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .join(Course, Assignment.course_id == Course.id)
            .where(
                Submission.student_id == student.id,
                Submission.status == "GRADED",
                Submission.score.isnot(None),
            )
            .order_by(Submission.graded_at.desc())
            .limit(6)
        )
        recent_grades = []
        score_trend = []
        for sub, ass, course in recent_raw:
            recent_grades.append({
                "courseName": course.name,
                "assignmentTitle": ass.title,
                "score": sub.score,
            })
            score_trend.append({
                "name": ass.title,
                "value": sub.score,
            })
        score_trend.reverse()

        # 近期活动
        from app.models.models import PublishedActivity
        acts_raw = await self.db.execute(
            select(PublishedActivity)
            .order_by(PublishedActivity.created_at.desc())
            .limit(10)
        )
        activities = [
            {"title": a.title, "content": a.content,
             "createdAt": a.created_at.isoformat() if a.created_at else None,
             "publishedAt": a.published_at.isoformat() if a.published_at else None}
            for a in acts_raw.scalars().all()
        ]

        return {
            "selected_course_count": len(courses),
            "graded_count": graded,
            "peer_review_bonus": float(bonus),
            "pending_count": pending,
            "submitted_pending_count": submitted_pending,
            "recent_grades": recent_grades,
            "score_trend": score_trend,
            "recent_activities": activities,
        }

    async def get_all_courses(self) -> List[CourseResponse]:
        courses = await self.course_service.get_all_visible()
        return [await self.course_service.to_response(c) for c in courses]

    async def get_my_courses(self, student: User) -> List[CourseResponse]:
        courses = await self.course_service.get_student_courses(student.id)
        return [await self.course_service.to_response(c) for c in courses]

    async def enroll(self, course_id: int, student: User):
        course = await self.course_service.get_by_id(course_id)
        if course is None:
            raise ValueError("课程不存在")
        if not course.visible:
            raise ValueError("该课程不可选")

        existing = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("已选过此课程")

        if course.enrolled_count >= course.max_students:
            raise ValueError("课程已满员")

        enrollment = Enrollment(
            course_id=course_id,
            student_id=student.id,
            enrolled_at=datetime.now(),
            score=0,
            base_score=0,
            peer_review_bonus=0,
        )
        self.db.add(enrollment)
        course.enrolled_count += 1
        await self.db.flush()

    async def drop(self, course_id: int, student: User):
        result = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student.id,
            )
        )
        enrollment = result.scalar_one_or_none()
        if enrollment is None:
            raise ValueError("未选此课程")
        await self.db.delete(enrollment)

        course = await self.course_service.get_by_id(course_id)
        if course and course.enrolled_count > 0:
            course.enrolled_count -= 1
        await self.db.flush()

    async def get_my_assignments(
        self, course_id: int, student: User
    ) -> List[Dict[str, Any]]:
        # 验证是否已选课
        enrollment = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student.id,
            )
        )
        if enrollment.scalar_one_or_none() is None and student.role != "ADMIN":
            raise ValueError("未选修此课程")

        assignments = await self.assignment_service.get_course_assignments(course_id)
        result = []
        for a in assignments:
            # 查询提交状态
            sub = await self.db.execute(
                select(Submission).where(
                    Submission.assignment_id == a.id,
                    Submission.student_id == student.id,
                )
            )
            sub_obj = sub.scalar_one_or_none()
            result.append({
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "dueDate": a.due_date.isoformat() if a.due_date else None,
                "totalPoints": a.total_points,
                "courseId": a.course_id,
                "teacherId": a.teacher_id,
                "createdAt": a.created_at.isoformat() if a.created_at else None,
                "peerReviewEnabled": a.peer_review_enabled,
                "status": self.assignment_service.assignment_status(a),
                "submissionStatus": sub_obj.status if sub_obj else "NOT_SUBMITTED",
                "submissionId": sub_obj.id if sub_obj else None,
                "content": sub_obj.content if sub_obj else None,
                "filePaths": sub_obj.file_paths if sub_obj else None,
                "fileName": sub_obj.file_name if sub_obj else None,
                "score": sub_obj.score if sub_obj else None,
                "teacherComment": sub_obj.teacher_comment if sub_obj else None,
                "submittedAt": sub_obj.submitted_at.isoformat() if sub_obj and sub_obj.submitted_at else None,
                "gradedAt": sub_obj.graded_at.isoformat() if sub_obj and sub_obj.graded_at else None,
            })
        return result

    async def submit_assignment(
        self,
        assignment_id: int,
        student: User,
        content: Optional[str] = None,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> SubmissionResponse:
        submission = await self.assignment_service.submit(
            assignment_id, student, content, file_path, file_name
        )
        return await self.assignment_service.to_submission_response(submission)

    async def get_my_peer_reviews(self, student: User) -> List[Dict[str, Any]]:
        """返回前端兼容的互评分组列表"""
        result = await self.db.execute(
            select(PeerReview).where(PeerReview.reviewer_id == student.id)
        )
        reviews = list(result.scalars().all())
        if not reviews:
            return []

        # 按 assignment 分组
        from collections import defaultdict
        groups = defaultdict(list)
        for r in reviews:
            groups[r.assignment_id].append(r)

        output = []
        for assignment_id, review_list in groups.items():
            assignment = await self.assignment_service.get_by_id(assignment_id)
            if not assignment:
                continue

            course = await self.db.execute(select(Course).where(Course.id == assignment.course_id))
            course_obj = course.scalar_one_or_none()

            completed = sum(1 for r in review_list if r.status in ("SUBMITTED", "BONUS_GRANTED"))
            required = assignment.peer_review_required_count or 1
            bonus_earned = sum(assignment.peer_review_bonus_per_review or 0 for r in review_list if r.status == "BONUS_GRANTED")

            # 构建每个 review 的详情
            reviews_data = []
            for r in review_list:
                target = None
                if r.target_submission_id:
                    t_sub = await self.db.execute(
                        select(Submission).where(Submission.id == r.target_submission_id)
                    )
                    t_sub_obj = t_sub.scalar_one_or_none()
                    if t_sub_obj:
                        t_stu = await self.db.execute(
                            select(User).where(User.id == t_sub_obj.student_id)
                        )
                        t_stu_obj = t_stu.scalar_one_or_none()
                        target = {
                            "submissionId": t_sub_obj.id,
                            "studentName": t_stu_obj.display_name or t_stu_obj.username if t_stu_obj else "同学",
                            "content": t_sub_obj.content or "",
                            "filePaths": t_sub_obj.file_paths,
                            "submittedAt": t_sub_obj.submitted_at.isoformat() if t_sub_obj.submitted_at else None,
                        }

                reviews_data.append({
                    "status": r.status,
                    "rating": r.rating,
                    "comment": r.comment or "",
                    "submittedAt": r.submitted_at.isoformat() if r.submitted_at else None,
                    "selectedTarget": target,
                    "candidateTargets": [target] if target else [],
                    "preview": target["content"][:100] if target else "",
                })

            output.append({
                "assignmentId": assignment.id,
                "courseName": course_obj.name if course_obj else "未知课程",
                "assignmentTitle": assignment.title,
                "prompt": assignment.peer_review_prompt or "请根据作业质量给出客观、具体的匿名评价。",
                "requiredCount": required,
                "completedCount": completed,
                "bonusEarned": float(bonus_earned),
                "reviews": reviews_data,
            })

        return output

    async def submit_peer_review(
        self,
        student: User,
        assignment_id: int,
        target_submission_id: int,
        rating: int,
        comment: Optional[str] = None,
    ) -> PeerReviewResponse:
        result = await self.db.execute(
            select(PeerReview).where(
                PeerReview.assignment_id == assignment_id,
                PeerReview.reviewer_id == student.id,
                PeerReview.target_submission_id == target_submission_id,
            )
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise ValueError("未分配此互评任务")
        if review.status != "ASSIGNED":
            raise ValueError("此互评任务已完成或已过期")
        if not comment or len(comment.strip()) < 10:
            raise ValueError("互评内容不能少于 10 个字")

        assignment = await self.assignment_service.get_by_id(assignment_id)
        if assignment is None:
            raise ValueError("作业不存在")
        if not assignment.peer_review_enabled:
            raise ValueError("此作业未开启互评")
        now = datetime.now()
        if assignment.peer_review_open_at and now < assignment.peer_review_open_at:
            raise ValueError("互评尚未开放")
        if assignment.peer_review_close_at and now > assignment.peer_review_close_at:
            raise ValueError("互评已截止")

        target = await self.db.execute(
            select(Submission).where(
                Submission.id == target_submission_id,
                Submission.assignment_id == assignment_id,
            )
        )
        target_submission = target.scalar_one_or_none()
        if target_submission is None:
            raise ValueError("被评提交不存在")
        if target_submission.student_id == student.id:
            raise ValueError("不能评价自己的作业")

        review.rating = rating
        review.comment = comment.strip()
        review.submitted_at = datetime.now()
        granted = await self._grant_peer_review_bonus(review, assignment)
        review.status = "BONUS_GRANTED" if granted > 0 else "SUBMITTED"
        await self.db.flush()
        return await self._to_peer_review_response(review)

    async def _grant_peer_review_bonus(
        self, review: PeerReview, assignment: Assignment
    ) -> float:
        per_review = float(assignment.peer_review_bonus_per_review or 0)
        cap = float(assignment.peer_review_bonus_cap or 0)
        if per_review <= 0 or cap <= 0:
            return 0

        granted_count = (
            await self.db.execute(
                select(func.count(PeerReview.id)).where(
                    PeerReview.assignment_id == assignment.id,
                    PeerReview.reviewer_id == review.reviewer_id,
                    PeerReview.status == "BONUS_GRANTED",
                )
            )
        ).scalar() or 0
        already_granted = float(granted_count) * per_review
        grant = max(0.0, min(per_review, cap - already_granted))
        if grant <= 0:
            return 0

        enrollment_result = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == assignment.course_id,
                Enrollment.student_id == review.reviewer_id,
            )
        )
        enrollment = enrollment_result.scalar_one_or_none()
        if enrollment is None:
            return 0

        enrollment.peer_review_bonus = float(enrollment.peer_review_bonus or 0) + grant
        enrollment.score = float(enrollment.base_score or 0) + float(enrollment.peer_review_bonus or 0)
        return grant

    async def get_my_grades(self, student: User) -> List[Dict[str, Any]]:
        rows = await self.db.execute(
            select(Submission, Assignment, Course, Enrollment)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .join(Course, Assignment.course_id == Course.id)
            .join(
                Enrollment,
                (Enrollment.course_id == Course.id)
                & (Enrollment.student_id == Submission.student_id),
            )
            .where(Submission.student_id == student.id)
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        )

        result = []
        for sub, assignment, course, enrollment in rows:
            teacher_score = sub.score if sub.status == "GRADED" else None
            peer_bonus = float(enrollment.peer_review_bonus or 0)
            result.append({
                "id": sub.id,
                "submissionId": sub.id,
                "assignmentId": assignment.id,
                "assignmentTitle": assignment.title,
                "courseId": course.id,
                "courseName": course.name,
                "content": sub.content,
                "filePaths": sub.file_paths,
                "fileName": sub.file_name,
                "status": sub.status,
                "teacherScore": teacher_score,
                "peerReviewBonus": peer_bonus,
                "score": (float(teacher_score) + peer_bonus) if teacher_score is not None else None,
                "teacherComment": sub.teacher_comment,
                "submittedAt": sub.submitted_at.isoformat() if sub.submitted_at else None,
                "gradedAt": sub.graded_at.isoformat() if sub.graded_at else None,
            })
        return result

    async def get_course_average(self, course_id: int, student: User) -> float:
        enrollment = await self.db.execute(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student.id,
            )
        )
        if enrollment.scalar_one_or_none() is None and student.role != "ADMIN":
            raise ValueError("未选修此课程")

        result = await self.db.execute(
            select(func.avg(Submission.score)).where(
                Submission.status == "GRADED",
                Submission.score.isnot(None),
                Submission.assignment_id.in_(
                    select(Assignment.id).where(Assignment.course_id == course_id)
                ),
            )
        )
        val = result.scalar()
        return float(val) if val is not None else -1

    async def _to_peer_review_response(
        self, review: PeerReview
    ) -> PeerReviewResponse:
        return PeerReviewResponse(
            id=review.id,
            assignment_id=review.assignment_id,
            reviewer_id=review.reviewer_id,
            target_submission_id=review.target_submission_id,
            rating=review.rating,
            comment=review.comment,
            status=review.status,
            submitted_at=review.submitted_at.isoformat()
            if review.submitted_at
            else None,
        )
