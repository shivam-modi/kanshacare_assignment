#!/usr/bin/env bash
# One-shot deploy: creates the 5 Fly apps, sets secrets from .env.production,
# deploys each, and registers the Telegram webhook.
#
# Usage (from repo root):
#   cp .env.production.example .env.production
#   $EDITOR .env.production    # fill in MONGO_URI, REDIS_URL, TELEGRAM_BOT_TOKEN, etc.
#   ./infra/deploy.sh
#
# Re-running is safe: app-create is idempotent (skipped if it exists), secrets
# are overwritten in-place, deploys are versioned by Fly.

set -euo pipefail

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl not on PATH. Run: export PATH=\"\$HOME/.fly/bin:\$PATH\""
  exit 1
fi

ENV_FILE="${ENV_FILE:-.env.production}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.production.example to $ENV_FILE and fill it in."
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

required=(MONGO_URI REDIS_URL TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET)
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    echo "Missing $v in $ENV_FILE"
    exit 1
  fi
done

APP_INGESTION="${APP_INGESTION:-kanshacare-ingestion}"
APP_API="${APP_API:-kanshacare-api}"
APP_ALERTS="${APP_ALERTS:-kanshacare-alerts}"
APP_WORKER="${APP_WORKER:-kanshacare-worker}"
APP_WEB="${APP_WEB:-kanshacare-web}"
GEOCODER_USER_AGENT="${GEOCODER_USER_AGENT:-kanshacare-prod (contact@example.com)}"

WEB_URL="https://${APP_WEB}.fly.dev"
API_URL="https://${APP_API}.fly.dev"
ALERTS_URL="https://${APP_ALERTS}.fly.dev"

create_app_if_missing() {
  local app="$1"
  if flyctl status --app "$app" >/dev/null 2>&1; then
    echo "  app $app already exists — skipping create"
  else
    echo "  creating $app"
    flyctl apps create "$app"
  fi
}

set_backend_secrets() {
  local app="$1"
  echo "  setting secrets on $app"
  flyctl secrets set --app "$app" --stage \
    MONGO_URI="$MONGO_URI" \
    MONGO_DB="kanshacare" \
    REDIS_URL="$REDIS_URL" \
    TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
    TELEGRAM_WEBHOOK_SECRET="$TELEGRAM_WEBHOOK_SECRET" \
    TELEGRAM_WEBHOOK_BASE_URL="$ALERTS_URL" \
    DASHBOARD_BASE_URL="$WEB_URL" \
    API_CORS_ORIGINS="$WEB_URL" \
    GEOCODER_USER_AGENT="$GEOCODER_USER_AGENT" \
    LOG_FORMAT="json" \
    ENV="production" >/dev/null
}

echo "▶ 1/4  Creating Fly apps (idempotent)..."
for app in "$APP_INGESTION" "$APP_API" "$APP_ALERTS" "$APP_WORKER" "$APP_WEB"; do
  create_app_if_missing "$app"
done

echo "▶ 2/4  Staging secrets on the four backend apps..."
for app in "$APP_INGESTION" "$APP_API" "$APP_ALERTS" "$APP_WORKER"; do
  set_backend_secrets "$app"
done

# Web app only needs the public API URL.
echo "  setting secrets on $APP_WEB"
flyctl secrets set --app "$APP_WEB" --stage \
  NEXT_PUBLIC_API_BASE_URL="$API_URL" >/dev/null

echo "▶ 3/4  Deploying all 5 apps..."
# The `.` argument sets the build context to the repo root so the Dockerfile
# paths inside the fly.<svc>.toml files (which start with `services/...` and
# `web/...`) resolve correctly. Without it, Fly uses `infra/` as the context.
flyctl deploy . -c infra/fly.ingestion.toml --remote-only
flyctl deploy . -c infra/fly.api.toml       --remote-only
flyctl deploy . -c infra/fly.alerts.toml    --remote-only
flyctl deploy . -c infra/fly.worker.toml    --remote-only
flyctl deploy . -c infra/fly.web.toml       --remote-only

echo "▶ 4/4  Registering Telegram webhook..."
curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"${ALERTS_URL}/telegram/webhook\",\"secret_token\":\"${TELEGRAM_WEBHOOK_SECRET}\",\"allowed_updates\":[\"message\"]}" \
  | grep -q '"ok":true' && echo "  webhook registered ✓"

cat <<EOF

──────────────────────────────────────────────────────────
✓ Deploy complete.

  Dashboard:     ${WEB_URL}
  API:           ${API_URL}/system/health
  alerts-svc:    ${ALERTS_URL}/healthz

  Try the bot:   open Telegram, find your bot, send /start

Next: fill the two placeholders in README.md (dashboard URL + bot
username) and push so contact@kansha.care can see them.
──────────────────────────────────────────────────────────
EOF
