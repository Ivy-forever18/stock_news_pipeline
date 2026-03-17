from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.news_api import news_bp
from src.schemas.base import ToolEnvelope


def test_orchestrator_runs_tool_calls_then_final_answer(monkeypatch):
    import src.agent.orchestrator as orch_mod

    llm_calls = {"n": 0}
    executed = []

    def _fake_call_llm(*, prompt, model, json_output, system_prompt, **kwargs):
        llm_calls["n"] += 1
        if json_output:
            if "need_more_tools" in system_prompt:
                return '{"need_more_tools": false, "reason": "enough", "additional_tool_calls": []}'
            return (
                '{"assistant_plan":"query portfolio",'
                '"tool_calls":[{"tool":"PMB.portfolio.snapshot","params":{"portfolio_id":"p1"}}]}'
            )
        return "Final synthesized answer based on tool results\n\nEvidence\n- [1] PMB.portfolio.snapshot"

    def _fake_call_tool(tool_name, params, mode):
        executed.append((tool_name, params))
        return ToolEnvelope.ok(tool=tool_name, data={"portfolio_id": "p1", "cash": 100000.0})

    monkeypatch.setattr(orch_mod, "call_llm", _fake_call_llm)
    monkeypatch.setattr(orch_mod, "call_tool", _fake_call_tool)

    orchestrator = orch_mod.AgentOrchestrator(model="deepseek-chat")
    out = orchestrator.answer("what is my portfolio cash?")

    assert out["assistant_plan"] == "query portfolio"
    assert len(out["tool_calls"]) == 1
    assert executed == [("PMB.portfolio.snapshot", {"portfolio_id": "p1"})]
    assert "Final synthesized answer based on tool results" in out["final_answer"]
    assert "Evidence" in out["final_answer"]
    assert out["evidence"]["stats"]["total"] == 1
    assert out["evidence"]["items"][0]["tool"] == "PMB.portfolio.snapshot"
    assert len(out["reflection_history"]) == 1
    assert llm_calls["n"] == 3


def test_agent_ask_api_requires_question():
    app = Flask(__name__)
    app.register_blueprint(news_bp, url_prefix="/api")
    app.config["TESTING"] = True
    client = app.test_client()

    resp = client.post("/api/agent/ask", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False


def test_agent_ask_api_success(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(news_bp, url_prefix="/api")
    app.config["TESTING"] = True
    client = app.test_client()

    import src.agent.orchestrator as orch_mod

    def _fake_answer(self, question, max_tool_calls=6, max_tool_budget=6.0):
        return {
            "question": question,
            "assistant_plan": "plan",
            "tool_calls": [],
            "tool_results": [],
            "evidence": {"items": [], "stats": {"total": 0, "ok": 0, "error": 0, "unknown": 0}},
            "tool_budget": {"max": max_tool_budget, "used": 0.0, "remaining": max_tool_budget},
            "final_answer": "ok",
        }

    monkeypatch.setattr(orch_mod.AgentOrchestrator, "answer_with_budget", _fake_answer)

    resp = client.post("/api/agent/ask", json={"question": "hello"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["result"]["final_answer"] == "ok"
