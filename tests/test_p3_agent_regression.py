from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_extract_json_plain():
    from src.agent.orchestrator import AgentOrchestrator

    parsed = AgentOrchestrator._extract_json('{"a":1}')
    assert parsed["a"] == 1


def test_extract_json_fenced():
    from src.agent.orchestrator import AgentOrchestrator

    parsed = AgentOrchestrator._extract_json("```json\n{\"a\":2}\n```")
    assert parsed["a"] == 2


def test_plan_tool_calls_normalizes_bad_items(monkeypatch):
    import src.agent.orchestrator as orch_mod

    def _fake_call_llm(**_kwargs):
        return (
            '{"assistant_plan":"p","tool_calls":['
            '{"tool":"PMB.portfolio.snapshot","params":{"portfolio_id":"x"}},'
            '123,{"tool":null,"params":{}},{"tool":"A","params":[]}'
            ']}'
        )

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    o = orch_mod.AgentOrchestrator(max_reflection_rounds=0)
    out = o.plan_tool_calls("q")
    assert len(out["tool_calls"]) == 2
    assert out["tool_calls"][0]["tool"] == "PMB.portfolio.snapshot"
    assert out["tool_calls"][1]["tool"] == "A"
    assert out["tool_calls"][1]["params"] == {}


def test_reflect_no_budget_returns_false():
    from src.agent.orchestrator import AgentOrchestrator

    o = AgentOrchestrator(max_reflection_rounds=1)
    r = o.reflect_and_replan("q", "p", [], remaining_tool_budget=0, remaining_tool_calls=1)
    assert r["need_more_tools"] is False


def test_reflect_additional_calls(monkeypatch):
    import src.agent.orchestrator as orch_mod

    def _fake_call_llm(**_kwargs):
        return '{"need_more_tools":true,"reason":"need","additional_tool_calls":[{"tool":"NPP.news.query","params":{"symbol":"AAPL"}}]}'

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    o = orch_mod.AgentOrchestrator(max_reflection_rounds=1)
    r = o.reflect_and_replan("q", "p", [], remaining_tool_budget=2, remaining_tool_calls=2)
    assert r["need_more_tools"] is True
    assert r["additional_tool_calls"][0]["tool"] == "NPP.news.query"


def test_answer_executes_reflection_extra_calls(monkeypatch):
    import src.agent.orchestrator as orch_mod
    from src.schemas.base import ToolEnvelope

    llm_counter = {"n": 0}
    executed = []

    def _fake_call_llm(*, json_output, system_prompt, **_kwargs):
        llm_counter["n"] += 1
        if json_output:
            if "need_more_tools" in system_prompt:
                return '{"need_more_tools":true,"reason":"more","additional_tool_calls":[{"tool":"PMB.portfolio.snapshot","params":{"portfolio_id":"p1"}}]}'
            return '{"assistant_plan":"p","tool_calls":[{"tool":"PMB.order.status","params":{"order_id":"o1","portfolio_id":"p1"}}]}'
        return "answer"

    def _fake_call_tool(tool_name, params, mode):
        executed.append(tool_name)
        return ToolEnvelope.ok(tool=tool_name, data={"ok": True})

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    monkeypatch.setattr(orch_mod, "call_tool", _fake_call_tool)

    o = orch_mod.AgentOrchestrator(max_reflection_rounds=1)
    out = o.answer_with_budget("q", max_tool_calls=3, max_tool_budget=3.0)
    assert len(out["tool_calls"]) == 2
    assert executed == ["PMB.order.status", "PMB.portfolio.snapshot"]
    assert llm_counter["n"] == 3
    assert out["tool_budget"]["used"] >= 2.0
    assert out["evidence"]["stats"]["total"] == 2
    assert out["evidence"]["items"][0]["tool"] == "PMB.order.status"


def test_build_evidence_summary_count_field():
    from src.agent.orchestrator import AgentOrchestrator

    text = AgentOrchestrator._build_evidence_summary([
        {"tool": "NPP.news.query", "result": {"status": "ok", "data": {"count": 3}}}
    ])
    assert "count=3" in text


def test_build_evidence_structured_payload():
    from src.agent.orchestrator import AgentOrchestrator

    payload = AgentOrchestrator._build_evidence([
        {"tool": "NPP.news.query", "result": {"status": "ok", "data": {"count": 3}}},
        {
            "tool": "UPQ.market.bars",
            "result": {
                "status": "error",
                "error": {"code": "E", "message": "x", "retryable": False},
            },
        },
    ])
    assert payload["stats"]["total"] == 2
    assert payload["stats"]["ok"] == 1
    assert payload["stats"]["error"] == 1
    assert payload["items"][0]["signal"] == {"key": "count", "value": 3}
    assert payload["items"][1]["error"]["code"] == "E"


def test_compose_final_appends_evidence_if_missing(monkeypatch):
    import src.agent.orchestrator as orch_mod

    def _fake_call_llm(**_kwargs):
        return "final without section"

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    o = orch_mod.AgentOrchestrator(max_reflection_rounds=0)
    text = o.compose_final_answer("q", "p", [])
    assert "Evidence" in text


def test_compose_final_keeps_existing_evidence(monkeypatch):
    import src.agent.orchestrator as orch_mod

    def _fake_call_llm(**_kwargs):
        return "final\n\nEvidence\n- already"

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    o = orch_mod.AgentOrchestrator(max_reflection_rounds=0)
    text = o.compose_final_answer("q", "p", [])
    assert text.count("Evidence") == 1


def test_agent_api_passes_reflection_rounds(monkeypatch):
    from flask import Flask
    from src.api.news_api import news_bp
    import src.agent.orchestrator as orch_mod

    init_args = {}

    original_init = orch_mod.AgentOrchestrator.__init__

    def _fake_init(self, model="deepseek-chat", mode=None, max_reflection_rounds=1):
        init_args["max_reflection_rounds"] = max_reflection_rounds
        original_init(self, model=model, mode=mode, max_reflection_rounds=max_reflection_rounds)

    def _fake_answer(self, question, max_tool_calls=6, max_tool_budget=6.0):
        return {
            "question": question,
            "assistant_plan": "p",
            "tool_calls": [],
            "tool_results": [],
            "evidence": {"items": [], "stats": {"total": 0, "ok": 0, "error": 0, "unknown": 0}},
            "reflection_history": [],
            "tool_budget": {"max": max_tool_budget, "used": 0.0, "remaining": max_tool_budget},
            "final_answer": "ok",
        }

    monkeypatch.setattr(orch_mod.AgentOrchestrator, "__init__", _fake_init)
    monkeypatch.setattr(orch_mod.AgentOrchestrator, "answer_with_budget", _fake_answer)

    app = Flask(__name__)
    app.register_blueprint(news_bp, url_prefix="/api")
    app.config["TESTING"] = True
    client = app.test_client()

    resp = client.post("/api/agent/ask", json={"question": "q", "max_reflection_rounds": 2})
    assert resp.status_code == 200
    assert init_args["max_reflection_rounds"] == 2


def test_plan_tool_calls_budget_prefers_higher_value(monkeypatch):
    import src.agent.orchestrator as orch_mod

    def _fake_call_llm(**_kwargs):
        return (
            '{"assistant_plan":"p","tool_calls":['
            '{"tool":"QLIB.factor.generate","params":{"task":"gen"}},'
            '{"tool":"PMB.portfolio.snapshot","params":{"portfolio_id":"p1"}},'
            '{"tool":"NPP.news.query","params":{"symbol":"AAPL"}}'
            ']}'
        )

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    o = orch_mod.AgentOrchestrator(max_reflection_rounds=0)
    out = o.plan_tool_calls(
        question="what is my portfolio cash and positions?",
        max_tool_calls=3,
        max_tool_budget=1.2,
    )
    assert len(out["tool_calls"]) == 1
    assert out["tool_calls"][0]["tool"] == "PMB.portfolio.snapshot"


def test_answer_with_budget_limits_reflection_extra_calls(monkeypatch):
    import src.agent.orchestrator as orch_mod
    from src.schemas.base import ToolEnvelope

    def _fake_call_llm(*, json_output, system_prompt, **_kwargs):
        if json_output:
            if "need_more_tools" in system_prompt:
                return '{"need_more_tools":true,"reason":"need","additional_tool_calls":[{"tool":"QLIB.factor.generate","params":{"task":"gen"}}]}'
            return '{"assistant_plan":"p","tool_calls":[{"tool":"PMB.order.status","params":{"order_id":"o1","portfolio_id":"p1"}}]}'
        return "answer"

    executed = []

    def _fake_call_tool(tool_name, params, mode):
        executed.append(tool_name)
        return ToolEnvelope.ok(tool=tool_name, data={"ok": True})

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    monkeypatch.setattr(orch_mod, "call_tool", _fake_call_tool)

    o = orch_mod.AgentOrchestrator(max_reflection_rounds=1)
    out = o.answer_with_budget("q", max_tool_calls=3, max_tool_budget=1.5)
    assert out["tool_calls"] == [{"tool": "PMB.order.status", "params": {"order_id": "o1", "portfolio_id": "p1"}}]
    assert executed == ["PMB.order.status"]
