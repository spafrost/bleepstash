"""Atomic JSON-file storage with in-process serialisation and rolling backups."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_settings
from .models import (
    AppState,
    Blueprint,
    InventorySession,
    Notification,
    Product,
    StockItem,
)

# One lock per absolute path — coarse but correct for our single-process app.
_locks: Dict[str, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    key = str(path.resolve())
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _atomic_write(path: Path, data: str) -> None:
    """Write to a sibling tmp file, fsync, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _snapshot(path: Path) -> None:
    """Copy the current file into /data/backups with a timestamped name."""
    if not path.exists():
        return
    settings = get_settings()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = settings.backups_dir / f"{path.stem}.{ts}{path.suffix}"
    shutil.copy2(path, dest)
    _prune_backups(path.stem, settings.backup_retention)


def _prune_backups(stem: str, keep: int) -> None:
    settings = get_settings()
    files = sorted(
        settings.backups_dir.glob(f"{stem}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


async def _load_json(path: Path, default: Any) -> Any:
    async with _lock_for(path):
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Corrupt JSON in {path}: {exc}") from exc


async def _save_json(path: Path, payload: Any, *, snapshot: bool = True) -> None:
    async with _lock_for(path):
        if snapshot:
            _snapshot(path)
        _atomic_write(path, json.dumps(payload, indent=2, default=str))


# ---------------------------------------------------------------------------
# High-level accessors
# ---------------------------------------------------------------------------


async def load_products() -> Dict[str, Product]:
    raw = await _load_json(get_settings().products_path, {})
    return {ean: Product.model_validate(p) for ean, p in raw.items()}


async def save_products(products: Dict[str, Product]) -> None:
    payload = {ean: p.model_dump(mode="json") for ean, p in products.items()}
    await _save_json(get_settings().products_path, payload)


async def load_stock() -> List[StockItem]:
    raw = await _load_json(get_settings().stock_path, {"items": []})
    return [StockItem.model_validate(item) for item in raw.get("items", [])]


async def save_stock(items: List[StockItem]) -> None:
    payload = {"items": [item.model_dump(mode="json") for item in items]}
    await _save_json(get_settings().stock_path, payload)


async def load_state() -> AppState:
    raw = await _load_json(get_settings().state_path, None)
    if raw is None:
        return AppState()
    return AppState.model_validate(raw)


async def save_state(state: AppState) -> None:
    # State is written on every mode change / pending update — snapshot would
    # produce hundreds of near-identical backup files, so opt out.
    await _save_json(get_settings().state_path, state.model_dump(mode="json"), snapshot=False)


async def load_notifications() -> List[Notification]:
    raw = await _load_json(get_settings().notifications_path, {"items": []})
    return [Notification.model_validate(n) for n in raw.get("items", [])]


async def save_notifications(items: List[Notification]) -> None:
    payload = {"items": [n.model_dump(mode="json") for n in items]}
    await _save_json(get_settings().notifications_path, payload, snapshot=False)


async def load_sessions() -> Dict[str, InventorySession]:
    raw = await _load_json(get_settings().sessions_path, {})
    return {sid: InventorySession.model_validate(s) for sid, s in raw.items()}


async def save_sessions(sessions: Dict[str, InventorySession]) -> None:
    payload = {sid: s.model_dump(mode="json") for sid, s in sessions.items()}
    await _save_json(get_settings().sessions_path, payload)


async def load_blueprints() -> Dict[str, Blueprint]:
    raw = await _load_json(get_settings().blueprints_path, {})
    return {bid: Blueprint.model_validate(b) for bid, b in raw.items()}


async def save_blueprints(blueprints: Dict[str, Blueprint]) -> None:
    payload = {bid: b.model_dump(mode="json") for bid, b in blueprints.items()}
    await _save_json(get_settings().blueprints_path, payload)


async def force_backup() -> Path:
    """Snapshot all top-level JSON files. Returns the backups directory path."""
    for path in (
        get_settings().products_path,
        get_settings().stock_path,
        get_settings().sessions_path,
        get_settings().notifications_path,
        get_settings().blueprints_path,
        get_settings().state_path,
    ):
        async with _lock_for(path):
            _snapshot(path)
    return get_settings().backups_dir
