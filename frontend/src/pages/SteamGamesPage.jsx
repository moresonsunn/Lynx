import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { FaSteam, FaSearch, FaDownload, FaTimes, FaServer, FaInfoCircle } from 'react-icons/fa';
import { API, authHeaders } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import { useGlobalData } from '../context/GlobalDataContext';

export default function SteamGamesPage() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const globalData = useGlobalData();

    const [games, setGames] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [installing, setInstalling] = useState(null);
    const [activeCategory, setActiveCategory] = useState('All');

    // Install Modal State
    const [selectedGame, setSelectedGame] = useState(null);
    const [serverName, setServerName] = useState('');
    const [hostPort, setHostPort] = useState('');
    const [envVars, setEnvVars] = useState({});

    useEffect(() => {
        fetchGames();
    }, []);

    const fetchGames = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API}/steam/games?include_all=true`, {
                headers: authHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                // Filter out Hytale as it has its own tab
                setGames(data.games.filter(g => g.slug !== 'hytale') || []);
            }
        } catch (err) {
            console.error(err);
            showToast('error', 'Failed to load Steam games');
        } finally {
            setLoading(false);
        }
    };

    const handleInstallClick = (game) => {
        setSelectedGame(game);
        setServerName(`${game.default_name || game.slug}-server`);
        setHostPort('');
        // Initialize env vars with defaults
        const initialEnv = {};
        Object.entries(game.env || {}).forEach(([k, v]) => {
            initialEnv[k] = v;
        });
        setEnvVars(initialEnv);
    };

    const handleInstallSubmit = async (e) => {
        e.preventDefault();
        if (!serverName) return;

        setInstalling(true);
        try {
            const payload = {
                game: selectedGame.slug,
                name: serverName,
                host_port: hostPort ? parseInt(hostPort) : null,
                env: envVars
            };

            const res = await fetch(`${API}/steam/install`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...authHeaders()
                },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }

            showToast('success', `Server ${serverName} is being installed!`);

            // Close modal
            setSelectedGame(null);

            // Refresh global server list if possible
            if (globalData && globalData.__refreshServers) {
                globalData.__refreshServers();
            }

            // Navigate to servers page
            navigate('/servers');
        } catch (err) {
            showToast('error', `Installation failed: ${err.message}`);
        } finally {
            setInstalling(false);
        }
    };

    const filteredGames = games.filter(g =>
        g.name.toLowerCase().includes(search.toLowerCase()) ||
        g.slug.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-white flex items-center gap-3">
                        <FaSteam className="text-blue-400" />
                        Steam Games
                    </h1>
                    <p className="text-white/60 mt-2">
                        Install dedicated servers for your favorite Steam games.
                    </p>
                </div>

                <div className="relative">
                    <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
                    <input
                        type="text"
                        placeholder={t('steamGames.searchGames')}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:outline-none focus:border-brand-500 w-full md:w-64"
                    />
                </div>
            </div>

            {/* Category Filter Buttons */}
            <div className="flex flex-wrap gap-2 mb-8">
                <button
                    onClick={() => setActiveCategory('All')}
                    className={`px-4 py-2 rounded-lg font-medium transition-all ${activeCategory === 'All'
                        ? 'bg-brand-600 text-white shadow-lg shadow-brand-500/20'
                        : 'bg-white/5 text-white/60 hover:bg-white/10 hover:text-white'
                        }`}
                >
                    All Games
                </button>
                {(() => {
                    const allCategories = ['Survival', 'Sandbox', 'Shooter', 'Simulation', 'Racing', 'Action', 'Strategy', 'Other'];
                    // Only show categories that have games
                    const availableCategories = allCategories.filter(cat =>
                        games.some(g => (g.category || 'Other') === cat)
                    );

                    return availableCategories.map(cat => (
                        <button
                            key={cat}
                            onClick={() => setActiveCategory(cat)}
                            className={`px-4 py-2 rounded-lg font-medium transition-all ${activeCategory === cat
                                ? 'bg-brand-600 text-white shadow-lg shadow-brand-500/20'
                                : 'bg-white/5 text-white/60 hover:bg-white/10 hover:text-white'
                                }`}
                        >
                            {cat}
                        </button>
                    ));
                })()}
            </div>

            {loading ? (
                <div className="flex justify-center py-20">
                    <div className="animate-spin w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full" />
                </div>
            ) : filteredGames.length === 0 ? (
                <div className="text-center py-20 text-white/50">
                    No games found matching "{search}"
                </div>
            ) : (
                <div className="space-y-12">
                    {activeCategory === 'All' ? (
                        // Grouped View for "All"
                        (() => {
                            const grouped = filteredGames.reduce((acc, game) => {
                                const cat = game.category || 'Other';
                                if (!acc[cat]) acc[cat] = [];
                                acc[cat].push(game);
                                return acc;
                            }, {});

                            const categories = Object.keys(grouped).sort((a, b) => {
                                const precedence = ['Survival', 'Sandbox', 'Shooter', 'Simulation', 'Racing', 'Action', 'Strategy', 'Other'];
                                const idxA = precedence.indexOf(a);
                                const idxB = precedence.indexOf(b);

                                if (idxA !== -1 && idxB !== -1) return idxA - idxB;
                                if (idxA !== -1) return -1;
                                if (idxB !== -1) return 1;

                                return a.localeCompare(b);
                            });

                            return categories.map(category => (
                                <div key={category}>
                                    <h2 className="text-2xl font-bold text-white mb-6 pl-3 border-l-4 border-brand-500">
                                        {category} Games
                                    </h2>
                                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                                        {grouped[category].map(game => (
                                            <GameTile key={game.slug} game={game} onInstall={handleInstallClick} />
                                        ))}
                                    </div>
                                </div>
                            ));
                        })()
                    ) : (
                        // Flat View for Specific Category
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                            {filteredGames
                                .filter(g => (g.category || 'Other') === activeCategory)
                                .map(game => (
                                    <GameTile key={game.slug} game={game} onInstall={handleInstallClick} />
                                ))}
                        </div>
                    )}
                </div>
            )}

            {/* Install Modal */}
            {selectedGame && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
                    <div className="bg-gray-900 border border-white/10 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
                        <form onSubmit={handleInstallSubmit}>
                            <div className="p-6 border-b border-white/10 flex items-center justify-between sticky top-0 bg-gray-900 z-10">
                                <h3 className="text-xl font-bold text-white">
                                    Install {selectedGame.name}
                                </h3>
                                <button
                                    type="button"
                                    onClick={() => setSelectedGame(null)}
                                    className="text-white/60 hover:text-white transition-colors"
                                >
                                    <FaTimes />
                                </button>
                            </div>

                            <div className="p-6 space-y-6">
                                <div>
                                    <label className="block text-sm font-medium text-white/70 mb-2">
                                        {t('steamGames.serverName')}
                                    </label>
                                    <input
                                        type="text"
                                        required
                                        value={serverName}
                                        onChange={(e) => setServerName(e.target.value)}
                                        className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                                        placeholder="my-server"
                                    />
                                    <p className="text-xs text-white/40 mt-1">
                                        Unique identifier for this server
                                    </p>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-white/70 mb-2">
                                        {t('steamGames.hostPort')}
                                    </label>
                                    <input
                                        type="number"
                                        value={hostPort}
                                        onChange={(e) => setHostPort(e.target.value)}
                                        className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                                        placeholder={t('steamGames.autoAssign')}
                                    />
                                    <p className="text-xs text-white/40 mt-1">
                                        Correct port mapping will be handled automatically if left blank.
                                    </p>
                                </div>

                                {Object.keys(envVars).length > 0 && (
                                    <div className="space-y-4 pt-4 border-t border-white/10">
                                        <h4 className="font-medium text-white">{t('steamGames.envVars')}</h4>
                                        {Object.entries(envVars).map(([key, value]) => (
                                            <div key={key}>
                                                <label className="block text-xs font-mono text-white/60 mb-1">
                                                    {key}
                                                </label>
                                                <input
                                                    type="text"
                                                    value={value}
                                                    onChange={(e) => setEnvVars(prev => ({ ...prev, [key]: e.target.value }))}
                                                    className="w-full px-3 py-1.5 bg-white/5 border border-white/10 rounded text-sm text-white font-mono focus:outline-none focus:border-brand-500"
                                                />
                                            </div>
                                        ))}
                                    </div>
                                )}

                                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4 flex items-start gap-3">
                                    <FaInfoCircle className="text-blue-400 mt-0.5 flex-shrink-0" />
                                    <div className="text-sm text-white/80">
                                        <p className="font-semibold text-blue-300 mb-1">Before you start:</p>
                                        <ul className="list-disc list-inside space-y-1 text-xs">
                                            <li>The first startup may take several minutes to download game files.</li>
                                            <li>Check the console logs if the server doesn't appear immediately.</li>
                                        </ul>
                                    </div>
                                </div>
                            </div>

                            <div className="p-6 border-t border-white/10 bg-black/20 sticky bottom-0 flex justify-end gap-3 z-10">
                                <button
                                    type="button"
                                    onClick={() => setSelectedGame(null)}
                                    className="px-4 py-2 text-white/70 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={installing}
                                    className="px-6 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg font-bold shadow-lg shadow-brand-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                                >
                                    {installing ? (
                                        <>
                                            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                            Creating...
                                        </>
                                    ) : (
                                        <>
                                            <FaDownload />
                                            Install Server
                                        </>
                                    )}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

// Get Steam CDN image URL from app ID
function getSteamImageUrl(appid, type = 'header') {
    if (!appid) return null;
    // Steam CDN image types:
    // header: 460x215 - good for cards/tiles
    // capsule_231x87: 231x87 - small capsule
    // library_600x900: 600x900 - vertical library art
    // library_hero: 1920x620 - horizontal hero banner
    const imageTypes = {
        header: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg`,
        capsule: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/capsule_231x87.jpg`,
        library: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/library_600x900.jpg`,
        hero: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/library_hero.jpg`,
    };
    return imageTypes[type] || imageTypes.header;
}

// Generate a consistent gradient based on game name
function getGameGradient(name) {
    const gradients = [
        'from-blue-600 to-purple-700',
        'from-emerald-600 to-teal-700',
        'from-orange-500 to-red-600',
        'from-pink-500 to-rose-600',
        'from-violet-600 to-indigo-700',
        'from-cyan-500 to-blue-600',
        'from-amber-500 to-orange-600',
        'from-fuchsia-500 to-purple-600',
        'from-lime-500 to-green-600',
        'from-sky-500 to-indigo-600',
    ];
    // Simple hash based on name
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    return gradients[Math.abs(hash) % gradients.length];
}

// Get initials from game name (max 2 chars)
function getGameInitials(name) {
    const words = name.split(/\s+/).filter(w => w.length > 0);
    if (words.length >= 2) {
        return (words[0][0] + words[1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
}

function GameTile({ game, onInstall }) {
    const gradient = getGameGradient(game.name);
    const initials = getGameInitials(game.name);
    // Use steam_appid to generate URL, or fall back to game_image if provided
    const steamImageUrl = getSteamImageUrl(game.steam_appid) || game.game_image;
    const [imageLoaded, setImageLoaded] = useState(false);
    const [imageError, setImageError] = useState(false);

    return (
        <div
            onClick={() => onInstall(game)}
            className="group cursor-pointer flex flex-col"
        >
            {/* Game Image/Placeholder */}
            <div className={`relative aspect-[4/3] rounded-xl overflow-hidden shadow-lg group-hover:shadow-xl group-hover:shadow-brand-500/20 transition-all duration-300 group-hover:scale-[1.03] ${!steamImageUrl || imageError ? `bg-gradient-to-br ${gradient}` : 'bg-gray-800'}`}>
                {/* Steam Image */}
                {steamImageUrl && !imageError && (
                    <img
                        src={steamImageUrl}
                        alt={game.name}
                        className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-300 ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                        onLoad={() => setImageLoaded(true)}
                        onError={() => setImageError(true)}
                    />
                )}

                {/* Fallback gradient background with initials (shown when no image or loading) */}
                {(!steamImageUrl || imageError || !imageLoaded) && (
                    <>
                        {/* Decorative overlay pattern */}
                        <div className="absolute inset-0 opacity-20">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -translate-y-1/2 translate-x-1/2" />
                            <div className="absolute bottom-0 left-0 w-24 h-24 bg-black/20 rounded-full translate-y-1/2 -translate-x-1/2" />
                        </div>

                        {/* Game Initials */}
                        <div className="absolute inset-0 flex items-center justify-center">
                            <span className="text-4xl font-black text-white/90 tracking-wider drop-shadow-lg">
                                {initials}
                            </span>
                        </div>
                    </>
                )}

                {/* Dark overlay for better text contrast on images */}
                {steamImageUrl && imageLoaded && !imageError && (
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
                )}

                {/* Hover overlay with install hint */}
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all duration-300 flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <div className="bg-white/20 backdrop-blur-sm rounded-full p-3 transform scale-75 group-hover:scale-100 transition-transform duration-300">
                        <FaDownload className="text-white text-xl" />
                    </div>
                </div>
            </div>

            {/* Game Name */}
            <h3 className="mt-3 text-sm font-semibold text-white text-center line-clamp-2 group-hover:text-brand-400 transition-colors">
                {game.name}
            </h3>
        </div>
    );
}
