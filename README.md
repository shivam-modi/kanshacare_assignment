# Kansha Care — Earthquake Telemetry

A continuous-feed ingestion, monitoring, and alerting system built on the USGS earthquake GeoJSON feeds. Modelled after the elder-care production system Kansha Care is building: sensor ingestion, anomaly detection, multi-channel alerting, observability.

## Submission

| | |
|---|---|
| Dashboard | <https://kanshacare-web.fly.dev> |
| Telegram bot | [@Kanshacare_bot](https://t.me/Kanshacare_bot) — send `/start` to subscribe, `/summary` for an on-demand digest |
| API health | <https://kanshacare-api.fly.dev/system/health> |
| Architecture doc | [ARCHITECTURE.md](./ARCHITECTURE.md) — 2 pages, evaluation-ready |
| Deploy guide | [infra/README.md](./infra/README.md) |

## What this is

Four FastAPI services + an arq worker + a Next.js dashboard, backed by MongoDB Atlas and Upstash Redis, deployed on Fly.io.

```
   ┌─ ingestion-svc ─┐                 ┌── api-svc ──┐  SSE  ┌── web ──┐
   │ backfill+poller │──┐              │ REST + SSE  │◀────▶│ Next.js │
   └─────────────────┘  │              └──────▲──────┘       └─────────┘
                        │ writes              │ reads
                        ▼                     │
                ┌── MongoDB Atlas ────────────┘
                │ events / locations / system_health /
                │ alerts_log / subscribers / geocode_cache
                └──┬────────────────────────────────────┐
       change      │                                    │
       stream      ▼                                    │
                ┌── alerts-svc ──┐  enqueue   ┌── Redis ──┐
                │ rules + bot    │───────────▶│ arq queue │
                │ silence + cron │            └─────┬─────┘
                └────────────────┘                  │ consume
                                                    ▼
                                          ┌── worker-svc ──┐
                                          │ send_alert     │
                                          │ summary_job    │──▶ Telegram
                                          └────────────────┘
```

## What's covered

Every requirement in the assignment, plus the engineering surrounding it:

- **Ingestion** — one-shot backfill (idempotent via `meta.backfill_complete`) + 60s live poller. Upsert by USGS id with `properties.updated` comparison so "new" vs "updated" counts are semantically precise. Malformed features land in `events_quarantine` instead of crashing. Every poll outcome logged to `system_health`.
- **Global view** — react-leaflet map with severity-coloured markers (PAGER → mag bands, tsunami override), sortable table, 1h / 24h / 7d / 30d window selector, live SSE refresh.
- **System Health card** — always visible. Surfaces last poll, last successful poll, 1h success rate, current failure streak, backfill state. Tone derived from these.
- **Per-location view** — up to 3 locations, geocoded query OR raw lat/lon. Risk score with documented formula on the card, 24h/7d/30d counts, largest nearby event, mini-map with radius circle, literal display of active thresholds.
- **Alerts** — high-severity global (≥5.0), high-severity near (≥4.0 within 500 km of any location, per-location overrides supported), swarm (≥5 in 30 min within 200 km), source silence (>10 min). Dedup via unique index on `alerts_log.dedup_key`. Detection in alerts-svc; delivery in worker-svc with token-bucket Telegram rate limit + retries + DLQ.
- **Daily summary** — scheduled cron (env-configurable hour UTC) **and** on-demand via dashboard button or bot `/summary` command. All paths share one arq job.
- **Observability** — structured JSON logs with request-ID correlation, `/healthz` `/readyz` `/metrics` (Prometheus) on every service. `system_health` collection is the source of truth, surfaced both on the dashboard card and in the daily summary.
- **Pluggable geocoder** — `Geocoder` Protocol, Nominatim implementation, Mongo-cached. Swapping providers is a 1-file change.
- **Engineering hygiene** — 72 tests passing across 6 layers (geo math, risk scoring, USGS parsing happy + 5xx + corrupt + 304, ingestion repo upsert classification, backfill idempotency, API endpoints with `FakeMongoClient` that implements `$geoWithin $centerSphere`, alert rules + dedup + silence, Telegram message formatters, token-bucket throttling). Ruff lint + format clean. CI runs all of it on every push.

## Local development

**Prereqs:** Docker (with compose), [`uv`](https://docs.astral.sh/uv/), Node 20.

```bash
cp .env.example .env             # fill in TELEGRAM_BOT_TOKEN for the bot to work
docker compose up --build        # Mongo, Redis, 4 Python services, arq worker, web
```

Local URLs:

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| api-svc OpenAPI | http://localhost:8001/docs |
| api-svc system health | http://localhost:8001/system/health |
| ingestion-svc | http://localhost:8000/healthz |
| alerts-svc | http://localhost:8002/healthz |
| worker-svc (FastAPI sidecar) | http://localhost:8003/healthz |
| Prometheus metrics | `/metrics` on each service |

### Native (no docker)

```bash
uv sync --all-packages --all-extras
# Each service in its own terminal:
uv run --package kanshacare-ingestion uvicorn ingestion_app.main:app --reload --port 8000 --app-dir services/ingestion
uv run --package kanshacare-api       uvicorn api_app.main:app       --reload --port 8001 --app-dir services/api
uv run --package kanshacare-alerts    uvicorn alerts_app.main:app    --reload --port 8002 --app-dir services/alerts
uv run --package kanshacare-worker    uvicorn worker_app.main:app    --reload --port 8003 --app-dir services/worker
uv run --package kanshacare-worker    arq worker_app.worker.WorkerSettings
# Frontend
cd web && npm install && npm run dev
```

### Tests / lint / types

```bash
uv run pytest                      # 72 tests
uv run ruff check .
uv run ruff format --check .
cd web && npm run typecheck && npm run build
```

### Pre-commit

```bash
uv tool install pre-commit
pre-commit install
```

## Deployment

See [`infra/README.md`](./infra/README.md) for step-by-step deploy instructions (Atlas + Upstash + Telegram bot + 5 Fly apps).

```bash
# One-time per app
flyctl apps create kanshacare-ingestion
# (… and four more)

# Secrets — see infra/README.md
flyctl secrets set --app kanshacare-ingestion MONGO_URI=... REDIS_URL=... TELEGRAM_BOT_TOKEN=...

# Deploy (from repo root)
flyctl deploy -c infra/fly.ingestion.toml --remote-only
flyctl deploy -c infra/fly.api.toml       --remote-only
flyctl deploy -c infra/fly.alerts.toml    --remote-only
flyctl deploy -c infra/fly.worker.toml    --remote-only
flyctl deploy -c infra/fly.web.toml       --remote-only

# Register the Telegram webhook (alerts-svc must be up first)
curl "https://api.telegram.org/bot${TOKEN}/setWebhook" \
  -d "url=https://kanshacare-alerts.fly.dev/telegram/webhook&secret_token=${SECRET}"
```

## Repository layout

```
kanshacare/
├── shared/                          # kanshacare_shared — Pydantic models, geo, risk, logging, metrics, USGS client, geocoder
├── services/
│   ├── ingestion/                   # backfill + 60s poller + system_health writer
│   ├── api/                         # REST + SSE for dashboard + locations CRUD + summary enqueue
│   ├── alerts/                      # change-stream rule engine + Telegram webhook + silence/daily schedulers
│   └── worker/                      # arq worker: send_alert + summary_job
├── web/                             # Next.js 14 dashboard (App Router + TS + Tailwind + react-leaflet)
├── infra/                           # fly.<service>.toml + deploy guide
├── docker-compose.yml               # local dev: Mongo + Redis + all services + arq worker + web
├── pyproject.toml                   # uv workspace root + ruff/mypy/pytest config
├── ARCHITECTURE.md                  # 2-page design doc (mandatory deliverable)
└── README.md                        # you are here
```

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — system diagram, per-component reasoning, scaling story 1→10k users, failure modes, deliberate omissions
- [infra/README.md](./infra/README.md) — deploy guide
- Per-service READMEs under `services/<name>/README.md`

## License

Private — built for the Kansha Care founding-engineer take-home.
