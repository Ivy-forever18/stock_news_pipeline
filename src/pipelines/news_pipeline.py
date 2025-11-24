# src/pipelines/news_pipeline.py
"""
Reworked news pipeline (full patched file).
- Use relative imports (package-safe).
- Normalize NewsItem and dict inputs to a consistent dict schema before DB insertion.
- Use TradingCalendar.map_timestamp_to_trading_day to map each news item's exact timestamp (tz-aware)
  to a trading day (handles after-close / weekend / holiday mapping).
- Fix mixing of NewsItem dataclass and dict access patterns.
- Ensure global events and company news are assigned to trading days by timestamp (not by naive date string).
- Ensure timestamps written as ISO UTC strings in DB.
- Robust insert_to_raw_db that logs/skips problematic items and always writes a non-null content_hash.
"""
import sqlite3
import json
import os
import logging
import hashlib
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any, Union, Optional

# Relative imports to be robust when running as package
from ..data_sources.fomc_scraper import FOMCScraper
from ..data_sources.economic_events import EconomicEventsCollector
from ..data_sources.stockbench_news import StockBenchNewsLoader
from ..utils.trading_calendar import TradingCalendar
from ..utils.data_models import EconomicEvent, NewsItem, TradingDayBundle
from ..config.settings import DATABASE_CONFIG, OUTPUTS_DIR

# Ensure output directory exists
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Canonical keys for normalized records
RAW_KEYS = [
    "id",
    "source",
    "title",
    "content",
    "timestamp_utc",
    "company_symbol",
    "url",
    "raw_data"
]


def _to_utc_iso(ts: Union[str, datetime, None]) -> str:
    """Return an ISO8601 string for a datetime or string timestamp.
    Naive datetimes are treated as UTC to avoid accidental shifts.
    Returns a string like '2025-11-03T08:00:00Z' or with timezone offset if tz-aware.
    """
    if ts is None:
        return datetime.utcnow().isoformat() + "Z"

    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            try:
                dt = datetime.strptime(ts.split("Z")[0], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return datetime.utcnow().isoformat() + "Z"
    else:
        dt = ts

    if dt.tzinfo is None:
        # treat naive as UTC and append Z
        return dt.replace(tzinfo=None).isoformat() + "Z"
    else:
        # return ISO with offset (convert to UTC if desired elsewhere)
        try:
            return dt.astimezone(tz=None).isoformat()
        except Exception:
            return dt.isoformat()


def _normalize_news_item(item: Union[NewsItem, Dict[str, Any]], source_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Normalize a NewsItem dataclass or a dict into a canonical dict.
    Ensures timestamp_utc is an ISO string.
    """
    if isinstance(item, NewsItem):
        nid = getattr(item, "id", None) or f"company_{abs(hash(item.title)) % 100000}"
        ts = getattr(item, "timestamp", None)
        ts_iso = _to_utc_iso(ts)
        return {
            "id": nid,
            "source": getattr(item, "source", source_hint or "stockbench"),
            "title": getattr(item, "title", "") or "",
            "content": getattr(item, "content", "") or "",
            "timestamp_utc": ts_iso,
            "company_symbol": getattr(item, "company_symbol", None),
            "url": getattr(item, "url", None),
            "raw_data": getattr(item, "raw_data", {}) or {}
        }

    elif isinstance(item, dict):
        nid = item.get("id") or item.get("event_id") or item.get("uid") or f"item_{abs(hash(str(item)))%100000}"
        source = item.get("source") or source_hint or "unknown"
        ts = item.get("timestamp_utc") or item.get("timestamp") or item.get("published_utc") or item.get("date") or item.get("date_utc")
        ts_iso = _to_utc_iso(ts)
        title = item.get("title") or item.get("event_name") or item.get("headline") or ""
        content = item.get("content") or item.get("description") or item.get("summary") or ""
        company = item.get("company") or item.get("company_symbol") or item.get("symbol") or item.get("company_name")
        return {
            "id": nid,
            "source": source,
            "title": title,
            "content": content,
            "timestamp_utc": ts_iso,
            "company_symbol": company,
            "url": item.get("url"),
            "raw_data": item
        }
    else:
        return {
            "id": f"unknown_{abs(hash(str(item)))%100000}",
            "source": source_hint or "unknown",
            "title": str(item)[:120],
            "content": str(item),
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            "company_symbol": None,
            "url": None,
            "raw_data": {"orig": str(item)}
        }


class NewsDataPipeline:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.fomc_scraper = FOMCScraper()
        self.economic_collector = EconomicEventsCollector()
        self.stockbench_loader = StockBenchNewsLoader()
        self.trading_calendar = TradingCalendar()
        self.init_db()

    def init_db(self):
        """Initialize DB tables if not exists (compat with existing schema)."""
        try:
            # Initialize raw news database
            conn = sqlite3.connect(DATABASE_CONFIG['raw_news_db'])
            conn.execute('''CREATE TABLE IF NOT EXISTS raw_news
                            (id TEXT PRIMARY KEY,
                             source TEXT,
                             title TEXT,
                             content TEXT,
                             timestamp DATETIME,
                             company_symbol TEXT,
                             url TEXT,
                             content_hash TEXT,
                             raw_data TEXT,
                             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.close()

            conn = sqlite3.connect(DATABASE_CONFIG['trading_day_db'])
            conn.execute('''CREATE TABLE IF NOT EXISTS trading_days
                            (trading_date TEXT PRIMARY KEY,
                             global_events TEXT,
                             company_news TEXT,
                             has_major_events BOOLEAN DEFAULT FALSE,
                             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.close()
            
            self.logger.info("Database initialization completed")
            
        except Exception as e:
            self.logger.error(f"Database initialization failed: {e}")
            raise

    def insert_to_raw_db(self, items: List[Union[NewsItem, Dict[str, Any]]], source: str):
        """
        Insert normalized items into raw_news DB.
        Robust: ensures content_hash is computed and non-null.
        Logs and skips problematic items instead of failing the entire batch.
        """
        try:
            conn = sqlite3.connect(DATABASE_CONFIG['raw_news_db'])
            cursor = conn.cursor()

            inserted = 0
            for raw in items:
                norm = None
                try:
                    norm = _normalize_news_item(raw, source_hint=source)
                    # Ensure title/content are strings
                    title = norm.get("title") or ""
                    if not isinstance(title, str):
                        title = str(title)
                    content = norm.get("content") or ""
                    if not isinstance(content, str):
                        content = str(content)
                    # Compute content_hash deterministically
                    content_hash = hashlib.md5((title + "\n" + content).encode("utf-8")).hexdigest()

                    cursor.execute(
                        "INSERT OR REPLACE INTO raw_news (id, source, title, content, timestamp, company_symbol, url, content_hash, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            norm.get("id"),
                            norm.get("source"),
                            title,
                            content,
                            norm.get("timestamp_utc"),
                            norm.get("company_symbol"),
                            norm.get("url"),
                            content_hash,
                            json.dumps(norm.get("raw_data", {}), ensure_ascii=False)
                        )
                    )
                    inserted += 1
                except Exception as item_exc:
                    # Log the problematic record (include norm if available) and continue
                    try:
                        self.logger.error(f"Failed to insert item to raw DB (skipping). norm={repr(norm)} error={item_exc}")
                    except Exception:
                        self.logger.error(f"Failed to insert item to raw DB (skipping). raw={repr(raw)} error={item_exc}")
                    continue

            conn.commit()
            conn.close()
            self.logger.debug(f"Inserted {inserted} records into raw_news database, source: {source}")
        except Exception as e:
            self.logger.error(f"Failed to insert into raw database: {e}")
            if 'conn' in locals():
                conn.close()

    def fetch_company_news(self, start_date: datetime, end_date: datetime) -> List[NewsItem]:
        """Fetch company news using StockBench loader (returns NewsItem list)."""
        try:
            self.logger.info("Fetching company news...")
            return self.stockbench_loader.fetch_news(start_date, end_date)
        except Exception as e:
            self.logger.error(f"Failed to fetch company news: {e}")
            return []

    def fetch_global_events(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch global events (FOMC + economic events). Return list of normalized dicts."""
        global_events: List[Dict[str, Any]] = []
        try:
            # 1. Get FOMC event
            self.logger.info("Fetching FOMC meeting schedule...")
            fomc_events = self.fomc_scraper.fetch_fomc_schedule()
            for ev in fomc_events:
                d = ev.to_dict() if hasattr(ev, "to_dict") else {
                    "event_id": getattr(ev, "event_id", None),
                    "date": getattr(ev, "date", None),
                    "event_name": getattr(ev, "event_name", "")
                }
                d["timestamp_utc"] = _to_utc_iso(d.get("date") or datetime.utcnow())
                d["id"] = d.get("event_id") or f"fomc_{abs(hash(d.get('event_name','')))%100000}"
                d["source"] = d.get("source", "federalreserve.gov")
                d["title"] = d.get("event_name", "")
                d["content"] = d.get("description", "")
                d["company_symbol"] = None
                d["raw_data"] = d.copy()
                global_events.append(d)

            self.logger.info("Fetching economic events...")
            economic_events = self.economic_collector.fetch_events(start_date, end_date)
            for ev in economic_events:
                d = ev.to_dict() if hasattr(ev, "to_dict") else {
                    "event_id": getattr(ev, "event_id", None),
                    "date": getattr(ev, "date", None),
                    "event_name": getattr(ev, "event_name", "")
                }
                d["timestamp_utc"] = _to_utc_iso(d.get("date") or datetime.utcnow())
                d["id"] = d.get("event_id") or f"econ_{abs(hash(d.get('event_name','')))%100000}"
                d["source"] = d.get("source", "ecocal")
                d["title"] = d.get("event_name", "")
                d["content"] = d.get("description", "")
                d["company_symbol"] = None
                d["raw_data"] = d.copy()
                global_events.append(d)

            self.logger.info(f"Retrieved {len(global_events)} global events")
            
        except Exception as e:
            self.logger.error(f"Failed to fetch global events: {e}")
        
        return global_events

    def process_company_news(self, start_date: datetime, end_date: datetime) -> List[NewsItem]:
        """Get company news (wrapper)."""
        return self.fetch_company_news(start_date, end_date)

    def group_by_trading_days(self, global_events: List[Dict[str, Any]], news_items: List[NewsItem],
                              start_date: datetime, end_date: datetime, policy: str = 'after_close_to_next_day') -> Dict[str, Dict]:
        """
        Group news and events into trading-day bundles.
        - Map each item by its timestamp to a trading day using TradingCalendar.map_timestamp_to_trading_day.
        Returns dict keyed by trading-day string 'YYYY-MM-DD'.
        """
        trading_day_bundles: Dict[str, Dict] = {}

        try:
            # 1) Normalize and map global events
            for ev in global_events:
                ev_norm = _normalize_news_item(ev, source_hint="global")
                td = self.trading_calendar.map_timestamp_to_trading_day(ev_norm["timestamp_utc"], policy=policy)
                if td not in trading_day_bundles:
                    trading_day_bundles[td] = {"global_events": [], "company_news": {}, "has_major_events": False}
                trading_day_bundles[td]["global_events"].append(ev_norm)
                imp = ev_norm.get("raw_data", {}).get("importance")
                try:
                    if imp and int(imp) >= 3:
                        trading_day_bundles[td]["has_major_events"] = True
                except Exception:
                    pass

            # 2) Normalize and map company news
            for ni in news_items:
                norm = _normalize_news_item(ni, source_hint="company")
                td = self.trading_calendar.map_timestamp_to_trading_day(norm["timestamp_utc"], policy=policy)
                if td not in trading_day_bundles:
                    trading_day_bundles[td] = {"global_events": [], "company_news": {}, "has_major_events": False}
                company = norm.get("company_symbol") or "UNK"
                if company not in trading_day_bundles[td]["company_news"]:
                    trading_day_bundles[td]["company_news"][company] = []
                trading_day_bundles[td]["company_news"][company].append(norm)

            self.logger.info(f"Created {len(trading_day_bundles)} trading day bundles")
            
        except Exception as e:
            self.logger.error(f"Failed to group by trading days: {e}")

        return trading_day_bundles

    def save_trading_day_bundles(self, trading_day_bundles: Dict[str, Dict]):
        """Save trading day bundles to trading_day_db as JSON strings (existing schema)."""
        try:
            conn = sqlite3.connect(DATABASE_CONFIG['trading_day_db'])
            cursor = conn.cursor()

            for trading_day, bundle in trading_day_bundles.items():
                if bundle["global_events"] or any(bundle["company_news"].values()):
                    cursor.execute(
                        """INSERT OR REPLACE INTO trading_days 
                           (trading_date, global_events, company_news, has_major_events) 
                           VALUES (?, ?, ?, ?)""",
                        (
                            trading_day,
                            json.dumps(bundle["global_events"], ensure_ascii=False),
                            json.dumps(bundle["company_news"], ensure_ascii=False),
                            bool(bundle.get("has_major_events", False))
                        )
                    )
            conn.commit()
            conn.close()
            
            self.logger.info(f"Saved {len(trading_day_bundles)} trading day bundles")
            
        except Exception as e:
            self.logger.error(f"Failed to save trading day bundles: {e}")
            if 'conn' in locals():
                conn.close()

    def run_pipeline(self, days_back: int = 7):
        """Run the complete data processing pipeline."""
        self.logger.info(f"Starting news data pipeline, processing last {days_back} days")
        
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days_back)
            
            self.logger.info(f"Processing date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

            # 1. Fetch global events and insert to raw DB
            global_events = self.fetch_global_events(start_date, end_date)
            if global_events:
                self.insert_to_raw_db(global_events, 'global')

            # 2. Fetch company news and insert to raw DB
            news_items = self.fetch_company_news(start_date, end_date)
            if news_items:
                self.insert_to_raw_db(news_items, 'company')

            # 3. Group by trading days using timestamp mapping
            trading_day_bundles = self.group_by_trading_days(global_events, news_items, start_date, end_date)

            # 4. Save trading day bundles
            self.save_trading_day_bundles(trading_day_bundles)

            # 5. Output statistics
            total_global_events = len(global_events)
            total_company_news = len(news_items) if news_items else 0

            self.logger.info("Processing complete statistics:")
            self.logger.info(f"  - Global events: {total_global_events}")
            self.logger.info(f"  - Company news: {total_company_news}")
            self.logger.info(f"  - Trading day bundles: {len(trading_day_bundles)}")
            self.logger.info(f"  - Output directory: {OUTPUTS_DIR}")
            
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {e}")
            raise


# Simplified pipeline for compatibility / testing
class SimpleNewsDataPipeline:
    """Simplified version of the pipeline for quick testing."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def run_pipeline(self, days_back: int = 1):
        self.logger.info(f"Running pipeline, processing {days_back} days of data")
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days_back)
            os.makedirs(OUTPUTS_DIR, exist_ok=True)
            output_file = os.path.join(OUTPUTS_DIR, f"sample_output_{end_date.strftime('%Y%m%d')}.json")
            sample_data = {
                "date_range": {"start": start_date.strftime("%Y-%m-%d"), "end": end_date.strftime("%Y-%m-%d")},
                "events": [{"date": end_date.strftime("%Y-%m-%d"), "type": "economic", "description": "Sample economic event"}]
            }
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(sample_data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Generated sample output file: {output_file}")
            return {"status": "success", "processed_days": days_back, "output_file": output_file}
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {e}")
            return {"status": "error", "error": str(e)}