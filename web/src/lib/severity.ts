// Severity / colour decisions live here so the table, map, and badges agree.
//
// Decision order:
//   1. Tsunami flag — overrides everything (always violet, marked).
//   2. PAGER alert — when USGS provides it (only on larger events) it's authoritative.
//   3. Magnitude bands — fallback for the long tail of small events.

import type { PagerAlert, USGSEvent } from './api';

export type Tier = 'tsunami' | 'high' | 'elevated' | 'moderate' | 'low' | 'mute';

const PAGER_TO_TIER: Record<PagerAlert, Tier> = {
  red: 'high',
  orange: 'elevated',
  yellow: 'moderate',
  green: 'low',
};

const TIER_COLOR: Record<Tier, string> = {
  tsunami: '#7c3aed',
  high: '#ef4444',
  elevated: '#f97316',
  moderate: '#f59e0b',
  low: '#10b981',
  mute: '#475569',
};

const TIER_LABEL: Record<Tier, string> = {
  tsunami: 'Tsunami',
  high: 'High',
  elevated: 'Elevated',
  moderate: 'Moderate',
  low: 'Low',
  mute: 'Minor',
};

export function eventTier(event: USGSEvent): Tier {
  if (event.properties.tsunami === 1) return 'tsunami';
  if (event.properties.alert) return PAGER_TO_TIER[event.properties.alert];
  const mag = event.properties.mag ?? 0;
  if (mag >= 6) return 'high';
  if (mag >= 5) return 'elevated';
  if (mag >= 4) return 'moderate';
  if (mag >= 3) return 'low';
  return 'mute';
}

export function tierColor(tier: Tier): string {
  return TIER_COLOR[tier];
}

export function tierLabel(tier: Tier): string {
  return TIER_LABEL[tier];
}

export function radiusForMarker(mag: number | null): number {
  // Marker size grows with magnitude; capped so big events don't dominate.
  if (mag == null) return 4;
  return Math.max(4, Math.min(28, 4 + (mag - 2) * 4));
}

export function formatTime(ms: number | null | undefined): string {
  if (!ms) return '—';
  const d = new Date(ms);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 30 * 86_400_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return d.toLocaleDateString();
}
