"""Scan ingress + mode read endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import scan as scan_pipeline
from .. import state as state_manager
from ..models import AppState, ScanResult

router = APIRouter(prefix="/api", tags=["scan"])


class ScanRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=128)


@router.post("/scan", response_model=ScanResult)
async def post_scan(payload: ScanRequest) -> ScanResult:
    return await scan_pipeline.dispatch(payload.code)


@router.get("/mode", response_model=AppState)
async def get_mode() -> AppState:
    await state_manager.initialise()
    return await state_manager.get()
