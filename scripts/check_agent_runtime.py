"""Lightweight checks for the controlled Agent runtime.

This script does not connect to MySQL or call an LLM. It validates the local
contracts that make the Agent more than a single API call: structured plans,
tool allowlists, argument validation, and confirmation metadata.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.agents.runtime import AgentPlan, AgentPlanStep
from ai.agents.tool_registry import AgentToolError, ToolDefinition


async def _noop(args):
    return {"ok": True, "args": args}


def check_plan_validation() -> None:
    plan = AgentPlan(
        objective="answer a course question",
        steps=[
            AgentPlanStep(
                tool="retrieve_course_material",
                args={"course_id": 1, "question": "Explain recursion"},
            )
        ],
    )
    assert plan.steps[0].tool == "retrieve_course_material"


def check_tool_argument_contract() -> None:
    tool = ToolDefinition(
        name="retrieve_course_material",
        description="retrieve",
        required_args={"course_id", "question"},
        optional_args=set(),
        allowed_roles={"STUDENT"},
        read_only=True,
        requires_confirmation=False,
        handler=_noop,
    )
    assert tool.normalize_args({"course_id": 1, "question": "x"})["course_id"] == 1
    try:
        tool.normalize_args({"course_id": 1})
    except AgentToolError:
        pass
    else:
        raise AssertionError("missing required arguments should be rejected")
    try:
        tool.normalize_args({"course_id": 1, "question": "x", "unsafe": True})
    except AgentToolError:
        pass
    else:
        raise AssertionError("unknown arguments should be rejected")


def check_confirmation_metadata() -> None:
    tool = ToolDefinition(
        name="send_notification",
        description="send",
        required_args={"recipient_username", "title", "content"},
        optional_args={"link"},
        allowed_roles={"TEACHER"},
        read_only=False,
        requires_confirmation=True,
        handler=_noop,
    )
    assert not tool.read_only
    assert tool.requires_confirmation


def check_confirmation_argument_contract() -> None:
    tool = ToolDefinition(
        name="send_notification",
        description="send",
        required_args={"recipient_username", "title", "content"},
        optional_args=set(),
        allowed_roles={"TEACHER"},
        read_only=False,
        requires_confirmation=True,
        handler=_noop,
    )
    assert tool.requires_confirmation is True
    values = tool.normalize_args(
        {
            "recipient_username": "student",
            "title": "Notice",
            "content": "Content",
        }
    )
    assert values["recipient_username"] == "student"


def main() -> None:
    check_plan_validation()
    check_tool_argument_contract()
    check_confirmation_metadata()
    check_confirmation_argument_contract()
    print("Agent runtime checks passed")


if __name__ == "__main__":
    main()
