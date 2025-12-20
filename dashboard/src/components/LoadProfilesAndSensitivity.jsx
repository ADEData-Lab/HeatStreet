import React from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { loadProfiles, sensitivityAnalysis, epcDistribution } from '../data/mockData';

export default function LoadProfilesAndSensitivity() {
  return (
    <div>
      <div className="card">
        <h2 className="card-header">Section 9: Load Profiles & System Impacts</h2>
        <p className="card-description">
          Time series demand profiles (hourly/daily) for each pathway, with peak kW, average kW, and peak-to-average ratios.
          Street-level aggregates account for diversity factors.
        </p>
      </div>

      <div className="card">
        <h3 className="card-header">Hourly Heat Demand Profile (Typical Winter Day)</h3>
        <p className="card-description">Stylized 24-hour profile based on UK domestic heating patterns (morning/evening peaks).</p>
        <ResponsiveContainer width="100%" height={400}>
          <LineChart data={loadProfiles.hourly}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" label={{ value: 'Hour of Day', position: 'insideBottom', offset: -5 }} />
            <YAxis label={{ value: 'Heat Demand (kW)', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="baseline" stroke="#8884d8" name="Baseline" strokeWidth={2} />
            <Line type="monotone" dataKey="fabricOnly" stroke="#82ca9d" name="Fabric Only" strokeWidth={2} />
            <Line type="monotone" dataKey="heatPump" stroke="#ffc658" name="Heat Pump" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h3 className="card-header">Load Profile Summary Metrics</h3>
        <table>
          <thead>
            <tr>
              <th>Pathway</th>
              <th>Peak kW per Home</th>
              <th>Average kW per Home</th>
              <th>Peak-to-Average Ratio</th>
            </tr>
          </thead>
          <tbody>
            {loadProfiles.summary.map((item, idx) => (
              <tr key={idx}>
                <td><strong>{item.pathway}</strong></td>
                <td>{item.peakKW.toFixed(2)}</td>
                <td>{item.avgKW.toFixed(2)}</td>
                <td>{item.peakToAvgRatio.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ marginTop: '20px' }}>
          <div className="grid grid-3">
            <div className="metric-card" style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
              <div className="metric-value">{((loadProfiles.summary[0].peakKW - loadProfiles.summary[2].peakKW) / loadProfiles.summary[0].peakKW * 100).toFixed(1)}%</div>
              <div className="metric-label">Peak Demand Reduction (HP vs Baseline)</div>
            </div>
            <div className="metric-card" style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
              <div className="metric-value">{((loadProfiles.summary[0].avgKW - loadProfiles.summary[2].avgKW) / loadProfiles.summary[0].avgKW * 100).toFixed(1)}%</div>
              <div className="metric-label">Average Demand Reduction</div>
            </div>
            <div className="metric-card" style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
              <div className="metric-value">Low</div>
              <div className="metric-label">Grid Reinforcement Risk</div>
            </div>
          </div>
        </div>

        <div style={{ marginTop: '16px', padding: '12px', background: '#f0f7ff', borderRadius: '6px' }}>
          <p style={{ margin: 0 }}>
            <strong>Grid Impact Assessment:</strong> With fabric improvements, peak demand is reduced by 28.6%.
            Heat pumps show similar peak-to-average ratios (1.88) as baseline (1.83), suggesting manageable grid impacts
            when combined with fabric efficiency measures. Street-level diversity factors further reduce simultaneous peak demand.
          </p>
        </div>
      </div>

      <div className="card">
        <h2 className="card-header">Section 10: Heat Network Penetration & Price Sensitivity</h2>
        <p className="card-description">
          Sensitivity analysis varying HN share (0.2%, 0.5%, 1%, 2%, 5%, 10%) and price scenarios (baseline, low, high, projected 2030).
        </p>
      </div>

      <div className="card">
        <h3 className="card-header">Sensitivity Tornado Chart</h3>
        <p className="card-description">Impact of key uncertain parameters on annual household energy costs (base case: £800/year).</p>
        <ResponsiveContainer width="100%" height={400}>
          <BarChart
            data={sensitivityAnalysis.parameters}
            layout="vertical"
            margin={{ left: 150 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" domain={[0, 1200]} />
            <YAxis type="category" dataKey="parameter" />
            <Tooltip />
            <Legend />
            <Bar dataKey="impactLow" fill="#82ca9d" name="Low Impact (£/yr)" />
            <Bar dataKey="impactHigh" fill="#ff8042" name="High Impact (£/yr)" />
          </BarChart>
        </ResponsiveContainer>

        <div style={{ marginTop: '20px' }}>
          <h4>Parameter Sensitivity Rankings</h4>
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Parameter</th>
                <th>Low Value</th>
                <th>High Value</th>
                <th>Sensitivity Range (£/yr)</th>
              </tr>
            </thead>
            <tbody>
              {sensitivityAnalysis.parameters
                .sort((a, b) => b.sensitivityRange - a.sensitivityRange)
                .map((param, idx) => (
                  <tr key={idx}>
                    <td><strong>#{idx + 1}</strong></td>
                    <td>{param.parameter}</td>
                    <td>{param.lowValue}</td>
                    <td>{param.highValue}</td>
                    <td>
                      <span className={`badge badge-${idx < 2 ? 'danger' : idx < 4 ? 'warning' : 'success'}`}>
                        £{param.sensitivityRange}
                      </span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: '16px', padding: '12px', background: '#fff3cd', borderRadius: '6px' }}>
          <p style={{ margin: 0 }}>
            <strong>Key Findings:</strong> Gas and electricity prices show highest sensitivity (£450/yr range each),
            demonstrating that energy pricing policy has greater impact on household costs than technical parameters like heat pump COP (£250 range)
            or fabric costs (£75 range). This suggests policy interventions on energy pricing may be most impactful for affordability.
          </p>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Price Scenario Overview</h3>
        <div className="grid grid-4">
          <div className="stat-box">
            <strong>Baseline:</strong>
            <p>Gas: 6.24p/kWh, Elec: 24.5p/kWh, HN: 8p/kWh</p>
          </div>
          <div className="stat-box">
            <strong>Low:</strong>
            <p>Gas: 5p/kWh, Elec: 20p/kWh, HN: 6p/kWh</p>
          </div>
          <div className="stat-box">
            <strong>High:</strong>
            <p>Gas: 8p/kWh, Elec: 30p/kWh, HN: 10p/kWh</p>
          </div>
          <div className="stat-box">
            <strong>Projected 2030:</strong>
            <p>Gas: 7p/kWh, Elec: 22p/kWh, HN: 7p/kWh</p>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="card-header">Uncertainty & Representativeness</h2>
        <p className="card-description">
          EPC data validation showing Shakespeare Crescent sample representativeness vs benchmark and national pre-1930 terraced homes.
        </p>
      </div>

      <div className="card">
        <h3 className="card-header">EPC Band Distribution Comparison</h3>
        <ResponsiveContainer width="100%" height={400}>
          <BarChart data={epcDistribution}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="band" />
            <YAxis label={{ value: 'Percentage (%)', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="shakespeareCrescent" fill="#667eea" name="Shakespeare Crescent" />
            <Bar dataKey="londonPre1930" fill="#82ca9d" name="Benchmark pre-1930 terraced" />
            <Bar dataKey="national" fill="#ffc658" name="National Pre-1930 Terraced" />
          </BarChart>
        </ResponsiveContainer>

        <div style={{ marginTop: '16px', padding: '12px', background: '#d4edda', borderRadius: '6px' }}>
          <p style={{ margin: 0 }}>
            <strong>Sample Representativeness:</strong> Shakespeare Crescent shows higher proportion of Band C properties (57.1% vs 42.3% benchmark average),
            indicating a slightly better-performing sample. However, the C/D band distribution (57.1% / 42.9%) aligns reasonably well with the benchmark
            pre-1930 terraced stock (42.3% / 47.9%), supporting the use of this sample as a representative case study for Edwardian terraced properties.
          </p>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Uncertainty Quantification</h3>
        <div className="grid grid-3">
          <div className="stat-box">
            <strong>Standard Uncertainty:</strong>
            <p>±20% around nominal demand</p>
            <p style={{ fontSize: '0.85rem', color: '#666' }}>Based on EPC measurement error research (Crawley et al., 2019)</p>
          </div>
          <div className="stat-box">
            <strong>Anomaly Uncertainty:</strong>
            <p>±30% for flagged properties</p>
            <p style={{ fontSize: '0.85rem', color: '#666' }}>Higher uncertainty for poor fabric/good EPC inconsistencies</p>
          </div>
          <div className="stat-box">
            <strong>SAP Score Uncertainty:</strong>
            <p>±2.4° to ±8.0° by band</p>
            <p style={{ fontSize: '0.85rem', color: '#666' }}>Temperature uncertainty varies with EPC rating</p>
          </div>
        </div>
      </div>
    </div>
  );
}
