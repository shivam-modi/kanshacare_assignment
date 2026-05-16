'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, type Location } from '@/lib/api';
import { LocationCard } from './LocationCard';
import { LocationForm } from './LocationForm';
import { SystemHealthCard } from './SystemHealthCard';

const MAX_LOCATIONS = 3;

export function LocationsView() {
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.listLocations();
      setLocations(r.locations);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const remove = async (id: string) => {
    await api.deleteLocation(id);
    await refresh();
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Per-location monitoring</h1>
          <p className="mt-1 text-sm text-slate-400">
            Up to {MAX_LOCATIONS} locations. Each drives its own risk score and the alert rules
            you see on the right.
          </p>
        </div>
      </div>

      <SystemHealthCard />

      <LocationForm disabled={locations.length >= MAX_LOCATIONS} onAdded={refresh} />

      {error && (
        <div className="surface border-rose-500/40 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {loading ? (
        <div className="text-sm text-slate-500">Loading locations…</div>
      ) : locations.length === 0 ? (
        <div className="surface px-4 py-6 text-sm text-slate-400">
          No locations yet. Add one above to start tracking earthquakes near it.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {locations.map((loc) => (
            <LocationCard key={loc._id} locationId={loc._id} onDelete={() => remove(loc._id)} />
          ))}
        </div>
      )}
    </div>
  );
}
