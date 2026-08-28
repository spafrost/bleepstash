"""Inventory-session helpers.

INVENTORY mode is a stocktake: the operator scans every unit currently in the
stash, one by one. Known EANs increment ``session.counts``; unknown EANs (no
catalogue entry) go into ``session.unknown_scans``.

FINISH closes the session, computes a difference report against current
``in_stock`` inventory, persists the report on the session, clears
``state.active_inventory_id`` and hands the mode back to whatever the operator
was in before starting the stocktake (typically CONSUME).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ulid import ULID

from . import audit, products, state, storage
from .models import InventorySession, Mode, StockItem, StockStatus


async def open_session(previous_mode: Mode) -> InventorySession:
    """Create and persist a fresh InventorySession."""
    session = InventorySession(
        id=f"inv_{ULID()}",
        opened_from_mode=previous_mode.value,
    )
    sessions = await storage.load_sessions()
    sessions[session.id] = session
    await storage.save_sessions(sessions)
    await audit.log("inventory_open", session_id=session.id, opened_from=previous_mode.value)
    return session


async def record_scan(session_id: str, ean: str) -> Tuple[InventorySession, bool]:
    """Add a scanned EAN to the session. Returns ``(session, known)``.

    Known = catalogue hit. Unknown EANs are collected verbatim; the operator
    can enrich them from the Catalogue view (M6) after finishing.
    """
    sessions = await storage.load_sessions()
    session = sessions.get(session_id)
    if session is None:
        raise LookupError(f"InventorySession {session_id!r} not found")
    product = await products.get_product(ean)
    if product is None:
        session.unknown_scans.append(ean)
        known = False
    else:
        session.counts[ean] = session.counts.get(ean, 0) + 1
        known = True
    sessions[session_id] = session
    await storage.save_sessions(sessions)
    await audit.log("inventory_scan", session_id=session_id, ean=ean, known=known)
    return session, known


async def finish_session(session_id: str) -> InventorySession:
    """Close the session, compute + persist the report."""
    sessions = await storage.load_sessions()
    session = sessions.get(session_id)
    if session is None:
        raise LookupError(f"InventorySession {session_id!r} not found")
    stock_items = await storage.load_stock()
    session.report = _build_report(session, stock_items)
    session.finished_at = datetime.now(timezone.utc)
    sessions[session_id] = session
    await storage.save_sessions(sessions)
    await state.set_active_inventory(None)
    await audit.log(
        "inventory_finish",
        session_id=session_id,
        matches=len(session.report["matches"]),
        shortfalls=len(session.report["shortfalls"]),
        surpluses=len(session.report["surpluses"]),
        expired=len(session.report["expired_still_in_stash"]),
        unknown=len(session.unknown_scans),
    )
    return session


def _build_report(session: InventorySession, stock_items: List[StockItem]) -> Dict[str, Any]:
    today = date.today()
    in_stock_by_ean: Dict[str, int] = {}
    expired: List[Dict[str, Any]] = []
    for item in stock_items:
        if item.status != StockStatus.IN_STOCK:
            continue
        in_stock_by_ean[item.ean] = in_stock_by_ean.get(item.ean, 0) + 1
        if item.best_before < today:
            expired.append({
                "stock_id": item.id,
                "ean": item.ean,
                "best_before": item.best_before.isoformat(),
                "location": item.location,
            })

    matches: List[Dict[str, Any]] = []
    shortfalls: List[Dict[str, Any]] = []
    surpluses: List[Dict[str, Any]] = []
    for ean in sorted(set(session.counts) | set(in_stock_by_ean)):
        counted = session.counts.get(ean, 0)
        expected = in_stock_by_ean.get(ean, 0)
        row = {"ean": ean, "counted": counted, "expected": expected, "diff": counted - expected}
        if counted == expected:
            matches.append(row)
        elif counted < expected:
            shortfalls.append(row)
        else:
            surpluses.append(row)

    return {
        "matches": matches,
        "shortfalls": shortfalls,
        "surpluses": surpluses,
        "expired_still_in_stash": expired,
        "unknown_scans": list(session.unknown_scans),
    }
