"""Control-sheet barcode generator.

Produces the list of barcode intents defined by the spec (§4) and renders each
as an inline SVG. Two symbologies are supported:

- ``code128`` — linear 1D via ``python-barcode``. Universally scanner-friendly
  but wide for long payloads (up to ~120 mm for ``^CTRL^ACTION:CONFIRM``).
- ``qr`` — 2D via ``segno``. Compact (~15–25 mm square regardless of payload
  length) but requires a 2D-capable scanner (Tera D5100 and similar).

The sheet defaults to QR. Add ``?symbology=code128`` to the URL to fall back.

WeasyPrint-based ``/control-sheet.pdf`` is deferred until the containerised
runtime ships the required system libs (M7 dockerisation).
"""
from __future__ import annotations

import io
from typing import Callable, List

import barcode
import segno
from barcode.writer import SVGWriter

from .models import Mode

_CODE128_WRITER_OPTIONS = {
    "write_text": False,
    "module_width": 0.45,
    "module_height": 15.0,
    "quiet_zone": 3.5,
}

_QR_SCALE = 4
_QR_BORDER = 2
_QR_ERROR = "m"  # ~15% recovery — comfortable margin for kitchen-grade printers

SYMBOLOGY_CODE128 = "code128"
SYMBOLOGY_QR = "qr"
DEFAULT_SYMBOLOGY = SYMBOLOGY_QR


def make_svg(code: str, symbology: str = DEFAULT_SYMBOLOGY) -> str:
    """Render ``code`` as an inline-embeddable SVG string (no XML decl)."""
    if symbology == SYMBOLOGY_QR:
        return _make_qr_svg(code)
    if symbology == SYMBOLOGY_CODE128:
        return _make_code128_svg(code)
    raise ValueError(f"Unknown symbology: {symbology!r}")


def _make_code128_svg(code: str) -> str:
    Code128 = barcode.get_barcode_class("code128")
    bc = Code128(code, writer=SVGWriter())
    raw = bc.render(writer_options=_CODE128_WRITER_OPTIONS).decode("utf-8")
    start = raw.find("<svg")
    return raw[start:] if start != -1 else raw


def _make_qr_svg(code: str) -> str:
    qr = segno.make(code, error=_QR_ERROR)
    buf = io.BytesIO()
    qr.save(
        buf,
        kind="svg",
        scale=_QR_SCALE,
        border=_QR_BORDER,
        dark="#000",
        light="#fff",
        xmldecl=False,
        svgns=False,
        omitsize=False,
    )
    svg = buf.getvalue().decode("utf-8")
    # Inject a viewBox so the SVG scales cleanly inside CSS-constrained
    # containers (e.g. the dense print grid). Without it, browsers use the
    # intrinsic pixel width/height and can clip when the container is smaller.
    if "viewBox=" not in svg:
        import re
        m = re.search(r'<svg\b[^>]*\bwidth="([^"]+)"[^>]*\bheight="([^"]+)"', svg)
        if m:
            w, h = m.group(1), m.group(2)
            svg = svg.replace(
                "<svg",
                f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet"',
                1,
            )
    return svg


def build_sections(symbology: str = DEFAULT_SYMBOLOGY) -> List[dict]:
    """Return the list of sections that populate the control sheet template."""
    render: Callable[[str], str] = lambda code: make_svg(code, symbology)
    sections: List[dict] = []

    sections.append(_section(
        "MODE",
        "Mode changes take effect immediately and persist until re-scanned.",
        [
            (f"^CTRL^MODE:{mode.value}", mode.value, f"MODE {mode.value}")
            for mode in Mode
        ],
        render,
    ))

    sections.append(_section(
        "YEAR",
        "Scan while in ADD mode to set the best-before year of the pending entry.",
        [
            (f"^CTRL^YEAR:{year}", str(year), f"YEAR {year}")
            for year in range(2026, 2036)
        ],
        render,
    ))

    sections.append(_section(
        "MONTH",
        "Scan while in ADD mode to set the best-before month; auto-commits the entry with best-before = end of that month.",
        [
            (f"^CTRL^MONTH:{month:02d}", f"{month:02d}", _month_name(month))
            for month in range(1, 13)
        ],
        render,
    ))

    sections.append(_section(
        "ACTION",
        "General control actions.",
        [
            ("^CTRL^ACTION:CANCEL", "CANCEL", "Cancel pending ADD entry"),
            ("^CTRL^ACTION:CONFIRM", "CONFIRM", "Force-commit a ready ADD entry"),
            ("^CTRL^ACTION:UNDO", "UNDO", "Reverse last stock mutation"),
            ("^CTRL^ACTION:FINISH", "FINISH", "Close active inventory session"),
        ],
        render,
    ))

    sections.append(_section(
        "QTY",
        "Applies to the NEXT ADD entry only, then resets to 1.",
        [
            (f"^CTRL^ACTION:QTY:+{n}", f"×{n}", f"Next entry recorded {n}× ")
            for n in (2, 3, 4, 5, 6, 8, 10, 12, 24)
        ],
        render,
    ))

    return sections


def _section(name: str, hint: str, entries: List[tuple], render: Callable[[str], str]) -> dict:
    return {
        "name": name,
        "hint": hint,
        "entries": [
            {"code": code, "label": label, "human": human, "svg": render(code)}
            for code, label, human in entries
        ],
    }


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _month_name(month: int) -> str:
    return _MONTH_NAMES[month - 1]
