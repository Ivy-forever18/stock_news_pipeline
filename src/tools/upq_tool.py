from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from src.data_sources.massive_client import MassiveClient
from src.schemas.base import MetaInfo, RunMode, ToolEnvelope
from src.schemas.upq import BarFreq, OptionChainRequest, StockBarsRequest
from src.tools.market_clock import MarketClock


def _asof(clock: Optional[MarketClock]) -> datetime:
    return clock.now() if clock else datetime.now(timezone.utc)


def _parse_iso(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _freq_to_massive(freq: BarFreq) -> Tuple[int, str]:
    if freq == BarFreq.DAY1:
        return 1, "day"
    if freq == BarFreq.MIN1:
        return 1, "minute"
    if freq == BarFreq.MIN5:
        return 5, "minute"
    if freq == BarFreq.MIN15:
        return 15, "minute"
    if freq == BarFreq.HOUR1:
        return 1, "hour"
    return 1, "day"


def _gen_synthetic_bars(req: StockBarsRequest) -> List[Dict]:
    start = _parse_iso(req.start)
    end = _parse_iso(req.end)
    step = timedelta(days=1)
    if req.freq == BarFreq.MIN1:
        step = timedelta(minutes=1)
    elif req.freq == BarFreq.MIN5:
        step = timedelta(minutes=5)
    elif req.freq == BarFreq.MIN15:
        step = timedelta(minutes=15)
    elif req.freq == BarFreq.HOUR1:
        step = timedelta(hours=1)

    ts = start
    px = 100.0
    out: List[Dict] = []
    i = 0
    while ts <= end and i < 500:
        drift = ((i % 7) - 3) * 0.15
        o = px
        c = px + drift
        h = max(o, c) + 0.1
        l = min(o, c) - 0.1
        v = 10000 + (i % 12) * 250
        out.append(
            {
                "timestamp": ts.isoformat(),
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": v,
                "vwap": round((o + c) / 2.0, 4),
                "trades": 0,
            }
        )
        px = c
        ts += step
        i += 1
    return out


def _query_stock_bars(req: StockBarsRequest) -> Tuple[List[Dict], List[str], List[str]]:
    client = MassiveClient()
    warnings: List[str] = []
    sources: List[str] = []
    mult, span = _freq_to_massive(req.freq)
    path = f"/v2/aggs/ticker/{req.symbol.upper()}/range/{mult}/{span}/{req.start}/{req.end}"
    params = {"adjusted": str(bool(req.adjusted)).lower(), "sort": "asc", "limit": 5000}

    try:
        resp = client.get(path, params=params)
        rows = resp.get("results", []) if isinstance(resp, dict) else []
        bars = []
        for row in rows:
            ts_ms = row.get("t")
            if ts_ms is None:
                continue
            bars.append(
                {
                    "timestamp": datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat(),
                    "open": row.get("o"),
                    "high": row.get("h"),
                    "low": row.get("l"),
                    "close": row.get("c"),
                    "volume": row.get("v"),
                    "vwap": row.get("vw"),
                    "trades": row.get("n"),
                }
            )
        if bars:
            sources.append("massive.aggs")
            return bars, sources, warnings
    except Exception as e:
        warnings.append(f"Massive bars query failed: {e}")

    warnings.append("Using synthetic bars fallback (offline mode or no market data available).")
    sources.append("synthetic.fallback")
    return _gen_synthetic_bars(req), sources, warnings


def upq_stock_daily(
    req: StockBarsRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    bars, sources, warnings = _query_stock_bars(req)
    return ToolEnvelope.ok(
        tool="UPQ.stock.daily",
        asof=_asof(clock),
        data={"bars": bars, "count": len(bars), "request": asdict(req)},
        mode=mode,
        meta=MetaInfo(source=sources, warnings=warnings),
    )


def upq_stock_intraday(
    req: StockBarsRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    bars, sources, warnings = _query_stock_bars(req)
    return ToolEnvelope.ok(
        tool="UPQ.stock.intraday",
        asof=_asof(clock),
        data={"bars": bars, "count": len(bars), "request": asdict(req)},
        mode=mode,
        meta=MetaInfo(source=sources, warnings=warnings),
    )


def upq_option_chain(
    req: OptionChainRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    client = MassiveClient()
    params = {
        "underlying_ticker": req.underlying.upper(),
        "limit": req.limit,
        "sort": "expiration_date",
    }
    if req.expiration_gte:
        params["expiration_date.gte"] = req.expiration_gte
    if req.expiration_lte:
        params["expiration_date.lte"] = req.expiration_lte
    if req.option_type:
        params["contract_type"] = req.option_type.value

    warnings: List[str] = []
    sources: List[str] = []
    contracts: List[Dict] = []
    try:
        resp = client.get("/v3/reference/options/contracts", params=params)
        rows = resp.get("results", []) if isinstance(resp, dict) else []
        for row in rows:
            oi = int(row.get("open_interest") or 0)
            vol = int(row.get("day", {}).get("volume") or row.get("volume") or 0)
            if oi < req.min_open_interest or vol < req.min_volume:
                continue
            bid = row.get("bid")
            ask = row.get("ask")
            mid = None
            spread_pct = None
            if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
                mid = (bid + ask) / 2.0
                if mid and mid > 0:
                    spread_pct = (ask - bid) / mid
            if req.max_spread_pct is not None and spread_pct is not None and spread_pct > req.max_spread_pct:
                continue

            contracts.append(
                {
                    "ticker": row.get("ticker"),
                    "underlying": row.get("underlying_ticker"),
                    "expiration": row.get("expiration_date"),
                    "strike": row.get("strike_price"),
                    "option_type": row.get("contract_type"),
                    "open_interest": oi,
                    "volume": vol,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "spread_pct": spread_pct,
                }
            )
            if len(contracts) >= req.limit:
                break
        sources.append("massive.options")
    except Exception as e:
        warnings.append(f"Massive option-chain query failed: {e}")

    return ToolEnvelope.ok(
        tool="UPQ.option.chain.query",
        asof=_asof(clock),
        data={"contracts": contracts, "count": len(contracts), "request": asdict(req)},
        mode=mode,
        meta=MetaInfo(source=sources or ["massive.options"], warnings=warnings),
    )
