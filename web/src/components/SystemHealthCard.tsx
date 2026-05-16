'use client';

import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { api, type SystemHealth } from '@/lib/api';
import { formatTime } from '@/lib/severity';

// Refresh every 30s — health card is one of the most-watched widgets so freshness
// matters, but we don't need sub-minute granularity for a 60s poll cycle.
const REFRESH_MS = 30_000;

export function SystemHealthCard() {
  const [data, setData] = useState<SystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const h = await api.systemHealth();
        if (alive) {
          setData(h);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : 'failed');
      }
    };
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (error)
    return (
      <Card tone="bad">
        <Dot tone="bad" />
        <span className="font-semibold">System Health</span>
        <span className="ml-auto text-xs text-slate-300">api unreachable</span>
      </Card>
    );
  if (!data)
    return (
      <Card tone="neutral">
        <Dot tone="neutral" />
        <span className="font-semibold">System Health</span>
        <span className="ml-auto text-xs text-slate-400">loading…</span>
      </Card>
    );

  const tone = pickTone(data);
  const successPct =
    data.success_rate_1h == null ? '—' : `${Math.round(data.success_rate_1h * 100)}%`;

  return (
    <Card tone={tone}>
      <div className="flex w-full flex-col gap-2">
        <div className="flex items-center gap-2">
          <Dot tone={tone} />
          <span className="font-semibold">System Health</span>
          <span className="ml-auto text-xs uppercase tracking-wide text-slate-400">
            {labelForTone(tone)}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt className="text-slate-400">Last poll</dt>
          <dd>{formatTime(epochOf(data.last_poll_ts))}</dd>
          <dt className="text-slate-400">Last success</dt>
          <dd>{formatTime(epochOf(data.last_successful_poll_ts))}</dd>
          <dt className="text-slate-400">Success rate (1h)</dt>
          <dd>{successPct} <span className="text-slate-500">({data.polls_last_hour} polls)</span></dd>
          <dt className="text-slate-400">Failure streak</dt>
          <dd>{data.consecutive_failures}</dd>
          <dt className="text-slate-400">Backfill</dt>
          <dd>
            {data.backfill.status}
            {data.backfill.events_loaded != null && (
              <span className="text-slate-500"> · {data.backfill.events_loaded} events</span>
            )}
          </dd>
        </dl>
      </div>
    </Card>
  );
}

type Tone = 'good' | 'warn' | 'bad' | 'neutral';

function pickTone(d: SystemHealth): Tone {
  if (d.backfill.status === 'failed') return 'bad';
  if (d.consecutive_failures >= 3) return 'bad';
  if (d.consecutive_failures > 0) return 'warn';
  if (d.last_poll_ts === null) return 'neutral';
  const ageMs = Date.now() - new Date(d.last_poll_ts).getTime();
  if (ageMs > 10 * 60_000) return 'bad';   // source silence ≥ 10 min
  if (ageMs > 3 * 60_000) return 'warn';
  return 'good';
}

function labelForTone(t: Tone): string {
  if (t === 'good') return 'healthy';
  if (t === 'warn') return 'degraded';
  if (t === 'bad') return 'incident';
  return 'unknown';
}

function epochOf(iso: string | null): number | null {
  return iso ? new Date(iso).getTime() : null;
}

function Card({ children, tone }: { children: React.ReactNode; tone: Tone }) {
  return (
    <div
      className={clsx(
        'surface flex items-start gap-3 px-4 py-3 text-sm',
        tone === 'good' && 'border-emerald-500/30',
        tone === 'warn' && 'border-amber-500/40',
        tone === 'bad' && 'border-rose-500/40',
      )}
    >
      {children}
    </div>
  );
}

function Dot({ tone }: { tone: Tone }) {
  return (
    <span
      className={clsx(
        'mt-1 inline-block h-2.5 w-2.5 rounded-full',
        tone === 'good' && 'bg-emerald-400',
        tone === 'warn' && 'bg-amber-400',
        tone === 'bad' && 'bg-rose-500',
        tone === 'neutral' && 'bg-slate-500',
      )}
    />
  );
}
