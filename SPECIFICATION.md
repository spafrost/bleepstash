# BleepStash — Preparedness Inventory Specification

**Version:** 0.1 (draft)
**Date:** 2026-08-28
**Purpose:** A barcode-driven inventory manager for household emergency food stores, aligned with civil preparedness guidance (e.g. the Swedish MSB *Om krisen eller kriget kommer* stockpile model).

---

## 1. Goals & Non-Goals

### Goals
- Track a household stockpile of shelf-stable food with **best-before dates** and **stock levels**.
- Enable **hands-free-ish** operation via a USB/Bluetooth barcode scanner plus printed **Control Barcode** sheets — no keyboard/mouse required for routine use.
- Surface **oldest-first (FIFO) consumption** guidance and expiry warnings.
- Expose an **API** so Home Assistant can read stock/expiry state and raise alerts.
- Run as a **single Docker container** with **JSON flat-file storage** — trivially backed up, no database dependency.

### Non-Goals (v1)
- Multi-household / multi-user auth (single-tenant, LAN-only assumed).
- Nutritional analysis, recipe planning, shopping list generation.
- Barcode *printing* of individual items (we consume commercial EAN/UPC barcodes on packaging).
- Cloud sync.

---

## 2. Core Concepts

| Term | Definition |
|---|---|
| **Product** | An abstract SKU identified by its retail barcode (EAN‑13 / UPC‑A). Holds metadata: name, weight, manufacturer, category, default shelf‑life. |
| **Stock Item** | A physical unit in the stash. Belongs to a Product. Has an individual best‑before date and a status (`in_stock`, `consumed`, `expired`, `discarded`). |
| **Control Barcode** | A special barcode printed on the operator's control sheets. Not an EAN — uses a distinct prefix so the app can tell it apart from a product scan. |
| **Mode** | The app's global operating state, set by a Control Barcode. Determines how the next product scan is interpreted. |

---

## 3. Global Modes

The app is always in exactly one mode. The mode is set by scanning a Mode control barcode and **persists indefinitely** — across page reloads, container restarts, and idle time — until another Mode control barcode is scanned. There is no auto-reset and no "neutral" state; the last mode chosen is the mode the next scan will act on.

Default mode on **first ever startup** (before any control barcode has been scanned) is `CONSUME`, on the assumption that day-to-day use dominates.

| Mode | Purpose | Product-scan behaviour |
|---|---|---|
| **`ADD`** | Register new stock arriving in the stash. | Prompts for best‑before via year+month control scans, then creates a new Stock Item. |
| **`CONSUME`** | Log usage of an item from the stash (eaten / used as intended). | Marks the **oldest in-stock unit** of that Product as `consumed`. |
| **`DISCARD`** | Log an item removed for waste reasons (spoiled, damaged, past expiry and unsafe). | Marks the **oldest in-stock unit** of that Product as `discarded`. Kept distinct from CONSUME so waste rates are measurable. |
| **`INVENTORY`** | Full stocktake / reconciliation. | Scans build up a live count; on completion, the system compares to recorded stock and produces a variance report. |
| **`LOOKUP`** | Info-only. | Scans display product & stock info without changing state. Useful for "what have I got and when does it expire?" |

Mode changes are audit-logged. The current mode is prominently displayed on every UI screen so the operator can't lose track.

---

## 4. Control Barcode Sheets

Control barcodes use **Code 128** with a reserved prefix `^CTRL^` so the parser can distinguish them from product EANs.

### 4.1 Mode Sheet
| Barcode value | Action |
|---|---|
| `^CTRL^MODE:ADD` | Enter ADD mode |
| `^CTRL^MODE:CONSUME` | Enter CONSUME mode |
| `^CTRL^MODE:DISCARD` | Enter DISCARD mode |
| `^CTRL^MODE:INVENTORY` | Start a new INVENTORY session |
| `^CTRL^MODE:LOOKUP` | Enter LOOKUP mode |

### 4.2 Date Sheet (used in ADD mode)
| Barcode value | Meaning |
|---|---|
| `^CTRL^YEAR:2026` … `^CTRL^YEAR:2035` | Year selector (10 years published on sheet) |
| `^CTRL^MONTH:01` … `^CTRL^MONTH:12` | Month selector |
| `^CTRL^DAY:END` | Shortcut: use last day of chosen month (default) |
| `^CTRL^DAY:01` … `^CTRL^DAY:31` | Optional day precision |

### 4.3 Action Sheet
| Barcode value | Action |
|---|---|
| `^CTRL^ACTION:CANCEL` | Abort current entry (e.g. wrong date scanned) |
| `^CTRL^ACTION:CONFIRM` | Confirm a pending action |
| `^CTRL^ACTION:UNDO` | Undo the last state change (single-step) |
| `^CTRL^ACTION:FINISH` | End an INVENTORY session and produce report |
| `^CTRL^ACTION:QTY:+N` | For ADD: repeat next entry N times (e.g. a case of 6) |

The **Control Sheet PDF** is a printable artifact the app can regenerate on demand from `/control-sheet.pdf`.

---

## 5. User Flows

### 5.1 Adding Products
```
1. Scan ^CTRL^MODE:ADD          → app enters ADD mode
2. Scan product EAN             → app looks up product
                                    - Known?   show name, prompt for BBE
                                    - Unknown? prompt "New product" — capture name/weight/mfr
                                               (fallback: external barcode DB lookup, then manual override)
3. Scan ^CTRL^YEAR:2027         → year = 2027
4. Scan ^CTRL^MONTH:03          → month = March, day defaults to 31
   (optional: ^CTRL^DAY:15 for finer precision)
5. Optional: ^CTRL^ACTION:QTY:+6 before step 2 to add a case of 6
6. Stock item(s) created; app stays in ADD, ready for next product
```

### 5.2 Consuming Products
```
1. Scan ^CTRL^MODE:CONSUME      → app enters CONSUME mode (if not already)
2. Scan product EAN             → app marks the OLDEST in-stock unit as consumed
3. Repeat for each item consumed
```
No "exit" scan is needed — CONSUME is the assumed default for routine household use, so the app simply stays in CONSUME until a different Mode control barcode is scanned.
If no in-stock units exist, the app emits an error tone and shows the shortfall.

### 5.3 Discarding Products
```
1. Scan ^CTRL^MODE:DISCARD      → app enters DISCARD mode
2. Scan product EAN             → app marks the OLDEST in-stock unit as discarded
3. Repeat for each item to discard
```
Functionally identical to CONSUME, but the resulting stock status is `discarded` — this lets the dashboard compute a **waste rate** and helps identify products that repeatedly go off before being eaten (i.e. rotation isn't working).

### 5.4 Regular Inventory
```
1. Scan ^CTRL^MODE:INVENTORY    → new session opens, counter = {}
2. Scan every product in the stash, one unit at a time
                                    - Duplicate EAN scans increment a counter
                                    - Unknown EANs are flagged for later handling
3. Scan ^CTRL^ACTION:FINISH     → report:
                                    - matches (product X: expected 4, counted 4)
                                    - shortfalls (expected 3, counted 2 → 1 missing)
                                    - surpluses (expected 0, counted 2 → 2 unrecorded)
                                    - expired items still in stash
4. Operator resolves variances via ADD / CONSUME / DISCARD as appropriate
```
Inventory sessions are **non-destructive** — they generate a report but do not auto-mutate stock. The operator applies fixes explicitly.

### 5.5 Lookup
```
1. Scan ^CTRL^MODE:LOOKUP
2. Scan product EAN             → shows: product info, all in-stock units with BBE dates,
                                          next expiry, total household days-of-supply
```

---

## 6. Data Model (JSON on disk)

Storage layout under `/data`:
```
/data
  ├── products.json        # SKU catalogue keyed by EAN
  ├── stock.json           # Individual stock items (append-mostly log)
  ├── sessions.json        # Inventory session records
  ├── notifications.json   # In-app notifications (bell icon feed)
  ├── audit.json           # Append-only audit log (mode changes, scans, mutations)
  ├── config.json          # App settings (warning thresholds, category defaults, default location)
  └── backups/             # Timestamped auto-snapshots (kept N=30)
```

### 6.1 `products.json`
```json
{
  "7310865004703": {
    "ean": "7310865004703",
    "name": "ICA Basic Krossade Tomater",
    "manufacturer": "ICA",
    "weight_g": 400,
    "category": "canned_veg",
    "default_shelf_life_months": 24,
    "created_at": "2026-08-28T08:30:00Z",
    "updated_at": "2026-08-28T08:30:00Z"
  }
}
```

### 6.2 `stock.json`
```json
{
  "items": [
    {
      "id": "stk_01HXYZ...",           // ULID
      "ean": "7310865004703",
      "best_before": "2028-03-31",
      "status": "in_stock",             // in_stock | consumed | discarded | expired
      "location": "pantry",             // nullable; freeform, autocompleted from prior entries
      "added_at": "2026-08-28T08:31:00Z",
      "consumed_at": null,              // set when status transitions to consumed or discarded
      "notes": null
    }
  ]
}
```
Statuses:
- `in_stock` — physically present, within date.
- `consumed` — used as intended (CONSUME mode).
- `discarded` — thrown away (DISCARD mode). Feeds waste-rate metrics.
- `expired` — computed dynamically from `best_before < today` **while still `in_stock`**; not written back to disk (kept as a derived flag) so a single scan can move an expired item straight to `discarded`.

### 6.3 `audit.json` (append-only)
```json
{"ts":"2026-08-28T08:30:12Z","event":"mode_change","from":"IDLE","to":"ADD"}
{"ts":"2026-08-28T08:30:18Z","event":"stock_add","stock_id":"stk_01H...","ean":"7310865004703","bbe":"2028-03-31"}
{"ts":"2026-08-28T08:32:04Z","event":"stock_consume","stock_id":"stk_01H...","ean":"7310865004703"}
```

### 6.4 Concurrency & Integrity
- Writes go through a single in-process **write queue** with atomic rename (`write to tmp → fsync → rename`).
- Every mutation triggers a rolling backup snapshot to `/data/backups/`.
- Startup: validate JSON schema; if corrupt, halt and refuse to overwrite (surface via API + red banner on UI).

---

## 7. Frontend

- **Static HTML + minimal JS** (no heavy framework). Vanilla + a small progressive-enhancement layer (Alpine.js or htmx — TBD, leaning **htmx** for server-driven simplicity).
- **Kiosk-friendly layout:** large fonts, high contrast, big status banner showing current MODE and any pending action.
- **Audio feedback:** distinct tones for *accepted*, *rejected*, *needs-attention*.
- **Scanner input:** a hidden always-focused `<input>` captures keyboard-emulation scanner input; buffered until CR/LF terminator.
- **Screens:**
  1. **Dashboard** — current mode, next 10 expiring items, category coverage, waste-rate widget, "days of supply" tiles (post-v1).
  2. **Catalogue** — searchable product list; edit product metadata.
  3. **Stock** — filter by product, status, expiry window, **location**; manual admin edits (with audit reason).
  4. **Inventory Sessions** — history + report viewer.
  5. **Settings** — thresholds, printer/control sheet download, backup management, default location.
  6. **Audit Log** — recent activity, filterable.
- **Notifications:** a **bell icon** in the top-right of every screen with an unread-count badge. Clicking opens a dismissable list of notifications generated by the app itself — no external delivery required.
  - Notification triggers (all configurable in `config.json` warning thresholds):
    - Item newly crossed an expiry threshold (30-day / 90-day / expired).
    - Unknown EAN scanned (needs product metadata).
    - Inventory session finished with variances.
    - Backup failed, disk full, JSON schema drift, etc.
  - Each notification: `id`, `created_at`, `severity` (`info`/`warn`/`error`), `title`, `body`, `dismissed_at`, optional `link` (deep-link into the relevant stock/product page).
  - Bell shows unread count; list supports individual dismiss + "dismiss all".
  - Notifications are persisted in `notifications.json` (see §6) so they survive restarts.

---

## 8. HTTP API

All endpoints return JSON. `Content-Type: application/json`. Auth: **optional bearer token** in `config.json` (off by default for LAN use; recommended when exposing to HA over network).

### 8.1 Scanner ingress
- `POST /api/scan` — body `{ "code": "7310865004703" }`. Server interprets against current mode. Returns `{ "result": "...", "mode": "ADD", "pending": {...} }`.

### 8.2 State
- `GET /api/mode` — current mode + any pending entry (read-only).

> **Note:** Mode is intentionally **not** settable via API. The mode is a physical-workflow signal and can only be changed by scanning a Mode control barcode. This keeps a single source of truth for operator intent and prevents remote systems from silently reinterpreting scans.

### 8.3 Products
- `GET /api/products` — list.
- `GET /api/products/{ean}`
- `PUT /api/products/{ean}` — upsert.
- `DELETE /api/products/{ean}` — only if no in-stock items.

### 8.4 Stock
- `GET /api/stock?ean=&status=&expires_before=&expires_within_days=`
- `GET /api/stock/{id}`
- `POST /api/stock` — manual add.
- `PATCH /api/stock/{id}` — status/notes edits (audited).
- `GET /api/stock/summary` — aggregates: totals per category, next expiries, days-of-supply.

### 8.5 Inventory sessions
- `POST /api/inventory` — start.
- `POST /api/inventory/{id}/scan` — record a count.
- `POST /api/inventory/{id}/finish` — close & get report.
- `GET /api/inventory/{id}` — fetch report.

### 8.6 Home Assistant helpers
- `GET /api/ha/sensors` — pre-shaped payload with the values HA cares about:
  ```json
  {
    "total_items": 87,
    "expired_count": 2,
    "expiring_30d_count": 5,
    "expiring_90d_count": 14,
    "days_of_supply": 21,
    "current_mode": "CONSUME",
    "next_expiry_date": "2026-09-15",
    "categories": { "canned_veg": {"items": 22, "days": 14}, ... }
  }
  ```
- `GET /api/ha/expiring?within_days=30` — list.
- **Webhook out (optional):** `config.json` can specify a URL to POST when expiry thresholds are crossed.

### 8.7 Notifications
- `GET /api/notifications?include_dismissed=false` — list.
- `POST /api/notifications/{id}/dismiss` — dismiss one.
- `POST /api/notifications/dismiss-all` — dismiss all currently visible.

The notifications endpoint powers the in-app bell icon and is also useful to HA (e.g. mirror unread count as a sensor).

### 8.8 Admin
- `GET /control-sheet.pdf` — regenerate & download printable sheets.
- `POST /api/backup` — force a snapshot.
- `GET /api/audit?since=`
- `GET /healthz`

---

## 9. Product Lookup

Order of precedence when a new EAN is scanned in ADD mode:

1. **Local `products.json`** — instant, offline.
2. **Optional external lookup** (configurable in `config.json`, off by default for privacy):
   - Open Food Facts API (`https://world.openfoodfacts.org/api/v2/product/{ean}.json`) — best fit, product data, weight, brand.
   - Fallback: UPCitemdb / Barcode Lookup (require API keys).
3. **Manual entry** via web UI — always available; the "add product" form pops on the kiosk display.

New products captured this way are written to `products.json` for future offline use.

---

## 10. Home Assistant Integration

Suggested pattern (documented in `README.md` post-build):
- Configure a **RESTful sensor** in HA pointing at `/api/ha/sensors`, scan every 5–15 min.
- Template sensors expose individual attributes (expired count, days-of-supply, etc.).
- Automations:
  - Notify when `expiring_30d_count` > 0.
  - Warn when `days_of_supply` < preparedness target (default 7 days per Swedish guidance; MSB currently recommends 7+).

HA is **read-only** with respect to BleepStash state. Mode changes are strictly a scanner-driven, physical-workflow action — HA gets to observe and alert, not steer.

---

## 11. Deployment

### 11.1 Container
- Single image, target `linux/amd64` and `linux/arm64` (Raspberry Pi friendly).
- Base: `python:3.12-slim`.
- Stack: **FastAPI** (async HTTP + auto-generated OpenAPI), **Jinja2** templates rendered server-side, **htmx** for progressive interactivity, **Pydantic** for schema validation of both API payloads and on-disk JSON.
- Exposes port `8080`.
- Volume: `/data` (persistent).

### 11.2 `docker-compose.yml` (example)
```yaml
services:
  bleepstash:
    image: bleepstash:latest
    container_name: bleepstash
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - BS_TZ=Europe/London
      - BS_AUTH_TOKEN=              # blank = no auth
      - BS_EXTERNAL_LOOKUP=off      # on|off
      - BS_WARN_DAYS=30,90
```

### 11.3 Backups
- Hourly diff snapshot to `/data/backups/`.
- Retention: 30 rolling snapshots + weekly for 12 weeks.
- User can pull `/api/backup` on demand.

---

## 12. Non-Functional Requirements

| Aspect | Target |
|---|---|
| **Startup time** | < 3 s to serving requests |
| **Scan-to-feedback latency** | < 150 ms on Raspberry Pi 4 |
| **Storage footprint** | < 10 MB for 1,000 stock items |
| **Concurrency** | Single-user optimistic; write queue serialises mutations |
| **Offline** | Fully functional without internet (external lookup optional) |
| **Portability** | Runs on any Docker host including HA OS add-on scenario |

---

## 13. Open Questions

All v1-blocking questions resolved. Post-v1 backlog items now tracked separately:

1. ~~**Stack choice**~~ — **Resolved:** Python 3.12 + FastAPI + Jinja2 + htmx + Pydantic.
2. ~~**PDF generation**~~ — **Resolved:** WeasyPrint rendering a Jinja HTML template, with `python-barcode` producing inline SVG barcodes.
3. ~~**HA add-on packaging**~~ — **Deferred** to post-v1. Standalone Docker image only for now.
4. ~~**Multi-location**~~ — **Resolved:** nullable `location` string on Stock Items from v1, freeform with autocomplete from prior entries. Default configurable.
5. ~~**Consume vs discard**~~ — **Resolved:** modelled as a distinct `DISCARD` **mode** (not a per-scan reason flag). Cleaner, no extra scan per item.
6. ~~**Alerting**~~ — **Resolved:** in-app notification bell + dismissable list, persisted to `notifications.json`. External delivery remains available via the optional outbound webhook and HA polling `/api/notifications`.
7. **Preparedness target (days-of-supply, household composition, per-product kcal)** — **Deferred** to post-v1. Big enough to warrant its own spec pass and depends on kcal/serving data quality.

---

## 14. Suggested v1 Milestones

1. **M1 — Skeleton**: Docker image (FastAPI on `python:3.12-slim`), JSON storage layer with atomic writes, `/healthz`, static index page.
2. **M2 — Scan pipeline**: `/api/scan`, mode state machine (`ADD`/`CONSUME`/`DISCARD`/`INVENTORY`/`LOOKUP`), control-barcode parser.
3. **M3 — ADD flow**: product create/lookup, BBE via control sheet, stock item creation with location.
4. **M4 — CONSUME + DISCARD flows**: FIFO stock resolution, tones, undo.
5. **M5 — INVENTORY flow**: session, report, variance UI.
6. **M6 — Dashboard, expiry views & notification bell**: htmx pages, notifications feed, HA sensors endpoint.
7. **M7 — Control-sheet PDF generator (WeasyPrint) + HA integration doc**.
8. **M8 — Polish**: backups, auth token, external product lookup toggle, waste-rate widget.
