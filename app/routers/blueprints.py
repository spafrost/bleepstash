"""Blueprint HTML + JSON API routes."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import __version__
from .. import blueprints as blueprints_mod
from .. import state as state_manager

router = APIRouter(tags=["blueprints"])


def _get_templates(request: Request):
    return request.app.state.templates


async def _base_context() -> dict:
    return {"state": await state_manager.get(), "version": __version__}


# ---- HTML routes ----

@router.get("/blueprints", response_class=HTMLResponse)
async def list_page(request: Request) -> HTMLResponse:
    all_ = await blueprints_mod.list_all()
    st = await state_manager.get()
    rows = []
    for bp_id, bp in all_.items():
        f = await blueprints_mod.compute_fulfilment(bp_id)
        rows.append({
            "id": bp_id,
            "name": bp.name,
            "description": bp.description,
            "slot_count": len(bp.slots),
            "totals": f["totals"] if f else None,
            "is_active": st.active_blueprint_id == bp_id,
        })
    rows.sort(key=lambda r: (not r["is_active"], r["name"].lower()))
    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "blueprints.html",
        {**await _base_context(), "blueprints": rows},
    )


@router.get("/blueprints/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    templates = _get_templates(request)
    return templates.TemplateResponse(
        request, "blueprint_new.html", await _base_context()
    )


@router.post("/blueprints", response_class=HTMLResponse)
async def create_blueprint(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    bp = await blueprints_mod.create(name, description.strip())
    return RedirectResponse(url=f"/blueprints/{bp.id}", status_code=303)


@router.post("/blueprints/deactivate", response_class=HTMLResponse)
async def deactivate_current(request: Request) -> HTMLResponse:
    await blueprints_mod.deactivate()
    return RedirectResponse(url="/blueprints", status_code=303)


@router.get("/blueprints/{blueprint_id}", response_class=HTMLResponse)
async def detail_page(request: Request, blueprint_id: str) -> HTMLResponse:
    f = await blueprints_mod.compute_fulfilment(blueprint_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"No blueprint {blueprint_id}")
    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "blueprint_detail.html",
        {**await _base_context(), "f": f},
    )


@router.post("/blueprints/{blueprint_id}", response_class=HTMLResponse)
async def update_blueprint(
    request: Request,
    blueprint_id: str,
    name: str = Form(...),
    description: str = Form(""),
) -> HTMLResponse:
    updated = await blueprints_mod.update(
        blueprint_id, name=name.strip() or None, description=description.strip()
    )
    if updated is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/blueprints/{blueprint_id}", status_code=303)


@router.post("/blueprints/{blueprint_id}/delete", response_class=HTMLResponse)
async def delete_blueprint(request: Request, blueprint_id: str) -> HTMLResponse:
    if not await blueprints_mod.delete(blueprint_id):
        raise HTTPException(status_code=404)
    return RedirectResponse(url="/blueprints", status_code=303)


@router.post("/blueprints/{blueprint_id}/activate", response_class=HTMLResponse)
async def activate_blueprint(request: Request, blueprint_id: str) -> HTMLResponse:
    if not await blueprints_mod.activate(blueprint_id):
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/blueprints/{blueprint_id}", status_code=303)


@router.post("/blueprints/{blueprint_id}/slots", response_class=HTMLResponse)
async def add_slot(
    request: Request,
    blueprint_id: str,
    label: str = Form(...),
    required_qty: int = Form(1),
    accepted_eans: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    eans = [e for e in (accepted_eans or "").splitlines() if e.strip()]
    slot = await blueprints_mod.add_slot(
        blueprint_id,
        label=label.strip(),
        required_qty=required_qty,
        accepted_eans=eans,
        notes=notes.strip(),
    )
    if slot is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/blueprints/{blueprint_id}", status_code=303)


@router.post("/blueprints/{blueprint_id}/slots/{slot_id}", response_class=HTMLResponse)
async def edit_slot(
    request: Request,
    blueprint_id: str,
    slot_id: str,
    label: str = Form(...),
    required_qty: int = Form(1),
    accepted_eans: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    eans = [e for e in (accepted_eans or "").splitlines() if e.strip()]
    updated = await blueprints_mod.update_slot(
        blueprint_id,
        slot_id,
        label=label.strip(),
        required_qty=required_qty,
        accepted_eans=eans,
        notes=notes.strip(),
    )
    if updated is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/blueprints/{blueprint_id}", status_code=303)


@router.post("/blueprints/{blueprint_id}/slots/{slot_id}/delete", response_class=HTMLResponse)
async def delete_slot(
    request: Request, blueprint_id: str, slot_id: str
) -> HTMLResponse:
    if not await blueprints_mod.delete_slot(blueprint_id, slot_id):
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/blueprints/{blueprint_id}", status_code=303)


# ---- JSON API ----

@router.get("/api/blueprints")
async def api_list():
    all_ = await blueprints_mod.list_all()
    return [
        {
            "id": bp.id,
            "name": bp.name,
            "description": bp.description,
            "slot_count": len(bp.slots),
        }
        for bp in all_.values()
    ]


@router.get("/api/blueprints/current")
async def api_current():
    st = await state_manager.get()
    if not st.active_blueprint_id:
        return None
    return await blueprints_mod.compute_fulfilment(st.active_blueprint_id)


@router.get("/api/blueprints/{blueprint_id}")
async def api_detail(blueprint_id: str):
    f = await blueprints_mod.compute_fulfilment(blueprint_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"No blueprint {blueprint_id}")
    return f
