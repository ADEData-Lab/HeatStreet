import React from 'react';
import { useDashboard } from '../context/DashboardContext';

export default function FilterBar() {
  const { filters, setFilters, resetFilters, rawData } = useDashboard();
  const constituencyOptions = rawData?.constituencyData || [];
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
          placeholder="Search constituencies, scenarios, notes"
        />
      </div>

      <div className="toolbar-group">
        <label className="toolbar-label">Constituency</label>
        <select value={filters.constituency} onChange={(e) => updateField('constituency', e.target.value)}>
          <option value="all">All constituencies</option>
          {constituencyOptions.map((item) => (
            <option key={item.constituency_name || item.constituency} value={item.constituency_name || item.constituency}>
              {item.constituency_name || item.constituency}
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
