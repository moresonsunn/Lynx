import React, { createContext, useContext, useEffect, useRef, useCallback, useMemo, useSyncExternalStore } from 'react';
import { getStoredToken, authHeaders, API } from './AppContext';

/**
 * Global data store.
 *
 * Previously this file exposed a single React context whose value was rebuilt on
 * every poll (as fast as every 2s), which forced *every* consumer to re-render
 * several times per second. This rewrite uses an external store with
 * `useSyncExternalStore` selectors so each component re-renders **only** when the
 * exact slice it reads changes.
 *
 * It also stops the previous polling firehose:
 *   - servers are driven by the SSE stream, with a slow poll only as a fallback
 *     when SSE is stale;
 *   - server stats poll at 5s (was 2s);
 *   - users/roles/audit-logs and dashboard/system-health/alerts are no longer
 *     polled globally — they are fetched on demand by the pages that use them
 *     (UsersPage, DashboardPage).
 */

const initialState = {
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
  featuredModpacks: [],
  isInitialized: false,
};

// ─────────────────────────────────────────────────────── external store
function createStore(initial) {
  let state = initial;
  const listeners = new Set();
  return {
    getState: () => state,
    setState(patch) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      if (!next || next === state) return;
      state = { ...state, ...next };
      listeners.forEach((l) => {
        try { l(); } catch { /* listener errors must not break the store */ }
      });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

function shallowEqual(a, b) {
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  for (const k of ka) {
    if (!Object.is(a[k], b[k])) return false;
  }
  return true;
}

const StoreContext = createContext(null);
const ActionsContext = createContext(null);

// ─────────────────────────────────────────────────────── provider
export function GlobalDataProvider({ children }) {
  const storeRef = useRef(null);
  if (storeRef.current === null) {
    storeRef.current = createStore(initialState);
  }
  const store = storeRef.current;

  // SSE freshness tracking for the servers fallback poll.
  const lastServersPushRef = useRef(0);

  // Background refresh helper — writes a single slice into the store.
  const refreshDataInBackground = useCallback(async (dataKey, url, processor = null) => {
    try {
      if (typeof window !== 'undefined' && window.HEAVY_PANEL_ACTIVE) return;
      if (typeof document !== 'undefined' && document.hidden) return;
      if (!getStoredToken()) return;
      const response = await fetch(url, { headers: authHeaders() });
      if (!response.ok) return;
      const data = await response.json();
      store.setState((cur) => ({ ...cur, [dataKey]: processor ? processor(data) : data }));
    } catch {
      // silent — background updates must never surface errors
    }
  }, [store]);

  const refreshServersNow = useCallback(async () => {
    try {
      const r = await fetch(`${API}/servers`, { headers: authHeaders() });
      if (!r.ok) return;
      const list = await r.json();
      store.setState((cur) => ({ ...cur, servers: Array.isArray(list) ? list : [] }));
    } catch { /* ignore */ }
  }, [store]);

  const updateServerStatus = useCallback((id, status) => {
    store.setState((cur) => ({
      ...cur,
      servers: (cur.servers || []).map((s) => (s.id === id ? { ...s, status } : s)),
    }));
  }, [store]);

  const setGlobalData = useCallback((updater) => {
    store.setState(updater);
  }, [store]);

  const refreshServerStats = useCallback(async () => {
    try {
      if (typeof window !== 'undefined' && window.HEAVY_PANEL_ACTIVE) return;
      if (typeof document !== 'undefined' && document.hidden) return;
      if (!getStoredToken()) return;
      const r = await fetch(`${API}/servers/stats?ttl=0`, { headers: authHeaders() });
      if (!r.ok) return;
      const data = await r.json();
      store.setState((current) => {
        const merged = { ...(current.serverStats || {}) };
        if (data && typeof data === 'object') {
          Object.entries(data).forEach(([id, s]) => {
            merged[id] = { ...(merged[id] || {}), ...(s || {}), players: merged[id]?.players };
          });
        }
        return { ...current, serverStats: merged };
      });
    } catch { /* ignore */ }
  }, [store]);

  // Initial, minimal preload: only globally-shared data (server types + servers).
  const preloadAllData = useCallback(async () => {
    const isAuth = !!getStoredToken();

    // server-types is cheap and shared; fetch it always.
    try {
      const r = await fetch(`${API}/server-types`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        store.setState((cur) => ({ ...cur, serverTypes: data.types || [] }));
      }
    } catch { /* ignore */ }

    if (isAuth) {
      await refreshServersNow();
      await refreshServerStats();
    }
    store.setState((cur) => ({ ...cur, isInitialized: true }));
  }, [store, refreshServersNow, refreshServerStats]);

  const actions = useMemo(() => ({
    __setGlobalData: setGlobalData,
    __refreshServers: refreshServersNow,
    __updateServerStatus: updateServerStatus,
    __refreshBG: refreshDataInBackground,
    __preloadAll: preloadAllData,
  }), [setGlobalData, refreshServersNow, updateServerStatus, refreshDataInBackground, preloadAllData]);

  // Startup + reduced polling.
  useEffect(() => {
    preloadAllData();

    const intervals = [];

    // Server stats: not available via SSE, so poll — but at 5s and only when
    // visible/authenticated (guards inside refreshServerStats).
    intervals.push(setInterval(refreshServerStats, 5000));

    // Servers fallback poll: only fires if the SSE stream has gone stale.
    intervals.push(setInterval(() => {
      if (!getStoredToken()) return;
      if (typeof document !== 'undefined' && document.hidden) return;
      if (Date.now() - lastServersPushRef.current < 15000) return; // SSE is fresh
      refreshServersNow();
    }, 10000));

    const handleVisibility = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      refreshServersNow();
      refreshServerStats();
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibility);
    }

    return () => {
      intervals.forEach((h) => { try { clearInterval(h); } catch { /* ignore */ } });
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibility);
      }
    };
  }, [preloadAllData, refreshServersNow, refreshServerStats]);

  // Real-time server list updates via SSE (primary source of truth).
  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const token = getStoredToken();
    if (!token) return undefined;

    const es = new EventSource(`${API}/servers/stream?token=${encodeURIComponent(token)}`);
    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === 'servers' && Array.isArray(payload.servers)) {
          lastServersPushRef.current = Date.now();
          store.setState((cur) => ({ ...cur, servers: payload.servers }));
        }
      } catch { /* ignore malformed payloads */ }
    };
    es.onerror = () => { try { es.close(); } catch { /* ignore */ } };
    return () => { try { es.close(); } catch { /* ignore */ } };
  }, [store]);

  // Lazily load per-server info only for servers we don't have info for yet,
  // and only when the *set* of server ids changes (cheap signature compare).
  useEffect(() => {
    let cancelled = false;
    let lastIds = '';
    const maybeLoad = async () => {
      const st = store.getState();
      const servers = st.servers || [];
      const ids = servers.map((s) => s.id).sort().join(',');
      if (ids === lastIds) return;
      lastIds = ids;
      const have = st.serverInfoById || {};
      const missing = servers.filter((s) => !have[s.id]);
      if (!missing.length) return;
      const entries = await Promise.allSettled(
        missing.map(async (s) => {
          const r = await fetch(`${API}/servers/${s.id}/info`, { headers: authHeaders() });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return [s.id, await r.json()];
        })
      );
      if (cancelled) return;
      const byId = {};
      entries.forEach((res) => {
        if (res.status === 'fulfilled') { const [id, info] = res.value; if (info) byId[id] = info; }
      });
      if (Object.keys(byId).length) {
        store.setState((cur) => ({ ...cur, serverInfoById: { ...(cur.serverInfoById || {}), ...byId } }));
      }
    };
    const unsub = store.subscribe(maybeLoad);
    maybeLoad();
    return () => { cancelled = true; unsub(); };
  }, [store]);

  return (
    <StoreContext.Provider value={store}>
      <ActionsContext.Provider value={actions}>
        {children}
      </ActionsContext.Provider>
    </StoreContext.Provider>
  );
}

// ─────────────────────────────────────────────────────── selector hooks
function useStoreSelector(selector, isEqual = Object.is) {
  const store = useContext(StoreContext);
  if (!store) {
    throw new Error('useStoreSelector must be used within GlobalDataProvider');
  }
  const lastRef = useRef({ hasValue: false, value: undefined });
  const getSnapshot = () => {
    const next = selector(store.getState());
    const prev = lastRef.current;
    if (prev.hasValue && isEqual(prev.value, next)) {
      return prev.value;
    }
    lastRef.current = { hasValue: true, value: next };
    return next;
  };
  return useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}

export function useGlobalActions() {
  const actions = useContext(ActionsContext);
  if (!actions) {
    throw new Error('useGlobalActions must be used within GlobalDataProvider');
  }
  return actions;
}

export function useServers() {
  return useStoreSelector((s) => s.servers);
}

export function useServerById(id) {
  return useStoreSelector((s) => s.servers.find((srv) => srv.id === id) || null, shallowEqual);
}

export function useServerStats(id) {
  return useStoreSelector((s) => s.serverStats[id] || null, shallowEqual);
}

export function useServerInfo(id) {
  return useStoreSelector((s) => s.serverInfoById[id] || null, shallowEqual);
}

export function useServerTypes() {
  return useStoreSelector((s) => s.serverTypes);
}

export function useIsInitialized() {
  return useStoreSelector((s) => s.isInitialized);
}

/**
 * Backward-compatible hook returning the full state merged with actions.
 *
 * Components using this re-render on any state change (the old behaviour). Hot
 * paths (server list cards, server details) should prefer the granular hooks
 * above so they only re-render on the slice they actually read.
 */
export function useGlobalData() {
  const store = useContext(StoreContext);
  const actions = useContext(ActionsContext);
  if (!store) {
    throw new Error('useGlobalData must be used within GlobalDataProvider');
  }
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  return useMemo(() => ({ ...state, ...actions }), [state, actions]);
}

export default GlobalDataProvider;
