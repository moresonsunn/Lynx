import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../i18n';
import { API, authHeaders } from '../context/AppContext';
import { useGlobalData } from '../context/GlobalDataContext';
import {
  FaLayerGroup, FaPlus, FaTrash, FaPlay, FaStop, FaSyncAlt,
  FaDatabase, FaClone, FaExchangeAlt, FaSpinner, FaCheck,
  FaTimes, FaServer, FaCheckCircle, FaTimesCircle, FaChevronDown,
  FaChevronUp, FaEllipsisH, FaCopy, FaFolderOpen
} from 'react-icons/fa';

// ─── Shared Card ───────────────────────────────────────────

function Card({ title, description, icon: Icon, children, actions, className = '' }) {
  return (
    <div className={`bg-white/5 border border-white/10 rounded-xl p-6 ${className}`}>
      {title && (
        <div className="flex items-start justify-between gap-3 mb-5">
          <div className="flex items-start gap-3">
            <div className="p-2 bg-brand-500/20 rounded-lg">
              <Icon className="w-5 h-5 text-brand-400" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white">{title}</h3>
              {description && <p className="text-sm text-white/50 mt-0.5">{description}</p>}
            </div>
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

// ─── Server Groups Panel ───────────────────────────────────

function ServerGroupsPanel() {
  const globalData = useGlobalData();
  const servers = globalData?.servers || [];
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupDesc, setNewGroupDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [addServerGroup, setAddServerGroup] = useState(null);
  const [selectedServers, setSelectedServers] = useState([]);

  const fetchGroups = useCallback(async () => {
    try {
      const r = await fetch(`${API}/multi-server/groups`, { headers: authHeaders() });
      if (r.ok) setGroups(await r.json());
    } catch { }
    setLoading(false);
  }, []);

  useEffect(() => { fetchGroups(); }, [fetchGroups]);

  const createGroup = async () => {
    if (!newGroupName.trim()) return;
    setCreating(true);
    try {
      const r = await fetch(`${API}/multi-server/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: newGroupName.trim(), description: newGroupDesc.trim() || null }),
      });
      if (r.ok) {
        setNewGroupName('');
        setNewGroupDesc('');
        fetchGroups();
      }
    } catch { }
    setCreating(false);
  };

  const deleteGroup = async (id) => {
    try {
      await fetch(`${API}/multi-server/groups/${id}`, { method: 'DELETE', headers: authHeaders() });
      fetchGroups();
    } catch { }
  };

  const addServersToGroup = async (groupId) => {
    if (selectedServers.length === 0) return;
    try {
      await fetch(`${API}/multi-server/groups/${groupId}/servers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ server_names: selectedServers }),
      });
      setSelectedServers([]);
      setAddServerGroup(null);
      fetchGroups();
    } catch { }
  };

  const removeServerFromGroup = async (groupId, serverName) => {
    try {
      await fetch(`${API}/multi-server/groups/${groupId}/servers/${serverName}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      fetchGroups();
    } catch { }
  };

  return (
    <Card title="Server Groups" description="Organize servers into groups for bulk operations" icon={FaLayerGroup}>
      {/* Create Group */}
      <div className="flex gap-2 mb-5">
        <input
          value={newGroupName}
          onChange={e => setNewGroupName(e.target.value)}
          placeholder="Group name"
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm"
        />
        <input
          value={newGroupDesc}
          onChange={e => setNewGroupDesc(e.target.value)}
          placeholder="Description (optional)"
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm hidden md:block"
        />
        <button
          onClick={createGroup}
          disabled={creating || !newGroupName.trim()}
          className="px-4 py-2 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg text-sm hover:bg-brand-500/30 disabled:opacity-50 flex items-center gap-2"
        >
          {creating ? <FaSpinner className="animate-spin" /> : <FaPlus />} Create
        </button>
      </div>

      {/* Groups List */}
      {loading ? (
        <div className="text-white/40 text-center py-6"><FaSpinner className="animate-spin inline mr-2" />Loading…</div>
      ) : groups.length === 0 ? (
        <div className="text-white/40 text-center py-8 text-sm">No groups yet. Create one above to get started.</div>
      ) : (
        <div className="space-y-3">
          {groups.map(group => (
            <div key={group.id} className="bg-white/5 rounded-lg border border-white/10">
              {/* Header */}
              <div
                className="flex items-center justify-between p-4 cursor-pointer hover:bg-white/5 transition-colors rounded-t-lg"
                onClick={() => setExpanded(expanded === group.id ? null : group.id)}
              >
                <div className="flex items-center gap-3">
                  <FaLayerGroup className="text-brand-400" />
                  <div>
                    <div className="text-white font-medium">{group.name}</div>
                    {group.description && <div className="text-xs text-white/40">{group.description}</div>}
                  </div>
                  <span className="text-xs bg-white/10 text-white/50 px-2 py-0.5 rounded-full">
                    {group.members?.length || 0} servers
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={e => { e.stopPropagation(); deleteGroup(group.id); }}
                    className="p-2 text-red-400/60 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                  >
                    <FaTrash className="w-3.5 h-3.5" />
                  </button>
                  {expanded === group.id ? <FaChevronUp className="text-white/30" /> : <FaChevronDown className="text-white/30" />}
                </div>
              </div>

              {/* Expanded: Server list */}
              {expanded === group.id && (
                <div className="p-4 pt-0 border-t border-white/5">
                  {/* Members */}
                  {group.members?.length > 0 ? (
                    <div className="space-y-2 mb-3">
                      {group.members.map(m => (
                        <div key={m.server_name} className="flex items-center justify-between p-2 bg-black/20 rounded-lg">
                          <div className="flex items-center gap-2">
                            <FaServer className="text-white/40 w-3.5 h-3.5" />
                            <span className="text-sm text-white">{m.server_name}</span>
                          </div>
                          <button
                            onClick={() => removeServerFromGroup(group.id, m.server_name)}
                            className="text-xs text-red-400/60 hover:text-red-400 p-1"
                          >
                            <FaTimes />
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-white/30 text-sm py-3 text-center">No servers in this group.</div>
                  )}

                  {/* Add Server */}
                  {addServerGroup === group.id ? (
                    <div className="p-3 bg-brand-500/10 border border-brand-500/20 rounded-lg space-y-3">
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-40 overflow-y-auto">
                        {servers.map(s => {
                          const name = s.name || s.id;
                          const inGroup = group.members?.some(m => m.server_name === name);
                          return (
                            <label
                              key={name}
                              className={`flex items-center gap-2 p-2 rounded-lg text-sm cursor-pointer transition-colors ${
                                inGroup ? 'bg-white/5 text-white/30 cursor-not-allowed' :
                                selectedServers.includes(name) ? 'bg-brand-500/20 text-brand-300 border border-brand-500/30' :
                                'bg-white/5 text-white/60 hover:bg-white/10'
                              }`}
                            >
                              <input
                                type="checkbox"
                                disabled={inGroup}
                                checked={selectedServers.includes(name)}
                                onChange={e => {
                                  setSelectedServers(prev =>
                                    e.target.checked ? [...prev, name] : prev.filter(n => n !== name)
                                  );
                                }}
                                className="accent-brand-500"
                              />
                              <span className="truncate">{name}</span>
                            </label>
                          );
                        })}
                      </div>
                      <div className="flex gap-2 justify-end">
                        <button onClick={() => { setAddServerGroup(null); setSelectedServers([]); }} className="px-3 py-1.5 text-sm text-white/50 hover:text-white">Cancel</button>
                        <button
                          onClick={() => addServersToGroup(group.id)}
                          disabled={selectedServers.length === 0}
                          className="px-3 py-1.5 text-sm bg-brand-500 text-white rounded-lg disabled:opacity-50 hover:bg-brand-600"
                        >
                          Add {selectedServers.length > 0 ? `(${selectedServers.length})` : ''}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setAddServerGroup(group.id)}
                      className="w-full py-2 text-sm text-brand-300 hover:bg-brand-500/10 rounded-lg border border-dashed border-brand-500/30 flex items-center justify-center gap-2"
                    >
                      <FaPlus className="w-3 h-3" /> Add Servers
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─── Bulk Operations Panel ─────────────────────────────────

function BulkOperationsPanel() {
  const globalData = useGlobalData();
  const servers = globalData?.servers || [];
  const [selected, setSelected] = useState([]);
  const [operation, setOperation] = useState('start');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/multi-server/bulk-operations?limit=10`, { headers: authHeaders() });
        if (r.ok) setHistory(await r.json());
      } catch { }
      setLoadingHistory(false);
    })();
  }, []);

  const toggleServer = (name) => {
    setSelected(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]);
  };

  const selectAll = () => setSelected(servers.map(s => s.name || s.id));
  const selectNone = () => setSelected([]);

  const executeBulk = async () => {
    if (selected.length === 0) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await fetch(`${API}/multi-server/bulk-operations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ operation_type: operation, server_names: selected }),
      });
      if (r.ok) {
        const data = await r.json();
        setResult(data);
        // Poll for completion
        if (data.id) {
          const poll = setInterval(async () => {
            try {
              const pr = await fetch(`${API}/multi-server/bulk-operations/${data.id}`, { headers: authHeaders() });
              if (pr.ok) {
                const pd = await pr.json();
                setResult(pd);
                if (pd.status === 'completed') clearInterval(poll);
              }
            } catch { clearInterval(poll); }
          }, 2000);
          setTimeout(() => clearInterval(poll), 60000);
        }
      }
    } catch { }
    setRunning(false);
  };

  const OP_CONFIG = {
    start: { icon: FaPlay, color: 'text-green-400', bg: 'bg-green-500/20 border-green-500/40' },
    stop: { icon: FaStop, color: 'text-red-400', bg: 'bg-red-500/20 border-red-500/40' },
    restart: { icon: FaSyncAlt, color: 'text-yellow-400', bg: 'bg-yellow-500/20 border-yellow-500/40' },
    backup: { icon: FaDatabase, color: 'text-blue-400', bg: 'bg-blue-500/20 border-blue-500/40' },
  };

  return (
    <Card title="Bulk Operations" description="Execute actions on multiple servers at once" icon={FaSyncAlt}>
      {/* Operation Selector */}
      <div className="flex gap-2 mb-4">
        {Object.entries(OP_CONFIG).map(([key, cfg]) => (
          <button
            key={key}
            onClick={() => setOperation(key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm border transition-colors ${
              operation === key ? `${cfg.bg} ${cfg.color}` : 'border-white/10 text-white/50 hover:bg-white/5'
            }`}
          >
            <cfg.icon className="w-3.5 h-3.5" /> {key.charAt(0).toUpperCase() + key.slice(1)}
          </button>
        ))}
      </div>

      {/* Server Selection */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-white/60">Select servers ({selected.length}/{servers.length})</span>
          <div className="flex gap-2">
            <button onClick={selectAll} className="text-xs text-brand-300 hover:text-brand-200">All</button>
            <button onClick={selectNone} className="text-xs text-white/40 hover:text-white/60">None</button>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 max-h-48 overflow-y-auto p-1">
          {servers.map(s => {
            const name = s.name || s.id;
            const isSelected = selected.includes(name);
            return (
              <button
                key={name}
                onClick={() => toggleServer(name)}
                className={`flex items-center gap-2 p-2.5 rounded-lg text-sm text-left transition-colors border ${
                  isSelected
                    ? 'bg-brand-500/15 border-brand-500/30 text-brand-300'
                    : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10'
                }`}
              >
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${s.status === 'running' ? 'bg-green-400' : 'bg-white/30'}`} />
                <span className="truncate">{name}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Execute */}
      <button
        onClick={executeBulk}
        disabled={running || selected.length === 0}
        className={`w-full py-3 rounded-lg font-medium text-sm flex items-center justify-center gap-2 transition-colors border disabled:opacity-50 ${OP_CONFIG[operation].bg} ${OP_CONFIG[operation].color}`}
      >
        {running ? <FaSpinner className="animate-spin" /> : (() => { const Icon = OP_CONFIG[operation].icon; return <Icon />; })()}
        {running ? 'Executing…' : `${operation.charAt(0).toUpperCase() + operation.slice(1)} ${selected.length} server${selected.length !== 1 ? 's' : ''}`}
      </button>

      {/* Result */}
      {result && (
        <div className="mt-4 p-4 bg-white/5 rounded-lg border border-white/10">
          <div className="flex items-center gap-3 mb-3">
            <span className={`text-xs px-2 py-0.5 rounded ${
              result.status === 'completed' ? 'bg-green-500/20 text-green-300' :
              result.status === 'running' ? 'bg-yellow-500/20 text-yellow-300' :
              'bg-white/10 text-white/50'
            }`}>{result.status || 'pending'}</span>
            {result.success_count !== undefined && (
              <span className="text-xs text-green-400">{result.success_count} succeeded</span>
            )}
            {result.failed_count > 0 && (
              <span className="text-xs text-red-400">{result.failed_count} failed</span>
            )}
          </div>
          {result.results && (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {Object.entries(result.results).map(([srv, res]) => (
                <div key={srv} className="flex items-center justify-between text-xs p-2 bg-black/20 rounded">
                  <span className="text-white/70">{srv}</span>
                  <span className={res.status === 'success' ? 'text-green-400' : 'text-red-400'}>
                    {res.status === 'success' ? <FaCheckCircle className="inline mr-1" /> : <FaTimesCircle className="inline mr-1" />}
                    {res.message}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="mt-6">
          <h4 className="text-sm font-semibold text-white/60 mb-3">Recent Operations</h4>
          <div className="space-y-2">
            {history.map(op => (
              <div key={op.id} className="flex items-center justify-between p-3 bg-white/5 rounded-lg text-sm">
                <div className="flex items-center gap-3">
                  {OP_CONFIG[op.operation_type] && (() => { const Icon = OP_CONFIG[op.operation_type].icon; return <Icon className={`w-3.5 h-3.5 ${OP_CONFIG[op.operation_type].color}`} />; })()}
                  <span className="text-white/70">{op.operation_type}</span>
                  <span className="text-xs text-white/40">{op.total_count} servers</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    op.status === 'completed' ? 'bg-green-500/10 text-green-400' :
                    op.status === 'running' ? 'bg-yellow-500/10 text-yellow-400' :
                    'bg-white/5 text-white/40'
                  }`}>{op.status}</span>
                  <span className="text-xs text-white/30">{op.started_at ? new Date(op.started_at).toLocaleString() : ''}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ─── Server Clone Panel ────────────────────────────────────

function ServerClonePanel() {
  const globalData = useGlobalData();
  const servers = globalData?.servers || [];
  const [source, setSource] = useState('');
  const [target, setTarget] = useState('');
  const [cloneType, setCloneType] = useState('full');
  const [includeWorlds, setIncludeWorlds] = useState(true);
  const [includeMods, setIncludeMods] = useState(true);
  const [includePlugins, setIncludePlugins] = useState(true);
  const [cloning, setCloning] = useState(false);
  const [result, setResult] = useState(null);

  const startClone = async () => {
    if (!source || !target.trim()) return;
    setCloning(true);
    setResult(null);
    try {
      const r = await fetch(`${API}/multi-server/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          source_server: source,
          target_server: target.trim(),
          clone_type: cloneType,
          include_worlds: includeWorlds,
          include_mods: includeMods,
          include_plugins: includePlugins,
        }),
      });
      if (r.ok) {
        const data = await r.json();
        setResult(data);
        // Poll for progress
        if (data.id) {
          const poll = setInterval(async () => {
            try {
              const pr = await fetch(`${API}/multi-server/clone/${data.id}`, { headers: authHeaders() });
              if (pr.ok) {
                const pd = await pr.json();
                setResult(pd);
                if (pd.status === 'completed' || pd.status === 'failed') clearInterval(poll);
              }
            } catch { clearInterval(poll); }
          }, 1500);
          setTimeout(() => clearInterval(poll), 120000);
        }
      }
    } catch { }
    setCloning(false);
  };

  const CLONE_TYPES = [
    { id: 'full', label: 'Full Clone', desc: 'Everything' },
    { id: 'config_only', label: 'Config Only', desc: 'Settings & properties' },
    { id: 'world_only', label: 'World Only', desc: 'World data' },
    { id: 'custom', label: 'Custom', desc: 'Pick components' },
  ];

  return (
    <Card title="Clone Server" description="Duplicate an existing server with selected components" icon={FaClone}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        {/* Source */}
        <div>
          <label className="text-sm text-white/60 mb-1.5 block">Source Server</label>
          <select
            value={source}
            onChange={e => setSource(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
          >
            <option value="">Select source…</option>
            {servers.map(s => <option key={s.name || s.id} value={s.name || s.id}>{s.name || s.id}</option>)}
          </select>
        </div>

        {/* Target */}
        <div>
          <label className="text-sm text-white/60 mb-1.5 block">New Server Name</label>
          <input
            value={target}
            onChange={e => setTarget(e.target.value)}
            placeholder="my-server-clone"
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm"
          />
        </div>
      </div>

      {/* Clone Type */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        {CLONE_TYPES.map(ct => (
          <button
            key={ct.id}
            onClick={() => setCloneType(ct.id)}
            className={`p-3 rounded-lg text-left border transition-colors ${
              cloneType === ct.id
                ? 'bg-brand-500/15 border-brand-500/30 text-brand-300'
                : 'bg-white/5 border-white/10 text-white/50 hover:bg-white/10'
            }`}
          >
            <div className="text-sm font-medium">{ct.label}</div>
            <div className="text-xs opacity-60">{ct.desc}</div>
          </button>
        ))}
      </div>

      {/* Custom options */}
      {cloneType === 'custom' && (
        <div className="flex gap-4 mb-4 p-3 bg-white/5 rounded-lg border border-white/10">
          {[
            { key: 'worlds', label: 'Worlds', val: includeWorlds, set: setIncludeWorlds },
            { key: 'mods', label: 'Mods', val: includeMods, set: setIncludeMods },
            { key: 'plugins', label: 'Plugins', val: includePlugins, set: setIncludePlugins },
          ].map(opt => (
            <label key={opt.key} className="flex items-center gap-2 text-sm text-white/70 cursor-pointer">
              <input type="checkbox" checked={opt.val} onChange={e => opt.set(e.target.checked)} className="accent-brand-500" />
              {opt.label}
            </label>
          ))}
        </div>
      )}

      {/* Execute */}
      <button
        onClick={startClone}
        disabled={cloning || !source || !target.trim()}
        className="w-full py-3 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg font-medium text-sm hover:bg-brand-500/30 disabled:opacity-50 flex items-center justify-center gap-2"
      >
        {cloning ? <FaSpinner className="animate-spin" /> : <FaClone />}
        {cloning ? 'Cloning…' : 'Clone Server'}
      </button>

      {/* Result */}
      {result && (
        <div className="mt-4 p-4 bg-white/5 rounded-lg border border-white/10">
          <div className="flex items-center gap-3">
            <span className={`text-xs px-2 py-0.5 rounded ${
              result.status === 'completed' ? 'bg-green-500/20 text-green-300' :
              result.status === 'running' ? 'bg-yellow-500/20 text-yellow-300' :
              result.status === 'failed' ? 'bg-red-500/20 text-red-300' :
              'bg-white/10 text-white/50'
            }`}>{result.status}</span>
            {result.progress_percent !== undefined && result.status === 'running' && (
              <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
                <div className="h-full bg-brand-500 transition-all" style={{ width: `${result.progress_percent}%` }} />
              </div>
            )}
            {result.error_message && <span className="text-xs text-red-300">{result.error_message}</span>}
          </div>
        </div>
      )}
    </Card>
  );
}

// ─── File Sync Panel ───────────────────────────────────────

function FileSyncPanel() {
  const globalData = useGlobalData();
  const servers = globalData?.servers || [];
  const [source, setSource] = useState('');
  const [targets, setTargets] = useState([]);
  const [paths, setPaths] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState(null);

  const toggleTarget = (name) => {
    setTargets(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]);
  };

  const syncFiles = async () => {
    if (!source || targets.length === 0 || !paths.trim()) return;
    setSyncing(true);
    setResult(null);
    try {
      const r = await fetch(`${API}/multi-server/file-sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          source_server: source,
          target_servers: targets,
          paths: paths.split('\n').map(p => p.trim()).filter(Boolean),
        }),
      });
      if (r.ok) setResult(await r.json());
    } catch { }
    setSyncing(false);
  };

  return (
    <Card title="File Sync" description="Sync files from one server to others" icon={FaExchangeAlt}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div>
          <label className="text-sm text-white/60 mb-1.5 block">Source Server</label>
          <select
            value={source}
            onChange={e => setSource(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
          >
            <option value="">Select source…</option>
            {servers.map(s => <option key={s.name || s.id} value={s.name || s.id}>{s.name || s.id}</option>)}
          </select>
        </div>
        <div>
          <label className="text-sm text-white/60 mb-1.5 block">Paths to sync (one per line)</label>
          <textarea
            value={paths}
            onChange={e => setPaths(e.target.value)}
            placeholder={"server.properties\nconfig/\nmods/"}
            rows={3}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm font-mono resize-none"
          />
        </div>
      </div>

      {/* Target servers */}
      <div className="mb-4">
        <label className="text-sm text-white/60 mb-1.5 block">Target Servers</label>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 max-h-36 overflow-y-auto p-1">
          {servers.filter(s => (s.name || s.id) !== source).map(s => {
            const name = s.name || s.id;
            const isSel = targets.includes(name);
            return (
              <button
                key={name}
                onClick={() => toggleTarget(name)}
                className={`p-2 rounded-lg text-sm text-left transition-colors border ${
                  isSel ? 'bg-brand-500/15 border-brand-500/30 text-brand-300' : 'bg-white/5 border-white/10 text-white/50 hover:bg-white/10'
                }`}
              >
                <span className="truncate">{name}</span>
              </button>
            );
          })}
        </div>
      </div>

      <button
        onClick={syncFiles}
        disabled={syncing || !source || targets.length === 0 || !paths.trim()}
        className="w-full py-3 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg font-medium text-sm hover:bg-brand-500/30 disabled:opacity-50 flex items-center justify-center gap-2"
      >
        {syncing ? <FaSpinner className="animate-spin" /> : <FaExchangeAlt />}
        {syncing ? 'Syncing…' : `Sync to ${targets.length} server${targets.length !== 1 ? 's' : ''}`}
      </button>

      {/* Results */}
      {result && (
        <div className="mt-4 space-y-2">
          {Object.entries(result.results || {}).map(([srv, res]) => (
            <div key={srv} className="p-3 bg-white/5 rounded-lg border border-white/10">
              <div className="flex items-center gap-2 mb-1">
                <FaServer className="text-white/40 w-3 h-3" />
                <span className="text-sm font-medium text-white">{srv}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  res.status === 'success' ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'
                }`}>{res.status}</span>
              </div>
              {res.synced?.length > 0 && (
                <div className="text-xs text-green-400/70">{res.synced.join(', ')}</div>
              )}
              {res.errors?.length > 0 && (
                <div className="text-xs text-red-400/70 mt-1">{res.errors.join(', ')}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─── Main Multi-Server Page ────────────────────────────────

export default function MultiServerPage() {
  const [tab, setTab] = useState('groups');

  const TABS = [
    { id: 'groups', label: 'Server Groups', icon: FaLayerGroup },
    { id: 'bulk', label: 'Bulk Operations', icon: FaSyncAlt },
    { id: 'clone', label: 'Clone Server', icon: FaClone },
    { id: 'sync', label: 'File Sync', icon: FaExchangeAlt },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="p-2 bg-brand-500/20 rounded-lg">
          <FaLayerGroup className="w-6 h-6 text-brand-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Multi-Server Operations</h1>
          <p className="text-sm text-white/50">Groups, bulk actions, cloning & file sync</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10 overflow-x-auto">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all border-b-2 ${
              tab === t.id
                ? 'border-brand-500 text-brand-400 bg-brand-500/10'
                : 'border-transparent text-white/60 hover:text-white/80 hover:bg-white/5'
            }`}
          >
            <t.icon className="w-4 h-4" />
            <span className="hidden sm:inline">{t.label}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="pb-8">
        {tab === 'groups' && <ServerGroupsPanel />}
        {tab === 'bulk' && <BulkOperationsPanel />}
        {tab === 'clone' && <ServerClonePanel />}
        {tab === 'sync' && <FileSyncPanel />}
      </div>
    </div>
  );
}
