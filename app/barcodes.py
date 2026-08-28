"""Control-barcode parser.

Control barcodes carry the reserved prefix ``^CTRL^`` and are distinguished from
retail EAN/UPC codes by that prefix alone. Grammar (spec §4):

    ^CTRL^MODE:{ADD|CONSUME|DISCARD|INVENTORY|LOOKUP}
    ^CTRL^YEAR:{2026..2035}
    ^CTRL^MONTH:{01..12}
    ^CTRL^ACTION:{CANCEL|CONFIRM|UNDO|FINISH}
    ^CTRL^ACTION:QTY:+{N}

DAY-level granularity was removed after user feedback: all stock is rotated a
year ahead of expiry, so month precision is sufficient and the extra scan step
didn't earn its keep. Best-before always resolves to end-of-month.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import Mode

CONTROL_PREFIX = "^CTRL^"

_YEAR_RE = re.compile(r"^YEAR:(\d{4})$")
_MONTH_RE = re.compile(r"^MONTH:(0[1-9]|1[0-2])$")
_QTY_RE = re.compile(r"^ACTION:QTY:\+(\d+)$")
_MODE_RE = re.compile(r"^MODE:([A-Z]+)$")
_ACTION_RE = re.compile(r"^ACTION:(CANCEL|CONFIRM|UNDO|FINISH)$")

# Retail EANs / UPCs — 8, 12, 13 or 14 digits.
_EAN_RE = re.compile(r"^\d{8}$|^\d{12,14}$")


@dataclass(frozen=True)
class BarcodeIntent:
    kind: str  # "mode" | "year" | "month" | "day" | "qty" | "action" | "product" | "unknown"
    value: object = None
    raw: str = ""


def is_control(code: str) -> bool:
    return code.startswith(CONTROL_PREFIX)


def parse(code: str) -> BarcodeIntent:
    """Classify a scanned code and return a typed intent."""
    code = (code or "").strip()

    if is_control(code):
        body = code[len(CONTROL_PREFIX):]

        m = _MODE_RE.match(body)
        if m:
            token = m.group(1)
            try:
                return BarcodeIntent(kind="mode", value=Mode(token), raw=code)
            except ValueError:
                return BarcodeIntent(kind="unknown", raw=code)

        m = _YEAR_RE.match(body)
        if m:
            return BarcodeIntent(kind="year", value=int(m.group(1)), raw=code)

        m = _MONTH_RE.match(body)
        if m:
            return BarcodeIntent(kind="month", value=int(m.group(1)), raw=code)

        m = _QTY_RE.match(body)
        if m:
            return BarcodeIntent(kind="qty", value=int(m.group(1)), raw=code)

        m = _ACTION_RE.match(body)
        if m:
            return BarcodeIntent(kind="action", value=m.group(1), raw=code)

        return BarcodeIntent(kind="unknown", raw=code)

    if _EAN_RE.match(code):
        return BarcodeIntent(kind="product", value=code, raw=code)

    return BarcodeIntent(kind="unknown", raw=code)
