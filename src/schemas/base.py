from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class RunMode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"
    BACKTEST = "BACKTEST"


class ToolStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    OPTION = "option"


@dataclass
class MetaInfo:
    source: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def model_dump(self) -> Dict[str, Any]:
        return {"source": self.source, "warnings": self.warnings}


@dataclass
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False

    def model_dump(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass
class ToolEnvelope:
    tool: str
    status: ToolStatus
    asof: datetime
    data: Any = None
    mode: RunMode = RunMode.BACKTEST
    meta: Optional[MetaInfo] = None
    error: Optional[ErrorInfo] = None

    @classmethod
    def ok(
        cls,
        tool: str,
        asof: Optional[datetime] = None,
        data: Any = None,
        mode: RunMode = RunMode.BACKTEST,
        meta: Optional[MetaInfo] = None,
    ) -> "ToolEnvelope":
        return cls(
            tool=tool,
            status=ToolStatus.OK,
            asof=asof or datetime.now(timezone.utc),
            data=data,
            mode=mode,
            meta=meta,
            error=None,
        )

    @classmethod
    def error(
        cls,
        tool: str,
        asof: Optional[datetime] = None,
        code: str = "TOOL_ERROR",
        message: str = "Unknown tool error",
        retryable: bool = False,
        mode: RunMode = RunMode.BACKTEST,
        meta: Optional[MetaInfo] = None,
    ) -> "ToolEnvelope":
        return cls(
            tool=tool,
            status=ToolStatus.ERROR,
            asof=asof or datetime.now(timezone.utc),
            data=None,
            mode=mode,
            meta=meta,
            error=ErrorInfo(code=code, message=message, retryable=retryable),
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status.value,
            "asof": self.asof.isoformat(),
            "data": self.data,
            "mode": self.mode.value,
            "meta": self.meta.model_dump() if self.meta else None,
            "error": self.error.model_dump() if self.error else None,
        }
