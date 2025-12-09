import React from 'react';
import { useDashboard } from '../context/DashboardContext';

export default function FilterBar() {
  const { filters, setFilters, resetFilters, rawData } = useDashboard();
  const boroughOptions = rawData?.boroughData || [];
  const scenarioOptions = rawData?.scenarioData || [];

  const updateField = (field, value) => setFilters((prev) => ({ ...prev, [field]: value }));

  return (
    <div className="toolbar">
      <div className="toolbar-group">
        <label className="toolbar-label">Search</label>
        <input
          type="search"
          value={filters.search}
          onChange={(e) => updateField('search', e.target.value)}
          placeholder="Search boroughs, scenarios, notes"
        />
      </div>

      <div className="toolbar-group">
        <label className="toolbar-label">Borough</label>
        <select value={filters.borough} onChange={(e) => updateField('borough', e.target.value)}>
          <option value="all">All boroughs</option>
          {boroughOptions.map((item) => (
            <option key={item.code || item.borough_name || item.borough} value={item.borough_name || item.borough}>
              {item.borough_name || item.borough}
            </option>
          ))}
        </select>
      </div>

      <div className="toolbar-group">
        <label className="toolbar-label">Pathway</label>
        <select value={filters.pathway} onChange={(e) => updateField('pathway', e.target.value)}>
          <option value="all">All scenarios</option>
          {scenarioOptions.map((item) => (
            <option key={item.scenario} value={item.scenario}>
              {item.scenario}
            </option>
          ))}
        </select>
      </div>

      <div className="toolbar-actions">
        <button type="button" className="ghost" onClick={resetFilters}>
          Reset filters
        </button>
      </div>
    </div>
  );
}
