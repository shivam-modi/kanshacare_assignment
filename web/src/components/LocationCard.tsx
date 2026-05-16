'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { api, type LocationSummary } from '@/lib/api';

const LocationMiniMap = dynamic(
  () => import('./LocationMiniMap').then((m) => m.LocationMiniMap),
  {
    ssr: false,
    loading: () => (
      <div className="surface flex h-[280px] items-center justify-center text-slate-500">
        Loading map…
      </div>
    ),
  },
);

const TIER_STYLES: Record<string, { ring: string; text: string; label: string }> = {
  low: { ring: 'ring-emerald-500/30', text: 'text-emerald-300', label: 'Low risk' },
  moderate: { ring: 'ring-amber-500/40', text: 'text-amber-300', label: 'Moderate' },
  elevated: { ring: 'ring-orange-500/40', text: 'text-orange-300', label: 'Elevated' },
  high: { ring: 'ring-rose-500/50', text: 'text-rose-300', label: 'High risk' },
};

export function LocationCard({
  locationId,
  onDelete,
}: {
  locationId: string;
  onDelete: () => void;
}) {
  const [data, setData] = useState<LocationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .locationSummary(locationId)
        .then((s) => alive && setData(s))
        .catch((e) => alive && setError(e instanceof Error ? e.message : 'load failed'));
    load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [locationId]);

  if (error)
    return (
      <div className="surface border-rose-500/30 p-4 text-sm">
        <div className="flex items-center justify-between">
          <strong>Error</strong>
          <button onClick={onDelete} className="text-xs text-slate-400 hover:text-white">
            remove
          </button>
        </div>
        <div className="mt-1 text-rose-200">{error}</div>
      </div>
    );
  if (!data) return <div className="surface p-4 text-sm text-slate-400">Loading…</div>;

  const tierStyle = TIER_STYLES[data.risk.tier] ?? TIER_STYLES.low;

  return (
    <div className="surface flex flex-col gap-4 p-4">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{data.location.name}</h3>
          <p className="text-xs text-slate-400">
            {data.location.point.coordinates[1].toFixed(3)},{' '}
            {data.location.point.coordinates[0].toFixed(3)} · radius {data.location.radius_km} km
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                await api.requestSummary();
                setToast('Summary queued. Check Telegram in a few seconds.');
                setTimeout(() => setToast(null), 5000);
              } catch (e) {
                setToast(`Failed: ${e instanceof Error ? e.message : 'unknown'}`);
                setTimeout(() => setToast(null), 5000);
              }
            }}
            className="rounded-md bg-[--surface-2] px-2 py-1 text-xs text-slate-200 hover:text-white"
            title="Enqueue a Telegram summary for all subscribers"
          >
            Send summary now
          </button>
          <button
            onClick={onDelete}
            className="text-xs text-slate-400 hover:text-rose-300"
            title="Remove location"
          >
            remove
          </button>
        </div>
      </header>

      {toast && (
        <div className="rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200">
          {toast}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className={clsx('surface flex flex-col gap-1 p-3 ring-2', tierStyle.ring)}>
          <span className="text-xs uppercase tracking-wide text-slate-400">Risk score</span>
          <span className={clsx('text-3xl font-mono tabular-nums', tierStyle.text)}>
            {data.risk.score}
          </span>
          <span className={clsx('text-xs', tierStyle.text)}>{tierStyle.label}</span>
          <span className="mt-2 text-[10px] leading-snug text-slate-500">{data.risk.formula}</span>
        </div>

        <div className="surface p-3">
          <span className="text-xs uppercase tracking-wide text-slate-400">Nearby activity</span>
          <dl className="mt-2 grid grid-cols-3 gap-1 text-center">
            {(['24h', '7d', '30d'] as const).map((w) => (
              <div key={w}>
                <dt className="text-[10px] text-slate-500">{w}</dt>
                <dd className="text-xl font-mono tabular-nums">{data.counts[w]}</dd>
              </div>
            ))}
          </dl>
          {data.risk.largest_mag != null && (
            <div className="mt-2 text-xs text-slate-400">
              Largest in 30d: <span className="font-mono">M{data.risk.largest_mag.toFixed(1)}</span>
              {data.risk.closest_km != null && (
                <> · closest <span className="font-mono">{data.risk.closest_km} km</span></>
              )}
            </div>
          )}
        </div>

        <div className="surface p-3">
          <span className="text-xs uppercase tracking-wide text-slate-400">Active thresholds</span>
          <p className="mt-2 text-xs leading-relaxed text-slate-300">
            Next alert fires if:
          </p>
          <ul className="mt-1 list-disc pl-5 text-xs text-slate-200">
            <li>
              Mag ≥ <span className="font-mono">{data.thresholds.near_mag}</span> within{' '}
              <span className="font-mono">{data.thresholds.near_radius_km} km</span>
            </li>
            <li>≥ 5 quakes within 200 km / 30 min (swarm)</li>
            <li>USGS feed silent for &gt; 10 min</li>
          </ul>
        </div>
      </div>

      <LocationMiniMap location={data.location} events={data.nearby_events} />
    </div>
  );
}
