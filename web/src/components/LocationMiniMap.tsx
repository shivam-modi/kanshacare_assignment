'use client';

import { Circle, CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import type { Location, USGSEvent } from '@/lib/api';
import { eventTier, radiusForMarker, tierColor, tierLabel, formatTime } from '@/lib/severity';

const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png';
const ATTRIBUTION =
  '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export function LocationMiniMap({
  location,
  events,
  height = 280,
}: {
  location: Location;
  events: USGSEvent[];
  height?: number;
}) {
  const [lon, lat] = location.point.coordinates;

  // Auto-pick a zoom level from the radius (rough heuristic).
  const zoom = location.radius_km <= 100 ? 7 : location.radius_km <= 500 ? 5 : 3;

  return (
    <div className="surface overflow-hidden" style={{ height }}>
      <MapContainer
        center={[lat, lon]}
        zoom={zoom}
        scrollWheelZoom={false}
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer url={TILE_URL} attribution={ATTRIBUTION} />
        <Circle
          center={[lat, lon]}
          radius={location.radius_km * 1000}
          pathOptions={{ color: '#38bdf8', fillColor: '#38bdf8', fillOpacity: 0.06, weight: 1 }}
        />
        <CircleMarker
          center={[lat, lon]}
          radius={4}
          pathOptions={{ color: '#38bdf8', fillColor: '#38bdf8', fillOpacity: 1 }}
        />
        {events.map((e) => {
          const [elon, elat] = e.geometry.coordinates;
          const tier = eventTier(e);
          const c = tierColor(tier);
          return (
            <CircleMarker
              key={e._id}
              center={[elat, elon]}
              radius={radiusForMarker(e.properties.mag)}
              pathOptions={{ color: c, fillColor: c, fillOpacity: 0.55, weight: 1 }}
            >
              <Popup>
                <div className="text-xs text-slate-900">
                  <div className="font-semibold">
                    M{e.properties.mag?.toFixed(1) ?? '?'} — {tierLabel(tier)}
                  </div>
                  <div>{e.properties.place ?? '—'}</div>
                  <div className="mt-1 text-slate-500">{formatTime(e.properties.time)}</div>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
