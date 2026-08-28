"""Blueprint management + fulfilment computation.

A Blueprint is a target state for the stash: a list of slots, each specifying
how many units of which EAN(s) are needed. Only one Blueprint may be active
at a time (tracked in AppState.active_blueprint_id).

Fulfilment is computed **independently per slot**: the same in-stock unit
counts towards every slot whose ``accepted_eans`` list includes its EAN.
Users control what a slot "owns" by curating the accepted_eans list.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ulid import ULID

from . import audit, state, storage
from .models import Blueprint, BlueprintSlot, StockStatus


async def list_all() -> Dict[str, Blueprint]:
    return await storage.load_blueprints()


async def get(blueprint_id: str) -> Optional[Blueprint]:
    all_ = await storage.load_blueprints()
    return all_.get(blueprint_id)


async def create(name: str, description: str = "") -> Blueprint:
    bp = Blueprint(
        id=f"bp_{ULID()}",
        name=name,
        description=description or None,
    )
    all_ = await storage.load_blueprints()
    all_[bp.id] = bp
    await storage.save_blueprints(all_)
    await audit.log("blueprint_create", blueprint_id=bp.id, name=name)
    return bp


async def update(
    blueprint_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[Blueprint]:
    all_ = await storage.load_blueprints()
    bp = all_.get(blueprint_id)
    if bp is None:
        return None
    changes: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if name is not None:
        changes["name"] = name
    if description is not None:
        changes["description"] = description or None
    all_[blueprint_id] = bp.model_copy(update=changes)
    await storage.save_blueprints(all_)
    return all_[blueprint_id]


async def delete(blueprint_id: str) -> bool:
    all_ = await storage.load_blueprints()
    if blueprint_id not in all_:
        return False
    del all_[blueprint_id]
    await storage.save_blueprints(all_)
    st = await state.get()
    if st.active_blueprint_id == blueprint_id:
        await state.set_active_blueprint(None)
    await audit.log("blueprint_delete", blueprint_id=blueprint_id)
    return True


async def add_slot(
    blueprint_id: str,
    *,
    label: str,
    required_qty: int,
    unit: str,
    accepted_eans: List[str],
    notes: Optional[str] = None,
) -> Optional[BlueprintSlot]:
    all_ = await storage.load_blueprints()
    bp = all_.get(blueprint_id)
    if bp is None:
        return None
    slot = BlueprintSlot(
        id=f"bps_{ULID()}",
        label=label,
        required_qty=max(0, int(required_qty)),
        unit=(unit or "units").strip() or "units",
        accepted_eans=[e.strip() for e in accepted_eans if e.strip()],
        notes=notes or None,
    )
    bp.slots.append(slot)
    bp.updated_at = datetime.now(timezone.utc)
    all_[blueprint_id] = bp
    await storage.save_blueprints(all_)
    await audit.log("blueprint_slot_add", blueprint_id=blueprint_id, slot_id=slot.id)
    return slot


async def update_slot(
    blueprint_id: str,
    slot_id: str,
    *,
    label: Optional[str] = None,
    required_qty: Optional[int] = None,
    unit: Optional[str] = None,
    accepted_eans: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Optional[BlueprintSlot]:
    all_ = await storage.load_blueprints()
    bp = all_.get(blueprint_id)
    if bp is None:
        return None
    for i, s in enumerate(bp.slots):
        if s.id == slot_id:
            changes: Dict[str, Any] = {}
            if label is not None:
                changes["label"] = label
            if required_qty is not None:
                changes["required_qty"] = max(0, int(required_qty))
            if unit is not None:
                changes["unit"] = (unit or "units").strip() or "units"
            if accepted_eans is not None:
                changes["accepted_eans"] = [e.strip() for e in accepted_eans if e.strip()]
            if notes is not None:
                changes["notes"] = notes or None
            bp.slots[i] = s.model_copy(update=changes)
            bp.updated_at = datetime.now(timezone.utc)
            all_[blueprint_id] = bp
            await storage.save_blueprints(all_)
            return bp.slots[i]
    return None


async def delete_slot(blueprint_id: str, slot_id: str) -> bool:
    all_ = await storage.load_blueprints()
    bp = all_.get(blueprint_id)
    if bp is None:
        return False
    before = len(bp.slots)
    bp.slots = [s for s in bp.slots if s.id != slot_id]
    if len(bp.slots) == before:
        return False
    bp.updated_at = datetime.now(timezone.utc)
    all_[blueprint_id] = bp
    await storage.save_blueprints(all_)
    return True


async def activate(blueprint_id: str) -> bool:
    all_ = await storage.load_blueprints()
    if blueprint_id not in all_:
        return False
    await state.set_active_blueprint(blueprint_id)
    await audit.log("blueprint_activate", blueprint_id=blueprint_id)
    return True


async def deactivate() -> None:
    st = await state.get()
    prev = st.active_blueprint_id
    await state.set_active_blueprint(None)
    if prev:
        await audit.log("blueprint_deactivate", blueprint_id=prev)


async def compute_fulfilment(blueprint_id: str) -> Optional[Dict[str, Any]]:
    """Independent per-slot fulfilment against current in-stock inventory."""
    bp = await get(blueprint_id)
    if bp is None:
        return None
    stock_items = await storage.load_stock()
    products = await storage.load_products()

    in_stock_by_ean: Dict[str, int] = {}
    for item in stock_items:
        if item.status == StockStatus.IN_STOCK:
            in_stock_by_ean[item.ean] = in_stock_by_ean.get(item.ean, 0) + 1

    slots_out: List[Dict[str, Any]] = []
    for slot in bp.slots:
        contributions: List[Dict[str, Any]] = []
        total_available = 0.0
        slot_unit_norm = (slot.unit or "").strip().lower()
        for ean in slot.accepted_eans:
            n = in_stock_by_ean.get(ean, 0)
            if n == 0:
                continue
            p = products.get(ean)
            if p is None:
                contributions.append({
                    "ean": ean,
                    "name": "Unknown",
                    "count": n,
                    "product_unit": None,
                    "product_size": None,
                    "contributed_total": 0,
                    "unit_mismatch": True,
                })
                continue
            p_unit_norm = (p.unit or "").strip().lower()
            if p_unit_norm and p_unit_norm == slot_unit_norm and p.size:
                contributed = n * p.size
                total_available += contributed
                contributions.append({
                    "ean": ean,
                    "name": p.name or "Unknown",
                    "count": n,
                    "product_unit": p.unit,
                    "product_size": p.size,
                    "contributed_total": contributed,
                    "unit_mismatch": False,
                })
            else:
                contributions.append({
                    "ean": ean,
                    "name": p.name or "Unknown",
                    "count": n,
                    "product_unit": p.unit,
                    "product_size": p.size,
                    "contributed_total": 0,
                    "unit_mismatch": True,
                })
        filled = min(total_available, slot.required_qty) if slot.required_qty > 0 else total_available
        missing = max(0, slot.required_qty - filled)
        if slot.required_qty <= 0:
            status = "matched"
        elif missing == 0:
            status = "matched"
        elif filled > 0:
            status = "partial"
        else:
            status = "empty"
        slots_out.append({
            "id": slot.id,
            "label": slot.label,
            "unit": slot.unit,
            "required_qty": slot.required_qty,
            "accepted_eans": list(slot.accepted_eans),
            "notes": slot.notes,
            "filled": filled,
            "missing": missing,
            "status": status,
            "contributions": contributions,
        })

    st = await state.get()
    return {
        "blueprint": {
            "id": bp.id,
            "name": bp.name,
            "description": bp.description,
            "template_version": bp.template_version,
            "created_at": bp.created_at.isoformat(),
            "updated_at": bp.updated_at.isoformat(),
        },
        "slots": slots_out,
        "totals": {
            "slots_matched": sum(1 for s in slots_out if s["status"] == "matched"),
            "slots_total": len(slots_out),
        },
        "is_active": st.active_blueprint_id == bp.id,
    }
