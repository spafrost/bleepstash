"""Dashboard aggregation helpers.

Read-only. Computes waste rate, expiry buckets, next-N-expiring and category
coverage from the current on-disk stock. Kept independent of the routers so
both the HTML dashboard and the HA-sensors JSON can share the same numbers.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from . import storage
from .config import get_settings
from .models import Product, StockItem, StockStatus


async def summary() -> Dict[str, Any]:
    stock_items = await storage.load_stock()
    products = await storage.load_products()
    notifs = await storage.load_notifications()

    today = date.today()
    warn_days = get_settings().warn_days

    in_stock = [i for i in stock_items if i.status == StockStatus.IN_STOCK]
    consumed = sum(1 for i in stock_items if i.status == StockStatus.CONSUMED)
    discarded = sum(1 for i in stock_items if i.status == StockStatus.DISCARDED)
    denom = consumed + discarded
    waste_rate_pct = round((discarded / denom) * 100.0, 1) if denom else 0.0

    buckets: Dict[str, int] = {}
    for days in warn_days:
        buckets[str(days)] = sum(
            1
            for item in in_stock
            if today <= item.best_before <= today + timedelta(days=days)
        )
    expired_in_stash = sum(1 for item in in_stock if item.best_before < today)

    next_expiring: List[Dict[str, Any]] = []
    for item in sorted(in_stock, key=lambda i: (i.best_before, i.added_at))[:10]:
        product = products.get(item.ean)
        next_expiring.append(_summarise_item(item, product))

    category_counts: Dict[str, int] = {}
    for item in in_stock:
        product = products.get(item.ean)
        cat = (product.category if product else None) or "(uncategorised)"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    unread_notifications = [n for n in notifs if n.dismissed_at is None]

    return {
        "totals": {
            "in_stock": len(in_stock),
            "consumed": consumed,
            "discarded": discarded,
            "catalogue_products": len(products),
        },
        "waste_rate_pct": waste_rate_pct,
        "expiring_within": buckets,
        "expired_in_stash": expired_in_stash,
        "next_expiring": next_expiring,
        "category_counts": category_counts,
        "unread_notifications": len(unread_notifications),
        "recent_notifications": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "severity": n.severity.value,
                "created_at": n.created_at.isoformat(),
                "link": n.link,
            }
            for n in sorted(unread_notifications, key=lambda x: x.created_at, reverse=True)[:5]
        ],
    }


async def items_expiring_within(days: int) -> List[Dict[str, Any]]:
    stock_items = await storage.load_stock()
    products = await storage.load_products()
    today = date.today()
    cutoff = today + timedelta(days=days)
    matches: List[Dict[str, Any]] = []
    for item in sorted(stock_items, key=lambda i: (i.best_before, i.added_at)):
        if item.status != StockStatus.IN_STOCK:
            continue
        if item.best_before > cutoff:
            continue
        matches.append(_summarise_item(item, products.get(item.ean)))
    return matches


def _summarise_item(item: StockItem, product: Optional[Product]) -> Dict[str, Any]:
    today = date.today()
    return {
        "stock_id": item.id,
        "ean": item.ean,
        "name": (product.name if product else None) or "Unknown",
        "best_before": item.best_before.isoformat(),
        "days_left": (item.best_before - today).days,
        "location": item.location,
    }
