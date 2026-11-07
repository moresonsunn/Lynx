import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FaArrowCircleUp, FaBoxOpen, FaSyncAlt, FaShieldAlt, FaTrash,
  FaCheckCircle, FaTimesCircle, FaExclamationTriangle, FaTimes,
  FaSpinner, FaArchive, FaCube, FaPuzzlePiece, FaCalendarAlt,
  FaChevronDown, FaChevronUp, FaFileAlt
} from 'react-icons/fa';
import { API, authHeaders } from '../../context/AppContext';
import { useTranslation } from '../../i18n';

// ─── Lightweight Safe Markdown / Changelog Renderer ─────────────────────────

function SimpleChangelogRenderer({ content, emptyText }) {
  if (!content || !content.trim()) {
    return (
      <div className="text-white/40 italic py-2">
        {emptyText || 'No changelog or release notes provided for this version.'}
      </div>
    );
  }

  // Parse lines into simple formatted blocks
  const lines = content.split('\n');
  return (
    <div className="space-y-1 font-sans text-xs text-white/80 select-text">
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return <div key={idx} className="h-1.5" />;
        }
        if (trimmed.startsWith('### ')) {
          return <h4 key={idx} className="font-semibold text-white/95 text-xs mt-2 mb-1">{trimmed.slice(4)}</h4>;
        }
        if (trimmed.startsWith('## ')) {
          return <h3 key={idx} className="font-bold text-brand-300 text-sm mt-2.5 mb-1">{trimmed.slice(3)}</h3>;
        }
        if (trimmed.startsWith('# ')) {
          return <h2 key={idx} className="font-bold text-brand-400 text-sm mt-3 mb-1.5 border-b border-white/10 pb-0.5">{trimmed.slice(2)}</h2>;
        }
        if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          return (
            <div key={idx} className="flex items-start gap-2 pl-2">
              <span className="text-brand-400 leading-none mt-1">•</span>
              <span className="flex-1">{trimmed.slice(2)}</span>
            </div>
          );
        }
        return <p key={idx} className="leading-relaxed">{trimmed}</p>;
      })}
    </div>
  );
}

// ─── Step Pipeline Configuration ───────────────────────────────────────────

const PIPELINE_STEPS = [
  { id: 'stopping', key: 'progressStopping', label: 'Stopping Server', desc: 'Gracefully stopping server container' },
  { id: 'backup', key: 'progressBackup', label: 'Safety Backup', desc: 'Creating full pre-update archive' },
  { id: 'download', key: 'progressDownloading', label: 'Downloading Modpack', desc: 'Fetching target version files from provider' },
  { id: 'cleanup', key: 'progressCleaning', label: 'Cleaning Outdated Mods', desc: 'Removing obsolete mod files to prevent duplicates' },
  { id: 'filter', key: 'progressFiltering', label: 'Filtering Client Mods', desc: 'Resolving mod sides & respecting allowlist' },
  { id: 'finalize', key: 'progressRestarting', label: 'Restarting Server', desc: 'Updating metadata and booting server' },
];

// ─── Main Component ────────────────────────────────────────────────────────

export default function ModpackUpdateModal({
  isOpen,
  onClose,
  serverName,
  currentVersion = '',
  onUpdateSuccess,
}) {
  const { t } = useTranslation();

  // Fetch state
  const [fetchState, setFetchState] = useState('idle'); // 'loading' | 'success' | 'not_modpack' | 'error'
  const [fetchError, setFetchError] = useState('');
  const [modpackData, setModpackData] = useState(null);

  // Selection state
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [createBackup, setCreateBackup] = useState(true);
  const [showChangelog, setShowChangelog] = useState(true);

  // Execution state
  const [updateState, setUpdateState] = useState('idle'); // 'idle' | 'updating' | 'success' | 'error'
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [updateError, setUpdateError] = useState('');
  const [updateResult, setUpdateResult] = useState(null);
  const [showCleanedDetails, setShowCleanedDetails] = useState(false);

  // Fetch modpack versions on open
  const fetchVersions = useCallback(async () => {
    if (!serverName) return;
    setFetchState('loading');
    setFetchError('');
    setUpdateState('idle');
    setUpdateResult(null);

    try {
      const res = await fetch(`${API}/modpacks/server/${encodeURIComponent(serverName)}/versions`, {
        headers: authHeaders(),
      });

      if (res.status === 404) {
        setFetchState('not_modpack');
        return;
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to fetch versions (HTTP ${res.status})`);
      }

      const data = await res.json();
      setModpackData(data);
      setFetchState('success');

      // Auto-select the first non-current version, or first version available
      const versions = data.versions || [];
      if (versions.length > 0) {
        const candidate = versions.find(v => !v.is_current) || versions[0];
        setSelectedVersionId(candidate.version_id);
      }
    } catch (err) {
      setFetchError(err.message || 'Unknown error occurred while fetching versions');
      setFetchState('error');
    }
  }, [serverName]);

  useEffect(() => {
    if (isOpen) {
      fetchVersions();
    } else {
      // Reset state on close
      setFetchState('idle');
      setUpdateState('idle');
      setUpdateResult(null);
      setUpdateError('');
      setActiveStepIndex(0);
      setShowCleanedDetails(false);
    }
  }, [isOpen, fetchVersions]);

  // Selected version object
  const selectedVersionObj = useMemo(() => {
    if (!modpackData?.versions) return null;
    return modpackData.versions.find(v => String(v.version_id) === String(selectedVersionId)) || null;
  }, [modpackData, selectedVersionId]);

  // Execute update
  const handleStartUpdate = async () => {
    if (!selectedVersionId || updateState === 'updating') return;

    setUpdateState('updating');
    setUpdateError('');
    setActiveStepIndex(0);

    // Step progression timer simulation while POST is executing
    const stepInterval = setInterval(() => {
      setActiveStepIndex(prev => {
        if (prev < PIPELINE_STEPS.length - 1) return prev + 1;
        return prev;
      });
    }, 4500);

    try {
      const res = await fetch(`${API}/modpacks/server/${encodeURIComponent(serverName)}/update`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          target_version_id: selectedVersionId,
          create_backup: createBackup,
        }),
      });

      clearInterval(stepInterval);

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Update failed with status ${res.status}`);
      }

      const result = await res.json();
      setActiveStepIndex(PIPELINE_STEPS.length); // All steps complete
      setUpdateResult(result);
      setUpdateState('success');
      onUpdateSuccess?.(result);
    } catch (err) {
      clearInterval(stepInterval);
      setUpdateError(err.message || 'Update failed');
      setUpdateState('error');
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={updateState === 'updating' ? undefined : onClose}
      />

      {/* Modal Dialog */}
      <div className="relative bg-ink-900 border border-white/10 rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/10 bg-white/[0.02]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-brand-500/20 text-brand-400 border border-brand-500/30">
              <FaArrowCircleUp className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-white">
                  {t('modpackUpdate.modalTitle') || 'Update Modpack'}
                </h2>
                <span className="font-mono text-xs text-white/70 bg-white/5 px-2 py-0.5 rounded border border-white/10">
                  {serverName}
                </span>
                {modpackData?.provider && (
                  <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    {modpackData.provider}
                  </span>
                )}
              </div>
              <p className="text-xs text-white/40 mt-0.5">
                {t('modpackUpdate.modalSubtitle', { serverName }) || 'Select target version, run safety backup, and resolve obsolete mods'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={updateState === 'updating'}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-30"
          >
            <FaTimes />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto flex-1 min-h-0 space-y-5">

          {/* FETCHING STATE */}
          {fetchState === 'loading' && (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
              <FaSpinner className="animate-spin text-brand-400 text-3xl" />
              <div className="text-sm font-medium text-white">
                {t('modpackUpdate.checkingVersions') || 'Checking available modpack versions...'}
              </div>
              <div className="text-xs text-white/40 max-w-xs">
                Querying repository for available releases, loaders, and changelogs.
              </div>
            </div>
          )}

          {/* NOT A MODPACK SERVER STATE */}
          {fetchState === 'not_modpack' && (
            <div className="p-5 bg-amber-500/10 border border-amber-500/20 rounded-xl text-center space-y-3">
              <FaExclamationTriangle className="w-8 h-8 text-amber-400 mx-auto" />
              <h3 className="text-base font-semibold text-white">
                {t('modpackUpdate.notTrackedTitle') || 'Not a Tracked Modpack Server'}
              </h3>
              <p className="text-xs text-white/70 max-w-md mx-auto leading-relaxed">
                {t('modpackUpdate.notTrackedMessage') || (
                  <>
                    Server <strong className="text-white">{serverName}</strong> does not have active modpack metadata
                    attached (or was created as a vanilla/custom server). Interactive updates are available for
                    servers installed via Modrinth, CurseForge, or FTB.
                  </>
                )}
              </p>
            </div>
          )}

          {/* FETCH ERROR STATE */}
          {fetchState === 'error' && (
            <div className="p-5 bg-red-500/10 border border-red-500/20 rounded-xl text-center space-y-3">
              <FaTimesCircle className="w-8 h-8 text-red-400 mx-auto" />
              <h3 className="text-base font-semibold text-white">
                {t('modpackUpdate.failedLoadTitle') || 'Failed to Load Versions'}
              </h3>
              <p className="text-xs text-red-300 max-w-md mx-auto leading-relaxed">
                {fetchError}
              </p>
              <button
                onClick={fetchVersions}
                className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-xs font-medium inline-flex items-center gap-1.5"
              >
                <FaSyncAlt /> {t('modpackUpdate.retryQuery') || 'Retry Query'}
              </button>
            </div>
          )}

          {/* READY STATE: FORM & VERSION SELECTION */}
          {fetchState === 'success' && updateState === 'idle' && (
            <>
              {/* Current Version Card */}
              <div className="flex items-center justify-between p-3.5 bg-white/5 rounded-xl border border-white/10">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-emerald-500/20 rounded-lg text-emerald-400">
                    <FaBoxOpen className="w-4 h-4" />
                  </div>
                  <div>
                    <span className="text-xs text-white/40 block">
                      {t('modpackUpdate.currentVersion') || 'Currently Installed'}
                    </span>
                    <span className="text-sm font-semibold text-white">
                      {modpackData?.current_version_name || modpackData?.current_version_id || currentVersion || 'Unknown'}
                    </span>
                  </div>
                </div>
                <span className="text-xs px-2.5 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-lg font-medium">
                  {t('modpackUpdate.activeRelease') || 'Active Release'}
                </span>
              </div>

              {/* Target Version Selector */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-white/80 flex items-center justify-between">
                  <span>{t('modpackUpdate.targetVersion') || 'Target Update Version'}</span>
                  {selectedVersionObj?.is_current && (
                    <span className="text-amber-400 text-[11px] font-normal">
                      {t('modpackUpdate.reinstallWarning') || '(Selected version is already installed — updating will reinstall/repair files)'}
                    </span>
                  )}
                </label>
                <select
                  value={selectedVersionId}
                  onChange={(e) => setSelectedVersionId(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-black/40 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:border-brand-500 transition-colors"
                >
                  {modpackData?.versions?.map((v) => (
                    <option key={v.version_id} value={v.version_id} className="bg-ink-900 text-white">
                      {v.version_name || v.version_number} 
                      {v.game_versions?.length ? ` · MC ${v.game_versions.join(', ')}` : ''}
                      {v.loaders?.length ? ` [${v.loaders.join(', ')}]` : ''}
                      {v.is_current ? ` (${t('modpackUpdate.currentBadge') || 'Current'})` : ''}
                    </option>
                  ))}
                </select>

                {/* Selected Version Meta Badges */}
                {selectedVersionObj && (
                  <div className="flex items-center gap-2 pt-1 flex-wrap">
                    {selectedVersionObj.game_versions?.map((gv) => (
                      <span key={gv} className="text-[11px] px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30 flex items-center gap-1">
                        <FaCube className="w-2.5 h-2.5" /> MC {gv}
                      </span>
                    ))}
                    {selectedVersionObj.loaders?.map((ld) => (
                      <span key={ld} className="text-[11px] px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 flex items-center gap-1">
                        <FaPuzzlePiece className="w-2.5 h-2.5" /> {ld}
                      </span>
                    ))}
                    {selectedVersionObj.date_published && (
                      <span className="text-[11px] px-2 py-0.5 rounded bg-white/10 text-white/60 flex items-center gap-1">
                        <FaCalendarAlt className="w-2.5 h-2.5" />
                        {new Date(selectedVersionObj.date_published).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Changelog Viewer */}
              {selectedVersionObj && (
                <div className="space-y-1.5">
                  <div
                    className="flex items-center justify-between text-xs font-semibold text-white/70 cursor-pointer select-none py-1"
                    onClick={() => setShowChangelog(!showChangelog)}
                  >
                    <span className="flex items-center gap-1.5">
                      <FaFileAlt className="text-brand-400" />
                      {t('modpackUpdate.changelogTitle') || 'Changelog & Release Notes'}
                    </span>
                    <button className="text-white/40 hover:text-white flex items-center gap-1">
                      {showChangelog ? <FaChevronUp className="w-3 h-3" /> : <FaChevronDown className="w-3 h-3" />}
                    </button>
                  </div>
                  {showChangelog && (
                    <div className="max-h-48 overflow-y-auto bg-black/30 border border-white/10 rounded-xl p-3.5">
                      <SimpleChangelogRenderer
                        content={selectedVersionObj.changelog}
                        emptyText={t('modpackUpdate.noChangelog')}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Safety Backup & Automated Safeguards Box */}
              <div className="p-4 bg-white/5 border border-white/10 rounded-xl space-y-3">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={createBackup}
                    onChange={(e) => setCreateBackup(e.target.checked)}
                    className="mt-1 w-4 h-4 rounded border-white/20 bg-black/40 text-brand-600 focus:ring-brand-500 accent-brand-500 cursor-pointer"
                  />
                  <div>
                    <span className="text-sm font-medium text-white flex items-center gap-1.5">
                      <FaArchive className="text-brand-400 w-3.5 h-3.5" />
                      {t('modpackUpdate.safetyBackupLabel') || 'Create pre-update safety backup (Recommended)'}
                    </span>
                    <p className="text-xs text-white/50 mt-0.5">
                      {t('modpackUpdate.safetyBackupNotice') || 'Automatically archives existing world, configurations, and mods before updating.'}
                    </p>
                  </div>
                </label>

                <div className="pt-2 border-t border-white/5 space-y-2">
                  <div className="flex items-start gap-2 text-xs text-white/60">
                    <FaTrash className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />
                    <span>
                      <strong className="text-white/80">{t('modpackUpdate.duplicateCleanupTitle') || 'Duplicate Cleanup:'}</strong>{' '}
                      {t('modpackUpdate.duplicateCleanupDesc') || 'Outdated and replaced mod JARs from the old version will be cleaned up to avoid duplicate mod conflicts.'}
                    </span>
                  </div>
                  <div className="flex items-start gap-2 text-xs text-white/60">
                    <FaShieldAlt className="w-3.5 h-3.5 text-teal-400 flex-shrink-0 mt-0.5" />
                    <span>
                      <strong className="text-white/80">{t('modpackUpdate.clientFilterTitle') || 'Client Mod Filter:'}</strong>{' '}
                      {t('modpackUpdate.clientFilterDesc') || 'Post-update inspection will automatically filter client-only mods while strictly preserving your allowlist.'}
                    </span>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* UPDATING EXECUTION PIPELINE */}
          {updateState === 'updating' && (
            <div className="py-6 space-y-6">
              <div className="text-center space-y-2">
                <div className="w-12 h-12 rounded-2xl bg-brand-500/20 border border-brand-500/40 text-brand-400 flex items-center justify-center mx-auto animate-pulse">
                  <FaSyncAlt className="w-6 h-6 animate-spin" />
                </div>
                <h3 className="text-base font-semibold text-white">
                  {t('modpackUpdate.progressTitle') || 'Updating Modpack...'}
                </h3>
                <p className="text-xs text-white/50 max-w-sm mx-auto">
                  {t('modpackUpdate.progressSubtitle', { version: selectedVersionObj?.version_name || selectedVersionId }) || (
                    <>Applying target release <strong className="text-white">{selectedVersionObj?.version_name || selectedVersionId}</strong>. Please do not close this dialog.</>
                  )}
                </p>
              </div>

              {/* Progress Steps List */}
              <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
                {PIPELINE_STEPS.map((step, idx) => {
                  const isDone = activeStepIndex > idx;
                  const isActive = activeStepIndex === idx;

                  return (
                    <div key={step.id} className="flex items-center gap-3">
                      <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0">
                        {isDone ? (
                          <FaCheckCircle className="w-5 h-5 text-emerald-400" />
                        ) : isActive ? (
                          <FaSpinner className="w-4 h-4 text-brand-400 animate-spin" />
                        ) : (
                          <div className="w-2.5 h-2.5 rounded-full bg-white/20" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className={`text-xs font-medium ${isActive ? 'text-white' : isDone ? 'text-white/70' : 'text-white/30'}`}>
                          {t(`modpackUpdate.${step.key}`) || step.label}
                        </div>
                        <div className="text-[11px] text-white/40 truncate">
                          {step.desc}
                        </div>
                      </div>
                      {isDone && (
                        <span className="text-[10px] text-emerald-400 font-mono">Done</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* UPDATE ERROR STATE */}
          {updateState === 'error' && (
            <div className="p-5 bg-red-500/10 border border-red-500/20 rounded-xl space-y-3">
              <div className="flex items-center gap-3">
                <FaTimesCircle className="w-6 h-6 text-red-400 flex-shrink-0" />
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    {t('modpackUpdate.updateError') || 'Modpack Update Failed'}
                  </h3>
                  <p className="text-xs text-red-300 mt-0.5">{updateError}</p>
                </div>
              </div>
              <p className="text-xs text-white/50 pt-2 border-t border-red-500/20">
                Any changes made prior to the error were safely handled. If a pre-update safety backup was created,
                you can restore your server at any time from the Backups panel.
              </p>
            </div>
          )}

          {/* UPDATE SUCCESS SUMMARY */}
          {updateState === 'success' && updateResult && (
            <div className="space-y-4">
              <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-center space-y-1.5">
                <FaCheckCircle className="w-8 h-8 text-emerald-400 mx-auto" />
                <h3 className="text-base font-semibold text-white">
                  {t('modpackUpdate.completedTitle') || 'Modpack Update Completed!'}
                </h3>
                <p className="text-xs text-white/70">
                  {t('modpackUpdate.updateSuccessDetail', { from: updateResult.previous_version || 'previous', to: updateResult.updated_version }) || (
                    <>Successfully updated to version <strong className="text-emerald-300 font-mono">{updateResult.updated_version}</strong></>
                  )}
                </p>
              </div>

              {/* Metrics Grid */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 bg-white/5 border border-white/10 rounded-xl">
                  <div className="flex items-center gap-2 text-xs text-white/50 mb-1">
                    <FaArchive className="text-blue-400" />
                    <span>{t('modpackUpdate.safetyBackup') || 'Safety Backup'}</span>
                  </div>
                  <div className="text-xs font-mono text-white truncate" title={updateResult.backup_created || 'None'}>
                    {updateResult.backup_created || t('modpackUpdate.backupSkipped') || 'Disabled / Skipped'}
                  </div>
                </div>

                <div className="p-3 bg-white/5 border border-white/10 rounded-xl">
                  <div className="flex items-center gap-2 text-xs text-white/50 mb-1">
                    <FaTrash className="text-amber-400" />
                    <span>{t('modpackUpdate.cleanedModsTitle') || 'Outdated Mods Cleaned'}</span>
                  </div>
                  <div className="text-sm font-semibold text-white">
                    {t('modpackUpdate.modsCleanedCount', { count: updateResult.mods_cleaned?.length || 0 })}
                  </div>
                </div>

                <div className="p-3 bg-white/5 border border-white/10 rounded-xl">
                  <div className="flex items-center gap-2 text-xs text-white/50 mb-1">
                    <FaCube className="text-emerald-400" />
                    <span>{t('modpackUpdate.newModsTitle') || 'New Mods Added'}</span>
                  </div>
                  <div className="text-sm font-semibold text-white">
                    {t('modpackUpdate.modsAddedCount', { count: updateResult.mods_added?.length || 0 })}
                  </div>
                </div>

                <div className="p-3 bg-white/5 border border-white/10 rounded-xl">
                  <div className="flex items-center gap-2 text-xs text-white/50 mb-1">
                    <FaShieldAlt className="text-teal-400" />
                    <span>{t('modpackUpdate.clientModsTitle') || 'Client Mods Filtered'}</span>
                  </div>
                  <div className="text-sm font-semibold text-white">
                    {t('modpackUpdate.clientModsFilteredCount', { count: updateResult.client_mods_filtered?.length || 0 })}
                  </div>
                </div>
              </div>

              {/* Cleaned Mods Inspection */}
              {((updateResult.mods_cleaned?.length || 0) > 0 || (updateResult.client_mods_filtered?.length || 0) > 0) && (
                <div className="border border-white/10 rounded-xl overflow-hidden bg-white/5">
                  <button
                    onClick={() => setShowCleanedDetails(!showCleanedDetails)}
                    className="w-full px-4 py-2.5 flex items-center justify-between text-xs text-white/70 hover:bg-white/5 transition-colors"
                  >
                    <span>
                      {t('modpackUpdate.inspectFiles') || 'Inspect Cleaned & Filtered Files'} ({ (updateResult.mods_cleaned?.length || 0) + (updateResult.client_mods_filtered?.length || 0) })
                    </span>
                    {showCleanedDetails ? <FaChevronUp /> : <FaChevronDown />}
                  </button>
                  {showCleanedDetails && (
                    <div className="p-3 border-t border-white/10 max-h-40 overflow-y-auto space-y-2 text-xs font-mono">
                      {updateResult.mods_cleaned?.length > 0 && (
                        <div>
                          <div className="text-[11px] text-amber-400 font-sans font-semibold mb-1">
                            {t('modpackUpdate.cleanedModsListTitle') || 'Cleaned Outdated Mods:'}
                          </div>
                          {updateResult.mods_cleaned.map((file) => (
                            <div key={file} className="text-white/60 pl-2 truncate">• {file}</div>
                          ))}
                        </div>
                      )}
                      {updateResult.client_mods_filtered?.length > 0 && (
                        <div className="pt-1">
                          <div className="text-[11px] text-teal-400 font-sans font-semibold mb-1">
                            {t('modpackUpdate.isolatedClientModsTitle') || 'Isolated Client-Only Mods:'}
                          </div>
                          {updateResult.client_mods_filtered.map((file) => (
                            <div key={file} className="text-white/60 pl-2 truncate">• {file}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-end gap-3 p-5 border-t border-white/10 bg-white/[0.02]">
          {updateState === 'success' ? (
            <button
              onClick={onClose}
              className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors"
            >
              {t('common.close') || 'Close'}
            </button>
          ) : updateState === 'error' ? (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-white/70 hover:text-white rounded-xl text-sm transition-colors"
              >
                {t('common.cancel') || 'Cancel'}
              </button>
              <button
                onClick={() => setUpdateState('idle')}
                className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors"
              >
                {t('common.tryAgain') || 'Try Again'}
              </button>
            </>
          ) : fetchState === 'not_modpack' || fetchState === 'error' ? (
            <button
              onClick={onClose}
              className="px-5 py-2 bg-white/10 hover:bg-white/20 text-white rounded-xl text-sm font-medium transition-colors"
            >
              {t('common.close') || 'Close'}
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                disabled={updateState === 'updating'}
                className="px-4 py-2 text-white/70 hover:text-white rounded-xl text-sm transition-colors disabled:opacity-30"
              >
                {t('common.cancel') || 'Cancel'}
              </button>
              <button
                onClick={handleStartUpdate}
                disabled={!selectedVersionId || updateState === 'updating' || fetchState !== 'success'}
                className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium flex items-center gap-2 transition-colors disabled:opacity-50"
              >
                {updateState === 'updating' ? (
                  <>
                    <FaSpinner className="animate-spin" /> {t('modpackUpdate.updating') || 'Updating...'}
                  </>
                ) : (
                  <>
                    <FaArrowCircleUp /> {t('modpackUpdate.updateNowButton') || 'Update Modpack Now'}
                  </>
                )}
              </button>
            </>
          )}
        </div>

      </div>
    </div>
  );
}
