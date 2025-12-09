import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import useDashboardData from '../data/useDashboardData';

const DashboardContext = createContext(null);
const DEFAULT_FILTERS = { search: '', borough: 'all', pathway: 'all', tenure: 'all' };
const DEFAULT_PREFS = { theme: 'system', animations: true, savedViews: [] };

function getStoredPreferences() {
  if (typeof localStorage === 'undefined') return DEFAULT_PREFS;
  try {
    const stored = localStorage.getItem('dashboard-preferences');
    return stored ? { ...DEFAULT_PREFS, ...JSON.parse(stored) } : DEFAULT_PREFS;
  } catch (err) {
    console.warn('Failed to read preferences', err);
    return DEFAULT_PREFS;
  }
}

function persistPreferences(prefs) {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem('dashboard-preferences', JSON.stringify(prefs));
  } catch (err) {
    console.warn('Failed to persist preferences', err);
  }
}

function applyTheme(theme) {
  const root = document.body;
  if (!root) return;
  const resolved = theme === 'system'
    ? (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme;
  root.setAttribute('data-theme', resolved);
}

export function DashboardProvider({ children }) {
  const { data, status } = useDashboardData();
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [preferences, setPreferences] = useState(() => getStoredPreferences());
  const [activeTab, setActiveTab] = useState('overview');
  const [comparisonSet, setComparisonSet] = useState([]);
  const [drilldownTarget, setDrilldownTarget] = useState(null);

  useEffect(() => {
    applyTheme(preferences.theme);
    persistPreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    const listener = (event) => {
      if (event.matches && preferences.theme === 'system') applyTheme('system');
    };
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, [preferences.theme]);

  const filteredData = useMemo(() => {
    if (!data) return {};
    const search = filters.search.toLowerCase();
    const match = (value) => !search || String(value).toLowerCase().includes(search);

    const filteredBoroughs = (data.boroughData || []).filter((item) => {
      const boroughMatch = filters.borough === 'all' || item.borough === filters.borough;
      return boroughMatch && (match(item.borough) || match(item.code));
    });

    const filteredScenarios = (data.scenarioData || []).filter((item) => {
      const scenarioMatch = filters.pathway === 'all' || item.scenario === filters.pathway;
      return scenarioMatch && match(item.scenario);
    });

    return {
      ...data,
      boroughData: filteredBoroughs,
      scenarioData: filteredScenarios,
    };
  }, [data, filters]);

  const resetFilters = () => setFilters(DEFAULT_FILTERS);

  const updatePreference = (key, value) => {
    setPreferences((prev) => ({ ...prev, [key]: value }));
  };

  const saveView = (label) => {
    const view = { label, filters, activeTab };
    setPreferences((prev) => ({
      ...prev,
      savedViews: [...prev.savedViews.filter((entry) => entry.label !== label), view].slice(-10),
    }));
  };

  const loadView = (label) => {
    const view = preferences.savedViews.find((entry) => entry.label === label);
    if (!view) return;
    setFilters(view.filters || DEFAULT_FILTERS);
    setActiveTab(view.activeTab || 'overview');
  };

  const toggleComparison = (scenario) => {
    setComparisonSet((prev) => {
      const exists = prev.includes(scenario);
      if (exists) return prev.filter((item) => item !== scenario);
      if (prev.length >= 3) return [...prev.slice(1), scenario];
      return [...prev, scenario];
    });
  };

  return (
    <DashboardContext.Provider
      value={{
        data: filteredData,
        rawData: data,
        status,
        filters,
        setFilters,
        resetFilters,
        preferences,
        updatePreference,
        activeTab,
        setActiveTab,
        saveView,
        loadView,
        comparisonSet,
        toggleComparison,
        drilldownTarget,
        setDrilldownTarget,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error('useDashboard must be used within a DashboardProvider');
  return ctx;
}
