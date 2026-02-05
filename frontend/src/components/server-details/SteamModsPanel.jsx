import React, { useEffect, useState, useMemo } from 'react';
import { FaDownload, FaTrash, FaCube, FaSearch, FaTimes, FaSteam, FaBolt, FaExternalLinkAlt, FaCog, FaFolder, FaFire } from 'react-icons/fa';
import { API, getStoredToken } from '../../lib/api';

// Games that support mods
const SUPPORTED_GAMES = {
    // Thunderstore games
    valheim: { source: 'thunderstore', community: 'valheim', name: 'Valheim' },
    lethal_company: { source: 'thunderstore', community: 'lethal-company', name: 'Lethal Company' },
    risk_of_rain_2: { source: 'thunderstore', community: 'ror2', name: 'Risk of Rain 2' },
    vrising: { source: 'thunderstore', community: 'v-rising', name: 'V Rising' },
    sunkenland: { source: 'thunderstore', community: 'sunkenland', name: 'Sunkenland' },
    palworld: { source: 'thunderstore', community: 'palworld', name: 'Palworld' },
    content_warning: { source: 'thunderstore', community: 'content-warning', name: 'Content Warning' },
    core_keeper: { source: 'thunderstore', community: 'core-keeper', name: 'Core Keeper' },
    // Workshop games
    gmod: { source: 'workshop', appid: 4000, name: "Garry's Mod" },
    garrys_mod: { source: 'workshop', appid: 4000, name: "Garry's Mod" },
    arma3: { source: 'workshop', appid: 107410, name: 'Arma 3' },
    dont_starve_together: { source: 'workshop', appid: 322330, name: "Don't Starve Together" },
    project_zomboid: { source: 'workshop', appid: 108600, name: 'Project Zomboid' },
    space_engineers: { source: 'workshop', appid: 244850, name: 'Space Engineers' },
    '7_days_to_die': { source: 'workshop', appid: 251570, name: '7 Days to Die' },
    conan_exiles: { source: 'workshop', appid: 440900, name: 'Conan Exiles' },
    ark: { source: 'workshop', appid: 346110, name: 'ARK' },
    rust: { source: 'workshop', appid: 252490, name: 'Rust (Oxide)' },
    // CurseForge games
    palworld_cf: { source: 'curseforge', game_id: 83374, slug: 'palworld', name: 'Palworld (CurseForge)' },
    '7_days_to_die_cf': { source: 'curseforge', game_id: 7, slug: '7_days_to_die', name: '7 Days to Die (CurseForge)' },
    ark_cf: { source: 'curseforge', game_id: 84698, slug: 'ark', name: 'ARK: Survival Ascended (CurseForge)' },
    terraria: { source: 'curseforge', game_id: 431, slug: 'terraria', name: 'Terraria' },
    ksp: { source: 'curseforge', game_id: 4401, slug: 'ksp', name: 'Kerbal Space Program' },
    stardew_valley: { source: 'curseforge', game_id: 669, slug: 'stardew_valley', name: 'Stardew Valley' },
    valheim_cf: { source: 'curseforge', game_id: 68940, slug: 'valheim', name: 'Valheim (CurseForge)' },
    rimworld: { source: 'curseforge', game_id: 73492, slug: 'rimworld', name: 'RimWorld' },
    satisfactory: { source: 'curseforge', game_id: 78054, slug: 'satisfactory', name: 'Satisfactory' },
    sims4: { source: 'curseforge', game_id: 78062, slug: 'sims4', name: 'The Sims 4' },
    among_us: { source: 'curseforge', game_id: 69762, slug: 'among_us', name: 'Among Us' },
};

export default function SteamModsPanel({ serverId, serverName, gameSlug }) {
    const [loading, setLoading] = useState(false);
    const [installedMods, setInstalledMods] = useState([]);
    const [error, setError] = useState('');
    
    // Search state
    const [showSearch, setShowSearch] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState('');
    const [installing, setInstalling] = useState(null);
    const [page, setPage] = useState(1);
    const [totalResults, setTotalResults] = useState(0);

    const gameConfig = SUPPORTED_GAMES[gameSlug] || null;
    const isSupported = gameConfig !== null;

    function authHeaders() {
        const token = getStoredToken();
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }

    // Fetch installed mods
    async function fetchInstalledMods() {
        if (!serverId || !gameSlug) return;
        setLoading(true);
        setError('');
        try {
            const res = await fetch(
                `${API}/steam-mods/installed/${encodeURIComponent(serverId)}?game_slug=${encodeURIComponent(gameSlug)}`,
                { headers: authHeaders() }
            );
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setInstalledMods(data.mods || []);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }

    // Search mods
    async function searchMods(newPage = 1) {
        if (!searchQuery.trim() && newPage === 1) return;
        setSearching(true);
        setSearchError('');
        if (newPage === 1) setSearchResults([]);

        try {
            let url;
            if (gameConfig.source === 'thunderstore') {
                url = `${API}/steam-mods/thunderstore/search?community=${encodeURIComponent(gameConfig.community)}&q=${encodeURIComponent(searchQuery)}&page=${newPage}`;
            } else if (gameConfig.source === 'curseforge') {
                url = `${API}/steam-mods/curseforge/search?game_slug=${encodeURIComponent(gameConfig.slug)}&query=${encodeURIComponent(searchQuery)}&page=${newPage}&page_size=20`;
            } else {
                url = `${API}/steam-mods/workshop/search?appid=${gameConfig.appid}&q=${encodeURIComponent(searchQuery)}&page=${newPage}`;
            }

            const res = await fetch(url, { headers: authHeaders() });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            
            // Normalize results based on source
            let results = [];
            if (gameConfig.source === 'curseforge') {
                results = (data.mods || []).map(mod => ({
                    id: mod.id,
                    mod_id: mod.id,
                    title: mod.name,
                    name: mod.name,
                    description: mod.summary,
                    icon_url: mod.logo?.thumbnailUrl || mod.logo?.url,
                    downloads: mod.downloadCount,
                    namespace: mod.authors?.[0]?.name || 'Unknown',
                    curseforge_url: mod.links?.websiteUrl,
                    latest_file: mod.latestFiles?.[0],
                    categories: mod.categories || []
                }));
            } else {
                results = data.results || [];
            }
            
            setSearchResults(prev => newPage === 1 ? results : [...prev, ...results]);
            setTotalResults(data.total || data.pagination?.totalCount || 0);
            setPage(newPage);
        } catch (e) {
            setSearchError(e.message);
        } finally {
            setSearching(false);
        }
    }

    // Install mod from Thunderstore
    async function installThunderstoreMod(mod) {
        setInstalling(mod.id);
        try {
            const res = await fetch(`${API}/steam-mods/thunderstore/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    server_id: serverId,
                    namespace: mod.namespace,
                    name: mod.name,
                    version: mod.version,
                    game_slug: gameSlug,
                    install_dependencies: true
                })
            });
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            const data = await res.json();
            alert(`✅ Installed ${data.installed?.length || 1} mod(s) successfully!`);
            await fetchInstalledMods();
        } catch (e) {
            alert(`❌ Failed to install: ${e.message}`);
        } finally {
            setInstalling(null);
        }
    }

    // Install mod from CurseForge
    async function installCurseForgeMod(mod) {
        setInstalling(mod.id);
        try {
            // Get latest file if we don't have one
            let fileId = mod.latest_file?.id;
            
            if (!fileId) {
                // Fetch files for this mod
                const filesRes = await fetch(
                    `${API}/steam-mods/curseforge/mod/${mod.mod_id}/files`,
                    { headers: authHeaders() }
                );
                if (filesRes.ok) {
                    const filesData = await filesRes.json();
                    if (filesData.files?.length > 0) {
                        fileId = filesData.files[0].id;
                    }
                }
            }
            
            if (!fileId) {
                throw new Error('No downloadable file found for this mod');
            }
            
            const res = await fetch(`${API}/steam-mods/curseforge/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    server_id: serverId,
                    game_slug: gameConfig.slug,
                    mod_id: mod.mod_id,
                    file_id: fileId
                })
            });
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            const data = await res.json();
            alert(`✅ Installed ${mod.name} successfully!`);
            await fetchInstalledMods();
        } catch (e) {
            alert(`❌ Failed to install: ${e.message}`);
        } finally {
            setInstalling(null);
        }
    }

    // Uninstall mod
    async function uninstallMod(modName) {
        if (!confirm(`Remove ${modName}?`)) return;
        try {
            const res = await fetch(`${API}/steam-mods/uninstall`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    server_id: serverId,
                    mod_name: modName,
                    game_slug: gameSlug
                })
            });
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            await fetchInstalledMods();
        } catch (e) {
            alert(`Failed to uninstall: ${e.message}`);
        }
    }

    useEffect(() => {
        if (isSupported) {
            fetchInstalledMods();
        }
    }, [serverId, gameSlug]);

    // Game not supported
    if (!isSupported) {
        return (
            <div className="p-6">
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-6 text-center">
                    <FaCube className="text-4xl text-yellow-400 mx-auto mb-4" />
                    <h3 className="text-xl font-bold text-white mb-2">Mod Support Not Available</h3>
                    <p className="text-white/60">
                        This game ({gameSlug}) doesn't have integrated mod support yet.
                    </p>
                    <p className="text-white/40 text-sm mt-2">
                        You can still manually add mods via the Files tab.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        <FaCube className="text-brand-400" />
                        Mods for {gameConfig.name}
                    </h2>
                    <p className="text-white/50 text-sm mt-1">
                        Source: {gameConfig.source === 'thunderstore' ? 'Thunderstore' : gameConfig.source === 'curseforge' ? 'CurseForge' : 'Steam Workshop'}
                    </p>
                </div>
                <button
                    onClick={() => setShowSearch(!showSearch)}
                    className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors"
                >
                    <FaSearch /> Browse Mods
                </button>
            </div>

            {/* Mod Browser Modal */}
            {showSearch && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
                    <div className="bg-gray-900 border border-white/10 rounded-xl w-full max-w-4xl shadow-2xl max-h-[85vh] flex flex-col">
                        {/* Header */}
                        <div className="p-4 border-b border-white/10 flex items-center justify-between shrink-0">
                            <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                {gameConfig.source === 'thunderstore' ? (
                                    <FaBolt className="text-blue-400" />
                                ) : gameConfig.source === 'curseforge' ? (
                                    <FaFire className="text-orange-500" />
                                ) : (
                                    <FaSteam className="text-blue-400" />
                                )}
                                Browse {gameConfig.source === 'thunderstore' ? 'Thunderstore' : gameConfig.source === 'curseforge' ? 'CurseForge' : 'Workshop'} Mods
                            </h3>
                            <button onClick={() => setShowSearch(false)} className="text-white/60 hover:text-white">
                                <FaTimes size={20} />
                            </button>
                        </div>

                        {/* Search Bar */}
                        <div className="p-4 border-b border-white/10 shrink-0">
                            <div className="flex gap-2">
                                <div className="relative flex-1">
                                    <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
                                    <input
                                        type="text"
                                        placeholder="Search mods..."
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && searchMods(1)}
                                        className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:outline-none focus:border-brand-500"
                                    />
                                </div>
                                <button
                                    onClick={() => searchMods(1)}
                                    disabled={searching}
                                    className="px-6 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors disabled:opacity-50"
                                >
                                    {searching ? 'Searching...' : 'Search'}
                                </button>
                            </div>
                            {searchError && (
                                <p className="text-red-400 text-sm mt-2">{searchError}</p>
                            )}
                        </div>

                        {/* Results */}
                        <div className="flex-1 overflow-y-auto p-4">
                            {searchResults.length === 0 && !searching ? (
                                <div className="text-center text-white/40 py-12">
                                    {searchQuery ? 'No mods found. Try a different search.' : 'Enter a search term to find mods'}
                                </div>
                            ) : (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {searchResults.map(mod => (
                                        <ModCard
                                            key={mod.id}
                                            mod={mod}
                                            installing={installing === mod.id}
                                            onInstall={() => {
                                                if (gameConfig.source === 'thunderstore') {
                                                    installThunderstoreMod(mod);
                                                } else if (gameConfig.source === 'curseforge') {
                                                    installCurseForgeMod(mod);
                                                } else {
                                                    alert('Workshop mod installation coming soon');
                                                }
                                            }}
                                        />
                                    ))}
                                </div>
                            )}

                            {/* Load More */}
                            {searchResults.length > 0 && searchResults.length < totalResults && (
                                <div className="text-center mt-6">
                                    <button
                                        onClick={() => searchMods(page + 1)}
                                        disabled={searching}
                                        className="px-6 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors disabled:opacity-50"
                                    >
                                        {searching ? 'Loading...' : `Load More (${searchResults.length} of ${totalResults})`}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Installed Mods */}
            <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                <div className="p-4 border-b border-white/10 flex items-center justify-between">
                    <h3 className="font-semibold text-white flex items-center gap-2">
                        <FaFolder className="text-white/60" />
                        Installed Mods ({installedMods.length})
                    </h3>
                    <button
                        onClick={fetchInstalledMods}
                        className="text-white/60 hover:text-white text-sm"
                    >
                        Refresh
                    </button>
                </div>

                {loading ? (
                    <div className="p-8 text-center">
                        <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full mx-auto" />
                    </div>
                ) : error ? (
                    <div className="p-6 text-center text-red-400">
                        {error}
                    </div>
                ) : installedMods.length === 0 ? (
                    <div className="p-8 text-center text-white/40">
                        No mods installed yet. Click "Browse Mods" to get started!
                    </div>
                ) : (
                    <div className="divide-y divide-white/5">
                        {installedMods.map((mod, idx) => (
                            <div key={mod.name || idx} className="p-4 flex items-center justify-between hover:bg-white/5">
                                <div>
                                    <p className="text-white font-medium">{mod.name}</p>
                                    <p className="text-white/50 text-sm">
                                        {mod.version !== 'unknown' && `v${mod.version} • `}
                                        {mod.type === 'file' ? mod.file : mod.folder}
                                    </p>
                                </div>
                                <button
                                    onClick={() => uninstallMod(mod.folder || mod.file || mod.name)}
                                    className="p-2 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                                    title="Uninstall"
                                >
                                    <FaTrash />
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Info Box */}
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                <h4 className="font-semibold text-blue-400 mb-2">💡 Tips</h4>
                <ul className="text-white/60 text-sm space-y-1">
                    <li>• Most mods require a server restart to take effect</li>
                    {gameConfig.source === 'thunderstore' && (
                        <>
                            <li>• Dependencies are automatically installed</li>
                            <li>• Some mods require BepInEx mod loader</li>
                        </>
                    )}
                    {gameConfig.source === 'curseforge' && (
                        <>
                            <li>• CurseForge hosts mods for many popular games</li>
                            <li>• Check mod compatibility with your game version</li>
                        </>
                    )}
                    {gameConfig.source === 'workshop' && (
                        <li>• Workshop items are downloaded from Steam</li>
                    )}
                </ul>
            </div>
        </div>
    );
}

// Mod Card Component
function ModCard({ mod, installing, onInstall }) {
    return (
        <div className="bg-white/5 border border-white/10 rounded-lg p-4 flex gap-4">
            {/* Icon */}
            {mod.icon_url ? (
                <img
                    src={mod.icon_url}
                    alt=""
                    className="w-16 h-16 rounded-lg object-cover shrink-0 bg-white/10"
                    onError={(e) => e.target.style.display = 'none'}
                />
            ) : (
                <div className="w-16 h-16 rounded-lg bg-gradient-to-br from-brand-500/30 to-purple-500/30 flex items-center justify-center shrink-0">
                    <FaCube className="text-2xl text-white/60" />
                </div>
            )}

            {/* Info */}
            <div className="flex-1 min-w-0">
                <h4 className="text-white font-semibold truncate">{mod.title || mod.name}</h4>
                <p className="text-white/50 text-sm line-clamp-2 mt-1">
                    {mod.description || 'No description available'}
                </p>
                <div className="flex items-center gap-4 mt-2 text-xs text-white/40">
                    {mod.downloads && (
                        <span className="flex items-center gap-1">
                            <FaDownload /> {formatNumber(mod.downloads)}
                        </span>
                    )}
                    {mod.version && (
                        <span>v{mod.version}</span>
                    )}
                    {mod.namespace && (
                        <span>by {mod.namespace}</span>
                    )}
                </div>
            </div>

            {/* Install Button */}
            <div className="shrink-0">
                <button
                    onClick={onInstall}
                    disabled={installing}
                    className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                    {installing ? (
                        <>
                            <span className="animate-spin">⏳</span> Installing
                        </>
                    ) : (
                        <>
                            <FaDownload /> Install
                        </>
                    )}
                </button>
            </div>
        </div>
    );
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num?.toString() || '0';
}
