"""In-app notification helper.

Notifications are persisted to ``notifications.json`` and surfaced via the
top-bar bell (rendered in M6) and the ``/api/notifications`` endpoint (M6).
The helpers here are minimal on purpose — the full CRUD and dismiss endpoints
land alongside the dashboard work.
"""
from __future__ import annotations

from typing import Optional

from ulid import ULID

from . import storage
from .models import Notification, NotificationSeverity


async def create(
    title: str,
    *,
    body: str = "",
    severity: NotificationSeverity = NotificationSeverity.INFO,
    link: Optional[str] = None,
) -> Notification:
    """Append a new notification and persist it."""
    notif = Notification(
        id=f"ntf_{ULID()}",
        title=title,
        body=body,
        severity=severity,
        link=link,
    )
    items = await storage.load_notifications()
    items.append(notif)
    await storage.save_notifications(items)
    return notif
