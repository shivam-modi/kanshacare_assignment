# worker-svc

Async job consumer. Owns everything that should *not* block detection: Telegram delivery, summary generation, retries, rate-limiting.

## Jobs (Phase 5)

| Job | Trigger | Behaviour |
|---|---|---|
| `send_alert` | enqueued by alerts-svc when a rule fires | Posts to Telegram for each subscriber. Token-bucket rate-limit (Telegram caps at 30/s global, 1/chat/s). Retries on 5xx / 429 with exponential backoff. |
| `summary_job` | scheduled daily cron + on-demand dashboard button + bot `/summary` command | Aggregates last 24h of events, computes per-location risk, formats Telegram message, sends to all (or one) subscriber. |

## Why a worker at all?

So the rule engine never blocks on Telegram. A 5s Telegram timeout in alerts-svc would back the change stream up; a 5s Telegram timeout in worker-svc just delays one job.

## Run locally

The Phase 1 build only runs the health sidecar so the deploy + dashboard works:

```bash
docker compose up worker
```

Phase 5 will add an `arq` process running `app.worker.WorkerSettings`.
