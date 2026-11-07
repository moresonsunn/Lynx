import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FaSyncAlt, FaCheckCircle, FaExclamationTriangle, FaTimes, FaSpinner
} from 'react-icons/fa';
import { API, authHeaders } from '../../context/AppContext';
import { useTranslation } from '../../i18n';

export default function ModpackUpdateModal({
  isOpen,
  onClose,
  serverName,
  currentVersion = '',
  onUpdateSuccess,
}) {
  const { t } = useTranslation();

  const [fetchState, setFetchState] = useState('idle'); // 'loading' | 'success' | 'not_modpack' | 'error'
  const [fetchError, setFetchError] = useState('');
  const [modpackData, setModpackData] = useState(null);

  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [createBackup, setCreateBackup] = useState(true);

  const [updateState, setUpdateState] = useState('idle'); // 'idle' | 'updating' | 'success' | 'error'
  const [updateError, setUpdateError] = useState('');
  const [updateResult, setUpdateResult] = useState(null);

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

      const versions = data.versions || [];
      if (versions.length > 0) {
        const candidate = versions.find(v => !v.is_current) || versions[0];
        setSelectedVersionId(candidate.version_id);
      }
    } catch (err) {
      setFetchError(err.message || 'Failed to load versions');
      setFetchState('error');
    }
  }, [serverName]);

  useEffect(() => {
    if (isOpen) {
      fetchVersions();
    } else {
      setFetchState('idle');
      setUpdateState('idle');
      setUpdateResult(null);
      setUpdateError('');
    }
  }, [isOpen, fetchVersions]);

  const selectedVersionObj = useMemo(() => {
    if (!modpackData?.versions) return null;
    return modpackData.versions.find(v => String(v.version_id) === String(selectedVersionId)) || null;
  }, [modpackData, selectedVersionId]);

  const handleStartUpdate = async () => {
    if (!selectedVersionId || updateState === 'updating') return;

    setUpdateState('updating');
    setUpdateError('');

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

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Update failed (HTTP ${res.status})`);
      }

      const result = await res.json();
      setUpdateResult(result);
      setUpdateState('success');
      onUpdateSuccess?.(result);
    } catch (err) {
      setUpdateError(err.message || 'Update failed');
      setUpdateState('error');
    }
  };

  if (!isOpen) return null;

  const installedLabel = modpackData?.current_version_name || modpackData?.current_version_id || currentVersion || '—';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={updateState === 'updating' ? undefined : onClose}
      />

      <div className="relative bg-ink-900 border border-white/10 rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden animate-in fade-in zoom-in-95 duration-200 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/10">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full bg-brand-500/20 text-brand-400 flex items-center justify-center flex-shrink-0">
              <FaSyncAlt className={updateState === 'updating' ? 'animate-spin' : ''} />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-white truncate">
                {t('modpackUpdate.modalTitle') || 'Update Modpack'}
              </h2>
              <p className="text-xs text-white/40 truncate">
                {modpackData?.pack_id
                  ? `${serverName} · ${modpackData.pack_id}${modpackData.provider ? ` (${modpackData.provider})` : ''}`
                  : serverName}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={updateState === 'updating'}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-40"
          >
            <FaTimes />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 overflow-y-auto flex-1 min-h-0 space-y-4">
          {fetchState === 'loading' && (
            <div className="flex items-center justify-center py-8 text-sm text-white/40">
              <FaSpinner className="animate-spin mr-2" />
              {t('modpackUpdate.checkingVersions') || 'Checking available versions...'}
            </div>
          )}

          {fetchState === 'not_modpack' && (
            <div className="p-3.5 bg-yellow-500/10 border border-yellow-500/20 rounded-lg text-xs text-yellow-200/80 space-y-1">
              <div className="font-semibold text-yellow-300">
                {t('modpackUpdate.notTrackedTitle') || 'Not a Tracked Modpack Server'}
              </div>
              <div>
                {t('modpackUpdate.notTrackedMessage') || `Server ${serverName} does not have tracked modpack metadata.`} ({serverName})
              </div>
            </div>
          )}

          {fetchState === 'error' && (
            <div className="p-3.5 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-300 flex items-center justify-between gap-3">
              <span>{fetchError}</span>
              <button
                onClick={fetchVersions}
                className="px-3 py-1.5 bg-white/10 hover:bg-white/20 text-white rounded-lg flex items-center gap-1.5 flex-shrink-0"
              >
                <FaSyncAlt /> {t('modpackUpdate.retryQuery') || 'Retry Query'}
              </button>
            </div>
          )}

          {fetchState === 'success' && (
            <>
              <div className="flex items-center justify-between text-sm bg-white/5 border border-white/10 rounded-lg px-3.5 py-2.5">
                <span className="text-white/50">{t('modpackUpdate.currentVersion') || 'Current version'}</span>
                <span className="text-white font-mono text-xs">{installedLabel}</span>
              </div>

              <div>
                <label className="block text-xs text-white/50 mb-1.5">
                  {t('modpackUpdate.targetVersion') || 'Target version'}
                </label>
                <select
                  value={selectedVersionId}
                  onChange={(e) => setSelectedVersionId(e.target.value)}
                  disabled={updateState === 'updating' || updateState === 'success'}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500/50 disabled:opacity-60"
                >
                  {modpackData?.versions?.map((v) => (
                    <option key={v.version_id} value={v.version_id} className="bg-ink-900 text-white">
                      {v.version_name || v.version_number || v.version_id}
                      {v.game_versions?.length ? ` · MC ${v.game_versions.join(', ')}` : ''}
                      {v.is_current ? ` (${t('modpackUpdate.currentBadge') || 'Current'})` : ''}
                    </option>
                  ))}
                </select>
              </div>

              {selectedVersionObj?.changelog?.trim() && updateState !== 'success' && (
                <div>
                  <div className="text-xs text-white/50 mb-1.5">
                    {t('modpackUpdate.changelogTitle') || 'Release notes'}
                  </div>
                  <div className="max-h-32 overflow-y-auto bg-white/5 border border-white/10 rounded-lg p-3 text-xs text-white/60 whitespace-pre-wrap">
                    {selectedVersionObj.changelog.trim()}
                  </div>
                </div>
              )}

              {updateState !== 'success' && (
                <label className="flex items-center gap-2 text-sm text-white/70 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={createBackup}
                    onChange={(e) => setCreateBackup(e.target.checked)}
                    disabled={updateState === 'updating'}
                    className="accent-brand-500"
                  />
                  <span>{t('modpackUpdate.safetyBackupLabel') || 'Create backup before updating'}</span>
                </label>
              )}

              {updateState === 'updating' && (
                <div className="p-3 bg-white/5 border border-white/10 rounded-lg flex items-center gap-2.5 text-xs text-white/70">
                  <FaSpinner className="animate-spin text-brand-400 flex-shrink-0" />
                  <span>{t('modpackUpdate.progressTitle') || 'Updating modpack...'}</span>
                </div>
              )}

              {updateState === 'error' && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-300">
                  <FaExclamationTriangle className="inline mr-1.5" />
                  {updateError}
                </div>
              )}

              {updateState === 'success' && updateResult && (
                <div className="p-3.5 bg-green-500/10 border border-green-500/20 rounded-lg text-xs space-y-1.5">
                  <div className="text-green-300 font-medium">
                    <FaCheckCircle className="inline mr-1.5" />
                    {t('modpackUpdate.updateSuccessDetail', {
                      from: updateResult.previous_version || installedLabel,
                      to: updateResult.updated_version,
                    })}
                  </div>
                  <div className="text-white/60 flex flex-wrap gap-x-2.5 gap-y-1">
                    <span>{t('modpackUpdate.modsAddedCount', { count: updateResult.mods_added?.length || 0 })}</span>
                    <span>·</span>
                    <span>{t('modpackUpdate.modsCleanedCount', { count: updateResult.mods_cleaned?.length || 0 })}</span>
                    <span>·</span>
                    <span>{t('modpackUpdate.clientModsFilteredCount', { count: updateResult.client_mods_filtered?.length || 0 })}</span>
                  </div>
                  {updateResult.backup_created && (
                    <div className="text-white/40 font-mono truncate">
                      {t('modpackUpdate.safetyBackup')}: {updateResult.backup_created}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-5 pt-0">
          {updateState === 'success' || fetchState === 'not_modpack' || fetchState === 'error' ? (
            <button
              onClick={onClose}
              className="px-5 py-2.5 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm font-medium transition-colors"
            >
              {t('common.close') || 'Close'}
            </button>
          ) : updateState === 'error' ? (
            <>
              <button
                onClick={onClose}
                className="px-5 py-2.5 text-white/70 hover:text-white hover:bg-white/10 rounded-lg transition-colors text-sm font-medium"
              >
                {t('common.cancel') || 'Cancel'}
              </button>
              <button
                onClick={() => setUpdateState('idle')}
                className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors text-sm font-medium"
              >
                {t('common.tryAgain') || 'Try Again'}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onClose}
                disabled={updateState === 'updating'}
                className="px-5 py-2.5 text-white/70 hover:text-white hover:bg-white/10 rounded-lg transition-colors text-sm font-medium disabled:opacity-50"
              >
                {t('common.cancel') || 'Cancel'}
              </button>
              <button
                onClick={handleStartUpdate}
                disabled={!selectedVersionId || updateState === 'updating' || fetchState !== 'success'}
                className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors text-sm font-medium flex items-center gap-2 disabled:opacity-50"
              >
                {updateState === 'updating' && (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                )}
                {updateState === 'updating'
                  ? (t('modpackUpdate.updating') || 'Updating...')
                  : (t('modpackUpdate.updateNowButton') || 'Update Modpack Now')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
