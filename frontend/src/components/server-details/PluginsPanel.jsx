import React, { useEffect, useState, useMemo } from 'react';
import { FaUpload, FaTrash, FaPlug, FaSearch, FaDownload, FaTimes, FaExternalLinkAlt, FaSyncAlt } from 'react-icons/fa';
import { API, getStoredToken } from '../../lib/api';

export default function PluginsPanel({ serverName, serverVersion }) {
  const sName = serverName || '';
  const [plugins, setPlugins] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [uploadPct, setUploadPct] = useState(0);
  const [uploading, setUploading] = useState(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchSource, setSearchSource] = useState('modrinth');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [installing, setInstalling] = useState(null);
  const [installError, setInstallError] = useState('');

  function authHeaders() {
    const token = getStoredToken();
    return token ? { 'Authorization': `Bearer ${token}` } : {};
  }

  async function refresh() {
    setLoading(true); setError('');
    try {
      if (!sName) { setPlugins([]); return; }
      const r = await fetch(`${API}/plugins/${encodeURIComponent(sName)}`, {
        headers: authHeaders()
      });
      const d = await r.json();
      setPlugins(d.plugins || []);
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  }

  useEffect(() => { refresh(); }, [serverName]);

  async function upload(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setUploading(true); setUploadPct(0);
    try {
      const token = getStoredToken();
      if (!sName) return;
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API}/plugins/${encodeURIComponent(sName)}/upload`, true);
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) setUploadPct(Math.round((ev.loaded / ev.total) * 100));
      };
      xhr.onload = async () => { await refresh(); };
      xhr.onerror = () => setError('Upload failed');
      const fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    } finally {
      setTimeout(() => { setUploading(false); setUploadPct(0); }, 400);
    }
  }

  async function reloadPlugins() {
    if (!sName) return;
    try {
      await fetch(`${API}/plugins/${encodeURIComponent(sName)}/reload`, {
        method: 'POST',
        headers: authHeaders()
      });
    } catch (e) { console.error('Reload failed:', e); }
  }

  async function remove(name) {
    if (!sName) return;
    await fetch(`${API}/plugins/${encodeURIComponent(sName)}/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: authHeaders()
    });
    await refresh();
  }

  async function searchPlugins() {
    if (!searchQuery.trim()) return;
    setSearching(true); setSearchError(''); setSearchResults([]);
    try {
      const params = new URLSearchParams({
        query: searchQuery,
        source: searchSource,
        limit: '20',
      });
      if (serverVersion) params.append('version', serverVersion);

      const r = await fetch(
        `${API}/plugins/${encodeURIComponent(sName)}/search?${params}`,
        { headers: authHeaders() }
      );
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setSearchResults(d.results || []);
    } catch (e) {
      setSearchError(String(e));
    } finally {
      setSearching(false);
    }
  }

  async function installPlugin(plugin) {
    setInstalling(plugin.id); setInstallError('');
    try {
      let downloadUrl = plugin.download_url;
      let filename = null;

      // For Modrinth, get versions first
      if (plugin.source === 'modrinth') {
        const versionParams = new URLSearchParams({ source: 'modrinth' });
        if (serverVersion) versionParams.append('version', serverVersion);

        // Need to call mods versions endpoint since plugins also use it
        const vr = await fetch(
          `${API}/mods/${encodeURIComponent(sName)}/versions/${plugin.id}?${versionParams}`,
          { headers: authHeaders() }
        );
        const vd = await vr.json();
        const versions = vd.versions || [];

        if (!versions.length) {
          throw new Error('No compatible version found');
        }

        downloadUrl = versions[0].download_url;
        filename = versions[0].filename;
      }

      // For Spiget, construct the URL
      if (plugin.source === 'spiget') {
        downloadUrl = `https://api.spiget.org/v2/resources/${plugin.id}/download`;
      }

      if (!downloadUrl) {
        throw new Error('No download URL available');
      }

      const r = await fetch(`${API}/plugins/${encodeURIComponent(sName)}/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          url: downloadUrl,
          filename: filename,
          resource_id: plugin.id,
          source: plugin.source,
        }),
      });
      const d = await r.json();
      if (!d.ok) throw new Error(d.detail || d.error || 'Install failed');

      await refresh();
    } catch (e) {
      setInstallError(`Failed to install ${plugin.name}: ${e.message || e}`);
    } finally {
      setInstalling(null);
    }
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDownloads(n) {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return String(n);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <FaPlug className="text-green-400" />
          <h3 className="text-lg font-medium text-white">Plugins</h3>
          <span className="text-sm text-white/50">({plugins.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSearch(!showSearch)}
            className={`rounded px-4 py-2 inline-flex items-center gap-2 transition-colors ${showSearch
                ? 'bg-green-500 text-white'
                : 'bg-white/10 hover:bg-white/20 text-white/80'
              }`}
          >
            <FaSearch />
            <span className="hidden sm:inline">Search Plugins</span>
          </button>
          <label className="rounded bg-green-600 hover:bg-green-500 px-4 py-2 cursor-pointer inline-flex items-center gap-2 text-white transition-colors">
            <FaUpload />
            <span className="hidden sm:inline">Upload</span>
            <input type="file" className="hidden" accept=".jar" onChange={upload} />
          </label>
          <button
            onClick={reloadPlugins}
            className="rounded bg-white/10 hover:bg-white/20 border border-white/10 px-3 py-2 text-white/80 inline-flex items-center gap-2"
            title="Reload plugins in game"
          >
            <FaSyncAlt />
            <span className="hidden sm:inline">Reload</span>
          </button>
        </div>
      </div>

      {/* Search Panel */}
      {showSearch && (
        <div className="glassmorphism rounded-xl p-4 space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && searchPlugins()}
                placeholder="Search for plugins..."
                className="w-full bg-white/10 border border-white/20 rounded-lg px-4 py-2 text-white placeholder-white/40 focus:outline-none focus:border-green-500"
              />
            </div>
            <select
              value={searchSource}
              onChange={(e) => setSearchSource(e.target.value)}
              className="bg-white/10 border border-white/20 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-green-500"
            >
              <option value="modrinth" className="bg-gray-800">Modrinth</option>
              <option value="spiget" className="bg-gray-800">SpigotMC</option>
            </select>
            <button
              onClick={searchPlugins}
              disabled={searching || !searchQuery.trim()}
              className="rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-50 px-4 py-2 text-white inline-flex items-center gap-2"
            >
              <FaSearch />
              {searching ? 'Searching...' : 'Search'}
            </button>
            <button
              onClick={() => { setShowSearch(false); setSearchResults([]); setSearchQuery(''); }}
              className="text-white/60 hover:text-white p-2"
            >
              <FaTimes />
            </button>
          </div>

          {serverVersion && (
            <div className="text-xs text-white/50">
              Server version: <span className="text-green-400">{serverVersion}</span>
            </div>
          )}

          {searchError && (
            <div className="text-red-400 text-sm">{searchError}</div>
          )}

          {installError && (
            <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg p-3">{installError}</div>
          )}

          {/* Search Results */}
          {searchResults.length > 0 && (
            <div className="grid gap-3 max-h-[400px] overflow-y-auto">
              {searchResults.map(plugin => (
                <div
                  key={`${plugin.source}-${plugin.id}`}
                  className="bg-white/5 border border-white/10 rounded-lg p-3 flex items-start gap-3 hover:bg-white/10 transition-colors"
                >
                  {plugin.icon_url ? (
                    <img
                      src={plugin.icon_url}
                      alt=""
                      className="w-12 h-12 rounded-lg object-cover flex-shrink-0"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                  ) : (
                    <div className="w-12 h-12 rounded-lg bg-green-500/20 flex items-center justify-center flex-shrink-0">
                      <FaPlug className="text-green-400" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h4 className="text-white font-medium truncate">{plugin.name}</h4>
                      {plugin.external && (
                        <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-400">External</span>
                      )}
                      {plugin.page_url && (
                        <a
                          href={plugin.page_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-white/40 hover:text-white"
                        >
                          <FaExternalLinkAlt className="text-xs" />
                        </a>
                      )}
                    </div>
                    <p className="text-white/60 text-sm line-clamp-2">{plugin.description}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-white/40">
                      {plugin.author && <span>by {plugin.author}</span>}
                      <span>{formatDownloads(plugin.downloads)} downloads</span>
                      <span className="capitalize">{plugin.source === 'spiget' ? 'SpigotMC' : plugin.source}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => installPlugin(plugin)}
                    disabled={installing === plugin.id || plugin.external}
                    className="flex-shrink-0 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-50 px-3 py-2 text-white text-sm inline-flex items-center gap-2"
                    title={plugin.external ? 'External plugins must be downloaded manually' : 'Install plugin'}
                  >
                    <FaDownload />
                    {installing === plugin.id ? 'Installing...' : 'Install'}
                  </button>
                </div>
              ))}
            </div>
          )}

          {searching && (
            <div className="text-center py-8 text-white/60">
              <div className="animate-spin w-8 h-8 border-2 border-green-500 border-t-transparent rounded-full mx-auto mb-2"></div>
              Searching...
            </div>
          )}

          {!searching && searchResults.length === 0 && searchQuery && (
            <div className="text-center py-8 text-white/50">
              No plugins found. Try a different search term.
            </div>
          )}
        </div>
      )}

      {uploading && (
        <div className="glassmorphism rounded-lg p-3">
          <div className="text-sm text-white/70 mb-1">Uploading… {uploadPct}%</div>
          <div className="w-full h-2 bg-white/10 rounded overflow-hidden">
            <div className="h-full bg-green-500 transition-all" style={{ width: `${uploadPct}%` }} />
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-white/60 text-sm py-8 text-center">Loading plugins…</div>
      ) : error ? (
        <div className="text-red-400 text-sm py-4">{error}</div>
      ) : plugins.length === 0 ? (
        <div className="glassmorphism rounded-xl p-8 text-center">
          <FaPlug className="text-4xl text-white/20 mx-auto mb-3" />
          <p className="text-white/60">No plugins installed</p>
          <p className="text-sm text-white/40 mt-1">Search for plugins or upload .jar files</p>
        </div>
      ) : (
        <div className="space-y-2">
          {plugins.map(plugin => (
            <div key={plugin.name} className="glassmorphism rounded-lg p-3 flex items-center justify-between hover:bg-white/5 transition-colors">
              <div className="flex items-center gap-3">
                <FaPlug className="text-green-400" />
                <div>
                  <div className="text-sm text-white font-medium">{plugin.name}</div>
                  <div className="text-xs text-white/50">{formatSize(plugin.size)}</div>
                </div>
              </div>
              <button
                onClick={() => remove(plugin.name)}
                className="text-red-400 hover:text-red-300 hover:bg-red-500/10 p-2 rounded transition-colors"
                title="Delete plugin"
              >
                <FaTrash />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
