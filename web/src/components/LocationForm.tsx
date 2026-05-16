'use client';

import { useState } from 'react';
import { api } from '@/lib/api';

export function LocationForm({
  disabled,
  onAdded,
}: {
  disabled: boolean;
  onAdded: () => void;
}) {
  const [name, setName] = useState('');
  const [query, setQuery] = useState('');
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [radius, setRadius] = useState('500');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const body: Parameters<typeof api.createLocation>[0] = {
        name: name.trim(),
        radius_km: Number(radius) || 500,
      };
      if (lat && lon) {
        body.lat = Number(lat);
        body.lon = Number(lon);
      } else if (query.trim()) {
        body.query = query.trim();
      } else {
        throw new Error('Provide a city name OR lat/lon.');
      }
      await api.createLocation(body);
      setName('');
      setQuery('');
      setLat('');
      setLon('');
      onAdded();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="surface flex flex-col gap-3 p-4 text-sm">
      <h3 className="font-semibold">Add a location</h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Input label="Name" value={name} onChange={setName} placeholder="Home, Office, …" required />
        <Input label="Radius (km)" value={radius} onChange={setRadius} placeholder="500" />
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Input
          label="City / place (geocoded)"
          value={query}
          onChange={setQuery}
          placeholder="Tokyo, San Francisco, …"
        />
        <Input label="Lat (override)" value={lat} onChange={setLat} placeholder="35.6762" />
        <Input label="Lon (override)" value={lon} onChange={setLon} placeholder="139.6503" />
      </div>
      <p className="text-xs text-slate-500">
        Either provide a city name to be geocoded (Nominatim, swappable provider) or paste a
        lat/lon directly — useful when the geocoder is rate-limited.
      </p>
      {error && <div className="rounded bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</div>}
      <button
        type="submit"
        disabled={disabled || submitting}
        className="self-start rounded-md bg-sev-elevated px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-400 disabled:opacity-40"
      >
        {disabled ? 'Cap reached (3)' : submitting ? 'Adding…' : 'Add location'}
      </button>
    </form>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <input
        type="text"
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-[--border] bg-[--surface-2] px-3 py-1.5 text-sm outline-none focus:border-sev-elevated"
      />
    </label>
  );
}
