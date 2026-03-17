from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Dict, List, Optional

from src.config.settings import DATABASE_CONFIG
from src.schemas.base import MetaInfo, RunMode, ToolEnvelope
from src.schemas.npp import EarningsQueryRequest, MacroQueryRequest, NewsQueryRequest
from src.tools.market_clock import MarketClock


def _asof(clock: Optional[MarketClock]) -> datetime:
    return clock.now() if clock else datetime.now(timezone.utc)


def _parse_dt(v: Optional[str], default: Optional[datetime] = None) -> Optional[datetime]:
    if not v:
        return default
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return default


def _norm_iso(v: Optional[str], default: datetime) -> str:
    dt = _parse_dt(v, default=default)
    if dt is None:
        dt = default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _extract_importance(raw_data: Dict) -> float:
    for k in ("importance", "impact", "score"):
        val = raw_data.get(k)
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            s = val.strip().lower()
            if s in {"high", "h"}:
                return 3.0
            if s in {"medium", "med", "m"}:
                return 2.0
            if s in {"low", "l"}:
                return 1.0
            try:
                return float(s)
            except Exception:
                pass
    return 0.0


def _extract_country(event: Dict) -> Optional[str]:
    for k in ("country", "currency", "region"):
        val = event.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
    return None


def npp_news_query(
    req: NewsQueryRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    asof = _asof(clock)
    db_path = DATABASE_CONFIG.get("raw_news_db")
    if not db_path:
        return ToolEnvelope.error(
            tool="NPP.news.query",
            asof=asof,
            code="DB_NOT_CONFIGURED",
            message="raw_news_db is not configured",
            mode=mode,
        )

    start_iso = _norm_iso(req.start, default=asof - timedelta(days=30))
    end_iso = _norm_iso(req.end, default=asof)
    symbols = [s.upper() for s in req.symbols if s]
    if req.symbol:
        symbols.append(req.symbol.upper())
    symbols = sorted(set(symbols))

    where: List[str] = ["timestamp IS NOT NULL", "timestamp >= ?", "timestamp <= ?"]
    params: List = [start_iso, end_iso]

    if symbols:
        where.append("UPPER(company_symbol) IN ({})".format(",".join(["?"] * len(symbols))))
        params.extend(symbols)

    if req.keywords:
        kw_clause = []
        for kw in req.keywords:
            kw_clause.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)")
            like_val = f"%{kw.lower()}%"
            params.extend([like_val, like_val])
        where.append("(" + " OR ".join(kw_clause) + ")")

    sql = (
        "SELECT id, source, title, content, timestamp, company_symbol, url, raw_data "
        "FROM raw_news WHERE " + " AND ".join(where) + " ORDER BY timestamp DESC LIMIT ?"
    )
    params.append(max(req.limit * 3, req.limit, 50))

    items = []
    warnings: List[str] = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()

        for row in rows:
            try:
                raw_data = json.loads(row[7]) if row[7] else {}
            except Exception:
                raw_data = {}

            importance = _extract_importance(raw_data)
            if importance < req.min_importance:
                continue

            item = {
                "id": row[0],
                "source": row[1],
                "title": row[2],
                "content": row[3],
                "timestamp": row[4],
                "symbol": row[5],
                "url": row[6],
                "importance": importance,
                "raw_data": raw_data,
            }
            items.append(item)
            if len(items) >= req.limit:
                break
    except sqlite3.OperationalError as e:
        warnings.append(f"raw_news table is not ready: {e}")
    except Exception as e:
        return ToolEnvelope.error(
            tool="NPP.news.query",
            asof=asof,
            code="DB_QUERY_FAILED",
            message=str(e),
            retryable=True,
            mode=mode,
        )

    if not items:
        warnings.append("No matching news found in local raw_news database.")

    return ToolEnvelope.ok(
        tool="NPP.news.query",
        asof=asof,
        data={"items": items, "count": len(items), "request": asdict(req)},
        mode=mode,
        meta=MetaInfo(source=["sqlite.raw_news"], warnings=warnings),
    )


def npp_earnings_query(
    req: EarningsQueryRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    asof = _asof(clock)
    earnings_db = DATABASE_CONFIG.get("earnings_db")
    if not earnings_db:
        return ToolEnvelope.error(
            tool="NPP.calendar.earnings",
            asof=asof,
            code="DB_NOT_CONFIGURED",
            message="earnings_db is not configured",
            mode=mode,
        )

    base_date = _parse_dt(req.asof, default=asof) or asof
    start_dt = _parse_dt(req.start, default=base_date)
    if req.end:
        end_dt = _parse_dt(req.end, default=base_date)
    elif req.days_ahead is not None:
        end_dt = start_dt + timedelta(days=max(req.days_ahead, 0))
    else:
        end_dt = start_dt + timedelta(days=7)

    warnings: List[str] = []
    items: List[Dict] = []
    try:
        conn = sqlite3.connect(earnings_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, symbol, company, report_date, time_of_day, raw_json "
            "FROM earnings WHERE report_date >= ? AND report_date <= ? ORDER BY report_date ASC",
            (start_dt.date().isoformat(), end_dt.date().isoformat()),
        )
        db_rows = cur.fetchall()
        conn.close()

        symbols = [s.upper() for s in req.symbols if s]
        if req.symbol:
            symbols.append(req.symbol.upper())
        symbols = sorted(set(symbols))

        for row in db_rows:
            sym = (row[1] or "").upper()
            if symbols and sym not in symbols:
                continue
            try:
                raw = json.loads(row[5]) if row[5] else {}
            except Exception:
                raw = {}
            items.append(
                {
                    "id": row[0],
                    "symbol": row[1],
                    "company": row[2],
                    "report_date": row[3],
                    "time_of_day": row[4],
                    "raw": raw,
                }
            )
    except sqlite3.OperationalError as e:
        warnings.append(f"earnings table is not ready: {e}")
    except Exception as e:
        return ToolEnvelope.error(
            tool="NPP.calendar.earnings",
            asof=asof,
            code="EARNINGS_QUERY_FAILED",
            message=str(e),
            retryable=True,
            mode=mode,
        )

    if not items:
        warnings.append("No matching earnings found in local earnings database cache.")

    return ToolEnvelope.ok(
        tool="NPP.calendar.earnings",
        asof=asof,
        data={"items": items, "count": len(items), "request": asdict(req)},
        mode=mode,
        meta=MetaInfo(source=["sqlite.earnings_db"], warnings=warnings),
    )


def npp_macro_query(
    req: MacroQueryRequest,
    clock: Optional[MarketClock] = None,
    mode: RunMode = RunMode.BACKTEST,
) -> ToolEnvelope:
    asof = _asof(clock)
    db_path = DATABASE_CONFIG.get("trading_day_db")
    if not db_path:
        return ToolEnvelope.error(
            tool="NPP.calendar.macro",
            asof=asof,
            code="DB_NOT_CONFIGURED",
            message="trading_day_db is not configured",
            mode=mode,
        )

    start_dt = _parse_dt(req.start, default=asof - timedelta(days=30))
    end_dt = _parse_dt(req.end, default=asof)
    start_s = start_dt.date().isoformat()
    end_s = end_dt.date().isoformat()
    countries = {c.upper() for c in req.countries if c}

    sql = (
        "SELECT trading_date, global_events FROM trading_days "
        "WHERE trading_date >= ? AND trading_date <= ? ORDER BY trading_date ASC"
    )

    items: List[Dict] = []
    warnings: List[str] = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql, (start_s, end_s))
        rows = cur.fetchall()
        conn.close()

        for trading_date, global_events in rows:
            try:
                events = json.loads(global_events) if global_events else []
            except Exception:
                events = []
            for ev in events:
                importance = _extract_importance(ev)
                if importance < req.min_importance:
                    continue
                country = _extract_country(ev)
                if countries and (country is None or country not in countries):
                    continue
                items.append(
                    {
                        "id": ev.get("id") or ev.get("event_id"),
                        "trading_date": trading_date,
                        "timestamp": ev.get("timestamp_utc") or ev.get("date"),
                        "event_name": ev.get("event_name") or ev.get("title"),
                        "country": country,
                        "importance": importance,
                        "source": ev.get("source"),
                        "raw": ev,
                    }
                )
    except sqlite3.OperationalError as e:
        warnings.append(f"trading_days table is not ready: {e}")
    except Exception as e:
        return ToolEnvelope.error(
            tool="NPP.calendar.macro",
            asof=asof,
            code="DB_QUERY_FAILED",
            message=str(e),
            retryable=True,
            mode=mode,
        )

    if not items:
        warnings.append("No macro events found in local trading_day bundles for the requested range.")

    return ToolEnvelope.ok(
        tool="NPP.calendar.macro",
        asof=asof,
        data={"items": items, "count": len(items), "request": asdict(req)},
        mode=mode,
        meta=MetaInfo(source=["sqlite.trading_day_db"], warnings=warnings),
    )
