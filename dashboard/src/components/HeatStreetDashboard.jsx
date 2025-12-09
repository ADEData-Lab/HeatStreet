import React from 'react';
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  LineChart,
  Line,
  AreaChart,
  Area,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts';
import FilterBar from './FilterBar';
import ExportMenu from './ExportMenu';
import PreferencesPanel from './PreferencesPanel';
import ComparisonDrawer from './ComparisonDrawer';
import MapView from './MapView';
import DrillDownModal from './DrillDownModal';
import { useDashboard } from '../context/DashboardContext';

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
export default function HeatStreetDashboard() {
  const { data, status, activeTab, setActiveTab, preferences, setDrilldownTarget } = useDashboard();
  const {
    epcBandData = [],
    epcComparisonData = [],
    wallTypeData = [],
    heatingSystemData = [],
    scenarioData = [],
    tierData = [],
    retrofitReadinessData = [],
    interventionData = [],
    boroughData = [],
    confidenceBandsData = [],
    sensitivityData = [],
    gridPeakData = [],
    indoorClimateData = [],
    costLeversData = [],
    loftInsulationData = [],
    costBenefitTierData = [],
    costCurveData = [],
    glazingData = [],
    summaryStats = {},
  } = data || {};

  if (status.loading) {
    return (
      <div style={styles.container} id="dashboard-root">
        <div style={styles.loading}>Loading latest analysis data...</div>
      </div>
    );
  }

  const isAnimated = preferences.animations;

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'housing', label: 'Housing Stock' },
    { id: 'scenarios', label: 'Scenarios' },
    { id: 'readiness', label: 'Retrofit Readiness' },
    { id: 'costbenefit', label: 'Cost-Benefit' },
    { id: 'boroughs', label: 'Boroughs' },
    { id: 'uncertainty', label: 'Uncertainty' },
    { id: 'grid', label: 'Grid & Climate' },
    { id: 'policy', label: 'Policy' },
  ];

  const tableClick = (row) => setDrilldownTarget(row);

  return (
    <div style={styles.container} id="dashboard-root">
      <header style={styles.header}>
        <h1 style={styles.headerTitle}>Heat Street EPC Analysis Dashboard</h1>
        <p style={styles.headerSubtitle}>
          Latest metrics generated from run_analysis.py with live JSON ingestion and saved-view support.
        </p>
        <p style={styles.headerMeta}>
          {summaryStats.totalProperties?.toLocaleString?.() || '704,292'} properties · Source: {status.source || 'analysis JSON'}
        </p>
        <div style={styles.statusRow}>
          <span style={styles.statusBadge}>Data source: {status.source === 'analysis' ? 'Latest run' : 'Bundled defaults'}</span>
          {status.error && <span style={styles.errorText}>Fallback used: {status.error}</span>}
          <button type="button" className="ghost" onClick={() => window.print()}>
            Print this view
          </button>
        </div>
      </header>

      <div style={styles.toolbarStack}>
        <FilterBar />
        <PreferencesPanel />
        <ExportMenu />
      </div>

      <nav style={styles.nav}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            style={{
              ...styles.navButton,
              ...(activeTab === tab.id ? styles.navButtonActive : styles.navButtonInactive),
            }}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main style={styles.content}>
        {activeTab === 'overview' && (
          <section>
            <div style={styles.grid}>
              <div style={styles.statCard}>
                <div style={styles.statValue}>{summaryStats.totalProperties?.toLocaleString?.() || '704,292'}</div>
                <div style={styles.statLabel}>Total properties</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statValue}>{summaryStats.avgSAPScore || 63.4}</div>
                <div style={styles.statLabel}>Average SAP score</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statValue}>{summaryStats.wallInsulationRate || 33.7}%</div>
                <div style={styles.statLabel}>Wall insulation rate</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statValue}>{summaryStats.commonEpcBand || 'D'}</div>
                <div style={styles.statLabel}>Most common EPC band</div>
              </div>
            </div>

            <div style={styles.gridTwo}>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>EPC band distribution</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={epcBandData} barCategoryGap={12}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="band" />
                    <YAxis />
                    <Tooltip formatter={(value) => value.toLocaleString()} />
                    <Bar dataKey="count" name="Properties" isAnimationActive={isAnimated}>
                      {epcBandData.map((entry) => (
                        <Cell key={entry.band} fill={EPC_COLORS[entry.band] || COLORS.primary} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Case street vs London</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <ComposedChart data={epcComparisonData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="band" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="shakespeareCrescent" name="Case street" fill={COLORS.primary} isAnimationActive={isAnimated} />
                    <Line type="monotone" dataKey="londonAverage" name="London" stroke={COLORS.accent} strokeWidth={3} isAnimationActive={isAnimated} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>
        )}

        {activeTab === 'housing' && (
          <section>
            <div style={styles.gridTwo}>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Wall construction types</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={wallTypeData} barSize={28}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="type" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="percentage" name="Share (%)" fill={COLORS.secondary} isAnimationActive={isAnimated} />
                    <ReferenceLine y={50} stroke={COLORS.warning} strokeDasharray="4 4" label="50%" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Heating systems</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <PieChart>
                    <Pie data={heatingSystemData} dataKey="value" nameKey="name" outerRadius={120} label isAnimationActive={isAnimated}>
                      {heatingSystemData.map((entry, index) => (
                        <Cell key={entry.name} fill={TIER_COLORS[index % TIER_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value) => `${value}%`} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Glazing and loft insulation</h3>
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={glazingData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="type" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="share" name="Share (%)" fill={COLORS.primary} isAnimationActive={isAnimated} />
                  <Line dataKey="uValue" name="U-value" stroke={COLORS.accent} strokeWidth={3} isAnimationActive={isAnimated} />
                </ComposedChart>
              </ResponsiveContainer>
              <div style={{ marginTop: 12 }}>
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={loftInsulationData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="thickness" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Area type="monotone" dataKey="properties" name="Properties" stroke={COLORS.secondary} fill={COLORS.secondary} opacity={0.3} isAnimationActive={isAnimated} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>
        )}

        {activeTab === 'scenarios' && (
          <section>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Scenario modelling</h3>
              <ResponsiveContainer width="100%" height={320}>
                <ComposedChart data={scenarioData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="scenario" />
                  <YAxis yAxisId="left" label={{ value: 'Capital (£m)', angle: -90, position: 'insideLeft' }} />
                  <YAxis yAxisId="right" orientation="right" label={{ value: 'Payback (years)', angle: 90, position: 'insideRight' }} />
                  <Tooltip formatter={(value) => value.toLocaleString()} />
                  <Legend />
                  <Bar yAxisId="left" dataKey="capitalCost" name="Capital (£m)" fill={COLORS.primary} isAnimationActive={isAnimated} onClick={(dataPoint) => tableClick(dataPoint)} />
                  <Line yAxisId="right" type="monotone" dataKey="paybackYears" name="Payback" stroke={COLORS.accent} strokeWidth={3} isAnimationActive={isAnimated} />
                </ComposedChart>
              </ResponsiveContainer>
              <p className="subtle">Click a bar to drill into the scenario details.</p>
            </div>
            <ComparisonDrawer />
          </section>
        )}

        {activeTab === 'readiness' && (
          <section style={styles.gridTwo}>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Retrofit readiness tiers</h3>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={retrofitReadinessData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="tier" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="percentage" name="Share (%)" fill={COLORS.primary} isAnimationActive={isAnimated} />
                  <Line type="monotone" dataKey="avgCost" name="Avg cost (£)" stroke={COLORS.accent} strokeWidth={3} isAnimationActive={isAnimated} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Intervention requirements</h3>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={interventionData} layout="vertical" margin={{ top: 5, right: 20, left: 80, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="intervention" width={160} />
                  <Tooltip formatter={(value) => `${value}%`} />
                  <Bar dataKey="percentage" name="Share (%)" fill={COLORS.secondary} isAnimationActive={isAnimated} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {activeTab === 'costbenefit' && (
          <section>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Cost curve</h3>
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={costCurveData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="measure" />
                  <YAxis />
                  <Tooltip />
                  <Area type="monotone" dataKey="cost" name="Cost (£)" stroke={COLORS.primary} fill={COLORS.primary} opacity={0.35} isAnimationActive={isAnimated} />
                  <Line type="monotone" dataKey="savings" name="Savings (£)" stroke={COLORS.success} strokeWidth={3} isAnimationActive={isAnimated} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div style={styles.gridTwo}>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Cost-benefit tiers</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={costBenefitTierData} dataKey="share" nameKey="tier" outerRadius={110} label isAnimationActive={isAnimated}>
                      {costBenefitTierData.map((entry, index) => (
                        <Cell key={entry.tier} fill={TIER_COLORS[index % TIER_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value) => `${value}%`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Cost levers</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={costLeversData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="lever" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="impact" name="Impact (£)" fill={COLORS.accent} isAnimationActive={isAnimated} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>
        )}

        {activeTab === 'boroughs' && (
          <section>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Borough performance</h3>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th>Borough</th>
                    <th>EPC</th>
                    <th>Energy</th>
                    <th>Properties</th>
                  </tr>
                </thead>
                <tbody>
                  {boroughData.map((row) => (
                    <tr key={row.borough} onClick={() => tableClick(row)} style={{ cursor: 'pointer' }}>
                      <td>{row.borough}</td>
                      <td>{row.meanEPC}</td>
                      <td>{row.energy}</td>
                      <td>{row.count?.toLocaleString?.() || row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <MapView />
          </section>
        )}

        {activeTab === 'uncertainty' && (
          <section>
            <div style={styles.gridTwo}>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Confidence bands</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <AreaChart data={confidenceBandsData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="stage" />
                    <YAxis />
                    <Tooltip />
                    <Area type="monotone" dataKey="estimate" name="Estimate" stroke={COLORS.primary} fill={COLORS.primary} opacity={0.25} isAnimationActive={isAnimated} />
                    <Line type="monotone" dataKey="lower" name="Lower" stroke={COLORS.warning} strokeWidth={2} isAnimationActive={isAnimated} />
                    <Line type="monotone" dataKey="upper" name="Upper" stroke={COLORS.danger} strokeWidth={2} isAnimationActive={isAnimated} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Sensitivity analysis</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={sensitivityData} layout="vertical" margin={{ top: 5, right: 20, left: 160, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis dataKey="parameter" type="category" />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="range" name="Range (£/yr)" fill={COLORS.secondary} isAnimationActive={isAnimated} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>
        )}

        {activeTab === 'grid' && (
          <section style={styles.gridTwo}>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Grid peak demand</h3>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={gridPeakData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="scenario" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="peak" name="Peak (kW)" stroke={COLORS.primary} strokeWidth={3} isAnimationActive={isAnimated} />
                  <Line type="monotone" dataKey="average" name="Average (kW)" stroke={COLORS.secondary} strokeDasharray="5 5" isAnimationActive={isAnimated} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Indoor climate profiles</h3>
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={indoorClimateData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="hour" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Area type="monotone" dataKey="temperature" name="Temperature" stroke={COLORS.accent} fill={COLORS.accent} opacity={0.35} isAnimationActive={isAnimated} />
                  <Area type="monotone" dataKey="humidity" name="Humidity" stroke={COLORS.success} fill={COLORS.success} opacity={0.25} isAnimationActive={isAnimated} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {activeTab === 'policy' && (
          <section>
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Heat network tiers</h3>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th>Tier</th>
                    <th>Properties</th>
                    <th>Share</th>
                    <th>Recommendation</th>
                  </tr>
                </thead>
                <tbody>
                  {tierData.map((row, index) => (
                    <tr key={row.tier} onClick={() => tableClick(row)} style={{ cursor: 'pointer' }}>
                      <td>{row.tier}</td>
                      <td>{row.properties?.toLocaleString?.() || row.properties}</td>
                      <td>{row.percentage}%</td>
                      <td>
                        <span style={{ ...styles.badge, backgroundColor: TIER_COLORS[index % TIER_COLORS.length] }}>
                          {row.recommendation}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>

      <DrillDownModal />
    </div>
  );
}

const styles = {
  container: {
    fontFamily: "'Source Sans Pro', -apple-system, BlinkMacSystemFont, sans-serif",
    backgroundColor: 'var(--surface)',
    color: 'var(--text)',
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
    opacity: 0.85,
    margin: '4px 0',
  },
  statusRow: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    gap: '12px',
    flexWrap: 'wrap',
    marginTop: '8px',
  },
  statusBadge: {
    display: 'inline-block',
    backgroundColor: '#fff',
    color: '#1e3a5f',
    padding: '6px 10px',
    borderRadius: '16px',
    fontSize: '0.85rem',
    fontWeight: 600,
    boxShadow: '0 2px 6px rgba(0,0,0,0.1)',
  },
  errorText: {
    fontSize: '0.85rem',
    color: '#ffe8e6',
  },
  nav: {
    display: 'flex',
    justifyContent: 'center',
    gap: '4px',
    padding: '16px 24px',
    backgroundColor: 'var(--panel)',
    borderBottom: '1px solid var(--border)',
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
  loading: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '60vh',
    fontSize: '1.1rem',
    color: COLORS.muted,
  },
  content: {
    maxWidth: '1400px',
    margin: '0 auto',
    padding: '24px',
  },
  card: {
    backgroundColor: 'var(--panel)',
    borderRadius: '12px',
    padding: '24px',
    boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
    border: '1px solid var(--border)',
    marginBottom: '20px',
  },
  cardTitle: {
    fontSize: '1rem',
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: '16px',
    marginTop: 0,
  },
  statCard: {
    backgroundColor: 'var(--panel)',
    borderRadius: '12px',
    padding: '20px',
    boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
    border: '1px solid var(--border)',
    textAlign: 'center',
  },
  statValue: {
    fontSize: '2rem',
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: '4px',
  },
  statLabel: {
    fontSize: '0.875rem',
    color: 'var(--muted)',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: '20px',
    marginBottom: '24px',
  },
  gridTwo: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
    gap: '20px',
    marginBottom: '24px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.9rem',
  },
  badge: {
    display: 'inline-block',
    padding: '4px 10px',
    borderRadius: '12px',
    color: '#fff',
    fontWeight: 600,
    fontSize: '0.85rem',
  },
  toolbarStack: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    padding: '16px 24px',
  },
};
