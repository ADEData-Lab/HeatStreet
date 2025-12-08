import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, LineChart, Line, Area, AreaChart } from 'recharts';
import { pathwayResults, tippingPointData, heatNetworkTiers } from '../data/mockData';

export default function PathwaysAnalysis() {
  const pathwaysForChart = pathwayResults.filter(p => p.id !== 'baseline');

  return (
    <div>
      <div className="card">
        <h2 className="card-header">Section 6: Pathways & Hybrid Scenarios</h2>
        <p className="card-description">
          Five distinct pathways with per-home and aggregate metrics: baseline, fabric-only, fabric+HP, fabric+HN, and hybrid (HN where available, HP elsewhere).
        </p>
      </div>

      <div className="card">
        <h3 className="card-header">Complete Pathway Comparison</h3>
        <table>
          <thead>
            <tr>
              <th>Pathway</th>
              <th>Total Capex (£M)</th>
              <th>Capex per Property (£)</th>
              <th>Annual Bill Savings (£M)</th>
              <th>Per Property (£/yr)</th>
              <th>CO₂ Reduction (tonnes)</th>
              <th>Payback (years)</th>
            </tr>
          </thead>
          <tbody>
            {pathwayResults.map((pathway) => (
              <tr key={pathway.id} style={{ background: pathway.id === 'baseline' ? '#f9f9f9' : 'white' }}>
                <td><strong>{pathway.name}</strong></td>
                <td>£{(pathway.capex / 1000000).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                <td>£{pathway.capexPerProperty.toLocaleString()}</td>
                <td>£{(pathway.annualBillSavings / 1000000).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                <td>£{pathway.annualBillSavingsPerProperty.toLocaleString()}</td>
                <td>{pathway.co2Reduction.toLocaleString()}</td>
                <td>{pathway.payback > 0 ? pathway.payback.toFixed(1) : 'N/A'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-header">Capex Comparison (per property)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={pathwaysForChart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" angle={-15} textAnchor="end" height={100} />
              <YAxis />
              <Tooltip formatter={(value) => `£${value.toLocaleString()}`} />
              <Bar dataKey="capexPerProperty" fill="#667eea" name="Capex (£)" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3 className="card-header">Annual CO₂ Reduction</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={pathwaysForChart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" angle={-15} textAnchor="end" height={100} />
              <YAxis />
              <Tooltip formatter={(value) => `${value.toLocaleString()} tonnes`} />
              <Bar dataKey="co2Reduction" fill="#43e97b" name="CO₂ Reduction (tonnes)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Hybrid Pathway Cost Breakdown</h3>
        <p className="card-description">
          The hybrid pathway correctly combines fabric package costs with heat technology costs (HP for non-HN properties, HN connection for HN-eligible properties).
          Code includes assertion to verify hybrid_cost &gt; fabric_only_cost when additional_capex &gt; 0.
        </p>
        <div className="grid grid-4">
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
            <div className="metric-value">£{pathwayResults.find(p => p.id === 'hybrid').capexPerProperty.toLocaleString()}</div>
            <div className="metric-label">Hybrid Capex per Property</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
            <div className="metric-value">£{pathwayResults.find(p => p.id === 'fabric_only').capexPerProperty.toLocaleString()}</div>
            <div className="metric-label">Fabric Only Capex</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
            <div className="metric-value">£{(pathwayResults.find(p => p.id === 'hybrid').capexPerProperty - pathwayResults.find(p => p.id === 'fabric_only').capexPerProperty).toLocaleString()}</div>
            <div className="metric-label">Additional Heat Tech Cost</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)' }}>
            <div className="metric-value">{pathwayResults.find(p => p.id === 'hybrid').payback.toFixed(1)}</div>
            <div className="metric-label">Payback (years)</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Section 8: Fabric Tipping Point Curve</h3>
        <p className="card-description">
          Cumulative fabric investment vs cumulative kWh saved, showing where marginal cost per kWh increases sharply.
        </p>
        <ResponsiveContainer width="100%" height={400}>
          <AreaChart data={tippingPointData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="cumulativeCapex" name="Cumulative Capex (£)" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Area
              type="monotone"
              dataKey="cumulativeKWh"
              fill="#667eea"
              stroke="#667eea"
              name="Cumulative kWh Saved"
            />
          </AreaChart>
        </ResponsiveContainer>

        <div style={{ marginTop: '20px' }}>
          <h4>Marginal Cost Analysis</h4>
          <table>
            <thead>
              <tr>
                <th>Measure</th>
                <th>Cumulative Capex (£)</th>
                <th>Cumulative kWh Saved</th>
                <th>Marginal Cost (£/kWh)</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {tippingPointData.filter(d => d.step > 0).map((item) => (
                <tr key={item.step} style={{ background: item.beyondTippingPoint ? '#fff3cd' : 'white' }}>
                  <td><strong>{item.measure}</strong></td>
                  <td>£{item.cumulativeCapex.toLocaleString()}</td>
                  <td>{item.cumulativeKWh.toLocaleString()}</td>
                  <td>£{item.marginalCost.toFixed(2)}</td>
                  <td>
                    <span className={`badge badge-${item.beyondTippingPoint ? 'warning' : 'success'}`}>
                      {item.beyondTippingPoint ? 'Beyond Tipping Point' : 'Cost Effective'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: '16px', padding: '12px', background: '#fff3cd', borderRadius: '6px' }}>
          <p style={{ margin: 0 }}>
            <strong>Tipping Point Identified:</strong> Marginal cost per kWh saved exceeds 2× minimum after
            Floor Insulation (£1.33/kWh). Double glazing shows particularly poor marginal cost effectiveness (£4.00/kWh),
            suggesting fabric measures should be prioritized in order of cost-effectiveness.
          </p>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Heat Network Tier Classification</h3>
        <p className="card-description">
          Properties classified by heat density and proximity to existing networks, informing pathway suitability.
        </p>
        <table>
          <thead>
            <tr>
              <th>Tier</th>
              <th>Properties</th>
              <th>Percentage</th>
              <th>Recommended Pathway</th>
            </tr>
          </thead>
          <tbody>
            {heatNetworkTiers.map((tier, idx) => (
              <tr key={idx}>
                <td><strong>{tier.tier}</strong></td>
                <td>{tier.properties.toLocaleString()}</td>
                <td>{tier.percentage}%</td>
                <td>{tier.recommendation}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ marginTop: '16px' }}>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={heatNetworkTiers}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="tier" angle={-15} textAnchor="end" height={120} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="percentage" fill="#764ba2" name="Percentage (%)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
