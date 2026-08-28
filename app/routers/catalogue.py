"""Catalogue: list + edit product metadata, view per-product stock history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import __version__
from .. import audit
from .. import products as products_mod
from .. import state as state_manager
from .. import storage
from ..models import StockStatus

router = APIRouter(tags=["catalogue"])


def _get_templates(request: Request):
    return request.app.state.templates


async def _base_context() -> dict:
    return {"state": await state_manager.get(), "version": __version__}


@router.get("/catalogue", response_class=HTMLResponse)
async def catalogue_index(request: Request) -> HTMLResponse:
    products = await storage.load_products()
    stock_items = await storage.load_stock()

    in_stock_counts: dict[str, int] = {}
    for item in stock_items:
        if item.status == StockStatus.IN_STOCK:
            in_stock_counts[item.ean] = in_stock_counts.get(item.ean, 0) + 1

    rows = []
    for ean, product in products.items():
        rows.append({
            "ean": ean,
            "name": product.name,
            "manufacturer": product.manufacturer,
            "weight_g": product.weight_g,
            "category": product.category,
            "in_stock": in_stock_counts.get(ean, 0),
            "is_placeholder": product.name == "Unknown",
        })
    rows.sort(key=lambda r: (r["name"] or "", r["ean"]))

    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "catalogue.html",
        {**await _base_context(), "products": rows},
    )


@router.get("/catalogue/{ean}", response_class=HTMLResponse)
async def catalogue_detail(request: Request, ean: str) -> HTMLResponse:
    product = await products_mod.get_product(ean)
    if product is None:
        raise HTTPException(status_code=404, detail=f"No catalogue entry for EAN {ean}")

    stock_items = await storage.load_stock()
    matches = [i for i in stock_items if i.ean == ean]
    matches.sort(key=lambda i: (i.best_before, i.added_at))

    counts = {
        "in_stock": sum(1 for i in matches if i.status == StockStatus.IN_STOCK),
        "consumed": sum(1 for i in matches if i.status == StockStatus.CONSUMED),
        "discarded": sum(1 for i in matches if i.status == StockStatus.DISCARDED),
    }

    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "product_detail.html",
        {
            **await _base_context(),
            "product": product,
            "stock_items": matches,
            "counts": counts,
        },
    )


@router.post("/catalogue/{ean}", response_class=HTMLResponse)
async def catalogue_update(
    request: Request,
    ean: str,
    name: str = Form(...),
    manufacturer: str = Form(""),
    weight_g: str = Form(""),
    category: str = Form(""),
    default_shelf_life_months: str = Form(""),
) -> HTMLResponse:
    product = await products_mod.get_product(ean)
    if product is None:
        raise HTTPException(status_code=404, detail=f"No catalogue entry for EAN {ean}")

    updated = product.model_copy(update={
        "name": name.strip() or "Unknown",
        "manufacturer": manufacturer.strip() or None,
        "weight_g": _to_float(weight_g),
        "category": category.strip() or None,
        "default_shelf_life_months": _to_int(default_shelf_life_months),
        "updated_at": datetime.now(timezone.utc),
    })

    # upsert_product only merges non-None updates, which would prevent
    # clearing a field. Persist directly to allow clearing.
    all_products = await storage.load_products()
    all_products[ean] = updated
    await storage.save_products(all_products)

    return RedirectResponse(url=f"/catalogue/{ean}", status_code=303)


@router.post("/catalogue/{ean}/refresh", response_class=HTMLResponse)
async def catalogue_refresh(request: Request, ean: str) -> HTMLResponse:
    product = await products_mod.get_product(ean)
    if product is None:
        raise HTTPException(status_code=404, detail=f"No catalogue entry for EAN {ean}")
    await products_mod.refresh_from_off(ean)
    return RedirectResponse(url=f"/catalogue/{ean}", status_code=303)


@router.post("/catalogue/{ean}/stock/{stock_id}/delete", response_class=HTMLResponse)
async def catalogue_delete_stock(
    request: Request,
    ean: str,
    stock_id: str,
) -> HTMLResponse:
    """Permanently remove a single stock item. Manual clean-up escape hatch.

    Distinct from CONSUME/DISCARD (which mutate status) and UNDO (which reverses
    the last mutation). Emits a ``stock_delete`` audit event so the removal is
    still traceable.
    """
    items = await storage.load_stock()
    target = next((i for i in items if i.id == stock_id and i.ean == ean), None)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"No stock item {stock_id} for EAN {ean}",
        )
    items = [i for i in items if i.id != stock_id]
    await storage.save_stock(items)
    await audit.log(
        "stock_delete",
        stock_id=target.id,
        ean=target.ean,
        bbe=target.best_before.isoformat(),
        prior_status=target.status.value,
    )
    return RedirectResponse(url=f"/catalogue/{ean}", status_code=303)


def _to_float(raw: str) -> Optional[float]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _to_int(raw: str) -> Optional[int]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
