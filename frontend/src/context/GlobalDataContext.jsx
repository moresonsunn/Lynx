import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import { getStoredToken, authHeaders, API } from './AppContext';

// Global Data Store Context for instant access to all data
const GlobalDataContext = createContext();

// Global data store that preloads everything
export function GlobalDataProvider({ children }) {
  // All application data - preloaded and always available
  const [globalData, setGlobalData] = useState({
    servers: [],
    serverStats: {},
    serverInfoById: {},
    dashboardData: null,
    systemHealth: null,
    alerts: [],
    users: [],
    roles: [],
    auditLogs: [],
    settings: {},
    serverTypes: [],
    serverVersions: {},
    featuredModpacks: [], // Preloaded featured modpacks for Dashboard
    isInitialized: false
  });

  // Keep latest servers in a ref for interval callbacks
  const serversRef = useRef(globalData.servers);
  useEffect(() => { serversRef.current = globalData.servers; }, [globalData.servers]);

  // Background timers/handles
  const refreshIntervals = useRef({});
  const abortControllers = useRef({});

  // Background refresh function - updates data silently
  const refreshDataInBackground = useCallback(async (dataKey, url, processor = null) => {
    try {
      if (typeof window !== 'undefined' && window.HEAVY_PANEL_ACTIVE) return;
      const response = await fetch(url, { headers: authHeaders() });
      if (response.ok) {
        const data = await response.json();
        setGlobalData(current => ({
          ...current,
          [dataKey]: processor ? processor(data) : data
        }));
      }
    } catch (error) {
      // Silent fail for background updates
    }
  }, []);

  // Aggressive preloading function - loads EVERYTHING immediately (run once on mount)
  const preloadAllData = useCallback(async () => {
    const isAuth = !!getStoredToken();
    
    // Load ALL critical data immediately in parallel - no delays
    const endpoints = [
      { key: 'serverTypes', url: `${API}/server-types` },
      ...(isAuth ? [
        { key: 'servers', url: `${API}/servers` },
        { key: 'dashboardData', url: `${API}/monitoring/dashboard-data` },
        { key: 'systemHealth', url: `${API}/monitoring/system-health` },
        { key: 'alerts', url: `${API}/monitoring/alerts`, processor: (d) => d.alerts || [] },
        { key: 'users', url: `${API}/users`, processor: (d) => d.users || [] },
        { key: 'roles', url: `${API}/users/roles`, processor: (d) => d.roles || [] },
        { key: 'auditLogs', url: `${API}/users/audit-logs?page=1&page_size=50`, processor: (d) => d.logs || [] },
        { key: 'featuredModpacks', url: `${API}/catalog/search?provider=all&page_size=6`, processor: (d) => Array.isArray(d?.results) ? d.results : [] },
      ] : [])
    ];

    // Create abort controllers for all requests
    const localControllers = Object.fromEntries(
      endpoints.map(e => [e.key, new AbortController()])
    );
    abortControllers.current = localControllers;

    // Execute all requests in parallel - instant loading
    const results = await Promise.all(endpoints.map(async endpoint => {
      try {
        const response = await fetch(endpoint.url, {
          signal: localControllers[endpoint.key]?.signal,
          headers: authHeaders()
        });
        if (response.ok) {
          const data = await response.json();
          return { key: endpoint.key, data, processor: endpoint.processor };
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          console.warn(`Failed to preload ${endpoint.key}:`, error);
        }
      }
      return { key: endpoint.key, data: null };
    }));

    // Build a single update object and commit once
    const updates = {};
    results.forEach(result => {
      if (result.data) {
        switch (result.key) {
          case 'servers':
            updates.servers = Array.isArray(result.data) ? result.data : [];
            break;
          case 'serverTypes':
            updates.serverTypes = result.data.types || [];
            break;
          default:
            // Apply processor if exists, otherwise use data directly
            updates[result.key] = result.processor ? result.processor(result.data) : result.data;
        }
      }
    });

    setGlobalData(current => ({ ...current, ...updates, isInitialized: true }));
    
    // Also fetch server stats immediately if we have servers
    if (updates.servers && updates.servers.length > 0) {
      try {
        const statsResponse = await fetch(`${API}/servers/stats?ttl=0`, { headers: authHeaders() });
        if (statsResponse.ok) {
          const statsData = await statsResponse.json();
          setGlobalData(current => ({
            ...current,
            serverStats: { ...(current.serverStats || {}), ...(statsData || {}) }
          }));
        }
      } catch {}
    }
  }, []);

  // Helper: refresh servers list on demand
  const refreshServersNow = useCallback(async () => {
    try {
      const r = await fetch(`${API}/servers`, { headers: authHeaders() });
      if (!r.ok) return;
      const list = await r.json();
      setGlobalData(cur => ({ ...cur, servers: Array.isArray(list) ? list : [] }));
    } catch {}
  }, []);

  // Helper: optimistic update server status locally without reload
  const updateServerStatus = useCallback((id, status) => {
    setGlobalData(cur => ({
      ...cur,
      servers: (cur.servers || []).map(s => s.id === id ? { ...s, status } : s),
    }));
  }, []);

  // Start aggressive preloading on mount
  useEffect(() => {
    preloadAllData();

    // Set up optimized background refresh intervals for balanced performance
    refreshIntervals.current.servers = setInterval(() => {
      refreshDataInBackground('servers', `${API}/servers`, (data) => Array.isArray(data) ? data : []);
    }, 5000); // Refresh servers every 5s for instant updates

    refreshIntervals.current.dashboardData = setInterval(() => {
      refreshDataInBackground('dashboardData', `${API}/monitoring/dashboard-data`);
    }, 15000); // Refresh dashboard data every 15s

    // Refresh users/roles frequently for instant updates
    refreshIntervals.current.users = setInterval(() => {
      refreshDataInBackground('users', `${API}/users`, (d) => d.users || []);
      refreshDataInBackground('roles', `${API}/users/roles`, (d) => d.roles || []);
    }, 10000); // Refresh every 10s

    refreshIntervals.current.alerts = setInterval(() => {
      refreshDataInBackground('alerts', `${API}/monitoring/alerts`, (data) => data.alerts || []);
    }, 30000); // Refresh alerts every 30s

    // Server stats refresh using bulk endpoint for performance
    refreshIntervals.current.serverStats = setInterval(async () => {
      try {
        if (typeof window !== 'undefined' && window.HEAVY_PANEL_ACTIVE) return;
        const r = await fetch(`${API}/servers/stats?ttl=2`, { headers: authHeaders() });
        if (!r.ok) return;
        const data = await r.json();
        setGlobalData(current => {
          const merged = { ...(current.serverStats || {}) };
          if (data && typeof data === 'object') {
            Object.entries(data).forEach(([id, s]) => {
              merged[id] = { ...(merged[id] || {}), ...(s || {}), players: merged[id]?.players };
            });
          }
          return { ...current, serverStats: merged };
        });
      } catch {}
    }, 4000); // Refresh stats every 4s for real-time feel

    const handleVisibility = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      // Refresh all critical data immediately when page becomes visible
      refreshDataInBackground('servers', `${API}/servers`, (data) => Array.isArray(data) ? data : []);
      refreshDataInBackground('users', `${API}/users`, (d) => d.users || []);
      refreshDataInBackground('roles', `${API}/users/roles`, (d) => d.roles || []);
      refreshDataInBackground('dashboardData', `${API}/monitoring/dashboard-data`);
    };
    
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibility);
    }

    return () => {
      // Cleanup intervals and abort controllers
      Object.values(refreshIntervals.current).forEach((h) => { try { clearInterval(h); } catch {} });
      Object.values(abortControllers.current).forEach(controller => { try { controller.abort(); } catch {} });
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibility);
      }
    };
  }, [preloadAllData, refreshDataInBackground]);

  // Real-time server list updates via SSE (falls back to polling above)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const token = getStoredToken();
    if (!token) return;

    const es = new EventSource(`${API}/servers/stream?token=${encodeURIComponent(token)}`);

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === 'servers' && Array.isArray(payload.servers)) {
          setGlobalData(cur => ({ ...cur, servers: payload.servers }));
        }
      } catch {
        // ignore malformed payloads
      }
    };

    es.onerror = () => {
      try { es.close(); } catch {}
    };

    return () => {
      try { es.close(); } catch {}
    };
  }, []);

  // Preload server info (type/version + dir snapshots) for all servers after initial load
  useEffect(() => {
    const servers = serversRef.current || [];
    if (!servers.length) return;
    let cancelled = false;
    (async () => {
      const entries = await Promise.allSettled(
        servers.map(async (s) => {
          try {
            const r = await fetch(`${API}/servers/${s.id}/info`, { headers: authHeaders() });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const d = await r.json();
            return [s.id, d];
          } catch {
            return [s.id, null];
          }
        })
      );
      if (cancelled) return;
      const byId = {};
      entries.forEach(res => { if (res.status === 'fulfilled') { const [id, info] = res.value; if (info) byId[id] = info; } });
      if (Object.keys(byId).length) {
        setGlobalData(cur => ({ ...cur, serverInfoById: { ...(cur.serverInfoById || {}), ...byId } }));
      }
    })();
    return () => { cancelled = true; };
  }, [globalData.servers.length]);

  // Initial bulk fetch of server stats once servers are available
  useEffect(() => {
    if (globalData.servers.length > 0 && globalData.isInitialized) {
      (async () => {
        try {
          const r = await fetch(`${API}/servers/stats?ttl=0`, { headers: authHeaders() });
          if (!r.ok) return;
          const data = await r.json();
          setGlobalData(current => ({
            ...current,
            serverStats: { ...(current.serverStats || {}), ...(data || {}) }
          }));
        } catch {}
      })();
    }
  }, [globalData.servers, globalData.isInitialized]);

  return (
    <GlobalDataContext.Provider value={{
      ...globalData,
      __setGlobalData: setGlobalData,
      __refreshServers: refreshServersNow,
      __updateServerStatus: updateServerStatus,
      __refreshBG: refreshDataInBackground,
      __preloadAll: preloadAllData,
    }}>
      {children}
    </GlobalDataContext.Provider>
  );
}

// Hook to access global data instantly
export function useGlobalData() {
  const data = useContext(GlobalDataContext);
  if (!data) {
    throw new Error('useGlobalData must be used within GlobalDataProvider');
  }
  return data;
}

export default GlobalDataProvider;
