import { useEffect, useState } from 'react';
import { defaultDashboardData } from './dashboardData';

const DEFAULT_SOURCE = 'fallback';

export default function useDashboardData() {
  const [data, setData] = useState(defaultDashboardData);
  const [status, setStatus] = useState({ loading: true, error: null, source: DEFAULT_SOURCE });

  useEffect(() => {
    const controller = new AbortController();

    async function loadData() {
      try {
        const response = await fetch('/dashboard-data.json', {
          cache: 'no-store',
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const payload = await response.json();
        setData({ ...defaultDashboardData, ...payload });
        setStatus({ loading: false, error: null, source: 'analysis' });
      } catch (err) {
        if (err.name === 'AbortError') return;
        // Fall back to bundled defaults to keep the UI usable
        setData(defaultDashboardData);
        setStatus({ loading: false, error: err.message, source: DEFAULT_SOURCE });
      }
    }

    loadData();
    return () => controller.abort();
  }, []);

  return { data, status };
}
