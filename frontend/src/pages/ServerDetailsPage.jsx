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
} from 'react-icons/fa';

// Import subpanels
import TerminalPanel from '../components/TerminalPanel';
import BackupsPanel from '../components/server-details/BackupsPanel';
import ConfigPanel from '../components/server-details/ConfigPanel';
import WorldsPanel from '../components/server-details/WorldsPanel';
import SchedulePanel from '../components/server-details/SchedulePanel';
import PlayersPanel from '../components/server-details/PlayersPanel';
import FilesPanelWrapper from '../components/server-details/FilesPanelWrapper';
import EditingPanel from '../components/server-details/EditingPanel';

// Server stats hook
function useServerStats(serverId) {
  const globalData = useGlobalData();
  return globalData.serverStats[serverId] || null;
}

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

export default function ServerDetailsPage() {
  const { serverId, tab: urlTab = 'overview' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const globalData = useGlobalData();
  
  // Find server from global data
  const server = useMemo(() => {
    return globalData.servers.find(s => s.id === serverId) || null;
  }, [globalData.servers, serverId]);

  const [activeTab, setActiveTab] = useState(urlTab);
  const [filesEditing, setFilesEditing] = useState(false);
  const [editPath, setEditPath] = useState('');
  const [editContent, setEditContent] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [logReset, setLogReset] = useState(0);
  const [actionLoading, setActionLoading] = useState(null);

  const stats = useServerStats(serverId);

  // Sync tab from URL
  useEffect(() => {
    setActiveTab(urlTab);
  }, [urlTab]);

  // Update URL when tab changes
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

  // Server info
  const preloadedInfo = globalData.serverInfoById?.[serverId] || null;
  const { data: fetchedInfo } = useFetch(
    !preloadedInfo && serverId ? `${API}/servers/${serverId}/info` : null,
    [serverId]
  );
  const typeVersionData = preloadedInfo || fetchedInfo || null;
  const runtimeKind = (typeVersionData?.server_kind || server?.server_kind || '').toLowerCase();
  const isSteam = runtimeKind === 'steam';

  // Tabs configuration
  const tabs = useMemo(() => {
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
    if (isSteam) {
      const allowed = new Set(['overview', 'console', 'files', 'backup', 'schedule']);
      return base.filter(tab => allowed.has(tab.id));
    }
    return base;
  }, [isSteam, t]);

  // Server actions
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
      // Refresh servers list
      if (globalData.__refreshServers) {
        globalData.__refreshServers();
      }
      // Optimistic update
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
    if (!window.confirm('Are you sure you want to delete this server? This action cannot be undone.')) {
      return;
    }
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
    }
  }, [serverId, globalData, navigate]);

  const handleEditStart = useCallback((filePath, content) => {
    setEditPath(filePath);
    setEditContent(content);
    setIsEditing(true);
    setFilesEditing(true);
  }, []);

  // Loading state
  if (!server) {
    return (
      <div className="p-6">
        <button 
          onClick={() => navigate('/servers')}
          className="flex items-center gap-2 text-white/70 hover:text-white mb-4"
        >
          <FaArrowLeft /> Back to Servers
        </button>
        <div className="text-white/60">Server not found or loading...</div>
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
            <FaArrowLeft /> Back to Servers
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
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    isRunning ? 'bg-green-500/20 text-green-300' : 'bg-yellow-500/20 text-yellow-300'
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
                    Restart
                  </button>
                  <button
                    onClick={() => handleAction('stop')}
                    disabled={!!actionLoading}
                    className="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded flex items-center gap-2 disabled:opacity-50"
                  >
                    <FaStop />
                    Stop
                  </button>
                </>
              ) : (
                <button
                  onClick={() => handleAction('start')}
                  disabled={!!actionLoading}
                  className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded flex items-center gap-2 disabled:opacity-50"
                >
                  <FaPlay />
                  Start
                </button>
              )}
              <button
                onClick={handleDelete}
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
                className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm transition-colors whitespace-nowrap ${
                  activeTab === tab.id
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
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="glassmorphism rounded-xl p-4">
                <h3 className="text-sm font-medium text-white/60 mb-2">Server Info</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-white/60">Type</span>
                    <span className="text-white">{displayType}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/60">Version</span>
                    <span className="text-white">{displayVersion}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/60">Status</span>
                    <span className="text-white">{server.status}</span>
                  </div>
                  {server.host_port && (
                    <div className="flex justify-between">
                      <span className="text-white/60">Port</span>
                      <span className="text-white">{server.host_port}</span>
                    </div>
                  )}
                </div>
              </div>
              
              <div className="glassmorphism rounded-xl p-4">
                <h3 className="text-sm font-medium text-white/60 mb-2">Resources</h3>
                <div className="space-y-2 text-sm">
                  {stats && !stats.error ? (
                    <>
                      <div className="flex justify-between">
                        <span className="text-white/60">CPU Usage</span>
                        <span className="text-white">{stats.cpu_percent}%</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-white/60">Memory</span>
                        <span className="text-white">{Math.round(stats.memory_usage_mb)} / {Math.round(stats.memory_limit_mb)} MB</span>
                      </div>
                      {stats.uptime_seconds > 0 && (
                        <div className="flex justify-between">
                          <span className="text-white/60">Uptime</span>
                          <span className="text-white">{formatUptime(stats.uptime_seconds)}</span>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-white/40">No stats available</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
        
        {activeTab === 'console' && (
          <div className="h-[600px]">
            <TerminalPanel
              serverName={server.name}
              serverId={server.id}
              isRunning={isRunning}
              resetKey={logReset}
            />
          </div>
        )}
        
        {activeTab === 'files' && !isEditing && (
          <FilesPanelWrapper
            serverName={server.name}
            serverId={server.id}
            onEdit={handleEditStart}
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
      </div>
    </div>
  );
}
