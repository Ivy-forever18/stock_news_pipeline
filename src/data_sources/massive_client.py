"""Stable Massive (Polygon-like) REST client.

This module provides a single `MassiveClient` with a small, well-tested
surface area used by the rest of the pipeline. It prefers `requests` when
available and falls back to the standard library `urllib` when necessary.

Behavior notes:
- If no API key is configured (env `MASSIVE_API_KEY`) the client will operate
  in "dry-run" mode and immediately return `{"status": "dry-run", "data": []}`
  for GET calls so the rest of the code can be exercised without network.
- The `get` method implements a simple retry with exponential backoff when
  429/temporary failures occur.
"""
from __future__ import annotations

import os
import time
import json
import logging
from typing import Optional, Any, Dict

BASE_URL = "https://api.massive.com"
API_KEY = os.environ.get("MASSIVE_API_KEY")

logger = logging.getLogger(__name__)


class MassiveClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = BASE_URL, timeout: int = 10):
        self.api_key = api_key or API_KEY
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        hdr = {"Accept": "application/json", "User-Agent": "stock-news-pipeline/1.0"}
        if self.api_key:
            hdr["Authorization"] = f"Bearer {self.api_key}"
        return hdr

    @property
    def dry_run(self) -> bool:
        return not bool(self.api_key)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, retries: int = 3, backoff: float = 1.0) -> Any:
        """Perform GET request with retry/backoff and requests/urllib fallback.

        Returns parsed JSON on success, or raises on permanent failure.
        In dry-run mode returns {"status": "dry-run", "data": []}.
        """
        if params is None:
            params = {}

        # Dry-run: short-circuit so callers can test without network/key
        if self.dry_run:
            return {"status": "dry-run", "data": []}

        # Ensure path starts with '/'
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"

        # First try to use requests if available
        try:
            import requests  # type: ignore
        except Exception:
            requests = None

        for attempt in range(1, retries + 1):
            # If we have requests, use it
            if requests is not None:
                try:
                    r = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
                    if r.status_code == 429:
                        # rate limited: backoff and retry
                        logger.warning("requests rate limited (429) on %s", url)
                        time.sleep(backoff * attempt)
                        continue
                    try:
                        r.raise_for_status()
                    except Exception as e:
                        body = None
                        try:
                            body = r.text
                        except Exception:
                            body = None
                        logger.debug("requests HTTP error %s: %s", r.status_code, body)
                        raise RuntimeError(f"HTTP {r.status_code} error from {url}: {body}") from e
                    return r.json()
                except requests.HTTPError as e:
                    if attempt == retries:
                        body = None
                        try:
                            body = e.response.text
                        except Exception:
                            body = None
                        raise RuntimeError(f"HTTP error from {url}: {body}") from e
                    logger.warning("requests HTTPError (attempt %s/%s), retrying", attempt, retries)
                    time.sleep(backoff * attempt)
                    continue
                except requests.RequestException as e:
                    if attempt == retries:
                        raise
                    logger.warning("requests RequestException (attempt %s/%s): %s", attempt, retries, str(e))
                    time.sleep(backoff * attempt)
                    continue

            # Fallback to urllib
            import urllib.request as _ur
            import urllib.parse as _up
            import urllib.error as _ue

            clean_params = {k: v for k, v in (params or {}).items() if v is not None}
            query = _up.urlencode(clean_params, doseq=True) if clean_params else ""
            full_url = f"{url}?{query}" if query else url
            req = _ur.Request(full_url, headers=self._headers())
            try:
                with _ur.urlopen(req, timeout=self.timeout) as resp:
                    code = resp.getcode()
                    body = resp.read()
                    if code == 429:
                        logger.warning("urllib rate limited (429) on %s", full_url)
                        time.sleep(backoff * attempt)
                        continue
                    if code >= 400:
                        body_text = None
                        try:
                            body_text = body.decode("utf-8", errors="replace")
                        except Exception:
                            body_text = None
                        if attempt == retries:
                            raise RuntimeError(f"HTTP {code} error from {full_url}: {body_text}")
                        logger.warning("urllib HTTP %s on %s, retrying", code, full_url)
                        time.sleep(backoff * attempt)
                        continue
                    return json.loads(body.decode("utf-8"))
            except _ue.HTTPError as e:
                body_text = None
                try:
                    body_text = e.read().decode("utf-8", errors="replace")
                except Exception:
                    body_text = None
                if attempt == retries:
                    raise RuntimeError(f"HTTP {e.code} error from {full_url}: {body_text}") from e
                logger.warning("urllib HTTPError (attempt %s/%s) %s", attempt, retries, e)
                time.sleep(backoff * attempt)
                continue
            except Exception as e:
                if attempt == retries:
                    raise
                logger.warning("urllib transport error (attempt %s/%s): %s", attempt, retries, str(e))
                time.sleep(backoff * attempt)

        raise RuntimeError("Failed to GET after retries")

    def get_news(self, symbol: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None, page: int = 1, page_size: int = 100) -> Any:
        """Convenience wrapper for the Massive `/stocks/news` endpoint.

        Parameters follow Massive API naming: `symbol`, `start`, `end`.
        """
        # According to Massive docs the canonical news endpoint is `/v2/reference/news`
        # which accepts `ticker`, `limit` and published_utc range filters.
        params: Dict[str, Any] = {"limit": page_size}
        # Support simple pagination: include the requested page number so callers
        # that iterate pages (see `fetch_news_for_symbol`) actually request
        # the next page from the API.
        if page is not None:
            params["page"] = page
        if symbol:
            params["ticker"] = symbol
        # published_utc filter modifiers: use `.gte` and `.lte` if start/end provided
        if start:
            params["published_utc.gte"] = start
        if end:
            params["published_utc.lte"] = end

        return self.get("/v2/reference/news", params=params)


__all__ = ["MassiveClient"]
