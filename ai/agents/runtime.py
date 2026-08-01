"""Controlled model -> plan -> tools -> memory Agent runtime."""

import json
import re
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from ai.llm import get_llm
from ai.agents.memory import AgentMemoryStore
from ai.agents.tool_registry import AgentToolError, AgentToolRegistry


class AgentPlanStep(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)
    args: Dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    objective: str = Field(min_length=1, max_length=1000)
    steps: List[AgentPlanStep] = Field(default_factory=list, max_length=8)


def _content(response: Any) -> str:
    value = getattr(response, "content", response)
    if isinstance(value, list):
        return "\n".join(
            item.get("text", str(item)) if isinstance(item, dict) else str(item)
            for item in value
        )
    return str(value)


def _extract_json(text: str) -> Dict[str, Any]:
    candidate = text.strip()
    candidate = re.sub(r"```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.replace("```", "").strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model did not return a JSON object")


class AgentRuntime:
    """A bounded runtime with explicit planning and execution state."""

    def __init__(
        self,
        db,
        user,
        service,
        retrieve_materials=None,
    ):
        self.db = db
        self.user = user
        self.service = service
        self.active_run_id: Optional[int] = None
        self.memory = AgentMemoryStore(db)
        self.registry = AgentToolRegistry(
            db,
            user,
            service,
            retrieve_materials=retrieve_materials,
        )

    async def _heuristic_plan(
        self, question: str, course_id: Optional[int], mode: str
    ) -> AgentPlan:
        text = question.lower()
        steps: List[AgentPlanStep] = []
        material_intent = any(
            word in text
            for word in (
                "资料", "课件", "文档", "讲义", "知识点", "概念", "原理", "material",
                "document", "concept", "explain",
            )
        )
        assignment_intent = any(
            word in text
            for word in ("作业", "任务", "截止", "待办", "assignment", "deadline")
        )
        grade_intent = any(
            word in text
            for word in ("成绩", "分数", "低分", "薄弱", "grade", "score", "weak")
        )
        plan_intent = any(
            word in text
            for word in ("建议", "教学", "计划", "规划", "复习", "提升", "安排", "plan", "review")
        ) or mode == "teaching_advice"

        if material_intent and course_id:
            steps.append(
                AgentPlanStep(
                    tool="retrieve_course_material",
                    reason="需要从课程索引中检索可引用的材料",
                    args={"course_id": course_id, "question": question},
                )
            )
        if assignment_intent and course_id:
            steps.append(
                AgentPlanStep(
                    tool="get_course_assignments",
                    reason="需要读取课程作业和截止时间",
                    args={"course_id": course_id},
                )
            )
        if (grade_intent or plan_intent) and self.user.role in {"ADMIN", "TEACHER"} and course_id:
            steps.append(
                AgentPlanStep(
                    tool="get_course_statistics",
                    reason="需要读取课程教学统计支撑建议",
                    args={"course_id": course_id},
                )
            )
        elif grade_intent or plan_intent:
            if course_id:
                steps.append(
                    AgentPlanStep(
                        tool="analyze_learning_gaps",
                        reason="需要基于成绩计算薄弱项",
                        args={"course_id": course_id},
                    )
                )
            else:
                steps.append(
                    AgentPlanStep(
                        tool="get_my_grades",
                        reason="需要读取当前用户的成绩数据",
                        args={},
                    )
                )
        if plan_intent and course_id and self.user.role == "STUDENT":
            steps.append(
                AgentPlanStep(
                    tool="generate_learning_plan",
                    reason="把成绩分析和作业转换为可执行任务",
                    args={"course_id": course_id},
                )
            )
        if not steps:
            steps.append(
                AgentPlanStep(
                    tool="get_course_overview",
                    reason="先获取当前用户可见的课程上下文",
                    args={"course_id": course_id} if course_id else {},
                )
            )
        return AgentPlan(
            objective=f"完成用户请求：{question[:900]}",
            steps=steps,
        )

    async def plan(
        self,
        question: str,
        course_id: Optional[int],
        mode: str,
        memory: List[Dict[str, Any]],
    ) -> tuple[AgentPlan, str]:
        tool_catalog = self.registry.specs()
        prompt = f"""You are the planning model inside a controlled education Agent.
Return JSON only with this shape:
{{"objective":"...", "steps":[{{"tool":"registered tool name","reason":"...","args":{{}}}}]}}
Use no more than 6 steps. Only use tools from TOOL_CATALOG.
The runtime validates permissions and arguments; never invent tool names.
User role: {self.user.role}
Mode: {mode}
Course id: {course_id}
User request: {question}
Recent memory: {json.dumps(memory[-4:], ensure_ascii=False, default=str)}
TOOL_CATALOG: {json.dumps(tool_catalog, ensure_ascii=False)}
"""
        planner_error = None
        raw_model_output = ""
        try:
            llm = get_llm(temperature=0.0)
            response = await llm.ainvoke(prompt)
            raw_model_output = _content(response)
            plan = AgentPlan.model_validate(_extract_json(raw_model_output))
            return plan, "model"
        except (Exception, ValidationError) as exc:
            planner_error = str(exc)

        # A second, smaller repair pass handles models that wrap valid plans in
        # prose or markdown. The fallback remains explicit in the run trace.
        try:
            repair_prompt = (
                "Convert the following model output into JSON only. Do not add "
                "explanations. Preserve only objective and steps, and use the "
                "registered tool names from the catalog.\n"
                f"CATALOG: {json.dumps(tool_catalog, ensure_ascii=False)}\n"
                f"MODEL_OUTPUT: {raw_model_output[:12000]}\n"
            )
            repaired = await get_llm(temperature=0.0).ainvoke(repair_prompt)
            plan = AgentPlan.model_validate(_extract_json(_content(repaired)))
            return plan, "model_repaired"
        except Exception as exc:
            planner_error = f"{planner_error}; repair: {exc}"

        plan = await self._heuristic_plan(question, course_id, mode)
        # The caller persists this diagnostic in the run plan and tool trace.
        plan.objective = f"{plan.objective} [planner_fallback: {planner_error[:300]}]"
        return plan, "heuristic_fallback"

    def _prepare_step(
        self, step: AgentPlanStep, question: str, course_id: Optional[int]
    ) -> AgentPlanStep:
        args = dict(step.args)
        if course_id is not None and "course_id" not in args:
            if step.tool in {
                "get_course_assignments",
                "retrieve_course_material",
                "analyze_learning_gaps",
                "generate_learning_plan",
            }:
                args["course_id"] = course_id
        if step.tool == "retrieve_course_material":
            args.setdefault("question", question)
        normalized = self.registry.prepare(step.tool, args)
        return AgentPlanStep(tool=step.tool, reason=step.reason, args=normalized)

    async def _synthesize(
        self,
        question: str,
        plan: AgentPlan,
        execution: List[Dict[str, Any]],
        memory: List[Dict[str, Any]],
    ) -> tuple[str, str]:
        prompt = f"""You are the answer model for EduAgent.
Answer in Chinese unless the user asks otherwise. Be concise and actionable.
Use only the execution results and memory below. State when data is missing.
Do not claim an action happened if its step failed or is awaiting confirmation.
USER: {question}
            PLAN: {json.dumps(plan.model_dump(), ensure_ascii=False, default=str)}
EXECUTION: {json.dumps(execution, ensure_ascii=False, default=str)[:16000]}
MEMORY: {json.dumps(memory[-6:], ensure_ascii=False, default=str)}
"""
        try:
            llm = get_llm(temperature=0.25)
            response = await llm.ainvoke(prompt)
            return _content(response), "model"
        except Exception:
            successful = [
                item for item in execution if item.get("status") == "COMPLETED"
            ]
            if not successful:
                return "我暂时没有取得足够的业务数据来回答这个问题。", "fallback"
            fragments = []
            for item in successful:
                output = item.get("output") or {}
                if item["tool"] == "retrieve_course_material":
                    fragments.append(
                        "检索到课程材料："
                        + "；".join(
                            str(c.get("content", ""))[:180]
                            for c in output.get("citations", [])[:3]
                        )
                    )
                elif item["tool"] == "generate_learning_plan":
                    fragments.append(
                        "已生成学习计划："
                        + json.dumps(output.get("daily_tasks", []), ensure_ascii=False)
                    )
                else:
                    fragments.append(
                        f"{item['tool']} 返回 {json.dumps(output, ensure_ascii=False)[:600]}"
                    )
            return "\n".join(fragments), "fallback"

    async def run(
        self,
        question: str,
        course_id: Optional[int],
        mode: str,
        session_id: str,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        started = time.time()
        run = await self.service.create_run(
            user_id=self.user.id,
            role=self.user.role,
            workflow="agent_runtime",
            input_summary=f"{mode}: {question[:120]}",
        )
        self.active_run_id = run.id
        memory = await self.memory.load(
            self.user.id, session_id, course_id, limit=8
        )
        plan, planner_source = await self.plan(question, course_id, mode, memory)
        prepared_steps: List[AgentPlanStep] = []
        rejected: List[Dict[str, Any]] = []
        for step in plan.steps:
            try:
                prepared_steps.append(self._prepare_step(step, question, course_id))
            except AgentToolError as exc:
                rejected.append(
                    {"tool": step.tool, "status": "REJECTED", "error": str(exc)}
                )
        plan = AgentPlan(objective=plan.objective, steps=prepared_steps)
        await self.service.update_run_plan(
            run.id,
            {
                "planner_source": planner_source,
                "objective": plan.objective,
                "steps": [step.model_dump() for step in plan.steps],
                "rejected": rejected,
            },
        )
        await self.service.log_tool_call_json(
            run.id,
            "agent_planner",
            {"question": question, "mode": mode},
            {
                "source": planner_source,
                "plan": plan.model_dump(),
                "rejected": rejected,
            },
        )

        pending = [
            step for step in plan.steps
            if self.registry.get(step.tool).requires_confirmation and not confirm
        ]
        if pending:
            answer = (
                "计划中包含需要确认的操作："
                + "、".join(step.tool for step in pending)
                + "。请确认后再次提交同一请求。"
            )
            await self.service.update_run_status(
                run.id,
                "WAITING_CONFIRMATION",
                output_summary=answer,
            )
            return {
                "answer": answer,
                "status": "WAITING_CONFIRMATION",
                "plan": plan.model_dump(),
                "executed_steps": [],
                "requires_confirmation": [step.model_dump() for step in pending],
                "memory": {"session_id": session_id, "used_count": len(memory)},
                "run_id": run.id,
                "citations": [],
                "confidence": 0.0,
                "confirmation_required": True,
            }

        execution: List[Dict[str, Any]] = []
        for step in plan.steps:
            started_step = time.time()
            trace: Dict[str, Any] = {
                "tool": step.tool,
                "args": step.args,
                "reason": step.reason,
                "status": "RUNNING",
            }
            try:
                output = await self.registry.execute(step.tool, step.args)
                trace.update(
                    {
                        "status": "COMPLETED",
                        "output": output,
                        "latency_ms": int((time.time() - started_step) * 1000),
                    }
                )
                await self.service.log_tool_call_json(
                    run.id,
                    step.tool,
                    step.args,
                    output,
                    latency_ms=trace["latency_ms"],
                )
            except Exception as exc:
                trace.update(
                    {
                        "status": "FAILED",
                        "error": str(exc),
                        "latency_ms": int((time.time() - started_step) * 1000),
                    }
                )
                await self.service.log_tool_call_json(
                    run.id,
                    step.tool,
                    step.args,
                    {},
                    latency_ms=trace["latency_ms"],
                    error=str(exc),
                )
            execution.append(trace)

        answer, synthesis_source = await self._synthesize(
            question, plan, execution, memory
        )
        await self.service.log_tool_call_json(
            run.id,
            "agent_synthesis",
            {"question": question, "step_count": len(execution)},
            {"answer": answer, "source": synthesis_source},
        )
        citations = []
        for trace in execution:
            citations.extend((trace.get("output") or {}).get("citations", []))
        confidence = max(
            [float(item.get("similarity", 0)) for item in citations] or [0.0]
        )
        await self.memory.remember_turn(
            self.user.id,
            session_id,
            course_id,
            question,
            answer,
            [item["tool"] for item in execution],
        )
        latency = int((time.time() - started) * 1000)
        await self.service.log_qa(
            course_id=course_id or 0,
            user_id=self.user.id,
            question=question,
            answer=answer,
            citations=json.dumps(citations, ensure_ascii=False),
            confidence=confidence,
            latency_ms=latency,
        )
        await self.service.complete_run(
            run.id,
            output_summary=answer[:500],
            latency_ms=latency,
        )
        return {
            "answer": answer,
            "status": "COMPLETED",
            "plan": plan.model_dump(),
            "executed_steps": execution,
            "requires_confirmation": [],
            "memory": {"session_id": session_id, "used_count": len(memory)},
            "run_id": run.id,
            "citations": citations[:10],
            "confidence": confidence,
            "confirmation_required": False,
        }
