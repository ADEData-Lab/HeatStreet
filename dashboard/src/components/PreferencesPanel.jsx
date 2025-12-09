import React, { useState } from 'react';
import { useDashboard } from '../context/DashboardContext';

export default function PreferencesPanel() {
  const { preferences, updatePreference, saveView, loadView, activeTab } = useDashboard();
  const [viewName, setViewName] = useState('');

  return (
    <div className="toolbar preferences">
      <div className="toolbar-group">
        <label className="toolbar-label">Theme</label>
        <select value={preferences.theme} onChange={(e) => updatePreference('theme', e.target.value)}>
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </div>

      <div className="toolbar-group">
        <label className="toolbar-label">Animations</label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={preferences.animations}
            onChange={(e) => updatePreference('animations', e.target.checked)}
          />
          <span>{preferences.animations ? 'On' : 'Off'}</span>
        </label>
      </div>

      <div className="toolbar-group">
        <label className="toolbar-label">Saved views</label>
        <div className="button-row">
          <input
            type="text"
            placeholder="Name this view"
            value={viewName}
            onChange={(e) => setViewName(e.target.value)}
          />
          <button type="button" onClick={() => viewName && saveView(viewName)}>
            Save current (tab: {activeTab})
          </button>
          <select onChange={(e) => e.target.value && loadView(e.target.value)} defaultValue="">
            <option value="" disabled>
              Load saved
            </option>
            {preferences.savedViews.map((view) => (
              <option key={view.label} value={view.label}>
                {view.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
