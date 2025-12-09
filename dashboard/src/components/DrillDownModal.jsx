import React from 'react';
import { useDashboard } from '../context/DashboardContext';

export default function DrillDownModal() {
  const { drilldownTarget, setDrilldownTarget } = useDashboard();

  if (!drilldownTarget) return null;

  return (
    <div className="modal-backdrop" onClick={() => setDrilldownTarget(null)}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{drilldownTarget.borough || drilldownTarget.scenario || 'Details'}</h3>
          <button type="button" className="ghost" onClick={() => setDrilldownTarget(null)}>
            Close
          </button>
        </div>
        <div className="modal-body">
          {Object.entries(drilldownTarget).map(([key, value]) => (
            <div key={key} className="modal-row">
              <div className="modal-key">{key}</div>
              <div className="modal-value">{typeof value === 'number' ? value.toLocaleString() : String(value)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
