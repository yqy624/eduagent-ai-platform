"""Learning-plan Agent workflow implemented with LangChain runnables."""
import json
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.runnables import RunnableBranch, RunnableLambda

from app.services.ai_tool_service import AiToolService


class LearningPlanState(TypedDict):
    run_id: int
    user_id: int
    student_id: int
    course_id: int
    role: str
    profile: Optional[Dict[str, Any]]
    grades: Optional[List[Dict[str, Any]]]
    submissions: Optional[List[Dict[str, Any]]]
    weakness: Optional[Dict[str, Any]]
    retrieved_materials: Optional[List[Dict[str, Any]]]
    plan: Optional[Dict[str, Any]]
    exercises: Optional[List[Dict[str, Any]]]
    validation_errors: Optional[List[str]]
    tool_trace: Optional[List[Dict[str, Any]]]
    final_report: Optional[Dict[str, Any]]
    error: Optional[str]


def _score_ratio(record: Dict[str, Any]) -> float:
    score = float(record.get("score") or 0)
    total = float(record.get("total_points") or 100)
    return score / max(total, 1) * 100


def _material_names(materials: Optional[List[Dict[str, Any]]]) -> List[str]:
    names: List[str] = []
    seen = set()
    for item in materials or []:
        source = str(item.get("source") or item.get("name") or "").strip()
        if not source:
            continue
        chunk_count = item.get("chunk_count")
        label = f"{source} ({chunk_count} chunks)" if chunk_count else source
        if label not in seen:
            seen.add(label)
            names.append(label)
    return names


async def collect_profile(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    profile = await service.get_student_profile(state["student_id"])
    await service.log_tool_call_json(
        state.get("run_id"),
        "collect_profile",
        {"student_id": state["student_id"]},
        {
            "course_count": len(profile.get("courses", [])),
            "grade_count": len(profile.get("grades", [])),
        },
    )
    return {
        "profile": profile,
        "grades": profile.get("grades", []),
        "submissions": [],
        "tool_trace": [
            {
                "node": "collect_profile",
                "result": f"Loaded profile with {len(profile.get('grades', []))} grade records",
            }
        ],
    }


async def analyze_weakness(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    profile = state.get("profile") or {}
    low_scores = profile.get("low_score_assignments", [])
    weakness_areas = []
    for record in low_scores:
        ratio = round(_score_ratio(record), 1)
        weakness_areas.append(
            {
                "assignment": record.get("assignment_title") or "Untitled assignment",
                "score": record.get("score"),
                "total": record.get("total_points") or 100,
                "ratio": ratio,
                "level": "high" if ratio < 60 else "medium",
            }
        )

    graded = [g for g in profile.get("grades", []) if g.get("score") is not None]
    pass_count = sum(1 for g in graded if _score_ratio(g) >= 60)
    summary = (
        f"{len(graded)} graded assignments, {pass_count} passed, "
        f"{len(graded) - pass_count} below passing threshold"
        if graded
        else "No graded assignment data is available yet"
    )
    weakness = {
        "total_assignments": len(profile.get("grades", [])),
        "graded_count": len(graded),
        "pass_count": pass_count,
        "fail_count": len(graded) - pass_count,
        "pass_rate": round(pass_count / len(graded) * 100, 1) if graded else 0,
        "weakness_areas": weakness_areas,
        "summary": summary,
    }
    await service.log_tool_call_json(
        state.get("run_id"),
        "analyze_weakness",
        {"grade_count": len(profile.get("grades", []))},
        {"weakness_count": len(weakness_areas), "summary": summary},
    )
    return {
        "weakness": weakness,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "analyze_weakness", "result": f"Found {len(weakness_areas)} weakness areas"}],
    }


async def retrieve_materials(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    materials = await service.get_course_materials_summary(state["course_id"])
    await service.log_tool_call_json(
        state.get("run_id"),
        "retrieve_materials",
        {"course_id": state["course_id"]},
        {"material_count": len(materials), "materials": materials[:5]},
    )
    return {
        "retrieved_materials": materials,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "retrieve_materials", "result": f"Retrieved {len(materials)} course materials"}],
    }


async def plan_tasks(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    weakness = state.get("weakness") or {}
    weak_areas = weakness.get("weakness_areas", [])
    materials = _material_names(state.get("retrieved_materials"))
    days = ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5"]
    daily_tasks = []

    task_count = max(len(weak_areas), 3)
    for index, day in enumerate(days[:task_count]):
        related_material = materials[index % len(materials)] if materials else None
        if index < len(weak_areas):
            area = weak_areas[index]
            tasks = [
                f"Review the concepts related to {area['assignment']}",
                "Complete targeted practice and record wrong answers",
                "Summarize the method and unresolved questions",
            ]
            if related_material:
                tasks.insert(1, f"Use course material: {related_material}")
            daily_tasks.append(
                {
                    "day": day,
                    "focus": f"Strengthen {area['assignment']}",
                    "duration_hours": 2,
                    "priority": "high" if area.get("ratio", 100) < 60 else "medium",
                    "tasks": tasks,
                }
            )
        else:
            tasks = [
                "Review this week's core concepts",
                "Complete mixed practice",
                "Update the error notebook",
            ]
            if related_material:
                tasks.insert(1, f"Read and annotate: {related_material}")
            daily_tasks.append(
                {
                    "day": day,
                    "focus": "Comprehensive review",
                    "duration_hours": 1.5,
                    "priority": "medium",
                    "tasks": tasks,
                }
            )

    plan = {
        "daily_tasks": daily_tasks,
        "total_hours": sum(task["duration_hours"] for task in daily_tasks),
        "weakness_summary": weakness.get("summary", ""),
        "materials": materials,
    }
    await service.log_tool_call_json(
        state.get("run_id"),
        "plan_tasks",
        {"weakness_count": len(weak_areas), "material_count": len(materials)},
        {
            "daily_task_count": len(daily_tasks),
            "total_hours": plan["total_hours"],
            "materials": materials,
        },
    )
    return {
        "plan": plan,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "plan_tasks", "result": f"Generated {len(daily_tasks)} daily tasks"}],
    }


async def generate_exercises(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    weakness = state.get("weakness") or {}
    weak_areas = weakness.get("weakness_areas", [])
    exercises = []
    for index, area in enumerate(weak_areas[:3]):
        exercises.append(
            {
                "id": index * 2 + 1,
                "type": "short_answer",
                "question": f"Summarize the core ideas of {area['assignment']} and give an example.",
                "hint": "Use class notes and course materials.",
                "target_weakness": area["assignment"],
                "estimated_time_minutes": 15,
            }
        )
        exercises.append(
            {
                "id": index * 2 + 2,
                "type": "applied_analysis",
                "question": f"Analyze a practical problem related to {area['assignment']}.",
                "hint": "State assumptions, process, evidence, and conclusion.",
                "target_weakness": area["assignment"],
                "estimated_time_minutes": 20,
            }
        )
    await service.log_tool_call_json(
        state.get("run_id"),
        "generate_exercises",
        {"weakness_count": len(weak_areas)},
        {"exercise_count": len(exercises)},
    )
    return {
        "exercises": exercises,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "generate_exercises", "result": f"Generated {len(exercises)} exercises"}],
    }


async def validate_plan(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    plan = state.get("plan") or {}
    errors = []
    total_hours = float(plan.get("total_hours") or 0)
    if total_hours > 20:
        errors.append(f"Total study time {total_hours}h exceeds recommended workload")
    if total_hours <= 0:
        errors.append("Learning plan is empty")
    if not plan.get("daily_tasks"):
        errors.append("Missing daily tasks")
    await service.log_tool_call_json(
        state.get("run_id"),
        "validate_plan",
        {"total_hours": total_hours, "daily_task_count": len(plan.get("daily_tasks") or [])},
        {"errors": errors},
    )
    return {
        "validation_errors": errors,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "validate_plan", "result": f"Validation found {len(errors)} issues"}],
    }


async def save_report(state: LearningPlanState, service: AiToolService) -> Dict[str, Any]:
    try:
        plan = state.get("plan") or {}
        report = await service.save_learning_report(
            student_id=state["student_id"],
            course_id=state["course_id"],
            run_id=state.get("run_id", 0),
            weakness_json=json.dumps(state.get("weakness", {}), ensure_ascii=False),
            plan_json=json.dumps(plan, ensure_ascii=False),
        )
        await service.log_tool_call_json(
            state.get("run_id"),
            "save_report",
            {"student_id": state["student_id"], "course_id": state["course_id"]},
            {"report_id": report.id},
        )
        final_report = {
            "report_id": report.id,
            "weakness": state.get("weakness", {}),
            "plan": plan,
            "materials": plan.get("materials", []),
            "exercises": state.get("exercises", []),
            "validation_errors": state.get("validation_errors", []),
        }
        return {
            "final_report": final_report,
            "tool_trace": (state.get("tool_trace") or [])
            + [{"node": "save_report", "result": f"Report saved with ID={report.id}"}],
        }
    except Exception as exc:
        return {"error": str(exc)}


def should_generate_exercises(state: LearningPlanState) -> str:
    return "generate_exercises" if state.get("weakness", {}).get("weakness_areas") else "validate_plan"


def _merge_state(updater):
    """Run one async workflow step and merge its updates into the state."""

    async def invoke(state: LearningPlanState) -> LearningPlanState:
        updates = await updater(state)
        return {**state, **updates}

    return RunnableLambda(invoke)


def build_learning_plan_chain(service: AiToolService):
    """Build the workflow as a LangChain RunnableSequence with one branch."""
    collect = _merge_state(lambda state: collect_profile(state, service))
    analyze = _merge_state(lambda state: analyze_weakness(state, service))
    retrieve = _merge_state(lambda state: retrieve_materials(state, service))
    plan = _merge_state(lambda state: plan_tasks(state, service))
    exercises = _merge_state(lambda state: generate_exercises(state, service))
    validate = _merge_state(lambda state: validate_plan(state, service))
    save = _merge_state(lambda state: save_report(state, service))

    conditional = RunnableBranch(
        (lambda state: should_generate_exercises(state) == "generate_exercises", exercises | validate),
        validate,
    )
    return collect | analyze | retrieve | plan | conditional | save
