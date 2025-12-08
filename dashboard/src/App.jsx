import React, { useState } from 'react';
import ExecutiveSummary from './components/ExecutiveSummary';
import FabricAnalysis from './components/FabricAnalysis';
import RetrofitAnalysis from './components/RetrofitAnalysis';
import PathwaysAnalysis from './components/PathwaysAnalysis';
import LoadProfilesAndSensitivity from './components/LoadProfilesAndSensitivity';

export default function App() {
  const [activeTab, setActiveTab] = useState('summary');

  const tabs = [
    { id: 'summary', label: 'Executive Summary', component: ExecutiveSummary },
    { id: 'fabric', label: 'Fabric Analysis (§1,7,11)', component: FabricAnalysis },
    { id: 'retrofit', label: 'Retrofit Measures (§2,3,4,5)', component: RetrofitAnalysis },
    { id: 'pathways', label: 'Pathways & Tipping Points (§6,8)', component: PathwaysAnalysis },
    { id: 'profiles', label: 'Load Profiles & Sensitivity (§9,10)', component: LoadProfilesAndSensitivity }
  ];

  const ActiveComponent = tabs.find(tab => tab.id === activeTab)?.component || ExecutiveSummary;

  return (
    <div>
      <div className="header">
        <div className="header-content">
          <h1>Heat Street EPC Analysis Dashboard</h1>
          <p>
            Comprehensive analysis of 704,292 Edwardian terraced properties across London
            • All 12 client requirements addressed • Evidence-based decarbonization pathways
          </p>
        </div>
      </div>

      <div className="container">
        <div className="card" style={{ marginBottom: '30px' }}>
          <h3 style={{ marginBottom: '12px' }}>Client Requirements Coverage</h3>
          <div className="grid grid-3" style={{ gap: '12px' }}>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 1</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Fabric Granularity</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 2</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Retrofit Measures</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 3</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Radiator Upsizing</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 4</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Window Upgrades</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 5</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Payback Times</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 6</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Pathways & Hybrid</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 7</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>EPC Anomalies</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 8</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Tipping Points</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 9</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Load Profiles</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 10</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Price Sensitivity</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 11</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Tenure Filtering</p>
            </div>
            <div style={{ padding: '12px', background: '#d4edda', borderRadius: '6px', textAlign: 'center' }}>
              <span className="badge badge-success">✓ Section 12</span>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>Documentation</p>
            </div>
          </div>
        </div>

        <div className="tabs">
          {tabs.map(tab => (
            <button
              key={tab.id}
              className={`tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div style={{ marginTop: '20px' }}>
          <ActiveComponent />
        </div>

        <div className="card" style={{ marginTop: '40px', background: '#f0f7ff' }}>
          <h3 className="card-header">About This Dashboard</h3>
          <p>
            This dashboard presents comprehensive analysis of Heat Street EPC data, addressing all 12 categories of client requirements:
          </p>
          <ul style={{ lineHeight: '1.8', marginLeft: '20px' }}>
            <li><strong>Sections 1, 7, 11:</strong> Fabric detail granularity, EPC anomalies, and tenure filtering</li>
            <li><strong>Sections 2, 3, 4, 5:</strong> Retrofit measures, radiator upsizing, window upgrades, and payback times</li>
            <li><strong>Sections 6, 8:</strong> Pathways (including hybrid scenarios) and fabric tipping point curves</li>
            <li><strong>Sections 9, 10:</strong> Load profiles, system impacts, and sensitivity analysis</li>
            <li><strong>Section 12:</strong> Comprehensive documentation with docstrings and assumptions</li>
          </ul>
          <p style={{ marginTop: '16px', fontStyle: 'italic' }}>
            Data sources: London EPC database (704,292 pre-1930 terraced properties), Shakespeare Crescent case study,
            heat network tier analysis. All calculations use HM Treasury Green Book discount rate (3.5%) and documented uncertainty ranges (±20-30%).
          </p>
        </div>
      </div>
    </div>
  );
}
