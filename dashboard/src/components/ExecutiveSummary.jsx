import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { executiveSummary, pathwayResults } from '../data/mockData';

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', '#82CA9D', '#FFC658'];

export default function ExecutiveSummary() {
  const epcData = Object.entries(executiveSummary.epcBands).map(([band, data]) => ({
    band,
    count: data.count,
    percentage: data.percentage
  }));

  const topPathways = pathwayResults.slice(1, 4); // Exclude baseline

  return (
    <div>
      <div className="card">
        <h2 className="card-header">Executive Summary</h2>
        <p className="card-description">
          Comprehensive analysis of {executiveSummary.totalProperties.toLocaleString()} Edwardian terraced properties across selected constituencies.
          This dashboard addresses all client requirements for fabric analysis, retrofit measures, pathways, and sensitivity analysis.
        </p>

        <div className="grid grid-4" style={{ marginTop: '20px' }}>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
            <div className="metric-value">{executiveSummary.totalProperties.toLocaleString()}</div>
            <div className="metric-label">Total Properties</div>
          </div>

          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
            <div className="metric-value">{executiveSummary.avgSAPScore}</div>
            <div className="metric-label">Average SAP Score</div>
          </div>

          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
            <div className="metric-value">{executiveSummary.wallInsulationRate}%</div>
            <div className="metric-label">Wall Insulation Rate</div>
          </div>

          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)' }}>
            <div className="metric-value">Band {Object.entries(executiveSummary.epcBands).reduce((a, b) => a[1].count > b[1].count ? a : b)[0]}</div>
            <div className="metric-label">Most Common EPC Band</div>
          </div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-header">EPC Band Distribution</h3>
          <p className="card-description">Distribution of Energy Performance Certificate ratings across the property sample.</p>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={epcData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="band" />
              <YAxis />
              <Tooltip formatter={(value) => value.toLocaleString()} />
              <Legend />
              <Bar dataKey="count" fill="#667eea" name="Property Count" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3 className="card-header">EPC Band Percentage Share</h3>
          <p className="card-description">Proportion of properties in each EPC rating category.</p>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={epcData}
                dataKey="percentage"
                nameKey="band"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry) => `${entry.band}: ${entry.percentage}%`}
              >
                {epcData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Pathway Comparison Summary</h3>
        <p className="card-description">High-level comparison of decarbonization pathways excluding baseline scenario.</p>
        <table>
          <thead>
            <tr>
              <th>Pathway</th>
              <th>Total Capex (£M)</th>
              <th>Per Property (£)</th>
              <th>Annual Bill Savings (£M)</th>
              <th>CO₂ Reduction (tonnes)</th>
              <th>Payback (years)</th>
            </tr>
          </thead>
          <tbody>
            {topPathways.map((pathway) => (
              <tr key={pathway.id}>
                <td><strong>{pathway.name}</strong></td>
                <td>£{(pathway.capex / 1000000).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                <td>£{pathway.capexPerProperty.toLocaleString()}</td>
                <td>£{(pathway.annualBillSavings / 1000000).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                <td>{pathway.co2Reduction.toLocaleString()}</td>
                <td>{pathway.payback.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
