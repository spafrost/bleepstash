"""Inventory HTML + API routes.

- ``GET /inventory`` — live view of the active session, or a landing page
  showing past sessions when idle.
- ``GET /inventory/{session_id}`` — post-FINISH read-only report page.
- ``GET /api/inventory/current`` — JSON snapshot of the active session, or
  ``null`` when no session is active. Polled by the /inventory page every 5 s.
- ``GET /api/inventory/{session_id}`` — JSON snapshot of any session.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import __version__
from .. import inventory as inventory_mod
from .. import state as state_manager
from .. import storage

router = APIRouter(tags=["inventory"])


def _get_templates(request: Request):
    return request.app.state.templates


async def _base_context() -> dict:
    return {"state": await state_manager.get(), "version": __version__}


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request) -> HTMLResponse:
    st = await state_manager.get()
    templates = _get_templates(request)
    snapshot = None
    if st.active_inventory_id:
        snapshot = await inventory_mod.snapshot(st.active_inventory_id)

    sessions = await storage.load_sessions()
    past = [
        {
            "id": s.id,
            "started_at": s.started_at.isoformat(),
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        }
        for s in sessions.values()
        if s.finished_at is not None
    ]
    past.sort(key=lambda p: p["finished_at"] or "", reverse=True)

    return templates.TemplateResponse(
        request,
        "inventory.html",
        {**await _base_context(), "snapshot": snapshot, "past_sessions": past[:10]},
    )


@router.get("/inventory/{session_id}", response_class=HTMLResponse)
async def inventory_report_page(request: Request, session_id: str) -> HTMLResponse:
    templates = _get_templates(request)
    snapshot = await inventory_mod.snapshot(session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No session {session_id}")
    return templates.TemplateResponse(
        request,
        "inventory_report.html",
        {**await _base_context(), "snapshot": snapshot},
    )


# ---- JSON API ----

@router.get("/api/inventory/current")
async def api_current():
    st = await state_manager.get()
    if not st.active_inventory_id:
        return None
    return await inventory_mod.snapshot(st.active_inventory_id)


@router.get("/api/inventory/{session_id}")
async def api_session(session_id: str):
    snapshot = await inventory_mod.snapshot(session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No session {session_id}")
    return snapshot
