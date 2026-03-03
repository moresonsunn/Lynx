import React, { useState, useEffect } from 'react';
import { FaServer, FaCircle, FaClock, FaGamepad, FaSyncAlt, FaGlobe } from 'react-icons/fa';

// Detect API base — works whether user is logged in or not
const API = (window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1'))
  ? (localStorage.getItem('api_override') || window.location.origin)
  : window.location.origin;

function formatUptime(seconds) {
  if (!seconds || seconds <= 0) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

const STATUS_CONFIG = {
  running: { color: 'text-green-400', bg: 'bg-green-400', label: 'Online', ring: 'ring-green-500/20' },
  exited: { color: 'text-red-400', bg: 'bg-red-400', label: 'Offline', ring: 'ring-red-500/20' },
  created: { color: 'text-yellow-400', bg: 'bg-yellow-400', label: 'Starting', ring: 'ring-yellow-500/20' },
  restarting: { color: 'text-yellow-400', bg: 'bg-yellow-400', label: 'Restarting', ring: 'ring-yellow-500/20' },
  paused: { color: 'text-gray-400', bg: 'bg-gray-400', label: 'Paused', ring: 'ring-gray-500/20' },
};

export default function PublicStatusPage() {
  const [servers, setServers] = useState([]);
  const [panelName, setPanelName] = useState('');
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API}/api/public/status`);
      if (res.ok) {
        const data = await res.json();
        setServers(data.servers || []);
        setPanelName(data.panel || 'Lynx');
        setLastUpdated(new Date());
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 30000);
    return () => clearInterval(iv);
  }, []);

  const onlineCount = servers.filter(s => s.status === 'running').length;

  return (
    <div className="min-h-screen bg-ink text-white">
      {/* Header */}
      <header className="border-b border-white/10 bg-card/50 backdrop-blur">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-3">
                <FaGlobe className="text-brand-400" />
                <span className="gradient-text-brand">{panelName || 'Lynx'}</span>
              </h1>
              <p className="text-white/50 mt-1 text-sm">Server Status</p>
            </div>
            <div className="text-right">
              <div className="flex items-center gap-2 text-sm">
                <span className={`inline-block w-2.5 h-2.5 rounded-full ${onlineCount > 0 ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
                <span className="text-white/70">
                  {onlineCount}/{servers.length} Online
                </span>
              </div>
              {lastUpdated && (
                <p className="text-white/30 text-xs mt-1">
                  Updated {lastUpdated.toLocaleTimeString()}
                </p>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full" />
          </div>
        ) : servers.length === 0 ? (
          <div className="text-center py-20 text-white/40">
            <FaServer className="text-5xl mx-auto mb-4 text-white/20" />
            <p className="text-lg">No servers configured</p>
          </div>
        ) : (
          <div className="space-y-3">
            {servers.map((srv, i) => {
              const cfg = STATUS_CONFIG[srv.status] || STATUS_CONFIG.exited;
              return (
                <div
                  key={i}
                  className={`bg-white/5 border border-white/10 rounded-xl p-4 sm:p-5 flex items-center gap-4 hover:bg-white/[0.07] transition-colors ring-1 ${cfg.ring}`}
                >
                  {/* Status indicator */}
                  <div className="flex-shrink-0">
                    <div className={`w-3 h-3 rounded-full ${cfg.bg} ${srv.status === 'running' ? 'animate-pulse' : ''}`} />
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-white truncate">{srv.name}</h3>
                      <span className={`text-xs px-2 py-0.5 rounded-full bg-white/10 ${cfg.color}`}>
                        {cfg.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-white/40 flex-wrap">
                      <span className="flex items-center gap-1">
                        <FaGamepad /> {srv.game || 'Unknown'}
                      </span>
                      {srv.version && (
                        <span>{srv.version}</span>
                      )}
                    </div>
                  </div>

                  {/* Uptime */}
                  <div className="flex-shrink-0 text-right">
                    {srv.status === 'running' && srv.uptime_seconds > 0 && (
                      <div className="flex items-center gap-1.5 text-sm text-white/60">
                        <FaClock className="text-white/30" />
                        {formatUptime(srv.uptime_seconds)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Footer */}
        <div className="mt-12 text-center text-white/20 text-xs">
          <p>Powered by {panelName || 'Lynx'} • Auto-refreshes every 30 seconds</p>
        </div>
      </main>
    </div>
  );
}
