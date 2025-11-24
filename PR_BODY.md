# PR: Add news API, NASDAQ earnings fetcher, batch runners, Massive client, and monitoring

## Summary

This PR adds backend support for news and earnings data ingestion and serving. It includes a Flask news API, a NASDAQ earnings fetcher and batch runner (with checkpointing/staged backfill and resume), a Massive/Polygon news client scaffold, and a lightweight monitor for fetch logs.

## What changed (high level)

- API
  - `src/api/news_api.py` — News API blueprint (`/api/health`, `/api/news/company`, `/api/news/overall`, calendar stubs)
  - `src/api/app.py` — Registers blueprint and supports dev run

- Data sources & loaders
  - `src/data_sources/nasdaq_earnings.py` — NASDAQ earnings fetch/parse/cache logic
  - `src/data_sources/massive_client.py` — Massive/Polygon API client scaffold (dry-run safe)
  - `src/data_sources/massive_news.py` — News normalization helpers
  - other data-source helpers (economic events, fomc scraper, stockbench_news)

- Batch scripts & monitoring
  - `scripts/fetch_nasdaq_earnings.py` — batch runner with `--staged`, `--dry-run`, `--resume`, checkpointing
  - `scripts/fetch_massive_news.py` — Massive news runner (dry-run safe)
  - `scripts/monitor_fetcher.py` — tails fetch log and writes alerts

## Safety & housekeeping

- A local backup of `earnings.db` was created before cleanup in the working tree; large DBs/backups and runtime files have been removed from git tracking and are now in `.gitignore`.

## How to run (dev)

Install dependencies (adjust per your environment):

```bash
python -m pip install -r requirements.txt
```

Start Flask locally:

```bash
export FLASK_APP=src/api/app.py
flask run -p 5002
```

Dry-run NASDAQ single-day fetch:

```bash
python scripts/fetch_nasdaq_earnings.py --start 2025-11-12 --end 2025-11-12 --dry-run
```

Staged backfill (dry-run first):

```bash
python scripts/fetch_nasdaq_earnings.py --staged --dry-run --checkpoint-file .fetch_nasdaq_checkpoint
# then real run
nohup python scripts/fetch_nasdaq_earnings.py --staged --checkpoint-file .fetch_nasdaq_checkpoint > data/outputs/fetch_nasdaq_earnings.log 2>&1 & echo $! > .fetch_nasdaq_pid
```

Massive news fetch (set API key):

```bash
export MASSIVE_API_KEY=your_key_here
python scripts/fetch_massive_news.py --symbols AAPL MSFT --start 2025-11-01 --end 2025-11-30 --dry-run
```

## Risks & recommendations

- Long backfills can hit rate limits — add robust retry/backoff.
- SQLite may be a bottleneck for concurrent or very large writes — consider Postgres for production.
- Add UPSERT/unique constraint on `(symbol, report_date, time_of_day)` and update write logic to `INSERT ... ON CONFLICT` to prevent duplicates.

## Files to review

- `src/api/news_api.py`
- `src/data_sources/nasdaq_earnings.py`
- `scripts/fetch_nasdaq_earnings.py`
- `src/data_sources/massive_client.py`
- `scripts/fetch_massive_news.py`

## Next steps (suggested follow-ups)

1. Implement UPSERT or unique DB constraint and update write paths accordingly.
2. Harden HTTP clients with exponential backoff and 429 handling.
3. Move large/backfill jobs to scheduled workers (Airflow/Prefect) and add alerting.
4. Add CI tests for dry-run behavior and DB invariants.

(End of PR body)
