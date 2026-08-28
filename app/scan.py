"""Scan pipeline — accepts raw scanner input and dispatches per current mode.

As of M3 the ADD flow is fully wired: product scans upsert the catalogue,
date control scans populate the pending entry, and reaching ``is_ready``
(either implicitly on MONTH scan, or explicitly via ``^CTRL^ACTION:CONFIRM``)
commits ``qty`` StockItem records. CONSUME/DISCARD/INVENTORY/LOOKUP remain
stubs and land in M4–M6.
"""
from __future__ import annotations

import calendar
from typing import Optional

from . import audit, barcodes, state
from .models import (
    AppState,
    Mode,
    PendingAdd,
    ScanKind,
    ScanResult,
    ScanResultStatus,
)


def _result(
    *,
    status: ScanResultStatus,
    kind: ScanKind,
    current_state: AppState,
    message: str,
    tone: str = "accept",
    detail: Optional[dict] = None,
) -> ScanResult:
    return ScanResult(
        status=status,
        kind=kind,
        mode=current_state.mode,
        message=message,
        pending=current_state.pending_add if current_state.mode == Mode.ADD else None,
        detail=detail,
        tone=tone,  # type: ignore[arg-type]
    )


async def _label_for(ean: str) -> str:
    """Return "Name (EAN)" when the catalogue knows the product, else the EAN.

    Placeholder entries with ``name == 'Unknown'`` are treated as unnamed so the
    kiosk keeps showing the raw EAN until an operator (or OFF enrichment) fills
    in a real name.
    """
    from . import products as products_mod  # lazy: avoid circular at import time

    product = await products_mod.get_product(ean)
    if product is not None and product.name and product.name != "Unknown":
        return f"{product.name} ({ean})"
    return ean


async def _handle_mode_change(new_mode: Mode) -> ScanResult:
    previous_state = await state.get()
    previous_mode = previous_state.mode
    st = await state.set_mode(new_mode)

    if new_mode == Mode.INVENTORY and st.active_inventory_id is None:
        from . import inventory  # lazy: avoid pulling storage on module import

        session = await inventory.open_session(previous_mode)
        st = await state.set_active_inventory(session.id)
        message = (
            f"Mode set to INVENTORY. Session {session.id} open — "
            "scan stash items one by one; scan CTRL^ACTION:FINISH to close."
        )
    else:
        message = f"Mode set to {new_mode.value}."

    return _result(
        status=ScanResultStatus.OK,
        kind=ScanKind.CONTROL,
        current_state=st,
        message=message,
    )


async def _handle_add_control(intent: barcodes.BarcodeIntent) -> ScanResult:
    """Handle YEAR / MONTH / DAY / QTY control scans while in ADD mode."""
    st = await state.get()

    if intent.kind == "year":
        st = await state.update_pending(year=int(intent.value))  # type: ignore[arg-type]
        if st.pending_add.is_ready:
            return await _commit_ready_add(st)
        return _result(
            status=ScanResultStatus.WAITING,
            kind=ScanKind.CONTROL,
            current_state=st,
            message=f"Year {intent.value} noted.",
        )

    if intent.kind == "month":
        st = await state.update_pending(month=int(intent.value))  # type: ignore[arg-type]
        if st.pending_add.is_ready:
            return await _commit_ready_add(st)
        return _result(
            status=ScanResultStatus.WAITING,
            kind=ScanKind.CONTROL,
            current_state=st,
            message=f"Month {intent.value:02d} noted.",
        )

    if intent.kind == "qty":
        st = await state.update_pending(qty=int(intent.value))  # type: ignore[arg-type]
        return _result(
            status=ScanResultStatus.WAITING,
            kind=ScanKind.CONTROL,
            current_state=st,
            message=f"Next entry will be recorded {intent.value}×.",
        )

    return _result(
        status=ScanResultStatus.IGNORED,
        kind=ScanKind.CONTROL,
        current_state=st,
        message="Control barcode ignored (not valid in current context).",
        tone="attention",
    )


async def _handle_action(intent: barcodes.BarcodeIntent) -> ScanResult:
    st = await state.get()
    action = intent.value

    if action == "CANCEL":
        st = await state.clear_pending()
        await audit.log("action", action="CANCEL")
        return _result(
            status=ScanResultStatus.OK,
            kind=ScanKind.CONTROL,
            current_state=st,
            message="Pending entry cancelled.",
        )

    if action == "CONFIRM":
        if st.mode == Mode.ADD and st.pending_add.is_ready:
            return await _commit_ready_add(st)
        return _result(
            status=ScanResultStatus.IGNORED,
            kind=ScanKind.CONTROL,
            current_state=st,
            message="Nothing to confirm — pending entry is not ready.",
            tone="attention",
        )

    if action == "UNDO":
        from . import stock  # lazy: stock imports resolve_best_before from here

        result = await stock.undo_last()
        if result is None:
            return _result(
                status=ScanResultStatus.IGNORED,
                kind=ScanKind.CONTROL,
                current_state=st,
                message="Nothing to undo.",
                tone="attention",
            )
        reverted = result["reverted_event"]
        stock_id = result["stock_id"]
        human = {
            "stock_add": "Reverted last ADD",
            "stock_consume": "Reverted last CONSUME",
            "stock_discard": "Reverted last DISCARD",
        }[reverted]
        return _result(
            status=ScanResultStatus.OK,
            kind=ScanKind.CONTROL,
            current_state=st,
            message=f"{human} — stock item {stock_id}.",
            detail=result,
        )

    if action == "FINISH":
        from . import inventory

        if st.mode != Mode.INVENTORY or not st.active_inventory_id:
            return _result(
                status=ScanResultStatus.IGNORED,
                kind=ScanKind.CONTROL,
                current_state=st,
                message="No inventory session to finish.",
                tone="attention",
            )
        session = await inventory.finish_session(st.active_inventory_id)
        # Restore previous mode (default CONSUME if unknown)
        try:
            restore = Mode(session.opened_from_mode) if session.opened_from_mode else Mode.CONSUME
        except ValueError:
            restore = Mode.CONSUME
        st = await state.set_mode(restore)
        report = session.report or {}
        summary = (
            f"Inventory session {session.id} closed. "
            f"{len(report.get('matches', []))} matches, "
            f"{len(report.get('shortfalls', []))} shortfalls, "
            f"{len(report.get('surpluses', []))} surpluses, "
            f"{len(report.get('expired_still_in_stash', []))} expired-in-stash, "
            f"{len(report.get('unknown_scans', []))} unknown scans. "
            f"Mode restored to {restore.value}."
        )
        return _result(
            status=ScanResultStatus.OK,
            kind=ScanKind.CONTROL,
            current_state=st,
            message=summary,
            detail={"session_id": session.id, "report": report},
        )

    return _result(
        status=ScanResultStatus.ERROR,
        kind=ScanKind.CONTROL,
        current_state=st,
        message=f"Unknown action: {action!r}.",
        tone="reject",
    )


async def _handle_product(ean: str) -> ScanResult:
    """Product handler — dispatch by mode. CONSUME/DISCARD/INVENTORY/LOOKUP
    remain stubs until M4–M6."""
    from . import products  # local import to avoid a circular reference at load

    st = await state.get()

    if st.mode == Mode.ADD:
        product, was_created = await products.ensure_product(ean)
        st = await state.update_pending(ean=ean)
        await audit.log(
            "scan_product_pending",
            ean=ean,
            mode=st.mode.value,
            product_created=was_created,
        )
        if st.pending_add.is_ready:
            return await _commit_ready_add(st)
        pending: PendingAdd = st.pending_add
        need = []
        if pending.year is None:
            need.append("YEAR")
        if pending.month is None:
            need.append("MONTH")
        label = (
            f"{product.name} ({ean})"
            if product.name and product.name != "Unknown"
            else ean
        )
        prefix = f"Product {label} noted."
        message = prefix + (
            f" Still need: {', '.join(need)}." if need else " Awaiting CONFIRM."
        )
        return _result(
            status=ScanResultStatus.WAITING,
            kind=ScanKind.PRODUCT,
            current_state=st,
            message=message,
        )

    if st.mode in (Mode.CONSUME, Mode.DISCARD):
        from . import notifications, stock  # lazy: avoid import cycle with stock
        from .models import NotificationSeverity

        mutate = stock.consume_oldest if st.mode == Mode.CONSUME else stock.discard_oldest
        verb = "consumed" if st.mode == Mode.CONSUME else "discarded"
        label = await _label_for(ean)
        item = await mutate(ean)
        if item is None:
            await notifications.create(
                f"Out of stock — {label}",
                body=(
                    f"Scanned {label} in {st.mode.value} mode but no in-stock units remain. "
                    "Check the catalogue or add more before scanning again."
                ),
                severity=NotificationSeverity.WARN,
                link=f"/catalogue/{ean}",
            )
            await audit.log("scan_out_of_stock", ean=ean, mode=st.mode.value)
            return _result(
                status=ScanResultStatus.ERROR,
                kind=ScanKind.PRODUCT,
                current_state=st,
                message=f"No in-stock units of {label} to {verb.rstrip('d')}.",
                tone="reject",
            )
        return _result(
            status=ScanResultStatus.OK,
            kind=ScanKind.PRODUCT,
            current_state=st,
            message=(
                f"{label} {verb} — best before {item.best_before.isoformat()}"
                + (f" ({item.location})." if item.location else ".")
            ),
            detail={
                "stock_id": item.id,
                "best_before": item.best_before.isoformat(),
            },
        )

    if st.mode == Mode.INVENTORY:
        from . import inventory

        if not st.active_inventory_id:
            # Defensive: shouldn't normally happen — mode-change bootstraps it.
            return _result(
                status=ScanResultStatus.ERROR,
                kind=ScanKind.PRODUCT,
                current_state=st,
                message="INVENTORY mode has no active session. Re-scan MODE:INVENTORY.",
                tone="reject",
            )
        session, known = await inventory.record_scan(st.active_inventory_id, ean)
        counted = session.counts.get(ean, 0)
        if known:
            label = await _label_for(ean)
            message = f"Counted {label} ({counted}× so far in session)."
        else:
            message = f"Unknown EAN {ean} recorded in session unknowns list."
        return _result(
            status=ScanResultStatus.OK if known else ScanResultStatus.WAITING,
            kind=ScanKind.PRODUCT,
            current_state=st,
            message=message,
            detail={"session_id": session.id, "counted": counted, "known": known},
            tone="accept" if known else "attention",
        )

    if st.mode == Mode.LOOKUP:
        from . import products as products_mod
        from . import storage as storage_mod

        product = await products_mod.get_product(ean)
        items = await storage_mod.load_stock()
        matches = [i for i in items if i.ean == ean]
        in_stock = sorted(
            (i for i in matches if i.status.value == "in_stock"),
            key=lambda i: (i.best_before, i.added_at),
        )
        consumed = sum(1 for i in matches if i.status.value == "consumed")
        discarded = sum(1 for i in matches if i.status.value == "discarded")

        await audit.log(
            "lookup",
            ean=ean,
            known=product is not None,
            in_stock=len(in_stock),
            consumed=consumed,
            discarded=discarded,
        )

        if product is None:
            return _result(
                status=ScanResultStatus.WAITING,
                kind=ScanKind.PRODUCT,
                current_state=st,
                message=f"Unknown EAN {ean} — nothing recorded.",
                tone="attention",
                detail={"known": False, "in_stock": 0, "consumed": 0, "discarded": 0},
            )

        label = await _label_for(ean)
        oldest_bbe = in_stock[0].best_before.isoformat() if in_stock else None
        parts = [f"{label} — {len(in_stock)}× in stock"]
        if oldest_bbe:
            parts.append(f"oldest BBE {oldest_bbe}")
        parts.append(f"{consumed} consumed")
        parts.append(f"{discarded} discarded")
        message = ", ".join(parts) + "."
        return _result(
            status=ScanResultStatus.OK,
            kind=ScanKind.PRODUCT,
            current_state=st,
            message=message,
            detail={
                "known": True,
                "in_stock": len(in_stock),
                "consumed": consumed,
                "discarded": discarded,
                "oldest_best_before": oldest_bbe,
                "product": product.model_dump(mode="json"),
            },
        )

    return _result(
        status=ScanResultStatus.ERROR,
        kind=ScanKind.PRODUCT,
        current_state=st,
        message="Unhandled mode.",
        tone="reject",
    )


async def dispatch(code: str) -> ScanResult:
    """Entry point for POST /api/scan."""
    await state.initialise()
    intent = barcodes.parse(code)
    st = await state.get()

    if intent.kind == "unknown":
        await audit.log("scan_unknown", raw=intent.raw)
        return _result(
            status=ScanResultStatus.ERROR,
            kind=ScanKind.UNKNOWN,
            current_state=st,
            message=f"Unrecognised code: {intent.raw!r}.",
            tone="reject",
        )

    if intent.kind == "mode":
        return await _handle_mode_change(intent.value)  # type: ignore[arg-type]

    if intent.kind == "action":
        return await _handle_action(intent)

    if intent.kind in ("year", "month", "qty"):
        if st.mode != Mode.ADD:
            return _result(
                status=ScanResultStatus.IGNORED,
                kind=ScanKind.CONTROL,
                current_state=st,
                message=f"{intent.kind.upper()} scan only meaningful in ADD mode.",
                tone="attention",
            )
        return await _handle_add_control(intent)

    if intent.kind == "product":
        return await _handle_product(intent.value)  # type: ignore[arg-type]

    return _result(
        status=ScanResultStatus.ERROR,
        kind=ScanKind.UNKNOWN,
        current_state=st,
        message="Unhandled scan.",
        tone="reject",
    )


async def _commit_ready_add(current_state: AppState) -> ScanResult:
    """Delegate to ``stock.commit_add`` and build the ScanResult.

    The stock module is imported lazily to keep this module free of a
    circular dependency (stock imports resolve_best_before from here).
    """
    from . import stock  # local import: stock -> scan -> stock cycle otherwise

    pending = current_state.pending_add
    created = await stock.commit_add(current_state)
    st = await state.get()
    bbe = created[0].best_before.isoformat()
    stock_ids = [item.id for item in created]
    label = await _label_for(pending.ean)  # type: ignore[arg-type]
    message = (
        f"Added {len(created)}× {label} — best before {bbe}"
        + (f" ({created[0].location})." if created[0].location else ".")
    )
    return _result(
        status=ScanResultStatus.OK,
        kind=ScanKind.PRODUCT,
        current_state=st,
        message=message,
        detail={"stock_ids": stock_ids, "best_before": bbe},
    )


def resolve_best_before(pending: PendingAdd) -> Optional[str]:
    """Return an ISO date string for the pending entry, or None if incomplete.

    Provided here (rather than in M3) because both the ADD commit path and the
    UI preview will need it.
    """
    if not pending.has_date:
        return None
    year = pending.year  # type: ignore[assignment]
    month = pending.month  # type: ignore[assignment]
    day = pending.day or calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{day:02d}"
