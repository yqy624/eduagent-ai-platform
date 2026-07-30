"""教师批改建议 Agent — LangGraph 状态机

Graph 节点流：
load_submission -> get_rubric -> suggest_grade -> generate_comment -> wait_for_review
"""
import json
import re
import time
from functools import partial
from typing import Any, Dict, List, Optional, TypedDict, Literal
from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_tool_service import AiToolService
from ai.tools.assignment_tools import AssignmentTools
from ai.tools.grade_tools import GradeTools


_STOPWORDS = {
    "作业", "要求", "提交", "课程", "学生", "教师", "完成", "说明", "内容", "分析", "进行", "根据", "包括",
    "需要", "相关", "一个", "以及", "或者", "通过", "使用", "格式", "评分", "标准", "附件", "文件", "包含",
    "the", "and", "for", "with", "that", "this", "from", "you", "your", "are", "not", "can", "will",
}
_CJK_SPLIT_NOISE = (
    "请", "围绕", "根据", "完成", "提交", "包含", "包括", "作业", "要求", "课程", "学生", "教师",
    "说明", "进行", "需要", "给出", "以及", "或者", "和", "与", "及", "的",
)


def _safe_total_points(assignment: Dict[str, Any]) -> float:
    value = assignment.get("total_points") or 100
    try:
        return float(value)
    except (TypeError, ValueError):
        return 100.0


def _text_value(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_keywords(text: str, limit: int = 16) -> List[str]:
    """从作业标题/要求中提取可用于评分覆盖度的关键词。"""
    if not text:
        return []
    tokens: List[str] = []
    tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        parts = [segment]
        for noise in _CJK_SPLIT_NOISE:
            next_parts: List[str] = []
            for part in parts:
                next_parts.extend([item for item in part.split(noise) if item])
            parts = next_parts
        for part in parts:
            if len(part) <= 6:
                tokens.append(part)
                continue
            bigrams = [part[index:index + 2] for index in range(0, len(part) - 1, 2)]
            tokens.extend(
                [bigrams[index] + bigrams[index + 1] for index in range(0, len(bigrams) - 1, 2)]
            )
            tokens.extend(bigrams)
    keywords: List[str] = []
    seen = set()
    for raw in tokens:
        token = raw.strip("，。！？；：、,.!?;:()（）[]【】<>《》\"'")
        if len(token) < 2:
            continue
        token_lower = token.lower()
        if token_lower in _STOPWORDS:
            continue
        if any(stop in token_lower for stop in _STOPWORDS if len(stop) >= 2 and stop in {"作业", "要求", "提交", "课程", "学生", "教师"}):
            continue
        if token_lower.isdigit():
            continue
        if token_lower not in seen:
            seen.add(token_lower)
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def _count_markers(text: str, markers: List[str]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker.lower() in lowered)


def _attachment_names(submission: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    raw_paths = _text_value(submission.get("file_paths"))
    if raw_paths:
        for item in re.split(r"[,;\n]+", raw_paths):
            item = item.strip()
            if not item:
                continue
            names.append(item.split("::", 1)[1] if "::" in item else item)
    file_name = _text_value(submission.get("file_name"))
    if file_name and file_name not in names:
        names.append(file_name)
    return names


def analyze_submission_for_grading(
    submission: Dict[str, Any],
    assignment: Dict[str, Any],
    peer_reviews: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """本地内容感知批改，避免不同提交只因字数相近而得到同质化建议。"""
    total_points = _safe_total_points(assignment)
    raw_content = _text_value(submission.get("content"))
    content = _normalize_text(raw_content)
    assignment_text = "\n".join(
        [
            _text_value(assignment.get("title")),
            _text_value(assignment.get("description")),
            _text_value(assignment.get("detail")),
        ]
    )
    keywords = _extract_keywords(assignment_text)
    content_lower = content.lower()
    matched_keywords = [kw for kw in keywords if kw.lower() in content_lower]
    missing_keywords = [kw for kw in keywords if kw.lower() not in content_lower]
    keyword_coverage = len(matched_keywords) / len(keywords) if keywords else 0.65

    content_length = len(content)
    sentences = [s for s in re.split(r"[。！？!?；;\n]+", raw_content) if s.strip()]
    paragraphs = [p for p in re.split(r"\n{1,}|\r\n{1,}", raw_content) if p.strip()]
    structure_markers = _count_markers(
        content,
        [
            "首先", "其次", "然后", "最后", "先", "再", "部分", "因此", "因为", "所以", "总结", "步骤",
            "一、", "二、", "1.", "2.", "3.",
        ],
    )
    evidence_markers = _count_markers(
        content,
        ["例如", "案例", "数据", "结果", "原因", "对比", "证明", "代码", "公式", "实验", "截图", "引用"],
    )
    has_numbers_or_code = bool(re.search(r"\d|```|def |class |function |SELECT |import |=", content))
    attachment_list = _attachment_names(submission)
    only_attachment = not content and bool(attachment_list)

    length_ratio = min(content_length / 650, 1.0)
    depth_ratio = min((len(sentences) / 8) * 0.45 + length_ratio * 0.55, 1.0)
    structure_ratio = min((len(paragraphs) / 3) * 0.45 + (structure_markers / 4) * 0.55, 1.0)
    evidence_ratio = min((evidence_markers / 4) * 0.65 + (0.35 if has_numbers_or_code else 0), 1.0)
    if len(matched_keywords) >= 5 and content_length >= 120:
        depth_ratio = max(depth_ratio, 0.55)
    if content_length >= 260 and evidence_ratio < 0.35:
        evidence_ratio = 0.35

    unique_chars = len(set(content))
    unique_ratio = unique_chars / content_length if content_length else 0
    repeated_lines = 0
    lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
    if len(lines) >= 3:
        repeated_lines = len(lines) - len(set(lines))
    expression_ratio = 0.82
    if content_length < 40:
        expression_ratio = 0.35
    elif unique_ratio < 0.18 or repeated_lines >= 2:
        expression_ratio = 0.48
    elif content_length >= 160:
        expression_ratio = 0.9

    if only_attachment:
        component_scores = {
            "requirements": 0.42,
            "depth": 0.38,
            "structure": 0.35,
            "evidence": 0.38,
            "expression": 0.65,
        }
    else:
        component_scores = {
            "requirements": keyword_coverage,
            "depth": depth_ratio,
            "structure": structure_ratio,
            "evidence": evidence_ratio,
            "expression": expression_ratio,
        }

    weighted_ratio = (
        component_scores["requirements"] * 0.34
        + component_scores["depth"] * 0.24
        + component_scores["structure"] * 0.16
        + component_scores["evidence"] * 0.16
        + component_scores["expression"] * 0.10
    )
    # 保留可演示的基础分，但让内容覆盖度和证据质量拉开差距。
    score = total_points * max(0.18, min(weighted_ratio, 0.96))

    peer_reviews = peer_reviews or []
    peer_summary = None
    if peer_reviews:
        avg_rating = sum(float(r.get("rating") or 0) for r in peer_reviews) / len(peer_reviews)
        peer_summary = round(avg_rating, 1)
        if avg_rating >= 8:
            score += total_points * 0.04
        elif avg_rating <= 3:
            score -= total_points * 0.05

    score = max(0, min(total_points, round(score, 1)))

    strengths: List[str] = []
    weaknesses: List[str] = []
    risks: List[str] = []

    if matched_keywords:
        strengths.append("回应了作业中的关键点：" + "、".join(matched_keywords[:4]))
    elif keywords and not only_attachment:
        weaknesses.append("未明显覆盖作业关键点：" + "、".join(missing_keywords[:4]))

    if content_length >= 450:
        strengths.append("提交内容较充分，具备一定展开")
    elif only_attachment:
        weaknesses.append("当前主要依赖附件，文本区缺少可直接判断的解题过程")
    elif content_length < 80:
        weaknesses.append("文本内容偏少，难以支撑高分判断")
    else:
        weaknesses.append("论述深度仍可加强，建议补充过程、依据或结论")

    if structure_ratio >= 0.65:
        strengths.append("结构较清晰，步骤或层次有体现")
    else:
        weaknesses.append("结构层次不够明显，可按步骤、观点或小标题组织")

    if evidence_ratio >= 0.55:
        strengths.append("能结合例子、数据、代码或结果说明观点")
    else:
        weaknesses.append("证据支撑不足，建议加入案例、数据、代码片段或推导过程")

    if peer_summary is not None:
        if peer_summary >= 8:
            strengths.append(f"互评平均 {peer_summary}/10，同伴反馈较好")
        elif peer_summary <= 3:
            weaknesses.append(f"互评平均 {peer_summary}/10，需要结合互评意见复查")

    if missing_keywords and len(matched_keywords) < max(2, len(keywords) // 3):
        risks.append("关键要求覆盖不足，请教师核对是否偏题")
    if content_length < 40 and not only_attachment:
        risks.append("提交文本过短，可能无法判断真实掌握情况")
    if unique_ratio and unique_ratio < 0.18:
        risks.append("文本重复度偏高，建议核查是否存在复制堆叠")
    if only_attachment:
        risks.append("AI 未读取附件正文，请教师预览附件后再确认分数")

    return {
        "score": score,
        "strengths": strengths[:5],
        "weaknesses": weaknesses[:5],
        "risks": risks[:4],
        "matched_keywords": matched_keywords[:6],
        "missing_keywords": missing_keywords[:6],
        "keyword_coverage": round(keyword_coverage, 2),
        "content_length": content_length,
        "attachment_names": attachment_list,
        "component_scores": {key: round(value, 2) for key, value in component_scores.items()},
    }


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
    grading_analysis: Optional[Dict[str, Any]]
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
    assignment_title = assignment.get("title") if assignment else "N/A"

    return {
        "submission": submission,
        "assignment": assignment,
        "peer_reviews": peer_reviews,
        "tool_trace": [
            {
                "node": "load_submission",
                "result": f"加载提交 ID={state['submission_id']}, 作业={assignment_title}",
            }
        ],
    }


async def get_rubric(state: GradingState, service: AiToolService) -> Dict:
    """获取评分标准（基于规则）"""
    assignment = state.get("assignment") or {}
    total_points = _safe_total_points(assignment)

    rubric = {
        "total_points": total_points,
        "criteria": [
            {"name": "要求覆盖", "weight": 0.34, "description": "是否回应题目中的关键任务、概念和交付要求"},
            {"name": "内容深度", "weight": 0.24, "description": "是否有充分展开，而不是只给结论或短句"},
            {"name": "结构层次", "weight": 0.16, "description": "是否按步骤、观点或小标题组织"},
            {"name": "证据支撑", "weight": 0.16, "description": "是否包含案例、数据、代码、结果或推导过程"},
            {"name": "表达规范", "weight": 0.10, "description": "语言是否清楚，是否存在明显重复堆叠"},
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
    """生成建议分数（基于作业要求与提交内容的本地分析）"""
    submission = state.get("submission") or {}
    assignment = state.get("assignment") or {}
    peer_reviews = state.get("peer_reviews") or []
    analysis = analyze_submission_for_grading(submission, assignment, peer_reviews)
    score = analysis["score"]
    strengths = analysis["strengths"]
    weaknesses = analysis["weaknesses"]
    risks = analysis["risks"]
    total_points = _safe_total_points(assignment)

    await service.log_tool_call_json(
        state.get("run_id"), "suggest_grade",
        {
            "submission_id": state["submission_id"],
            "content_length": analysis["content_length"],
            "peer_review_count": len(peer_reviews),
            "matched_keywords": analysis["matched_keywords"],
            "missing_keywords": analysis["missing_keywords"],
        },
        {
            "suggested_score": score,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risks": risks,
            "component_scores": analysis["component_scores"],
            "keyword_coverage": analysis["keyword_coverage"],
        },
    )

    return {
        "suggested_score": score,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "risks": risks,
        "grading_analysis": {
            "matched_keywords": analysis["matched_keywords"],
            "missing_keywords": analysis["missing_keywords"],
            "keyword_coverage": analysis["keyword_coverage"],
            "content_length": analysis["content_length"],
            "attachment_names": analysis["attachment_names"],
            "component_scores": analysis["component_scores"],
        },
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "suggest_grade", "result": f"建议分数: {score}/{total_points}"}],
    }


async def generate_comment(state: GradingState, service: AiToolService) -> Dict:
    """生成评语（基于内容分析结果）"""
    strengths = state.get("strengths", [])
    weaknesses = state.get("weaknesses", [])
    risks = state.get("risks", [])
    suggested_score = state.get("suggested_score", 0)
    assignment = state.get("assignment") or {}
    submission = state.get("submission") or {}
    total_points = _safe_total_points(assignment)
    assignment_title = _text_value(assignment.get("title")) or "本次作业"
    content = _normalize_text(_text_value(submission.get("content")))

    comment_parts = [f"批改建议：{assignment_title}"]

    if strengths:
        comment_parts.append("优点：" + "；".join(strengths))
    if weaknesses:
        comment_parts.append("改进建议：" + "；".join(weaknesses))
    if risks:
        comment_parts.append("需教师复核：" + "；".join(risks))

    if content:
        excerpt = content[:90] + ("..." if len(content) > 90 else "")
        comment_parts.append("依据摘录：" + excerpt)

    ratio = suggested_score / total_points * 100
    if ratio >= 90:
        comment_parts.append("总体判断：表现优秀，关键要求覆盖充分，可继续保持。")
    elif ratio >= 75:
        comment_parts.append("总体判断：完成度较好，补足细节和证据后还能提升。")
    elif ratio >= 60:
        comment_parts.append("总体判断：基本达到要求，但需要针对薄弱环节继续完善。")
    else:
        comment_parts.append("总体判断：与要求仍有明显差距，建议按作业要求重新梳理后再提交。")

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
