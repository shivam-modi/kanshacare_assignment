# web — Kansha Care dashboard

Next.js 14 (App Router) + TypeScript + Tailwind. Talks to `api-svc` over HTTP + SSE.

## Pages

- `/` — Global incident tracker (map + table + live SSE refresh + System Health card)
- `/locations` — Add up to 3 locations; each gets a risk score, 24h/7d/30d counts, largest nearby event, mini-map with radius circle, and a literal display of its alert thresholds. "Send summary now" enqueues a Telegram digest.

## Run

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

Set `NEXT_PUBLIC_API_BASE_URL` if your api-svc isn't on `http://localhost:8001`.

## Notes

- Map uses CartoDB dark tiles (free, no API key)
- Leaflet is client-only — loaded via `next/dynamic` with `ssr: false`
- SSE uses the native `EventSource`; auto-reconnects on transient errors
- All severity colours / tier logic live in `src/lib/severity.ts` so the map, table, and badges agree
