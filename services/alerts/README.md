# alerts-svc

The brain of the alerting subsystem. Detects rule firings; defers delivery to `worker-svc`.

## Responsibility

| | |
|---|---|
| Detection | Mongo change-stream consumer on `events`; source-silence scheduler |
| Rules | high-severity global (≥5.0), high-severity near (≥4.0 within 500 km of any location), swarm (≥5 in 30 min within 200 km), source silence (no successful poll > 10 min) |
| Telegram surface | webhook receiver — `/start`, `/summary`, `/stop`, `/locations` commands |
| Output | enqueue alert + summary jobs onto Redis (consumed by worker-svc) |
| Storage | `alerts_log` (idempotency + audit), `telegram_subscribers` |

## Why detection and delivery are separated

Detection is latency-critical and runs in a single process (rules must not double-fire). Delivery hits Telegram's API, which rate-limits and occasionally 5xxs — perfect work for a retriable worker behind a queue. Keeps the alert engine fast and idempotent.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/telegram/webhook` | Receives Telegram updates (verified via `X-Telegram-Bot-Api-Secret-Token`) |
| GET  | `/healthz` `/readyz` `/metrics` | Standard |

## Run locally

```bash
docker compose up alerts
```
