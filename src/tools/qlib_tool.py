"""
qlib_tool.py – QLIB.factor.generate 工具

封装 LLM 驱动的 Qlib alpha 因子生成器，供 AgentOrchestrator 通过工具调用触发。
不依赖 qlib 库或不存在的 agent.robust.valid，只做：
  LLM 生成 → 轻量语法校验 → (可选) factor_eval_api 打分 → ToolEnvelope 返回
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from src.schemas.base import MetaInfo, RunMode, ToolEnvelope
from src.tools.market_clock import MarketClock
from src.agent.llm_client import call_llm
from src.agent.prompts.bank import QLIB_GENERATE_INSTRUCTION

logger = logging.getLogger(__name__)

TOOL_NAME = "QLIB.factor.generate"
ALLOWED_VARS = {
    "$close", "$open", "$high", "$low", "$volume",
    # Event-driven features built from local news + macro caches
    "$news_count", "$news_sentiment", "$news_importance",
    "$event_score", "$fomc_risk", "$high_vol_day",
}

_SYSTEM_PROMPT = f"""You are an expert quantitative researcher who designs alpha factors for stock ranking.
Generate a single new Qlib alpha factor in JSON format.

Rules:
- Variables: market vars ($close, $open, $high, $low, $volume)
    and event vars ($news_count, $news_sentiment, $news_importance, $event_score, $fomc_risk, $high_vol_day)
- Use CamelCase function names (Qlib style, e.g. Div, Sub, Mean, Rank)
- Parentheses must balance exactly
- Division: always add epsilon: Div(x, Add(den, 1e-12))
- Expression depth <= 4
- Return a single JSON object (no markdown fences)

Event-driven guidance:
- Prefer combining price structure + event signal, e.g. Mul(Rank(Sub($close, Ref($close, 5)), 20), $event_score)
- Add risk control by suppressing signals on high event risk days, e.g. Mul(alpha, Sub(1, $high_vol_day))
- Around FOMC events, avoid over-leverage unless directional confidence is high.

{QLIB_GENERATE_INSTRUCTION}

Output format:
{{
  "name": "MomentumRatio5d",
  "expression": "Div(Sub($close, Ref($close, 5)), Add(Ref($close, 5), 1e-12))",
  "description": "5-day price momentum ratio"
}}
"""


def _validate_expression(expr: str) -> tuple[bool, str]:
    """Lightweight syntactic validation (no qlib runtime required)."""
    # 1. Balanced parentheses
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False, "Unbalanced parentheses (extra closing paren)"
    if depth != 0:
        return False, f"Unbalanced parentheses ({depth} unclosed)"

    # 2. No raw arithmetic operators between identifiers/numbers
    if re.search(r'(?<![0-9eE(,\s])[+\-\*/](?![0-9eE.\s])', expr):
        return False, "Raw arithmetic operators found; use Add/Sub/Mul/Div instead"

    # 3. Only allowed $ variables
    vars_found = set(re.findall(r'\$\w+', expr))
    disallowed = vars_found - ALLOWED_VARS
    if disallowed:
        return False, f"Disallowed variables: {sorted(disallowed)}"

    # 4. At least one recognised function call
    if not re.search(r'[A-Z][a-zA-Z]+\(', expr):
        return False, "Expression must use at least one Qlib function (e.g. Mean, Rank, Div)"

    return True, "OK"


def qlib_factor_generate(
    req: dict,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    """
    QLIB.factor.generate – LLM-driven alpha factor generation.

    Request keys:
      instruction  str   – User prompt / idea description (required)
      model        str   – LLM model identifier (default: deepseek-chat)
      max_try      int   – Retry attempts on validation failure (default: 3)
      temperature  float – LLM sampling temperature (default: 1.0)
      evaluate     bool  – If True, call factor_eval_api to get IC score (default: False)
    """
    asof = clock.now() if clock else datetime.now(timezone.utc)
    instruction = req.get("instruction") or "Generate a novel alpha factor for stock ranking."
    model = req.get("model") or "deepseek-chat"
    max_try = int(req.get("max_try") or 3)
    temperature = float(req.get("temperature") or 1.0)
    do_evaluate = bool(req.get("evaluate", False))

    current_instruction = instruction
    last_error = ""

    for attempt in range(1, max_try + 1):
        try:
            raw = call_llm(
                prompt=current_instruction,
                model=model,
                system_prompt=_SYSTEM_PROMPT,
                json_output=True,
                temperature=temperature,
                service_provider="default",
            )

            # Strip markdown fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict) or "expression" not in parsed:
                last_error = f"Missing 'expression' key in output: {cleaned[:200]}"
                current_instruction = (
                    f"Previous output was missing the 'expression' field.\n"
                    f"Output was: {cleaned[:300]}\n\n"
                    f"Original task: {instruction}"
                )
                continue

            expr = parsed["expression"]
            if not isinstance(expr, str):
                expr = str(expr)
            valid, msg = _validate_expression(expr)
            if not valid:
                last_error = f"Validation failed [{msg}] for: {expr[:120]}"
                current_instruction = (
                    f"Previous expression was invalid: {msg}\n"
                    f"Expression: {expr}\n"
                    f"Fix the issue and regenerate.\n\n"
                    f"Original task: {instruction}"
                )
                continue

            # Optional: evaluate via factor_eval_api
            eval_result: dict = {}
            if do_evaluate:
                try:
                    from src.api.factor_eval_client import check_factor_via_api
                    check_result = check_factor_via_api(expr)
                    ok = bool(check_result.get("success", False))
                    err = (
                        check_result.get("error")
                        or check_result.get("error_message")
                        or None
                    )
                    eval_result = {
                        "check_passed": ok,
                        "check_error": err,
                        "raw": check_result,
                    }
                except Exception as eval_exc:
                    eval_result = {"check_passed": None, "check_error": str(eval_exc)}

            result_data = {**parsed}
            if eval_result:
                result_data["eval"] = eval_result

            return ToolEnvelope.ok(
                tool=TOOL_NAME,
                asof=asof,
                data=result_data,
                mode=mode,
                meta=MetaInfo(
                    source=["llm"],
                    warnings=[f"Produced on attempt {attempt}/{max_try}"] if attempt > 1 else [],
                ),
            )

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error (attempt {attempt}): {e}"
            current_instruction = (
                f"Output could not be parsed as JSON. Error: {e}\n"
                f"Please output only a valid JSON object, no markdown, no extra text.\n\n"
                f"Original task: {instruction}"
            )
        except Exception as e:
            last_error = f"Unexpected error (attempt {attempt}): {e}"
            logger.exception("qlib_factor_generate failed")

    return ToolEnvelope.error(
        tool=TOOL_NAME,
        asof=asof,
        code="GENERATION_FAILED",
        message=f"Factor generation failed after {max_try} attempts: {last_error}",
    )
