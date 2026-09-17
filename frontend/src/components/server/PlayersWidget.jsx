import React, { useState, useEffect } from 'react';
import { FaUsers, FaUser, FaUserPlus, FaSync } from 'react-icons/fa';
import PlayerAvatar from '../ui/PlayerAvatar';
import { useFetch } from '../../hooks/useFetch';
import { useAuth } from '../../context/AuthContext';

const PlayersWidget = ({ serverName, serverId }) => {
  const { token } = useAuth();
  const [players, setPlayers] = useState([]);
  const [online, setOnline] = useState(0);
  const [max, setMax] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchPlayers = async () => {
    if (!serverName) return;

    try {
      setLoading(true);
      setError(null);

      const encodedName = encodeURIComponent(serverName);
      const response = await fetch(`/api/players/${encodedName}/roster`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        let errorMessage = `HTTP ${response.status}`;
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch {
          // Ignore
        }
        throw new Error(errorMessage);
      }

      const data = await response.json();

      // Roster sends plain name strings; tolerate {name, uuid} objects too.
      // UUID-looking fragments are parser garbage, never players.
      const isUuidish = (n) => /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(n)
        || (/^[0-9a-fA-F-]{4,36}$/.test(n) && n.includes('-'));
      const toPlayer = (p) => (typeof p === 'string' ? { name: p } : { name: p && p.name, uuid: p && p.uuid });
      const filtered = (Array.isArray(data.players) ? data.players : [])
        .map(toPlayer)
        .filter(p => p.name && p.name.toLowerCase() !== 'client' && !isUuidish(String(p.name).trim()));

      setPlayers(filtered);
      // Badge must match the tiles: trust the resolved list, not a stale count.
      setOnline(filtered.length > 0 ? filtered.length : (typeof data.count === 'number' ? data.count : 0));
      setMax(data.max || 0);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch players:', err);
      setError(err.message || 'Failed to load players');
      setPlayers([]);
      setOnline(0);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    let active = true;
    let timer = null;
    // Serialized: never overlap, pause when tab hidden
    async function loop() {
      if (!active) return;
      if (typeof document !== 'undefined' && document.hidden) {
        timer = setTimeout(loop, 30000);
        return;
      }
      try {
        await fetchPlayers();
      } finally {
        if (active) timer = setTimeout(loop, 30000);
      }
    }
    loop();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [serverName]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    fetchPlayers();
  };

  // Loading state
  if (loading) {
    return (
      <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center gap-2 text-gray-400">
          <FaUsers className="animate-pulse" />
          <span>Loading players...</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="bg-gray-800/50 rounded-lg p-4 border border-yellow-700/50">
        <div className="flex items-center gap-2 text-yellow-400">
          <FaUsers />
          <span className="font-medium">Could not load players</span>
        </div>
        <p className="text-sm text-gray-400 mt-1">{error}</p>
        <button
          onClick={handleRefresh}
          className="mt-2 text-sm text-blue-400 hover:text-blue-300 underline"
        >
          Retry
        </button>
        <div className="mt-2 p-2 bg-gray-900/50 rounded text-xs text-gray-500">
          <p>💡 Tip: Enable RCON for more reliable player list:</p>
          <pre className="mt-1 text-gray-400">
            enable-rcon=true{'\n'}
            rcon.password=your_password{'\n'}
            rcon.port=25575
          </pre>
        </div>
      </div>
    );
  }

  // No players online
  if (players.length === 0 && online === 0) {
    return (
      <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-gray-400">
            <FaUsers />
            <span>No players online</span>
          </div>
          <button
            onClick={handleRefresh}
            className="text-xs text-gray-500 hover:text-gray-300"
            disabled={isRefreshing}
          >
            {isRefreshing ? '⟳' : '⟳ Refresh'}
          </button>
        </div>
      </div>
    );
  }

  // Show player list
  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <FaUsers className="text-blue-400" />
          <span className="font-medium text-white">
            {online} / {max || '?'} online
          </span>
        </div>
        <button
          onClick={handleRefresh}
          className="text-xs text-gray-500 hover:text-gray-300"
          disabled={isRefreshing}
        >
          {isRefreshing ? '⟳' : '⟳ Refresh'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {players.map((player) => (
          <div
            key={player.uuid || player.name}
            className="flex items-center gap-2 bg-gray-700/50 px-3 py-1.5 rounded-full hover:bg-gray-700 transition-colors"
          >
            <PlayerAvatar uuid={player.uuid} name={player.name} size={24} />
            <span className="text-sm text-white">{player.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default PlayersWidget;