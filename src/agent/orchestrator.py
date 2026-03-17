from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from src.agent.llm_client import call_llm
from src.schemas.base import RunMode
from src.tools.registry import TOOL_REGISTRY, call_tool


@dataclass
class ToolCall:
    tool: str
    params: Dict[str, Any]


@dataclass
class ScoredToolCall:
    tool: str
    params: Dict[str, Any]
    cost: float
    gain: float
    score: float


class AgentOrchestrator:
    """Tool-using orchestrator:

    1) user question
    2) build system prompt with available tools
    3) ask LLM for JSON tool_calls
    4) execute tools
    5) feed tool results back to LLM
    6) LLM produces final answer
    """

    def __init__(
        self,
        model: str = "deepseek-chat",
        mode: RunMode = RunMode.BACKTEST,
        max_reflection_rounds: int = 1,
    ):
        self.model = model
        self.mode = mode
        self.max_reflection_rounds = max(0, int(max_reflection_rounds))

    TOOL_COSTS: Dict[str, float] = {
        "NPP": 1.2,
        "UPQ": 1.3,
        "PMB": 1.0,
        "QLIB": 2.5,
    }

    QUESTION_TOOL_KEYWORDS: Dict[str, List[str]] = {
        "NPP": ["news", "headline", "event", "earnings", "fomc", "macro"],
        "UPQ": ["price", "bar", "quote", "option", "iv", "volatility", "ohlc"],
        "PMB": ["portfolio", "position", "order", "cash", "pnl", "broker"],
        "QLIB": ["qlib", "factor", "alpha", "expression", "signal"],
    }

    def _tool_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in TOOL_REGISTRY
        ]

    def _planning_system_prompt(self) -> str:
        catalog = json.dumps(self._tool_catalog(), ensure_ascii=False)
        return (
            "You are a financial data assistant that can use tools. "
            "Decide which tools to call before answering.\n\n"
            "Available tools (JSON):\n"
            f"{catalog}\n\n"
            "Return STRICT JSON only with this schema:\n"
            "{\n"
            '  "assistant_plan": "short plan",\n'
            '  "tool_calls": [\n'
            '    {"tool": "Tool.Name", "params": {}}\n'
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Use only tools from catalog.\n"
            "- Keep tool_calls minimal and relevant.\n"
            "- If no tool needed, return an empty tool_calls array."
        )

    def _reflection_system_prompt(self) -> str:
        catalog = json.dumps(self._tool_catalog(), ensure_ascii=False)
        return (
            "You are a reflection module for a tool-using agent. "
            "Given current tool outputs, decide whether more tool calls are needed.\n\n"
            "Available tools (JSON):\n"
            f"{catalog}\n\n"
            "Return STRICT JSON:\n"
            "{\n"
            '  "need_more_tools": true/false,\n'
            '  "reason": "short reason",\n'
            '  "additional_tool_calls": [{"tool":"Tool.Name","params":{}}]\n'
            "}\n"
            "Rules:\n"
            "- Use only tools from catalog.\n"
            "- If enough information is already available, set need_more_tools=false.\n"
            "- Keep additional_tool_calls concise and high-signal."
        )

    @staticmethod
    def _extract_json(raw: str) -> Dict[str, Any]:
        s = (raw or "").strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.startswith("json"):
                s = s[4:].strip()
        try:
            return json.loads(s)
        except Exception:
            start = s.find("{")
            end = s.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(s[start : end + 1])
            raise

    @staticmethod
    def _tool_family(tool_name: str) -> str:
        if not isinstance(tool_name, str) or "." not in tool_name:
            return "UNKNOWN"
        return tool_name.split(".", 1)[0].upper()

    def _estimate_tool_cost(self, tool_name: str, params: Dict[str, Any]) -> float:
        family = self._tool_family(tool_name)
        base_cost = float(self.TOOL_COSTS.get(family, 1.0))
        # Slightly increase cost for wide queries that are likely more expensive.
        param_penalty = 0.0
        if isinstance(params, dict):
            if (params.get("limit") or 0) and isinstance(params.get("limit"), int):
                limit = int(params.get("limit", 0))
                if limit > 20:
                    param_penalty += min(0.8, (limit - 20) / 200.0)
            if params.get("symbols") and isinstance(params.get("symbols"), list):
                param_penalty += min(0.8, len(params.get("symbols", [])) / 50.0)
        return max(0.1, base_cost + param_penalty)

    def _estimate_information_gain(self, question: str, tool_name: str, params: Dict[str, Any]) -> float:
        family = self._tool_family(tool_name)
        q = (question or "").lower()
        gain = 1.0
        for kw in self.QUESTION_TOOL_KEYWORDS.get(family, []):
            if kw in q:
                gain += 0.7

        # Richer parameterized calls are often more targeted and useful.
        if isinstance(params, dict):
            gain += min(0.8, len(params.keys()) * 0.1)
            if params.get("symbol"):
                gain += 0.2
            if params.get("portfolio_id"):
                gain += 0.2

        # Prefer deterministic, state-retrieval tools over expensive generation by default.
        if family == "QLIB":
            gain -= 0.3
        return max(0.2, gain)

    def _prioritize_tool_calls(
        self,
        question: str,
        tool_calls: List[Dict[str, Any]],
        max_tool_calls: int,
        max_tool_budget: float,
    ) -> List[Dict[str, Any]]:
        scored: List[ScoredToolCall] = []
        for item in tool_calls:
            tool = item.get("tool")
            params = item.get("params") or {}
            if not isinstance(tool, str) or not isinstance(params, dict):
                continue
            cost = self._estimate_tool_cost(tool, params)
            gain = self._estimate_information_gain(question, tool, params)
            score = gain / max(cost, 0.1)
            scored.append(ScoredToolCall(tool=tool, params=params, cost=cost, gain=gain, score=score))

        scored.sort(key=lambda x: (x.score, x.gain), reverse=True)

        selected: List[Dict[str, Any]] = []
        budget_used = 0.0
        for s in scored:
            if len(selected) >= max_tool_calls:
                break
            if budget_used + s.cost > max_tool_budget:
                continue
            selected.append({"tool": s.tool, "params": s.params})
            budget_used += s.cost
        return selected

    def plan_tool_calls(
        self,
        question: str,
        max_tool_calls: int = 6,
        max_tool_budget: float | None = None,
    ) -> Dict[str, Any]:
        if max_tool_budget is None:
            max_tool_budget = float(max_tool_calls)
        max_tool_budget = max(0.1, float(max_tool_budget))

        raw = call_llm(
            prompt=question,
            model=self.model,
            json_output=True,
            system_prompt=self._planning_system_prompt(),
            service_provider="default",
        )

        if isinstance(raw, str) and raw.startswith("LLM API error:"):
            return {"assistant_plan": "llm_error", "tool_calls": [], "raw": raw}

        parsed = self._extract_json(raw)
        tool_calls_in = parsed.get("tool_calls") or []

        normalized: List[Dict[str, Any]] = []
        for item in tool_calls_in[:max_tool_calls]:
            if not isinstance(item, dict):
                continue
            tool = item.get("tool")
            params = item.get("params") or {}
            if not isinstance(tool, str) or not isinstance(params, dict):
                continue
            normalized.append({"tool": tool, "params": params})

        prioritized = self._prioritize_tool_calls(
            question=question,
            tool_calls=normalized,
            max_tool_calls=max_tool_calls,
            max_tool_budget=max_tool_budget,
        )

        return {
            "assistant_plan": parsed.get("assistant_plan", ""),
            "tool_calls": prioritized,
            "raw": parsed,
        }

    def execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        outputs: List[Dict[str, Any]] = []
        for tc in tool_calls:
            tool = tc["tool"]
            params = tc["params"]
            try:
                env = call_tool(tool_name=tool, params=params, mode=self.mode)
                outputs.append(
                    {
                        "tool": tool,
                        "params": params,
                        "result": env.model_dump(),
                    }
                )
            except Exception as e:
                outputs.append(
                    {
                        "tool": tool,
                        "params": params,
                        "result": {
                            "tool": tool,
                            "status": "error",
                            "error": {"code": "EXEC_ERROR", "message": str(e), "retryable": False},
                        },
                    }
                )
        return outputs

    def reflect_and_replan(
        self,
        question: str,
        assistant_plan: str,
        current_tool_results: List[Dict[str, Any]],
        remaining_tool_budget: float,
        remaining_tool_calls: int,
    ) -> Dict[str, Any]:
        if remaining_tool_budget <= 0 or remaining_tool_calls <= 0:
            return {
                "need_more_tools": False,
                "reason": "tool budget/call limit exhausted",
                "additional_tool_calls": [],
                "raw": {},
            }

        reflection_prompt = (
            "User question:\n"
            f"{question}\n\n"
            "Current assistant plan:\n"
            f"{assistant_plan}\n\n"
            "Current tool results (JSON):\n"
            f"{json.dumps(current_tool_results, ensure_ascii=False)}\n\n"
            "Decide if more tools are needed before final answer."
        )

        raw = call_llm(
            prompt=reflection_prompt,
            model=self.model,
            json_output=True,
            system_prompt=self._reflection_system_prompt(),
            service_provider="default",
        )

        if isinstance(raw, str) and raw.startswith("LLM API error:"):
            return {
                "need_more_tools": False,
                "reason": f"reflection llm error: {raw}",
                "additional_tool_calls": [],
                "raw": raw,
            }

        parsed = self._extract_json(raw)
        need_more = bool(parsed.get("need_more_tools", False))
        extra_in = parsed.get("additional_tool_calls") or []

        normalized: List[Dict[str, Any]] = []
        for item in extra_in[:remaining_tool_calls]:
            if not isinstance(item, dict):
                continue
            tool = item.get("tool")
            params = item.get("params") or {}
            if not isinstance(tool, str) or not isinstance(params, dict):
                continue
            normalized.append({"tool": tool, "params": params})

        extra_calls = self._prioritize_tool_calls(
            question=question,
            tool_calls=normalized,
            max_tool_calls=remaining_tool_calls,
            max_tool_budget=max(0.1, float(remaining_tool_budget)),
        )

        return {
            "need_more_tools": bool(need_more and extra_calls),
            "reason": parsed.get("reason", ""),
            "additional_tool_calls": extra_calls,
            "raw": parsed,
        }

    @staticmethod
    def _build_evidence(tool_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        ok_count = 0
        error_count = 0

        for idx, tr in enumerate(tool_results, start=1):
            tool = tr.get("tool", "unknown")
            result = tr.get("result") or {}
            status = result.get("status", "unknown")
            data = result.get("data")
            error = result.get("error") if isinstance(result, dict) else None

            signal_key = None
            signal_value = None
            summary = ""

            if isinstance(data, dict):
                if "count" in data:
                    signal_key, signal_value = "count", data.get("count")
                elif "cash" in data:
                    signal_key, signal_value = "cash", data.get("cash")
                elif "equity" in data:
                    signal_key, signal_value = "equity", data.get("equity")
                summary = f"dict_keys={list(data.keys())[:6]}"
            elif isinstance(data, list):
                signal_key, signal_value = "items", len(data)
                summary = f"list_items={len(data)}"

            if signal_key is not None:
                summary = f"{signal_key}={signal_value}"
            elif not summary:
                summary = "no_structured_signal"

            if status == "ok":
                ok_count += 1
            elif status == "error":
                error_count += 1

            item = {
                "id": idx,
                "tool": tool,
                "status": status,
                "summary": summary,
                "signal": {"key": signal_key, "value": signal_value} if signal_key is not None else None,
                "error": error if status == "error" else None,
            }
            items.append(item)

        total = len(items)
        unknown = total - ok_count - error_count
        return {
            "items": items,
            "stats": {
                "total": total,
                "ok": ok_count,
                "error": error_count,
                "unknown": max(0, unknown),
            },
        }

    @staticmethod
    def _build_evidence_summary(tool_results: List[Dict[str, Any]]) -> str:
        evidence = AgentOrchestrator._build_evidence(tool_results)
        lines: List[str] = []
        for item in evidence.get("items", []):
            line = f"[{item.get('id')}] {item.get('tool')} status={item.get('status')}"
            if item.get("summary"):
                line += f" {item.get('summary')}"
            lines.append(line)
        return "\n".join(lines)

    def compose_final_answer(
        self,
        question: str,
        assistant_plan: str,
        tool_results: List[Dict[str, Any]],
        evidence: Dict[str, Any] | None = None,
    ) -> str:
        if evidence is None:
            evidence = self._build_evidence(tool_results)
        evidence_text = self._build_evidence_summary(tool_results)
        synthesis_prompt = (
            "User question:\n"
            f"{question}\n\n"
            "Assistant plan:\n"
            f"{assistant_plan}\n\n"
            "Tool execution results (JSON):\n"
            f"{json.dumps(tool_results, ensure_ascii=False)}\n\n"
            "Structured evidence (JSON):\n"
            f"{json.dumps(evidence, ensure_ascii=False)}\n\n"
            "Evidence summary:\n"
            f"{evidence_text or 'No tool evidence.'}\n\n"
            "Now provide the final answer to the user. "
            "Use tool results as primary evidence and be explicit about uncertainty when data is missing. "
            "At the end, include a short section titled 'Evidence' with bullet points referencing used tools."
        )

        final = call_llm(
            prompt=synthesis_prompt,
            model=self.model,
            json_output=False,
            system_prompt="You are a precise financial assistant.",
            service_provider="default",
        )

        if isinstance(final, str) and final.startswith("LLM API error:"):
            return (
                "I could execute tools, but final LLM synthesis failed. "
                "Please retry or switch model/provider.\n\n"
                f"Raw error: {final}"
            )
        final_text = final
        if "Evidence" not in final_text:
            final_text = f"{final_text}\n\nEvidence\n{evidence_text or '- no tool evidence'}"
        return final_text

    def answer(self, question: str, max_tool_calls: int = 6) -> Dict[str, Any]:
        return self.answer_with_budget(
            question=question,
            max_tool_calls=max_tool_calls,
            max_tool_budget=float(max_tool_calls),
        )

    def answer_with_budget(
        self,
        question: str,
        max_tool_calls: int = 6,
        max_tool_budget: float = 6.0,
    ) -> Dict[str, Any]:
        max_tool_budget = max(0.1, float(max_tool_budget))

        plan = self.plan_tool_calls(
            question=question,
            max_tool_calls=max_tool_calls,
            max_tool_budget=max_tool_budget,
        )
        calls = plan.get("tool_calls", [])
        tool_results = self.execute_tools(calls)
        reflection_history: List[Dict[str, Any]] = []

        budget_used = sum(self._estimate_tool_cost(tc.get("tool", ""), tc.get("params") or {}) for tc in calls)

        for _ in range(self.max_reflection_rounds):
            remaining_budget = max(0.0, max_tool_budget - budget_used)
            remaining_calls = max(0, max_tool_calls - len(calls))
            reflection = self.reflect_and_replan(
                question=question,
                assistant_plan=plan.get("assistant_plan", ""),
                current_tool_results=tool_results,
                remaining_tool_budget=remaining_budget,
                remaining_tool_calls=remaining_calls,
            )
            reflection_history.append(reflection)
            if not reflection.get("need_more_tools"):
                break

            extra_calls = reflection.get("additional_tool_calls", [])
            if not extra_calls:
                break

            extra_cost = sum(
                self._estimate_tool_cost(tc.get("tool", ""), tc.get("params") or {})
                for tc in extra_calls
            )
            if budget_used + extra_cost > max_tool_budget + 1e-9:
                break

            calls.extend(extra_calls)
            tool_results.extend(self.execute_tools(extra_calls))
            budget_used += extra_cost

        evidence = self._build_evidence(tool_results)

        final = self.compose_final_answer(
            question=question,
            assistant_plan=plan.get("assistant_plan", ""),
            tool_results=tool_results,
            evidence=evidence,
        )
        return {
            "question": question,
            "assistant_plan": plan.get("assistant_plan", ""),
            "tool_calls": calls,
            "tool_results": tool_results,
            "evidence": evidence,
            "reflection_history": reflection_history,
            "tool_budget": {
                "max": float(max_tool_budget),
                "used": float(round(budget_used, 4)),
                "remaining": float(round(max(0.0, max_tool_budget - budget_used), 4)),
            },
            "final_answer": final,
        }
