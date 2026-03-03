import React, { useState, useEffect } from 'react';
import {
  FaLink, FaDownload, FaBox, FaSync, FaCheck, FaTimes,
  FaExclamationTriangle, FaServer, FaMemory, FaNetworkWired
} from 'react-icons/fa';
import { API, authHeaders } from '../context/AppContext';
import { useToast } from '../context/ToastContext';

export default function ModpackImporter({ onInstallStarted, onClose }) {
  const { showToast } = useToast();
  const [url, setUrl] = useState('');
  const [resolving, setResolving] = useState(false);
  const [packInfo, setPackInfo] = useState(null);
  const [error, setError] = useState('');
  const [selectedVersion, setSelectedVersion] = useState('');
  const [serverName, setServerName] = useState('');
  const [hostPort, setHostPort] = useState(25565);
  const [minRam, setMinRam] = useState('2G');
  const [maxRam, setMaxRam] = useState('4G');
  const [installing, setInstalling] = useState(false);
  const [installProgress, setInstallProgress] = useState(null);

  async function resolveUrl() {
    if (!url.trim()) return;
    setResolving(true);
    setError('');
    setPackInfo(null);
    try {
      const r = await fetch(`${API}/modpacks/resolve-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ url: url.trim() }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${r.status}`);
      }
      const data = await r.json();
      setPackInfo(data);
      // Auto-fill server name
      const safeName = (data.name || 'modpack')
        .replace(/[^a-zA-Z0-9_-]/g, '-')
        .replace(/-+/g, '-')
        .toLowerCase()
        .slice(0, 30);
      setServerName(safeName);
      // Select first version
      if (data.versions?.length > 0) {
        setSelectedVersion(data.versions[0].id);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setResolving(false);
    }
  }

  async function startInstall() {
    if (!packInfo || !serverName.trim()) return;
    setInstalling(true);
    setInstallProgress({ step: 'starting', message: 'Starting installation...', progress: 0 });
    try {
      const r = await fetch(`${API}/modpacks/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          provider: packInfo.provider,
          pack_id: packInfo.pack_id,
          version_id: selectedVersion || undefined,
          name: serverName.trim(),
          host_port: hostPort,
          min_ram: minRam,
          max_ram: maxRam,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${r.status}`);
      }
      const data = await r.json();
      const taskId = data.task_id;
      if (taskId) {
        pollInstallEvents(taskId);
      } else {
        showToast('success', 'Modpack installation started');
        setInstallProgress({ step: 'done', message: 'Done!', progress: 100 });
        onInstallStarted?.();
      }
    } catch (e) {
      showToast('error', e.message);
      setInstalling(false);
      setInstallProgress(null);
    }
  }

  function pollInstallEvents(taskId) {
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API}/modpacks/install/events/${taskId}`, { headers: authHeaders() });
        if (!r.ok) return;
        const data = await r.json();
        const events = data.events || [];
        const latestProgress = events.filter(e => e.type === 'progress').pop();
        const done = events.find(e => e.type === 'done');
        const error = events.find(e => e.type === 'error');

        if (latestProgress) {
          setInstallProgress({
            step: latestProgress.step,
            message: latestProgress.message,
            progress: latestProgress.progress || 0,
          });
        }
        if (done) {
          clearInterval(interval);
          setInstallProgress({ step: 'done', message: 'Installation complete!', progress: 100 });
          showToast('success', `Modpack "${packInfo.name}" installed successfully`);
          setTimeout(() => onInstallStarted?.(), 1500);
        }
        if (error) {
          clearInterval(interval);
          setInstallProgress(null);
          setInstalling(false);
          showToast('error', error.message || 'Installation failed');
        }
      } catch {
        // Retry silently
      }
    }, 2000);
    // Cleanup after 10 minutes max
    setTimeout(() => clearInterval(interval), 600000);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') resolveUrl();
  }

  const formatNumber = (n) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return String(n);
  };

  return (
    <div className="space-y-6">
      {/* URL Input */}
      <div>
        <label className="block text-sm font-medium text-white/70 mb-2">
          Paste a CurseForge or Modrinth modpack URL
        </label>
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <FaLink className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30 w-4 h-4" />
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="https://modrinth.com/modpack/cobblemon or https://www.curseforge.com/minecraft/modpacks/all-the-mods-9"
              className="w-full pl-10 pr-4 py-3 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/30 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none"
              disabled={resolving || installing}
            />
          </div>
          <button
            onClick={resolveUrl}
            disabled={!url.trim() || resolving || installing}
            className="px-5 py-3 bg-brand-500 hover:bg-brand-400 disabled:opacity-50 rounded-lg flex items-center gap-2 text-white font-medium whitespace-nowrap"
          >
            {resolving ? <FaSync className="w-4 h-4 animate-spin" /> : <FaBox className="w-4 h-4" />}
            {resolving ? 'Resolving...' : 'Detect'}
          </button>
        </div>
        {error && (
          <div className="mt-2 flex items-center gap-2 text-red-400 text-sm">
            <FaExclamationTriangle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}
      </div>

      {/* Pack Info */}
      {packInfo && (
        <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
          {/* Pack Header */}
          <div className="flex items-start gap-4 p-5">
            {packInfo.icon_url ? (
              <img
                src={packInfo.icon_url}
                alt={packInfo.name}
                className="w-16 h-16 rounded-lg object-cover bg-white/10 flex-shrink-0"
              />
            ) : (
              <div className="w-16 h-16 rounded-lg bg-white/10 flex items-center justify-center flex-shrink-0">
                <FaBox className="text-white/30 text-2xl" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold text-white truncate">{packInfo.name}</h3>
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                  packInfo.provider === 'modrinth'
                    ? 'bg-green-500/20 text-green-400'
                    : 'bg-orange-500/20 text-orange-400'
                }`}>
                  {packInfo.provider === 'modrinth' ? 'Modrinth' : 'CurseForge'}
                </span>
              </div>
              {packInfo.description && (
                <p className="text-sm text-white/50 mt-1 line-clamp-2">{packInfo.description}</p>
              )}
              <div className="flex items-center gap-4 mt-2 text-xs text-white/40">
                {packInfo.downloads > 0 && (
                  <span>{formatNumber(packInfo.downloads)} downloads</span>
                )}
                {packInfo.loaders?.length > 0 && (
                  <span>{packInfo.loaders.join(', ')}</span>
                )}
              </div>
            </div>
          </div>

          {/* Configuration Form */}
          <div className="border-t border-white/10 p-5 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Version Select */}
              {packInfo.versions?.length > 0 && (
                <div className="sm:col-span-2">
                  <label className="block text-xs text-white/50 mb-1">Version</label>
                  <select
                    value={selectedVersion}
                    onChange={(e) => setSelectedVersion(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
                    disabled={installing}
                  >
                    {packInfo.versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name || v.version_number}
                        {v.game_versions?.length > 0 ? ` (${v.game_versions[0]})` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Server Name */}
              <div>
                <label className="block text-xs text-white/50 mb-1">
                  <FaServer className="inline w-3 h-3 mr-1" />
                  Server Name
                </label>
                <input
                  type="text"
                  value={serverName}
                  onChange={(e) => setServerName(e.target.value.replace(/[^a-zA-Z0-9_-]/g, '-'))}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
                  placeholder="my-modpack-server"
                  disabled={installing}
                />
              </div>

              {/* Port */}
              <div>
                <label className="block text-xs text-white/50 mb-1">
                  <FaNetworkWired className="inline w-3 h-3 mr-1" />
                  Port
                </label>
                <input
                  type="number"
                  value={hostPort}
                  onChange={(e) => setHostPort(parseInt(e.target.value) || 25565)}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
                  disabled={installing}
                />
              </div>

              {/* RAM */}
              <div>
                <label className="block text-xs text-white/50 mb-1">
                  <FaMemory className="inline w-3 h-3 mr-1" />
                  Min RAM
                </label>
                <select
                  value={minRam}
                  onChange={(e) => setMinRam(e.target.value)}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
                  disabled={installing}
                >
                  <option value="1G">1 GB</option>
                  <option value="2G">2 GB</option>
                  <option value="4G">4 GB</option>
                  <option value="6G">6 GB</option>
                  <option value="8G">8 GB</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-white/50 mb-1">
                  <FaMemory className="inline w-3 h-3 mr-1" />
                  Max RAM
                </label>
                <select
                  value={maxRam}
                  onChange={(e) => setMaxRam(e.target.value)}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
                  disabled={installing}
                >
                  <option value="2G">2 GB</option>
                  <option value="4G">4 GB</option>
                  <option value="6G">6 GB</option>
                  <option value="8G">8 GB</option>
                  <option value="12G">12 GB</option>
                  <option value="16G">16 GB</option>
                </select>
              </div>
            </div>

            {/* Install Progress */}
            {installProgress && (
              <div className="mt-4">
                <div className="flex items-center justify-between text-sm mb-2">
                  <span className="text-white/70">{installProgress.message}</span>
                  <span className="text-white/40">{installProgress.progress}%</span>
                </div>
                <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      installProgress.step === 'done' ? 'bg-green-500' : 'bg-brand-500'
                    }`}
                    style={{ width: `${installProgress.progress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Install Button */}
            <button
              onClick={startInstall}
              disabled={installing || !serverName.trim()}
              className={`w-full py-3 rounded-lg flex items-center justify-center gap-2 font-medium transition-colors ${
                installProgress?.step === 'done'
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-brand-500 hover:bg-brand-400 text-white disabled:opacity-50'
              }`}
            >
              {installProgress?.step === 'done' ? (
                <>
                  <FaCheck className="w-4 h-4" />
                  Installed Successfully!
                </>
              ) : installing ? (
                <>
                  <FaSync className="w-4 h-4 animate-spin" />
                  Installing...
                </>
              ) : (
                <>
                  <FaDownload className="w-4 h-4" />
                  Install Modpack
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
