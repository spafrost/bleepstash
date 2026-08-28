"""In-memory global app state with write-through to state.json."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from . import audit, storage
from .models import AppState, Mode, PendingAdd

_state: Optional[AppState] = None
_state_lock = asyncio.Lock()


async def initialise() -> AppState:
    global _state
    async with _state_lock:
        if _state is None:
            _state = await storage.load_state()
    return _state


async def get() -> AppState:
    if _state is None:
        await initialise()
    return _state  # type: ignore[return-value]


async def _persist() -> None:
    assert _state is not None
    _state.updated_at = datetime.now(timezone.utc)
    await storage.save_state(_state)


async def set_mode(mode: Mode) -> AppState:
    """Change the global mode. Resets any in-flight pending ADD entry."""
    global _state
    async with _state_lock:
        if _state is None:
            _state = await storage.load_state()
        previous = _state.mode
        _state.mode = mode
        _state.pending_add = PendingAdd()
        await _persist()
    await audit.log("mode_change", **{"from": previous.value, "to": mode.value})
    return _state


async def update_pending(**changes) -> AppState:
    global _state
    async with _state_lock:
        if _state is None:
            _state = await storage.load_state()
        pending = _state.pending_add.model_copy(update=changes)
        _state.pending_add = pending
        await _persist()
    return _state


async def clear_pending() -> AppState:
    return await update_pending(
        ean=None, year=None, month=None, day=None, qty=1,
    )


async def set_active_inventory(session_id: Optional[str]) -> AppState:
    global _state
    async with _state_lock:
        if _state is None:
            _state = await storage.load_state()
        _state.active_inventory_id = session_id
        await _persist()
    return _state


async def set_active_blueprint(blueprint_id: Optional[str]) -> AppState:
    global _state
    async with _state_lock:
        if _state is None:
            _state = await storage.load_state()
        _state.active_blueprint_id = blueprint_id
        await _persist()
    return _state
