import React from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import { boroughGeo } from '../data/boroughGeo';
import { useDashboard } from '../context/DashboardContext';
import 'leaflet/dist/leaflet.css';

const LONDON_CENTER = [51.5072, -0.1276];

export default function MapView() {
  const { data, setDrilldownTarget } = useDashboard();
  const boroughs = data?.boroughData || [];

  const joined = boroughGeo
    .map((geo) => ({
      ...geo,
      metrics: boroughs.find((b) => b.borough === geo.borough),
    }))
    .filter((item) => item.metrics);

  if (!joined.length) return null;

  return (
    <div className="card">
      <div className="card-header-row">
        <h3 className="card-title">Interactive borough map</h3>
        <p className="subtle">Click a marker to open the borough drill-down.</p>
      </div>
      <div className="map-shell">
        <MapContainer center={LONDON_CENTER} zoom={10} scrollWheelZoom={false} style={{ height: 360 }}>
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {joined.map((item) => (
            <CircleMarker
              key={item.borough}
              center={[item.lat, item.lng]}
              radius={Math.max(6, Math.min(18, (item.metrics.count || 0) / 50000))}
              color="#1e3a5f"
              weight={2}
              fillColor="#ee6c4d"
              fillOpacity={0.8}
              eventHandlers={{ click: () => setDrilldownTarget(item.metrics) }}
            >
              <Tooltip direction="top" offset={[0, -6]} opacity={1} permanent={false}>
                <div>
                  <strong>{item.borough}</strong>
                  <div>EPC: {item.metrics.meanEPC}</div>
                  <div>Properties: {item.metrics.count?.toLocaleString?.() || item.metrics.count}</div>
                </div>
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}
