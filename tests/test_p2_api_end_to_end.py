from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.news_api import news_bp


def _client():
    app = Flask(__name__)
    app.register_blueprint(news_bp, url_prefix="/api")
    app.config["TESTING"] = True
    return app.test_client()


def test_tools_list_endpoint_contains_registry_tools():
    client = _client()
    resp = client.get("/api/tools/list")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "NPP.news.query" in body["tools"]
    assert "PMB.order.place" in body["tools"]


def test_tools_call_endpoint_places_order_and_returns_snapshot():
    import src.tools.pmb_tool as pmb_mod

    pmb_mod._ORDER_STORE.clear()
    pmb_mod._PORTFOLIO_STORE.clear()
    pmb_mod._LAST_PRICE.clear()

    client = _client()

    place_resp = client.post(
        "/api/tools/call",
        json={
            "tool": "PMB.order.place",
            "mode": "BACKTEST",
            "params": {
                "portfolio_id": "api_p2",
                "symbol": "AAPL",
                "action": "BUY",
                "order_type": "MARKET",
                "quantity": 5,
            },
        },
    )
    assert place_resp.status_code == 200
    place_body = place_resp.get_json()
    assert place_body["success"] is True
    assert place_body["result"]["status"] == "ok"

    snap_resp = client.post(
        "/api/tools/call",
        json={
            "tool": "PMB.portfolio.snapshot",
            "params": {"portfolio_id": "api_p2"},
        },
    )
    assert snap_resp.status_code == 200
    snap_body = snap_resp.get_json()
    assert snap_body["success"] is True
    assert snap_body["result"]["status"] == "ok"
    assert snap_body["result"]["data"]["cash"] == 99500.0
    assert len(snap_body["result"]["data"]["positions"]) == 1


def test_tools_call_validates_payload_shape():
    client = _client()

    bad_resp = client.post("/api/tools/call", json={"params": {}})
    assert bad_resp.status_code == 400
    assert bad_resp.get_json()["success"] is False

    bad_resp2 = client.post(
        "/api/tools/call",
        json={"tool": "PMB.portfolio.snapshot", "params": []},
    )
    assert bad_resp2.status_code == 400
    assert bad_resp2.get_json()["success"] is False
