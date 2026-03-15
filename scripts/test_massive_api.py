"""Simple script to test Massive API connectivity via the project's MassiveClient.

Usage:
  # dry-run (no key set):
  python3 scripts/test_massive_api.py

  # with real key:
  MASSIVE_API_KEY=your_key_here python3 scripts/test_massive_api.py

The script prints basic diagnostics and the top-level response (truncated).
"""

from __future__ import annotations

import os
import json
import sys
import logging

# Ensure the repo package path is available when executed from project root
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

try:
    from src.data_sources.massive_client import MassiveClient
except Exception:
    # fallback if running from different cwd
    import importlib.util, os as _os
    client_path = _os.path.join(_os.path.dirname(__file__), "..", "src", "data_sources", "massive_client.py")
    client_path = _os.path.normpath(client_path)
    spec = importlib.util.spec_from_file_location("massive_client", client_path)
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    MassiveClient = mc.MassiveClient


def run_test(symbol: str = "AAPL") -> int:
    key = os.environ.get("MASSIVE_API_KEY")
    print("MASSIVE_API_KEY set:", bool(key))

    client = MassiveClient()
    print("Client dry_run:", client.dry_run)

    try:
        print("Requesting news for symbol:", symbol)
        # small page_size so response stays small
        res = client.get_news(symbol=symbol, page=1, page_size=1)
        print("Response type:", type(res))

        try:
            s = json.dumps(res, indent=2, ensure_ascii=False)
            # truncate long output
            print(s[:2000])
        except Exception:
            print(str(res)[:2000])

        # Helpful summary
        if isinstance(res, dict):
            data = res.get("data") or res.get("results")
            if data is None:
                print("No `data`/`results` in response; full keys:", list(res.keys()))
            else:
                print("Items returned:", len(data))

        return 0
    except Exception as e:
        print("Error calling Massive API:", repr(e))
        return 2


if __name__ == "__main__":
    sys.exit(run_test())
