import React, { useState } from 'react';
import {
  BarChart, Bar, PieChart, Pie, LineChart, Line, AreaChart, Area,
  ComposedChart, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Cell, ReferenceLine
} from 'recharts';
import {
  epcBandData,
  epcComparisonData,
  wallTypeData,
  heatingSystemData,
  scenarioData,
  tierData,
  retrofitReadinessData,
  interventionData,
  boroughData,
  confidenceBandsData,
  sensitivityData,
  gridPeakData,
  indoorClimateData,
  costLeversData,
  loftInsulationData,
  costBenefitTierData,
  costCurveData,
  glazingData,
  summaryStats
} from '../data/dashboardData';

// Color Palette (Section 2)
const COLORS = {
  primary: '#1e3a5f',
  secondary: '#3d5a80',
  accent: '#ee6c4d',
  success: '#40916c',
  warning: '#f4a261',
  danger: '#d62828',
  light: '#f8f9fa',
  muted: '#6c757d',
};

const EPC_COLORS = {
  A: '#1a472a',
  B: '#2d6a4f',
  C: '#40916c',
  D: '#f4a261',
  E: '#e76f51',
  F: '#d62828',
  G: '#9d0208',
};

const TIER_COLORS = ['#40916c', '#52b788', '#f4a261', '#e76f51', '#d62828'];
const PIE_COLORS = ['#1e3a5f', '#3d5a80', '#5c7a99', '#7b9ab3'];

export default function HeatStreetDashboard() {
  const [activeTab, setActiveTab] = useState('overview');

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'housing', label: 'Housing Stock' },
    { id: 'scenarios', label: 'Scenarios' },
    { id: 'readiness', label: 'Retrofit Readiness' },
    { id: 'costbenefit', label: 'Cost-Benefit' },
    { id: 'boroughs', label: 'Boroughs' },
    { id: 'casestreet', label: 'Case Street' },
    { id: 'uncertainty', label: 'Uncertainty' },
    { id: 'grid', label: 'Grid & Climate' },
    { id: 'policy', label: 'Policy' },
  ];

  // Styles
  const styles = {
    container: {
      fontFamily: "'Source Sans Pro', -apple-system, BlinkMacSystemFont, sans-serif",
      backgroundColor: '#f5f6f8',
      color: COLORS.primary,
      minHeight: '100vh',
    },
    header: {
      background: 'linear-gradient(135deg, #1e3a5f 0%, #3d5a80 100%)',
      color: 'white',
      padding: '32px 24px',
      textAlign: 'center',
    },
    headerTitle: {
      fontSize: '2.25rem',
      fontWeight: 700,
      marginBottom: '8px',
      letterSpacing: '-0.5px',
      margin: 0,
    },
    headerSubtitle: {
      fontSize: '1.1rem',
      opacity: 0.9,
      margin: '8px 0',
    },
    headerMeta: {
      fontSize: '0.875rem',
      opacity: 0.7,
      margin: '4px 0',
    },
    nav: {
      display: 'flex',
      justifyContent: 'center',
      gap: '4px',
      padding: '16px 24px',
      backgroundColor: 'white',
      borderBottom: '1px solid #e2e8f0',
      flexWrap: 'wrap',
    },
    navButton: {
      padding: '10px 18px',
      border: 'none',
      borderRadius: '6px',
      cursor: 'pointer',
      fontSize: '0.875rem',
      fontWeight: 600,
      transition: 'all 0.2s ease',
    },
    navButtonActive: {
      backgroundColor: COLORS.primary,
      color: 'white',
    },
    navButtonInactive: {
      backgroundColor: 'transparent',
      color: COLORS.secondary,
    },
    content: {
      maxWidth: '1400px',
      margin: '0 auto',
      padding: '24px',
    },
    card: {
      backgroundColor: 'white',
      borderRadius: '12px',
      padding: '24px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
      border: '1px solid #e2e8f0',
      marginBottom: '20px',
    },
    cardTitle: {
      fontSize: '1rem',
      fontWeight: 700,
      color: COLORS.primary,
      marginBottom: '16px',
      marginTop: 0,
    },
    statCard: {
      backgroundColor: 'white',
      borderRadius: '12px',
      padding: '20px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
      border: '1px solid #e2e8f0',
      textAlign: 'center',
    },
    statValue: {
      fontSize: '2rem',
      fontWeight: 700,
      color: COLORS.primary,
      marginBottom: '4px',
    },
    statLabel: {
      fontSize: '0.875rem',
      color: COLORS.muted,
    },
    highlight: {
      backgroundColor: '#fff8e6',
      borderLeft: '4px solid #f4a261',
      padding: '16px 20px',
      borderRadius: '0 8px 8px 0',
      marginBottom: '20px',
    },
    highlightTitle: {
      fontWeight: 700,
      color: COLORS.primary,
      marginBottom: '8px',
      marginTop: 0,
    },
    grid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
      gap: '20px',
      marginBottom: '24px',
    },
    statsGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
      gap: '16px',
      marginBottom: '24px',
    },
    sectionTitle: {
      fontSize: '1.5rem',
      fontWeight: 700,
      color: COLORS.primary,
      marginBottom: '20px',
      paddingBottom: '12px',
      borderBottom: '2px solid #e2e8f0',
    },
    table: {
      width: '100%',
      borderCollapse: 'collapse',
      fontSize: '0.875rem',
    },
    th: {
      textAlign: 'left',
      padding: '12px 16px',
      backgroundColor: '#f8f9fa',
      borderBottom: '2px solid #e2e8f0',
      fontWeight: 600,
      color: COLORS.primary,
    },
    td: {
      padding: '12px 16px',
      borderBottom: '1px solid #e2e8f0',
    },
    badge: {
      display: 'inline-block',
      padding: '4px 10px',
      borderRadius: '20px',
      fontSize: '0.75rem',
      fontWeight: 600,
    },
    footer: {
      textAlign: 'center',
      padding: '24px',
      color: COLORS.muted,
      fontSize: '0.875rem',
      borderTop: '1px solid #e2e8f0',
      marginTop: '40px',
    },
  };

  // Helper Components
  const StatCard = ({ value, label }) => (
    <div style={styles.statCard}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  );

  const Card = ({ title, children }) => (
    <div style={styles.card}>
      {title && <h3 style={styles.cardTitle}>{title}</h3>}
      {children}
    </div>
  );

  const HighlightBox = ({ title, text }) => (
    <div style={styles.highlight}>
      {title && <h4 style={styles.highlightTitle}>{title}</h4>}
      <p style={{ margin: 0 }}>{text}</p>
    </div>
  );

  const PolicyCard = ({ title, text, color }) => (
    <div style={{
      padding: '16px',
      borderRadius: '8px',
      borderLeft: `4px solid ${color}`,
      marginBottom: '12px',
      backgroundColor: `${color}10`,
    }}>
      <h4 style={{ marginTop: 0, marginBottom: '8px', color: COLORS.primary }}>{title}</h4>
      <p style={{ margin: 0, fontSize: '0.875rem' }}>{text}</p>
    </div>
  );

  const Badge = ({ type, children }) => {
    const colors = {
      success: { background: '#d4edda', color: '#155724' },
      warning: { background: '#fff3cd', color: '#856404' },
      danger: { background: '#f8d7da', color: '#721c24' },
    };
    const style = colors[type] || colors.success;
    return (
      <span style={{ ...styles.badge, ...style }}>{children}</span>
    );
  };

  // Tab Content Components
  const OverviewTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Executive Summary</h2>

      <div style={styles.statsGrid}>
        <StatCard value="704,483" label="Properties Analysed" />
        <StatCard value="63.4" label="Mean SAP Score" />
        <StatCard value="33.7%" label="Wall Insulation Rate" />
        <StatCard value="235,989" label="DH-Viable Properties" />
        <StatCard value="95.8%" label="Gas Boiler Dependency" />
        <StatCard value="67.8%" label="Below Band C (MEES)" />
      </div>

      <HighlightBox
        title="Key Finding: Heat Network Viability"
        text="Approximately one-third of London's Edwardian terraces (33.5%) sit in heat-network-viable zones. In these areas, district heating could deliver decarbonisation at £9,070 lower cost per property compared to individual heat pump installations (£29,479 vs £38,549), while reducing peak grid demand by 85%."
      />

      <div style={styles.grid}>
        <Card title="EPC Band Distribution">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={epcBandData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="band" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
              <Tooltip formatter={(value) => value.toLocaleString()} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {epcBandData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
            Band D dominates at 52.5% • 67.8% below proposed 2030 MEES threshold
          </p>
        </Card>

        <Card title="Heating System Distribution">
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={heatingSystemData}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                dataKey="value"
                label={({ name, value }) => `${name}: ${value}%`}
              >
                {heatingSystemData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card title="Heat Network Zone Classification">
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie
              data={tierData}
              cx="50%"
              cy="50%"
              outerRadius={100}
              dataKey="percentage"
              label={({ tier, percentage }) => `${percentage}%`}
            >
              {tierData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={TIER_COLORS[index % TIER_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );

  const HousingStockTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Housing Stock Characterisation</h2>

      <div style={styles.statsGrid}>
        <StatCard value="231 kWh/m²" label="Mean Energy Consumption" />
        <StatCard value="62.5%" label="Solid Brick Walls" />
        <StatCard value="86.1%" label="Need Loft Work" />
        <StatCard value="95.8%" label="Gas Heated" />
      </div>

      <Card>
        <HighlightBox
          title="Critical Finding: Solid brick walls represent 62.5% of stock"
          text="With only 3.2% insulated — this is the single largest fabric deficiency."
        />

        <h4 style={styles.cardTitle}>Wall Construction Analysis</h4>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Wall Type</th>
              <th style={styles.th}>% of Stock</th>
              <th style={styles.th}>Insulation Rate</th>
            </tr>
          </thead>
          <tbody>
            {wallTypeData.map((row, idx) => (
              <tr key={idx}>
                <td style={styles.td}>{row.type}</td>
                <td style={styles.td}>{row.percentage}%</td>
                <td style={styles.td}>{row.insulated}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div style={styles.grid}>
        <Card title="Loft Insulation Status">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart layout="vertical" data={loftInsulationData} margin={{ left: 100 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis type="category" dataKey="category" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="percentage" fill={COLORS.secondary} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
            86.1% require loft insulation work
          </p>
        </Card>

        <Card title="Glazing Distribution">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={glazingData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="type" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="percentage" fill={COLORS.accent} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );

  const ScenariosTab = () => {
    const scenarioDisplay = scenarioData.filter(s => s.scenario !== 'Baseline');

    return (
      <div>
        <h2 style={styles.sectionTitle}>Decarbonisation Scenario Modelling</h2>

        <div style={styles.statsGrid}>
          <StatCard value="£9,070" label="Cost Advantage (DH vs HP)" />
          <StatCard value="33.5%" label="DH-Viable Properties" />
          <StatCard value="85%" label="Peak Grid Reduction" />
        </div>

        <Card title="Scenario Comparison">
          <ResponsiveContainer width="100%" height={350}>
            <ComposedChart data={scenarioDisplay}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="scenario" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis yAxisId="left" tick={{ fill: COLORS.muted, fontSize: 11 }} tickFormatter={(v) => `£${(v/1000).toFixed(0)}k`} />
              <YAxis yAxisId="right" orientation="right" tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: 'Payback (years)', angle: 90, position: 'insideRight' }} />
              <Tooltip />
              <Legend />
              <Bar yAxisId="left" dataKey="costPerProperty" fill={COLORS.secondary} name="Cost per Property" />
              <Line yAxisId="right" type="monotone" dataKey="paybackYears" stroke={COLORS.accent} strokeWidth={3} name="Payback Years" />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Scenario Summary">
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Scenario</th>
                <th style={styles.th}>Cost/Property</th>
                <th style={styles.th}>CO₂ Reduction (Mt)</th>
                <th style={styles.th}>Bill Savings</th>
                <th style={styles.th}>Payback</th>
              </tr>
            </thead>
            <tbody>
              {scenarioData.map((row, idx) => (
                <tr key={idx}>
                  <td style={styles.td}>{row.scenario}</td>
                  <td style={styles.td}>£{row.costPerProperty.toLocaleString()}</td>
                  <td style={styles.td}>{(row.co2Reduction / 1000000).toFixed(2)}</td>
                  <td style={styles.td}>£{row.billSavings}/yr</td>
                  <td style={styles.td}>{row.paybackYears > 0 ? `${row.paybackYears.toFixed(1)}yr` : 'N/A'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card>
          <HighlightBox
            title="Heat Network vs Heat Pump Comparison"
            text="£9,070 per property saving with heat networks in viable zones (£33,407 vs £42,477), though heat pumps deliver greater CO₂ reduction. Heat networks reduce peak grid demand by 85%."
          />
        </Card>
      </div>
    );
  };

  const RetrofitReadinessTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Retrofit Readiness Analysis</h2>

      <div style={styles.statsGrid}>
        <StatCard value="£7,710" label="Mean Fabric Pre-requisite Cost" />
        <StatCard value="£22,177" label="Mean Total Retrofit Cost" />
        <StatCard value="37.4%" label="Heat Demand Reduction" />
        <StatCard value="33.3%" label="Ready or Near-Ready" />
      </div>

      <HighlightBox
        text="96.3% of properties require radiator upsizing for efficient heat pump operation — this is the most common intervention needed across the stock."
      />

      <div style={styles.grid}>
        <Card title="Readiness Tier Distribution">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={retrofitReadinessData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="tier" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
              <Tooltip formatter={(value) => value.toLocaleString()} />
              <Bar dataKey="properties" radius={[4, 4, 0, 0]}>
                {retrofitReadinessData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={TIER_COLORS[index]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Average Retrofit Cost by Tier">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={retrofitReadinessData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="tier" tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} tickFormatter={(v) => `£${(v/1000).toFixed(0)}k`} />
              <Tooltip formatter={(value) => `£${value.toLocaleString()}`} />
              <Bar dataKey="avgCost" radius={[4, 4, 0, 0]}>
                {retrofitReadinessData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={TIER_COLORS[index]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card title="Intervention Requirements">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart layout="vertical" data={interventionData} margin={{ left: 120 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis type="number" domain={[0, 100]} tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis type="category" dataKey="intervention" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="percentage" fill={COLORS.accent} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );

  const CostBenefitTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Cost-Benefit Optimisation Analysis</h2>

      <HighlightBox
        title="Key Finding: Diminishing Returns Above £4,500"
        text="The first £4,500 of fabric investment delivers 29 kWh/m² reduction per £1,000 spent. Beyond this threshold, efficiency drops to 7-9 kWh/m² per £1,000 — a 3-4× decrease in cost-effectiveness."
      />

      <div style={styles.statsGrid}>
        <div style={styles.statCard}>
          <div style={styles.statValue}>£4,500</div>
          <div style={styles.statLabel}>Optimal Investment Point</div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statValue}>37.4%</div>
          <div style={styles.statLabel}>Max Heat Demand Reduction</div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statValue}>82%</div>
          <div style={styles.statLabel}>Fewer Cold Days (Full Retrofit)</div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statValue}>33.3%</div>
          <div style={styles.statLabel}>High-Efficiency Stock (Tiers 1-2)</div>
        </div>
      </div>

      <Card title="Fabric Cost vs Heat Demand & Comfort Score">
        <ResponsiveContainer width="100%" height={350}>
          <ComposedChart data={costCurveData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="cost" tick={{ fill: COLORS.muted, fontSize: 11 }} tickFormatter={(v) => `£${(v/1000).toFixed(1)}k`} />
            <YAxis yAxisId="left" domain={[100, 250]} tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: 'Heat Demand (kWh/m²)', angle: -90, position: 'insideLeft' }} />
            <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: 'Comfort Score', angle: 90, position: 'insideRight' }} />
            <Tooltip />
            <Legend />
            <ReferenceLine x={4500} yAxisId="left" stroke={COLORS.success} strokeDasharray="5 5" label={{ value: 'Optimal Zone', fill: COLORS.success, fontSize: 11 }} />
            <Line yAxisId="left" type="monotone" dataKey="heatDemand" stroke={COLORS.primary} strokeWidth={3} dot={{ r: 6 }} name="Heat Demand" />
            <Line yAxisId="right" type="monotone" dataKey="comfort" stroke={COLORS.success} strokeWidth={3} dot={{ r: 6 }} name="Comfort Score" />
          </ComposedChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Steep improvement up to £4,500 • Diminishing returns beyond this threshold
        </p>
      </Card>

      <Card title="Cost Efficiency by Retrofit Tier">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={costBenefitTierData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="tier" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: 'kWh/m² per £1,000', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Bar dataKey="efficiency" radius={[4, 4, 0, 0]}>
              {costBenefitTierData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={index < 2 ? COLORS.success : index < 3 ? COLORS.warning : COLORS.danger} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Green = High efficiency • Yellow = Moderate • Red = Low efficiency
        </p>
      </Card>

      <Card title="Tier-by-Tier Analysis">
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Tier</th>
              <th style={styles.th}>Properties</th>
              <th style={styles.th}>Fabric Cost</th>
              <th style={styles.th}>Heat Demand</th>
              <th style={styles.th}>Reduction</th>
              <th style={styles.th}>Cold Days</th>
              <th style={styles.th}>Efficiency</th>
            </tr>
          </thead>
          <tbody>
            {costBenefitTierData.map((row, idx) => (
              <tr key={idx}>
                <td style={styles.td}>{row.tier} - {row.tierLabel}</td>
                <td style={styles.td}>{row.properties.toLocaleString()} ({row.pct}%)</td>
                <td style={styles.td}>£{row.fabricCost.toLocaleString()}</td>
                <td style={styles.td}>{row.heatDemand} kWh/m²</td>
                <td style={styles.td}>{row.reductionPct}%</td>
                <td style={styles.td}>{row.coldDays}</td>
                <td style={styles.td}>
                  <Badge type={idx < 2 ? 'success' : idx < 3 ? 'warning' : 'danger'}>
                    {row.efficiency.toFixed(1)} kWh/£k
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div style={styles.grid}>
        <PolicyCard
          title="Target Tiers 1-2 First"
          text="33.3% of stock (234,523 properties) offers best ROI at 21-29 kWh/m² per £1,000. Average cost £18,000 for 32% heat demand reduction."
          color={COLORS.success}
        />
        <PolicyCard
          title="Tier 3: Case-by-Case Assessment"
          text="35.7% of stock shows moderate returns. Bundle with heat network connection where viable for improved economics."
          color={COLORS.warning}
        />
        <PolicyCard
          title="Tiers 4-5: Strategic Selection Only"
          text="31% of stock has low efficiency (7-8 kWh/m² per £1,000). Consider only where fuel poverty, conservation, or bulk procurement applies."
          color={COLORS.danger}
        />
        <PolicyCard
          title="Heat Network Opportunity"
          text="33.5% of properties in DH-viable zones. Fabric + DH connection delivers £9,070 lower cost vs individual heat pumps."
          color={COLORS.primary}
        />
      </div>
    </div>
  );

  const BoroughsTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Borough-Level Analysis</h2>

      <Card title="Top 15 Boroughs by Property Count">
        <ResponsiveContainer width="100%" height={400}>
          <BarChart layout="vertical" data={boroughData} margin={{ left: 150 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis type="number" tick={{ fill: COLORS.muted, fontSize: 11 }} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
            <YAxis type="category" dataKey="borough" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <Tooltip formatter={(value) => value.toLocaleString()} />
            <Bar dataKey="count" fill={COLORS.secondary} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          All 33 London boroughs show Band D as modal EPC • Newham hosts case street
        </p>
      </Card>

      <Card title="Borough Statistics">
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Borough</th>
              <th style={styles.th}>Properties</th>
              <th style={styles.th}>Mean EPC</th>
              <th style={styles.th}>Energy (kWh/m²)</th>
            </tr>
          </thead>
          <tbody>
            {boroughData.map((row, idx) => (
              <tr key={idx}>
                <td style={styles.td}>{row.borough}</td>
                <td style={styles.td}>{row.count.toLocaleString()}</td>
                <td style={styles.td}>{row.meanEPC}</td>
                <td style={styles.td}>{row.energy}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );

  const CaseStreetTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Shakespeare Crescent Validation</h2>

      <HighlightBox
        title="Representativeness Confirmed"
        text="Shakespeare Crescent (115 properties) closely matches London-wide characteristics, validating its use as a representative case study."
      />

      <Card>
        <h4 style={styles.cardTitle}>Case Street vs London Comparison</h4>
        <div style={{ ...styles.statsGrid, gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <div style={{ textAlign: 'center', padding: '16px', backgroundColor: '#f8f9fa', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted, marginBottom: '8px' }}>Energy Consumption</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, color: COLORS.primary }}>224 kWh/m²</div>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted }}>Case Street</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, color: COLORS.secondary, marginTop: '8px' }}>231 kWh/m²</div>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted }}>London</div>
          </div>
          <div style={{ textAlign: 'center', padding: '16px', backgroundColor: '#f8f9fa', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted, marginBottom: '8px' }}>Mean SAP Score</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, color: COLORS.primary }}>65.7</div>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted }}>Case Street</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, color: COLORS.secondary, marginTop: '8px' }}>63.4</div>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted }}>London</div>
          </div>
          <div style={{ textAlign: 'center', padding: '16px', backgroundColor: '#f8f9fa', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted, marginBottom: '8px' }}>Band D Proportion</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, color: COLORS.primary }}>42.9%</div>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted }}>Case Street</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, color: COLORS.secondary, marginTop: '8px' }}>52.5%</div>
            <div style={{ fontSize: '0.875rem', color: COLORS.muted }}>London</div>
          </div>
        </div>
      </Card>

      <Card title="EPC Band Comparison">
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={epcComparisonData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="band" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="shakespeareCrescent" fill={COLORS.accent} name="Shakespeare Crescent" />
            <Bar dataKey="londonAverage" fill={COLORS.secondary} name="London Average" />
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Case street performs marginally better than London average
        </p>
      </Card>
    </div>
  );

  const UncertaintyTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Uncertainty & Sensitivity Analysis</h2>

      <Card title="Heat Demand Confidence Bands">
        <ResponsiveContainer width="100%" height={350}>
          <AreaChart data={confidenceBandsData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="stage" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: 'kWh/year', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Area type="monotone" dataKey="upper" stackId="1" stroke={COLORS.primary} fill={COLORS.primary} fillOpacity={0.2} name="Upper Bound" />
            <Area type="monotone" dataKey="estimate" stackId="2" stroke={COLORS.primary} fill={COLORS.primary} fillOpacity={0.6} strokeWidth={3} name="Estimate" />
            <Area type="monotone" dataKey="lower" stackId="3" stroke={COLORS.primary} fill={COLORS.primary} fillOpacity={0.2} name="Lower Bound" />
          </AreaChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          ±15% confidence interval reflects EPC measurement uncertainty
        </p>
      </Card>

      <Card title="Sensitivity Analysis (Tornado Chart)">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart layout="vertical" data={sensitivityData} margin={{ left: 120 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis type="number" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis type="category" dataKey="parameter" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="range" fill={COLORS.warning} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Energy prices dominate uncertainty; fabric costs relatively stable
        </p>
      </Card>

      <Card title="Key Uncertainties">
        <ul style={{ lineHeight: '1.8', marginLeft: '20px' }}>
          <li>EPC measurement error: ±8 SAP points at lower ratings</li>
          <li>Performance gap: 8-48% overprediction depending on band</li>
          <li>Emitter sizing and conservation area status unknown</li>
          <li><strong>Subsidy sensitivity module producing placeholder values — requires debugging</strong></li>
        </ul>
      </Card>
    </div>
  );

  const GridClimateTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Grid Impact & Indoor Climate</h2>

      <Card title="Grid Peak Load by Technology">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={gridPeakData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="technology" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: 'Peak kW', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Bar dataKey="peakKW" radius={[4, 4, 0, 0]}>
              {gridPeakData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.risk === 'High' ? COLORS.danger : entry.risk === 'Medium' ? COLORS.warning : COLORS.success} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Heat networks reduce peak grid load by 85% vs individual heat pumps
        </p>
      </Card>

      <div style={styles.statsGrid}>
        <StatCard value="73%" label="Fewer Cold Days" />
        <StatCard value="35%" label="Respiratory Risk Reduction" />
        <StatCard value="55%" label="Optimal Humidity" />
        <StatCard value="2%" label="Time Below 16°C" />
      </div>

      <Card title="Indoor Climate Improvement">
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={indoorClimateData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="metric" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis tick={{ fill: COLORS.muted, fontSize: 11 }} label={{ value: '% of Time', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="before" fill={COLORS.secondary} name="Before Retrofit" />
            <Bar dataKey="after" fill={COLORS.success} name="After Retrofit" />
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Post-retrofit: 90% of time in comfortable 18-22°C range
        </p>
      </Card>
    </div>
  );

  const PolicyTab = () => (
    <div>
      <h2 style={styles.sectionTitle}>Policy Implications</h2>

      <Card title="Cost Reduction Levers">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart layout="vertical" data={costLeversData} margin={{ left: 150 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis type="number" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <YAxis type="category" dataKey="lever" tick={{ fill: COLORS.muted, fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="saving" fill={COLORS.success} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p style={{ fontSize: '0.875rem', color: COLORS.muted, marginTop: '12px', marginBottom: 0 }}>
          Total Potential Saving: £6,100/dwelling
        </p>
      </Card>

      <h3 style={styles.cardTitle}>Key Recommendations</h3>
      <div style={styles.grid}>
        <PolicyCard
          title="Technology-Neutral Subsidies"
          text="Equal support for heat network connections could reduce system costs by £2.1bn while achieving comparable carbon outcomes."
          color={COLORS.success}
        />
        <PolicyCard
          title="Fabric-First Integration"
          text="77.4% of properties need wall insulation before heat pump installation. Bundled grants would improve outcomes."
          color={COLORS.warning}
        />
        <PolicyCard
          title="EPC Framework Reform"
          text="Current EPCs over-predict by 8-48%. Scotland's multi-metric approach provides a model for reform."
          color={COLORS.primary}
        />
        <PolicyCard
          title="Grid Reinforcement"
          text="Individual HPs create 3.5kW peak vs 0.5kW for heat networks. Area-based approaches should be prioritised."
          color={COLORS.danger}
        />
      </div>

      <Card title="Data Limitations">
        <ul style={{ lineHeight: '1.8', marginLeft: '20px' }}>
          <li>EPC measurement uncertainty (±8 SAP points for lower bands)</li>
          <li>Performance gap between predicted and actual consumption (8-48%)</li>
          <li>Emitter sizing data not available in EPC records</li>
          <li>Conservation area constraints not quantified</li>
          <li>Subsidy sensitivity module requires debugging</li>
        </ul>
      </Card>
    </div>
  );

  // Render active tab
  const renderActiveTab = () => {
    switch (activeTab) {
      case 'overview': return <OverviewTab />;
      case 'housing': return <HousingStockTab />;
      case 'scenarios': return <ScenariosTab />;
      case 'readiness': return <RetrofitReadinessTab />;
      case 'costbenefit': return <CostBenefitTab />;
      case 'boroughs': return <BoroughsTab />;
      case 'casestreet': return <CaseStreetTab />;
      case 'uncertainty': return <UncertaintyTab />;
      case 'grid': return <GridClimateTab />;
      case 'policy': return <PolicyTab />;
      default: return <OverviewTab />;
    }
  };

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.headerTitle}>Heat Street Project</h1>
        <p style={styles.headerSubtitle}>
          Analysis of 704,483 Edwardian Terraced Properties Across London
        </p>
        <p style={styles.headerMeta}>
          ADE Research for Danish Energy Agency & Danish Embassy • December 2025
        </p>
      </div>

      {/* Navigation */}
      <div style={styles.nav}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            style={{
              ...styles.navButton,
              ...(activeTab === tab.id ? styles.navButtonActive : styles.navButtonInactive)
            }}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={styles.content}>
        {renderActiveTab()}
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        <p>Heat Street Project • ADE Research • Danish Energy Agency & Danish Embassy</p>
        <p>Data source: UK EPC Register • Analysis: December 2025</p>
      </div>
    </div>
  );
}
