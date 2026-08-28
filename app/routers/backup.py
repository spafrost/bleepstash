"""Backup + reset endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from .. import storage

router = APIRouter(prefix="/api", tags=["backup"])


@router.post("/backup")
async def force_backup() -> dict:
    """Snapshot every top-level JSON file into ``/data/backups`` immediately."""
    backups_dir = await storage.force_backup()
    return {"status": "ok", "backups_dir": str(backups_dir)}
