"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__, audit, control_sheet, dashboard, state
from .auth import BearerTokenMiddleware
from .config import get_settings
from .routers import backup, catalogue, ha, health, notifications, scan
from .routers import inventory as inventory_router

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # eager-load config; ensures data dirs exist
    await state.initialise()
    await audit.log("app_start", version=__version__)
    yield
    await audit.log("app_stop", version=__version__)


app = FastAPI(
    title="BleepStash",
    description="Barcode-driven preparedness inventory manager.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(BearerTokenMiddleware)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Expose the Jinja templates instance to routers via app.state so we don't
# create circular imports.
app.state.templates = templates

app.include_router(health.router)
app.include_router(scan.router)
app.include_router(notifications.router)
app.include_router(ha.router)
app.include_router(backup.router)
app.include_router(catalogue.router)
app.include_router(inventory_router.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    current = await state.get()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"state": current, "version": __version__},
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    current = await state.get()
    summary = await dashboard.summary()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"state": current, "version": __version__, "summary": summary},
    )


@app.get("/control-sheet", response_class=HTMLResponse)
async def control_sheet_page(
    request: Request,
    symbology: str = "qr",
) -> HTMLResponse:
    if symbology not in (control_sheet.SYMBOLOGY_QR, control_sheet.SYMBOLOGY_CODE128):
        symbology = control_sheet.DEFAULT_SYMBOLOGY
    sections = control_sheet.build_sections(symbology=symbology)
    return templates.TemplateResponse(
        request,
        "control_sheet.html",
        {
            "version": __version__,
            "sections": sections,
            "symbology": symbology,
        },
    )


@app.get("/control-sheet/print", response_class=HTMLResponse)
async def control_sheet_print(
    request: Request,
    symbology: str = "qr",
) -> HTMLResponse:
    """Chromeless, dense-grid version tuned to maximise codes per A4 page."""
    if symbology not in (control_sheet.SYMBOLOGY_QR, control_sheet.SYMBOLOGY_CODE128):
        symbology = control_sheet.DEFAULT_SYMBOLOGY
    sections = control_sheet.build_sections(symbology=symbology)
    total = sum(len(s["entries"]) for s in sections)
    return templates.TemplateResponse(
        request,
        "control_sheet_print.html",
        {
            "version": __version__,
            "sections": sections,
            "symbology": symbology,
            "total": total,
        },
    )
