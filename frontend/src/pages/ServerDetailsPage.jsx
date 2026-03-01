import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useGlobalData } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import { useFetch } from '../lib/useFetch';
import {
  FaServer,
  FaPlay,
  FaStop,
  FaSync,
  FaTrash,
  FaArrowLeft,
  FaFolder,
  FaCog,
  FaUsers,
  FaDownload,
  FaClock,
  FaTerminal,
  FaCube,
  FaPlug,
  FaPuzzlePiece,
  FaGlobe,
  FaCopy,
  FaNetworkWired,
  FaHdd,
  FaCalendarAlt,
  FaGamepad,
  FaShieldAlt,
  FaInfoCircle,
  FaMicrochip,
  FaSlidersH,
} from 'react-icons/fa';


import TerminalPanel from '../components/TerminalPanel';
import BackupsPanel from '../components/server-details/BackupsPanel';
import ConfigPanel from '../components/server-details/ConfigPanel';
import WorldsPanel from '../components/server-details/WorldsPanel';
import SchedulePanel from '../components/server-details/SchedulePanel';
import PlayersPanel from '../components/server-details/PlayersPanel';
import FilesPanelWrapper from '../components/server-details/FilesPanelWrapper';
import EditingPanel from '../components/server-details/EditingPanel';
import ModsPanel from '../components/server-details/ModsPanel';
import PluginsPanel from '../components/server-details/PluginsPanel';
import SteamModsPanel from '../components/server-details/SteamModsPanel';
import SteamSettingsPanel from '../components/server-details/SteamSettingsPanel';
import ModManagerPanel from '../components/server-details/ModManagerPanel';
import ClientModFilterPanel from '../components/server-details/ClientModFilterPanel';
import ConfirmModal from '../components/ConfirmModal';


function useServerStats(serverId) {
  const globalData = useGlobalData();
  return globalData.serverStats[serverId] || null;
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

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export default function ServerDetailsPage() {
  const { serverId, tab: urlTab = 'overview' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const globalData = useGlobalData();


  const server = useMemo(() => {
    return globalData.servers.find(s => s.id === serverId) || null;
  }, [globalData.servers, serverId]);

  const [activeTab, setActiveTab] = useState(urlTab);
  const [filesEditing, setFilesEditing] = useState(false);
  const [editPath, setEditPath] = useState('');
  const [editContent, setEditContent] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [filesPath, setFilesPath] = useState('.');
  const [logReset, setLogReset] = useState(0);
  const [actionLoading, setActionLoading] = useState(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [copiedAddress, setCopiedAddress] = useState(false);

  const stats = useServerStats(serverId);


  useEffect(() => {
    setActiveTab(urlTab);
  }, [urlTab]);


  const handleTabChange = useCallback((newTab) => {
    setActiveTab(newTab);
    navigate(`/servers/${serverId}/${newTab}`, { replace: true });
  }, [navigate, serverId]);

  const prettify = useCallback((value) => {
    if (!value) return '';
    return value
      .toString()
      .split(/[-_\s]+/)
      .filter(Boolean)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }, []);


  const preloadedInfo = globalData.serverInfoById?.[serverId] || null;
  const { data: fetchedInfo } = useFetch(
    !preloadedInfo && serverId ? `${API}/servers/${serverId}/info` : null,
    [serverId]
  );
  const typeVersionData = preloadedInfo || fetchedInfo || null;
  const runtimeKind = (typeVersionData?.server_kind || server?.server_kind || '').toLowerCase();
  const isSteam = runtimeKind === 'steam';

  // Additional data for overview
  const { data: playerData } = useFetch(
    server?.name ? `${API}/players/${server.name}/roster` : null,
    [server?.name, server?.status]
  );
  const { data: backupData } = useFetch(
    server?.name ? `${API}/servers/${server.name}/backups` : null,
    [server?.name]
  );
  const { data: worldsData } = useFetch(
    server?.name ? `${API}/servers/${server.name}/worlds` : null,
    [server?.name]
  );
  const { data: schedulesData } = useFetch(
    server?.name ? `${API}/servers/${server.name}/schedules` : null,
    [server?.name]
  );


  const tabs = useMemo(() => {
    const serverType = (typeVersionData?.server_type || server?.type || '').toLowerCase();
    const isModdedServer = ['fabric', 'forge', 'neoforge'].includes(serverType);
    const isPluginServer = ['paper', 'purpur', 'spigot', 'bukkit'].includes(serverType);
    // Hybrid servers support BOTH mods and plugins
    const isHybridServer = ['mohist', 'magma', 'banner', 'catserver', 'spongeforge'].includes(serverType);

    const base = [
      { id: 'overview', label: t('tabs.overview'), icon: FaServer },
      { id: 'console', label: t('tabs.console') || 'Console', icon: FaTerminal },
      { id: 'files', label: t('tabs.files'), icon: FaFolder },
      { id: 'config', label: t('tabs.config'), icon: FaCog },
      { id: 'players', label: t('tabs.players'), icon: FaUsers },
      { id: 'worlds', label: t('tabs.worlds'), icon: FaFolder },
      { id: 'backup', label: t('tabs.backup'), icon: FaDownload },
      { id: 'schedule', label: t('tabs.schedule'), icon: FaClock },
    ];

    // Add Mods tab for Fabric/Forge/NeoForge
    if (isModdedServer || isHybridServer) {
      base.splice(3, 0, { id: 'mods', label: 'Mods', icon: FaCube });
      base.splice(4, 0, { id: 'mod-manager', label: 'Mod Manager', icon: FaPuzzlePiece });
      base.splice(5, 0, { id: 'client-mod-filter', label: 'Client Mod Filter', icon: FaShieldAlt });
    }

    // Add Plugins tab for Paper/Purpur/Spigot and hybrid servers
    if (isPluginServer || isHybridServer) {
      base.splice(3, 0, { id: 'plugins', label: 'Plugins', icon: FaPlug });
    }

    if (isSteam) {
      const allowed = new Set(['overview', 'console', 'files', 'mods', 'backup', 'schedule']);
      // Add mods tab for Steam games
      const steamBase = base.filter(tab => allowed.has(tab.id));
      // Insert settings tab after files
      const filesIdx = steamBase.findIndex(t => t.id === 'files');
      if (filesIdx !== -1) {
        steamBase.splice(filesIdx + 1, 0, { id: 'settings', label: 'Settings', icon: FaSlidersH });
        // Insert mods tab after settings
        if (!steamBase.find(t => t.id === 'mods')) {
          steamBase.splice(filesIdx + 2, 0, { id: 'mods', label: 'Mods', icon: FaCube });
        }
      }
      return steamBase;
    }
    return base;
  }, [isSteam, t, typeVersionData, server]);


  const handleAction = useCallback(async (action) => {
    if (!serverId || actionLoading) return;
    setActionLoading(action);
    try {
      const endpoint = `${API}/servers/${serverId}/${action}`;
      const r = await fetch(endpoint, {
        method: 'POST',
        headers: authHeaders()
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Action failed: ${r.status}`);
      }

      if (globalData.__refreshServers) {
        globalData.__refreshServers();
      }

      if (globalData.__updateServerStatus) {
        const statusMap = { start: 'running', stop: 'stopped', restart: 'running' };
        if (statusMap[action]) {
          globalData.__updateServerStatus(serverId, statusMap[action]);
        }
      }
      setLogReset(x => x + 1);
    } catch (err) {
      alert(`Failed to ${action} server: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  }, [serverId, actionLoading, globalData]);

  const handleDelete = useCallback(async () => {
    if (!serverId) return;
    setActionLoading('delete');
    try {
      const r = await fetch(`${API}/servers/${serverId}`, {
        method: 'DELETE',
        headers: authHeaders()
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Delete failed: ${r.status}`);
      }
      if (globalData.__refreshServers) {
        globalData.__refreshServers();
      }
      navigate('/servers');
    } catch (err) {
      alert(`Failed to delete server: ${err.message}`);
    } finally {
      setActionLoading(null);
      setShowDeleteModal(false);
    }
  }, [serverId, globalData, navigate]);

  const handleEditStart = useCallback((filePath, content) => {
    setEditPath(filePath);
    setEditContent(content);
    // Remember the directory this file is in so we restore it after editing
    const parts = filePath.split('/');
    parts.pop();
    setFilesPath(parts.length ? parts.join('/') : '.');
    setIsEditing(true);
    setFilesEditing(true);
  }, []);


  if (!server) {
    return (
      <div className="p-6">
        <button
          onClick={() => navigate('/servers')}
          className="flex items-center gap-2 text-white/70 hover:text-white mb-4"
        >
          <FaArrowLeft /> {t('servers.backToServers')}
        </button>
        <div className="text-white/60">{t('servers.serverNotFound')}</div>
      </div>
    );
  }

  const isRunning = server.status === 'running';
  const displayType = isSteam
    ? `Steam · ${prettify(typeVersionData?.steam_game || server?.steam_game || server?.type || 'Dedicated')}`
    : prettify(typeVersionData?.server_type || server.type || 'Minecraft');
  const displayVersion = typeVersionData?.server_version || server.version || 'Unknown';

  return (
    <div className="min-h-screen">
      {/* Header */}
      <div className="border-b border-white/10 bg-ink/80 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4">
          <button
            onClick={() => navigate('/servers')}
            className="flex items-center gap-2 text-white/60 hover:text-white text-sm mb-4"
          >
            <FaArrowLeft /> {t('servers.backToServers')}
          </button>

          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-lg bg-brand-500/90 ring-4 ring-brand-500/20 flex items-center justify-center text-2xl text-white">
                <FaServer />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">{server.name}</h1>
                <div className="flex items-center gap-3 text-sm text-white/60 mt-1">
                  <span>{displayType}</span>
                  <span>•</span>
                  <span>{displayVersion}</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${isRunning ? 'bg-green-500/20 text-green-300' : 'bg-yellow-500/20 text-yellow-300'
                    }`}>
                    {server.status}
                  </span>
                </div>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2">
              {isRunning ? (
                <>
                  <button
                    onClick={() => handleAction('restart')}
                    disabled={!!actionLoading}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded flex items-center gap-2 disabled:opacity-50"
                  >
                    <FaSync className={actionLoading === 'restart' ? 'animate-spin' : ''} />
                    {t('servers.restart')}
                  </button>
                  <button
                    onClick={() => handleAction('stop')}
                    disabled={!!actionLoading}
                    className="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded flex items-center gap-2 disabled:opacity-50"
                  >
                    <FaStop />
                    {t('servers.stop')}
                  </button>
                </>
              ) : (
                <button
                  onClick={() => handleAction('start')}
                  disabled={!!actionLoading}
                  className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded flex items-center gap-2 disabled:opacity-50"
                >
                  <FaPlay />
                  {t('servers.start')}
                </button>
              )}
              <button
                onClick={() => setShowDeleteModal(true)}
                disabled={!!actionLoading}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded flex items-center gap-2 disabled:opacity-50"
              >
                <FaTrash />
              </button>
            </div>
          </div>

          {/* Stats bar */}
          {stats && !stats.error && isRunning && (
            <div className="flex items-center gap-4 mt-4 text-sm text-white/70">
              {stats.uptime_seconds > 0 && (
                <span>Uptime: {formatUptime(stats.uptime_seconds)}</span>
              )}
              <span>CPU: {stats.cpu_percent}%</span>
              <span>RAM: {Math.round(stats.memory_usage_mb)}/{Math.round(stats.memory_limit_mb)} MB</span>
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 mt-4 overflow-x-auto pb-1">
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm transition-colors whitespace-nowrap ${activeTab === tab.id
                  ? 'bg-white/10 text-white border-b-2 border-brand-500'
                  : 'text-white/60 hover:text-white hover:bg-white/5'
                  }`}
              >
                <tab.icon className="text-xs" />
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Tab Content */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
        {activeTab === 'overview' && (() => {
          const backups = Array.isArray(backupData) ? backupData : backupData?.backups || [];
          const worlds = Array.isArray(worldsData) ? worldsData : worldsData?.worlds || [];
          const tasks = Array.isArray(schedulesData) ? schedulesData : schedulesData?.tasks || [];
          const onlinePlayers = playerData?.online || [];
          const onlineCount = playerData?.count || onlinePlayers.length;
          const maxPlayers = playerData?.max || 0;
          const connectPort = server.host_port || typeVersionData?.host_port;
          const steamPorts = typeVersionData?.steam_ports || server?.steam_ports || [];
          const gamePortInfo = typeVersionData?.game_port || server?.game_port;
          const portSummary = typeVersionData?.port_summary || server?.port_summary || [];

          return (
          <div className="space-y-5">
            {/* Quick Connect Banner */}
            {connectPort && (
              <div className="glassmorphism rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-brand-500/20 flex items-center justify-center flex-shrink-0">
                    <FaGlobe className="text-brand-400 text-xl" />
                  </div>
                  <div>
                    <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider">Quick Connect</h3>
                    <p className="text-white font-mono text-lg mt-0.5">localhost:{connectPort}</p>
                    {isSteam && portSummary.length > 1 && (
                      <p className="text-white/40 text-xs mt-1 font-mono">
                        All ports: {portSummary.join(', ')}
                      </p>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(`localhost:${connectPort}`);
                    setCopiedAddress(true);
                    setTimeout(() => setCopiedAddress(false), 2000);
                  }}
                  className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all text-sm ${
                    copiedAddress
                      ? 'bg-green-500/20 text-green-300'
                      : 'bg-white/10 hover:bg-white/20 text-white'
                  }`}
                >
                  <FaCopy className="text-xs" />
                  {copiedAddress ? 'Copied!' : 'Copy Address'}
                </button>
              </div>
            )}

            {/* Server Info + Resources */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Server Info — Enhanced */}
              <div className="glassmorphism rounded-xl p-5">
                <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <FaInfoCircle className="text-blue-400" />
                  {t('servers.serverInfo')}
                </h3>
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between items-center">
                    <span className="text-white/50">{t('common.type')}</span>
                    <span className="text-white font-medium">{displayType}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-white/50">{t('common.version')}</span>
                    <span className="text-white font-medium">{displayVersion}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-white/50">{t('common.status')}</span>
                    <span className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-400 animate-pulse' : 'bg-yellow-400'}`} />
                      <span className={isRunning ? 'text-green-300' : 'text-yellow-300'}>{server.status}</span>
                    </span>
                  </div>
                  {connectPort && (
                    <div className="flex justify-between items-center">
                      <span className="text-white/50">{isSteam ? 'Game Port' : t('servers.port')}</span>
                      <span className="text-white font-mono">{connectPort}{gamePortInfo?.protocol ? `/${gamePortInfo.protocol}` : ''}</span>
                    </div>
                  )}
                  {isSteam && steamPorts.length > 1 && (
                    <div className="flex justify-between items-start">
                      <span className="text-white/50">All Ports</span>
                      <div className="text-right">
                        {steamPorts.map((sp, i) => (
                          <span key={i} className="text-white/70 font-mono text-xs block">
                            {sp.host_port || sp.container_port}/{sp.protocol}
                            {gamePortInfo && sp.container_port === gamePortInfo.container_port && sp.protocol === gamePortInfo.protocol
                              ? ' (game)' : ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex justify-between items-center">
                    <span className="text-white/50">Server ID</span>
                    <span className="text-white/60 font-mono text-xs">{serverId.substring(0, 12)}</span>
                  </div>
                  {!isSteam && typeVersionData?.java_version && (
                    <div className="flex justify-between items-center">
                      <span className="text-white/50">Java</span>
                      <span className="text-white font-medium">Java {typeVersionData.java_version}</span>
                    </div>
                  )}
                  {typeVersionData?.loader_version && (
                    <div className="flex justify-between items-center">
                      <span className="text-white/50">Loader</span>
                      <span className="text-white font-medium">{typeVersionData.loader_version}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Resources — Enhanced with progress bars */}
              <div className="glassmorphism rounded-xl p-5">
                <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <FaMicrochip className="text-purple-400" />
                  {t('servers.resources')}
                </h3>
                {stats && !stats.error && isRunning ? (
                  <div className="space-y-4 text-sm">
                    {/* CPU */}
                    <div>
                      <div className="flex justify-between items-center mb-1.5">
                        <span className="text-white/50">{t('servers.cpuUsage')}</span>
                        <span className={`font-medium ${
                          stats.cpu_percent > 80 ? 'text-red-400' : stats.cpu_percent > 50 ? 'text-yellow-400' : 'text-green-400'
                        }`}>
                          {stats.cpu_percent}%
                        </span>
                      </div>
                      <div className="w-full bg-white/10 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full transition-all duration-500 ${
                            stats.cpu_percent > 80 ? 'bg-red-500' : stats.cpu_percent > 50 ? 'bg-yellow-500' : 'bg-green-500'
                          }`}
                          style={{ width: `${Math.min(stats.cpu_percent, 100)}%` }}
                        />
                      </div>
                    </div>
                    {/* Memory */}
                    <div>
                      {(() => {
                        const memPct = stats.memory_limit_mb > 0
                          ? Math.round((stats.memory_usage_mb / stats.memory_limit_mb) * 100)
                          : 0;
                        return (
                          <>
                            <div className="flex justify-between items-center mb-1.5">
                              <span className="text-white/50">{t('servers.memory')}</span>
                              <span className={`font-medium ${
                                memPct > 85 ? 'text-red-400' : memPct > 60 ? 'text-yellow-400' : 'text-green-400'
                              }`}>
                                {Math.round(stats.memory_usage_mb)} / {Math.round(stats.memory_limit_mb)} MB
                              </span>
                            </div>
                            <div className="w-full bg-white/10 rounded-full h-2">
                              <div
                                className={`h-2 rounded-full transition-all duration-500 ${
                                  memPct > 85 ? 'bg-red-500' : memPct > 60 ? 'bg-yellow-500' : 'bg-green-500'
                                }`}
                                style={{ width: `${Math.min(memPct, 100)}%` }}
                              />
                            </div>
                          </>
                        );
                      })()}
                    </div>
                    {/* Network I/O */}
                    {(stats.network_rx_mb !== undefined || stats.network_tx_mb !== undefined) && (
                      <div className="flex justify-between items-center pt-1">
                        <span className="text-white/50 flex items-center gap-1.5">
                          <FaNetworkWired className="text-xs" /> Network
                        </span>
                        <span className="text-white font-mono text-xs">
                          ↓ {(stats.network_rx_mb || 0).toFixed(1)} MB&nbsp;&nbsp;↑ {(stats.network_tx_mb || 0).toFixed(1)} MB
                        </span>
                      </div>
                    )}
                    {/* Uptime */}
                    {stats.uptime_seconds > 0 && (
                      <div className="flex justify-between items-center">
                        <span className="text-white/50">{t('servers.uptime')}</span>
                        <span className="text-white font-medium">{formatUptime(stats.uptime_seconds)}</span>
                      </div>
                    )}
                    {/* Restart count */}
                    {stats.restart_count > 0 && (
                      <div className="flex justify-between items-center">
                        <span className="text-white/50">Restarts</span>
                        <span className="text-yellow-400 font-medium">{stats.restart_count}</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-8 text-white/30">
                    <FaMicrochip className="text-2xl mb-2" />
                    <span className="text-sm">{isRunning ? t('servers.noStatsAvailable') : 'Server is offline'}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Players + Worlds / Storage */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Online Players */}
              {!isSteam && (
                <div className="glassmorphism rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider flex items-center gap-2">
                      <FaGamepad className="text-green-400" />
                      Players Online
                    </h3>
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-300">
                      {onlineCount}{maxPlayers > 0 ? ` / ${maxPlayers}` : ''}
                    </span>
                  </div>
                  {onlinePlayers.length > 0 ? (
                    <div className="space-y-2">
                      {onlinePlayers.slice(0, 8).map((name, i) => (
                        <div key={i} className="flex items-center gap-2.5 text-sm">
                          <img
                            src={`https://mc-heads.net/avatar/${encodeURIComponent(name)}/24`}
                            alt={name}
                            className="w-6 h-6 rounded flex-shrink-0"
                            onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                          />
                          <span
                            className="w-6 h-6 rounded bg-brand-600 items-center justify-center text-[10px] font-bold text-white flex-shrink-0 hidden"
                          >
                            {name.slice(0, 1).toUpperCase()}
                          </span>
                          <span className="text-white">{name}</span>
                        </div>
                      ))}
                      {onlinePlayers.length > 8 && (
                        <p className="text-white/40 text-xs">+{onlinePlayers.length - 8} more</p>
                      )}
                      <button
                        onClick={() => handleTabChange('players')}
                        className="text-brand-400 hover:text-brand-300 text-xs mt-2 transition-colors"
                      >
                        View all players →
                      </button>
                    </div>
                  ) : onlineCount > 0 ? (
                    <div className="space-y-3">
                      <div className="flex items-center gap-3 py-2">
                        <div className="flex -space-x-1.5">
                          {Array.from({ length: Math.min(onlineCount, 5) }).map((_, i) => (
                            <div key={i} className="w-6 h-6 rounded-full bg-green-500/30 border-2 border-[#1a1a2e] flex items-center justify-center">
                              <FaUsers className="text-green-400 text-[8px]" />
                            </div>
                          ))}
                        </div>
                        <span className="text-white text-sm font-medium">
                          {onlineCount} player{onlineCount !== 1 ? 's' : ''} online
                        </span>
                      </div>
                      <p className="text-white/40 text-xs">Player names unavailable — enable RCON for detailed info</p>
                      <button
                        onClick={() => handleTabChange('players')}
                        className="text-brand-400 hover:text-brand-300 text-xs mt-1 transition-colors"
                      >
                        View players tab →
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-8 text-white/30">
                      <FaUsers className="text-2xl mb-2" />
                      <span className="text-sm">{isRunning ? 'No players online' : 'Server is offline'}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Storage / Worlds */}
              <div className={`glassmorphism rounded-xl p-5 ${isSteam ? 'md:col-span-2' : ''}`}>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider flex items-center gap-2">
                    <FaHdd className="text-orange-400" />
                    {isSteam ? 'Storage' : 'Worlds'}
                  </h3>
                  {worlds.length > 0 && (
                    <span className="text-xs text-white/40">
                      {worlds.length} world{worlds.length !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {worlds.length > 0 ? (
                  <div className="space-y-1">
                    {worlds.slice(0, 5).map((world, i) => (
                      <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-white/5 last:border-0">
                        <div className="flex items-center gap-2">
                          <FaFolder className="text-white/30 text-xs" />
                          <span className="text-white">{world.name}</span>
                        </div>
                        <span className="text-white/50 text-xs font-mono">{formatBytes(world.size)}</span>
                      </div>
                    ))}
                    {!isSteam && (
                      <button
                        onClick={() => handleTabChange('worlds')}
                        className="text-brand-400 hover:text-brand-300 text-xs mt-2 transition-colors"
                      >
                        Manage worlds →
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-8 text-white/30">
                    <FaHdd className="text-2xl mb-2" />
                    <span className="text-sm">No world data available</span>
                  </div>
                )}
              </div>
            </div>

            {/* Backups + Scheduled Tasks */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Recent Backups */}
              <div className="glassmorphism rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider flex items-center gap-2">
                    <FaDownload className="text-cyan-400" />
                    Recent Backups
                  </h3>
                  {backups.length > 0 && (
                    <span className="text-xs text-white/40">{backups.length} total</span>
                  )}
                </div>
                {backups.length > 0 ? (
                  <div className="space-y-1">
                    {backups.slice(0, 3).map((backup, i) => (
                      <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-white/5 last:border-0">
                        <span className="text-white truncate max-w-[55%]">{backup.name}</span>
                        <div className="flex items-center gap-3 text-xs text-white/40">
                          <span>{formatBytes(backup.size)}</span>
                          {formatDate(backup.modified) && <span>{formatDate(backup.modified)}</span>}
                        </div>
                      </div>
                    ))}
                    <button
                      onClick={() => handleTabChange('backup')}
                      className="text-brand-400 hover:text-brand-300 text-xs mt-2 transition-colors"
                    >
                      Manage backups →
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-8 text-white/30">
                    <FaDownload className="text-2xl mb-2" />
                    <span className="text-sm">No backups yet</span>
                    <button
                      onClick={() => handleTabChange('backup')}
                      className="text-brand-400 hover:text-brand-300 text-xs mt-3 transition-colors"
                    >
                      Create first backup →
                    </button>
                  </div>
                )}
              </div>

              {/* Scheduled Tasks */}
              <div className="glassmorphism rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider flex items-center gap-2">
                    <FaCalendarAlt className="text-indigo-400" />
                    Scheduled Tasks
                  </h3>
                  {tasks.length > 0 && (
                    <span className="text-xs text-white/40">
                      {tasks.filter(tk => tk.enabled !== false).length} active
                    </span>
                  )}
                </div>
                {tasks.length > 0 ? (
                  <div className="space-y-1">
                    {tasks.slice(0, 4).map((task, i) => (
                      <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-white/5 last:border-0">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                            task.enabled !== false ? 'bg-green-400' : 'bg-white/20'
                          }`} />
                          <span className="text-white">{task.name || task.action}</span>
                        </div>
                        <span className="text-white/40 text-xs font-mono">{task.schedule || task.cron || ''}</span>
                      </div>
                    ))}
                    <button
                      onClick={() => handleTabChange('schedule')}
                      className="text-brand-400 hover:text-brand-300 text-xs mt-2 transition-colors"
                    >
                      Manage schedules →
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-8 text-white/30">
                    <FaCalendarAlt className="text-2xl mb-2" />
                    <span className="text-sm">No scheduled tasks</span>
                    <button
                      onClick={() => handleTabChange('schedule')}
                      className="text-brand-400 hover:text-brand-300 text-xs mt-3 transition-colors"
                    >
                      Create a schedule →
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Runtime Configuration (Minecraft only) */}
            {!isSteam && typeVersionData && (typeVersionData.java_version || typeVersionData.java_opts) && (
              <div className="glassmorphism rounded-xl p-5">
                <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <FaShieldAlt className="text-yellow-400" />
                  Runtime Configuration
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3 text-sm">
                  {typeVersionData.java_version && (
                    <div className="flex justify-between items-center">
                      <span className="text-white/50">Java Version</span>
                      <span className="text-white font-mono">Java {typeVersionData.java_version}</span>
                    </div>
                  )}
                  {typeVersionData.java_path && (
                    <div className="flex justify-between items-center">
                      <span className="text-white/50">Java Path</span>
                      <span className="text-white/60 font-mono text-xs truncate max-w-[200px]" title={typeVersionData.java_path}>
                        {typeVersionData.java_path}
                      </span>
                    </div>
                  )}
                  {typeVersionData.java_opts && (
                    <div className="sm:col-span-2">
                      <span className="text-white/50 text-sm">JVM Arguments</span>
                      <div className="mt-1.5 p-3 bg-white/5 rounded-lg font-mono text-xs text-white/70 break-all leading-relaxed">
                        {typeVersionData.java_opts}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
          );
        })()}

        {activeTab === 'console' && (
          <div className="h-[600px]">
            <TerminalPanel
              serverId={server.id}
              resetToken={logReset}
            />
          </div>
        )}

        {activeTab === 'files' && !isEditing && (
          <FilesPanelWrapper
            serverName={server.name}
            serverId={server.id}
            onEdit={handleEditStart}
            initialPath={filesPath}
            onPathChange={setFilesPath}
          />
        )}

        {activeTab === 'files' && isEditing && (
          <EditingPanel
            serverName={server.name}
            serverId={server.id}
            filePath={editPath}
            initialContent={editContent}
            onClose={() => {
              setIsEditing(false);
              setFilesEditing(false);
            }}
          />
        )}

        {activeTab === 'config' && (
          <ConfigPanel
            server={server}
          />
        )}

        {activeTab === 'players' && (
          <PlayersPanel
            serverName={server.name}
            serverId={server.id}
          />
        )}

        {activeTab === 'worlds' && (
          <WorldsPanel
            serverName={server.name}
            serverId={server.id}
          />
        )}

        {activeTab === 'backup' && (
          <BackupsPanel
            serverName={server.name}
            serverId={server.id}
          />
        )}

        {activeTab === 'schedule' && (
          <SchedulePanel
            serverName={server.name}
            serverId={server.id}
          />
        )}

        {activeTab === 'settings' && isSteam && (
          <SteamSettingsPanel
            serverName={server.name}
            serverId={server.id}
            gameSlug={typeVersionData?.steam_game || server?.steam_game || server?.type || ''}
          />
        )}

        {activeTab === 'mods' && (
          isSteam ? (
            <SteamModsPanel
              serverId={server.id}
              serverName={server.name}
              gameSlug={typeVersionData?.server_type || server?.type || ''}
            />
          ) : (
            <ModsPanel
              serverName={server.name}
              serverVersion={typeVersionData?.server_version || server?.version || ''}
              serverLoader={(typeVersionData?.server_type || server?.type || '').toLowerCase()}
            />
          )
        )}

        {activeTab === 'plugins' && (
          <PluginsPanel
            serverName={server.name}
            serverVersion={typeVersionData?.server_version || server?.version || ''}
            serverType={(typeVersionData?.server_type || server?.type || '').toLowerCase()}
          />
        )}

        {activeTab === 'mod-manager' && (
          <ModManagerPanel
            serverName={server.name}
          />
        )}

        {activeTab === 'client-mod-filter' && (
          <ClientModFilterPanel
            serverName={server.name}
          />
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteModal}
        title={t('modals.deleteServer')}
        message={t('modals.deleteServerMessage', { name: server?.name })}
        confirmText={t('servers.deleteServer')}
        cancelText={t('common.cancel')}
        confirmVariant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
        isLoading={actionLoading === 'delete'}
      />
    </div>
  );
}
