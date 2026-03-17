from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class BarFreq(str, Enum):
    DAY1 = "1d"
    MIN1 = "1m"
    MIN5 = "5m"
    MIN15 = "15m"
    HOUR1 = "1h"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class MoneynessBound:
    pct_otm_min: Optional[float] = None
    pct_otm_max: Optional[float] = None
    reference_price: Optional[float] = None


@dataclass
class StockBarsRequest:
    symbol: str
    start: str
    end: str
    adjusted: bool = True
    freq: BarFreq = BarFreq.DAY1
    asof: Optional[datetime] = None


@dataclass
class OptionChainRequest:
    underlying: str
    expiration_gte: Optional[str] = None
    expiration_lte: Optional[str] = None
    option_type: Optional[OptionType] = None
    min_open_interest: int = 100
    min_volume: int = 10
    max_spread_pct: Optional[float] = None
    limit: int = 200
    moneyness: Optional[MoneynessBound] = None
    asof: Optional[datetime] = None
