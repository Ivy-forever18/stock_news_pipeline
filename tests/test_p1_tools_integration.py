from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import DATABASE_CONFIG
from src.schemas.npp import NewsQueryRequest
from src.schemas.pmb import OrderAction, OrderPlaceRequest, OrderType, SingleOrderRequest
from src.schemas.upq import OptionChainRequest, StockBarsRequest
from src.tools.npp_tool import npp_news_query
from src.tools.pmb_tool import pmb_order_place, pmb_portfolio_snapshot
from src.tools.upq_tool import upq_option_chain, upq_stock_daily


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_npp_news_query_reads_from_sqlite(tmp_path):
    raw_db = tmp_path / "raw_news.db"
    DATABASE_CONFIG["raw_news_db"] = str(raw_db)

    conn = sqlite3.connect(raw_db)
    conn.execute(
        """
        CREATE TABLE raw_news (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            content TEXT,
            timestamp DATETIME,
            company_symbol TEXT,
            url TEXT,
            raw_data TEXT
        )
        """
    )
    row = (
        "id-1",
        "unit",
        "Apple launches product",
        "AAPL event content",
        _utc_now_iso(),
        "AAPL",
        "https://example.com/aapl",
        json.dumps({"importance": 2}),
    )
    conn.execute(
        "INSERT INTO raw_news (id, source, title, content, timestamp, company_symbol, url, raw_data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    conn.commit()
    conn.close()

    now = datetime.now(timezone.utc)
    req = NewsQueryRequest(
        symbol="AAPL",
        start=(now - timedelta(days=1)).isoformat(),
        end=(now + timedelta(days=1)).isoformat(),
        min_importance=1.0,
        limit=5,
    )
    out = npp_news_query(req).model_dump()

    assert out["status"] == "ok"
    assert out["data"]["count"] == 1
    assert out["data"]["items"][0]["symbol"] == "AAPL"


def test_npp_news_query_missing_table_returns_warning(tmp_path):
    raw_db = tmp_path / "raw_news_empty.db"
    DATABASE_CONFIG["raw_news_db"] = str(raw_db)

    req = NewsQueryRequest(symbol="AAPL", limit=3)
    out = npp_news_query(req).model_dump()

    assert out["status"] == "ok"
    assert out["data"]["count"] == 0
    warnings = (out.get("meta") or {}).get("warnings") or []
    assert any("raw_news table is not ready" in w for w in warnings)


def test_upq_stock_daily_falls_back_to_synthetic(monkeypatch):
    from src.data_sources.massive_client import MassiveClient

    def _raise(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(MassiveClient, "get", _raise)

    req = StockBarsRequest(symbol="AAPL", start="2026-03-01", end="2026-03-05")
    out = upq_stock_daily(req).model_dump()

    assert out["status"] == "ok"
    assert out["data"]["count"] > 0
    assert "synthetic.fallback" in ((out.get("meta") or {}).get("source") or [])


def test_upq_option_chain_filters_contracts(monkeypatch):
    from src.data_sources.massive_client import MassiveClient

    def _fake_get(*_args, **_kwargs):
        return {
            "results": [
                {
                    "ticker": "O:AAPL260620C00100000",
                    "underlying_ticker": "AAPL",
                    "expiration_date": "2026-06-20",
                    "strike_price": 100,
                    "contract_type": "call",
                    "open_interest": 1000,
                    "day": {"volume": 500},
                    "bid": 2.0,
                    "ask": 2.2,
                },
                {
                    "ticker": "O:AAPL260620C00200000",
                    "underlying_ticker": "AAPL",
                    "expiration_date": "2026-06-20",
                    "strike_price": 200,
                    "contract_type": "call",
                    "open_interest": 1,
                    "day": {"volume": 1},
                    "bid": 1.0,
                    "ask": 5.0,
                },
            ]
        }

    monkeypatch.setattr(MassiveClient, "get", _fake_get)

    req = OptionChainRequest(underlying="AAPL", min_open_interest=100, min_volume=10, limit=10)
    out = upq_option_chain(req).model_dump()

    assert out["status"] == "ok"
    assert out["data"]["count"] == 1
    assert out["data"]["contracts"][0]["ticker"] == "O:AAPL260620C00100000"


def test_pmb_order_and_snapshot_updates_cash_positions():
    import src.tools.pmb_tool as pmb_mod

    pmb_mod._ORDER_STORE.clear()
    pmb_mod._PORTFOLIO_STORE.clear()
    pmb_mod._LAST_PRICE.clear()

    req = OrderPlaceRequest(
        portfolio_id="paper_test",
        orders=[
            SingleOrderRequest(
                asset_id="US.AAPL",
                symbol="AAPL",
                asset_type="stock",
                action=OrderAction.BUY,
                order_type=OrderType.MARKET,
                quantity=10,
            )
        ],
    )

    place_out = pmb_order_place(req).model_dump()
    snap_out = pmb_portfolio_snapshot("paper_test").model_dump()

    assert place_out["status"] == "ok"
    assert place_out["data"][0]["status"] == "FILLED"
    assert snap_out["status"] == "ok"
    assert snap_out["data"]["cash"] == 99000.0
    assert len(snap_out["data"]["positions"]) == 1


def test_pmb_sell_without_position_is_rejected():
    import src.tools.pmb_tool as pmb_mod

    pmb_mod._ORDER_STORE.clear()
    pmb_mod._PORTFOLIO_STORE.clear()
    pmb_mod._LAST_PRICE.clear()

    req = OrderPlaceRequest(
        portfolio_id="paper_reject",
        orders=[
            SingleOrderRequest(
                asset_id="US.AAPL",
                symbol="AAPL",
                asset_type="stock",
                action=OrderAction.SELL,
                order_type=OrderType.MARKET,
                quantity=1,
            )
        ],
    )

    out = pmb_order_place(req).model_dump()
    assert out["status"] == "ok"
    assert out["data"][0]["status"] == "REJECTED"
    assert out["data"][0]["reject_reason"] == "Insufficient position"


def test_pmb_buy_insufficient_cash_is_rejected():
    import src.tools.pmb_tool as pmb_mod

    pmb_mod._ORDER_STORE.clear()
    pmb_mod._PORTFOLIO_STORE.clear()
    pmb_mod._LAST_PRICE.clear()

    req = OrderPlaceRequest(
        portfolio_id="paper_cash_reject",
        orders=[
            SingleOrderRequest(
                asset_id="US.AAPL",
                symbol="AAPL",
                asset_type="stock",
                action=OrderAction.BUY,
                order_type=OrderType.LIMIT,
                quantity=2000,
                limit_price=100.0,
            )
        ],
    )

    out = pmb_order_place(req).model_dump()
    assert out["status"] == "ok"
    assert out["data"][0]["status"] == "REJECTED"
    assert out["data"][0]["reject_reason"] == "Insufficient cash"


def test_upq_option_chain_respects_max_spread(monkeypatch):
    from src.data_sources.massive_client import MassiveClient

    def _fake_get(*_args, **_kwargs):
        return {
            "results": [
                {
                    "ticker": "O:AAPL260620C00100000",
                    "underlying_ticker": "AAPL",
                    "expiration_date": "2026-06-20",
                    "strike_price": 100,
                    "contract_type": "call",
                    "open_interest": 1000,
                    "day": {"volume": 500},
                    "bid": 1.0,
                    "ask": 3.0,
                },
                {
                    "ticker": "O:AAPL260620C00110000",
                    "underlying_ticker": "AAPL",
                    "expiration_date": "2026-06-20",
                    "strike_price": 110,
                    "contract_type": "call",
                    "open_interest": 1000,
                    "day": {"volume": 500},
                    "bid": 1.9,
                    "ask": 2.1,
                },
            ]
        }

    monkeypatch.setattr(MassiveClient, "get", _fake_get)

    req = OptionChainRequest(
        underlying="AAPL",
        min_open_interest=100,
        min_volume=10,
        max_spread_pct=0.2,
        limit=10,
    )
    out = upq_option_chain(req).model_dump()

    assert out["status"] == "ok"
    assert out["data"]["count"] == 1
    assert out["data"]["contracts"][0]["ticker"] == "O:AAPL260620C00110000"
