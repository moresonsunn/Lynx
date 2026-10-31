import React, { useEffect, useState } from 'react';
import {
  FaDownload,
  FaClock,
  FaCloud,
  FaTrash,
  FaSave,
  FaSync,
  FaCalendarAlt,
  FaFolderOpen,
  FaUndo,
  FaPlus,
  FaPuzzlePiece,
} from 'react-icons/fa';
import { API, authHeaders } from '../../context/AppContext';
import { useTranslation } from '../../i18n';

export default function BackupsPanel({ serverName, onOpenInFiles }) {
  const { t } = useTranslation();
  const [list, setList] = useState([]);
  const [modFolders, setModFolders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [schedule, setSchedule] = useState(null);
  const [scheduleForm, setScheduleForm] = useState({
    enabled: false,
    interval_hours: 24,
    retention_count: 10,
    retention_days: 30,
    remote_upload: false,
    compression: 'zip',
  });
  const [showSchedule, setShowSchedule] = useState(false);
  const [sourceFilter, setSourceFilter] = useState('all'); // 'all' | 'panel' | 'mod'

  async function refresh() {
    setLoading(true);
    try {
      const r = await fetch(`${API}/servers/${encodeURIComponent(serverName)}/backups`, {
        headers: authHeaders(),
      });
      const d = await r.json();
      setList(d.items || d.backups || []);
      setModFolders(Array.isArray(d.mod_folders) ? d.mod_folders : []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  async function loadSchedule() {
    try {
      const r = await fetch(`${API}/backup-schedules/${encodeURIComponent(serverName)}`, {
        headers: authHeaders(),
      });
      if (r.ok) {
        const data = await r.json();
        if (data.schedule && Object.keys(data.schedule).length > 0) {
          setSchedule(data.schedule);
          setScheduleForm((prev) => ({ ...prev, ...data.schedule }));
        }
      }
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refresh();
    loadSchedule();
  }, [serverName]);

  async function createBackup() {
    setCreating(true);
    try {
      await fetch(`${API}/servers/${encodeURIComponent(serverName)}/backups`, {
        method: 'POST',
        headers: authHeaders(),
      });
      setTimeout(refresh, 1500);
    } catch {
      // ignore
    } finally {
      setCreating(false);
    }
  }

  async function restore(file) {
    if (!confirm(`Restore backup "${file}"? Stop the server before restoring for safety.`)) return;
    await fetch(
      `${API}/servers/${encodeURIComponent(serverName)}/restore?file=${encodeURIComponent(file)}`,
      {
        method: 'POST',
        headers: authHeaders(),
      }
    );
    alert('Backup restore completed.');
  }

  async function downloadBackup(b) {
    try {
      const r = await fetch(
        `${API}/servers/${encodeURIComponent(serverName)}/backups/download?file=${encodeURIComponent(b.file)}`,
        { headers: authHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = b.name || String(b.file).split('/').pop() || 'backup.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Download failed: ${e.message || e}`);
    }
  }

  async function deleteBackup(file) {
    if (!confirm(`Delete backup "${file}"? This cannot be undone.`)) return;
    await fetch(
      `${API}/servers/${encodeURIComponent(serverName)}/backups/${encodeURIComponent(file)}`,
      {
        method: 'DELETE',
        headers: authHeaders(),
      }
    );
    refresh();
  }

  async function saveSchedule() {
    try {
      await fetch(`${API}/backup-schedules/${encodeURIComponent(serverName)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(scheduleForm),
      });
      loadSchedule();
      setShowSchedule(false);
    } catch {
      // ignore
    }
  }

  async function deleteSchedule() {
    try {
      await fetch(`${API}/backup-schedules/${encodeURIComponent(serverName)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      setSchedule(null);
      setScheduleForm({
        enabled: false,
        interval_hours: 24,
        retention_count: 10,
        retention_days: 30,
        remote_upload: false,
        compression: 'zip',
      });
    } catch {
      // ignore
    }
  }

  function formatSize(bytes) {
    if (!bytes) return '0 B';
    const mb = bytes / 1024 / 1024;
    if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
    if (mb >= 1) return `${mb.toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  function formatDate(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleString();
  }

  const modBackupsCount = list.filter((b) => b.source === 'mod').length;
  const panelBackupsCount = list.filter((b) => b.source !== 'mod').length;
  const filteredList = list.filter((b) => {
    if (sourceFilter === 'mod') return b.source === 'mod';
    if (sourceFilter === 'panel') return b.source !== 'mod';
    return true;
  });

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="rounded-xl bg-white/[0.03] border border-white/10 p-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="text-base font-semibold text-white">Backups</h3>
            <span className="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-white/60">
              {list.length} total
            </span>
            {modBackupsCount > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-purple-500/15 border border-purple-500/25 text-purple-300">
                <FaPuzzlePiece className="text-[10px]" />
                {modBackupsCount} Mod Backup{modBackupsCount === 1 ? '' : 's'}
              </span>
            )}
            {schedule?.enabled && (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-emerald-500/15 border border-emerald-500/25 text-emerald-300 rounded text-xs">
                <FaClock className="w-3 h-3" />
                Every {schedule.interval_hours}h
              </span>
            )}
          </div>
          <p className="text-xs text-white/45 mt-1">
            Includes Panel backups and automatic Modpack backups (SimpleBackups, FTB Backups, etc.).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
          >
            <FaSync className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => setShowSchedule(!showSchedule)}
            className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs border transition-colors ${
              showSchedule
                ? 'bg-brand-500/20 border-brand-500/40 text-brand-300'
                : 'bg-white/5 hover:bg-white/10 border-white/10 text-white/75'
            }`}
          >
            <FaCalendarAlt className="w-3 h-3" />
            Schedule
          </button>
          <button
            onClick={createBackup}
            disabled={creating}
            className="px-3 py-1.5 bg-brand-500 hover:bg-brand-400 rounded-lg flex items-center gap-1.5 text-xs font-medium text-white disabled:opacity-50 transition-colors"
          >
            <FaPlus className="w-3 h-3" />
            {creating ? 'Creating…' : 'Create Backup'}
          </button>
        </div>
      </div>

      {/* Connected Modpack Backup Folders Bar */}
      {modFolders.length > 0 && (
        <div className="rounded-xl bg-white/[0.02] border border-white/10 px-4 py-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap text-xs text-white/60">
            <FaPuzzlePiece className="text-purple-400" />
            <span>Connected Modpack Backup Folders:</span>
            {modFolders.map((folder) => (
              <button
                key={folder.folder}
                onClick={() => onOpenInFiles && onOpenInFiles(folder.folder)}
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-white/80 font-mono text-[11px] transition-colors"
                title={`Open /${folder.folder} in File Manager`}
              >
                <FaFolderOpen className="text-amber-400/80 text-[10px]" />
                /{folder.folder} ({folder.archive_count})
              </button>
            ))}
          </div>
          {list.length > 0 && (
            <div className="inline-flex rounded-lg bg-white/5 p-0.5 border border-white/10 text-xs">
              {[
                { id: 'all', label: `All (${list.length})` },
                { id: 'panel', label: `Panel (${panelBackupsCount})` },
                { id: 'mod', label: `Modpack (${modBackupsCount})` },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setSourceFilter(tab.id)}
                  className={`px-2.5 py-1 rounded-md transition-colors ${
                    sourceFilter === tab.id
                      ? 'bg-brand-500 text-white font-medium'
                      : 'text-white/60 hover:text-white'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Schedule Configuration */}
      {showSchedule && (
        <div className="bg-white/[0.03] border border-white/10 rounded-xl p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-white/70 mb-3 flex items-center gap-2">
            <FaClock className="text-brand-400" />
            Automatic Backup Schedule
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <label className="flex items-center gap-2.5 cursor-pointer sm:col-span-2 lg:col-span-4">
              <input
                type="checkbox"
                checked={scheduleForm.enabled}
                onChange={(e) => setScheduleForm((prev) => ({ ...prev, enabled: e.target.checked }))}
                className="w-4 h-4 rounded bg-white/10 border-white/20 text-brand-500"
              />
              <span className="text-white text-xs">Enable scheduled panel backups</span>
            </label>

            <div>
              <label className="block text-xs text-white/50 mb-1">Interval</label>
              <select
                value={scheduleForm.interval_hours}
                onChange={(e) =>
                  setScheduleForm((prev) => ({ ...prev, interval_hours: parseInt(e.target.value, 10) }))
                }
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-white text-xs"
              >
                <option value={1}>Every hour</option>
                <option value={6}>Every 6 hours</option>
                <option value={12}>Every 12 hours</option>
                <option value={24}>Every 24 hours</option>
                <option value={48}>Every 2 days</option>
                <option value={168}>Weekly</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-white/50 mb-1">Keep last N backups</label>
              <input
                type="number"
                min={1}
                max={100}
                value={scheduleForm.retention_count}
                onChange={(e) =>
                  setScheduleForm((prev) => ({
                    ...prev,
                    retention_count: parseInt(e.target.value, 10) || 10,
                  }))
                }
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-white text-xs"
              />
            </div>

            <div>
              <label className="block text-xs text-white/50 mb-1">Max age (days)</label>
              <input
                type="number"
                min={1}
                max={365}
                value={scheduleForm.retention_days}
                onChange={(e) =>
                  setScheduleForm((prev) => ({
                    ...prev,
                    retention_days: parseInt(e.target.value, 10) || 30,
                  }))
                }
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-white text-xs"
              />
            </div>

            <div>
              <label className="block text-xs text-white/50 mb-1">Compression</label>
              <select
                value={scheduleForm.compression}
                onChange={(e) => setScheduleForm((prev) => ({ ...prev, compression: e.target.value }))}
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-white text-xs"
              >
                <option value="zip">ZIP</option>
                <option value="tar.gz">TAR.GZ</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 mt-4 pt-3 border-t border-white/10">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={scheduleForm.remote_upload}
                onChange={(e) =>
                  setScheduleForm((prev) => ({ ...prev, remote_upload: e.target.checked }))
                }
                className="w-4 h-4 rounded bg-white/10 border-white/20 text-brand-500"
              />
              <span className="text-white/70 text-xs flex items-center gap-1.5">
                <FaCloud className="text-blue-400 w-3.5 h-3.5" />
                Upload to remote storage
              </span>
            </label>

            <div className="flex gap-2">
              <button
                onClick={saveSchedule}
                className="px-3 py-1.5 bg-brand-500 hover:bg-brand-400 rounded-lg flex items-center gap-1.5 text-xs text-white"
              >
                <FaSave className="w-3 h-3" />
                Save Schedule
              </button>
              {schedule && (
                <button
                  onClick={deleteSchedule}
                  className="px-3 py-1.5 bg-red-500/15 hover:bg-red-500/25 text-red-300 rounded-lg flex items-center gap-1.5 text-xs"
                >
                  <FaTrash className="w-3 h-3" />
                  Remove
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Backup List */}
      <div className="rounded-xl bg-white/[0.02] border border-white/10 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-12">
            <FaSync className="w-5 h-5 text-white/30 animate-spin" />
          </div>
        ) : filteredList.length > 0 ? (
          <div className="divide-y divide-white/10">
            {filteredList.map((b) => {
              const isMod = b.source === 'mod';
              return (
                <div
                  key={b.file}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 hover:bg-white/[0.03] transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white text-sm font-medium truncate">
                        {b.name || b.file}
                      </span>
                      {isMod ? (
                        <span className="text-[11px] px-2 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/25">
                          Mod Backup ({b.folder || 'backups'})
                        </span>
                      ) : (
                        <span className="text-[11px] px-2 py-0.5 rounded bg-brand-500/15 text-brand-300 border border-brand-500/25">
                          Panel Backup
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-white/45 mt-1">
                      <span>{formatSize(b.size)}</span>
                      {b.modified && <span>{formatDate(b.modified)}</span>}
                      {b.file && b.file !== b.name && (
                        <span className="font-mono text-[11px] text-white/35 truncate">{b.file}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {isMod && b.folder && onOpenInFiles && (
                      <button
                        onClick={() => onOpenInFiles(b.folder)}
                        className="px-2.5 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
                        title={`Open /${b.folder} in File Manager`}
                      >
                        <FaFolderOpen className="text-amber-400/80" />
                        Folder
                      </button>
                    )}
                    <button
                      onClick={() => downloadBackup(b)}
                      className="px-2.5 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
                      title="Download archive"
                    >
                      <FaDownload className="text-emerald-400" />
                      Download
                    </button>
                    <button
                      onClick={() => restore(b.file)}
                      className="px-2.5 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
                    >
                      <FaUndo className="text-brand-400" />
                      Restore
                    </button>
                    <button
                      onClick={() => deleteBackup(b.file)}
                      className="px-2.5 py-1.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 rounded-lg text-xs text-red-300 transition-colors"
                      title="Delete backup"
                    >
                      <FaTrash className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-white/40">
            <FaDownload className="text-2xl mb-2 opacity-50" />
            <span className="text-sm">{t('servers.noBackups') || 'No backups found'}</span>
            <span className="text-xs text-white/30 mt-1">
              Create a backup manually, enable the scheduler, or let your modpack backup mod write to /backups or /simplebackups.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
