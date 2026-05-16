# infra — deployment

Five Fly apps + MongoDB Atlas (M0 free tier) + Upstash Redis (free tier).

## One-time setup

### 1. MongoDB Atlas

1. Create a free M0 cluster on [Atlas](https://www.mongodb.com/cloud/atlas/register).
2. **Critical for change streams:** Atlas M0 already runs as a replica set — no extra config needed.
3. In Network Access, allow `0.0.0.0/0` (Fly egress IPs are dynamic). Use a strong password.
4. Copy the SRV connection string: `mongodb+srv://USER:PASS@cluster.mongodb.net`.

### 2. Upstash Redis

1. Create a free database on [Upstash](https://upstash.com/). Pick the same region as Fly (e.g. us-east-1).
2. Copy the `rediss://` (TLS) URL.

### 3. Telegram bot

1. Talk to [@BotFather](https://t.me/BotFather), `/newbot`, save the token.
2. Pick a random webhook secret (e.g. `openssl rand -hex 32`).

### 4. Fly apps

```bash
flyctl auth login
flyctl apps create kanshacare-ingestion --org personal
flyctl apps create kanshacare-api      --org personal
flyctl apps create kanshacare-alerts   --org personal
flyctl apps create kanshacare-worker   --org personal
flyctl apps create kanshacare-web      --org personal
```

### 5. Set secrets (one-shot per app)

The same secrets are needed by ingestion / api / alerts / worker:

```bash
for app in kanshacare-ingestion kanshacare-api kanshacare-alerts kanshacare-worker; do
  flyctl secrets set --app "$app" \
    MONGO_URI='mongodb+srv://USER:PASS@cluster.mongodb.net' \
    MONGO_DB='kanshacare' \
    REDIS_URL='rediss://default:TOKEN@host.upstash.io:6379' \
    TELEGRAM_BOT_TOKEN='YOUR_BOT_TOKEN' \
    TELEGRAM_WEBHOOK_SECRET='YOUR_WEBHOOK_SECRET' \
    TELEGRAM_WEBHOOK_BASE_URL='https://kanshacare-alerts.fly.dev' \
    DASHBOARD_BASE_URL='https://kanshacare-web.fly.dev' \
    API_CORS_ORIGINS='https://kanshacare-web.fly.dev' \
    GEOCODER_USER_AGENT='kanshacare-prod (your-email@example.com)'
done

flyctl secrets set --app kanshacare-web \
  NEXT_PUBLIC_API_BASE_URL='https://kanshacare-api.fly.dev'
```

### 6. Deploy (run from the repo root)

```bash
flyctl deploy -c infra/fly.ingestion.toml --remote-only
flyctl deploy -c infra/fly.api.toml       --remote-only
flyctl deploy -c infra/fly.alerts.toml    --remote-only
flyctl deploy -c infra/fly.worker.toml    --remote-only
flyctl deploy -c infra/fly.web.toml       --remote-only
```

### 7. Register the Telegram webhook (once, after alerts-svc is up)

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://kanshacare-alerts.fly.dev/telegram/webhook",
    "secret_token": "YOUR_WEBHOOK_SECRET",
    "allowed_updates": ["message"]
  }'
```

### 8. Verify

```bash
curl https://kanshacare-api.fly.dev/system/health
curl https://kanshacare-api.fly.dev/events?window=24h | jq '.count'
open https://kanshacare-web.fly.dev
# Then DM your bot — `/start` should respond.
```

## What to watch after deploy

- **ingestion** logs should show `ingestion.poll.ok` once per minute, and a `ingestion.backfill.complete` on first boot.
- **alerts** logs should show `alerts.changestream.opened` (Atlas) — if you see `alerts.changestream.failed_falling_back` you're on a non-replicaset Mongo.
- **worker** logs should show `worker.send.*` when an alert fires.

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `kanshacare-web` 500s on first load | `NEXT_PUBLIC_API_BASE_URL` not set at *build* time | Re-run deploy after `flyctl secrets set` |
| Alerts never fire on Atlas | Connection string missing `?retryWrites=true&w=majority` | Use the full SRV string from Atlas |
| `/telegram/webhook` returns 401 | Webhook secret mismatch | Check `TELEGRAM_WEBHOOK_SECRET` in Fly + `secret_token` in setWebhook payload |
| `system_health` empty | ingestion-svc scaled to 0 | `min_machines_running = 1` in fly.ingestion.toml |
