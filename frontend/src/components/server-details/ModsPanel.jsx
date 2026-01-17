import React, { useEffect, useState, useMemo } from 'react';
import { FaUpload, FaTrash, FaCube, FaSearch, FaDownload, FaTimes, FaExternalLinkAlt } from 'react-icons/fa';
import { useTranslation } from '../../i18n';
import { API, getStoredToken } from '../../lib/api';

export default function ModsPanel({ serverName, serverVersion, serverLoader }) {
    const { t } = useTranslation();
    const sName = serverName || '';
    const [mods, setMods] = useState([]);
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
    const [sources, setSources] = useState([]);
    const [installing, setInstalling] = useState(null); // mod id being installed
    const [installError, setInstallError] = useState('');

    // Get auth headers
    function authHeaders() {
        const token = getStoredToken();
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }

    async function refresh() {
        setLoading(true); setError('');
        try {
            if (!sName) { setMods([]); return; }
            const r = await fetch(`${API}/mods/${encodeURIComponent(sName)}`, {
                headers: authHeaders()
            });
            const d = await r.json();
            setMods(d.mods || []);
        } catch (e) { setError(String(e)); } finally { setLoading(false); }
    }

    async function loadSources() {
        try {
            if (!sName) return;
            const r = await fetch(`${API}/mods/${encodeURIComponent(sName)}/sources`, {
                headers: authHeaders()
            });
            const d = await r.json();
            setSources(d.sources || []);
        } catch (e) { console.error('Failed to load sources:', e); }
    }

    useEffect(() => { refresh(); loadSources(); }, [serverName]);

    async function upload(e) {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        setUploading(true); setUploadPct(0);
        try {
            const token = getStoredToken();
            if (!sName) return;
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${API}/mods/${encodeURIComponent(sName)}/upload`, true);
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

    async function remove(name) {
        if (!sName) return;
        await fetch(`${API}/mods/${encodeURIComponent(sName)}/${encodeURIComponent(name)}`, {
            method: 'DELETE',
            headers: authHeaders()
        });
        await refresh();
    }

    async function searchMods() {
        if (!searchQuery.trim()) return;
        setSearching(true); setSearchError(''); setSearchResults([]);
        try {
            const params = new URLSearchParams({
                query: searchQuery,
                source: searchSource,
                limit: '20',
            });
            if (serverVersion) params.append('version', serverVersion);
            if (serverLoader) params.append('loader', serverLoader);

            const r = await fetch(
                `${API}/mods/${encodeURIComponent(sName)}/search?${params}`,
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

    async function installMod(mod) {
        setInstalling(mod.id); setInstallError('');
        try {
            // First get the versions to find the best download URL
            const versionParams = new URLSearchParams({
                source: mod.source,
            });
            if (serverVersion) versionParams.append('version', serverVersion);
            if (serverLoader) versionParams.append('loader', serverLoader);

            const vr = await fetch(
                `${API}/mods/${encodeURIComponent(sName)}/versions/${mod.id}?${versionParams}`,
                { headers: authHeaders() }
            );
            const vd = await vr.json();
            const versions = vd.versions || [];

            if (!versions.length) {
                throw new Error('No compatible version found');
            }

            // Use the first (latest compatible) version
            const version = versions[0];

            const r = await fetch(`${API}/mods/${encodeURIComponent(sName)}/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    url: version.download_url,
                    filename: version.filename,
                }),
            });
            const d = await r.json();
            if (!d.ok) throw new Error(d.detail || d.error || 'Install failed');

            // Refresh installed mods list
            await refresh();
        } catch (e) {
            setInstallError(`Failed to install ${mod.name}: ${e.message || e}`);
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

    // Check if a mod is already installed
    const installedNames = useMemo(() => new Set(mods.map(m => m.name.toLowerCase())), [mods]);

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                    <FaCube className="text-purple-400" />
                    <h3 className="text-lg font-medium text-white">Mods</h3>
                    <span className="text-sm text-white/50">({mods.length})</span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setShowSearch(!showSearch)}
                        className={`rounded px-4 py-2 inline-flex items-center gap-2 transition-colors ${showSearch
                            ? 'bg-purple-500 text-white'
                            : 'bg-white/10 hover:bg-white/20 text-white/80'
                            }`}
                    >
                        <FaSearch />
                        <span className="hidden sm:inline">Search Mods</span>
                    </button>
                    <label className="rounded bg-purple-600 hover:bg-purple-500 px-4 py-2 cursor-pointer inline-flex items-center gap-2 text-white transition-colors">
                        <FaUpload />
                        <span className="hidden sm:inline">Upload</span>
                        <input type="file" className="hidden" accept=".jar" onChange={upload} />
                    </label>
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
                                onKeyDown={(e) => e.key === 'Enter' && searchMods()}
                                placeholder={t('modsPlugins.searchForMods')}
                                className="w-full bg-white/10 border border-white/20 rounded-lg px-4 py-2 text-white placeholder-white/40 focus:outline-none focus:border-purple-500"
                            />
                        </div>
                        <select
                            value={searchSource}
                            onChange={(e) => setSearchSource(e.target.value)}
                            className="bg-white/10 border border-white/20 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-purple-500"
                        >
                            {sources.filter(s => s.available).map(s => (
                                <option key={s.id} value={s.id} className="bg-gray-800">{s.name}</option>
                            ))}
                            {!sources.length && (
                                <>
                                    <option value="modrinth" className="bg-gray-800">Modrinth</option>
                                    <option value="curseforge" className="bg-gray-800">CurseForge</option>
                                </>
                            )}
                        </select>
                        <button
                            onClick={searchMods}
                            disabled={searching || !searchQuery.trim()}
                            className="rounded-lg bg-purple-600 hover:bg-purple-500 disabled:opacity-50 px-4 py-2 text-white inline-flex items-center gap-2"
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
                            Filtering for: <span className="text-purple-400">{serverLoader || 'any'}</span> on <span className="text-purple-400">{serverVersion}</span>
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
                            {searchResults.map(mod => (
                                <div
                                    key={`${mod.source}-${mod.id}`}
                                    className="bg-white/5 border border-white/10 rounded-lg p-3 flex items-start gap-3 hover:bg-white/10 transition-colors"
                                >
                                    {mod.icon_url ? (
                                        <img
                                            src={mod.icon_url}
                                            alt=""
                                            className="w-12 h-12 rounded-lg object-cover flex-shrink-0"
                                            onError={(e) => { e.target.style.display = 'none'; }}
                                        />
                                    ) : (
                                        <div className="w-12 h-12 rounded-lg bg-purple-500/20 flex items-center justify-center flex-shrink-0">
                                            <FaCube className="text-purple-400" />
                                        </div>
                                    )}
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <h4 className="text-white font-medium truncate">{mod.name}</h4>
                                            {mod.page_url && (
                                                <a
                                                    href={mod.page_url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="text-white/40 hover:text-white"
                                                >
                                                    <FaExternalLinkAlt className="text-xs" />
                                                </a>
                                            )}
                                        </div>
                                        <p className="text-white/60 text-sm line-clamp-2">{mod.description}</p>
                                        <div className="flex items-center gap-3 mt-1 text-xs text-white/40">
                                            {mod.author && <span>by {mod.author}</span>}
                                            <span>{formatDownloads(mod.downloads)} downloads</span>
                                            <span className="capitalize">{mod.source}</span>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => installMod(mod)}
                                        disabled={installing === mod.id}
                                        className="flex-shrink-0 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-50 px-3 py-2 text-white text-sm inline-flex items-center gap-2"
                                    >
                                        <FaDownload />
                                        {installing === mod.id ? 'Installing...' : 'Install'}
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    {searching && (
                        <div className="text-center py-8 text-white/60">
                            <div className="animate-spin w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full mx-auto mb-2"></div>
                            Searching...
                        </div>
                    )}

                    {!searching && searchResults.length === 0 && searchQuery && (
                        <div className="text-center py-8 text-white/50">
                            No mods found. Try a different search term.
                        </div>
                    )}
                </div>
            )}

            {uploading && (
                <div className="glassmorphism rounded-lg p-3">
                    <div className="text-sm text-white/70 mb-1">Uploading… {uploadPct}%</div>
                    <div className="w-full h-2 bg-white/10 rounded overflow-hidden">
                        <div className="h-full bg-purple-500 transition-all" style={{ width: `${uploadPct}%` }} />
                    </div>
                </div>
            )}

            {loading ? (
                <div className="text-white/60 text-sm py-8 text-center">Loading mods…</div>
            ) : error ? (
                <div className="text-red-400 text-sm py-4">{error}</div>
            ) : mods.length === 0 ? (
                <div className="glassmorphism rounded-xl p-8 text-center">
                    <FaCube className="text-4xl text-white/20 mx-auto mb-3" />
                    <p className="text-white/60">No mods installed</p>
                    <p className="text-sm text-white/40 mt-1">Search for mods or upload .jar files</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {mods.map(mod => (
                        <div key={mod.name} className="glassmorphism rounded-lg p-3 flex items-center justify-between hover:bg-white/5 transition-colors">
                            <div className="flex items-center gap-3">
                                <FaCube className="text-purple-400" />
                                <div>
                                    <div className="text-sm text-white font-medium">{mod.name}</div>
                                    <div className="text-xs text-white/50">{formatSize(mod.size)}</div>
                                </div>
                            </div>
                            <button
                                onClick={() => remove(mod.name)}
                                className="text-red-400 hover:text-red-300 hover:bg-red-500/10 p-2 rounded transition-colors"
                                title={t('modsPlugins.deleteMod')}
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
