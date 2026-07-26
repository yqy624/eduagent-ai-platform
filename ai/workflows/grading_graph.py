"""教师批改建议 Agent — LangGraph 状态机

Graph 节点流：
load_submission -> get_rubric -> suggest_grade -> generate_comment -> wait_for_review
"""
import json
import time
from functools import partial
from typing import Any, Dict, List, Optional, TypedDict, Literal
from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_tool_service import AiToolService
from ai.tools.assignment_tools import AssignmentTools
from ai.tools.grade_tools import GradeTools


# ===== Agent State =====
class GradingState(TypedDict):
    run_id: int
    user_id: int
    submission_id: int
    role: str

    # 加载的数据
    submission: Optional[Dict[str, Any]]
    assignment: Optional[Dict[str, Any]]
    peer_reviews: Optional[List[Dict[str, Any]]]

    # AI 输出
    suggested_score: Optional[float]
    rubric: Optional[Dict[str, Any]]
    comment: Optional[str]
    strengths: Optional[List[str]]
    weaknesses: Optional[List[str]]
    risks: Optional[List[str]]
    suggestion_id: Optional[int]

    # 人机协同
    teacher_action: Optional[str]  # ACCEPTED, MODIFIED, REJECTED
    teacher_score: Optional[float]
    tool_trace: Optional[List[Dict[str, Any]]]

    # 元数据
    error: Optional[str]


# ===== 节点函数 =====
async def load_submission(state: GradingState, service: AiToolService) -> Dict:
    submission = await service.grade_tools.get_submission_detail(state["submission_id"])
    if submission is None:
        return {"error": "提交记录不存在"}

    assignment = await service.assignment_tools.get_assignment(submission["assignment_id"])
    peer_reviews = await service.assignment_tools.get_peer_reviews_for_submission(
        state["submission_id"]
    )
    await service.log_tool_call_json(
        state.get("run_id"), "load_submission",
        {"submission_id": state["submission_id"]},
        {
            "assignment_id": submission.get("assignment_id"),
            "assignment_title": assignment.get("title") if assignment else None,
            "peer_review_count": len(peer_reviews),
        },
    )

    return {
        "submission": submission,
        "assignment": assignment,
        "peer_reviews": peer_reviews,
        "tool_trace": [
            {
                "node": "load_submission",
                "result": f"加载提交 ID={state['submission_id']}, 作业={assignment.get('title') if assignment else 'N/A'}",
            }
        ],
    }


async def get_rubric(state: GradingState, service: AiToolService) -> Dict:
    """获取评分标准（基于规则）"""
    assignment = state.get("assignment", {})
    total_points = assignment.get("total_points", 100)

    rubric = {
        "total_points": total_points,
        "criteria": [
            {"name": "内容完整性", "weight": 0.3, "description": "是否完整回答了题目要求"},
            {"name": "逻辑与结构", "weight": 0.2, "description": "论述是否清晰有条理"},
            {"name": "技术准确性", "weight": 0.3, "description": "概念和技术是否正确"},
            {"name": "表达与规范", "weight": 0.2, "description": "语言表达和格式规范"},
        ],
    }
    await service.log_tool_call_json(
        state.get("run_id"), "get_rubric",
        {"assignment_id": assignment.get("id")},
        rubric,
    )

    return {
        "rubric": rubric,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "get_rubric", "result": f"评分标准加载完成，总分 {total_points}"}],
    }


async def suggest_grade(state: GradingState, service: AiToolService) -> Dict:
    """生成建议分数（基于规则，后续可升级为 LLM）"""
    submission = state.get("submission", {})
    assignment = state.get("assignment", {})
    total_points = assignment.get("total_points", 100)

    # 基于规则的评分
    content = submission.get("content", "")
    content_length = len(content) if content else 0

    score = 0
    strengths = []
    weaknesses = []

    # 内容完整性
    if content_length > 500:
        score += total_points * 0.3
        strengths.append("内容完整，回答详实")
    elif content_length > 200:
        score += total_points * 0.2
        weaknesses.append("内容可以更丰富")
    elif content_length > 50:
        score += total_points * 0.15
        weaknesses.append("内容较为简单，建议补充详细说明")
    else:
        score += total_points * 0.1
        weaknesses.append("内容过少，请补充完整")

    # 默认为基础分
    score = max(score, total_points * 0.4)

    # 根据互评调整
    peer_reviews = state.get("peer_reviews", [])
    if peer_reviews:
        avg_rating = sum(r.get("rating", 5) for r in peer_reviews) / len(peer_reviews)
        if avg_rating >= 7:
            strengths.append("获得同学好评")
            score += total_points * 0.05
        elif avg_rating <= 3:
            weaknesses.append("同学评价较低，建议查看互评反馈")
            score -= total_points * 0.05

    # 确保在合理范围内
    score = max(0, min(total_points, round(score, 1)))

    risks = []
    if content_length < 100:
        risks.append("内容过少可能存在抄袭风险，请教师核实")
    await service.log_tool_call_json(
        state.get("run_id"), "suggest_grade",
        {
            "submission_id": state["submission_id"],
            "content_length": content_length,
            "peer_review_count": len(peer_reviews),
        },
        {
            "suggested_score": score,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risks": risks,
        },
    )

    return {
        "suggested_score": score,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "risks": risks,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "suggest_grade", "result": f"建议分数: {score}/{total_points}"}],
    }


async def generate_comment(state: GradingState, service: AiToolService) -> Dict:
    """生成评语（基于规则）"""
    strengths = state.get("strengths", [])
    weaknesses = state.get("weaknesses", [])
    suggested_score = state.get("suggested_score", 0)
    assignment = state.get("assignment", {})
    total_points = assignment.get("total_points", 100)

    comment_parts = ["批改建议："]

    if strengths:
        comment_parts.append("优点：" + "；".join(strengths))
    if weaknesses:
        comment_parts.append("改进建议：" + "；".join(weaknesses))

    ratio = suggested_score / total_points * 100
    if ratio >= 90:
        comment_parts.append("整体表现优秀，继续保持！")
    elif ratio >= 75:
        comment_parts.append("整体表现良好，仍有提升空间。")
    elif ratio >= 60:
        comment_parts.append("基本达到要求，建议针对性加强薄弱环节。")
    else:
        comment_parts.append("需要重点关注，建议重新学习相关内容后再提交。")

    comment = "\n".join(comment_parts)
    await service.log_tool_call_json(
        state.get("run_id"), "generate_comment",
        {"suggested_score": suggested_score, "total_points": total_points},
        {"comment": comment},
    )

    return {
        "comment": comment,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "generate_comment", "result": "评语生成完成"}],
    }


async def wait_for_review(state: GradingState, service: AiToolService) -> Dict:
    """等待教师确认（Human-in-the-loop 占位）"""
    # 保存批改建议到数据库
    try:
        rubric_json = json.dumps(state.get("rubric", {}), ensure_ascii=False)
        suggestion = await service.save_grading_suggestion(
            submission_id=state["submission_id"],
            run_id=state.get("run_id", 0),
            suggested_score=state.get("suggested_score", 0),
            rubric_json=rubric_json,
            comment=state.get("comment", ""),
            strengths=json.dumps(state.get("strengths", []), ensure_ascii=False),
            weaknesses=json.dumps(state.get("weaknesses", []), ensure_ascii=False),
        )
        await service.log_tool_call_json(
            state.get("run_id"), "wait_for_review",
            {"submission_id": state["submission_id"]},
            {"suggestion_id": suggestion.id, "teacher_action": "PENDING"},
        )

        return {
            "suggestion_id": suggestion.id,
            "tool_trace": (state.get("tool_trace") or [])
            + [{
                "node": "wait_for_review",
                "result": f"批改建议已保存 (ID={suggestion.id})，等待教师确认",
            }],
        }
    except Exception as e:
        return {"error": f"保存批改建议失败: {e}"}


def should_generate_comment(state: GradingState) -> Literal["generate_comment", "wait_for_review"]:
    """条件边"""
    if state.get("error"):
        return "wait_for_review"
    return "generate_comment"


# ===== 通过 partial 绑定 service =====
def build_grading_graph(service: AiToolService):
    workflow = StateGraph(GradingState)

    workflow.add_node("load_submission", partial(load_submission, service=service))
    workflow.add_node("get_rubric", partial(get_rubric, service=service))
    workflow.add_node("suggest_grade", partial(suggest_grade, service=service))
    workflow.add_node("generate_comment", partial(generate_comment, service=service))
    workflow.add_node("wait_for_review", partial(wait_for_review, service=service))

    workflow.set_entry_point("load_submission")

    workflow.add_edge("load_submission", "get_rubric")
    workflow.add_edge("get_rubric", "suggest_grade")
    workflow.add_conditional_edges(
        "suggest_grade",
        should_generate_comment,
        {
            "generate_comment": "generate_comment",
            "wait_for_review": "wait_for_review",
        },
    )
    workflow.add_edge("generate_comment", "wait_for_review")
    workflow.add_edge("wait_for_review", END)

    return workflow.compile()
