import React from 'react';
import { useDashboard } from '../context/DashboardContext';

export default function MapView() {
  const { data } = useDashboard();
  const constituencyCount = data?.constituencyData?.length || 0;

  return (
    <div className="card">
      <div className="card-header-row">
        <h3 className="card-title">Geographic coverage</h3>
        <p className="subtle">Map views are intentionally disabled for local authority datasets.</p>
      </div>
      <p>
        Constituency summaries are available in the table view. {constituencyCount ? `Loaded ${constituencyCount} constituencies.` : 'Load dashboard data to see constituency counts.'}
      </p>
    </div>
  );
}
