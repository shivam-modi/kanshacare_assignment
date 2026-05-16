# Architecture — Kansha Care Earthquake Telemetry

## 1. System diagram

```
                ┌──────────────────┐
                │ USGS GeoJSON     │  all_hour.geojson  (every 60s)
                │ feeds (public)   │  all_month.geojson (one-shot)
                └────────┬─────────┘
                         │ httpx + tenacity (3 retries, ETag conditional GET)
                         ▼
          ┌────────── ingestion-svc ──────────┐
          │  FastAPI + APScheduler            │
          │  • backfill (idempotent, meta-    │
          │    flagged, runs in parallel)     │
          │  • 60s poller, max_instances=1    │
          │  • upsert by USGS id with         │
          │    properties.updated comparison  │
          │  • malformed features quarantined │
          │  • writes system_health every     │
          │    cycle (never raises)           │
          └────────────────┬──────────────────┘
                           │ Motor (async)
                           ▼
          ┌──────────── MongoDB Atlas M0 ─────────────┐
          │  events (2dsphere, time-indexed)          │
          │  events_quarantine                        │
          │  locations (2dsphere, cap 3 per user)     │
          │  system_health (TTL 7d, used for the      │
          │    "always-visible" dashboard card)       │
          │  alerts_log (unique dedup_key)            │
          │  telegram_subscribers                     │
          │  geocode_cache (TTL 30d)                  │
          │  meta (backfill state)                    │
          └──────────────┬──────────────┬─────────────┘
                         │              │
            change stream│              │ reads
                         ▼              ▼
          ┌─── alerts-svc ───┐    ┌─── api-svc ────┐
          │ FastAPI          │    │ FastAPI        │
          │ • change stream  │    │ • REST + SSE   │
          │   consumer (poll │    │ • locations    │
          │   fallback for   │    │   CRUD, summary│
          │   non-replica    │    │ • /system/     │
          │   dev Mongo)     │    │   health card  │
          │ • rule engine    │    │ • /summaries/  │
          │   (4 rules)      │    │   request      │
          │ • silence cron   │    │   (rate-limit  │
          │ • daily cron     │    │   1/min)       │
          │ • /tg/webhook    │    │ • slowapi      │
          │   (HMAC verified)│    └────────┬───────┘
          └────────┬─────────┘             │ Server-Sent Events
                   │ enqueue              ▲┘
                   ▼                       │
          ┌──── Upstash Redis ─────┐       │
          │  arq queues:           │       │
          │  • kanshacare:alerts   │       │
          │  • kanshacare:summaries│       │
          └────────┬───────────────┘       │
                   │ consume                │
                   ▼                        │
          ┌──── worker-svc ────┐             │
          │ arq worker process │             │
          │ • send_alert       │──┐          │
          │ • summary_job      │  │ Telegram │
          │ token-bucket rate  │  │ Bot API  │
          │ limit (30/s global,│  │          │
          │  1/s per chat)     │  └──→ Telegram users
          │ retries w/ backoff │             │
          │ DLQ on exhaustion  │             │
          └────────────────────┘             │
                                              │
                              ┌── web (Next.js) ──┘
                              │ App Router + TS    │
                              │ react-leaflet      │
                              │ SSE-driven         │
                              │ /  /locations      │
                              └────────────────────┘
```

## 2. Why each choice

| Component | Choice | Reasoning |
|---|---|---|
| Service split | 4 Python services (ingestion / api / alerts / worker) + 1 Next.js | Matches Kansha's real production shape: device ingestion is write-heavy + single-writer; user-facing API is read-heavy + horizontally scalable; alert detection must not double-fire; alert delivery must not block detection. Splitting maps cleanly to those scaling/failure characteristics. |
| Mongo | Atlas M0 free tier; 2dsphere indexes; change streams | USGS data IS GeoJSON — Mongo stores it almost verbatim. `$geoWithin $centerSphere` makes "events within 500 km of point" a one-line query (PostGIS in Postgres would also work; we chose Mongo for native fit). Change streams give push-based rule evaluation without a separate bus. |
| Redis (Upstash) + arq | Job queue between detection and delivery | Detection is in-process and latency-critical; delivery hits Telegram which rate-limits and 5xxs. Queue decouples them so Telegram outages can't back up the change stream. Same queue carries on-demand + cron daily summaries — single code path. |
| Geocoder | Pluggable `Geocoder` Protocol, Nominatim impl, Mongo-cached | The Protocol interface is the contract; swapping in LocationIQ or Mapbox is a 1-file change, callers untouched. Cache is provider-agnostic — survives provider swaps. |
| Severity model | Cascade: tsunami → PAGER alert → mag band | USGS publishes PAGER (estimated human/economic impact) for larger events; when present it's authoritative. Mag-band fallback covers the long tail. Tsunami flag overrides everything because the consequence is qualitative, not quantitative. Severity logic lives in one module (`severity.ts` on web, `rules.py` on backend) so map markers, table tags, and alert payloads agree. |
| Risk score | `Σ magnitude_weight(10^1.5(M-2)) × recency_decay(half-life 7d) × proximity_decay(quadratic to radius edge)` | Magnitude is exponential (it's an energy proxy), recency should be smooth (half-life is intuitive for operators), proximity should fall off faster than linear (a quake at the edge of the radius is qualitatively different from one overhead). Documented and visible on the dashboard — the operator needs a stable mental model. |
| Dedup | Unique index on `alerts_log.dedup_key`; key = `(rule, event_id or location_id [+ 30-min bucket for swarm, hour bucket for silence])` | Atomic at the DB level — even if alerts-svc somehow processed the same event twice (e.g. change stream resume after pod restart), only one alert fires. |
| SSE for live dashboard | `text/event-stream` from api-svc, change stream behind it | Simpler than WebSocket for unidirectional push. Browsers auto-reconnect. Server falls back to a 15s polling loop if Mongo isn't a replica set (local dev). |

## 3. Scaling: 1 user / 3 locations → 10k users / 30k locations

**What stays:**
- USGS feed cadence (still 60s; their cache says so)
- Per-poll upsert + system_health write
- Mongo for events (read-heavy, geo-indexed)
- The rule engine logic and dedup discipline
- Change-stream pattern (or its successor — see below)
- Telegram rate-limit token bucket in worker-svc

**What changes:**
- **api-svc** horizontally scales behind Fly's L4 LB. SSE connections become the bottleneck (each idle listener is a goroutine-equivalent); switch to long-polling or a dedicated push gateway.
- **alerts-svc** stays single-instance for the rule engine itself, but the change-stream consumer becomes a consumer **group** partitioned by `event.id`'s leading bits (Redis Streams or Kafka) — each partition runs independently, dedup index still catches any rare double-evaluation.
- **worker-svc** scales horizontally on the same Redis queue. The token bucket moves from in-process to a Redis-backed shared counter (Lua script) so all workers respect the global Telegram limit collectively.
- **Mongo Atlas M0 → M30+** with sharding on `geohash(events.geometry)`. Locations collection cached in Redis (per-user keys, invalidated on write).
- **Per-location summary endpoint** is the hottest read path at scale (one query per location card render). Add a materialised collection refreshed every 60s in alerts-svc post-poll, served from a Redis cache keyed by location_id.
- **Daily summary** stops broadcasting on a single cron — switch to a paginated fan-out: cron enqueues N batched summary jobs (e.g. 100 chats per job), workers process them in parallel respecting per-bot Telegram limits.
- **Multi-tenancy**: locations grow a `user_id` field, indexes prefix on it, change-stream consumers filter or partition by it.

**What breaks first:**
1. The 1-min poll/0-replica ingestion process — a 90s GC pause or single Fly machine failure silences the feed. *Fix:* leader election (Mongo `_id` heartbeat or a distributed lock in Redis) lets a second ingestion replica take over without doubling polls.
2. SSE fan-out from one api-svc machine — long-lived connections + memory cost. *Fix:* dedicated push tier (e.g. CloudFlare Durable Objects, AWS API Gateway WebSocket) or migrate to short-poll.
3. Telegram per-bot global limit (30/s). At 10k subscribers and a high-mag global event, broadcast takes ~5 minutes. *Fix:* multiple Telegram bots routed per geographic shard, or migrate to provider-redundant delivery (push notifications via FCM + Telegram both).
4. Atlas M0 storage cap (512 MB). 30 days × ~10k global events ≈ several MB — fine. Backing alerts_log unbounded growth is the real risk; need a TTL on resolved alerts or archive to cold storage.

## 4. Failure modes considered

| Mode | Handling |
|---|---|
| USGS feed unreachable / 5xx | `tenacity` 3 retries with exponential backoff. Persistent failure logs an error row to `system_health`; the System Health card flips to red after consecutive_failures ≥ 3. |
| USGS returns malformed JSON or invalid feature | Per-feature Pydantic validation; bad features go to `events_quarantine` with the parse error. The rest of the batch ingests normally. |
| USGS revises an event after publication | `properties.updated` comparison classifies it as "updated" (not "new"); `_ingested_at` preserved. Updated counts are surfaced on the dashboard. |
| Source silence (no successful poll > 10 min) | `silence.py` runs every 2 minutes against `system_health`. Fires a critical alert, deduped per hour bucket. |
| Mongo unreachable at boot | Services start anyway; `/readyz` returns 503. `ensure_indexes` retried on next write. |
| Mongo unreachable during operation | All writes wrapped in try/except; health endpoint reflects truth. The change-stream consumer reconnects on its own. |
| Atlas not configured as replica set (local dev) | `EventConsumer` and SSE both detect the failure and fall back to a 15s polling loop. Same correctness, lower freshness. |
| Telegram API rate limit (429) | Worker treats it as a retriable failure. arq retries with backoff. The token bucket prevents most 429s from happening at all. |
| Telegram API 5xx | arq retries up to `max_tries=5`. After exhaustion the job lands in arq's DLQ; `alerts_log.delivery_status` is marked `failed`. |
| Duplicate alert dispatch (e.g. change stream resumed after process restart re-emits the same event) | Unique index on `alerts_log.dedup_key` rejects the second insert; `dispatch()` returns False and increments `alerts_suppressed_total`. No Telegram message is sent. |
| Geocoder rate-limited / down | Validation error surfaced to user; the "lat/lon paste" escape hatch always works. |
| Webhook spoofing | `X-Telegram-Bot-Api-Secret-Token` verified on every inbound request; mismatches return 401 and log a warning. |
| Daily summary cron fires twice (e.g. scheduler restart at the trigger time) | APScheduler `coalesce=True` collapses missed runs. arq de-dupes by job_id when explicitly set; the broadcast path is idempotent at the message-content level. |

## 5. What I deliberately did not do — and why

- **No user authentication / multi-tenancy on the dashboard.** The assignment is single-user. Adding auth would have eaten 4-6 hours that I spent on observability + dedup + tests instead. Multi-tenancy is the first change on the scaling path.
- **No Mongo migrations framework.** `_schema_version` is on every doc, but actual `umongo` / `motor-migrations` setup is unnecessary at v1. The pattern is in place.
- **No mTLS or service-to-service auth between Fly apps.** Fly's private network is internal-only by default; we route via public URLs for the webhook only. Adding zero-trust would harden production but doesn't change the architecture.
- **No alert delivery via email / SMS.** The assignment specified Telegram. The `worker-svc` jobs are channel-agnostic in shape, so adding a delivery target is one new job + format.
- **No real-time map updates on the per-location card.** Global SSE is enough — per-location data refreshes every 60s, which matches the poll cadence anyway. Stream churn on every event for every open location card isn't worth the bytes.
- **No Grafana / Loki stack.** Each service exposes `/metrics` Prometheus and structured JSON logs. Anyone with a Grafana Cloud free tier can plug them in within an hour; building it here would be undifferentiated infra work.
- **No load tests.** I unit-tested the rule engine, dedup, message formatting, geo math, USGS parsing (happy + 5xx + corrupt + 304), and 17 endpoint tests with a `FakeMongoClient` that implements `$geoWithin $centerSphere`. End-to-end load against a real Mongo + Redis is the next test layer — captured in a follow-up.
