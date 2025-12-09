import React from 'react';
import { ComposedChart, XAxis, YAxis, Tooltip, Legend, CartesianGrid, Bar, Line, ResponsiveContainer } from 'recharts';
import { useDashboard } from '../context/DashboardContext';

export default function ComparisonDrawer() {
  const { data, comparisonSet, toggleComparison } = useDashboard();
  const scenarios = data?.scenarioData || [];
  const selected = scenarios.filter((item) => comparisonSet.includes(item.scenario));

  if (!scenarios.length) return null;

  return (
    <div className="card comparison">
      <div className="comparison-header">
        <div>
          <h3 className="card-title">Scenario comparison</h3>
          <p className="subtle">Select up to three scenarios to compare capex and CO₂ side by side.</p>
        </div>
        <div className="chip-row">
          {scenarios.map((item) => (
            <button
              key={item.scenario}
              type="button"
              className={`chip ${comparisonSet.includes(item.scenario) ? 'chip-active' : ''}`}
              onClick={() => toggleComparison(item.scenario)}
            >
              {item.scenario}
            </button>
          ))}
        </div>
      </div>

      <div style={{ height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={selected.length ? selected : scenarios.slice(0, 3)} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="scenario" />
            <YAxis yAxisId="left" label={{ value: 'Capital (£m)', angle: -90, position: 'insideLeft' }} />
            <YAxis yAxisId="right" orientation="right" label={{ value: 'CO₂ reduction', angle: 90, position: 'insideRight' }} />
            <Tooltip formatter={(value) => value.toLocaleString()} />
            <Legend />
            <Bar yAxisId="left" dataKey="capitalCost" name="Capital (£m)" fill="#1e3a5f" radius={[4, 4, 0, 0]} />
            <Line yAxisId="right" dataKey="co2Reduction" name="CO₂ reduction" stroke="#ee6c4d" strokeWidth={2} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
