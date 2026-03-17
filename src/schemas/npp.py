from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NewsQueryRequest:
    symbol: Optional[str] = None
    symbols: List[str] = field(default_factory=list)
    start: Optional[str] = None
    end: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    min_importance: float = 0.0
    limit: int = 50
    asof: Optional[str] = None


@dataclass
class EarningsQueryRequest:
    symbol: Optional[str] = None
    symbols: List[str] = field(default_factory=list)
    start: Optional[str] = None
    end: Optional[str] = None
    days_ahead: Optional[int] = None
    asof: Optional[str] = None


@dataclass
class MacroQueryRequest:
    countries: List[str] = field(default_factory=list)
    start: Optional[str] = None
    end: Optional[str] = None
    min_importance: float = 0.5
    asof: Optional[str] = None
