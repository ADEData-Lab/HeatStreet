import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ScatterChart, Scatter } from 'recharts';
import { retrofitMeasures, retrofitPackages } from '../data/mockData';

export default function RetrofitAnalysis() {
  const windowComparison = retrofitMeasures.filter(m => m.id.includes('glazing'));
  const radiatorMeasure = retrofitMeasures.find(m => m.id === 'rad_upsizing');

  return (
    <div>
      <div className="card">
        <h2 className="card-header">Section 2: Retrofit Measures & Packages</h2>
        <p className="card-description">
          Individual measures with clear cost and savings metadata, plus combinations of measures (packages)
          showing total capex, savings, paybacks, and diminishing returns.
        </p>
      </div>

      <div className="card">
        <h3 className="card-header">Individual Retrofit Measures</h3>
        <p className="card-description">15+ measures catalogued with applicability checks based on property characteristics.</p>
        <table>
          <thead>
            <tr>
              <th>Measure</th>
              <th>Capex (£)</th>
              <th>Annual Saving (£)</th>
              <th>kWh Saving</th>
              <th>CO₂ Saving (t)</th>
              <th>Simple Payback (yrs)</th>
              <th>Discounted Payback (yrs)</th>
            </tr>
          </thead>
          <tbody>
            {retrofitMeasures.filter(m => m.id !== 'rad_upsizing').map((measure) => (
              <tr key={measure.id}>
                <td><strong>{measure.name}</strong></td>
                <td>£{measure.capex.toLocaleString()}</td>
                <td>£{measure.annualSaving.toLocaleString()}</td>
                <td>{measure.kwhSaving.toLocaleString()}</td>
                <td>{measure.co2Saving.toFixed(2)}</td>
                <td>{measure.simplePayback ? measure.simplePayback.toFixed(1) : 'N/A'}</td>
                <td>{measure.discountedPayback ? measure.discountedPayback.toFixed(1) : 'N/A'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3 className="card-header">Section 3: Radiator Upsizing</h3>
        <p className="card-description">
          Radiator upsizing explicitly represented as standalone measure and in combination packages.
          Enables low-temperature heat pump compatibility.
        </p>
        <div className="grid grid-3">
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
            <div className="metric-value">£{radiatorMeasure.capex.toLocaleString()}</div>
            <div className="metric-label">Capex per Home</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
            <div className="metric-value">{radiatorMeasure.flowTempReduction}°C</div>
            <div className="metric-label">Flow Temp Reduction</div>
          </div>
          <div className="metric-card" style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
            <div className="metric-value">Essential</div>
            <div className="metric-label">For HP Operation</div>
          </div>
        </div>
        <div style={{ marginTop: '16px', padding: '12px', background: '#fff3cd', borderRadius: '6px' }}>
          <p style={{ margin: 0 }}>
            <strong>Note:</strong> {radiatorMeasure.note}. This measure has no direct energy savings
            but enables 10°C lower flow temperature, critical for heat pump efficiency.
          </p>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Section 4: Window Upgrades (Double vs Triple Glazing)</h3>
        <p className="card-description">Direct comparison of double and triple glazing impacts on cost, savings, and payback.</p>
        <div className="grid grid-2">
          <div>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={windowComparison}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis yAxisId="left" />
                <YAxis yAxisId="right" orientation="right" />
                <Tooltip />
                <Legend />
                <Bar yAxisId="left" dataKey="capex" fill="#667eea" name="Capex (£)" />
                <Bar yAxisId="right" dataKey="annualSaving" fill="#43e97b" name="Annual Saving (£)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div>
            <table>
              <thead>
                <tr>
                  <th>Glazing Type</th>
                  <th>Capex (£)</th>
                  <th>kWh Saving</th>
                  <th>Payback (yrs)</th>
                </tr>
              </thead>
              <tbody>
                {windowComparison.map((measure) => (
                  <tr key={measure.id}>
                    <td><strong>{measure.name}</strong></td>
                    <td>£{measure.capex.toLocaleString()}</td>
                    <td>{measure.kwhSaving.toLocaleString()}</td>
                    <td>{measure.simplePayback.toFixed(1)}</td>
                  </tr>
                ))}
                <tr style={{ background: '#f0f7ff', fontWeight: 'bold' }}>
                  <td>Triple vs Double (Marginal)</td>
                  <td>+£{(windowComparison[1].capex - windowComparison[0].capex).toLocaleString()}</td>
                  <td>+{(windowComparison[1].kwhSaving - windowComparison[0].kwhSaving).toLocaleString()}</td>
                  <td>{((windowComparison[1].capex - windowComparison[0].capex) / (windowComparison[1].annualSaving - windowComparison[0].annualSaving)).toFixed(1)}</td>
                </tr>
              </tbody>
            </table>
            <p style={{ marginTop: '12px', fontSize: '0.9rem', color: '#666' }}>
              Marginal benefit analysis shows triple glazing costs £3,000 more for 750 kWh additional savings,
              resulting in same payback period as double glazing upgrade.
            </p>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-header">Section 5: Retrofit Packages & Payback Times</h3>
        <p className="card-description">
          Combinations of measures showing total capex, savings, simple and discounted payback (3.5% discount rate per HM Treasury Green Book).
        </p>
        <table>
          <thead>
            <tr>
              <th>Package</th>
              <th>Measures Included</th>
              <th>Total Capex (£)</th>
              <th>Annual Saving (£)</th>
              <th>kWh Saving</th>
              <th>Simple Payback</th>
              <th>Discounted Payback</th>
            </tr>
          </thead>
          <tbody>
            {retrofitPackages.map((pkg) => (
              <tr key={pkg.id}>
                <td><strong>{pkg.name}</strong></td>
                <td style={{ fontSize: '0.85rem' }}>{pkg.measures ? pkg.measures.join(', ') : 'Single measure'}</td>
                <td>£{pkg.capex.toLocaleString()}</td>
                <td>£{pkg.annualSaving.toLocaleString()}</td>
                <td>{pkg.kwhSaving.toLocaleString()}</td>
                <td>{pkg.simplePayback.toFixed(1)} yrs</td>
                <td>{pkg.discountedPayback.toFixed(1)} yrs</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ marginTop: '20px' }}>
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="capex" name="Capex (£)" />
              <YAxis dataKey="simplePayback" name="Payback (years)" />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} />
              <Legend />
              <Scatter name="Retrofit Packages" data={retrofitPackages} fill="#667eea" />
            </ScatterChart>
          </ResponsiveContainer>
        </div>

        <div style={{ marginTop: '16px', padding: '12px', background: '#f0f7ff', borderRadius: '6px' }}>
          <p style={{ margin: 0 }}>
            <strong>Diminishing Returns Visible:</strong> The "Value Sweet Spot" package (£3,700) achieves
            61% of maximum kWh savings at only 17% of "Maximum Retrofit" cost. Marginal cost per kWh increases
            sharply beyond this point, demonstrating clear diminishing returns.
          </p>
        </div>
      </div>
    </div>
  );
}
