'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE, api, type TimeWindow, type USGSEvent } from '@/lib/api';
import { EventTable } from './EventTable';
import { SystemHealthCard } from './SystemHealthCard';
import { WindowSelector } from './WindowSelector';

// Leaflet uses `window`, so we must client-only it via dynamic import (no SSR).
const EventMap = dynamic(() => import('./EventMap').then((m) => m.EventMap), {
  ssr: false,
  loading: () => (
    <div className="surface flex h-[480px] items-center justify-center text-slate-500">
      Loading map…
    </div>
  ),
});

export function GlobalView() {
  const [window, setWindow] = useState<TimeWindow>('24h');
  const [events, setEvents] = useState<USGSEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Refetch whenever the time window changes.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .events(window)
      .then((r) => {
        if (alive) {
          setEvents(r.events);
          setError(null);
        }
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'load failed'))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [window]);

  // Live updates via SSE. Each pushed event is upserted in-place by id, so the
  // visible feed stays current without a full refetch.
  const onSseEvent = useCallback((doc: USGSEvent) => {
    setEvents((prev) => {
      const idx = prev.findIndex((p) => p._id === doc._id);
      if (idx === -1) return [doc, ...prev].slice(0, 1000);
      const next = prev.slice();
      next[idx] = doc;
      return next;
    });
  }, []);

  useEffect(() => {
    // EventSource is browser-only.
    if (typeof EventSource === 'undefined') return;
    const es = new EventSource(`${API_BASE}/events/stream`);
    es.addEventListener('event', (ev: MessageEvent) => {
      try {
        const doc = JSON.parse(ev.data) as USGSEvent;
        onSseEvent(doc);
      } catch {
        /* ignore malformed frame */
      }
    });
    es.onerror = () => {
      // Browser will auto-reconnect; nothing to do.
    };
    return () => es.close();
  }, [onSseEvent]);

  const stats = useMemo(() => summarise(events), [events]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Global incident tracker</h1>
          <p className="mt-1 text-sm text-slate-400">
            {loading
              ? 'Loading…'
              : `${stats.total} events · M-max ${stats.maxMag.toFixed(1)} · ${stats.tsunamiCount} tsunami flag${stats.tsunamiCount === 1 ? '' : 's'}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <WindowSelector value={window} onChange={setWindow} />
        </div>
      </div>

      <SystemHealthCard />

      {error && (
        <div className="surface border-rose-500/40 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <EventMap events={events} />
      <EventTable events={events} />
    </div>
  );
}

function summarise(events: USGSEvent[]) {
  let maxMag = 0;
  let tsunamiCount = 0;
  for (const e of events) {
    if ((e.properties.mag ?? 0) > maxMag) maxMag = e.properties.mag ?? 0;
    if (e.properties.tsunami === 1) tsunamiCount += 1;
  }
  return { total: events.length, maxMag, tsunamiCount };
}
