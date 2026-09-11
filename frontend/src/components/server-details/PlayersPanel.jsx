import React, { useEffect, useState, useRef } from 'react';
import { useTranslation } from '../../i18n';
import { API, authHeaders } from '../../context/AppContext';
import PlayerAvatar from '../ui/PlayerAvatar';
/* eslint-disable */
export default function PlayersPanel({ serverId, serverName, focusPlayer = '', onFocusConsumed }) {
  const { t } = useTranslation();
  // Defensive: normalize serverName to avoid ReferenceError if caller omits prop
  const sName = serverName || '';
  const [online, setOnline] = useState([]);
  const [onlineCount, setOnlineCount] = useState(0);
  const [offline, setOffline] = useState([]);
  const [method, setMethod] = useState('');
  const [errorDetail, setErrorDetail] = useState('');
  const [loading, setLoading] = useState(true);
  const [playerName, setPlayerName] = useState('');
  const [reason, setReason] = useState('');
  const [rconHintDismissed, setRconHintDismissed] = useState(() => {
    try { return localStorage.getItem('rcon_hint_dismissed') === '1'; } catch { return false; }
  });
  const avatarCache = useRef({});
  const [avatarUrls, setAvatarUrls] = useState({});
  const highlightRefs = useRef({});
  const [highlightedPlayer, setHighlightedPlayer] = useState('');

  async function fetchRoster() {
    try {
      if (!sName) { setOnline([]); setOffline([]); setMethod('missing'); setErrorDetail(''); return; }
      const r = await fetch(`${API}/players/${encodeURIComponent(sName)}/roster`, { headers: authHeaders() });
      if (!r.ok) {
        let errorMessage = `HTTP ${r.status}`;
        try {
          const errorData = await r.json();
          errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch {}
        // Include URL for easier debugging (helps when API prefix is wrong)
        errorMessage = `${errorMessage} — ${API}/players/${encodeURIComponent(sName)}/roster`;
        setOnline([]);
        setOffline([]);
        setMethod('error');
        setErrorDetail(errorMessage);
        console.error('Failed to fetch players:', errorMessage);
        return;
      }
      const d = await r.json();
      if (d && typeof d === 'object') {
        // Backend roster sends players/offline entries as plain name strings;
        // tolerate object shapes ({name, uuid}) from older builds too.
        const toPlayer = (p) => (typeof p === 'string' ? { name: p } : { name: p && p.name, uuid: p && p.uuid });
        const toOffline = (o) => (typeof o === 'string' ? { name: o } : { name: o && o.name, last_seen: o && o.last_seen });
        const isBad = (name) => !name || String(name).toLowerCase() === 'client' || String(name).trim() === '';
        const rawPlayers = Array.isArray(d.players)
          ? d.players
          : (Array.isArray(d.online) ? d.online : []);
        const normalizedOnline = rawPlayers.map(toPlayer).filter(p => !isBad(p.name));
        const normalizedOffline = (Array.isArray(d.offline) ? d.offline : []).map(toOffline).filter(o => !isBad(o.name));
        setOnline(normalizedOnline);
        setOnlineCount(typeof d.count === 'number' ? d.count : normalizedOnline.length);
        setOffline(normalizedOffline);
        setMethod(d.method || 'unknown');
        setErrorDetail('');
        // Debug: log the effective method so operators can tell if fallback worked
        if (d.method) console.debug(`roster method=${d.method} online=${normalizedOnline.length} offline=${normalizedOffline.length}`);
      }
    } catch (e) {
      setOnline([]);
      setOffline([]);
      setMethod('error');
      setErrorDetail(e && e.message ? e.message : String(e));
      console.error('Error fetching players:', e);
    } finally {
      setLoading(false);
    }
  }

  // Serialized roster poll: never overlap requests, pause when tab hidden.
  useEffect(() => {
    let active = true;
    let timer = null;
    async function load() {
      if (!active) return;
      if (typeof document !== 'undefined' && document.hidden) {
        timer = setTimeout(load, 3000);
        return;
      }
      try {
        await fetchRoster();
      } finally {
        if (active) timer = setTimeout(load, 3000);
      }
    }
    load();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [serverId, serverName]);

  async function getAvatar(player) {
    if (!player) return null;
    if (avatarCache.current[player]) return avatarCache.current[player];
    // Use mc-heads.net which resolves by username directly (no UUID lookup needed)
    const url = `https://mc-heads.net/avatar/${encodeURIComponent(player)}/64`;
    avatarCache.current[player] = url;
    setAvatarUrls(prev => ({ ...prev, [player]: url }));
    return url;
  }

  useEffect(() => {
    let canceled = false;
    (async () => {
      const all = [...online.map(p => p.name), ...offline.map(o => o.name)].filter(Boolean);
      for (const p of all) {
        if (canceled) return;
        if (!avatarCache.current[p]) {
          await getAvatar(p).catch(() => null);
        }
      }
    })();
    return () => { canceled = true; };
  }, [online, offline]);

  async function call(endpoint, method = 'POST', body = null) {
    if (!sName) return;
    await fetch(`${API}/players/${encodeURIComponent(sName)}/${endpoint}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json', ...authHeaders() } : authHeaders(),
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async function postAction(action, player, reasonArg = '') {
    try {
      if (!sName) return;
      await fetch(`${API}/players/${encodeURIComponent(sName)}/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ player_name: player, action_type: action, reason: reasonArg })
      });
      await fetchRoster();
    } catch (e) {
      console.error('action error', e);
    }
  }

  async function deop(player) {
    try {
      if (!sName) return;
      await fetch(`${API}/players/${encodeURIComponent(sName)}/op/${encodeURIComponent(player)}`, { method: 'DELETE', headers: authHeaders() });
      await fetchRoster();
    } catch (e) { console.error(e); }
  }

  async function sendTell(player) {
    const msg = window.prompt(`Message to ${player}`);
    if (!msg) return;
    try {
      await fetch(`${API}/servers/${serverId}/command`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ command: `tell ${player} ${msg}` }) });
    } catch (e) { console.error(e); }
  }

  useEffect(() => {
    highlightRefs.current = {};
  }, [online, offline]);

  useEffect(() => {
    if (!focusPlayer) return;
    const key = focusPlayer.toString().toLowerCase();
    if (!key) return;
    setHighlightedPlayer(key);
    const focusTick = setTimeout(() => {
      const node = highlightRefs.current[key];
      if (node && node.scrollIntoView) {
        try { node.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) { }
      }
      if (typeof onFocusConsumed === 'function') {
        onFocusConsumed();
      }
    }, 120);
    const clearTick = setTimeout(() => {
      setHighlightedPlayer('');
    }, 2400);
    return () => {
      clearTimeout(focusTick);
      clearTimeout(clearTick);
    };
}, [focusPlayer, online, offline, onFocusConsumed]);
 
  return (
    <div className="p-4 bg-black/20 rounded-lg space-y-4" style={{ minHeight: 300 }}>
      <div className="flex items-center justify-between">
        <div className="text-sm text-white/70">{t('playerManagement.title')}</div>
        <div className="text-xs text-white/50">Updated every 3s</div>
      </div>
 
      {method === 'missing' && (
        <div className="bg-yellow-500/20 border border-yellow-500/30 text-yellow-300 p-3 rounded-lg text-sm">
          No server selected. Open a server first.
        </div>
      )}

      {method === 'server-not-found' && (
        <div className="bg-red-500/20 border border-red-500/30 text-red-300 p-3 rounded-lg text-sm">
          Server “{sName}” not found. Check the server name / ID — it must match the container or directory name exactly.
          <button onClick={fetchRoster} className="ml-2 underline hover:text-white">Retry</button>
        </div>
      )}

      {method === 'server-stopped' && (
        <div className="bg-yellow-500/20 border border-yellow-500/30 text-yellow-300 p-3 rounded-lg text-sm">
          Server is stopped. Start the server to see live players; offline history is shown below when available.
        </div>
      )}

      {method === 'error' && (
        <div className="bg-red-500/20 border border-red-500/30 text-red-300 p-3 rounded-lg text-sm space-y-2">
          <div>Failed to load players. {errorDetail ? errorDetail : 'Check server RCON configuration.'}</div>
          {errorDetail && <div className="text-xs opacity-80 break-all">Detail: {errorDetail}</div>}
          <div className="text-xs opacity-70">Server: “{sName}” · Try enabling RCON (enable-rcon=true + rcon.password) or wait for the log fallback.</div>
          <button onClick={() => { setLoading(true); fetchRoster(); }} className="mt-2 px-3 py-1.5 rounded bg-white/10 hover:bg-white/20 text-white text-xs">Retry</button>
        </div>
      )}

      {method === 'rcon-no-password' && (
        <div className="bg-yellow-500/20 border border-yellow-500/30 text-yellow-300 p-4 rounded-lg">
          <p className="font-medium">⚠️ RCON is disabled for this server.</p>
          <p className="text-sm mt-1">To enable player list, enable RCON in server.properties:</p>
          <pre className="text-xs bg-gray-900 p-2 rounded mt-2 whitespace-pre-wrap">
enable-rcon=true
rcon.password=your_password
rcon.port=25575
          </pre>
          <p className="text-xs text-yellow-400 mt-2">
            Or restart the server after enabling RCON to use the mcstatus fallback.
          </p>
          <button onClick={() => { setLoading(true); fetchRoster(); }} className="mt-2 px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-white text-xs">Retry</button>
        </div>
      )}

      {method === 'mcstatus' && (
        <div className="bg-green-500/20 border border-green-500/30 text-green-300 p-3 rounded-lg text-sm">
          Showing players via server status query (mcstatus fallback).
        </div>
      )}

      {method === 'docker_logs' && (
        <div className="bg-blue-500/20 border border-blue-500/30 text-blue-300 p-3 rounded-lg text-sm">
          Showing players from Docker container logs (RCON/mcstatus unavailable).
        </div>
      )}

      {method === 'log_parse' && (
        <div className="bg-blue-500/20 border border-blue-500/30 text-blue-300 p-3 rounded-lg text-sm">
          Showing players from server logs (filesystem).
        </div>
      )}

      {method === 'rcon-props' && (
        <div className="bg-green-500/20 border border-green-500/30 text-green-300 p-3 rounded-lg text-sm">
          Showing players via RCON (server.properties).
        </div>
      )}

      {method === 'mcstatus-failed' && (
        <div className="bg-red-500/20 border border-red-500/30 text-red-300 p-3 rounded-lg text-sm space-y-2">
          <div>Both RCON and server status query failed. Check if server is running and port 25565 is accessible.</div>
          <div className="text-xs opacity-70">No Docker log data either. The next player join/leave will populate the list.</div>
          <button onClick={() => { setLoading(true); fetchRoster(); }} className="mt-2 px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-white text-xs">Retry</button>
        </div>
      )}

      {method === 'unknown' && !loading && (
        <div className="bg-white/5 border border-white/10 text-white/60 p-3 rounded-lg text-sm">
          Player source unknown — showing best available data.
        </div>
      )}

      <div>
        <div className="text-xs text-white/60 mb-2">{t('playerManagement.onlinePlayers')} {onlineCount > 0 ? `(${onlineCount})` : ''} {method ? ` — ${method}` : ''}</div>
        {loading ? <div className="text-xs text-white/50">Loading…</div> : null}

        {online.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {online.map((p) => {
              const key = p.name.toLowerCase();
              const isHighlighted = highlightedPlayer && highlightedPlayer === key;
              return (
                <div
                  key={p.uuid || p.name}
                  ref={(el) => { if (el) highlightRefs.current[key] = el; }}
                  className={`bg-white/5 border border-white/10 rounded-lg p-3 space-y-3 hover:shadow-lg transition ${isHighlighted ? 'ring-2 ring-brand-500/60 animate-pulse-glow' : ''}`}
                >
                  <div className="flex items-center gap-3">
                    <PlayerAvatar uuid={p.uuid} name={p.name} size={40} />
                    <div className="min-w-0">
                      <div className="text-sm text-white font-semibold truncate">{p.name}</div>
                      <div className="text-xs text-green-400">online</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <button title={t('playerManagement.message')} onClick={() => sendTell(p.name)} className="px-2 py-1 bg-sky-500/20 border border-sky-500/30 rounded text-xs text-sky-300 hover:bg-sky-500/30 transition">{t('playerManagement.message')}</button>
                    <button title={t('playerManagement.op')} onClick={() => postAction('op', p.name)} className="px-2 py-1 bg-green-500/20 border border-green-500/30 rounded text-xs text-green-300 hover:bg-green-500/30 transition">OP</button>
                    <button title={t('playerManagement.deop')} onClick={() => deop(p.name)} className="px-2 py-1 bg-orange-500/20 border border-orange-500/30 rounded text-xs text-orange-300 hover:bg-orange-500/30 transition">DEOP</button>
                    <button title={t('playerManagement.kick')} onClick={() => postAction('kick', p.name)} className="px-2 py-1 bg-yellow-600 rounded text-xs text-white hover:bg-yellow-500 transition">{t('playerManagement.kick')}</button>
                    <button title={t('playerManagement.ban')} onClick={() => postAction('ban', p.name)} className="px-2 py-1 bg-red-600 rounded text-xs text-white hover:bg-red-500 transition">{t('playerManagement.ban')}</button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-xs text-white/50">No players online.</div>
        )}
      </div>

      <div className="pt-4">
        <div className="text-xs text-white/60 mb-2">{t('playerManagement.offlinePlayers')} {offline.length ? `(${offline.length})` : ''}</div>
        {offline.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {offline.map((o) => {
              const key = o.name.toLowerCase();
              const isHighlighted = highlightedPlayer && highlightedPlayer === key;
              const avatar = avatarUrls[o.name];
              return (
                <div
                  key={o.name}
                  ref={(el) => { if (el) highlightRefs.current[key] = el; }}
                  className={`bg-white/3 border border-white/6 rounded-lg p-3 flex items-center justify-between opacity-90 ${isHighlighted ? 'ring-2 ring-brand-500/60 animate-pulse-glow' : ''}`}
                >
                  <div className="flex items-center gap-3">
                    {avatar ? (
                      <img src={avatar} alt={o.name} className="w-10 h-10 rounded" />
                    ) : (
                      <div className="w-10 h-10 rounded bg-gray-600 flex items-center justify-center text-sm font-semibold text-white flex-shrink-0">{o.name.slice(0, 1).toUpperCase()}</div>
                    )}
                    <div>
                      <div className="text-sm text-white">{o.name}</div>
                      <div className="text-xs text-white/50">{o.last_seen ? new Date(o.last_seen * 1000).toLocaleString() : 'seen recently'}</div>
                    </div>
                  </div>
                  <div className="text-xs text-white/40">offline</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-xs text-white/50">No known offline players yet.</div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <input className="rounded bg-gray-800 border border-white/20 px-3 py-2 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500" placeholder={t('playerManagement.playerName')} value={playerName} onChange={e => setPlayerName(e.target.value)} />
        <input className="rounded bg-gray-800 border border-white/20 px-3 py-2 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500" placeholder={t('playerManagement.reason')} value={reason} onChange={e => setReason(e.target.value)} />
        <div className="flex items-center gap-2">
          <button onClick={() => call('whitelist', 'POST', { player_name: playerName, reason })} className="rounded bg-white/10 hover:bg-white/20 border border-white/10 px-3 py-2 text-sm text-white/80">Whitelist</button>
          <button onClick={() => call('ban', 'POST', { player_name: playerName, reason })} className="rounded bg-red-600 hover:bg-red-500 px-3 py-2 text-sm">Ban</button>
          <button onClick={() => call('kick', 'POST', { player_name: playerName, reason })} className="rounded bg-yellow-600 hover:bg-yellow-500 px-3 py-2 text-sm">Kick</button>
          <button onClick={() => call('op', 'POST', { player_name: playerName, reason })} className="rounded bg-green-600 hover:bg-green-500 px-3 py-2 text-sm">OP</button>
        </div>
      </div>
    </div>
  );
}
