"""Home Assistant integration endpoints.

Strictly read-only per the design contract (§2.1 of the handover). Anything
that would mutate state has to be triggered via a control barcode.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from .. import dashboard, state, storage

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])


@router.get("/sensors", response_model=Dict[str, Any])
async def sensors() -> Dict[str, Any]:
    summary = await dashboard.summary()
    st = await state.get()
    return {
        "mode": st.mode.value,
        "active_inventory_id": st.active_inventory_id,
        "in_stock_total": summary["totals"]["in_stock"],
        "consumed_total": summary["totals"]["consumed"],
        "discarded_total": summary["totals"]["discarded"],
        "waste_rate_pct": summary["waste_rate_pct"],
        "expired_in_stash": summary["expired_in_stash"],
        "expiring_within": summary["expiring_within"],
        "unread_notifications": summary["unread_notifications"],
        "catalogue_products": summary["totals"]["catalogue_products"],
    }


@router.get("/expiring", response_model=List[Dict[str, Any]])
async def expiring(
    within_days: int = Query(30, ge=0, le=3650, description="Cutoff window in days from today."),
) -> List[Dict[str, Any]]:
    return await dashboard.items_expiring_within(within_days)
