"""Allow-listed, role-aware tools used by the Agent runtime."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Assignment, Course, Enrollment, Submission, User
from app.services.ai_tool_service import AiToolService
from ai.tools.notification_tools import NotificationTools


class AgentToolError(Exception):
    """Expected tool failure that can be shown in an execution trace."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    required_args: Set[str]
    optional_args: Set[str]
    allowed_roles: Set[str]
    read_only: bool
    requires_confirmation: bool
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

    def normalize_args(self, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        values = dict(args or {})
        unknown = set(values) - self.required_args - self.optional_args
        if unknown:
            raise AgentToolError(
                f"Tool {self.name} received unsupported arguments: {sorted(unknown)}"
            )
        missing = self.required_args - set(values)
        if missing:
            raise AgentToolError(
                f"Tool {self.name} is missing required arguments: {sorted(missing)}"
            )
        return values


class AgentToolRegistry:
    """Central registry. No model output can call an unregistered function."""

    def __init__(
        self,
        db: AsyncSession,
        user: User,
        service: AiToolService,
        retrieve_materials: Optional[
            Callable[[int, str], Awaitable[List[Dict[str, Any]]]]
        ] = None,
    ):
        self.db = db
        self.user = user
        self.service = service
        self.retrieve_materials = retrieve_materials
        self.notification_tools = NotificationTools(db)
        self._tools = self._build_tools()

    def specs(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "required_args": sorted(tool.required_args),
                "optional_args": sorted(tool.optional_args),
                "read_only": tool.read_only,
                "requires_confirmation": tool.requires_confirmation,
            }
            for tool in self._tools.values()
            if self.user.role in tool.allowed_roles
        ]

    def get(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise AgentToolError(f"Unknown tool: {name}")
        if self.user.role not in tool.allowed_roles:
            raise AgentToolError(f"Role {self.user.role} cannot use tool {name}")
        return tool

    def prepare(self, name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return self.get(name).normalize_args(args)

    async def execute(self, name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        tool = self.get(name)
        return await tool.handler(tool.normalize_args(args))

    async def _ensure_course_access(self, course_id: int) -> Course:
        result = await self.db.execute(select(Course).where(Course.id == course_id))
        course = result.scalar_one_or_none()
        if course is None:
            raise AgentToolError("Course not found")
        if self.user.role == "ADMIN":
            return course
        if self.user.role == "TEACHER" and course.teacher_id == self.user.id:
            return course
        if self.user.role == "STUDENT":
            enrolled = await self.db.execute(
                select(Enrollment.id).where(
                    Enrollment.course_id == course_id,
                    Enrollment.student_id == self.user.id,
                )
            )
            if enrolled.scalar_one_or_none() is not None:
                return course
        raise AgentToolError("You do not have access to this course")

    async def _get_course_overview(self, args: Dict[str, Any]) -> Dict[str, Any]:
        course_id = args.get("course_id")
        if course_id is not None:
            course = await self._ensure_course_access(int(course_id))
            return {
                "course": {
                    "id": course.id,
                    "name": course.name,
                    "description": course.description,
                    "schedule": course.schedule,
                    "credits": course.credits,
                    "category": course.category,
                }
            }
        if self.user.role == "STUDENT":
            rows = await self.db.execute(
                select(Course)
                .join(Enrollment, Enrollment.course_id == Course.id)
                .where(Enrollment.student_id == self.user.id)
                .order_by(Course.id.desc())
            )
        else:
            query = select(Course).order_by(Course.id.desc())
            if self.user.role == "TEACHER":
                query = query.where(Course.teacher_id == self.user.id)
            rows = await self.db.execute(query)
        return {
            "courses": [
                {"id": c.id, "name": c.name, "description": c.description}
                for c in rows.scalars().all()
            ]
        }

    async def _get_course_assignments(self, args: Dict[str, Any]) -> Dict[str, Any]:
        course_id = int(args["course_id"])
        await self._ensure_course_access(course_id)
        if self.user.role == "STUDENT":
            rows = await self.db.execute(
                select(Assignment, Submission)
                .outerjoin(
                    Submission,
                    (Submission.assignment_id == Assignment.id)
                    & (Submission.student_id == self.user.id),
                )
                .where(Assignment.course_id == course_id)
                .order_by(Assignment.due_date.asc(), Assignment.id.desc())
                .limit(20)
            )
            assignments = [
                self._assignment_status_payload(assignment, submission)
                for assignment, submission in rows
            ]
        else:
            rows = await self.db.execute(
                select(Assignment)
                .where(Assignment.course_id == course_id)
                .order_by(Assignment.due_date.asc(), Assignment.id.desc())
                .limit(20)
            )
            assignments = [
                self._assignment_payload(assignment)
                for assignment in rows.scalars().all()
            ]
        return {
            "course_id": course_id,
            "assignments": assignments,
        }

    async def _get_my_grades(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.user.role != "STUDENT":
            raise AgentToolError("get_my_grades is currently available to students")
        course_id = args.get("course_id")
        query = (
            select(Submission, Assignment)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Submission.student_id == self.user.id)
            .order_by(Submission.graded_at.desc(), Submission.id.desc())
        )
        if course_id is not None:
            await self._ensure_course_access(int(course_id))
            query = query.where(Assignment.course_id == int(course_id))
        rows = await self.db.execute(query.limit(30))
        grades = []
        for submission, assignment in rows:
            grades.append(
                {
                    "assignment_id": assignment.id,
                    "title": assignment.title,
                    "score": submission.score,
                    "total_points": assignment.total_points,
                    "status": submission.status,
                    "teacher_comment": submission.teacher_comment,
                }
            )
        return {"grades": grades}

    async def _get_my_submissions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.user.role != "STUDENT":
            raise AgentToolError("get_my_submissions is currently available to students")
        course_id = args.get("course_id")
        query = (
            select(Assignment, Course, Submission)
            .join(Course, Course.id == Assignment.course_id)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .outerjoin(
                Submission,
                (Submission.assignment_id == Assignment.id)
                & (Submission.student_id == self.user.id),
            )
            .where(Enrollment.student_id == self.user.id)
        )
        if course_id is not None:
            await self._ensure_course_access(int(course_id))
            query = query.where(Assignment.course_id == int(course_id))
        rows = await self.db.execute(
            query.order_by(Assignment.due_date.asc(), Assignment.id.desc()).limit(50)
        )
        assignment_statuses = [
            {
                **self._assignment_status_payload(assignment, submission),
                "course_id": course.id,
                "course_name": course.name,
            }
            for assignment, course, submission in rows
        ]
        submitted = [
            item
            for item in assignment_statuses
            if item["submission_status"] in {"SUBMITTED", "GRADED"}
        ]
        not_submitted = [
            item
            for item in assignment_statuses
            if item["submission_status"] == "NOT_SUBMITTED"
        ]
        return {
            "course_id": int(course_id) if course_id is not None else None,
            "assignment_statuses": assignment_statuses,
            "submissions": submitted,
            "not_submitted_assignments": not_submitted,
            "submitted_count": len(submitted),
            "not_submitted_count": len(not_submitted),
            "total_assignment_count": len(assignment_statuses),
        }

    def _assignment_payload(self, assignment: Assignment) -> Dict[str, Any]:
        return {
            "id": assignment.id,
            "title": assignment.title,
            "description": assignment.description,
            "detail": assignment.detail,
            "due_date": assignment.due_date.isoformat()
            if assignment.due_date
            else None,
            "total_points": assignment.total_points,
        }

    def _assignment_status_payload(
        self,
        assignment: Assignment,
        submission: Optional[Submission],
    ) -> Dict[str, Any]:
        status = submission.status if submission else "NOT_SUBMITTED"
        return {
            **self._assignment_payload(assignment),
            "assignment_id": assignment.id,
            "submission_id": submission.id if submission else None,
            "submission_status": status,
            "status": status,
            "score": submission.score if submission else None,
            "submitted_at": (
                submission.submitted_at.isoformat()
                if submission and submission.submitted_at
                else None
            ),
            "graded_at": (
                submission.graded_at.isoformat()
                if submission and submission.graded_at
                else None
            ),
        }

    async def _retrieve_materials(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.retrieve_materials is None:
            raise AgentToolError("Course material retrieval is not configured")
        course_id = int(args["course_id"])
        await self._ensure_course_access(course_id)
        citations = await self.retrieve_materials(course_id, str(args["question"]))
        return {"course_id": course_id, "hit_count": len(citations), "citations": citations}

    async def _analyze_learning_gaps(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.user.role != "STUDENT":
            raise AgentToolError("Learning gap analysis is currently student-scoped")
        course_id = args.get("course_id")
        grades = (await self._get_my_grades({"course_id": course_id})).get("grades", [])
        scored = [
            item for item in grades
            if item.get("score") is not None and item.get("total_points")
        ]
        weak = [
            item for item in scored
            if float(item["score"]) / float(item["total_points"]) * 100 < 60
        ]
        average = (
            sum(float(item["score"]) / float(item["total_points"]) * 100 for item in scored)
            / len(scored)
            if scored else None
        )
        return {
            "graded_count": len(scored),
            "average_percentage": round(average, 2) if average is not None else None,
            "weak_assignments": weak,
            "summary": "需要优先复习低分作业对应知识点" if weak else "暂未发现明显低分作业",
        }

    async def _generate_learning_plan(self, args: Dict[str, Any]) -> Dict[str, Any]:
        course_id = int(args["course_id"])
        await self._ensure_course_access(course_id)
        gaps = await self._analyze_learning_gaps({"course_id": course_id})
        assignments = (await self._get_course_assignments({"course_id": course_id})).get(
            "assignments", []
        )
        weak_titles = {item.get("title") for item in gaps["weak_assignments"]}
        tasks = []
        for index, assignment in enumerate(assignments[:5], start=1):
            focus = "复习并完成"
            if assignment["title"] in weak_titles:
                focus = "重点复习并订正"
            tasks.append(
                {
                    "day": index,
                    "focus": f"{focus}：{assignment['title']}",
                    "duration_hours": 1.0 if assignment["title"] in weak_titles else 0.5,
                    "priority": "HIGH" if assignment["title"] in weak_titles else "NORMAL",
                }
            )
        return {
            "course_id": course_id,
            "focus": args.get("focus") or "根据成绩和待办作业动态安排",
            "weakness": gaps,
            "daily_tasks": tasks,
            "total_hours": round(sum(item["duration_hours"] for item in tasks), 1),
        }

    async def _get_course_statistics(self, args: Dict[str, Any]) -> Dict[str, Any]:
        course_id = int(args["course_id"])
        await self._ensure_course_access(course_id)
        enrolled = await self.db.execute(
            select(func.count(Enrollment.id)).where(Enrollment.course_id == course_id)
        )
        assignment_count = await self.db.execute(
            select(func.count(Assignment.id)).where(Assignment.course_id == course_id)
        )
        submitted = await self.db.execute(
            select(func.count(Submission.id))
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Assignment.course_id == course_id, Submission.status == "SUBMITTED")
        )
        graded = await self.db.execute(
            select(func.count(Submission.id))
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Assignment.course_id == course_id, Submission.status == "GRADED")
        )
        average = await self.db.execute(
            select(func.avg(Submission.score))
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Assignment.course_id == course_id, Submission.score.isnot(None))
        )
        average_score = average.scalar()
        return {
            "course_id": course_id,
            "student_count": enrolled.scalar() or 0,
            "assignment_count": assignment_count.scalar() or 0,
            "pending_grading": submitted.scalar() or 0,
            "graded_count": graded.scalar() or 0,
            "average_score": (
                float(average_score) if average_score is not None else None
            ),
        }

    async def _send_notification(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.notification_tools.send_notification(
            recipient_username=str(args["recipient_username"]),
            title=str(args["title"]),
            content=str(args["content"]),
            category=str(args.get("category") or "SYSTEM"),
            link=args.get("link"),
        )
        return {"sent": True, **result}

    def _build_tools(self) -> Dict[str, ToolDefinition]:
        everyone = {"ADMIN", "TEACHER", "STUDENT"}
        students = {"STUDENT"}
        staff = {"ADMIN", "TEACHER"}
        return {
            "get_course_overview": ToolDefinition(
                "get_course_overview",
                "Read course metadata or the courses visible to the current user.",
                set(),
                {"course_id"},
                everyone,
                True,
                False,
                self._get_course_overview,
            ),
            "get_course_assignments": ToolDefinition(
                "get_course_assignments",
                "Read assignments and due dates for an accessible course.",
                {"course_id"},
                set(),
                everyone,
                True,
                False,
                self._get_course_assignments,
            ),
            "retrieve_course_material": ToolDefinition(
                "retrieve_course_material",
                "Retrieve indexed course material with citations.",
                {"course_id", "question"},
                set(),
                everyone,
                True,
                False,
                self._retrieve_materials,
            ),
            "get_my_grades": ToolDefinition(
                "get_my_grades",
                "Read the current student's graded submissions.",
                set(),
                {"course_id"},
                students,
                True,
                False,
                self._get_my_grades,
            ),
            "get_my_submissions": ToolDefinition(
                "get_my_submissions",
                "Read the current student's submission status.",
                set(),
                {"course_id"},
                students,
                True,
                False,
                self._get_my_submissions,
            ),
            "analyze_learning_gaps": ToolDefinition(
                "analyze_learning_gaps",
                "Compute low-score areas and a bounded learning diagnosis.",
                set(),
                {"course_id"},
                students,
                True,
                False,
                self._analyze_learning_gaps,
            ),
            "generate_learning_plan": ToolDefinition(
                "generate_learning_plan",
                "Create a study plan from grades, weaknesses, and assignments.",
                {"course_id"},
                {"focus"},
                students,
                True,
                False,
                self._generate_learning_plan,
            ),
            "get_course_statistics": ToolDefinition(
                "get_course_statistics",
                "Read teaching statistics for a course visible to the teacher.",
                {"course_id"},
                set(),
                staff,
                True,
                False,
                self._get_course_statistics,
            ),
            "send_notification": ToolDefinition(
                "send_notification",
                "Send a notification to a user after explicit confirmation.",
                {"recipient_username", "title", "content"},
                {"category", "link"},
                staff,
                False,
                True,
                self._send_notification,
            ),
        }
