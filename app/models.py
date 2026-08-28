"""Pydantic models used across storage, API and the state machine."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Mode(str, Enum):
    ADD = "ADD"
    CONSUME = "CONSUME"
    DISCARD = "DISCARD"
    INVENTORY = "INVENTORY"
    LOOKUP = "LOOKUP"


class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    CONSUMED = "consumed"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class Product(BaseModel):
    ean: str
    name: str
    manufacturer: Optional[str] = None
    weight_g: Optional[float] = None
    category: Optional[str] = None
    default_shelf_life_months: Optional[int] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class StockItem(BaseModel):
    id: str
    ean: str
    best_before: date
    status: StockStatus = StockStatus.IN_STOCK
    location: Optional[str] = None
    added_at: datetime = Field(default_factory=_now)
    consumed_at: Optional[datetime] = None
    notes: Optional[str] = None


class PendingAdd(BaseModel):
    """In-progress ADD entry — accumulates fields as control barcodes are scanned."""

    ean: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    qty: int = 1
    started_at: datetime = Field(default_factory=_now)

    @property
    def has_ean(self) -> bool:
        return self.ean is not None

    @property
    def has_date(self) -> bool:
        return self.year is not None and self.month is not None

    @property
    def is_ready(self) -> bool:
        return self.has_ean and self.has_date


class InventorySession(BaseModel):
    id: str
    started_at: datetime = Field(default_factory=_now)
    finished_at: Optional[datetime] = None
    counts: Dict[str, int] = Field(default_factory=dict)
    unknown_scans: List[str] = Field(default_factory=list)
    report: Optional[Dict[str, Any]] = None
    opened_from_mode: Optional[str] = None


class AppState(BaseModel):
    """Persisted global state — the mode and any in-flight entries."""

    mode: Mode = Mode.CONSUME
    pending_add: PendingAdd = Field(default_factory=PendingAdd)
    active_inventory_id: Optional[str] = None
    updated_at: datetime = Field(default_factory=_now)


class NotificationSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Notification(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=_now)
    severity: NotificationSeverity = NotificationSeverity.INFO
    title: str
    body: str = ""
    link: Optional[str] = None
    dismissed_at: Optional[datetime] = None


class ScanKind(str, Enum):
    CONTROL = "control"
    PRODUCT = "product"
    UNKNOWN = "unknown"


class ScanResultStatus(str, Enum):
    OK = "ok"
    WAITING = "waiting"
    ERROR = "error"
    IGNORED = "ignored"


class ScanResult(BaseModel):
    """Response payload from POST /api/scan."""

    status: ScanResultStatus
    kind: ScanKind
    mode: Mode
    message: str
    pending: Optional[PendingAdd] = None
    detail: Optional[Dict[str, Any]] = None
    tone: Literal["accept", "reject", "attention", "silent"] = "accept"
