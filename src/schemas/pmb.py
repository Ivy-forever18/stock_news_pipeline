from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    BUY_TO_OPEN = "BUY_TO_OPEN"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"
    SELL_TO_OPEN = "SELL_TO_OPEN"
    BUY_TO_CLOSE = "BUY_TO_CLOSE"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderState(str, Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass
class SingleOrderRequest:
    asset_id: str
    symbol: str
    asset_type: str
    action: OrderAction
    order_type: OrderType
    quantity: float
    tif: str = "DAY"
    client_order_id: Optional[str] = None
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None


@dataclass
class OrderPlaceRequest:
    portfolio_id: str
    orders: List[SingleOrderRequest]
    asof: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
