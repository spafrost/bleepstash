"""Product catalogue helpers.

Wraps ``storage.load_products`` / ``storage.save_products`` with lookup and
upsert semantics used by the ADD flow. Also owns the optional Open Food Facts
lookup gated by ``BS_EXTERNAL_LOOKUP``; the network path is off by default per
the user's privacy preference.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from . import notifications, storage
from .config import get_settings
from .models import Notification, NotificationSeverity, Product

_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
_OFF_TIMEOUT_SECONDS = 3.0
_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)", re.IGNORECASE)


async def get_product(ean: str) -> Optional[Product]:
    products = await storage.load_products()
    return products.get(ean)


async def upsert_product(product: Product) -> Product:
    """Insert or update a product by EAN. Does not overwrite existing metadata
    fields with ``None`` values from ``product``."""
    products = await storage.load_products()
    existing = products.get(product.ean)
    if existing is None:
        products[product.ean] = product
    else:
        merged = existing.model_copy(update={
            k: v for k, v in product.model_dump(exclude={"created_at"}).items()
            if v is not None
        })
        products[product.ean] = merged
    await storage.save_products(products)
    return products[product.ean]


async def ensure_product(ean: str) -> tuple[Product, bool]:
    """Return ``(product, was_created)``.

    - Existing catalogue hit → return as-is, ``was_created=False``.
    - Miss → create a placeholder ``name="Unknown"`` Product, optionally
      enrich from Open Food Facts (if ``BS_EXTERNAL_LOOKUP=on``), persist it,
      and raise an in-app notification prompting the operator to complete
      metadata later. Returns ``was_created=True``.
    """
    existing = await get_product(ean)
    if existing is not None:
        return existing, False

    placeholder = Product(ean=ean, name="Unknown")

    if get_settings().external_lookup.lower() == "on":
        enriched = await _lookup_open_food_facts(ean)
        if enriched is not None:
            placeholder = placeholder.model_copy(update={
                k: v for k, v in enriched.items() if v is not None
            })

    saved = await upsert_product(placeholder)
    await _notify_unknown(ean, saved.name)
    return saved, True


async def refresh_from_off(ean: str) -> Optional[Product]:
    """Manually re-fetch OFF for an existing catalogue entry.

    Never overwrites locally-set fields — only fills fields that are still
    ``None`` (or ``name == 'Unknown'``, treated as a placeholder). Returns the
    updated product, or ``None`` if the product doesn't exist locally.
    """
    existing = await get_product(ean)
    if existing is None:
        return None

    enriched = await _lookup_open_food_facts(ean)
    if enriched is None:
        return existing

    updates: dict = {}
    for key, value in enriched.items():
        if value is None:
            continue
        current = getattr(existing, key, None)
        # Treat placeholder "Unknown" name as still-unset so OFF can fill it.
        if current in (None, "", "Unknown"):
            updates[key] = value

    if not updates:
        return existing
    return await upsert_product(existing.model_copy(update=updates))


async def _notify_unknown(ean: str, current_name: str) -> Notification:
    title = f"Unknown EAN scanned — {ean}"
    body = (
        f"A stock item was added for EAN {ean} using the placeholder name "
        f"'{current_name}'. Please complete its metadata from the Catalogue "
        "when convenient."
    )
    return await notifications.create(
        title,
        body=body,
        severity=NotificationSeverity.WARN,
        link=f"/catalogue/{ean}",
    )


async def _lookup_open_food_facts(ean: str) -> Optional[dict]:
    """Fetch a subset of OFF fields. Returns None on any failure."""
    try:
        return await asyncio.to_thread(_fetch_off_blocking, ean)
    except Exception:
        return None


def _fetch_off_blocking(ean: str) -> Optional[dict]:
    url = _OFF_URL.format(ean=ean)
    req = urlrequest.Request(url, headers={"User-Agent": "BleepStash/0.1 (+local)"})
    try:
        with urlrequest.urlopen(req, timeout=_OFF_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            payload = json.load(resp)
    except (urlerror.URLError, TimeoutError, json.JSONDecodeError):
        return None

    if payload.get("status") != 1:
        return None
    product = payload.get("product") or {}
    return {
        "name": product.get("product_name") or None,
        "manufacturer": product.get("brands") or None,
        "weight_g": _parse_weight_g(product.get("quantity")),
    }


def _parse_weight_g(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    match = _WEIGHT_RE.search(raw)
    if match is None:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit == "kg":
        return value * 1000.0
    if unit == "g":
        return value
    # Liquids: treat 1 ml ≈ 1 g as a best-effort default; user can correct.
    if unit == "l":
        return value * 1000.0
    if unit == "ml":
        return value
    return None
