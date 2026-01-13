import React, { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useGlobalData } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import {
  FaServer,
  FaHome,
  FaChevronRight,
  FaFilter,
  FaClock,
} from 'react-icons/fa';

// Format uptime helper
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

// Server List Card Component - uses preloaded data for instant display
const ServerListCard = React.memo(function ServerListCard({ server, onClick }) {
  const globalData = useGlobalData();
  const stats = globalData.serverStats[server.id] || null;
  
  // Use preloaded server info from global context - NO individual API calls
  const typeVersionData = globalData.serverInfoById?.[server.id] || null;

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
  const primaryHostPort = typeVersionData?.primary_host_port
    ?? server.primary_host_port
    ?? server.host_port;
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
                <span>Port: {primaryHostPort}</span>
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
                <span className="rounded-full bg-white/10 px-2 py-0.5 shadow-inner">CPU {stats.cpu_percent}%</span>
                <span className="rounded-full bg-white/10 px-2 py-0.5 shadow-inner">RAM {Math.round(stats.memory_usage_mb)}/{Math.round(stats.memory_limit_mb)} MB</span>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 md:self-start">
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

// Main Servers Page
export default function ServersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const globalData = useGlobalData();
  const servers = globalData?.servers || [];
  
  const normalizedServers = useMemo(
    () => (Array.isArray(servers) ? servers : []),
    [servers]
  );

  const [statusFilter, setStatusFilter] = useState('all');
  const [runtimeFilter, setRuntimeFilter] = useState('all');
  const [modpackFilter, setModpackFilter] = useState('all');

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
    return normalizedServers.filter(server => {
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
  }, [normalizedServers, statusFilter, runtimeFilter, modpackFilter, deriveRuntime, deriveModpackKey]);

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

        {totalServers === 0 ? (
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
              <ServerListCard
                key={server.id}
                server={server}
                onClick={() => handleSelectServer(server.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
