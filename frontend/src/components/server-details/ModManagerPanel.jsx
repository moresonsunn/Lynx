import React, { useState, useEffect, useCallback } from 'react';
import { API, authHeaders } from '../../context/AppContext';
import {
  FaSearch, FaSyncAlt, FaExclamationTriangle, FaCheckCircle,
  FaTimesCircle, FaSpinner, FaArrowUp, FaBoxOpen, FaDownload,
  FaCube, FaPuzzlePiece, FaExclamationCircle, FaChevronDown,
  FaChevronUp, FaArchive, FaList, FaBug, FaLink
} from 'react-icons/fa';

// ─── Mod Scanner & List ────────────────────────────────────

function ModListSection({ serverName, mods, onRefresh }) {
  const [scanning, setScanning] = useState(false);

  const scanMods = async () => {
    setScanning(true);
    try {
      await fetch(`${API}/mods-enhanced/scan/${serverName}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      onRefresh();
    } catch { }
    setScanning(false);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white/60">Tracked Mods ({mods.length})</h3>
        <button
          onClick={scanMods}
          disabled={scanning}
          className="px-3 py-1.5 text-xs bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg hover:bg-brand-500/30 disabled:opacity-50 flex items-center gap-1.5"
        >
          {scanning ? <FaSpinner className="animate-spin" /> : <FaSearch />} Scan Mods
        </button>
      </div>

      {mods.length === 0 ? (
        <div className="text-center py-8 text-white/30">
          <FaBoxOpen className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No mods tracked yet. Click "Scan Mods" to detect installed mods.</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
          {mods.map(mod => (
            <div key={mod.id || mod.file_name} className="flex items-center justify-between p-3 bg-white/5 rounded-lg border border-white/10">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <FaCube className="text-brand-400 w-3.5 h-3.5 flex-shrink-0" />
                  <span className="text-sm font-medium text-white truncate">{mod.mod_name || mod.file_name}</span>
                  {mod.mod_loader && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/50">{mod.mod_loader}</span>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-white/40">
                  <span>v{mod.current_version || '?'}</span>
                  {mod.minecraft_version && <span>MC {mod.minecraft_version}</span>}
                  <span className="truncate">{mod.file_name}</span>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                {mod.update_available ? (
                  <span className="flex items-center gap-1 text-xs px-2 py-1 bg-yellow-500/20 border border-yellow-500/30 text-yellow-300 rounded-lg">
                    <FaArrowUp className="w-3 h-3" /> {mod.latest_version}
                  </span>
                ) : mod.last_checked ? (
                  <span className="text-xs text-green-400/60"><FaCheckCircle className="inline mr-1" />Up to date</span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Update Checker ────────────────────────────────────────

function UpdateCheckerSection({ serverName, onRefresh }) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState(null);
  const [updates, setUpdates] = useState([]);

  const checkUpdates = async () => {
    setChecking(true);
    setResult(null);
    try {
      const r = await fetch(`${API}/mods-enhanced/check-updates/${serverName}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) {
        const d = await r.json();
        setResult(d);
        // Fetch updated mods list
        const ur = await fetch(`${API}/mods-enhanced/updates/${serverName}`, { headers: authHeaders() });
        if (ur.ok) setUpdates(await ur.json());
        onRefresh();
      }
    } catch { }
    setChecking(false);
  };

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 bg-yellow-500/20 rounded-lg">
          <FaSyncAlt className="w-4 h-4 text-yellow-400" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-white">Update Checker</h3>
          <p className="text-xs text-white/40">Check Modrinth & CurseForge for newer versions</p>
        </div>
        <button
          onClick={checkUpdates}
          disabled={checking}
          className="px-4 py-2 bg-yellow-500/20 border border-yellow-500/40 text-yellow-300 rounded-lg text-sm hover:bg-yellow-500/30 disabled:opacity-50 flex items-center gap-2"
        >
          {checking ? <FaSpinner className="animate-spin" /> : <FaSyncAlt />} Check Now
        </button>
      </div>

      {result && (
        <div className="mb-4 p-3 bg-white/5 rounded-lg text-sm">
          <span className="text-white/60">Checked <span className="text-white">{result.checked}</span> mods — </span>
          {result.updates_available > 0 ? (
            <span className="text-yellow-300">{result.updates_available} updates available</span>
          ) : (
            <span className="text-green-400">All up to date!</span>
          )}
        </div>
      )}

      {updates.length > 0 && (
        <div className="space-y-2">
          {updates.map(mod => (
            <div key={mod.id || mod.file_name} className="flex items-center justify-between p-3 bg-yellow-500/10 rounded-lg border border-yellow-500/20">
              <div className="min-w-0">
                <div className="text-sm font-medium text-white">{mod.mod_name}</div>
                <div className="text-xs text-white/40 mt-0.5">
                  {mod.current_version} → <span className="text-yellow-300">{mod.latest_version}</span>
                </div>
              </div>
              <FaArrowUp className="text-yellow-400 w-4 h-4 flex-shrink-0" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Conflict Detector ─────────────────────────────────────

function ConflictDetectorSection({ serverName }) {
  const [detecting, setDetecting] = useState(false);
  const [result, setResult] = useState(null);
  const [conflicts, setConflicts] = useState([]);

  const detectConflicts = async () => {
    setDetecting(true);
    try {
      const r = await fetch(`${API}/mods-enhanced/detect-conflicts/${serverName}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) setResult(await r.json());

      const cr = await fetch(`${API}/mods-enhanced/conflicts/${serverName}`, { headers: authHeaders() });
      if (cr.ok) setConflicts(await cr.json());
    } catch { }
    setDetecting(false);
  };

  const SEVERITY_STYLES = {
    critical: { bg: 'bg-red-500/10 border-red-500/20', text: 'text-red-300', badge: 'bg-red-500/20 text-red-300' },
    warning: { bg: 'bg-yellow-500/10 border-yellow-500/20', text: 'text-yellow-300', badge: 'bg-yellow-500/20 text-yellow-300' },
    info: { bg: 'bg-blue-500/10 border-blue-500/20', text: 'text-blue-300', badge: 'bg-blue-500/20 text-blue-300' },
  };

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 bg-red-500/20 rounded-lg">
          <FaBug className="w-4 h-4 text-red-400" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-white">Conflict Detection</h3>
          <p className="text-xs text-white/40">Find duplicate mods, loader mismatches & version issues</p>
        </div>
        <button
          onClick={detectConflicts}
          disabled={detecting}
          className="px-4 py-2 bg-red-500/20 border border-red-500/40 text-red-300 rounded-lg text-sm hover:bg-red-500/30 disabled:opacity-50 flex items-center gap-2"
        >
          {detecting ? <FaSpinner className="animate-spin" /> : <FaBug />} Detect
        </button>
      </div>

      {result && (
        <div className="mb-4 p-3 bg-white/5 rounded-lg text-sm">
          {result.conflicts_found > 0 ? (
            <span className="text-red-300"><FaExclamationTriangle className="inline mr-1" />{result.conflicts_found} conflict{result.conflicts_found !== 1 ? 's' : ''} detected</span>
          ) : (
            <span className="text-green-400"><FaCheckCircle className="inline mr-1" />No conflicts found!</span>
          )}
        </div>
      )}

      {conflicts.length > 0 && (
        <div className="space-y-2">
          {conflicts.map((c, i) => {
            const style = SEVERITY_STYLES[c.severity] || SEVERITY_STYLES.info;
            return (
              <div key={i} className={`p-3 rounded-lg border ${style.bg}`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded font-semibold ${style.badge}`}>{c.severity}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded bg-white/10 text-white/50`}>{c.conflict_type}</span>
                </div>
                <div className={`text-sm ${style.text}`}>{c.description}</div>
                <div className="text-xs text-white/30 mt-1">{c.mod_a} ↔ {c.mod_b}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Dependency Resolver ───────────────────────────────────

function DependencyResolverSection({ serverName }) {
  const [resolving, setResolving] = useState(false);
  const [result, setResult] = useState(null);

  const resolveDeps = async () => {
    setResolving(true);
    try {
      const r = await fetch(`${API}/mods-enhanced/resolve-dependencies/${serverName}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) setResult(await r.json());
    } catch { }
    setResolving(false);
  };

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 bg-purple-500/20 rounded-lg">
          <FaLink className="w-4 h-4 text-purple-400" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-white">Dependency Check</h3>
          <p className="text-xs text-white/40">Find missing required dependencies</p>
        </div>
        <button
          onClick={resolveDeps}
          disabled={resolving}
          className="px-4 py-2 bg-purple-500/20 border border-purple-500/40 text-purple-300 rounded-lg text-sm hover:bg-purple-500/30 disabled:opacity-50 flex items-center gap-2"
        >
          {resolving ? <FaSpinner className="animate-spin" /> : <FaLink />} Check
        </button>
      </div>

      {result && (
        <>
          <div className="mb-3 p-3 bg-white/5 rounded-lg text-sm">
            {result.missing_dependencies?.length > 0 ? (
              <span className="text-yellow-300"><FaExclamationCircle className="inline mr-1" />{result.missing_dependencies.length} missing dependenc{result.missing_dependencies.length !== 1 ? 'ies' : 'y'}</span>
            ) : (
              <span className="text-green-400"><FaCheckCircle className="inline mr-1" />All dependencies satisfied!</span>
            )}
          </div>

          {result.missing_dependencies?.length > 0 && (
            <div className="space-y-2">
              {result.missing_dependencies.map((dep, i) => (
                <div key={i} className="p-3 bg-yellow-500/10 rounded-lg border border-yellow-500/20">
                  <div className="flex items-center gap-2">
                    <FaPuzzlePiece className="text-yellow-400 w-3.5 h-3.5" />
                    <span className="text-sm font-medium text-yellow-300">{dep.dependency_id}</span>
                    {dep.version && <span className="text-xs text-white/40">v{dep.version}</span>}
                  </div>
                  <div className="text-xs text-white/40 mt-1">
                    Required by: {dep.required_by.join(', ')}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Client Modpack Generator ──────────────────────────────

function ClientModpackSection({ serverName }) {
  const [generating, setGenerating] = useState(false);
  const [version, setVersion] = useState('1.0.0');
  const [includeConfig, setIncludeConfig] = useState(true);
  const [includeRP, setIncludeRP] = useState(false);
  const [result, setResult] = useState(null);
  const [packs, setPacks] = useState([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/mods-enhanced/client-modpacks/${serverName}`, { headers: authHeaders() });
        if (r.ok) setPacks(await r.json());
      } catch { }
    })();
  }, [serverName]);

  const generate = async () => {
    setGenerating(true);
    setResult(null);
    try {
      const r = await fetch(`${API}/mods-enhanced/generate-client-modpack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          server_name: serverName,
          version,
          include_config: includeConfig,
          include_resourcepacks: includeRP,
        }),
      });
      if (r.ok) {
        const d = await r.json();
        setResult(d);
        // Refresh list
        const lr = await fetch(`${API}/mods-enhanced/client-modpacks/${serverName}`, { headers: authHeaders() });
        if (lr.ok) setPacks(await lr.json());
      }
    } catch { }
    setGenerating(false);
  };

  const formatSize = (bytes) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return `${size.toFixed(1)} ${units[i]}`;
  };

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 bg-green-500/20 rounded-lg">
          <FaArchive className="w-4 h-4 text-green-400" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-white">Client Modpack Generator</h3>
          <p className="text-xs text-white/40">Create a ZIP with client-side mods for players</p>
        </div>
      </div>

      {/* Options */}
      <div className="flex flex-wrap gap-4 mb-4">
        <div>
          <label className="text-xs text-white/50 block mb-1">Version</label>
          <input
            value={version}
            onChange={e => setVersion(e.target.value)}
            className="w-28 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-white/60 cursor-pointer self-end pb-1">
          <input type="checkbox" checked={includeConfig} onChange={e => setIncludeConfig(e.target.checked)} className="accent-brand-500" />
          Include config
        </label>
        <label className="flex items-center gap-2 text-sm text-white/60 cursor-pointer self-end pb-1">
          <input type="checkbox" checked={includeRP} onChange={e => setIncludeRP(e.target.checked)} className="accent-brand-500" />
          Include resourcepacks
        </label>
        <button
          onClick={generate}
          disabled={generating}
          className="ml-auto px-4 py-2 bg-green-500/20 border border-green-500/40 text-green-300 rounded-lg text-sm hover:bg-green-500/30 disabled:opacity-50 flex items-center gap-2 self-end"
        >
          {generating ? <FaSpinner className="animate-spin" /> : <FaArchive />} Generate
        </button>
      </div>

      {result && (
        <div className="mb-4 p-3 bg-green-500/10 border border-green-500/20 rounded-lg text-sm text-green-300">
          <FaCheckCircle className="inline mr-1" /> Modpack created with {result.mod_count} mods ({formatSize(result.file_size)})
        </div>
      )}

      {/* Previous packs */}
      {packs.length > 0 && (
        <div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2 text-xs text-white/40 hover:text-white/60 mb-2"
          >
            {expanded ? <FaChevronUp /> : <FaChevronDown />}
            Previous Packs ({packs.length})
          </button>
          {expanded && (
            <div className="space-y-2">
              {packs.map(pack => (
                <div key={pack.id} className="flex items-center justify-between p-3 bg-white/5 rounded-lg text-sm">
                  <div>
                    <span className="text-white">v{pack.version}</span>
                    <span className="text-white/40 ml-2">{pack.mod_count} mods · {formatSize(pack.file_size)}</span>
                  </div>
                  <span className="text-xs text-white/30">{new Date(pack.generated_at).toLocaleDateString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main Mod Manager Panel ────────────────────────────────

export default function ModManagerPanel({ serverName }) {
  const [mods, setMods] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchMods = useCallback(async () => {
    try {
      const r = await fetch(`${API}/mods-enhanced/mods/${serverName}`, { headers: authHeaders() });
      if (r.ok) setMods(await r.json());
    } catch { }
    setLoading(false);
  }, [serverName]);

  useEffect(() => { fetchMods(); }, [fetchMods]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-white/40">
        <FaSpinner className="animate-spin mr-2" /> Loading mod manager…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 bg-brand-500/20 rounded-lg">
          <FaPuzzlePiece className="w-5 h-5 text-brand-400" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-white">Mod Manager</h2>
          <p className="text-xs text-white/40">Scan, track, update & manage server mods</p>
        </div>
      </div>

      {/* Mod List */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-5">
        <ModListSection serverName={serverName} mods={mods} onRefresh={fetchMods} />
      </div>

      {/* Tools Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <UpdateCheckerSection serverName={serverName} onRefresh={fetchMods} />
        <ConflictDetectorSection serverName={serverName} />
        <DependencyResolverSection serverName={serverName} />
        <ClientModpackSection serverName={serverName} />
      </div>
    </div>
  );
}
