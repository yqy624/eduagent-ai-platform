"""学生服务"""
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

        # 已提交待批改
        pending = (await self.db.execute(
            select(func.count(Submission.id)).where(
                Submission.student_id == student.id, Submission.status == "SUBMITTED"
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
        for sub, ass, course in recent_raw:
            recent_grades.append({
                "courseName": course.name,
                "assignmentTitle": ass.title,
                "score": sub.score,
            })

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
            "recent_grades": recent_grades,
            "score_trend": [],
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
                "submissionStatus": sub_obj.status if sub_obj else "NOT_SUBMITTED",
                "submissionId": sub_obj.id if sub_obj else None,
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

        review.rating = rating
        review.comment = comment
        review.status = "SUBMITTED"
        review.submitted_at = datetime.now()
        await self.db.flush()
        return await self._to_peer_review_response(review)

    async def get_my_grades(self, student: User) -> List[StudentGradeResponse]:
        enrollments = await self.db.execute(
            select(Enrollment).where(Enrollment.student_id == student.id)
        )
        enrollments = list(enrollments.scalars().all())

        result = []
        for enr in enrollments:
            course = await self.course_service.get_by_id(enr.course_id)
            submissions = await self.db.execute(
                select(Submission).where(
                    Submission.student_id == student.id,
                    Submission.assignment_id.in_(
                        select(Assignment.id).where(
                            Assignment.course_id == enr.course_id
                        )
                    ),
                )
            )
            subs = list(submissions.scalars().all())
            assignments_data = []
            for sub in subs:
                ass = await self.assignment_service.get_by_id(sub.assignment_id)
                assignments_data.append({
                    "assignment_id": sub.assignment_id,
                    "assignment_title": ass.title if ass else None,
                    "score": sub.score,
                    "status": sub.status,
                    "comment": sub.teacher_comment,
                    "submitted_at": sub.submitted_at.isoformat()
                    if sub.submitted_at
                    else None,
                })

            result.append(
                StudentGradeResponse(
                    course_id=enr.course_id,
                    course_name=course.name if course else None,
                    assignments=assignments_data,
                    course_average=enr.base_score if enr.base_score else 0,
                    peer_review_bonus=enr.peer_review_bonus or 0,
                )
            )
        return result

    async def get_course_average(self, course_id: int) -> float:
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
