// Typed API client. Single source of truth for the API_BASE_URL.

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8001';

export type TimeWindow = '1h' | '24h' | '7d' | '30d';
export type PagerAlert = 'green' | 'yellow' | 'orange' | 'red';

export interface EventProps {
  mag: number | null;
  place: string | null;
  time: number | null;
  updated: number | null;
  alert: PagerAlert | null;
  status: 'automatic' | 'reviewed' | 'deleted' | null;
  tsunami: number;
  sig: number | null;
  magType: string | null;
  type: string | null;
}

export interface USGSEvent {
  _id: string;
  properties: EventProps;
  geometry: { type: 'Point'; coordinates: [number, number, number] };
  _ingested_at?: string;
  _last_seen_at?: string;
}

export interface SystemHealth {
  now: string;
  last_poll_ts: string | null;
  last_poll_status: 'ok' | 'error' | 'timeout' | null;
  last_successful_poll_ts: string | null;
  success_rate_1h: number | null;
  consecutive_failures: number;
  polls_last_hour: number;
  backfill: {
    status: 'pending' | 'running' | 'complete' | 'failed';
    events_loaded: number | null;
    completed_at: string | null;
  };
}

export interface Location {
  _id: string;
  name: string;
  query: string | null;
  point: { type: 'Point'; coordinates: [number, number] };
  radius_km: number;
  thresholds: { near_mag: number | null; near_radius_km: number | null };
  created_at: string;
}

export interface LocationSummary {
  location: Location;
  thresholds: { near_mag: number; near_radius_km: number };
  risk: {
    score: number;
    tier: 'low' | 'moderate' | 'elevated' | 'high';
    event_count: number;
    largest_mag: number | null;
    closest_km: number | null;
    formula: string;
  };
  counts: { '24h': number; '7d': number; '30d': number };
  largest_event: USGSEvent | null;
  nearby_events: USGSEvent[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    cache: 'no-store',
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body?.error?.message || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return (await res.json()) as T;
}

export const api = {
  events: (window: TimeWindow, minMag?: number) =>
    request<{ window: TimeWindow; count: number; events: USGSEvent[] }>(
      `/events?window=${window}${minMag != null ? `&min_mag=${minMag}` : ''}`,
    ),

  eventsNear: (lat: number, lon: number, radiusKm: number, window: TimeWindow = '30d') =>
    request<{ window: TimeWindow; count: number; events: USGSEvent[] }>(
      `/events/near?lat=${lat}&lon=${lon}&radius_km=${radiusKm}&window=${window}`,
    ),

  systemHealth: () => request<SystemHealth>('/system/health'),

  listLocations: () => request<{ count: number; locations: Location[] }>('/locations'),

  createLocation: (body: {
    name: string;
    query?: string;
    lat?: number;
    lon?: number;
    radius_km?: number;
  }) =>
    request<Location>('/locations', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteLocation: (id: string) =>
    request<void>(`/locations/${id}`, { method: 'DELETE' }),

  locationSummary: (id: string) => request<LocationSummary>(`/locations/${id}/summary`),

  requestSummary: (chatId?: number) =>
    request<{ status: string; job_id: string | null }>('/summaries/request', {
      method: 'POST',
      body: JSON.stringify(chatId ? { chat_id: chatId } : {}),
    }),
};
