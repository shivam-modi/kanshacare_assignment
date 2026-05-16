'use client';

import clsx from 'clsx';
import type { TimeWindow } from '@/lib/api';

const OPTIONS: { value: TimeWindow; label: string }[] = [
  { value: '1h', label: '1 hour' },
  { value: '24h', label: '24 hours' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
];

export function WindowSelector({
  value,
  onChange,
}: {
  value: TimeWindow;
  onChange: (v: TimeWindow) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-[--border] bg-[--surface] p-1 text-sm">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            'rounded-md px-3 py-1 transition-colors',
            value === o.value
              ? 'bg-[--surface-2] text-white shadow-inner'
              : 'text-slate-400 hover:text-slate-200',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
