import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useServers, useServerStats, useServerInfo, useIsInitialized } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import {
  FaServer,
  FaHome,
  FaChevronRight,
  FaFilter,
  FaClock,
  FaGripVertical,
  FaStar,
  FaRegStar,
} from 'react-icons/fa';


const SERVER_ORDER_KEY = 'lynx_server_order';

function loadServerOrder() {
  try {
    const v = JSON.parse(localStorage.getItem(SERVER_ORDER_KEY));
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function saveServerOrder(ids) {
  try {
    localStorage.setItem(SERVER_ORDER_KEY, JSON.stringify(ids));
  } catch {
    /* ignore storage quota / availability errors */
  }
}

function sortByOrder(servers, order) {
  if (!order || !order.length) return servers;
  const rank = new Map(order.map((id, i) => [id, i]));
  const BIG = Number.MAX_SAFE_INTEGER;
  // Array.sort is stable, so servers not present in the saved order keep their
  // natural relative position and fall to the end.
  return [...servers].sort((a, b) => {
    const ra = rank.has(a.id) ? rank.get(a.id) : BIG;
    const rb = rank.has(b.id) ? rank.get(b.id) : BIG;
    return ra - rb;
  });
}


const SERVER_PINS_KEY = 'lynx_server_pins';

function loadServerPins() {
  try {
    const v = JSON.parse(localStorage.getItem(SERVER_PINS_KEY));
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function saveServerPins(ids) {
  try {
    localStorage.setItem(SERVER_PINS_KEY, JSON.stringify(ids));
  } catch {
    /* ignore storage errors */
  }
}

// Server-side preference sync (order + pins) so the layout follows the user
// across devices/browsers. localStorage stays as an offline cache.
const PREFS_ENDPOINT = `${API}/users/me/preferences`;

async function fetchServerPrefs() {
  try {
    const res = await fetch(PREFS_ENDPOINT, { headers: authHeaders() });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function saveServerPrefs(patch) {
  // Fire-and-forget; localStorage has already been updated as a fallback.
  try {
    fetch(PREFS_ENDPOINT, {
      method: 'PUT',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).catch(() => {});
  } catch {
    /* ignore */
  }
}

function ServerCardSkeleton() {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-5 md:p-6 animate-pulse" style={{ minHeight: 100 }}>
      <div className="flex items-center gap-4 md:gap-5">
        <div className="w-12 h-12 rounded-lg bg-white/10 flex-shrink-0" />
        <div className="flex-1 space-y-2">
          <div className="h-4 w-40 bg-white/10 rounded" />
          <div className="h-3 w-24 bg-white/10 rounded" />
          <div className="flex gap-2 pt-1">
            <div className="h-4 w-16 bg-white/10 rounded-full" />
            <div className="h-4 w-24 bg-white/10 rounded-full" />
          </div>
        </div>
        <div className="h-6 w-16 bg-white/10 rounded-full" />
      </div>
    </div>
  );
}


function formatUptime(seconds) {
  if (!seconds || seconds < 0) return '0s';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}


const ServerListCard = React.memo(function ServerListCard({ server, onClick, onHandleDragStart, isPinned, onTogglePin }) {
  const stats = useServerStats(server.id);
  
  
  const typeVersionData = useServerInfo(server.id);

  const normalizeLabel = useCallback((value) => {
    if (!value) return '';
    return value
      .toString()
      .split(/[-_\s]+/)
      .filter(Boolean)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }, []);

  const runtimeKind = (typeVersionData?.server_kind || server.server_kind || '').toLowerCase();
  const isSteam = runtimeKind === 'steam';
  const steamGame = typeVersionData?.steam_game || server.steam_game;
  const displayKind = isSteam
    ? `Steam · ${normalizeLabel(steamGame || server.type || 'Dedicated')}`
    : normalizeLabel(server.type || typeVersionData?.server_type || 'Minecraft');
  const primaryHostPort = typeVersionData?.host_port
    ?? server.host_port
    ?? typeVersionData?.primary_host_port
    ?? server.primary_host_port;
  const gamePortProto = isSteam && typeVersionData?.game_port?.protocol
    ? `/${typeVersionData.game_port.protocol}` : '';
  const dataPath = typeVersionData?.data_path || server.data_path;
  
  const handleMouseEnter = useCallback(() => {
    if (server?.id) {
      fetch(`${API}/servers/${server.id}/info`, { headers: authHeaders() })
        .catch(() => {});
    }
  }, [server?.id]);

  return (
    <div
      className="rounded-xl bg-gradient-to-b from-white/10 to-white/5 border border-white/10 shadow-[0_8px_30px_rgb(0,0,0,0.12)] p-5 md:p-6 transition-all duration-200 hover:from-white/15 hover:to-white/10 cursor-pointer"
      onClick={onClick}
      onMouseEnter={handleMouseEnter}
      tabIndex={0}
      role="button"
      style={{ minHeight: 100 }}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4 md:gap-5">
          {onHandleDragStart && (
            <button
              type="button"
              onPointerDown={onHandleDragStart}
              onClick={(e) => e.stopPropagation()}
              className="flex items-center justify-center cursor-grab active:cursor-grabbing text-white/25 hover:text-white/60 transition-colors flex-shrink-0 -ml-1 py-2 px-1 touch-none select-none"
              title="Drag to reorder"
              aria-label="Drag to reorder"
            >
              <FaGripVertical />
            </button>
          )}
          <div className="w-12 h-12 rounded-lg bg-brand-500/90 ring-4 ring-brand-500/20 inline-flex items-center justify-center text-2xl text-white shadow-md flex-shrink-0">
            <FaServer />
          </div>
          <div>
            <div className="font-bold text-lg md:text-xl leading-tight text-white">{server.name}</div>
            <div className="text-xs md:text-sm text-white/60 break-all">{server.id.slice(0, 12)}</div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] md:text-xs text-white/60 mt-1">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/10 border border-white/15">
                {displayKind || <span className="text-white/40">Unknown</span>}
              </span>
              <span>
                Version: {typeVersionData?.server_version || server.version || <span className="text-white/40">Unknown</span>}
              </span>
              {primaryHostPort ? (
                <span>Port: {primaryHostPort}{gamePortProto}</span>
              ) : null}
            </div>
            {dataPath ? (
              <div className="text-[10px] text-white/40 mt-1 break-all">{dataPath}</div>
            ) : null}
            {stats && !stats.error && (
              <div className="flex flex-wrap items-center gap-2 mt-2 text-[11px] text-white/80">
                {stats.uptime_seconds > 0 && (
                  <span className="rounded-full bg-green-500/20 px-2 py-0.5 shadow-inner text-green-300">
                    <FaClock className="inline mr-1 text-[9px]" />{formatUptime(stats.uptime_seconds)}
                  </span>
                )}
                <span className="rounded-full bg-white/10 px-2 py-0.5 shadow-inner">CPU {Math.min(Math.round(stats.cpu_percent), 100)}%</span>
                <span className="rounded-full bg-white/10 px-2 py-0.5 shadow-inner">RAM {Math.round(stats.memory_usage_mb)}/{Math.round(stats.memory_limit_mb)} MB</span>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 md:self-start">
          {onTogglePin && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onTogglePin(server.id); }}
              className={`p-1.5 rounded-lg transition-colors ${isPinned ? 'text-yellow-400 hover:text-yellow-300' : 'text-white/25 hover:text-white/60'}`}
              title={isPinned ? 'Unpin server' : 'Pin server'}
              aria-label={isPinned ? 'Unpin server' : 'Pin server'}
              aria-pressed={isPinned}
            >
              {isPinned ? <FaStar /> : <FaRegStar />}
            </button>
          )}
          <div
            className={`text-xs md:text-sm px-3 py-1.5 rounded-full border ${
              server.status === 'running'
                ? 'bg-green-500/15 text-green-300 border-green-400/20'
                : 'bg-yellow-500/15 text-yellow-300 border-yellow-400/20'
            }`}
          >
            {server.status}
          </div>
          <FaChevronRight className="text-white/40 text-lg md:text-xl" />
        </div>
      </div>
    </div>
  );
});


export default function ServersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const servers = useServers();
  
  const normalizedServers = useMemo(
    () => (Array.isArray(servers) ? servers : []),
    [servers]
  );

  const [statusFilter, setStatusFilter] = useState('all');
  const [runtimeFilter, setRuntimeFilter] = useState('all');
  const [modpackFilter, setModpackFilter] = useState('all');

  // Custom drag-and-drop order (persisted in localStorage + synced to the
  // backend so it follows the user across devices).
  const [order, setOrder] = useState(loadServerOrder);
  const [pins, setPins] = useState(loadServerPins);
  const [dragId, setDragId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);

  const isInitialized = useIsInitialized();

  // On mount, adopt server-side preferences (source of truth). If the server
  // has none yet but this browser has local data, migrate it up once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const prefs = await fetchServerPrefs();
      if (cancelled || !prefs) return;
      const serverOrder = Array.isArray(prefs.server_order) ? prefs.server_order : [];
      const serverPins = Array.isArray(prefs.server_pins) ? prefs.server_pins : [];
      if (serverOrder.length) {
        setOrder(serverOrder);
        saveServerOrder(serverOrder);
      } else {
        const local = loadServerOrder();
        if (local.length) saveServerPrefs({ server_order: local });
      }
      if (serverPins.length) {
        setPins(serverPins);
        saveServerPins(serverPins);
      } else {
        const local = loadServerPins();
        if (local.length) saveServerPrefs({ server_pins: local });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const orderedServers = useMemo(() => {
    const base = sortByOrder(normalizedServers, order);
    if (!pins.length) return base;
    const pinSet = new Set(pins);
    const pinned = base.filter(s => pinSet.has(s.id));
    const rest = base.filter(s => !pinSet.has(s.id));
    return [...pinned, ...rest];
  }, [normalizedServers, order, pins]);

  const togglePin = useCallback((id) => {
    setPins(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id];
      saveServerPins(next);
      saveServerPrefs({ server_pins: next });
      return next;
    });
  }, []);

  const deriveRuntime = useCallback((server) => {
    const image = typeof server?.image === 'string' ? server.image.toLowerCase() : '';
    if (image === 'local' || image.includes('local-runtime')) return 'local';
    return 'docker';
  }, []);

  const deriveModpackKey = useCallback((server) => {
    const labels = (server && server.labels) || {};
    const provider = labels['mc.modpack.provider'];
    const packId = labels['mc.modpack.id'];
    const versionId = labels['mc.modpack.version_id'];
    if (provider && packId) {
      const key = `${provider}:${packId}`;
      const suffix = versionId ? ` (${versionId})` : '';
      return { key, label: `${provider} · ${packId}${suffix}` };
    }
    return { key: 'none', label: 'No modpack' };
  }, []);

  const formatLabel = useCallback((value) => {
    if (!value) return 'Unknown';
    return value
      .toString()
      .split(/[-_\s]+/)
      .filter(Boolean)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }, []);

  const filterSummary = useMemo(() => {
    const statusMap = new Map();
    const runtimeMap = new Map();
    const modpackMap = new Map();
    normalizedServers.forEach(server => {
      const status = (server?.status || 'unknown').toString().toLowerCase();
      statusMap.set(status, (statusMap.get(status) || 0) + 1);

      const runtime = deriveRuntime(server);
      runtimeMap.set(runtime, (runtimeMap.get(runtime) || 0) + 1);

      const modpack = deriveModpackKey(server);
      const existing = modpackMap.get(modpack.key) || { label: modpack.label, count: 0 };
      existing.label = modpack.label;
      existing.count += 1;
      modpackMap.set(modpack.key, existing);
    });
    if (!modpackMap.has('none')) {
      modpackMap.set('none', { label: 'No modpack', count: 0 });
    }
    return {
      statuses: Array.from(statusMap.entries()).map(([value, count]) => ({ value, count })),
      runtimes: Array.from(runtimeMap.entries()).map(([value, count]) => ({ value, count })),
      modpacks: Array.from(modpackMap.entries()).map(([value, info]) => ({ value, label: info.label, count: info.count })),
    };
  }, [normalizedServers, deriveRuntime, deriveModpackKey]);

  const statusOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All', count: normalizedServers.length }];
    filterSummary.statuses
      .slice()
      .sort((a, b) => b.count - a.count)
      .forEach(({ value, count }) => {
        options.push({ value, label: formatLabel(value), count });
      });
    return options;
  }, [filterSummary.statuses, normalizedServers.length, formatLabel]);

  const runtimeOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All', count: normalizedServers.length }];
    filterSummary.runtimes
      .slice()
      .sort((a, b) => b.count - a.count)
      .forEach(({ value, count }) => {
        options.push({ value, label: formatLabel(value), count });
      });
    return options;
  }, [filterSummary.runtimes, normalizedServers.length, formatLabel]);

  const modpackOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All', count: normalizedServers.length }];
    filterSummary.modpacks
      .slice()
      .sort((a, b) => b.count - a.count)
      .forEach(({ value, label, count }) => {
        if (value === 'none') {
          options.push({ value: 'none', label: 'No modpack', count });
        } else {
          options.push({ value, label, count });
        }
      });
    return options;
  }, [filterSummary.modpacks, normalizedServers.length]);

  const filteredServers = useMemo(() => {
    return orderedServers.filter(server => {
      const status = (server?.status || 'unknown').toString().toLowerCase();
      if (statusFilter !== 'all' && status !== statusFilter) return false;
      const runtime = deriveRuntime(server);
      if (runtimeFilter !== 'all' && runtime !== runtimeFilter) return false;
      const modpack = deriveModpackKey(server);
      if (modpackFilter === 'none') {
        if (modpack.key !== 'none') return false;
      } else if (modpackFilter !== 'all' && modpack.key !== modpackFilter) {
        return false;
      }
      return true;
    });
  }, [orderedServers, statusFilter, runtimeFilter, modpackFilter, deriveRuntime, deriveModpackKey]);

  const hasFilters = statusFilter !== 'all' || runtimeFilter !== 'all' || modpackFilter !== 'all';
  const totalServers = normalizedServers.length;

  const chipClass = useCallback((active) => (
    active
      ? 'px-3 py-1.5 rounded-full text-xs font-medium bg-brand-500 text-white border border-brand-500/70 shadow-sm transition-colors'
      : 'px-3 py-1.5 rounded-full text-xs font-medium bg-white/10 border border-white/10 text-white/80 hover:bg-white/15 transition-colors'
  ), []);

  const clearFilters = useCallback(() => {
    setStatusFilter('all');
    setRuntimeFilter('all');
    setModpackFilter('all');
  }, []);

  const handleSelectServer = useCallback((serverId) => {
    navigate(`/servers/${serverId}`);
  }, [navigate]);

  // Pointer-based drag-and-drop reordering. Uses Pointer Events so it works
  // for mouse, pen and touch alike (HTML5 native DnD has no touch support).
  const orderedRef = useRef(orderedServers);
  orderedRef.current = orderedServers;
  const dragCleanup = useRef(null);

  const commitReorder = useCallback((sourceId, targetId) => {
    if (!sourceId || sourceId === targetId) return;
    const ids = orderedRef.current.map(s => s.id);
    const from = ids.indexOf(sourceId);
    if (from === -1) return;
    ids.splice(from, 1);
    const insertAt = targetId ? ids.indexOf(targetId) : -1;
    if (insertAt === -1) ids.push(sourceId);
    else ids.splice(insertAt, 0, sourceId);
    setOrder(ids);
    saveServerOrder(ids);
    saveServerPrefs({ server_order: ids });
  }, []);

  const findServerIdAt = useCallback((x, y) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    const card = el.closest('[data-server-id]');
    return card ? card.getAttribute('data-server-id') : null;
  }, []);

  const beginDrag = useCallback((e, id) => {
    // Only start on primary button / touch / pen contact.
    if (typeof e.button === 'number' && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    // Tear down any previous drag listeners defensively.
    if (dragCleanup.current) dragCleanup.current();
    setDragId(id);

    const onMove = (ev) => {
      const overId = findServerIdAt(ev.clientX, ev.clientY);
      setDragOverId(overId && overId !== id ? overId : null);
    };
    const finish = (ev) => {
      const targetId = ev ? findServerIdAt(ev.clientX, ev.clientY) : null;
      cleanup();
      setDragId(null);
      setDragOverId(null);
      if (targetId) commitReorder(id, targetId);
    };
    const onUp = (ev) => finish(ev);
    const onCancel = () => finish(null);
    const onKey = (ev) => { if (ev.key === 'Escape') finish(null); };

    function cleanup() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
      window.removeEventListener('keydown', onKey);
      dragCleanup.current = null;
    }

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);
    window.addEventListener('keydown', onKey);
    dragCleanup.current = cleanup;
  }, [findServerIdAt, commitReorder]);

  // Clean up drag listeners if the component unmounts mid-drag.
  useEffect(() => () => { if (dragCleanup.current) dragCleanup.current(); }, []);

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <nav className="flex items-center gap-2 text-xs text-white/60">
        <button
          type="button"
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-1 hover:text-white transition-colors"
        >
          <FaHome className="text-sm" /> {t('nav.dashboard')}
        </button>
        <FaChevronRight className="text-white/40 text-[10px]" />
        <span className="text-white/80">{t('servers.title')}</span>
        {hasFilters ? (
          <span className="ml-2 text-white/50">{filteredServers.length} / {totalServers}</span>
        ) : null}
      </nav>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-3">
            <FaServer className="text-brand-500" /> <span className="gradient-text-brand">{t('servers.serverManagement')}</span>
          </h1>
          <p className="text-white/70 mt-2">{t('servers.manageDescription')}</p>
        </div>
      </div>

      {/* Servers List */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-4 sm:p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-white">{t('servers.yourServers')}</h3>
          <div className="flex items-center gap-3 text-xs text-white/60">
            {totalServers > 1 && (
              <span className="inline-flex items-center gap-1 text-white/40">
                <FaGripVertical className="text-[10px]" /> Drag to reorder
              </span>
            )}
            <span>{filteredServers.length} / {totalServers}</span>
            {hasFilters ? (
              <button
                type="button"
                onClick={clearFilters}
                className="px-3 py-1.5 rounded bg-white/10 hover:bg-white/20 text-xs text-white"
              >
                {t('common.clearFilters')}
              </button>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div>
            <div className="text-[11px] text-white/50 uppercase tracking-wide flex items-center gap-2 mb-2">
              <FaFilter className="text-white/40" /> Status
            </div>
            <div className="flex flex-wrap gap-2">
              {statusOptions.map(({ value, label, count }) => (
                <button
                  key={`status-${value}`}
                  type="button"
                  onClick={() => setStatusFilter(value)}
                  className={chipClass(statusFilter === value)}
                >
                  {label}
                  <span className="ml-1 text-[10px] opacity-70">{count}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-white/50 uppercase tracking-wide flex items-center gap-2 mb-2">
              <FaFilter className="text-white/40" /> Runtime
            </div>
            <div className="flex flex-wrap gap-2">
              {runtimeOptions.map(({ value, label, count }) => (
                <button
                  key={`runtime-${value}`}
                  type="button"
                  onClick={() => setRuntimeFilter(value)}
                  className={chipClass(runtimeFilter === value)}
                >
                  {label}
                  <span className="ml-1 text-[10px] opacity-70">{count}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-white/50 uppercase tracking-wide flex items-center gap-2 mb-2">
              <FaFilter className="text-white/40" /> Modpack
            </div>
            <div className="flex flex-wrap gap-2">
              {modpackOptions.map(({ value, label, count }) => (
                <button
                  key={`modpack-${value}`}
                  type="button"
                  onClick={() => setModpackFilter(value)}
                  className={chipClass(modpackFilter === value)}
                >
                  {label}
                  <span className="ml-1 text-[10px] opacity-70">{count}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {!isInitialized && totalServers === 0 ? (
          <div className="space-y-4">
            <ServerCardSkeleton />
            <ServerCardSkeleton />
            <ServerCardSkeleton />
          </div>
        ) : totalServers === 0 ? (
          <div className="text-white/60 text-center py-8 space-y-3">
            <div>No servers created yet. Use Templates to create your first server.</div>
            <button
              type="button"
              onClick={() => navigate('/templates')}
              className="inline-flex items-center gap-2 px-4 py-2 rounded bg-brand-500 hover:bg-brand-600 text-white text-sm"
            >
              Go to Templates
            </button>
          </div>
        ) : filteredServers.length === 0 ? (
          <div className="text-white/60 text-center py-8">
            No servers match the current filters.
          </div>
        ) : (
          <div className="space-y-4">
            {filteredServers.map((server) => (
              <div
                key={server.id}
                data-server-id={server.id}
                className={`rounded-xl transition-all duration-150 ${dragId === server.id ? 'opacity-40' : ''} ${dragOverId === server.id && dragId && dragId !== server.id ? 'ring-2 ring-brand-400' : ''}`}
              >
                <ServerListCard
                  server={server}
                  onClick={() => handleSelectServer(server.id)}
                  onHandleDragStart={(e) => beginDrag(e, server.id)}
                  isPinned={pins.includes(server.id)}
                  onTogglePin={togglePin}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
