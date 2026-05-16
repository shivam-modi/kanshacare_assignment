# ingestion-svc

Pulls USGS earthquake events into MongoDB.

## Responsibility

| | |
|---|---|
| Inputs | USGS `all_hour.geojson` (every 60s) and `all_month.geojson` (once, on first boot) |
| Outputs | `events` collection (upsert by USGS id), `system_health` collection (one row per poll) |
| Public surface | `/healthz`, `/readyz`, `/metrics` — no business endpoints (write-only service) |

## Run locally

```bash
docker compose up ingestion
# or natively:
uv sync --all-packages --dev
uv run --package kanshacare-ingestion uvicorn ingestion_app.main:app --reload --port 8000 --app-dir services/ingestion
```

## Env vars

See root `.env.example`. Service-specific:

- `USGS_POLL_INTERVAL_SECONDS` (default 60)
- `USGS_BACKFILL_ON_BOOT` (default true; set false on subsequent runs to skip backfill)
- `USGS_REQUEST_TIMEOUT_SECONDS` (default 10)

## Operational notes

- Backfill is idempotent; safe to leave `USGS_BACKFILL_ON_BOOT=true` (it short-circuits if `events` collection is non-empty).
- The 60s poll interval matches USGS's server-side cache. Polling faster is wasted.
- Malformed features land in `events_quarantine` rather than crashing the poller.
- Every poll outcome is logged to `system_health` so the dashboard's System Health card has real data even on the very first poll.
