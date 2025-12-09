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
import { defaultDashboardData } from '../data/dashboardData';

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

  const mergedSummary = {
    ...defaultDashboardData.summaryStats,
    ...summaryStats,
    meanSAPScore: summaryStats.meanSAPScore ?? summaryStats.avgSAPScore ?? defaultDashboardData.summaryStats.meanSAPScore,
  };

  const totalProperties = mergedSummary.totalProperties;
  const dhViableShare =
    mergedSummary.dhViableProperties && totalProperties
      ? (mergedSummary.dhViableProperties / totalProperties) * 100
      : null;

  const formatNumber = (value, options = {}) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return Number(value).toLocaleString(undefined, options);
  };

  const formatPercent = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return `${Number(value).toFixed(1)}%`;
  };

  const summaryMetrics = [
    {
      label: 'Total properties',
      value: formatNumber(totalProperties),
      caption: 'Section 7 · EPC data robustness',
    },
    {
      label: 'Average SAP score',
      value: formatNumber(mergedSummary.meanSAPScore, { maximumFractionDigits: 1 }),
      caption: 'Section 1 · Fabric detail granularity',
    },
    {
      label: 'Wall insulation rate',
      value: formatPercent(mergedSummary.wallInsulationRate),
      caption: 'Section 1 · Fabric detail granularity',
    },
    {
      label: 'Below Band C',
      value: formatPercent(mergedSummary.belowBandC),
      caption: 'Section 1 · Fabric detail granularity',
    },
    {
      label: 'Most common EPC band',
      value: mergedSummary.commonEpcBand || 'D',
      caption: 'Section 1 · Fabric detail granularity',
    },
    {
      label: 'Gas boiler dependency',
      value: formatPercent(mergedSummary.gasBoilerDependency),
      caption: 'Section 6 · Pathways & hybrid scenarios',
    },
    {
      label: 'District heating viable',
      value: `${formatNumber(mergedSummary.dhViableProperties)} (${formatPercent(dhViableShare)})`,
      caption: 'Section 10 · Heat network penetration & price sensitivity',
    },
    {
      label: 'Cost advantage: DH vs HP',
      value: `£${formatNumber(mergedSummary.costAdvantageDHvsHP)}`,
      caption: 'Section 10 · Heat network penetration & price sensitivity',
    },
    {
      label: 'Optimal investment point',
      value: `£${formatNumber(mergedSummary.optimalInvestmentPoint)}`,
      caption: 'Section 8 · Fabric tipping point curve',
    },
    {
      label: 'Mean fabric cost',
      value: `£${formatNumber(mergedSummary.meanFabricCost)}`,
      caption: 'Section 2 · Retrofit measures & packages',
    },
    {
      label: 'Mean total retrofit cost',
      value: `£${formatNumber(mergedSummary.meanTotalRetrofitCost)}`,
      caption: 'Section 5 · Payback times',
    },
    {
      label: 'Heat-demand reduction',
      value: formatPercent(mergedSummary.heatDemandReduction),
      caption: 'Section 9 · Load profiles & system impacts',
    },
    {
      label: 'Peak grid reduction',
      value: formatPercent(mergedSummary.peakGridReduction),
      caption: 'Section 9 · Load profiles & system impacts',
    },
    {
      label: 'Ready or near-ready homes',
      value: formatPercent(mergedSummary.readyOrNearReady),
      caption: 'Section 11 · Tenure filtering',
    },
  ];

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
          {formatNumber(totalProperties)} properties · Source: {status.source || 'analysis JSON'}
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Executive snapshot</div>
              <h3 style={styles.introTitle}>What the visuals answer</h3>
              <ul style={styles.introList}>
                <li>
                  Band mix and case street vs London chart show the scale of the EPC gap and where the case street diverges most
                  from the city baseline.
                </li>
                <li>Headline stats call out portfolio size, SAP scores, and common band to orient the conversation quickly.</li>
                <li>
                  Use this tab when clients ask “how big is the problem and where are we off-trend?” before diving into segments.
                </li>
              </ul>
            </div>
            <div style={styles.grid}>
              {summaryMetrics.map((metric) => (
                <div style={styles.statCard} key={metric.label}>
                  <div style={styles.statValue}>{metric.value}</div>
                  <div style={styles.statLabel}>{metric.label}</div>
                  <div style={styles.statCaption}>{metric.caption}</div>
                </div>
              ))}
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Fabric and systems</div>
              <h3 style={styles.introTitle}>How this answers client prompts</h3>
              <ul style={styles.introList}>
                <li>Wall type and heating system splits show the dominant fabric archetypes driving retrofit complexity.</li>
                <li>
                  Glazing and loft insulation visuals highlight where simple measures can unlock SAP gains with minimal disruption.
                </li>
                <li>Use when asked “what stock characteristics constrain or accelerate retrofit rollout?”</li>
              </ul>
            </div>
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Scenario levers</div>
              <h3 style={styles.introTitle}>What to look for</h3>
              <ul style={styles.introList}>
                <li>Capital vs payback overlay surfaces the quickest wins versus longer-horizon investments.</li>
                <li>Click-to-drill lets you answer “what drives that payback?” in one motion during live discussions.</li>
                <li>Use this tab for pathway prioritisation and when comparing against budget envelopes.</li>
              </ul>
            </div>
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Delivery readiness</div>
              <h3 style={styles.introTitle}>How it addresses the ask</h3>
              <ul style={styles.introList}>
                <li>Tier distribution clarifies which homes are installation-ready versus needing enabling works.</li>
                <li>Intervention bar chart surfaces the most common blockers for planning resource and sequencing.</li>
                <li>Use this when stakeholders ask “how deployable is the stock today?”</li>
              </ul>
            </div>
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Value for money</div>
              <h3 style={styles.introTitle}>Why these visuals matter</h3>
              <ul style={styles.introList}>
                <li>Cost curve shows diminishing returns and where spend concentrates for each measure.</li>
                <li>Tier and lever summaries answer “which packages deliver best £/impact and what drives variance?”</li>
                <li>Use this tab to brief finance teams on ROI trade-offs and sequencing.</li>
              </ul>
            </div>
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Geographic lens</div>
              <h3 style={styles.introTitle}>How this answers client questions</h3>
              <ul style={styles.introList}>
                <li>Table ranks boroughs by EPC and energy so you can spot outliers for targeted engagement.</li>
                <li>Map pairs the ranking with spatial context to explain clusters and delivery logistics.</li>
                <li>Use when asked “where should we pilot first and why there?”</li>
              </ul>
            </div>
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
                      <td>{row.borough_name || row.borough}</td>
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Robustness checks</div>
              <h3 style={styles.introTitle}>What the charts convey</h3>
              <ul style={styles.introList}>
                <li>Confidence bands show spread around central estimates so you can communicate risk ranges.</li>
                <li>Sensitivity tornado highlights which assumptions move the business case most.</li>
                <li>Use this tab when addressing “how certain are these outcomes?” and mitigation plans.</li>
              </ul>
            </div>
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
            <div style={styles.introBlock}>
              <div style={styles.introLabel}>Systems impact</div>
              <h3 style={styles.introTitle}>How this answers grid and comfort queries</h3>
              <ul style={styles.introList}>
                <li>Peak vs average demand lines reveal how each scenario stresses the grid across seasons.</li>
                <li>Indoor climate profiles reassure clients on comfort and humidity under modeled upgrades.</li>
                <li>Use for DNO discussions and to evidence customer experience impacts.</li>
              </ul>
            </div>
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
  statCaption: {
    fontSize: '0.75rem',
    color: 'var(--muted)',
    marginTop: 6,
    letterSpacing: '0.01em',
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
  introBlock: {
    backgroundColor: 'var(--panel)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '16px 20px',
    marginBottom: '16px',
    boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
  },
  introLabel: {
    fontSize: '0.85rem',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.4px',
    color: COLORS.muted,
    marginBottom: '6px',
  },
  introTitle: {
    fontSize: '1rem',
    margin: 0,
    color: 'var(--text)',
    fontWeight: 700,
  },
  introList: {
    margin: '10px 0 0 18px',
    padding: 0,
    color: 'var(--text)',
    lineHeight: 1.6,
  },
};
