from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from src.schemas.base import MetaInfo, RunMode, ToolEnvelope
from src.schemas.pmb import OrderPlaceRequest, OrderState
from src.tools.market_clock import MarketClock


_ORDER_STORE: Dict[str, Dict] = {}
_PORTFOLIO_STORE: Dict[str, Dict] = {}
_LAST_PRICE: Dict[str, float] = {}
_DEFAULT_STARTING_CASH = 100000.0


def _asof(clock: Optional[MarketClock]) -> datetime:
    return clock.now() if clock else datetime.now(timezone.utc)


def _ensure_portfolio(portfolio_id: str) -> Dict:
    if portfolio_id not in _PORTFOLIO_STORE:
        _PORTFOLIO_STORE[portfolio_id] = {
            "portfolio_id": portfolio_id,
            "cash": _DEFAULT_STARTING_CASH,
            "positions": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    return _PORTFOLIO_STORE[portfolio_id]


def _mark_price(symbol: str) -> float:
    key = symbol.upper()
    px = _LAST_PRICE.get(key)
    if px is None:
        px = 100.0
        _LAST_PRICE[key] = px
    return px


def _apply_fill(portfolio: Dict, order_payload: Dict) -> Dict:
    symbol = order_payload["symbol"].upper()
    action = order_payload["action"].value if hasattr(order_payload.get("action"), "value") else order_payload.get("action")
    qty = float(order_payload["quantity"])
    if qty <= 0:
        return {"ok": False, "reason": "Invalid quantity"}

    fill_price = float(order_payload.get("limit_price") or _mark_price(symbol))
    notional = fill_price * qty
    positions = portfolio["positions"]
    pos = positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})

    if action in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        if portfolio["cash"] < notional:
            return {"ok": False, "reason": "Insufficient cash"}
        new_qty = pos["quantity"] + qty
        new_avg = ((pos["quantity"] * pos["avg_price"]) + notional) / new_qty if new_qty > 0 else 0.0
        pos["quantity"] = new_qty
        pos["avg_price"] = new_avg
        positions[symbol] = pos
        portfolio["cash"] -= notional
    elif action in {"SELL", "SELL_TO_CLOSE", "SELL_TO_OPEN"}:
        if pos["quantity"] < qty:
            return {"ok": False, "reason": "Insufficient position"}
        pos["quantity"] -= qty
        if pos["quantity"] <= 0:
            positions.pop(symbol, None)
        else:
            positions[symbol] = pos
        portfolio["cash"] += notional
    else:
        return {"ok": False, "reason": f"Unsupported action: {action}"}

    _LAST_PRICE[symbol] = fill_price
    return {"ok": True, "fill_price": fill_price, "filled_qty": qty}


def pmb_order_place(
    req: OrderPlaceRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    asof = _asof(clock)
    portfolio = _ensure_portfolio(req.portfolio_id)
    results: List[Dict] = []
    warnings: List[str] = []

    for order in req.orders:
        payload = asdict(order)
        order_type = payload.get("order_type")
        order_type = order_type.value if hasattr(order_type, "value") else order_type
        order_id = f"ord_{req.portfolio_id}_{uuid.uuid4().hex[:12]}"
        item = {
            "order_id": order_id,
            "portfolio_id": req.portfolio_id,
            "status": OrderState.ACCEPTED.value,
            "payload": payload,
            "asof": asof.isoformat(),
        }

        if order_type in {"MARKET", "LIMIT"}:
            fill = _apply_fill(portfolio, payload)
            if fill["ok"]:
                item["status"] = OrderState.FILLED.value
                item["fill_price"] = fill["fill_price"]
                item["filled_qty"] = fill["filled_qty"]
            else:
                item["status"] = OrderState.REJECTED.value
                item["reject_reason"] = fill["reason"]
        else:
            warnings.append(f"Order {order_id} kept as ACCEPTED: only MARKET/LIMIT are fill-simulated.")

        _ORDER_STORE[order_id] = item
        results.append(item)

    return ToolEnvelope.ok(
        tool="PMB.order.place",
        asof=asof,
        data=results,
        mode=mode,
        meta=MetaInfo(source=["pmb.paper_broker"], warnings=warnings),
    )


def pmb_order_status(
    order_id: str,
    portfolio_id: str,
    asof: Optional[datetime] = None,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    now = asof or _asof(clock)
    rec = _ORDER_STORE.get(order_id)
    if not rec or rec.get("portfolio_id") != portfolio_id:
        return ToolEnvelope.error(
            tool="PMB.order.status",
            asof=now,
            code="ORDER_NOT_FOUND",
            message=f"order_id={order_id} not found for portfolio={portfolio_id}",
            mode=mode,
        )
    return ToolEnvelope.ok(
        tool="PMB.order.status",
        asof=now,
        data=rec,
        mode=mode,
        meta=MetaInfo(source=["pmb.paper_broker"]),
    )


def pmb_portfolio_snapshot(
    portfolio_id: str,
    asof: Optional[datetime] = None,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    now = asof or _asof(clock)
    portfolio = _ensure_portfolio(portfolio_id)
    orders = [v for v in _ORDER_STORE.values() if v.get("portfolio_id") == portfolio_id and v.get("status") == OrderState.ACCEPTED.value]
    positions = []
    equity = float(portfolio["cash"])
    for symbol, pos in portfolio["positions"].items():
        mark = _mark_price(symbol)
        mv = mark * float(pos["quantity"])
        upl = (mark - float(pos["avg_price"])) * float(pos["quantity"])
        equity += mv
        positions.append(
            {
                "symbol": symbol,
                "quantity": float(pos["quantity"]),
                "avg_price": float(pos["avg_price"]),
                "mark_price": mark,
                "market_value": mv,
                "unrealized_pnl": upl,
            }
        )

    return ToolEnvelope.ok(
        tool="PMB.portfolio.snapshot",
        asof=now,
        data={
            "portfolio_id": portfolio_id,
            "cash": float(portfolio["cash"]),
            "equity": float(equity),
            "open_orders": len(orders),
            "positions": positions,
        },
        mode=mode,
        meta=MetaInfo(source=["pmb.paper_broker"]),
    )
