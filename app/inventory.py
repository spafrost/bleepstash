"""Inventory-session helpers.

INVENTORY mode is a stocktake: the operator scans every unit currently in the
stash, one by one. Known EANs increment ``session.counts``; unknown EANs (no
catalogue entry) go into ``session.unknown_scans``.

FINISH closes the session, computes a difference report against current
``in_stock`` inventory, persists the report on the session, clears
``state.active_inventory_id`` and hands the mode back to whatever the operator
was in before starting the stocktake (typically CONSUME).

``snapshot()`` (used by the ``/inventory`` live view and ``/api/inventory/*``)
returns the current picture of a session with per-EAN rows and progress
numbers.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ulid import ULID

from . import audit, products, state, storage
from .models import InventorySession, Mode, Product, StockItem, StockStatus


_STATUS_ORDER = {
    "pending": 0,
    "partial": 1,
    "surplus": 2,
    "matched": 3,
    "unknown": 4,
    "idle": 5,
}


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


async def snapshot(session_id: str) -> Optional[Dict[str, Any]]:
    """Return a live snapshot of a session: rows keyed by EAN + progress.

    Used by ``/inventory`` (live) and ``/inventory/{id}`` (post-FINISH report).
    Returns ``None`` if the session doesn't exist.
    """
    sessions = await storage.load_sessions()
    session = sessions.get(session_id)
    if session is None:
        return None
    catalogue = await storage.load_products()
    stock_items = await storage.load_stock()

    in_stock_by_ean: Dict[str, int] = {}
    for item in stock_items:
        if item.status == StockStatus.IN_STOCK:
            in_stock_by_ean[item.ean] = in_stock_by_ean.get(item.ean, 0) + 1

    all_eans = set(catalogue.keys()) | set(session.counts.keys()) | set(in_stock_by_ean.keys())

    rows: List[Dict[str, Any]] = []
    for ean in all_eans:
        product = catalogue.get(ean)
        expected = in_stock_by_ean.get(ean, 0)
        counted = session.counts.get(ean, 0)
        rows.append({
            "ean": ean,
            "name": (product.name if product else None) or "Unknown",
            "known": product is not None,
            "expected": expected,
            "counted": counted,
            "delta": counted - expected,
            "status": _row_status(counted, expected, product),
        })
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 99), r["name"].lower(), r["ean"]))

    tracked = [r for r in rows if r["expected"] > 0]
    products_done = sum(1 for r in tracked if r["counted"] >= r["expected"])
    products_total = len(tracked)
    units_counted = sum(session.counts.values())
    units_expected = sum(r["expected"] for r in tracked)

    return {
        "session": {
            "id": session.id,
            "started_at": session.started_at.isoformat(),
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
            "opened_from_mode": session.opened_from_mode,
            "is_active": session.finished_at is None,
        },
        "progress": {
            "products_done": products_done,
            "products_total": products_total,
            "units_counted": units_counted,
            "units_expected": units_expected,
        },
        "rows": rows,
        "unknown_scans": list(session.unknown_scans),
        "report": session.report,
    }


def _row_status(counted: int, expected: int, product: Optional[Product]) -> str:
    if product is None:
        return "unknown"
    if counted == 0 and expected == 0:
        return "idle"
    if counted == 0:
        return "pending"
    if counted < expected:
        return "partial"
    if counted == expected:
        return "matched"
    return "surplus"
