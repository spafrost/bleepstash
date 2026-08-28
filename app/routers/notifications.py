"""Notification API endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .. import storage
from ..models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=List[Notification])
async def list_notifications(
    unread: Optional[bool] = Query(None, description="If true, only unread items."),
) -> List[Notification]:
    items = await storage.load_notifications()
    if unread:
        items = [n for n in items if n.dismissed_at is None]
    return sorted(items, key=lambda n: n.created_at, reverse=True)


@router.post("/dismiss-all", response_model=dict)
async def dismiss_all() -> dict:
    items = await storage.load_notifications()
    now = datetime.now(timezone.utc)
    count = 0
    for i, n in enumerate(items):
        if n.dismissed_at is None:
            items[i] = n.model_copy(update={"dismissed_at": now})
            count += 1
    if count:
        await storage.save_notifications(items)
    return {"dismissed": count}


@router.post("/{notification_id}/dismiss", response_model=Notification)
async def dismiss_one(notification_id: str) -> Notification:
    items = await storage.load_notifications()
    for i, n in enumerate(items):
        if n.id == notification_id:
            if n.dismissed_at is None:
                items[i] = n.model_copy(update={"dismissed_at": datetime.now(timezone.utc)})
                await storage.save_notifications(items)
            return items[i]
    raise HTTPException(status_code=404, detail="Notification not found")
