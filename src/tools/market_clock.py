from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class MarketClock:
    """Simple clock abstraction for live/backtest consistency."""

    fixed_now: Optional[datetime] = None

    @classmethod
    def backtest(cls, asof: datetime) -> "MarketClock":
        if asof.tzinfo is None:
            asof = asof.replace(tzinfo=timezone.utc)
        return cls(fixed_now=asof)

    @classmethod
    def live(cls) -> "MarketClock":
        return cls(fixed_now=None)

    def now(self) -> datetime:
        return self.fixed_now or datetime.now(timezone.utc)
