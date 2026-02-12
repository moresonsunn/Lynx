import React, { useState, useEffect, useCallback } from 'react';
import { API, authHeaders } from '../../context/AppContext';
import {
  FaShieldAlt, FaSpinner, FaSearch, FaTrash, FaUndo, FaEyeSlash,
  FaCheckCircle, FaExclamationTriangle, FaTimesCircle, FaFilter,
  FaChevronDown, FaChevronUp, FaCube, FaPlus, FaTimes, FaInfoCircle,
  FaDesktop, FaServer, FaQuestion, FaStar, FaEye
} from 'react-icons/fa';

const SIDE_CONFIG = {
  client: { icon: FaDesktop, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20', label: 'Client Only', badge: 'bg-orange-500/20 text-orange-300' },
  server: { icon: FaServer, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20', label: 'Server Only', badge: 'bg-blue-500/20 text-blue-300' },
  both: { icon: FaCheckCircle, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20', label: 'Both Sides', badge: 'bg-green-500/20 text-green-300' },
  unknown: { icon: FaQuestion, color: 'text-white/40', bg: 'bg-white/5 border-white/10', label: 'Unknown', badge: 'bg-white/10 text-white/50' },
};

const METHOD_LABELS = {
  jar_metadata: 'JAR Metadata',
  modrinth_api: 'Modrinth API',
  curseforge_api: 'CurseForge API',
  known_database: 'Known Database',
  filename_pattern: 'Filename Pattern',
  user_override: 'User Override',
  entrypoint_analysis: 'Entrypoint Analysis',
};

function ConfidenceBadge({ confidence }) {
  const pct = Math.round((confidence || 0) * 100);
  let color = 'text-white/40 bg-white/10';
  if (pct >= 90) color = 'text-green-300 bg-green-500/20';
  else if (pct >= 70) color = 'text-yellow-300 bg-yellow-500/20';
  else if (pct >= 50) color = 'text-orange-300 bg-orange-500/20';
  else if (pct > 0) color = 'text-red-300 bg-red-500/20';
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${color}`}>{pct}%</span>;
}

function ModCard({ mod, onDisable, onRestore, onWhitelist, disabledMode = false }) {
  const [expanded, setExpanded] = useState(false);
  const sideKey = (mod.side || 'unknown').toLowerCase();
  const cfg = SIDE_CONFIG[sideKey] || SIDE_CONFIG.unknown;
  const SideIcon = cfg.icon;

  return (
    <div className={`rounded-lg border transition-all ${mod.is_client_only && !disabledMode ? cfg.bg : 'bg-white/5 border-white/10'}`}>
      <div className="flex items-center gap-3 p-3 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <SideIcon className={`w-4 h-4 flex-shrink-0 ${cfg.color}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-white truncate">{mod.mod_name || mod.filename}</span>
            {mod.loader && <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/50">{mod.loader}</span>}
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cfg.badge}`}>{cfg.label}</span>
            {mod.confidence > 0 && <ConfidenceBadge confidence={mod.confidence} />}
            {mod.whitelisted && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-300">Whitelisted</span>}
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-white/40">
            {mod.version && <span>v{mod.version}</span>}
            <span className="truncate max-w-[200px]">{mod.filename}</span>
            {mod.detection_method && <span className="text-white/30">{METHOD_LABELS[mod.detection_method] || mod.detection_method}</span>}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {disabledMode ? (
            <button onClick={(e) => { e.stopPropagation(); onRestore?.(mod.filename); }}
              className="p-1.5 text-green-400 hover:bg-green-500/20 rounded-lg transition-colors" title="Restore mod">
              <FaUndo className="w-3.5 h-3.5" />
            </button>
          ) : mod.is_client_only ? (
            <>
              <button onClick={(e) => { e.stopPropagation(); onWhitelist?.(mod.filename); }}
                className="p-1.5 text-blue-400 hover:bg-blue-500/20 rounded-lg transition-colors" title="Whitelist mod">
                <FaStar className="w-3.5 h-3.5" />
              </button>
              <button onClick={(e) => { e.stopPropagation(); onDisable?.(mod.filename); }}
                className="p-1.5 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors" title="Disable mod">
                <FaEyeSlash className="w-3.5 h-3.5" />
              </button>
            </>
          ) : (
            <button onClick={(e) => { e.stopPropagation(); onDisable?.(mod.filename); }}
              className="p-1.5 text-white/20 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors" title="Force disable">
              <FaEyeSlash className="w-3.5 h-3.5" />
            </button>
          )}
          {expanded ? <FaChevronUp className="w-3 h-3 text-white/30" /> : <FaChevronDown className="w-3 h-3 text-white/30" />}
        </div>
      </div>
      {expanded && (
        <div className="px-3 pb-3 space-y-1 border-t border-white/5 pt-2">
          {mod.reason && <div className="text-xs text-white/50"><span className="text-white/30">Reason:</span> {mod.reason}</div>}
          {mod.mod_id && <div className="text-xs text-white/50"><span className="text-white/30">Mod ID:</span> {mod.mod_id}</div>}
          {mod.modrinth_id && <div className="text-xs text-white/50"><span className="text-white/30">Modrinth:</span> {mod.modrinth_id}</div>}
          {mod.file_size > 0 && <div className="text-xs text-white/50"><span className="text-white/30">Size:</span> {(mod.file_size / 1024).toFixed(0)} KB</div>}
        </div>
      )}
    </div>
  );
}

export default function ClientModFilterPanel({ serverName }) {
  const [analyzing, setAnalyzing] = useState(false);
  const [filtering, setFiltering] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [disabledMods, setDisabledMods] = useState([]);
  const [whitelist, setWhitelist] = useState([]);
  const [newPattern, setNewPattern] = useState('');
  const [showDisabled, setShowDisabled] = useState(false);
  const [showWhitelist, setShowWhitelist] = useState(false);
  const [filter, setFilter] = useState('all'); // all, client, server, unknown
  const [useApi, setUseApi] = useState(true);
  const [minConfidence, setMinConfidence] = useState(0.6);
  const [actionLog, setActionLog] = useState([]);

  const addLog = (msg, type = 'info') => {
    setActionLog(prev => [{ msg, type, time: Date.now() }, ...prev].slice(0, 20));
  };

  const loadDisabledMods = useCallback(async () => {
    try {
      const r = await fetch(`${API}/client-mods/disabled/${serverName}`, { headers: authHeaders() });
      if (r.ok) setDisabledMods((await r.json()).mods || []);
    } catch { }
  }, [serverName]);

  const loadWhitelist = useCallback(async () => {
    try {
      const r = await fetch(`${API}/client-mods/whitelist/${serverName}`, { headers: authHeaders() });
      if (r.ok) setWhitelist((await r.json()).patterns || []);
    } catch { }
  }, [serverName]);

  useEffect(() => {
    loadDisabledMods();
    loadWhitelist();
  }, [loadDisabledMods, loadWhitelist]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setAnalysis(null);
    try {
      const r = await fetch(`${API}/client-mods/analyze/${serverName}?use_api=${useApi}`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        setAnalysis(data);
        addLog(`Analyzed ${data.total_mods} mods: ${data.client_only_count} client-only, ${data.server_or_both_count} server/both, ${data.unknown_count} unknown`);
      }
    } catch (e) {
      addLog(`Analysis failed: ${e.message}`, 'error');
    }
    setAnalyzing(false);
  };

  const runFilter = async (dryRun = false) => {
    setFiltering(true);
    try {
      const r = await fetch(`${API}/client-mods/filter/${serverName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ use_api: useApi, min_confidence: minConfidence, dry_run: dryRun }),
      });
      if (r.ok) {
        const data = await r.json();
        if (dryRun) {
          addLog(`Preview: would disable ${data.client_only_moved} mods (dry run)`);
        } else {
          addLog(`Disabled ${data.client_only_moved} client-only mods`, 'success');
          runAnalysis();
          loadDisabledMods();
        }
      }
    } catch (e) {
      addLog(`Filter failed: ${e.message}`, 'error');
    }
    setFiltering(false);
  };

  const disableMod = async (filename) => {
    try {
      const r = await fetch(`${API}/client-mods/disable/${serverName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ filename }),
      });
      if (r.ok) {
        addLog(`Disabled: ${filename}`, 'success');
        runAnalysis();
        loadDisabledMods();
      }
    } catch (e) { addLog(`Failed to disable ${filename}: ${e.message}`, 'error'); }
  };

  const restoreMod = async (filename) => {
    try {
      const r = await fetch(`${API}/client-mods/restore/${serverName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ filename }),
      });
      if (r.ok) {
        addLog(`Restored: ${filename}`, 'success');
        if (analysis) runAnalysis();
        loadDisabledMods();
      }
    } catch (e) { addLog(`Failed to restore ${filename}: ${e.message}`, 'error'); }
  };

  const restoreAll = async () => {
    try {
      const r = await fetch(`${API}/client-mods/restore-all/${serverName}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) {
        const data = await r.json();
        addLog(`Restored ${data.restored} mods`, 'success');
        if (analysis) runAnalysis();
        loadDisabledMods();
      }
    } catch (e) { addLog(`Restore all failed: ${e.message}`, 'error'); }
  };

  const whitelistMod = async (filename) => {
    const pattern = filename.toLowerCase().replace('.jar', '');
    try {
      const r = await fetch(`${API}/client-mods/whitelist/${serverName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ pattern }),
      });
      if (r.ok) {
        addLog(`Whitelisted: ${pattern}`, 'success');
        loadWhitelist();
      }
    } catch (e) { addLog(`Failed to whitelist: ${e.message}`, 'error'); }
  };

  const addWhitelistPattern = async () => {
    if (!newPattern.trim()) return;
    try {
      const r = await fetch(`${API}/client-mods/whitelist/${serverName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ pattern: newPattern.trim() }),
      });
      if (r.ok) {
        addLog(`Added whitelist pattern: ${newPattern}`, 'success');
        setNewPattern('');
        loadWhitelist();
      }
    } catch (e) { addLog(`Failed: ${e.message}`, 'error'); }
  };

  const removeWhitelistPattern = async (pattern) => {
    try {
      const r = await fetch(`${API}/client-mods/whitelist/${serverName}?pattern=${encodeURIComponent(pattern)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (r.ok) {
        addLog(`Removed whitelist pattern: ${pattern}`, 'success');
        loadWhitelist();
      }
    } catch (e) { addLog(`Failed: ${e.message}`, 'error'); }
  };

  const filteredMods = analysis?.mods?.filter(m => {
    if (filter === 'client') return m.is_client_only;
    if (filter === 'server') return !m.is_client_only && m.side !== 'unknown';
    if (filter === 'unknown') return m.side === 'unknown' && !m.is_client_only;
    return true;
  }) || [];

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-start gap-3">
        <div className="p-2.5 bg-orange-500/20 rounded-xl">
          <FaShieldAlt className="w-5 h-5 text-orange-400" />
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold text-white">Client Mod Filter</h2>
          <p className="text-xs text-white/40 mt-0.5">
            Automatically detect & remove client-only mods that crash or are useless on dedicated servers.
            Uses JAR metadata, Modrinth/CurseForge APIs, known mod database, and entrypoint analysis.
          </p>
        </div>
      </div>

      {/* ── Controls ── */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={runAnalysis} disabled={analyzing}
            className="px-4 py-2 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg text-sm hover:bg-brand-500/30 disabled:opacity-50 flex items-center gap-2">
            {analyzing ? <FaSpinner className="animate-spin" /> : <FaSearch />} Analyze Mods
          </button>
          <button onClick={() => runFilter(false)} disabled={filtering || !analysis}
            className="px-4 py-2 bg-orange-500/20 border border-orange-500/40 text-orange-300 rounded-lg text-sm hover:bg-orange-500/30 disabled:opacity-50 flex items-center gap-2">
            {filtering ? <FaSpinner className="animate-spin" /> : <FaFilter />} Auto-Filter Client Mods
          </button>
          <button onClick={() => runFilter(true)} disabled={filtering || !analysis}
            className="px-4 py-2 bg-white/5 border border-white/10 text-white/50 rounded-lg text-sm hover:bg-white/10 disabled:opacity-50 flex items-center gap-2">
            <FaEye /> Preview (Dry Run)
          </button>

          <div className="ml-auto flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-white/50 cursor-pointer">
              <input type="checkbox" checked={useApi} onChange={e => setUseApi(e.target.checked)} className="accent-brand-500 w-3.5 h-3.5" />
              Use Modrinth API
            </label>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-white/30">Min confidence:</span>
              <select value={minConfidence} onChange={e => setMinConfidence(parseFloat(e.target.value))}
                className="bg-white/5 border border-white/10 rounded px-2 py-1 text-xs text-white">
                <option value="0.5">50%</option>
                <option value="0.6">60%</option>
                <option value="0.7">70%</option>
                <option value="0.8">80%</option>
                <option value="0.9">90%</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* ── Analysis Results ── */}
      {analysis && (
        <div className="space-y-4">
          {/* Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center">
              <div className="text-2xl font-bold text-white">{analysis.total_mods}</div>
              <div className="text-xs text-white/40 mt-1">Total Mods</div>
            </div>
            <div className="bg-orange-500/10 border border-orange-500/20 rounded-xl p-3 text-center cursor-pointer hover:bg-orange-500/15" onClick={() => setFilter('client')}>
              <div className="text-2xl font-bold text-orange-400">{analysis.client_only_count}</div>
              <div className="text-xs text-orange-300/60 mt-1">Client Only</div>
            </div>
            <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-3 text-center cursor-pointer hover:bg-green-500/15" onClick={() => setFilter('server')}>
              <div className="text-2xl font-bold text-green-400">{analysis.server_or_both_count}</div>
              <div className="text-xs text-green-300/60 mt-1">Server / Both</div>
            </div>
            <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center cursor-pointer hover:bg-white/10" onClick={() => setFilter('unknown')}>
              <div className="text-2xl font-bold text-white/60">{analysis.unknown_count}</div>
              <div className="text-xs text-white/30 mt-1">Unknown</div>
            </div>
          </div>

          {/* Filter Tabs */}
          <div className="flex items-center gap-1 bg-white/5 rounded-lg p-1">
            {[
              { key: 'all', label: 'All', count: analysis.total_mods },
              { key: 'client', label: 'Client Only', count: analysis.client_only_count },
              { key: 'server', label: 'Server/Both', count: analysis.server_or_both_count },
              { key: 'unknown', label: 'Unknown', count: analysis.unknown_count },
            ].map(tab => (
              <button key={tab.key} onClick={() => setFilter(tab.key)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${filter === tab.key ? 'bg-white/10 text-white' : 'text-white/40 hover:text-white/60'}`}>
                {tab.label} ({tab.count})
              </button>
            ))}
          </div>

          {/* Mod List */}
          <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
            {filteredMods.length === 0 ? (
              <div className="text-center py-8 text-white/30 text-sm">No mods match this filter</div>
            ) : filteredMods.map((mod, i) => (
              <ModCard key={mod.filename || i} mod={mod} onDisable={disableMod} onRestore={restoreMod} onWhitelist={whitelistMod} />
            ))}
          </div>
        </div>
      )}

      {/* ── Disabled Mods Section ── */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex items-center justify-between cursor-pointer" onClick={() => setShowDisabled(!showDisabled)}>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-500/20 rounded-lg"><FaEyeSlash className="w-4 h-4 text-red-400" /></div>
            <div>
              <h3 className="text-sm font-semibold text-white">Disabled Client Mods ({disabledMods.length})</h3>
              <p className="text-xs text-white/40">Mods moved to mods-disabled-client/</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {disabledMods.length > 0 && (
              <button onClick={(e) => { e.stopPropagation(); restoreAll(); }}
                className="px-3 py-1.5 text-xs bg-green-500/20 border border-green-500/40 text-green-300 rounded-lg hover:bg-green-500/30 flex items-center gap-1.5">
                <FaUndo /> Restore All
              </button>
            )}
            {showDisabled ? <FaChevronUp className="text-white/30" /> : <FaChevronDown className="text-white/30" />}
          </div>
        </div>

        {showDisabled && disabledMods.length > 0 && (
          <div className="mt-4 space-y-2 max-h-[300px] overflow-y-auto">
            {disabledMods.map((mod, i) => (
              <div key={mod.filename || i} className="flex items-center justify-between p-2.5 bg-red-500/5 rounded-lg border border-red-500/10">
                <div className="flex items-center gap-2 min-w-0">
                  <FaCube className="text-red-400/50 w-3.5 h-3.5 flex-shrink-0" />
                  <span className="text-sm text-white/60 truncate">{mod.filename}</span>
                  <span className="text-xs text-white/30">{(mod.size / 1024).toFixed(0)} KB</span>
                </div>
                <button onClick={() => restoreMod(mod.filename)}
                  className="px-2.5 py-1 text-xs bg-green-500/20 border border-green-500/30 text-green-300 rounded-lg hover:bg-green-500/30 flex items-center gap-1">
                  <FaUndo className="w-3 h-3" /> Restore
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Whitelist Section ── */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex items-center justify-between cursor-pointer" onClick={() => setShowWhitelist(!showWhitelist)}>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/20 rounded-lg"><FaStar className="w-4 h-4 text-blue-400" /></div>
            <div>
              <h3 className="text-sm font-semibold text-white">Whitelist ({whitelist.length})</h3>
              <p className="text-xs text-white/40">Patterns that prevent mods from being filtered</p>
            </div>
          </div>
          {showWhitelist ? <FaChevronUp className="text-white/30" /> : <FaChevronDown className="text-white/30" />}
        </div>

        {showWhitelist && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2">
              <input value={newPattern} onChange={e => setNewPattern(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addWhitelistPattern()}
                placeholder="e.g. jei, create, botania..."
                className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30" />
              <button onClick={addWhitelistPattern} disabled={!newPattern.trim()}
                className="px-3 py-2 bg-blue-500/20 border border-blue-500/40 text-blue-300 rounded-lg text-sm hover:bg-blue-500/30 disabled:opacity-50 flex items-center gap-1.5">
                <FaPlus className="w-3 h-3" /> Add
              </button>
            </div>
            {whitelist.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {whitelist.map(pat => (
                  <span key={pat} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/10 border border-blue-500/20 rounded-lg text-xs text-blue-300">
                    {pat}
                    <button onClick={() => removeWhitelistPattern(pat)} className="hover:text-red-300 transition-colors">
                      <FaTimes className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Activity Log ── */}
      {actionLog.length > 0 && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-white/40 mb-2 uppercase tracking-wider">Activity Log</h3>
          <div className="space-y-1 max-h-[150px] overflow-y-auto">
            {actionLog.map((log, i) => (
              <div key={i} className={`flex items-start gap-2 text-xs ${log.type === 'error' ? 'text-red-400' : log.type === 'success' ? 'text-green-400' : 'text-white/50'}`}>
                {log.type === 'error' ? <FaTimesCircle className="w-3 h-3 mt-0.5 flex-shrink-0" /> :
                 log.type === 'success' ? <FaCheckCircle className="w-3 h-3 mt-0.5 flex-shrink-0" /> :
                 <FaInfoCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />}
                <span>{log.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Info Box ── */}
      {!analysis && (
        <div className="bg-brand-500/5 border border-brand-500/20 rounded-xl p-4">
          <div className="flex items-start gap-3">
            <FaInfoCircle className="w-4 h-4 text-brand-400 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-white/50 space-y-1.5">
              <p><strong className="text-white/70">How it works:</strong> Click "Analyze Mods" to scan all JAR files in your server's mods folder.</p>
              <p>The system detects client-only mods using <strong className="text-white/60">5 strategies</strong>:</p>
              <ul className="list-disc ml-4 space-y-0.5">
                <li><strong className="text-white/60">JAR Metadata</strong> — reads fabric.mod.json <code className="text-brand-300">environment</code>, quilt.mod.json, Forge <code className="text-brand-300">clientSideOnly</code></li>
                <li><strong className="text-white/60">Entrypoint Analysis</strong> — checks if mod only has client entrypoints (no main/server)</li>
                <li><strong className="text-white/60">Known Database</strong> — 800+ known client-only mod IDs (Sodium, Iris, OptiFine, etc.)</li>
                <li><strong className="text-white/60">Modrinth API</strong> — queries <code className="text-brand-300">server_side</code>/<code className="text-brand-300">client_side</code> metadata</li>
                <li><strong className="text-white/60">Filename Patterns</strong> — fallback matching for unrecognized JARs</li>
              </ul>
              <p>Client mods are moved to <code className="text-brand-300">mods-disabled-client/</code> — they can always be restored.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
