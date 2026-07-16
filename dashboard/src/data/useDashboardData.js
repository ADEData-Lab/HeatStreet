import { useEffect, useState } from 'react';
export default function useDashboardData() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState({ loading: true, error: null, source: null });

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
        if (!payload?.runMetadata?.run_id || !payload?.runMetadata?.dataset_fingerprint) {
          throw new Error('Dashboard payload lacks mandatory run provenance');
        }
        setData(payload);
        setStatus({ loading: false, error: null, source: 'analysis' });
      } catch (err) {
        if (err.name === 'AbortError') return;
        setData(null);
        setStatus({ loading: false, error: err.message, source: 'error' });
      }
    }

    loadData();
    return () => controller.abort();
  }, []);

  return { data, status };
}
