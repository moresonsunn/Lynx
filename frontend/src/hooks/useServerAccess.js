import { useState, useEffect } from 'react';
import { API, authHeaders, useAuth } from '../context/AppContext';

const RANK = { view: 0, operate: 1, manage: 2 };

/**
 * Resolve the current user's effective permission level for one server.
 * Admins/owners always get manage. Regular users get their explicit grant
 * (or null when they have no grant at all). Backend remains the enforcer —
 * this only hides actions the API would reject with 403.
 */
export function useServerAccess(serverName) {
  const { currentUser } = useAuth();
  const [level, setLevel] = useState(null); // null = unknown/loading
  const role = currentUser?.role;
  const isAdmin = role === 'admin' || role === 'owner';

  useEffect(() => {
    if (!serverName || isAdmin || !currentUser) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API}/permissions/my-servers`, { headers: authHeaders() });
        if (r.ok) {
          const data = await r.json().catch(() => ({}));
          const list = data.permissions || data.servers || [];
          const entry = (Array.isArray(list) ? list : []).find(
            (s) => (s.server_name || s.name) === serverName
          );
          if (!cancelled) setLevel(entry?.permission || false);
        } else if (!cancelled) {
          setLevel(false);
        }
      } catch {
        if (!cancelled) setLevel(false);
      }
    })();
    return () => { cancelled = true; };
  }, [serverName, isAdmin, currentUser]);

  if (isAdmin) {
    return { level: 'manage', loading: false, canView: true, canOperate: true, canManage: true };
  }
  if (level === null) {
    // Still loading — default to hiding destructive actions until known
    return { level: null, loading: true, canView: true, canOperate: false, canManage: false };
  }
  if (level === false) {
    return { level: null, loading: false, canView: false, canOperate: false, canManage: false };
  }
  const rank = RANK[level] ?? 0;
  return { level, loading: false, canView: rank >= 0, canOperate: rank >= 1, canManage: rank >= 2 };
}
