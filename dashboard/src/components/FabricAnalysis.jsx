import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { fabricAnalysis, tenureBreakdown } from '../data/mockData';

const COLORS = ['#667eea', '#764ba2', '#f093fb', '#f5576c', '#4facfe', '#00f2fe', '#43e97b', '#38f9d7'];

export default function FabricAnalysis() {
  return (
    <div>
      <div className="card">
        <h2 className="card-header">Section 1: Fabric Detail Granularity</h2>
        <p className="card-description">
          Detailed analysis of building fabric characteristics including wall types, insulation status,
          roof insulation thickness, floor insulation, glazing types, and ventilation systems.
        </p>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-header">Wall Type Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={fabricAnalysis.wallTypes}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="type" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="percentage" fill="#667eea" name="Percentage (%)" />
            </BarChart>
          </ResponsiveContainer>
          <div style={{ marginTop: '16px' }}>
            {fabricAnalysis.wallTypes.map((item, idx) => (
              <div key={idx} className="stat-box">
                <strong>{item.type}:</strong> {item.count.toLocaleString()} properties ({item.percentage}%)
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3 className="card-header">Wall Insulation Status</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={fabricAnalysis.wallInsulation}
                dataKey="percentage"
                nameKey="status"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry) => `${entry.status}: ${entry.percentage}%`}
              >
                {fabricAnalysis.wallInsulation.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
          <div style={{ marginTop: '16px' }}>
            <div className="stat-box">
              <strong>Insulated:</strong> {((100 - fabricAnalysis.wallInsulation[0].percentage)).toFixed(1)}%
            </div>
            <div className="stat-box">
              <strong>Uninsulated:</strong> {fabricAnalysis.wallInsulation[0].percentage}%
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Roof Insulation Analysis</h3>
        <div className="grid grid-3">
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
            <div className="metric-value">{fabricAnalysis.roofInsulation.median}mm</div>
            <div className="metric-label">Median Thickness</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
            <div className="metric-value">{fabricAnalysis.roofInsulation.below100mm}%</div>
            <div className="metric-label">Below 100mm</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
            <div className="metric-value">{fabricAnalysis.roofInsulation.below150mm}%</div>
            <div className="metric-label">Below 150mm</div>
          </div>
        </div>
        <div style={{ marginTop: '20px' }}>
          <p><strong>Distribution:</strong></p>
          <div className="stat-box">Q1 (25th percentile): {fabricAnalysis.roofInsulation.q1}mm</div>
          <div className="stat-box">Median (50th percentile): {fabricAnalysis.roofInsulation.median}mm</div>
          <div className="stat-box">Q3 (75th percentile): {fabricAnalysis.roofInsulation.q3}mm</div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-header">Glazing Type Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={fabricAnalysis.glazingTypes}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="type" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#764ba2" name="Property Count" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3 className="card-header">Section 7: EPC Anomalies</h3>
          <p className="card-description">Properties with inconsistent fabric quality vs EPC ratings.</p>
          <div className="grid grid-2" style={{ marginTop: '16px' }}>
            <div className="metric-card" style={{ background: 'linear-gradient(135deg, #FF8042 0%, #FF6B6B 100%)' }}>
              <div className="metric-value">{fabricAnalysis.anomalies.total.toLocaleString()}</div>
              <div className="metric-label">Total Anomalies</div>
            </div>
            <div className="metric-card" style={{ background: 'linear-gradient(135deg, #FFA726 0%, #FB8C00 100%)' }}>
              <div className="metric-value">{fabricAnalysis.anomalies.percentage}%</div>
              <div className="metric-label">Anomaly Rate</div>
            </div>
          </div>
          <div style={{ marginTop: '16px' }}>
            <div className="stat-box">
              <strong>Poor Fabric, Good EPC:</strong> {fabricAnalysis.anomalies.poorFabricGoodEPC.toLocaleString()} properties
            </div>
            <div className="stat-box">
              <strong>Good Fabric, Poor EPC:</strong> {fabricAnalysis.anomalies.goodFabricPoorEPC.toLocaleString()} properties
            </div>
            <p style={{ marginTop: '12px', fontSize: '0.9rem', color: '#666' }}>
              These properties are flagged with ±30% uncertainty ranges (vs ±20% standard) to account for EPC measurement limitations.
            </p>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Section 11: Tenure Breakdown</h3>
        <p className="card-description">Analysis segmented by property tenure for targeted policy interventions.</p>
        <table>
          <thead>
            <tr>
              <th>Tenure Type</th>
              <th>Properties</th>
              <th>Percentage</th>
              <th>Avg EPC Band</th>
              <th>Median SAP Score</th>
            </tr>
          </thead>
          <tbody>
            {tenureBreakdown.map((item, idx) => (
              <tr key={idx}>
                <td><strong>{item.tenure}</strong></td>
                <td>{item.properties.toLocaleString()}</td>
                <td>{item.percentage}%</td>
                <td>
                  <span className={`badge badge-${item.avgEPCBand === 'C' ? 'success' : 'warning'}`}>
                    Band {item.avgEPCBand}
                  </span>
                </td>
                <td>{item.medianSAP}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: '16px', padding: '12px', background: '#f0f7ff', borderRadius: '6px' }}>
          <p style={{ margin: 0, fontSize: '0.9rem' }}>
            <strong>Key Finding:</strong> Owner-occupied properties represent 60.3% of the sample and show slightly better
            energy performance (median SAP 65) compared to private rented (SAP 62), suggesting tenure-specific policy approaches may be needed.
          </p>
        </div>
      </div>
    </div>
  );
}
