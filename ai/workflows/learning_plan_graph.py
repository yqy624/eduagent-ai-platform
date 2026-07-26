"""学习路径规划 Agent — LangGraph 状态机"""
import json
from functools import partial
from typing import Any, Dict, List, Optional, TypedDict, Literal
from langgraph.graph import StateGraph, END
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


# ===== 节点函数（通过 partial 注入 service） =====
async def collect_profile(state: LearningPlanState, service: AiToolService) -> Dict:
    profile = await service.get_student_profile(state["student_id"])
    await service.log_tool_call_json(
        state.get("run_id"), "collect_profile",
        {"student_id": state["student_id"]},
        {"course_count": len(profile.get("courses", [])), "grade_count": len(profile.get("grades", []))},
    )
    return {
        "profile": profile,
        "grades": profile.get("grades", []),
        "submissions": [],
        "tool_trace": [{"node": "collect_profile", "result": f"获取到 {len(profile.get('courses', []))} 门课程, {len(profile.get('grades', []))} 条成绩"}],
    }


async def analyze_weakness(state: LearningPlanState, service: AiToolService) -> Dict:
    profile = state.get("profile", {})
    low_scores = profile.get("low_score_assignments", [])
    weakness_areas = []
    for g in low_scores:
        weakness_areas.append({
            "assignment": g.get("assignment_title", "未知"),
            "score": g.get("score"),
            "total": g.get("total_points", 100),
            "ratio": round(g["score"] / g["total_points"] * 100, 1) if g.get("total_points") else 0,
            "level": "弱" if (g.get("score", 0) / max(g.get("total_points", 100), 1) * 100) < 60 else "中",
        })
    graded = [g for g in profile.get("grades", []) if g.get("score") is not None]
    pass_count = sum(1 for g in graded if g["score"] / max(g.get("total_points", 100), 1) * 100 >= 60) if graded else 0
    weakness = {
        "total_assignments": len(profile.get("grades", [])),
        "graded_count": len(graded),
        "pass_count": pass_count,
        "fail_count": len(graded) - pass_count,
        "pass_rate": round(pass_count / len(graded) * 100, 1) if graded else 0,
        "weakness_areas": weakness_areas,
        "summary": f"共 {len(profile.get('grades', []))} 项作业，已批改 {len(graded)} 项，通过 {pass_count} 项"
        if graded else "暂无已批改成绩数据",
    }
    await service.log_tool_call_json(
        state.get("run_id"), "analyze_weakness",
        {"grade_count": len(profile.get("grades", []))},
        {"weakness_count": len(weakness_areas), "summary": weakness["summary"]},
    )
    return {
        "weakness": weakness,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "analyze_weakness", "result": f"找到 {len(weakness_areas)} 个薄弱点"}],
    }


async def retrieve_materials(state: LearningPlanState, service: AiToolService) -> Dict:
    materials = await service.get_course_materials_summary(state["course_id"])
    await service.log_tool_call_json(
        state.get("run_id"), "retrieve_materials",
        {"course_id": state["course_id"]},
        {"material_count": len(materials), "materials": materials[:5]},
    )
    return {
        "retrieved_materials": materials,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "retrieve_materials", "result": f"找到 {len(materials)} 份课程资料"}],
    }


async def plan_tasks(state: LearningPlanState, service: AiToolService) -> Dict:
    weakness = state.get("weakness", {})
    weak_areas = weakness.get("weakness_areas", [])
    daily_tasks = []
    days = ["周一", "周二", "周三", "周四", "周五"]
    for i, day in enumerate(days[:max(len(weak_areas), 3)]):
        if i < len(weak_areas):
            wa = weak_areas[i]
            task = {
                "day": day, "focus": f"强化 {wa['assignment']}", "duration_hours": 2,
                "priority": "高" if wa.get("ratio", 100) < 60 else "中",
                "tasks": [f"复习 {wa['assignment']} 相关内容", "完成课后练习题", "整理错题笔记"],
            }
        else:
            task = {"day": day, "focus": "综合复习", "duration_hours": 1.5, "priority": "中",
                    "tasks": ["复习本周知识点", "完成综合练习题"]}
        daily_tasks.append(task)
    plan = {"daily_tasks": daily_tasks, "total_hours": sum(t["duration_hours"] for t in daily_tasks), "weakness_summary": weakness.get("summary", "")}
    await service.log_tool_call_json(
        state.get("run_id"), "plan_tasks",
        {"weakness_count": len(weak_areas)},
        {"daily_task_count": len(daily_tasks), "total_hours": plan["total_hours"]},
    )
    return {"plan": plan, "tool_trace": (state.get("tool_trace") or [])
            + [{"node": "plan_tasks", "result": f"生成 {len(daily_tasks)} 天计划"}]}


async def generate_exercises(state: LearningPlanState, service: AiToolService) -> Dict:
    weakness = state.get("weakness", {})
    weak_areas = weakness.get("weakness_areas", [])
    exercises = []
    for i, wa in enumerate(weak_areas[:3]):
        exercises.append({"id": i + 1, "type": "简答题",
            "question": f"请总结 {wa['assignment']} 的核心知识点，并举例说明",
            "hint": "回顾课堂笔记和讲义", "target_weakness": wa["assignment"], "estimated_time_minutes": 15})
        exercises.append({"id": i + 1 + len(weak_areas), "type": "综合题",
            "question": f"基于 {wa['assignment']} 的内容，分析在实际应用中可能遇到的问题",
            "hint": "结合课程案例思考", "target_weakness": wa["assignment"], "estimated_time_minutes": 20})
    await service.log_tool_call_json(
        state.get("run_id"), "generate_exercises",
        {"weakness_count": len(weak_areas)},
        {"exercise_count": len(exercises)},
    )
    return {"exercises": exercises, "tool_trace": (state.get("tool_trace") or [])
            + [{"node": "generate_exercises", "result": f"生成 {len(exercises)} 道练习题"}]}


async def validate_plan(state: LearningPlanState, service: AiToolService) -> Dict:
    plan = state.get("plan", {})
    errors = []
    total_hours = plan.get("total_hours", 0)
    if total_hours > 20: errors.append(f"总时长 {total_hours}h 超过建议值")
    if total_hours <= 0: errors.append("学习计划为空")
    if not plan.get("daily_tasks"): errors.append("缺少每日任务")
    await service.log_tool_call_json(
        state.get("run_id"), "validate_plan",
        {"total_hours": total_hours, "daily_task_count": len(plan.get("daily_tasks") or [])},
        {"errors": errors},
    )
    return {"validation_errors": errors, "tool_trace": (state.get("tool_trace") or [])
            + [{"node": "validate_plan", "result": f"校验完成，发现 {len(errors)} 个问题"}]}


async def save_report(state: LearningPlanState, service: AiToolService) -> Dict:
    try:
        report = await service.save_learning_report(
            student_id=state["student_id"], course_id=state["course_id"], run_id=state.get("run_id", 0),
            weakness_json=json.dumps(state.get("weakness", {}), ensure_ascii=False),
            plan_json=json.dumps(state.get("plan", {}), ensure_ascii=False))
        await service.log_tool_call_json(
            state.get("run_id"), "save_report",
            {"student_id": state["student_id"], "course_id": state["course_id"]},
            {"report_id": report.id},
        )
        final_report = {"report_id": report.id, "weakness": state.get("weakness", {}),
                        "plan": state.get("plan", {}), "exercises": state.get("exercises", []),
                        "validation_errors": state.get("validation_errors", [])}
        return {"final_report": final_report, "tool_trace": (state.get("tool_trace") or [])
                + [{"node": "save_report", "result": f"报告已保存 ID={report.id}"}]}
    except Exception as e:
        return {"error": str(e)}


def should_generate_exercises(state: LearningPlanState) -> str:
    return "generate_exercises" if state.get("weakness", {}).get("weakness_areas") else "validate_plan"


# ===== 通过 partial 绑定 service =====
def build_learning_plan_graph(service: AiToolService):
    workflow = StateGraph(LearningPlanState)
    workflow.add_node("collect_profile", partial(collect_profile, service=service))
    workflow.add_node("analyze_weakness", partial(analyze_weakness, service=service))
    workflow.add_node("retrieve_materials", partial(retrieve_materials, service=service))
    workflow.add_node("plan_tasks", partial(plan_tasks, service=service))
    workflow.add_node("generate_exercises", partial(generate_exercises, service=service))
    workflow.add_node("validate_plan", partial(validate_plan, service=service))
    workflow.add_node("save_report", partial(save_report, service=service))

    workflow.set_entry_point("collect_profile")
    workflow.add_edge("collect_profile", "analyze_weakness")
    workflow.add_edge("analyze_weakness", "retrieve_materials")
    workflow.add_edge("retrieve_materials", "plan_tasks")
    workflow.add_conditional_edges("plan_tasks", should_generate_exercises, {
        "generate_exercises": "generate_exercises", "validate_plan": "validate_plan"})
    workflow.add_edge("generate_exercises", "validate_plan")
    workflow.add_edge("validate_plan", "save_report")
    workflow.add_edge("save_report", END)
    return workflow.compile()
