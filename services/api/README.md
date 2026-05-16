# api-svc

Read-side REST API + SSE stream for the Next.js dashboard. Also accepts the on-demand summary request and enqueues it into Redis for `worker-svc`.

## Endpoints (planned, Phase 3)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/events`                       | Global event feed (window, magnitude filter) |
| GET  | `/events/near`                  | Events within `radius_km` of `lat,lon` |
| GET  | `/events/stream`                | SSE — pushes new events as they arrive (Mongo change stream) |
| GET  | `/locations`                    | List user-selected locations (cap 3) |
| POST | `/locations`                    | Create location (geocoded or raw lat/lon) |
| DELETE | `/locations/{id}`             | Remove location |
| GET  | `/locations/{id}/summary`       | Risk score, 24h/7d/30d counts, largest event, thresholds |
| GET  | `/system/health`                | Aggregated dashboard health card data |
| POST | `/summaries/request`            | Enqueue an on-demand Telegram summary (returns 202) |
| GET  | `/summaries/{job_id}`           | Check job status |

## Run locally

```bash
docker compose up api
# or natively:
uv run --package kanshacare-api uvicorn api_app.main:app --reload --port 8001 --app-dir services/api
```

OpenAPI: http://localhost:8001/docs
