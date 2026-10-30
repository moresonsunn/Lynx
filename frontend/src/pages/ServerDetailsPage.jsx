import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useServerById, useServerStats, useServerInfo, useGlobalActions } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import { useFetch } from '../lib/useFetch';
import { useServerAccess } from '../hooks/useServerAccess';
import { defaultMuteRegexes } from '../lib/consoleFilters';
import { ansiToHtml } from '../lib/ansiToHtml';
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
  FaChartArea,
  FaUserShield,
  FaChevronDown,
  FaExpandAlt,
  FaPause,
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
import ResourceGraphs from '../components/ResourceGraphs';
import ServerPermissionsPanel from '../components/server-details/ServerPermissionsPanel';
import ConfirmModal from '../components/ConfirmModal';
import RamSlider from '../components/RamSlider';
import CpuSlider from '../components/CpuSlider';

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

/**
 * Read-only Live Console Feed for the Server Overview tab.
 * Polls recent logs and renders colored output without command execution.
 */
function LiveConsolePreview({ serverId, isRunning, resetToken = 0, onOpenConsole }) {
  const [rawLogs, setRawLogs] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!serverId) return;
    let active = true;
    let timer = null;
    let ctrl = null;

    async function pollLogs() {
      if (!active) return;
      if (typeof document !== 'undefined' && document.hidden) {
        timer = setTimeout(pollLogs, 3500);
        return;
      }
      try {
        ctrl = new AbortController();
        const timeout = setTimeout(() => { try { ctrl.abort(); } catch {} }, 10000);
        const r = await fetch(`${API}/servers/${serverId}/logs?tail=80`, {
          headers: authHeaders(),
          signal: ctrl.signal,
        });
        clearTimeout(timeout);
        const d = await r.json();
        if (active && d && typeof d.logs === 'string') {
          setRawLogs(d.logs);
        }
      } catch (e) {
        if (active && e && e.name !== 'AbortError') {
          // keep previous logs on transient error
        }
      } finally {
        if (active) timer = setTimeout(pollLogs, 3000);
      }
    }

    pollLogs();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
      try { ctrl && ctrl.abort(); } catch {}
    };
  }, [serverId, resetToken]);

  const filteredLogs = useMemo(() => {
    if (!rawLogs) return '';
    const lines = rawLogs.split(/\r?\n/);
    const kept = lines.filter(line => !defaultMuteRegexes.some(rx => rx.test(line)));
    return kept.slice(-60).join('\n');
  }, [rawLogs]);

  const renderedHtml = useMemo(() => {
    if (!filteredLogs) return '';
    return ansiToHtml(filteredLogs);
  }, [filteredLogs]);

  const lineCount = useMemo(() => {
    if (!filteredLogs) return 0;
    return filteredLogs.split('\n').filter(Boolean).length;
  }, [filteredLogs]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredLogs, autoScroll]);

  return (
    <div className="glassmorphism rounded-xl p-5 border border-white/10">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand-500/15 border border-brand-500/30 flex items-center justify-center text-brand-400">
            <FaTerminal className="text-xs" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
                Live Console Activity
              </h3>
              <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium ${
                isRunning
                  ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                  : 'bg-white/10 text-white/50'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-emerald-400 animate-pulse' : 'bg-white/40'}`} />
                {isRunning ? 'Live Stream' : 'Offline'}
              </span>
              <span className="hidden sm:inline text-[11px] text-white/35">
                Read-only preview ({lineCount} lines)
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAutoScroll(v => !v)}
            className={`px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors border ${
              autoScroll
                ? 'bg-white/10 text-white border-white/15'
                : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
            }`}
            title={autoScroll ? 'Pause auto-scroll' : 'Resume auto-scroll'}
          >
            <FaPause className="text-[10px]" />
            <span className="hidden sm:inline">{autoScroll ? 'Auto-Scroll' : 'Paused'}</span>
          </button>

          <button
            type="button"
            onClick={onOpenConsole}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-500/20 hover:bg-brand-500/30 text-brand-300 border border-brand-500/30 flex items-center gap-1.5 transition-colors"
          >
            <FaExpandAlt className="text-[10px]" />
            <span>Open Console →</span>
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="text-xs text-white/75 whitespace-pre-wrap bg-black/50 border border-white/10 p-3.5 rounded-lg h-52 overflow-y-auto font-mono leading-relaxed select-text"
        dangerouslySetInnerHTML={{
          __html: renderedHtml || '<span class="text-white/35">Waiting for console output...</span>',
        }}
      />
    </div>
  );
}

function SettingsModalContent({ server, serverId, typeVersionData, isSteam }) {
  const serverType = (typeVersionData?.server_type || server?.type || '').toLowerCase();

  const [ramMax, setRamMax] = useState('4G');
  const [ramMin, setRamMin] = useState('2G');
  const [ramLoading, setRamLoading] = useState(true);
  const [ramSaving, setRamSaving] = useState(false);
  const [ramMsg, setRamMsg] = useState('');
  const [cpuCores, setCpuCores] = useState(null);
  const [cpuLoading, setCpuLoading] = useState(true);
  const [cpuSaving, setCpuSaving] = useState(false);
  const [cpuMsg, setCpuMsg] = useState('');

  useEffect(() => {
    if (isSteam || !serverId) return;
    let cancelled = false;
    async function loadRam() {
      try {
        const r = await fetch(`${API}/servers/${serverId}/ram`, { headers: authHeaders() });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (!cancelled) {
          if (d.max_ram) setRamMax(d.max_ram);
          if (d.min_ram) setRamMin(d.min_ram);
        }
      } catch {
        // keep defaults
      } finally {
        if (!cancelled) setRamLoading(false);
      }
    }
    loadRam();
    return () => { cancelled = true; };
  }, [serverId, isSteam]);

  const handleRamSave = async () => {
    setRamSaving(true);
    setRamMsg('');
    try {
      const r = await fetch(`${API}/servers/${serverId}/ram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ min_ram: ramMin, max_ram: ramMax }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setRamMsg('RAM updated — server is restarting...');
      setTimeout(() => setRamMsg(''), 4000);
    } catch (e) {
      setRamMsg(`Failed: ${e.message}`);
    } finally {
      setRamSaving(false);
    }
  };

  useEffect(() => {
    if (isSteam || !serverId) { setCpuLoading(false); return; }
    let cancelled = false;
    async function loadCpu() {
      try {
        const r = await fetch(`${API}/servers/${serverId}/cpu`, { headers: authHeaders() });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (!cancelled && d && !d.unlimited && d.cpu_cores) setCpuCores(d.cpu_cores);
      } catch {
        // keep unlimited default
      } finally {
        if (!cancelled) setCpuLoading(false);
      }
    }
    loadCpu();
    return () => { cancelled = true; };
  }, [serverId, isSteam]);

  const handleCpuSave = async () => {
    setCpuSaving(true);
    setCpuMsg('');
    try {
      const r = await fetch(`${API}/servers/${serverId}/cpu`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ cpu_cores: cpuCores }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setCpuMsg(cpuCores ? `Capped at ${cpuCores} core${cpuCores === 1 ? '' : 's'} — applied live.` : 'Unlimited — applied live.');
      setTimeout(() => setCpuMsg(''), 4000);
    } catch (e) {
      setCpuMsg(`Failed: ${e.message}`);
    } finally {
      setCpuSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {!isSteam && (
        <div className="glassmorphism rounded-xl p-4">
          <h4 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3 flex items-center gap-2">
            <FaMicrochip className="text-purple-400" />
            Memory Allocation
          </h4>
          {ramLoading ? (
            <div className="text-sm text-white/50">Loading current RAM...</div>
          ) : (
            <>
              <RamSlider
                value={ramMax}
                onChange={(v) => {
                  setRamMax(v);
                  try {
                    const gb = parseInt(String(v).replace(/[^0-9]/g, ''), 10) || 4;
                    setRamMin(`${Math.max(1, Math.floor(gb / 2))}G`);
                  } catch {}
                }}
                showCategories={false}
                label="Max RAM — min is auto-set to half. Restart required."
              />
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mt-3">
                <span className="text-xs text-white/50">Current: {ramMin} → {ramMax} {ramMsg && <span className="ml-2 text-purple-300">{ramMsg}</span>}</span>
                <button
                  onClick={handleRamSave}
                  disabled={ramSaving}
                  className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold whitespace-nowrap"
                >
                  {ramSaving ? 'Saving...' : 'Save & Restart'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
      {!isSteam && (
        <div className="glassmorphism rounded-xl p-4">
          <h4 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3 flex items-center gap-2">
            <FaMicrochip className="text-emerald-400" />
            CPU Allocation
          </h4>
          {cpuLoading ? (
            <div className="text-sm text-white/50">Loading CPU limit...</div>
          ) : (
            <>
              <CpuSlider
                value={cpuCores}
                onChange={setCpuCores}
                label="Hard cap — the server can never use more than this. Applies instantly, no restart."
              />
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mt-3">
                <span className="text-xs text-white/50">Current: {cpuCores ? `${cpuCores} core${cpuCores === 1 ? '' : 's'}` : 'unlimited'} {cpuMsg && <span className="ml-2 text-emerald-300">{cpuMsg}</span>}</span>
                <button
                  onClick={handleCpuSave}
                  disabled={cpuSaving}
                  className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold whitespace-nowrap"
                >
                  {cpuSaving ? 'Saving...' : 'Apply Live'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
      <div className="glassmorphism rounded-xl p-4">
        <h4 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3 flex items-center gap-2">
          <FaInfoCircle className="text-blue-400" />
          Runtime & Container Info
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-white/50">Type</span>
            <span className="text-white font-medium">{isSteam ? `Steam · ${server.steam_game || server.type}` : (serverType || 'Minecraft')}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-white/50">Version</span>
            <span className="text-white font-medium">{typeVersionData?.server_version || server.version || 'Unknown'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-white/50">Status</span>
            <span className={`flex items-center gap-2 ${server.status === 'running' ? 'text-green-300' : 'text-yellow-300'}`}>
              <span className={`w-2 h-2 rounded-full ${server.status === 'running' ? 'bg-green-400 animate-pulse' : 'bg-yellow-400'}`} />
              {server.status}
            </span>
          </div>
          {server.host_port && (
            <div className="flex justify-between">
              <span className="text-white/50">Port</span>
              <span className="text-white font-mono">{server.host_port}</span>
            </div>
          )}
          {typeVersionData?.java_version && (
            <div className="flex justify-between">
              <span className="text-white/50">Java</span>
              <span className="text-white font-medium">Java {typeVersionData.java_version}</span>
            </div>
          )}
          {typeVersionData?.loader_version && (
            <div className="flex justify-between">
              <span className="text-white/50">Loader</span>
              <span className="text-white font-medium">{typeVersionData.loader_version}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ServerDetailsPage() {
  const { serverId, tab: urlTab = 'overview' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const actions = useGlobalActions();

  const server = useServerById(serverId);
  const access = useServerAccess(server?.name);

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
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const moreMenuRef = useRef(null);

  const stats = useServerStats(serverId);

  useEffect(() => {
    setActiveTab(urlTab);
  }, [urlTab]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target)) {
        setMoreMenuOpen(false);
      }
    }
    if (moreMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [moreMenuOpen]);

  const handleTabChange = useCallback((newTab) => {
    setActiveTab(newTab);
    setMoreMenuOpen(false);
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

  const preloadedInfo = useServerInfo(serverId);
  const { data: fetchedInfo } = useFetch(
    !preloadedInfo && serverId ? `${API}/servers/${serverId}/info` : null,
    [serverId]
  );
  const typeVersionData = preloadedInfo || fetchedInfo || null;
  const runtimeKind = (typeVersionData?.server_kind || server?.server_kind || '').toLowerCase();
  const isSteam = runtimeKind === 'steam';

  const overviewActive = activeTab === 'overview';
  const { data: playerData } = useFetch(
    overviewActive && server?.name ? `${API}/players/${server.name}/roster` : null,
    [server?.name, overviewActive]
  );
  const { data: backupData } = useFetch(
    overviewActive && server?.name ? `${API}/servers/${server.name}/backups` : null,
    [server?.name, overviewActive]
  );
  const { data: worldsData } = useFetch(
    overviewActive && server?.name ? `${API}/servers/${server.name}/worlds` : null,
    [server?.name, overviewActive]
  );
  const { data: schedulesData } = useFetch(
    overviewActive && server?.name ? `${API}/servers/${server.name}/schedules` : null,
    [server?.name, overviewActive]
  );

  // Build Primary Tabs + Categorized Secondary ("Tools & More") Tabs
  const { primaryTabs, secondaryGroups, allTabs } = useMemo(() => {
    const serverType = (typeVersionData?.server_type || server?.type || '').toLowerCase();
    const isModdedServer = ['fabric', 'forge', 'neoforge', 'quilt'].includes(serverType);
    const isPluginServer = ['paper', 'purpur', 'spigot', 'bukkit'].includes(serverType);
    const isHybridServer = ['mohist', 'magma', 'banner', 'catserver', 'spongeforge'].includes(serverType);

    if (isSteam) {
      const pTabs = [
        { id: 'overview', label: t('tabs.overview') || 'Overview', icon: FaServer },
        { id: 'console', label: t('tabs.console') || 'Console', icon: FaTerminal },
        { id: 'files', label: t('tabs.files') || 'Files', icon: FaFolder },
        { id: 'settings', label: 'Game Settings', icon: FaCog },
        { id: 'mods', label: 'Workshop / Mods', icon: FaCube },
      ];
      const sGroups = [
        {
          title: 'Automation & Backups',
          items: [
            { id: 'backup', label: 'Backups', icon: FaDownload, desc: 'Snapshots & restore points' },
            { id: 'schedule', label: 'Scheduled Tasks', icon: FaClock, desc: 'Automated restarts & jobs' },
          ],
        },
        {
          title: 'Monitoring & Access',
          items: [
            { id: 'graphs', label: 'Resource Graphs', icon: FaChartArea, desc: 'CPU, RAM & network history' },
            ...(access.canManage ? [{ id: 'permissions', label: 'Server Access', icon: FaUserShield, desc: 'Per-user server permissions' }] : []),
          ],
        },
      ];
      const flat = [...pTabs, ...sGroups.flatMap(g => g.items)];
      return { primaryTabs: pTabs, secondaryGroups: sGroups, allTabs: flat };
    }

    const pTabs = [
      { id: 'overview', label: t('tabs.overview') || 'Overview', icon: FaServer },
      { id: 'console', label: t('tabs.console') || 'Console', icon: FaTerminal },
      { id: 'players', label: 'Players', icon: FaUsers },
      { id: 'files', label: t('tabs.files') || 'Files', icon: FaFolder },
      { id: 'config', label: t('tabs.config') || 'Config', icon: FaCog },
    ];

    const contentItems = [];
    if (isModdedServer || isHybridServer) {
      contentItems.push(
        { id: 'mods', label: 'Installed Mods', icon: FaCube, desc: 'View & toggle server mods' },
        { id: 'mod-manager', label: 'Mod Browser', icon: FaPuzzlePiece, desc: 'Install from Modrinth / CurseForge' },
        { id: 'client-mod-filter', label: 'Client Mod Filter', icon: FaShieldAlt, desc: 'Auto-filter client-only mods' },
      );
    } else {
      // Allow Client Mod Filter & Mod Manager on any Minecraft server (e.g. modpack imports)
      contentItems.push(
        { id: 'mods', label: 'Mods', icon: FaCube, desc: 'Manage server mods folder' },
        { id: 'client-mod-filter', label: 'Client Mod Filter', icon: FaShieldAlt, desc: 'Scan & remove client-only mods' },
      );
    }

    if (isPluginServer || isHybridServer) {
      contentItems.push(
        { id: 'plugins', label: 'Plugins', icon: FaPlug, desc: 'Manage Bukkit/Paper plugins' },
      );
    }

    const sGroups = [
      {
        title: 'World & Automation',
        items: [
          { id: 'worlds', label: 'Worlds', icon: FaHdd, desc: 'Manage worlds, seeds & uploads' },
          { id: 'backup', label: 'Backups', icon: FaDownload, desc: 'Create & restore backups' },
          { id: 'schedule', label: 'Scheduled Tasks', icon: FaCalendarAlt, desc: 'Cron jobs & auto-restarts' },
        ],
      },
      {
        title: 'Mods & Extensions',
        items: contentItems,
      },
      {
        title: 'Analytics & Security',
        items: [
          { id: 'graphs', label: 'Resource Graphs', icon: FaChartArea, desc: 'Live & historical metrics' },
          ...(access.canManage ? [{ id: 'permissions', label: 'Server Access', icon: FaUserShield, desc: 'Grant user roles on this server' }] : []),
        ],
      },
    ].filter(g => g.items.length > 0);

    const flat = [...pTabs, ...sGroups.flatMap(g => g.items)];
    return { primaryTabs: pTabs, secondaryGroups: sGroups, allTabs: flat };
  }, [isSteam, t, typeVersionData, server, access.canManage]);

  const activeSecondaryTab = useMemo(() => {
    const isPrimary = primaryTabs.some(pt => pt.id === activeTab);
    if (isPrimary) return null;
    return allTabs.find(tItem => tItem.id === activeTab) || null;
  }, [primaryTabs, allTabs, activeTab]);

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

      if (actions.__refreshServers) {
        actions.__refreshServers();
      }

      if (actions.__updateServerStatus) {
        const statusMap = { start: 'running', stop: 'stopped', restart: 'running' };
        if (statusMap[action]) {
          actions.__updateServerStatus(serverId, statusMap[action]);
        }
      }
      setLogReset(x => x + 1);
    } catch (err) {
      alert(`Failed to ${action} server: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  }, [serverId, actionLoading, actions]);

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
      if (actions.__refreshServers) {
        actions.__refreshServers();
      }
      navigate('/servers');
    } catch (err) {
      alert(`Failed to delete server: ${err.message}`);
    } finally {
      setActionLoading(null);
      setShowDeleteModal(false);
    }
  }, [serverId, actions, navigate]);

  const handleEditStart = useCallback((filePath, content) => {
    setEditPath(filePath);
    setEditContent(content);
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

  if (!access.loading && !access.canView) {
    return (
      <div className="p-6">
        <button
          onClick={() => navigate('/servers')}
          className="flex items-center gap-2 text-white/70 hover:text-white mb-4"
        >
          <FaArrowLeft /> {t('servers.backToServers')}
        </button>
        <div className="text-white/60">You don&apos;t have access to this server. Ask an admin to grant it in Server Access Control.</div>
      </div>
    );
  }

  const isRunning = server.status === 'running';
  const rawType = typeVersionData?.server_type || server.type;
  const displayType = isSteam
    ? `Steam · ${prettify(typeVersionData?.steam_game || server?.steam_game || server?.type || 'Dedicated')}`
    : (rawType && rawType.toLowerCase() !== 'unknown' ? prettify(rawType) : 'Minecraft');
  const rawVersion = typeVersionData?.server_version || server.version;
  const displayVersion = rawVersion && rawVersion.toLowerCase() !== 'unknown' ? rawVersion : 'Dedicated Server';

  return (
    <div className="min-h-screen">
      {/* Header */}
      <div className="border-b border-white/10 bg-ink/80 backdrop-blur relative z-30">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 pt-4">
          <button
            onClick={() => navigate('/servers')}
            className="flex items-center gap-2 text-white/60 hover:text-white text-sm mb-3 transition-colors"
          >
            <FaArrowLeft className="text-xs" /> {t('servers.backToServers')}
          </button>

          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-500 to-indigo-600 ring-4 ring-brand-500/20 flex items-center justify-center text-xl text-white flex-shrink-0 shadow-lg">
                <FaServer />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <h1 className="text-xl sm:text-2xl font-bold text-white truncate">{server.name}</h1>
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    isRunning
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                    {server.status}
                  </span>
                </div>
                <div className="flex items-center gap-2.5 text-xs sm:text-sm text-white/60 mt-1 flex-wrap">
                  <span>{displayType}</span>
                  <span>•</span>
                  <span>{displayVersion}</span>
                  {stats && !stats.error && isRunning && (
                    <>
                      <span className="hidden sm:inline">•</span>
                      <span className="text-white/75 font-mono text-xs">
                        CPU {Math.min(Math.round(stats.cpu_percent), 100)}%
                      </span>
                      <span className="text-white/75 font-mono text-xs">
                        RAM {Math.round(stats.memory_usage_mb)}/{Math.round(stats.memory_limit_mb)} MB
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 flex-wrap">
              {access.canOperate && (isRunning ? (
                <>
                  <button
                    onClick={() => handleAction('restart')}
                    disabled={!!actionLoading}
                    className="px-3.5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors"
                  >
                    <FaSync className={actionLoading === 'restart' ? 'animate-spin' : ''} />
                    <span>{t('servers.restart')}</span>
                  </button>
                  <button
                    onClick={() => handleAction('stop')}
                    disabled={!!actionLoading}
                    className="px-3.5 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors"
                  >
                    <FaStop />
                    <span>{t('servers.stop')}</span>
                  </button>
                </>
              ) : (
                <button
                  onClick={() => handleAction('start')}
                  disabled={!!actionLoading}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors"
                >
                  <FaPlay />
                  <span>{t('servers.start')}</span>
                </button>
              ))}
              {access.canManage && (
                <button
                  onClick={() => setShowSettingsModal(true)}
                  className="px-3 py-2 text-white/75 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition-colors flex items-center gap-2 text-sm"
                  title="Hardware & Runtime Allocation (RAM / CPU)"
                >
                  <FaSlidersH className="text-sm text-brand-400" />
                  <span className="hidden lg:inline">Resources</span>
                </button>
              )}
              {access.canManage && (
                <button
                  onClick={() => setShowDeleteModal(true)}
                  disabled={!!actionLoading}
                  className="p-2.5 bg-red-600/20 hover:bg-red-600 text-red-300 hover:text-white border border-red-500/30 rounded-lg flex items-center justify-center disabled:opacity-50 transition-colors"
                  title={t('servers.deleteServer')}
                >
                  <FaTrash className="text-sm" />
                </button>
              )}
            </div>
          </div>

          {/* Responsive Navigation Bar: Core Tabs + "Tools & More" Dropdown */}
          <div className="flex items-center justify-between gap-2 mt-5">
            <div className="flex items-center gap-1 overflow-x-auto no-scrollbar select-none">
              {primaryTabs.map(tab => {
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => handleTabChange(tab.id)}
                    className={`flex items-center gap-2 px-3.5 sm:px-4 py-2.5 rounded-t-xl text-xs sm:text-sm font-medium transition-all whitespace-nowrap border-b-2 ${
                      isActive
                        ? 'bg-white/10 text-white border-brand-500'
                        : 'border-transparent text-white/60 hover:text-white hover:bg-white/5'
                    }`}
                  >
                    <tab.icon className={`text-xs ${isActive ? 'text-brand-400' : ''}`} />
                    <span>{tab.label}</span>
                  </button>
                );
              })}

              {/* Tools & More Dropdown Trigger */}
              {secondaryGroups.length > 0 && (
                <div className="relative" ref={moreMenuRef}>
                  <button
                    type="button"
                    onClick={() => setMoreMenuOpen(v => !v)}
                    className={`flex items-center gap-2 px-3.5 sm:px-4 py-2.5 rounded-t-xl text-xs sm:text-sm font-medium transition-all whitespace-nowrap border-b-2 ${
                      activeSecondaryTab
                        ? 'bg-brand-500/20 text-white border-brand-500'
                        : moreMenuOpen
                          ? 'bg-white/10 text-white border-white/30'
                          : 'border-transparent text-white/65 hover:text-white hover:bg-white/5'
                    }`}
                  >
                    {activeSecondaryTab ? (
                      <>
                        <activeSecondaryTab.icon className="text-xs text-brand-400" />
                        <span>{activeSecondaryTab.label}</span>
                      </>
                    ) : (
                      <>
                        <FaPuzzlePiece className="text-xs text-brand-400" />
                        <span>Tools & More</span>
                      </>
                    )}
                    <FaChevronDown className={`text-[10px] transition-transform duration-200 ${moreMenuOpen ? 'rotate-180' : ''}`} />
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Categorized Tools Dropdown / Drawer Panel */}
          {moreMenuOpen && secondaryGroups.length > 0 && (
            <div
              ref={moreMenuRef}
              className="mt-1 mb-3 p-4 rounded-2xl bg-[#141827]/95 border border-white/15 shadow-2xl backdrop-blur-xl animate-fade-in"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {secondaryGroups.map(group => (
                  <div key={group.title} className="space-y-1.5">
                    <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                      {group.title}
                    </div>
                    {group.items.map(item => {
                      const active = activeTab === item.id;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => handleTabChange(item.id)}
                          className={`w-full flex items-start gap-3 p-2.5 rounded-xl text-left transition-all ${
                            active
                              ? 'bg-brand-500/20 border border-brand-500/40 text-white'
                              : 'hover:bg-white/5 text-white/75 hover:text-white border border-transparent'
                          }`}
                        >
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
                            active ? 'bg-brand-500 text-white' : 'bg-white/10 text-brand-400'
                          }`}>
                            <item.icon className="text-xs" />
                          </div>
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">{item.label}</div>
                            {item.desc && (
                              <div className="text-[11px] text-white/45 truncate">{item.desc}</div>
                            )}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Tab Content */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
        {activeTab === 'overview' && (() => {
          const backups = Array.isArray(backupData) ? backupData : backupData?.backups || [];
          const worlds = Array.isArray(worldsData) ? worldsData : worldsData?.worlds || [];
          const tasks = Array.isArray(schedulesData) ? schedulesData : schedulesData?.tasks || [];
          const toName = (p) => (typeof p === 'string' ? p : (p && p.name) || '');
          const isUuidish = (n) => /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(n)
            || (/^[0-9a-fA-F-]{4,36}$/.test(n) && n.includes('-'));
          const rawOnline = Array.isArray(playerData?.online) ? playerData.online : (Array.isArray(playerData?.players) ? playerData.players : []);
          const onlinePlayers = rawOnline.map(toName).filter(name => name && name.toLowerCase() !== 'client' && name.trim() !== '' && !isUuidish(name.trim()));
          const onlineCount = typeof playerData?.count === 'number' ? playerData.count : onlinePlayers.length;
          const maxPlayers = playerData?.max || 0;
          const connectPort = server.host_port || typeVersionData?.host_port;
          const connectHost = typeVersionData?.lan_ip || server?.lan_ip || 'localhost';
          const connectAddr = `${connectHost}:${connectPort}`;
          const steamPorts = typeVersionData?.steam_ports || server?.steam_ports || [];
          const gamePortInfo = typeVersionData?.game_port || server?.game_port;
          const portSummary = typeVersionData?.port_summary || server?.port_summary || [];

          const quickTools = secondaryGroups.flatMap(g => g.items);

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
                      <p className="text-white font-mono text-lg mt-0.5">{connectAddr}</p>
                      {isSteam && portSummary.length > 1 && (
                        <p className="text-white/40 text-xs mt-1 font-mono">
                          All ports: {portSummary.join(', ')}
                        </p>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(connectAddr);
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

              {/* Quick Tools Strip — Mobile-friendly 1-click access to all tools */}
              {quickTools.length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
                  {quickTools.slice(0, 6).map(tool => (
                    <button
                      key={tool.id}
                      type="button"
                      onClick={() => handleTabChange(tool.id)}
                      className="glassmorphism hover:bg-white/10 border border-white/10 hover:border-brand-500/40 rounded-xl p-3 flex items-center gap-2.5 text-left transition-all group"
                    >
                      <div className="w-8 h-8 rounded-lg bg-brand-500/15 group-hover:bg-brand-500 text-brand-400 group-hover:text-white flex items-center justify-center flex-shrink-0 transition-colors">
                        <tool.icon className="text-xs" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs font-semibold text-white truncate">{tool.label}</div>
                        <div className="text-[10px] text-white/40 truncate">{tool.desc || 'Open tool'}</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}

              {/* Live Read-Only Console Preview */}
              <LiveConsolePreview
                serverId={server.id}
                isRunning={isRunning}
                resetToken={logReset}
                onOpenConsole={() => handleTabChange('console')}
              />

              {/* Server Info + Resources */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Server Info */}
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
                    {!isSteam && typeVersionData?.java_version && String(typeVersionData.java_version).toLowerCase() !== 'unknown' && (
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

                {/* Resources */}
                <div className="glassmorphism rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider flex items-center gap-2">
                      <FaMicrochip className="text-purple-400" />
                      {t('servers.resources')}
                    </h3>
                    {access.canManage && (
                      <button
                        type="button"
                        onClick={() => setShowSettingsModal(true)}
                        className="text-xs text-brand-400 hover:text-brand-300 transition-colors"
                      >
                        Adjust limits →
                      </button>
                    )}
                  </div>
                  {stats && !stats.error && isRunning ? (
                    <div className="space-y-4 text-sm">
                      <div>
                        <div className="flex justify-between items-center mb-1.5">
                          <span className="text-white/50">{t('servers.cpuUsage')}</span>
                          <span className={`font-medium ${
                            stats.cpu_percent > 80 ? 'text-red-400' : stats.cpu_percent > 50 ? 'text-yellow-400' : 'text-green-400'
                          }`}>
                            {Math.min(Math.round(stats.cpu_percent), 100)}%
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
                      {(stats.network_rx_mb !== undefined || stats.network_tx_mb !== undefined) && (
                        <div className="flex justify-between items-center pt-1">
                          <span className="text-white/50 flex items-center gap-1.5">
                            <FaNetworkWired className="text-xs" /> Network
                          </span>
                          <span className="text-white font-sans font-medium text-xs tabular-nums">
                            ↓ {(stats.network_rx_mb || 0).toFixed(1)} MB &nbsp; ↑ {(stats.network_tx_mb || 0).toFixed(1)} MB
                          </span>
                        </div>
                      )}
                      {stats.uptime_seconds > 0 && (
                        <div className="flex justify-between items-center">
                          <span className="text-white/50">{t('servers.uptime')}</span>
                          <span className="text-white font-medium">{formatUptime(stats.uptime_seconds)}</span>
                        </div>
                      )}
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
                          <span className="text-white/60 text-xs font-sans tabular-nums">{formatBytes(world.size)}</span>
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
                          <div className="flex items-center gap-3 text-xs text-white/40 tabular-nums">
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
            </div>
          );
        })()}

        {activeTab === 'console' && (
          <div className="h-[600px]">
            <TerminalPanel
              serverId={server.id}
              resetToken={logReset}
              canSend={access.canOperate}
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
            onNavigateToBackup={() => handleTabChange('backup')}
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
          <ConfigPanel server={server} />
        )}

        {activeTab === 'players' && (
          <PlayersPanel serverName={server.name} serverId={server.id} />
        )}

        {activeTab === 'worlds' && (
          <WorldsPanel serverName={server.name} serverId={server.id} />
        )}

        {activeTab === 'backup' && (
          <BackupsPanel serverName={server.name} serverId={server.id} />
        )}

        {activeTab === 'schedule' && (
          <SchedulePanel serverName={server.name} serverId={server.id} />
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
              gameSlug={typeVersionData?.steam_game || server?.steam_game || server?.type || ''}
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
          <ModManagerPanel serverName={server.name} />
        )}

        {activeTab === 'client-mod-filter' && (
          <ClientModFilterPanel serverName={server.name} />
        )}

        {activeTab === 'graphs' && (
          <ResourceGraphs serverId={server.id} />
        )}

        {activeTab === 'permissions' && (
          access.canManage ? (
            <ServerPermissionsPanel serverName={server.name} />
          ) : (
            <div className="text-center py-8 text-white/30">
              <p className="text-sm">Managing server access requires the Manage permission.</p>
            </div>
          )
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

      {/* Hardware & Runtime Allocation Modal */}
      <ConfirmModal
        isOpen={showSettingsModal}
        title="Hardware & Runtime Allocation"
        message={<SettingsModalContent server={server} serverId={serverId} typeVersionData={typeVersionData} isSteam={isSteam} />}
        confirmText={t('common.close') || 'Close'}
        cancelText={null}
        onConfirm={() => setShowSettingsModal(false)}
        onCancel={() => setShowSettingsModal(false)}
        confirmVariant="primary"
        size="xl"
      />
    </div>
  );
}
