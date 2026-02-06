import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useGlobalData } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import { normalizeRamInput } from '../utils/ram';
import {
  FaChevronRight,
  FaPlay,
  FaStop,
  FaServer,
  FaDownload,
  FaExclamationTriangle,
  FaClock,
  FaShieldAlt,
  FaInfoCircle,
  FaCheck,
} from 'react-icons/fa';


export default function DashboardPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const globalData = useGlobalData();

  const {
    servers,
    serverStats,
    dashboardData,
    systemHealth,
    alerts,
    featuredModpacks,
    isInitialized
  } = globalData;


  const [localFeatured, setLocalFeatured] = useState([]);
  const [featuredError, setFeaturedError] = useState('');
  const featured = featuredModpacks?.length > 0 ? featuredModpacks : localFeatured;


  const [installOpen, setInstallOpen] = useState(false);
  const [installPack, setInstallPack] = useState(null);
  const [installProvider, setInstallProvider] = useState('modrinth');
  const [installVersions, setInstallVersions] = useState([]);
  const [installVersionId, setInstallVersionId] = useState('');
  const [installEvents, setInstallEvents] = useState([]);
  const [installWorking, setInstallWorking] = useState(false);
  const [serverName, setServerName] = useState('mp-' + Math.random().toString(36).slice(2, 6));
  const [hostPort, setHostPort] = useState('');
  const [minRam, setMinRam] = useState('2048M');
  const [maxRam, setMaxRam] = useState('4096M');


  // --- Activity Feed ---
  const [activityFeed, setActivityFeed] = useState([]);
  const [activityLoading, setActivityLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setActivityLoading(true);
      try {
        const r = await fetch(`${API}/realtime/notifications?limit=8`, { headers: authHeaders() });
        if (r.ok && !cancelled) {
          const d = await r.json();
          setActivityFeed(d.notifications || []);
        }
      } catch { }
      if (!cancelled) setActivityLoading(false);
    })();
    // Re-fetch every 30s
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API}/realtime/notifications?limit=8`, { headers: authHeaders() });
        if (r.ok && !cancelled) {
          const d = await r.json();
          setActivityFeed(d.notifications || []);
        }
      } catch { }
    }, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // --- Quick Actions ---
  const [actionLoading, setActionLoading] = useState({});

  const quickPower = useCallback(async (serverId, action, e) => {
    e.stopPropagation();
    setActionLoading(prev => ({ ...prev, [serverId]: action }));
    try {
      await fetch(`${API}/servers/${serverId}/power`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ signal: action }),
      });
    } catch { }
    // Give Docker a moment then refresh
    setTimeout(() => {
      if (globalData?.__refreshServers) globalData.__refreshServers();
      setActionLoading(prev => ({ ...prev, [serverId]: null }));
    }, 1500);
  }, [globalData]);

  useEffect(() => {
    if (featuredModpacks?.length > 0) return;
    let cancelled = false;
    // Fetch immediately - no delay
    (async () => {
      try {
        const r = await fetch(`${API}/catalog/search?provider=all&page_size=6`, { headers: authHeaders() });
        const d = await r.json();
        if (!cancelled) setLocalFeatured(Array.isArray(d?.results) ? d.results : []);
      } catch (e) { if (!cancelled) setFeaturedError(String(e.message || e)); }
    })();
    return () => { cancelled = true; };
  }, [featuredModpacks]);

  async function openInstallFromFeatured(pack) {
    setInstallPack(pack);
    setInstallOpen(true);
    setInstallEvents([]);
    setInstallWorking(false);
    try {
      const srcProvider = pack.provider || 'modrinth';
      setInstallProvider(srcProvider);
      const packId = encodeURIComponent(pack.id || pack.slug || '');
      const r = await fetch(`${API}/catalog/${srcProvider}/packs/${packId}/versions`, { headers: authHeaders() });
      const d = await r.json().catch(() => ({}));
      const vers = Array.isArray(d?.versions) ? d.versions : [];
      setInstallVersions(vers);
      setInstallVersionId(vers[0]?.id || '');
    } catch {
      setInstallVersions([]);
      setInstallVersionId('');
    }
  }

  async function submitInstall() {
    if (!installPack) return;
    if (!serverName || !String(serverName).trim()) {
      setInstallEvents((prev) => [...prev, { type: 'error', message: 'Server name is required' }]);
      return;
    }
    const normMin = normalizeRamInput(minRam);
    const normMax = normalizeRamInput(maxRam);
    if (!normMin || !normMax) {
      setInstallEvents((prev) => [...prev, { type: 'error', message: 'Please enter valid RAM values (examples: 2048M, 2G, or raw MB like 2048).' }]);
      return;
    }
    setInstallWorking(true);
    setInstallEvents([{ type: 'progress', message: 'Submitting install task...' }]);
    try {
      const body = {
        provider: installProvider,
        pack_id: String(installPack.id || installPack.slug || ''),
        version_id: installVersionId ? String(installVersionId) : null,
        name: String(serverName).trim(),
        host_port: hostPort ? Number(hostPort) : null,
        min_ram: normMin,
        max_ram: normMax,
      };
      const r = await fetch(`${API}/modpacks/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body)
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const taskId = d?.task_id;
      if (!taskId) throw new Error('No task id');
      const es = new EventSource(`${API}/modpacks/install/events/${taskId}`);
      es.onmessage = (ev) => {
        try {
          const evd = JSON.parse(ev.data);
          setInstallEvents((prev) => {
            const next = [...prev, evd];
            return next.length > 500 ? next.slice(-500) : next;
          });
          if (evd.type === 'done' || evd.type === 'error') {
            try { es.close(); } catch { }
            setInstallWorking(false);
            // Refresh immediately - no delays
            if (globalData.__refreshServers) {
              globalData.__refreshServers();
            }
          }
        } catch { }
      };
      es.onerror = () => { try { es.close(); } catch { } setInstallWorking(false); };
    } catch (e) {
      setInstallEvents((prev) => [...prev, { type: 'error', message: String(e.message || e) }]);
      setInstallWorking(false);
    }
  }


  const { totalServers, runningServers, totalMemoryMB, avgCpuPercent, criticalAlerts, warningAlerts } = useMemo(() => {
    const total = servers?.length || 0;
    const runningList = Array.isArray(servers) ? servers.filter(s => s?.status === 'running') : [];
    const running = runningList.length || 0;

    const health = (systemHealth && typeof systemHealth === 'object')
      ? systemHealth
      : (dashboardData && typeof dashboardData === 'object' ? dashboardData.health : null);

    let cpuPercent = 0;
    let memoryMB = 0;

    if (health && typeof health.cpu_usage_percent === 'number') {
      cpuPercent = health.cpu_usage_percent;
    }
    if (health && typeof health.used_memory_gb === 'number') {
      memoryMB = health.used_memory_gb * 1024;
    }

    if ((!cpuPercent || !memoryMB) && serverStats && typeof serverStats === 'object') {
      let cpuSum = 0;
      let cpuCount = 0;
      let memSumMB = 0;
      runningList.forEach((s) => {
        const id = s?.id;
        if (!id) return;
        const st = serverStats[id];
        if (st && typeof st.cpu_percent === 'number') {
          cpuSum += st.cpu_percent;
          cpuCount += 1;
        }
        if (st && typeof st.memory_usage_mb === 'number') {
          memSumMB += st.memory_usage_mb;
        }
      });
      if (!cpuPercent && cpuCount > 0) {
        cpuPercent = cpuSum / cpuCount;
      }
      if (!memoryMB && memSumMB > 0) {
        memoryMB = memSumMB;
      }
    }

    if (!Number.isFinite(cpuPercent)) cpuPercent = 0;
    if (!Number.isFinite(memoryMB)) memoryMB = 0;
    const critical = alerts?.filter(a => a.type === 'critical' && !a.acknowledged).length || 0;
    const warning = alerts?.filter(a => a.type === 'warning' && !a.acknowledged).length || 0;

    return {
      totalServers: total,
      runningServers: running,
      totalMemoryMB: memoryMB,
      avgCpuPercent: cpuPercent,
      criticalAlerts: critical,
      warningAlerts: warning
    };
  }, [servers, serverStats, dashboardData, systemHealth, alerts]);

  return (
    <div className="min-h-screen bg-transparent">
      {/* Clean Linear-inspired header */}
      <div className="border-b border-white/10 bg-ink/80 backdrop-blur supports-[backdrop-filter]:bg-ink/60">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold gradient-text-brand mb-1">{t('dashboard.overview')}</h1>
              <p className="text-sm text-white/60">{t('dashboard.monitorInfrastructure')}</p>
            </div>

            {(criticalAlerts > 0 || warningAlerts > 0) && (
              <div className="flex items-center gap-2">
                {criticalAlerts > 0 && (
                  <div className="flex items-center gap-1 px-2 py-1 bg-red-900/20 text-red-300 rounded text-sm">
                    <div className="w-2 h-2 bg-red-400 rounded-full" />
                    {criticalAlerts}
                  </div>
                )}
                {warningAlerts > 0 && (
                  <div className="flex items-center gap-1 px-2 py-1 bg-yellow-900/20 text-yellow-300 rounded text-sm">
                    <div className="w-2 h-2 bg-yellow-400 rounded-full" />
                    {warningAlerts}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8 animate-fade-in">

        {/* Simplified Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 sm:gap-6">
          <div className="glassmorphism rounded-xl p-4 sm:p-5">
            <div className="text-sm text-white/60 mb-1">{t('dashboard.totalServers')}</div>
            <div className="flex items-baseline gap-2">
              <div className="text-xl sm:text-2xl font-medium text-white">
                {runningServers}
              </div>
              <div className="text-sm text-white/40">/ {totalServers}</div>
            </div>
          </div>

          <div className="glassmorphism rounded-xl p-4 sm:p-5">
            <div className="text-sm text-white/60 mb-1">{t('dashboard.cpuUsage')}</div>
            <div className="text-xl sm:text-2xl font-medium text-white">
              {`${avgCpuPercent.toFixed(0)}%`}
            </div>
          </div>

          <div className="glassmorphism rounded-xl p-4 sm:p-5">
            <div className="text-sm text-white/60 mb-1">{t('dashboard.memoryUsage')}</div>
            <div className="text-xl sm:text-2xl font-medium text-white">
              {`${(totalMemoryMB / 1024).toFixed(1)}GB`}
            </div>
          </div>

          <div className="glassmorphism rounded-xl p-4 sm:p-5">
            <div className="text-sm text-white/60 mb-1">{t('dashboard.issues')}</div>
            <div className="text-xl sm:text-2xl font-medium text-white">
              {criticalAlerts + warningAlerts}
            </div>
          </div>
        </div>

        {/* Featured Modpacks - instant load */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium text-white">{t('dashboard.featuredModpacks')}</h2>
            {featuredError && <div className="text-sm text-red-400">{featuredError}</div>}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-3 gap-4">
            {featured.length > 0 ? (
              featured.map((p, idx) => (
                <div key={p.id || p.slug || idx} className="glassmorphism rounded-xl p-4 hover:bg-white/10 transition-colors">
                  <div className="flex items-center gap-3 mb-2">
                    {p.icon_url ? <img src={p.icon_url} alt="" className="w-8 h-8 rounded" loading="lazy" /> : <div className="w-8 h-8 bg-white/10 rounded" />}
                    <div className="min-w-0 flex-1">
                      <div className="text-white font-medium truncate" title={p.name}>{p.name}</div>
                      <div className="text-xs text-white/60">{p.provider || 'Modrinth'} • {typeof p.downloads === 'number' ? `⬇ ${Intl.NumberFormat().format(p.downloads)}` : ''}</div>
                    </div>
                  </div>
                  <div className="text-sm text-white/60 line-clamp-2 min-h-[38px]">{p.description}</div>
                  <div className="mt-3">
                    <button onClick={() => openInstallFromFeatured(p)} className="text-sm text-brand-400 hover:text-brand-300">Install</button>
                  </div>
                </div>
              ))
            ) : !featuredError ? (
              <div className="text-white/40 text-sm">Loading modpacks...</div>
            ) : (
              <div className="text-white/60">No featured packs available.</div>
            )}
          </div>
        </div>

        {/* Install Wizard Modal */}
        {installOpen && (
          <div className="fixed inset-0 bg-black/60 flex items-start sm:items-center justify-center z-50 p-4">
            <div className="bg-ink border border-white/10 rounded-lg p-4 sm:p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <div className="text-lg font-semibold text-white">{t('modpackInstall.title')}{installPack?.name ? `: ${installPack.name}` : ''}</div>
                <button onClick={() => { setInstallOpen(false); setInstallPack(null); }} className="text-white/60 hover:text-white">Close</button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                <div>
                  <label className="block text-xs text-white/60 mb-1">Version</label>
                  <select className="w-full rounded bg-white/10 border border-white/20 px-3 py-2 text-white" value={installVersionId} onChange={e => setInstallVersionId(e.target.value)} style={{ backgroundColor: '#1f2937' }}>
                    {installVersions.map(v => <option key={v.id} value={v.id} style={{ backgroundColor: '#1f2937' }}>{v.name || v.version_number}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-white/60 mb-1">{t('modpackInstall.serverName')}</label>
                  <input className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white" value={serverName} onChange={e => setServerName(e.target.value)} />
                </div>
                <div>
                  <label className="block text-xs text-white/60 mb-1">{t('modpackInstall.hostPort')}</label>
                  <input className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white" value={hostPort} onChange={e => setHostPort(e.target.value)} placeholder="25565" />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-white/60 mb-1">{t('modpackInstall.minRam')}</label>
                    <input className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white" value={minRam} onChange={e => setMinRam(e.target.value)} onBlur={() => { const v = normalizeRamInput(minRam); if (v) setMinRam(v); }} />
                    <div className="text-[11px] text-white/50 mt-1">Accepts 2048M, 2G, or raw MB.</div>
                  </div>
                  <div>
                    <label className="block text-xs text-white/60 mb-1">{t('modpackInstall.maxRam')}</label>
                    <input className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white" value={maxRam} onChange={e => setMaxRam(e.target.value)} onBlur={() => { const v = normalizeRamInput(maxRam); if (v) setMaxRam(v); }} />
                    <div className="text-[11px] text-white/50 mt-1">Accepts 4096M, 4G, or raw MB.</div>
                  </div>
                </div>
                <div className="md:col-span-2 flex items-center gap-2 mt-2">
                  <button disabled={installWorking} onClick={submitInstall} className="bg-brand-500 hover:bg-brand-600 disabled:opacity-50 px-4 py-2 rounded text-white">{installWorking ? 'Installing…' : 'Start Install'}</button>
                  <div className="text-sm text-white/70">{installProvider}</div>
                </div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded p-3 h-40 overflow-auto text-sm">
                {installEvents.length === 0 ? (
                  <div className="text-white/50">No events yet…</div>
                ) : (
                  <ul className="space-y-1">
                    {installEvents.map((ev, i) => {
                      let text = '';
                      if (typeof ev?.message === 'string') {
                        text = ev.message;
                      } else if (ev?.message) {
                        try { text = JSON.stringify(ev.message); } catch { text = String(ev.message); }
                      } else if (ev?.step) {
                        const pct = typeof ev.progress === 'number' ? ` (${ev.progress}%)` : '';
                        text = `${ev.step}${pct}`;
                      } else {
                        try { text = JSON.stringify(ev); } catch { text = String(ev); }
                      }
                      return (
                        <li key={i} className="flex items-start gap-2 text-white/80">
                          <span className="w-2 h-2 rounded-full mt-2 flex-shrink-0" style={{ background: ev.type === 'error' ? '#f87171' : ev.type === 'done' ? '#34d399' : '#a78bfa' }}></span>
                          <span>{text}</span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Two-column: Servers + Activity Feed */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Server List — 2/3 width */}
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-medium text-white">Servers</h2>
              <button
                onClick={() => navigate('/servers')}
                className="text-sm text-white/60 hover:text-white transition-colors"
              >
                View all
              </button>
            </div>

            <div className="glassmorphism rounded-xl divide-y divide-white/10">
              {servers.length > 0 ? (
                servers.slice(0, 6).map((server) => {
                  const isRunning = server.status === 'running';
                  const loading = actionLoading[server.id];

                  return (
                    <div
                      key={server.id}
                      className="flex flex-col sm:flex-row sm:items-center items-start justify-between p-4 gap-3 hover:bg-white/5 cursor-pointer transition-colors"
                      onClick={() => navigate(`/servers/${server.id}`)}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isRunning ? 'bg-green-400' : 'bg-gray-500'}`} />
                        <div>
                          <div className="text-white font-medium">{server.name}</div>
                          <div className="text-sm text-white/60">
                            {server.version} • {server.type || 'vanilla'}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {isRunning ? (
                          <button
                            onClick={(e) => quickPower(server.id, 'stop', e)}
                            disabled={!!loading}
                            className="p-1.5 rounded-lg bg-red-500/15 text-red-300 hover:bg-red-500/25 border border-red-500/20 transition-colors disabled:opacity-50"
                            title="Stop server"
                          >
                            {loading === 'stop' ? <span className="w-3 h-3 border-2 border-red-300/40 border-t-red-300 rounded-full animate-spin block" /> : <FaStop className="text-xs" />}
                          </button>
                        ) : (
                          <button
                            onClick={(e) => quickPower(server.id, 'start', e)}
                            disabled={!!loading}
                            className="p-1.5 rounded-lg bg-green-500/15 text-green-300 hover:bg-green-500/25 border border-green-500/20 transition-colors disabled:opacity-50"
                            title="Start server"
                          >
                            {loading === 'start' ? <span className="w-3 h-3 border-2 border-green-300/40 border-t-green-300 rounded-full animate-spin block" /> : <FaPlay className="text-xs" />}
                          </button>
                        )}
                        <span className={`text-xs px-2 py-1 rounded ${isRunning
                            ? 'bg-green-500/15 text-green-200 border border-green-500/30'
                            : 'bg-white/5 text-white/60 border border-white/10'
                          }`}>
                          {isRunning ? 'Running' : 'Stopped'}
                        </span>
                        <FaChevronRight className="w-3 h-3 text-white/40" />
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="p-8 text-center">
                  <div className="text-white/60 mb-2">No servers yet</div>
                  <button
                    onClick={() => navigate('/templates')}
                    className="text-sm text-brand-400 hover:text-brand-300"
                  >
                    Create your first server
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Activity Feed — 1/3 width */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-medium text-white">Recent Activity</h2>
            </div>

            <div className="glassmorphism rounded-xl p-4">
              {activityFeed.length > 0 ? (
                <div className="space-y-3">
                  {activityFeed.map((item) => {
                    const typeIcons = {
                      server_start: { icon: FaPlay, color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
                      server_stop: { icon: FaStop, color: 'text-red-400', bg: 'bg-red-500/15' },
                      server_crash: { icon: FaExclamationTriangle, color: 'text-orange-400', bg: 'bg-orange-500/15' },
                      backup: { icon: FaDownload, color: 'text-blue-400', bg: 'bg-blue-500/15' },
                      scheduled: { icon: FaClock, color: 'text-purple-400', bg: 'bg-purple-500/15' },
                      security: { icon: FaShieldAlt, color: 'text-yellow-400', bg: 'bg-yellow-500/15' },
                    };
                    const cfg = typeIcons[item.type] || { icon: FaInfoCircle, color: 'text-blue-400', bg: 'bg-blue-500/15' };
                    const Icon = cfg.icon;
                    const ago = (() => {
                      if (!item.created_at) return '';
                      const s = Math.floor((Date.now() - new Date(item.created_at)) / 1000);
                      if (s < 60) return 'just now';
                      const m = Math.floor(s / 60);
                      if (m < 60) return `${m}m ago`;
                      const h = Math.floor(m / 60);
                      if (h < 24) return `${h}h ago`;
                      return `${Math.floor(h / 24)}d ago`;
                    })();

                    return (
                      <div key={item.id} className="flex items-start gap-3">
                        <div className={`mt-0.5 p-1.5 rounded-lg ${cfg.bg} flex-shrink-0`}>
                          <Icon className={`text-[10px] ${cfg.color}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-white/80 truncate">{item.title}</div>
                          <div className="text-[11px] text-white/40">{ago}</div>
                        </div>
                        {!item.is_read && <span className="w-1.5 h-1.5 rounded-full bg-brand-500 mt-2 flex-shrink-0" />}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-8">
                  <FaClock className="text-2xl text-white/20 mx-auto mb-2" />
                  <div className="text-sm text-white/40">No recent activity</div>
                  <div className="text-xs text-white/30 mt-1">Server events will appear here</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Alerts */}
        <div className="space-y-6">

          {/* Clean Alerts */}
          {alerts.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-medium text-white">{t('modpackInstall.recentIssues')}</h2>
              </div>

              <div className="glassmorphism rounded-xl divide-y divide-white/10">
                {alerts.slice(0, 3).map((alert, index) => {
                  const isError = alert.type === 'critical' || alert.type === 'error';

                  return (
                    <div key={alert.id || index} className="p-4">
                      <div className="flex items-start gap-3">
                        <div className={`w-2 h-2 rounded-full mt-2 ${isError ? 'bg-red-400' : 'bg-yellow-400'
                          }`} />
                        <div className="flex-1 min-w-0">
                          <div className="text-white text-sm">{alert.message}</div>
                          <div className="text-xs text-white/50 mt-1">
                            {new Date(alert.timestamp).toLocaleString()}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
