'use client';

import { useState } from 'react';
import clsx from 'clsx';
import type { USGSEvent } from '@/lib/api';
import { eventTier, formatTime, tierColor, tierLabel } from '@/lib/severity';

type SortBy = 'time' | 'mag' | 'sig';

export function EventTable({ events }: { events: USGSEvent[] }) {
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const sorted = [...events].sort((a, b) => {
    const av = pick(a, sortBy);
    const bv = pick(b, sortBy);
    if (av === bv) return 0;
    return ((av ?? -Infinity) > (bv ?? -Infinity) ? 1 : -1) * sortDir;
  });

  return (
    <div className="surface overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-[--surface-2] text-xs uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left">Severity</th>
            <SortableTh label="Mag" col="mag" sortBy={sortBy} sortDir={sortDir} onSort={(c) => toggle(c, sortBy, sortDir, setSortBy, setSortDir)} />
            <th className="px-3 py-2 text-left">Place</th>
            <SortableTh label="Sig" col="sig" sortBy={sortBy} sortDir={sortDir} onSort={(c) => toggle(c, sortBy, sortDir, setSortBy, setSortDir)} />
            <th className="px-3 py-2 text-left">Tags</th>
            <SortableTh label="Time" col="time" sortBy={sortBy} sortDir={sortDir} onSort={(c) => toggle(c, sortBy, sortDir, setSortBy, setSortDir)} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((e) => {
            const t = eventTier(e);
            return (
              <tr key={e._id} className="border-t border-[--border] hover:bg-[--surface-2]/50">
                <td className="px-3 py-2">
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full align-middle"
                    style={{ backgroundColor: tierColor(t) }}
                    title={tierLabel(t)}
                  />
                  <span className="ml-2 text-xs text-slate-300">{tierLabel(t)}</span>
                </td>
                <td className="px-3 py-2 font-mono tabular-nums">{e.properties.mag?.toFixed(1) ?? '—'}</td>
                <td className="px-3 py-2 text-slate-200">{e.properties.place ?? '—'}</td>
                <td className="px-3 py-2 text-slate-400 tabular-nums">{e.properties.sig ?? '—'}</td>
                <td className="px-3 py-2">
                  {e.properties.tsunami === 1 && <Tag color="#7c3aed">Tsunami</Tag>}
                  {e.properties.alert && (
                    <Tag color={tierColor(eventTier(e))}>PAGER {e.properties.alert}</Tag>
                  )}
                  {e.properties.status === 'reviewed' && <Tag color="#22d3ee">Reviewed</Tag>}
                </td>
                <td className="px-3 py-2 text-slate-400">{formatTime(e.properties.time)}</td>
              </tr>
            );
          })}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                No events in this window.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function pick(e: USGSEvent, by: SortBy): number | null {
  if (by === 'time') return e.properties.time;
  if (by === 'mag') return e.properties.mag;
  return e.properties.sig;
}

function toggle(
  col: SortBy,
  cur: SortBy,
  curDir: 1 | -1,
  setBy: (c: SortBy) => void,
  setDir: (d: 1 | -1) => void,
) {
  if (cur === col) setDir(curDir === 1 ? -1 : 1);
  else {
    setBy(col);
    setDir(-1);
  }
}

function SortableTh({
  label,
  col,
  sortBy,
  sortDir,
  onSort,
}: {
  label: string;
  col: SortBy;
  sortBy: SortBy;
  sortDir: 1 | -1;
  onSort: (c: SortBy) => void;
}) {
  return (
    <th
      onClick={() => onSort(col)}
      className={clsx(
        'cursor-pointer select-none px-3 py-2 text-left',
        sortBy === col && 'text-white',
      )}
    >
      {label}
      {sortBy === col && <span className="ml-1 text-xs">{sortDir === 1 ? '↑' : '↓'}</span>}
    </th>
  );
}

function Tag({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span
      className="mr-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}55` }}
    >
      {children}
    </span>
  );
}
