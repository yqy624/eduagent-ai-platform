"""Teacher grading-suggestion Agent workflow."""
import json
import re
from functools import partial
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.services.ai_tool_service import AiToolService


_STOPWORDS = {
    "assignment",
    "requirement",
    "requirements",
    "student",
    "teacher",
    "submit",
    "submission",
    "course",
    "content",
    "include",
    "using",
    "with",
    "from",
    "that",
    "this",
    "your",
    "\u4f5c\u4e1a",
    "\u8981\u6c42",
    "\u63d0\u4ea4",
    "\u8bfe\u7a0b",
    "\u5b66\u751f",
    "\u6559\u5e08",
    "\u5b8c\u6210",
    "\u8bf4\u660e",
    "\u5185\u5bb9",
    "\u5206\u6790",
    "\u6839\u636e",
    "\u5305\u62ec",
    "\u9700\u8981",
    "\u76f8\u5173",
    "\u901a\u8fc7",
    "\u4f7f\u7528",
    "\u8bc4\u5206",
    "\u6807\u51c6",
    "\u9644\u4ef6",
    "\u6587\u4ef6",
}

_CJK_NOISE_PATTERN = re.compile(
    "|".join(
        [
            "\u8bf7",
            "\u6839\u636e",
            "\u5b8c\u6210",
            "\u63d0\u4ea4",
            "\u5305\u542b",
            "\u5305\u62ec",
            "\u4f5c\u4e1a",
            "\u8981\u6c42",
            "\u8bfe\u7a0b",
            "\u5b66\u751f",
            "\u6559\u5e08",
            "\u8bf4\u660e",
            "\u8fdb\u884c",
            "\u5206\u6790",
            "\u5b9e\u9a8c",
            "\u9700\u8981",
            "\u7ed9\u51fa",
            "\u4ee5\u53ca",
            "\u6216\u8005",
            "\u548c",
            "\u4e0e",
            "\u53ca",
            "\u5e76",
            "\u7684",
        ]
    )
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


def _split_cjk_phrases(segment: str) -> List[str]:
    cleaned = _CJK_NOISE_PATTERN.sub("|", segment)
    raw_parts = re.split(r"[|,.;:!?，。；：！？、\s]+", cleaned)
    phrases: List[str] = []
    for part in raw_parts:
        part = part.strip()
        if len(part) < 2:
            continue
        if len(part) <= 6:
            phrases.append(part)
            continue
        phrases.append(part)
        sizes = (6, 4) if len(part) > 10 else (4,)
        for size in sizes:
            step = max(size // 2, 1)
            for index in range(0, max(len(part) - size + 1, 0), step):
                chunk = part[index:index + size]
                if len(chunk) >= 4:
                    phrases.append(chunk)
    return phrases


def _extract_keywords(text: str, limit: int = 16) -> List[str]:
    """Extract grading-coverage keywords without fragmenting CJK text into bigrams."""
    if not text:
        return []

    candidates: List[str] = []
    candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        candidates.extend(_split_cjk_phrases(segment))

    keywords: List[str] = []
    seen = set()
    for raw in candidates:
        token = raw.strip(" \t\r\n,.!?;:()[]{}<>\"'")
        if len(token) < 2:
            continue
        token_lower = token.lower()
        if token_lower in _STOPWORDS or token_lower.isdigit():
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
            if item:
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
    """Local content-aware grading analysis for deterministic Agent tooling."""
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
    sentences = [s for s in re.split(r"[.!?\n\u3002\uff01\uff1f]+", raw_content) if s.strip()]
    paragraphs = [p for p in re.split(r"\n{1,}|\r\n{1,}", raw_content) if p.strip()]
    structure_markers = _count_markers(
        content,
        [
            "first",
            "second",
            "then",
            "finally",
            "summary",
            "1.",
            "2.",
            "3.",
            "\u9996\u5148",
            "\u5176\u6b21",
            "\u7136\u540e",
            "\u6700\u540e",
            "\u56e0\u6b64",
            "\u603b\u7ed3",
        ],
    )
    evidence_markers = _count_markers(
        content,
        [
            "example",
            "case",
            "data",
            "result",
            "because",
            "code",
            "formula",
            "experiment",
            "\u4f8b\u5982",
            "\u6848\u4f8b",
            "\u6570\u636e",
            "\u7ed3\u679c",
            "\u539f\u56e0",
            "\u5bf9\u6bd4",
            "\u8bc1\u660e",
            "\u4ee3\u7801",
            "\u516c\u5f0f",
            "\u5b9e\u9a8c",
        ],
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
    lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
    repeated_lines = len(lines) - len(set(lines)) if len(lines) >= 3 else 0
    if content_length < 40:
        expression_ratio = 0.35
    elif unique_ratio < 0.18 or repeated_lines >= 2:
        expression_ratio = 0.48
    elif content_length >= 160:
        expression_ratio = 0.9
    else:
        expression_ratio = 0.82

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
    score = total_points * max(0.18, min(weighted_ratio, 0.96))

    peer_reviews = peer_reviews or []
    peer_summary = None
    if peer_reviews:
        peer_summary = round(sum(float(r.get("rating") or 0) for r in peer_reviews) / len(peer_reviews), 1)
        if peer_summary >= 8:
            score += total_points * 0.04
        elif peer_summary <= 3:
            score -= total_points * 0.05

    score = max(0, min(total_points, round(score, 1)))

    strengths: List[str] = []
    weaknesses: List[str] = []
    risks: List[str] = []

    if matched_keywords:
        strengths.append("Covers key requirements: " + ", ".join(matched_keywords[:4]))
    elif keywords and not only_attachment:
        weaknesses.append("Does not clearly cover key requirements: " + ", ".join(missing_keywords[:4]))

    if content_length >= 450:
        strengths.append("Submission is sufficiently detailed and developed")
    elif only_attachment:
        weaknesses.append("Main evidence is in attachments; text content is not enough for direct assessment")
    elif content_length < 80:
        weaknesses.append("Text content is too short to support a high-confidence grade")
    else:
        weaknesses.append("Depth can be improved with more process, evidence, or conclusions")

    if structure_ratio >= 0.65:
        strengths.append("Structure is clear enough for review")
    else:
        weaknesses.append("Structure is not clear; organize by steps, viewpoints, or headings")

    if evidence_ratio >= 0.55:
        strengths.append("Uses examples, data, code, results, or reasoning as evidence")
    else:
        weaknesses.append("Evidence is insufficient; add cases, data, code, or derivation steps")

    if peer_summary is not None:
        if peer_summary >= 8:
            strengths.append(f"Peer-review average is {peer_summary}/10")
        elif peer_summary <= 3:
            weaknesses.append(f"Peer-review average is {peer_summary}/10; teacher review is recommended")

    if missing_keywords and len(matched_keywords) < max(2, len(keywords) // 3):
        risks.append("Low requirement coverage; teacher should check for topic drift")
    if content_length < 40 and not only_attachment:
        risks.append("Submission text is too short to judge mastery")
    if unique_ratio and unique_ratio < 0.18:
        risks.append("Text repetition is high; check for copied or padded content")
    if only_attachment:
        risks.append("AI did not parse attachment body; preview attachments before confirming the score")

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


class GradingState(TypedDict):
    run_id: int
    user_id: int
    submission_id: int
    role: str
    submission: Optional[Dict[str, Any]]
    assignment: Optional[Dict[str, Any]]
    peer_reviews: Optional[List[Dict[str, Any]]]
    suggested_score: Optional[float]
    rubric: Optional[Dict[str, Any]]
    comment: Optional[str]
    strengths: Optional[List[str]]
    weaknesses: Optional[List[str]]
    risks: Optional[List[str]]
    grading_analysis: Optional[Dict[str, Any]]
    suggestion_id: Optional[int]
    teacher_action: Optional[str]
    teacher_score: Optional[float]
    tool_trace: Optional[List[Dict[str, Any]]]
    error: Optional[str]


async def load_submission(state: GradingState, service: AiToolService) -> Dict[str, Any]:
    submission = await service.grade_tools.get_submission_detail(state["submission_id"])
    if submission is None:
        return {"error": "Submission does not exist"}

    assignment = await service.assignment_tools.get_assignment(submission["assignment_id"])
    peer_reviews = await service.assignment_tools.get_peer_reviews_for_submission(state["submission_id"])
    await service.log_tool_call_json(
        state.get("run_id"),
        "load_submission",
        {"submission_id": state["submission_id"]},
        {
            "assignment_id": submission.get("assignment_id"),
            "assignment_title": assignment.get("title") if assignment else None,
            "peer_review_count": len(peer_reviews),
        },
    )
    return {
        "submission": submission,
        "assignment": assignment or {},
        "peer_reviews": peer_reviews,
        "tool_trace": [
            {
                "node": "load_submission",
                "result": f"Loaded submission ID={state['submission_id']}",
            }
        ],
    }


async def get_rubric(state: GradingState, service: AiToolService) -> Dict[str, Any]:
    assignment = state.get("assignment") or {}
    total_points = _safe_total_points(assignment)
    rubric = {
        "total_points": total_points,
        "criteria": [
            {"name": "requirement_coverage", "weight": 0.34},
            {"name": "depth", "weight": 0.24},
            {"name": "structure", "weight": 0.16},
            {"name": "evidence", "weight": 0.16},
            {"name": "expression", "weight": 0.10},
        ],
    }
    await service.log_tool_call_json(
        state.get("run_id"),
        "get_rubric",
        {"assignment_id": assignment.get("id")},
        rubric,
    )
    return {
        "rubric": rubric,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "get_rubric", "result": f"Loaded rubric with total points {total_points}"}],
    }


async def suggest_grade(state: GradingState, service: AiToolService) -> Dict[str, Any]:
    submission = state.get("submission") or {}
    assignment = state.get("assignment") or {}
    peer_reviews = state.get("peer_reviews") or []
    analysis = analyze_submission_for_grading(submission, assignment, peer_reviews)
    total_points = _safe_total_points(assignment)

    await service.log_tool_call_json(
        state.get("run_id"),
        "suggest_grade",
        {
            "submission_id": state["submission_id"],
            "content_length": analysis["content_length"],
            "peer_review_count": len(peer_reviews),
            "matched_keywords": analysis["matched_keywords"],
            "missing_keywords": analysis["missing_keywords"],
        },
        {
            "suggested_score": analysis["score"],
            "strengths": analysis["strengths"],
            "weaknesses": analysis["weaknesses"],
            "risks": analysis["risks"],
            "component_scores": analysis["component_scores"],
            "keyword_coverage": analysis["keyword_coverage"],
        },
    )
    return {
        "suggested_score": analysis["score"],
        "strengths": analysis["strengths"],
        "weaknesses": analysis["weaknesses"],
        "risks": analysis["risks"],
        "grading_analysis": {
            "matched_keywords": analysis["matched_keywords"],
            "missing_keywords": analysis["missing_keywords"],
            "keyword_coverage": analysis["keyword_coverage"],
            "content_length": analysis["content_length"],
            "attachment_names": analysis["attachment_names"],
            "component_scores": analysis["component_scores"],
        },
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "suggest_grade", "result": f"Suggested score: {analysis['score']}/{total_points}"}],
    }


async def generate_comment(state: GradingState, service: AiToolService) -> Dict[str, Any]:
    strengths = state.get("strengths") or []
    weaknesses = state.get("weaknesses") or []
    risks = state.get("risks") or []
    suggested_score = float(state.get("suggested_score") or 0)
    assignment = state.get("assignment") or {}
    submission = state.get("submission") or {}
    total_points = _safe_total_points(assignment)
    assignment_title = _text_value(assignment.get("title")) or "Assignment"
    content = _normalize_text(_text_value(submission.get("content")))

    comment_parts = [f"Grading suggestion for {assignment_title}"]
    if strengths:
        comment_parts.append("Strengths: " + "; ".join(strengths))
    if weaknesses:
        comment_parts.append("Improvements: " + "; ".join(weaknesses))
    if risks:
        comment_parts.append("Teacher review: " + "; ".join(risks))
    if content:
        excerpt = content[:90] + ("..." if len(content) > 90 else "")
        comment_parts.append("Evidence excerpt: " + excerpt)

    ratio = suggested_score / max(total_points, 1) * 100
    if ratio >= 90:
        comment_parts.append("Overall: excellent coverage and quality.")
    elif ratio >= 75:
        comment_parts.append("Overall: good completion; details and evidence can still improve.")
    elif ratio >= 60:
        comment_parts.append("Overall: basically meets requirements, with visible weak areas.")
    else:
        comment_parts.append("Overall: clearly below requirements; rework is recommended.")

    comment = "\n".join(comment_parts)
    await service.log_tool_call_json(
        state.get("run_id"),
        "generate_comment",
        {"suggested_score": suggested_score, "total_points": total_points},
        {"comment": comment},
    )
    return {
        "comment": comment,
        "tool_trace": (state.get("tool_trace") or [])
        + [{"node": "generate_comment", "result": "Generated grading comment"}],
    }


async def wait_for_review(state: GradingState, service: AiToolService) -> Dict[str, Any]:
    if state.get("error"):
        return {"error": state["error"]}
    try:
        suggestion = await service.save_grading_suggestion(
            submission_id=state["submission_id"],
            run_id=state.get("run_id", 0),
            suggested_score=state.get("suggested_score", 0),
            rubric_json=json.dumps(state.get("rubric", {}), ensure_ascii=False),
            comment=state.get("comment", ""),
            strengths=json.dumps(state.get("strengths", []), ensure_ascii=False),
            weaknesses=json.dumps(state.get("weaknesses", []), ensure_ascii=False),
        )
        await service.log_tool_call_json(
            state.get("run_id"),
            "wait_for_review",
            {"submission_id": state["submission_id"]},
            {"suggestion_id": suggestion.id, "teacher_action": "PENDING"},
        )
        return {
            "suggestion_id": suggestion.id,
            "tool_trace": (state.get("tool_trace") or [])
            + [{"node": "wait_for_review", "result": f"Saved suggestion ID={suggestion.id}"}],
        }
    except Exception as exc:
        return {"error": f"Failed to save grading suggestion: {exc}"}


def should_generate_comment(state: GradingState) -> Literal["generate_comment", "wait_for_review"]:
    return "wait_for_review" if state.get("error") else "generate_comment"


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
        {"generate_comment": "generate_comment", "wait_for_review": "wait_for_review"},
    )
    workflow.add_edge("generate_comment", "wait_for_review")
    workflow.add_edge("wait_for_review", END)
    return workflow.compile()
