"""Batch fetcher for Massive news (dry-run scaffold).

Usage:
  python scripts/fetch_massive_news.py --symbol AAPL --start 2025-01-01 --end 2025-06-30 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import sqlite3
import json
from typing import Optional

# Ensure repository root is on sys.path so `src` is importable when running scripts
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
  sys.path.insert(0, REPO_ROOT)

import importlib.util

# Import `src/data_sources/massive_news.py` by path to avoid importing other
# `src.data_sources` package-level modules that require optional deps.
module_path = os.path.join(REPO_ROOT, "src", "data_sources", "massive_news.py")
spec = importlib.util.spec_from_file_location("massive_news", module_path)
massive_news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(massive_news)
fetch_news_for_symbol = massive_news.fetch_news_for_symbol

from src.config.settings import DATABASE_CONFIG


RAW_DB = DATABASE_CONFIG.get("raw_news_db")

RAW_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_news (
  id TEXT PRIMARY KEY,
  source TEXT,
  title TEXT,
  content TEXT,
  timestamp TEXT,
  company_symbol TEXT,
  url TEXT,
  raw_data TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def ensure_raw_db(path: str):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  conn = sqlite3.connect(path)
  cur = conn.cursor()
  cur.executescript(RAW_SCHEMA)
  conn.commit()
  conn.close()


def insert_articles(path: str, articles: list[dict]):
  if not articles:
    return 0
  conn = sqlite3.connect(path)
  cur = conn.cursor()
  inserted = 0
  for a in articles:
    aid = a.get("id") or None
    source = a.get("raw", {}).get("source") or "massive"
    title = a.get("title")
    content = a.get("summary") or a.get("raw", {}).get("content") or None
    ts = a.get("published_at")
    sym = a.get("symbol")
    url = a.get("url")
    raw_json = json.dumps(a.get("raw", {}), ensure_ascii=False)
    try:
      cur.execute(
        "INSERT OR REPLACE INTO raw_news (id, source, title, content, timestamp, company_symbol, url, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, source, title, content, ts, sym, url, raw_json),
      )
      inserted += 1
    except Exception:
      # skip invalid rows
      continue
  conn.commit()
  conn.close()
  return inserted


def main(symbol: str, start: Optional[str], end: Optional[str], dry_run: bool = True):
  # Fetch articles (MassiveClient handles dry-run when API key missing)
  out = fetch_news_for_symbol(symbol, start=start, end=end)
  print(f"Found {len(out)} articles for {symbol} (dry-run={dry_run})")

  if dry_run:
    return

  # Ensure DB exists and insert
  ensure_raw_db(RAW_DB)
  n = insert_articles(RAW_DB, out)
  print(f"Inserted {n} articles into {RAW_DB}")


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--symbol", required=True)
  parser.add_argument("--start", required=False)
  parser.add_argument("--end", required=False)
  parser.add_argument("--dry-run", action="store_true")
  args = parser.parse_args()
  main(args.symbol, args.start, args.end, dry_run=args.dry_run)
