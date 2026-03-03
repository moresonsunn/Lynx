import React, { useEffect, useState } from 'react';
import { FaDownload, FaClock, FaCloud, FaTrash, FaSave, FaSync, FaCalendarAlt } from 'react-icons/fa';
import { API, authHeaders } from '../../context/AppContext';
import { useTranslation } from '../../i18n';

export default function BackupsPanel({ serverName }) {
  const { t } = useTranslation();
  const [list, setList] = useState([]);
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

  async function refresh() {
    setLoading(true);
    try {
      const r = await fetch(`${API}/servers/${encodeURIComponent(serverName)}/backups`, { headers: authHeaders() });
      const d = await r.json();
      setList(d.items || []);
    } catch {} finally {
      setLoading(false);
    }
  }

  async function loadSchedule() {
    try {
      const r = await fetch(`${API}/api/backup-schedules/${encodeURIComponent(serverName)}`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        if (data.schedule && Object.keys(data.schedule).length > 0) {
          setSchedule(data.schedule);
          setScheduleForm(prev => ({ ...prev, ...data.schedule }));
        }
      }
    } catch {}
  }

  useEffect(() => { refresh(); loadSchedule(); }, [serverName]);

  async function createBackup() {
    setCreating(true);
    try {
      await fetch(`${API}/servers/${encodeURIComponent(serverName)}/backups`, {
        method: 'POST',
        headers: authHeaders(),
      });
      refresh();
    } catch {} finally {
      setCreating(false);
    }
  }

  async function restore(file) {
    if (!confirm(`Restore backup "${file}"? The server should be stopped before restoring.`)) return;
    await fetch(`${API}/servers/${encodeURIComponent(serverName)}/restore?file=${encodeURIComponent(file)}`, {
      method: 'POST',
      headers: authHeaders(),
    });
    alert('Restore triggered. Stop the server before restoring for safety.');
  }

  async function deleteBackup(file) {
    if (!confirm(`Delete backup "${file}"? This cannot be undone.`)) return;
    await fetch(`${API}/servers/${encodeURIComponent(serverName)}/backups/${encodeURIComponent(file)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    refresh();
  }

  async function saveSchedule() {
    try {
      await fetch(`${API}/api/backup-schedules/${encodeURIComponent(serverName)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(scheduleForm),
      });
      loadSchedule();
    } catch {}
  }

  async function deleteSchedule() {
    try {
      await fetch(`${API}/api/backup-schedules/${encodeURIComponent(serverName)}`, {
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
    } catch {}
  }

  function formatSize(bytes) {
    if (!bytes) return '0 B';
    const mb = bytes / 1024 / 1024;
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${Math.ceil(mb)} MB`;
  }

  function formatDate(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleString();
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold text-white">Backups</h3>
          {schedule?.enabled && (
            <span className="flex items-center gap-1.5 px-2 py-0.5 bg-green-500/20 text-green-400 rounded-full text-xs">
              <FaClock className="w-3 h-3" />
              Every {schedule.interval_hours}h
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowSchedule(!showSchedule)}
            className={`px-3 py-2 rounded-lg flex items-center gap-2 text-sm transition-colors ${
              showSchedule ? 'bg-brand-500/20 text-brand-400' : 'bg-white/10 hover:bg-white/20 text-white/70'
            }`}
          >
            <FaCalendarAlt className="w-3.5 h-3.5" />
            Schedule
          </button>
          <button
            onClick={createBackup}
            disabled={creating}
            className="px-3 py-2 bg-brand-500 hover:bg-brand-400 rounded-lg flex items-center gap-2 text-sm text-white disabled:opacity-50"
          >
            <FaDownload className="w-3.5 h-3.5" />
            {creating ? 'Creating...' : 'Create Backup'}
          </button>
        </div>
      </div>

      {/* Schedule Configuration */}
      {showSchedule && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-5">
          <h4 className="text-sm font-medium text-white/80 mb-4 flex items-center gap-2">
            <FaClock className="text-brand-400" />
            Automatic Backup Schedule
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <label className="flex items-center gap-3 cursor-pointer sm:col-span-2 lg:col-span-3">
              <input
                type="checkbox"
                checked={scheduleForm.enabled}
                onChange={(e) => setScheduleForm(prev => ({ ...prev, enabled: e.target.checked }))}
                className="w-4 h-4 rounded bg-white/10 border-white/20 text-brand-500 focus:ring-brand-500"
              />
              <span className="text-white text-sm">Enable automatic backups</span>
            </label>

            <div>
              <label className="block text-xs text-white/50 mb-1">Interval</label>
              <select
                value={scheduleForm.interval_hours}
                onChange={(e) => setScheduleForm(prev => ({ ...prev, interval_hours: parseInt(e.target.value) }))}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
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
                onChange={(e) => setScheduleForm(prev => ({ ...prev, retention_count: parseInt(e.target.value) || 10 }))}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-white/50 mb-1">Max age (days)</label>
              <input
                type="number"
                min={1}
                max={365}
                value={scheduleForm.retention_days}
                onChange={(e) => setScheduleForm(prev => ({ ...prev, retention_days: parseInt(e.target.value) || 30 }))}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-white/50 mb-1">Compression</label>
              <select
                value={scheduleForm.compression}
                onChange={(e) => setScheduleForm(prev => ({ ...prev, compression: e.target.value }))}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
              >
                <option value="zip">ZIP</option>
                <option value="tar.gz">TAR.GZ</option>
                <option value="none">No compression</option>
              </select>
            </div>

            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={scheduleForm.remote_upload}
                onChange={(e) => setScheduleForm(prev => ({ ...prev, remote_upload: e.target.checked }))}
                className="w-4 h-4 rounded bg-white/10 border-white/20 text-brand-500 focus:ring-brand-500"
              />
              <span className="text-white text-sm flex items-center gap-1.5">
                <FaCloud className="text-blue-400 w-3.5 h-3.5" />
                Upload to remote storage
              </span>
            </label>
          </div>

          {schedule?.last_backup && (
            <p className="text-xs text-white/40 mt-3">
              Last automatic backup: {new Date(schedule.last_backup).toLocaleString()}
            </p>
          )}

          <div className="flex gap-2 mt-4 pt-3 border-t border-white/10">
            <button
              onClick={saveSchedule}
              className="px-3 py-1.5 bg-brand-500 hover:bg-brand-400 rounded-lg flex items-center gap-2 text-sm text-white"
            >
              <FaSave className="w-3 h-3" />
              Save Schedule
            </button>
            {schedule && (
              <button
                onClick={deleteSchedule}
                className="px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg flex items-center gap-2 text-sm"
              >
                <FaTrash className="w-3 h-3" />
                Remove Schedule
              </button>
            )}
          </div>
        </div>
      )}

      {/* Backup List */}
      <div className="space-y-2">
        {loading ? (
          <div className="flex justify-center py-12">
            <FaSync className="w-5 h-5 text-white/30 animate-spin" />
          </div>
        ) : list.length > 0 ? (
          list.map((b) => (
            <div key={b.file} className="flex items-center justify-between bg-white/5 border border-white/10 rounded-lg px-4 py-3 hover:bg-white/[0.07] transition-colors">
              <div className="min-w-0 flex-1">
                <div className="text-white text-sm font-medium truncate">{b.file}</div>
                <div className="flex items-center gap-3 text-xs text-white/40 mt-0.5">
                  <span>{formatSize(b.size)}</span>
                  {b.modified && <span>{formatDate(b.modified)}</span>}
                </div>
              </div>
              <div className="flex gap-2 ml-3">
                <button
                  onClick={() => restore(b.file)}
                  className="px-2.5 py-1.5 bg-white/10 hover:bg-white/20 rounded text-xs text-white/80 transition-colors"
                >
                  Restore
                </button>
                <button
                  onClick={() => deleteBackup(b.file)}
                  className="px-2.5 py-1.5 bg-red-500/10 hover:bg-red-500/20 rounded text-xs text-red-400 transition-colors"
                >
                  <FaTrash className="w-3 h-3" />
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-white/30">
            <FaDownload className="text-3xl mb-3" />
            <span className="text-sm">{t('servers.noBackups')}</span>
            <span className="text-xs text-white/20 mt-1">Create a backup or set up automatic scheduling</span>
          </div>
        )}
      </div>
    </div>
  );
}
