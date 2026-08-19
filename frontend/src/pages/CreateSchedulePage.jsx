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
  FaInfoCircle,
  FaExternalLinkAlt,
  FaSpinner,
  FaChevronDown,
  FaChevronUp,
  FaArrowLeft,
  FaSave,
  FaTimes,
} from 'react-icons/fa';

const TASK_TYPES = [
  { value: 'backup', label: 'Backup', icon: FaServer, description: 'Create a backup of the server' },
  { value: 'restart', label: 'Restart', icon: FaSync, description: 'Restart the server' },
  { value: 'command', label: 'Command', icon: FaCode, description: 'Execute a console command' },
  { value: 'cleanup', label: 'Cleanup', icon: FaBroom, description: 'Clean up old backups/logs' },
];

const CRON_EXAMPLES = [
  { expression: '0 2 * * *', description: 'Daily at 2:00 AM' },
  { expression: '0 */6 * * *', description: 'Every 6 hours' },
  { expression: '0 0 * * 0', description: 'Weekly on Sunday at midnight' },
  { expression: '*/30 * * * *', description: 'Every 30 minutes' },
  { expression: '0 0 1 * *', description: 'Monthly on the 1st at midnight' },
];

export default function CreateSchedulePage() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const globalData = useGlobalData();
  const { __refreshBG } = useGlobalActions();
  const { serverId } = useParams();
  const navigate = useNavigate();
  const servers = globalData.servers || [];

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    task_type: 'backup',
    server_name: '',
    cron_expression: '0 2 * * *',
    command: '',
    is_active: true,
  });
  const [submitting, setSubmitting] = useState(false);
  const [showCronHelp, setShowCronHelp] = useState(false);

  // Pre-fill server_name if we can find the server
  useEffect(() => {
    if (serverId) {
      const server = servers.find(s => s.id === serverId);
      if (server) {
        setFormData(prev => ({ ...prev, server_name: server.name }));
      }
    }
  }, [serverId, servers]);

  const handleInputChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const validateForm = () => {
    if (!formData.name.trim()) return 'Task name is required';
    if (!formData.cron_expression.trim()) return 'Cron expression is required';
    if (['backup', 'restart'].includes(formData.task_type) && !formData.server_name.trim()) {
      return 'Server is required for backup/restart tasks';
    }
    if (formData.task_type === 'command' && !formData.command.trim()) {
      return 'Command is required for command tasks';
    }
    return null;
  };

  const submitTask = async () => {
    const error = validateForm();
    if (error) {
      showToast('error', error);
      return;
    }

    setSubmitting(true);
    try {
      const body = { ...formData };
      // Don't send is_active for create
      delete body.is_active;

      const r = await fetch(`${API}/schedule/tasks`, {
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
      __refreshBG('schedule', `${API}/schedule/tasks`, (d) => d);
      
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

        {/* Server Selection (for backup/restart) */}
        {['backup', 'restart'].includes(formData.task_type) && (
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
            <p className="text-xs text-white/50 mt-1">Required for backup and restart tasks</p>
          </div>
        )}

        {/* Cron Expression */}
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1 flex items-center gap-2">
            Cron Expression <span className="text-red-400">*</span>
            <a
              href="https://crontab.guru/"
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => { e.stopPropagation(); setShowCronHelp(true); }}
              className="text-brand-400 hover:text-brand-300 text-xs flex items-center gap-1"
            >
              <FaExternalLinkAlt className="w-3 h-3" /> crontab.guru
            </a>
            <button
              type="button"
              onClick={() => setShowCronHelp(!showCronHelp)}
              className="p-1 text-white/50 hover:text-white"
              title="Show examples"
            >
              {showCronHelp ? <FaChevronUp className="w-4 h-4" /> : <FaChevronDown className="w-4 h-4" />}
            </button>
          </label>
          <input
            type="text"
            required
            className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono"
            placeholder="0 2 * * *"
            value={formData.cron_expression}
            onChange={e => handleInputChange('cron_expression', e.target.value)}
          />
          {showCronHelp && (
            <div className="mt-2 p-3 bg-white/5 border border-white/10 rounded-lg">
              <p className="text-xs text-white/60 mb-2">Common examples (min hour day month weekday):</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {CRON_EXAMPLES.map((ex, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => { handleInputChange('cron_expression', ex.expression); setShowCronHelp(false); }}
                    className="text-left p-2 bg-white/5 hover:bg-white/10 rounded text-sm border border-white/10"
                  >
                    <code className="font-mono text-brand-300">{ex.expression}</code>
                    <span className="text-white/60 ml-2">{ex.description}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
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

      {/* Cron Help Modal */}
      {showCronHelp && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowCronHelp(false)} />
          <div className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <FaInfoCircle className="text-brand-400" /> Cron Expression Help
              </h3>
              <button onClick={() => setShowCronHelp(false)} className="text-white/60 hover:text-white">
                <FaTimes className="w-5 h-5" />
              </button>
            </div>
            <p className="text-white/70 text-sm">Format: <code className="font-mono bg-white/5 px-1 rounded">minute hour day month weekday</code></p>
            <div className="space-y-2">
              {CRON_EXAMPLES.map((ex, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => { handleInputChange('cron_expression', ex.expression); setShowCronHelp(false); }}
                  className="w-full text-left p-3 bg-white/5 hover:bg-white/10 rounded border border-white/10"
                >
                  <code className="font-mono text-brand-300 block">{ex.expression}</code>
                  <span className="text-white/60 text-sm">{ex.description}</span>
                </button>
              ))}
            </div>
            <p className="text-xs text-white/40 mt-2">
              Learn more at <a href="https://crontab.guru/" target="_blank" rel="noopener noreferrer" className="text-brand-400 underline">crontab.guru</a>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}