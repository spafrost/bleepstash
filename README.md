# BleepStash

Barcode-driven preparedness inventory manager. See [SPECIFICATION.md](./SPECIFICATION.md) for the full design.

## Quick start (dev)

```bash
docker compose up --build
```

Then open http://localhost:8080/.

## Current state

- **M1** — Skeleton (Docker, storage layer, `/healthz`, static index) ✅
- **M2** — Scan pipeline, mode state machine, control-barcode parser ✅
- M3+ — see spec §14

## Testing a scan

```bash
# Change mode
curl -X POST http://localhost:8080/api/scan \
  -H 'Content-Type: application/json' \
  -d '{"code":"^CTRL^MODE:ADD"}'

# Check current mode
curl http://localhost:8080/api/mode
```

## Data layout

Everything lives in the mounted `./data` volume. See spec §6.
