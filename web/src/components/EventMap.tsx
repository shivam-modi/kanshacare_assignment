'use client';

import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import type { USGSEvent } from '@/lib/api';
import { eventTier, radiusForMarker, tierColor, tierLabel, formatTime } from '@/lib/severity';

// CartoDB dark — free, no API key, dark-themed.
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png';
const ATTRIBUTION =
  '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export function EventMap({
  events,
  height = 480,
  center = [20, 0],
  zoom = 2,
}: {
  events: USGSEvent[];
  height?: number;
  center?: [number, number];
  zoom?: number;
}) {
  return (
    <div className="surface overflow-hidden" style={{ height }}>
      <MapContainer
        center={center}
        zoom={zoom}
        scrollWheelZoom
        worldCopyJump
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer url={TILE_URL} attribution={ATTRIBUTION} />
        {events.map((e) => {
          const [lon, lat] = e.geometry.coordinates;
          const tier = eventTier(e);
          const color = tierColor(tier);
          return (
            <CircleMarker
              key={e._id}
              center={[lat, lon]}
              radius={radiusForMarker(e.properties.mag)}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.55, weight: 1 }}
            >
              <Popup>
                <div className="text-xs text-slate-900">
                  <div className="font-semibold">
                    M{e.properties.mag?.toFixed(1) ?? '?'} — {tierLabel(tier)}
                  </div>
                  <div className="text-slate-700">{e.properties.place ?? '—'}</div>
                  <div className="mt-1 text-slate-500">{formatTime(e.properties.time)}</div>
                  {e.properties.tsunami === 1 && (
                    <div className="mt-1 font-semibold text-purple-700">Tsunami flag set</div>
                  )}
                  {e.properties.alert && (
                    <div className="mt-1 text-slate-700">PAGER: {e.properties.alert}</div>
                  )}
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
