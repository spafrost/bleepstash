"""Append-only audit log written as JSON Lines."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import get_settings

_audit_lock = asyncio.Lock()

_REVERSIBLE_EVENTS = {"stock_add", "stock_consume", "stock_discard"}


async def log(event: str, **fields: Any) -> None:
    """Append a single audit event.

    Kept intentionally simple — no rotation yet (v1 volume is low; add later
    once we know the growth rate).
    """
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    record.update(fields)
    path = get_settings().audit_path
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str)
    async with _audit_lock:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def tail_reversible() -> Optional[Dict[str, Any]]:
    """Return the most recent reversible stock event or ``None``.

    ``None`` is returned if the log is empty, if the most recent stock event
    was itself a ``stock_undo`` (single-step undo policy), or if no reversible
    event is present at all.
    """
    path = get_settings().audit_path
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        event = rec.get("event")
        if event == "stock_undo":
            return None
        if event in _REVERSIBLE_EVENTS:
            return rec
    return None
