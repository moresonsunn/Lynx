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
                        placeholder="Search games..."
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
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                                        {grouped[category].map(game => (
                                            <GameCard key={game.slug} game={game} onInstall={handleInstallClick} />
                                        ))}
                                    </div>
                                </div>
                            ));
                        })()
                    ) : (
                        // Flat View for Specific Category
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            {filteredGames
                                .filter(g => (g.category || 'Other') === activeCategory)
                                .map(game => (
                                    <GameCard key={game.slug} game={game} onInstall={handleInstallClick} />
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
                                        Server Name
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
                                        Host Port (Optional)
                                    </label>
                                    <input
                                        type="number"
                                        value={hostPort}
                                        onChange={(e) => setHostPort(e.target.value)}
                                        className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                                        placeholder="Auto-assign"
                                    />
                                    <p className="text-xs text-white/40 mt-1">
                                        Correct port mapping will be handled automatically if left blank.
                                    </p>
                                </div>

                                {Object.keys(envVars).length > 0 && (
                                    <div className="space-y-4 pt-4 border-t border-white/10">
                                        <h4 className="font-medium text-white">Environment Variables</h4>
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

function GameCard({ game, onInstall }) {
    return (
        <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden hover:bg-white/10 transition-colors flex flex-col">
            <div className="p-6 flex-1">
                <div className="flex items-start justify-between mb-4">
                    <div className="w-12 h-12 bg-blue-500/20 rounded-lg flex items-center justify-center text-2xl text-blue-400">
                        <FaServer />
                    </div>
                    <div className="flex gap-2">
                        {game.category && (
                            <span className="text-xs px-2 py-1 bg-white/10 rounded text-white/60 font-mono">
                                {game.category}
                            </span>
                        )}
                        {game.image && (
                            <span className="text-xs px-2 py-1 bg-white/10 rounded text-white/60 font-mono">
                                Docker
                            </span>
                        )}
                    </div>
                </div>
                <h3 className="text-xl font-bold text-white mb-2">{game.name}</h3>
                <p className="text-sm text-white/60 line-clamp-3">{game.summary}</p>

                {game.ports && game.ports.length > 0 && (
                    <div className="mt-4 text-xs text-white/40 font-mono">
                        Ports: {game.ports.map(p => `${p.container}/${p.protocol}`).join(', ')}
                    </div>
                )}
            </div>
            <div className="p-4 bg-black/20 border-t border-white/10">
                <button
                    onClick={() => onInstall(game)}
                    className="w-full py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
                >
                    <FaDownload />
                    Install Server
                </button>
            </div>
        </div>
    );
}
