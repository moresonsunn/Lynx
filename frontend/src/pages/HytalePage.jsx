import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { FaDungeon, FaDownload, FaInfoCircle, FaExclamationTriangle } from 'react-icons/fa';
import { API, authHeaders } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import { useGlobalData } from '../context/GlobalDataContext';

export default function HytalePage() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const globalData = useGlobalData();

    const [loading, setLoading] = useState(true);
    const [hytaleData, setHytaleData] = useState(null);
    const [installing, setInstalling] = useState(false);

    // Form State
    const [serverName, setServerName] = useState('hytale-server');
    const [envVars, setEnvVars] = useState({});

    useEffect(() => {
        fetchHytaleData();
    }, []);

    const fetchHytaleData = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API}/steam/games?include_all=true`, {
                headers: authHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                const found = data.games.find(g => g.slug === 'hytale');
                if (found) {
                    setHytaleData(found);
                    const initialEnv = {};
                    Object.entries(found.env || {}).forEach(([k, v]) => {
                        initialEnv[k] = v;
                    });
                    setEnvVars(initialEnv);
                }
            }
        } catch (err) {
            console.error(err);
            showToast('error', 'Failed to load Hytale configuration');
        } finally {
            setLoading(false);
        }
    };

    const handleInstallSubmit = async (e) => {
        e.preventDefault();
        if (!serverName) return;

        setInstalling(true);
        try {
            const payload = {
                game: 'hytale',
                name: serverName,
                host_port: null, // Auto-assign
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

            showToast('success', `Hytale server ${serverName} is being created!`);

            // Refresh global server list
            if (globalData && globalData.__refreshServers) {
                globalData.__refreshServers();
            }

            navigate('/servers');
        } catch (err) {
            showToast('error', `Installation failed: ${err.message}`);
        } finally {
            setInstalling(false);
        }
    };

    if (loading) {
        return (
            <div className="flex justify-center items-center h-[50vh]">
                <div className="animate-spin w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full" />
            </div>
        );
    }

    if (!hytaleData) {
        return (
            <div className="p-10 text-center">
                <h2 className="text-2xl font-bold text-white mb-2">Hytale Configuration Not Found</h2>
                <p className="text-white/60">The backend does not have Hytale configured in steam_games.py.</p>
            </div>
        );
    }

    return (
        <div className="p-6 max-w-4xl mx-auto">
            {/* Hero Header */}
            <div className="relative rounded-2xl overflow-hidden mb-8 border border-white/10 bg-gradient-to-br from-purple-900/50 to-blue-900/50 shadow-2xl">
                <div className="absolute inset-0 bg-[url('https://cdn.hytale.com/5ed66ef25965a30018a38c20_Hytale_Orbis_Art_1.jpg')] bg-cover bg-center opacity-30 mix-blend-overlay"></div>
                <div className="relative p-10 flex flex-col items-center text-center">
                    <div className="w-20 h-20 bg-brand-500 rounded-2xl flex items-center justify-center text-4xl text-white shadow-lg shadow-brand-500/30 mb-6 rotate-3 transform hover:rotate-6 transition-transform">
                        <FaDungeon />
                    </div>
                    <h1 className="text-4xl md:text-5xl font-extrabold text-white mb-4 tracking-tight">
                        Create Hytale Server
                    </h1>
                    <p className="text-lg text-blue-100/80 max-w-2xl">
                        Deploy your own Hytale world instantly. Manage configuration, backups, and more through Lynx.
                    </p>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Left Column: Form */}
                <div className="lg:col-span-2">
                    <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                        <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                            <FaDungeon className="text-brand-400" />
                            {t('hytale.serverConfiguration')}
                        </h2>

                        <form onSubmit={handleInstallSubmit} className="space-y-6">
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    {t('hytale.serverName')}
                                </label>
                                <input
                                    type="text"
                                    required
                                    value={serverName}
                                    onChange={(e) => setServerName(e.target.value)}
                                    className="w-full px-4 py-3 bg-black/20 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500 transition-colors"
                                    placeholder="my-hytale-world"
                                />
                            </div>

                            {Object.keys(envVars).length > 0 && (
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between">
                                        <h3 className="text-sm font-semibold text-white/90">Environment Settings</h3>
                                        <span className="text-xs text-white/40">Advanced</span>
                                    </div>
                                    <div className="bg-black/20 rounded-lg p-4 space-y-4 border border-white/5">
                                        {Object.entries(envVars).map(([key, value]) => (
                                            <div key={key}>
                                                <label className="block text-xs font-mono text-white/60 mb-1">
                                                    {key}
                                                </label>
                                                <input
                                                    type="text"
                                                    value={value}
                                                    onChange={(e) => setEnvVars(prev => ({ ...prev, [key]: e.target.value }))}
                                                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm text-white font-mono focus:outline-none focus:border-brand-500"
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div className="pt-4">
                                <button
                                    type="submit"
                                    disabled={installing}
                                    className="w-full py-4 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-bold text-lg shadow-xl shadow-brand-500/20 transition-all transform hover:-translate-y-1 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none flex items-center justify-center gap-3"
                                >
                                    {installing ? (
                                        <>
                                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                            Deploying Solution...
                                        </>
                                    ) : (
                                        <>
                                            <FaDownload />
                                            Deploy Server
                                        </>
                                    )}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>

                {/* Right Column: Info */}
                <div className="space-y-6">
                    <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-6">
                        <h3 className="text-lg font-bold text-blue-100 mb-2 flex items-center gap-2">
                            <FaInfoCircle />
                            About Hytale Servers
                        </h3>
                        <p className="text-sm text-blue-200/70 leading-relaxed mb-4">
                            Hytale dedicated servers allow you to host persistent worlds for you and your friends.
                        </p>
                        <div className="text-xs text-blue-200/50 font-mono bg-black/20 p-3 rounded">
                            Port: 25565 (UDP/TCP)<br />
                            RAM: 4GB Recommended
                        </div>
                    </div>

                    <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-xl p-6">
                        <h3 className="text-lg font-bold text-yellow-100 mb-2 flex items-center gap-2">
                            <FaExclamationTriangle />
                            License Required
                        </h3>
                        <p className="text-sm text-yellow-200/70 leading-relaxed">
                            Ensure you have a valid Hytale license. The server may require authentication on first startup. Check the console logs for any verification links or codes.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
