import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useGlobalData, useGlobalActions } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import {
  FaPlus,
  FaServer,
  FaSync,
  FaCode,
  FaBroom,
  FaClock,
  FaPlay,
  FaStop,
  FaInfoCircle,
  FaSpinner,
  FaArrowLeft,
  FaSave,
  FaTimes,
} from 'react-icons/fa';
import ScheduleBuilder from '../components/ScheduleBuilder';

const TASK_TYPES = [
  { value: 'backup', label: 'Backup', icon: FaServer, description: 'Create a backup of the server (runs in background)' },
  { value: 'restart', label: 'Restart', icon: FaSync, description: 'Restart the server' },
  { value: 'start', label: 'Start', icon: FaPlay, description: 'Start the server (e.g. back on at 9 AM)' },
  { value: 'stop', label: 'Stop', icon: FaStop, description: 'Stop the server gracefully (e.g. down at 2 AM)' },
  { value: 'command', label: 'Command', icon: FaCode, description: 'Execute a console command' },
  { value: 'announce', label: 'Announce', icon: FaInfoCircle, description: 'Broadcast a message to all players (say)' },
  { value: 'save', label: 'Save', icon: FaServer, description: 'Save the world (save-all)' },
  { value: 'cleanup', label: 'Cleanup', icon: FaBroom, description: 'Clean up old backups/logs' },
];

export default function CreateSchedulePage() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const globalData = useGlobalData();
  const { __refreshBG } = useGlobalActions();
  const { serverId } = useParams();
  const navigate = useNavigate();
  const servers = globalData.servers || [];

  // Find server to get its name for API calls
  const server = servers.find(s => s.id === serverId);
  const serverName = server?.name;

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    task_type: 'backup',
    server_name: serverName || '',
    cron_expression: '0 2 * * *',
    command: '',
    is_active: true,
  });
  const [submitting, setSubmitting] = useState(false);
  const [serverLoading, setServerLoading] = useState(!serverName);

  // Fetch server if not in global data
  useEffect(() => {
    if (!serverName && serverId) {
      setServerLoading(true);
      fetch(`${API}/servers/${serverId}`, { headers: authHeaders() })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data?.name) {
            setFormData(prev => ({ ...prev, server_name: data.name }));
          }
        })
        .finally(() => setServerLoading(false));
    }
  }, [serverId, serverName]);

  // Update server_name when server changes
  useEffect(() => {
    if (serverName) {
      setFormData(prev => ({ ...prev, server_name: serverName }));
    }
  }, [serverName]);

  const handleInputChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const validateForm = () => {
    if (!formData.name.trim()) return 'Task name is required';
    if (!formData.cron_expression.trim()) return 'Schedule is required';
    if (['backup', 'restart', 'start', 'stop', 'save', 'announce'].includes(formData.task_type) && !formData.server_name.trim()) {
      return 'Server is required for this task type';
    }
    if (formData.task_type === 'command' && !formData.command.trim()) {
      return 'Command is required for command tasks';
    }
    if (formData.task_type === 'announce' && !formData.command.trim()) {
      return 'Message is required for announce tasks';
    }
    return null;
  };

  const submitTask = async () => {
    const error = validateForm();
    if (error) {
      showToast('error', error);
      return;
    }

    const currentServerName = formData.server_name;
    if (!currentServerName) {
      showToast('error', 'Server not found');
      return;
    }

    setSubmitting(true);
    try {
      const body = { ...formData };
      // Don't send is_active for create
      delete body.is_active;

      const r = await fetch(`${API}/servers/${encodeURIComponent(currentServerName)}/schedules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }

      const task = await r.json();
      showToast('success', 'Task created');
      
      // Refresh tasks in global data
      __refreshBG('schedule', `${API}/servers/${encodeURIComponent(currentServerName)}/schedules`, (d) => d);
      
      // Navigate back to server details
      navigate(`/servers/${serverId}`);
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = () => {
    navigate(`/servers/${serverId}`);
  };

  const taskTypeInfo = TASK_TYPES.find(t => t.value === formData.task_type);

  // Show loading while fetching server
  if (serverLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <button
            onClick={cancel}
            className="text-white/60 hover:text-white mb-3 flex items-center gap-2"
          >
            <FaArrowLeft /> Back to Server
          </button>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <FaClock className="text-brand-500" />
            Create New Task
          </h2>
          <p className="text-white/60 mt-1">Configure a new scheduled task for this server</p>
        </div>
      </div>

      {/* Form */}
      <form onSubmit={submitTask} className="bg-card border border-white/10 rounded-xl shadow-xl p-6 space-y-5 max-w-2xl">
        {/* Task Name */}
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1">Task Name <span className="text-red-400">*</span></label>
          <input
            type="text"
            required
            autoFocus
            className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            placeholder="Daily backup, Nightly restart, etc."
            value={formData.name}
            onChange={e => handleInputChange('name', e.target.value)}
          />
        </div>

        {/* Task Type */}
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1">Task Type <span className="text-red-400">*</span></label>
          <select
            className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            value={formData.task_type}
            onChange={e => handleInputChange('task_type', e.target.value)}
          >
            {TASK_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <p className="text-xs text-white/50 mt-1">{taskTypeInfo?.description}</p>
        </div>

        {/* Server Selection (for server-bound types) */}
        {['backup', 'restart', 'start', 'stop', 'save', 'announce'].includes(formData.task_type) && (
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1">Server <span className="text-red-400">*</span></label>
            <select
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              value={formData.server_name}
              onChange={e => handleInputChange('server_name', e.target.value)}
            >
              <option value="">Select a server</option>
              {servers.map(s => (
                <option key={s.id} value={s.name}>{s.name}</option>
              ))}
            </select>
            <p className="text-xs text-white/50 mt-1">Required for backup / restart / start / stop / save / announce tasks</p>
          </div>
        )}

        {/* Schedule — friendly builder */}
        <div>
          <label className="block text-sm font-medium text-white/70 mb-2">When should it run? <span className="text-red-400">*</span></label>
          <ScheduleBuilder
            value={formData.cron_expression}
            onChange={(cron) => handleInputChange('cron_expression', cron)}
          />
        </div>

        {/* Command (only for command type) */}
        {formData.task_type === 'command' && (
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1">Command <span className="text-red-400">*</span></label>
            <input
              type="text"
              required
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono"
              placeholder="say Server restarting in 1 minute"
              value={formData.command}
              onChange={e => handleInputChange('command', e.target.value)}
            />
            <p className="text-xs text-white/50 mt-1">The command to execute in the server console</p>
          </div>
        )}

        {/* Message (announce type) */}
        {formData.task_type === 'announce' && (
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1">Message <span className="text-red-400">*</span></label>
            <input
              type="text"
              required
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              placeholder="Server restarts in 10 minutes!"
              value={formData.command}
              onChange={e => handleInputChange('command', e.target.value)}
            />
            <p className="text-xs text-white/50 mt-1">Broadcast to all players via <code>say</code></p>
          </div>
        )}

        {/* Active Toggle */}
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="is_active"
            checked={formData.is_active}
            onChange={e => handleInputChange('is_active', e.target.checked)}
            className="accent-brand-500 w-4 h-4"
          />
          <label htmlFor="is_active" className="text-sm text-white/70 cursor-pointer">
            Task is active (enabled)
          </label>
        </div>

        {/* Submit Buttons */}
        <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
          <button
            type="button"
            onClick={cancel}
            className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80 flex items-center gap-2"
          >
            <FaTimes /> Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg text-white flex items-center gap-2"
          >
            {submitting ? (
              <>
                <FaSpinner className="animate-spin w-4 h-4" />
                Saving...
              </>
            ) : (
              <>
                <FaSave /> Create Task
              </>
            )}
          </button>
        </div>
      </form>

    </div>
  );
}