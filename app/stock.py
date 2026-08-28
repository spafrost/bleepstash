"""Stock mutation helpers.

Covers the ADD commit path (M3), FIFO CONSUME/DISCARD, and single-step UNDO
(M4). CONSUME/DISCARD resolve the oldest ``in_stock`` unit for a given EAN
ordered by ``best_before ASC, added_at ASC``. UNDO reads the last reversible
audit event and inverts it (removes a just-added item, or flips a
consumed/discarded item back to ``in_stock``).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from ulid import ULID

from . import audit, state, storage
from .config import get_settings
from .models import AppState, StockItem, StockStatus
from .scan import resolve_best_before


async def commit_add(current_state: AppState) -> List[StockItem]:
    """Create ``qty`` StockItem records from the ready pending entry.

    Assumes ``current_state.pending_add.is_ready`` — the caller (``scan``) is
    responsible for that guard. Resets the pending entry on success.
    """
    pending = current_state.pending_add
    assert pending.is_ready, "commit_add called with non-ready pending entry"

    bbe_iso = resolve_best_before(pending)
    assert bbe_iso is not None
    bbe = date.fromisoformat(bbe_iso)

    location = get_settings().default_location or None
    qty = max(1, pending.qty)

    items = await storage.load_stock()
    created: List[StockItem] = []
    for _ in range(qty):
        item = StockItem(
            id=f"stk_{ULID()}",
            ean=pending.ean,  # type: ignore[arg-type]
            best_before=bbe,
            status=StockStatus.IN_STOCK,
            location=location,
        )
        items.append(item)
        created.append(item)

    await storage.save_stock(items)
    for item in created:
        await audit.log(
            "stock_add",
            stock_id=item.id,
            ean=item.ean,
            bbe=item.best_before.isoformat(),
            location=item.location,
        )
    await state.clear_pending()
    return created


async def consume_oldest(ean: str) -> Optional[StockItem]:
    """Mark the FIFO-oldest in-stock unit for ``ean`` as consumed."""
    return await _mutate_oldest(ean, target=StockStatus.CONSUMED, event="stock_consume")


async def discard_oldest(ean: str) -> Optional[StockItem]:
    """Mark the FIFO-oldest in-stock unit for ``ean`` as discarded."""
    return await _mutate_oldest(ean, target=StockStatus.DISCARDED, event="stock_discard")


async def _mutate_oldest(
    ean: str, *, target: StockStatus, event: str
) -> Optional[StockItem]:
    items = await storage.load_stock()
    candidates = [
        (idx, item)
        for idx, item in enumerate(items)
        if item.ean == ean and item.status == StockStatus.IN_STOCK
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[1].best_before, pair[1].added_at))
    idx, chosen = candidates[0]
    updated = chosen.model_copy(update={
        "status": target,
        "consumed_at": datetime.now(timezone.utc),
    })
    items[idx] = updated
    await storage.save_stock(items)
    await audit.log(
        event,
        stock_id=updated.id,
        ean=updated.ean,
        bbe=updated.best_before.isoformat(),
        location=updated.location,
    )
    return updated


async def undo_last() -> Optional[Dict[str, Any]]:
    """Reverse the most recent reversible audit event.

    - ``stock_add`` → remove the created item from stock.
    - ``stock_consume`` / ``stock_discard`` → flip the item back to
      ``in_stock`` and clear ``consumed_at``.

    Returns a dict describing what was reverted, or ``None`` when there is
    nothing to undo (empty log, last mutation was itself an undo, or the
    referenced stock item is missing).
    """
    record = audit.tail_reversible()
    if record is None:
        return None
    stock_id = record.get("stock_id")
    if not stock_id:
        return None
    reverted_event = record["event"]
    items = await storage.load_stock()

    if reverted_event == "stock_add":
        before = len(items)
        items = [item for item in items if item.id != stock_id]
        if len(items) == before:
            return None
    else:  # stock_consume | stock_discard
        target_idx = next((i for i, item in enumerate(items) if item.id == stock_id), None)
        if target_idx is None:
            return None
        items[target_idx] = items[target_idx].model_copy(update={
            "status": StockStatus.IN_STOCK,
            "consumed_at": None,
        })

    await storage.save_stock(items)
    await audit.log(
        "stock_undo",
        reverted=reverted_event,
        stock_id=stock_id,
        ean=record.get("ean"),
    )
    return {
        "reverted_event": reverted_event,
        "stock_id": stock_id,
        "ean": record.get("ean"),
    }
