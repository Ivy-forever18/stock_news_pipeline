from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from src.schemas.base import RunMode, ToolEnvelope
from src.tools.market_clock import MarketClock


@dataclass
class ToolDef:
    name: str
    description: str
    fn: Callable[..., ToolEnvelope]
    parameters: Dict[str, Any]


def _npp_news(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.npp import NewsQueryRequest
    from src.tools.npp_tool import npp_news_query

    req = NewsQueryRequest(**params)
    return npp_news_query(req, clock=clock, mode=mode)


def _npp_earnings(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.npp import EarningsQueryRequest
    from src.tools.npp_tool import npp_earnings_query

    req = EarningsQueryRequest(**params)
    return npp_earnings_query(req, clock=clock, mode=mode)


def _npp_macro(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.npp import MacroQueryRequest
    from src.tools.npp_tool import npp_macro_query

    req = MacroQueryRequest(**params)
    return npp_macro_query(req, clock=clock, mode=mode)


def _upq_daily(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.upq import StockBarsRequest
    from src.tools.upq_tool import upq_stock_daily

    req = StockBarsRequest(**params)
    return upq_stock_daily(req, clock=clock, mode=mode)


def _upq_intraday(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.upq import StockBarsRequest
    from src.tools.upq_tool import upq_stock_intraday

    req = StockBarsRequest(**params)
    return upq_stock_intraday(req, clock=clock, mode=mode)


def _upq_option_chain(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.upq import OptionChainRequest
    from src.tools.upq_tool import upq_option_chain

    req = OptionChainRequest(**params)
    return upq_option_chain(req, clock=clock, mode=mode)


def _pmb_order_place(params: dict, clock, mode) -> ToolEnvelope:
    from src.schemas.pmb import OrderAction, OrderPlaceRequest, OrderType, SingleOrderRequest
    from src.tools.pmb_tool import pmb_order_place

    if "orders" in params:
        orders = []
        for raw in params["orders"]:
            orders.append(
                SingleOrderRequest(
                    asset_id=raw["asset_id"],
                    symbol=raw["symbol"],
                    asset_type=raw.get("asset_type", "stock"),
                    action=OrderAction(raw["action"]),
                    order_type=OrderType(raw["order_type"]),
                    quantity=float(raw["quantity"]),
                    tif=raw.get("tif", "DAY"),
                    client_order_id=raw.get("client_order_id"),
                    limit_price=raw.get("limit_price"),
                    stop_price=raw.get("stop_price"),
                )
            )
        req = OrderPlaceRequest(portfolio_id=params["portfolio_id"], orders=orders)
    else:
        order = SingleOrderRequest(
            asset_id=params.get("asset_id", f"US.{params.get('symbol', '')}"),
            symbol=params.get("symbol", ""),
            asset_type=params.get("asset_type", "stock"),
            action=OrderAction(params.get("action", "BUY")),
            order_type=OrderType(params.get("order_type", "MARKET")),
            quantity=float(params.get("quantity", params.get("qty", 0))),
            tif=params.get("tif", "DAY"),
            limit_price=params.get("limit_price"),
            stop_price=params.get("stop_price"),
        )
        req = OrderPlaceRequest(portfolio_id=params.get("portfolio_id", "paper_default"), orders=[order])

    return pmb_order_place(req, clock=clock, mode=mode)


def _pmb_order_status(params: dict, clock, mode) -> ToolEnvelope:
    from src.tools.pmb_tool import pmb_order_status

    return pmb_order_status(
        order_id=params["order_id"],
        portfolio_id=params["portfolio_id"],
        asof=params.get("asof"),
        clock=clock,
        mode=mode,
    )


def _pmb_portfolio(params: dict, clock, mode) -> ToolEnvelope:
    from src.tools.pmb_tool import pmb_portfolio_snapshot

    return pmb_portfolio_snapshot(
        portfolio_id=params["portfolio_id"],
        asof=params.get("asof"),
        clock=clock,
        mode=mode,
    )


def _qlib_factor_generate(params: dict, clock, mode) -> ToolEnvelope:
    from src.tools.qlib_tool import qlib_factor_generate

    return qlib_factor_generate(params, clock=clock, mode=mode)


TOOL_REGISTRY: List[ToolDef] = [
    ToolDef(
        name="NPP.news.query",
        description="Query news articles by symbols, time range, and keywords.",
        fn=_npp_news,
        parameters={"type": "object", "properties": {"symbol": {"type": "string"}}},
    ),
    ToolDef(
        name="NPP.calendar.earnings",
        description="Query earnings announcements.",
        fn=_npp_earnings,
        parameters={"type": "object", "properties": {"symbol": {"type": "string"}}},
    ),
    ToolDef(
        name="NPP.calendar.macro",
        description="Query macro events.",
        fn=_npp_macro,
        parameters={"type": "object", "properties": {"countries": {"type": "array", "items": {"type": "string"}}}},
    ),
    ToolDef(
        name="UPQ.stock.daily",
        description="Fetch daily OHLCV bars.",
        fn=_upq_daily,
        parameters={"type": "object", "required": ["symbol", "start", "end"], "properties": {"symbol": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}},
    ),
    ToolDef(
        name="UPQ.stock.intraday",
        description="Fetch intraday bars.",
        fn=_upq_intraday,
        parameters={"type": "object", "required": ["symbol", "start", "end"], "properties": {"symbol": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}},
    ),
    ToolDef(
        name="UPQ.option.chain.query",
        description="Query option chain.",
        fn=_upq_option_chain,
        parameters={"type": "object", "required": ["underlying"], "properties": {"underlying": {"type": "string"}}},
    ),
    ToolDef(
        name="PMB.order.place",
        description="Place paper order(s).",
        fn=_pmb_order_place,
        parameters={"type": "object", "properties": {"portfolio_id": {"type": "string"}}},
    ),
    ToolDef(
        name="PMB.order.status",
        description="Get order status.",
        fn=_pmb_order_status,
        parameters={"type": "object", "required": ["order_id", "portfolio_id"], "properties": {"order_id": {"type": "string"}, "portfolio_id": {"type": "string"}}},
    ),
    ToolDef(
        name="PMB.portfolio.snapshot",
        description="Get account snapshot.",
        fn=_pmb_portfolio,
        parameters={"type": "object", "required": ["portfolio_id"], "properties": {"portfolio_id": {"type": "string"}}},
    ),
    ToolDef(
        name="QLIB.factor.generate",
        description="Generate a Qlib alpha factor expression from natural language.",
        fn=_qlib_factor_generate,
        parameters={
            "type": "object",
            "required": ["instruction"],
            "properties": {
                "instruction": {"type": "string"},
                "model": {"type": "string", "default": "deepseek-chat"},
                "max_try": {"type": "integer", "default": 3},
                "temperature": {"type": "number", "default": 1.0},
                "evaluate": {"type": "boolean", "default": False},
            },
        },
    ),
]

_REGISTRY_MAP: Dict[str, ToolDef] = {t.name: t for t in TOOL_REGISTRY}


def call_tool(
    tool_name: str,
    params: Dict[str, Any],
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    td = _REGISTRY_MAP.get(tool_name)
    if td is None:
        return ToolEnvelope.error(
            tool=tool_name,
            asof=datetime.now(timezone.utc),
            code="UNKNOWN_TOOL",
            message=f"Tool '{tool_name}' not registered",
            mode=mode,
        )
    return td.fn(params, clock, mode)


def get_openai_tools() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name.replace(".", "__"),
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOL_REGISTRY
    ]


def list_tools() -> List[str]:
    return [t.name for t in TOOL_REGISTRY]
