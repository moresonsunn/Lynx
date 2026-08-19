import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../../i18n';
import { useFetch } from '../../lib/useFetch';
import { useGlobalData, useGlobalActions } from '../../context/GlobalDataContext';
import { API, authHeaders } from '../../context/AppContext';
import { useToast } from '../../context/ToastContext';
import {
  FaPlus,
  FaTrash,
  FaPlay,
  FaToggleOn,
  FaToggleOff,
  FaClock,
  FaServer,
  FaCode,
  FaBroom,
  FaSync,
  FaInfoCircle,
  FaExternalLinkAlt,
  FaSpinner,
  FaChevronDown,
  FaChevronUp,
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

export default function SchedulePanel({ serverName: propServerName, serverId: propServerId }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const globalData = useGlobalData();
  const { __refreshBG } = useGlobalActions();
  const servers = globalData.servers || [];

  const { data: tasks, loading: tasksLoading, error: tasksError, setData: setTasks } = useFetch(
    `${API}/schedule/tasks`,
    []
  );

  // Form state
  const [showForm, setShowForm] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    task_type: 'backup',
    server_name: propServerName || '',
    cron_expression: '0 2 * * *',
    command: '',
    is_active: true,
  });
  const [submitting, setSubmitting] = useState(false);
  const [runLoading, setRunLoading] = useState(null);
  const [deleteLoading, setDeleteLoading] = useState(null);
  const [toggleLoading, setToggleLoading] = useState(null);
  const [showCronHelp, setShowCronHelp] = useState(false);

  // Reset form when opening/closing
  useEffect(() => {
    if (!showForm && !editingTask) {
      setFormData({
        name: '',
        task_type: 'backup',
        server_name: propServerName || '',
        cron_expression: '0 2 * * *',
        command: '',
        is_active: true,
      });
    }
  }, [showForm, editingTask, propServerName]);

  // Populate form when editing
  useEffect(() => {
    if (editingTask) {
      setFormData({
        name: editingTask.name,
        task_type: editingTask.task_type,
        server_name: editingTask.server_name || '',
        cron_expression: editingTask.cron_expression,
        command: editingTask.command || '',
        is_active: editingTask.is_active !== false,
      });
    }
  }, [editingTask]);

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
      const url = editingTask
        ? `${API}/schedule/tasks/${editingTask.id}`
        : `${API}/schedule/tasks`;
      const method = editingTask ? 'PUT' : 'POST';
      const body = { ...formData };
      // Don't send is_active for create, only for update
      if (!editingTask) delete body.is_active;

      const r = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }

      const task = await r.json();
      showToast('success', editingTask ? 'Task updated' : 'Task created');
      setShowForm(false);
      setEditingTask(null);
      // Refresh tasks
      __refreshBG('schedule', `${API}/schedule/tasks`, (d) => d);
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const runTask = async (task) => {
    setRunLoading(task.id);
    try {
      const r = await fetch(`${API}/schedule/tasks/${task.id}/run`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      showToast('success', `Task "${task.name}" executed`);
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setRunLoading(null);
    }
  };

  const deleteTask = async (task) => {
    if (!window.confirm(`Delete task "${task.name}"? This cannot be undone.`)) return;
    setDeleteLoading(task.id);
    try {
      const r = await fetch(`${API}/schedule/tasks/${task.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      showToast('success', 'Task deleted');
      setTasks(prev => (prev || []).filter(t => t.id !== task.id));
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setDeleteLoading(null);
    }
  };

  const toggleTask = async (task) => {
    setToggleLoading(task.id);
    try {
      const r = await fetch(`${API}/schedule/tasks/${task.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: !task.is_active }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      showToast('success', `Task ${!task.is_active ? 'enabled' : 'disabled'}`);
      setTasks(prev => (prev || []).map(t =>
        t.id === task.id ? { ...t, is_active: !t.is_active } : t
      ));
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setToggleLoading(null);
    }
  };

  const startEdit = (task) => {
    setEditingTask(task);
    setShowForm(true);
  };

  const cancelEdit = () => {
    setEditingTask(null);
    setShowForm(false);
  };

  const taskTypeInfo = TASK_TYPES.find(t => t.value === formData.task_type);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <FaClock className="text-brand-500" />
            Scheduled Tasks
          </h2>
          <p className="text-white/60 mt-1">Automate server backups, restarts, commands, and cleanup</p>
        </div>
        <button
          onClick={() => { setEditingTask(null); setShowForm(true); }}
          className="bg-brand-500 hover:bg-brand-600 px-4 py-2 rounded-lg flex items-center gap-2"
        >
          <FaPlus /> Create Task
        </button>
      </div>

      {/* Tasks List */}
      <div className="space-y-4">
        {tasksLoading && (
          <div className="bg-white/5 border border-white/10 rounded-lg p-8 text-center">
            <FaSpinner className="animate-spin text-brand-500 text-2xl mx-auto mb-2" />
            <p className="text-white/60">Loading tasks...</p>
          </div>
        )}

        {tasksError && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-300 p-4 rounded-lg">
            Failed to load tasks: {String(tasksError)}
          </div>
        )}

        {!tasksLoading && !tasksError && (!tasks || tasks.length === 0) && (
          <div className="bg-white/5 border border-white/10 rounded-lg p-8 text-center">
            <FaClock className="text-4xl text-white/20 mx-auto mb-3" />
            <p className="text-white/60 mb-4">No scheduled tasks yet</p>
            <button
              onClick={() => { setEditingTask(null); setShowForm(true); }}
              className="bg-brand-500 hover:bg-brand-600 px-4 py-2 rounded-lg flex items-center gap-2 mx-auto"
            >
              <FaPlus /> Create Your First Task
            </button>
          </div>
        )}

        {!tasksLoading && !tasksError && tasks && tasks.length > 0 && (
          <div className="space-y-3">
            {tasks.map((task) => {
              const typeInfo = TASK_TYPES.find(t => t.value === task.task_type);
              const isRunning = runLoading === task.id;
              const isToggling = toggleLoading === task.id;
              const isDeleting = deleteLoading === task.id;
              const disabled = isRunning || isToggling || isDeleting;

              return (
                <div
                  key={task.id}
                  className={`bg-white/5 border border-white/10 rounded-xl p-4 transition-all ${
                    task.is_active === false ? 'opacity-60 border-red-500/20' : ''
                  }`}
                >
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    {/* Task Info */}
                    <div className="flex items-start gap-4 flex-1 min-w-0">
                      <div
                        className={`w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0 ${
                          task.is_active === false ? 'bg-gray-700' : 'bg-brand-500/20'
                        }`}
                      >
                        {typeInfo?.icon ? (
                          <typeInfo.icon className={`text-xl ${task.is_active === false ? 'text-white/40' : 'text-brand-400'}`} />
                        ) : (
                          <FaClock className={`text-xl ${task.is_active === false ? 'text-white/40' : 'text-brand-400'}`} />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-3 flex-wrap">
                          <h4 className="font-medium text-white truncate">{task.name}</h4>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            task.is_active === false
                              ? 'bg-gray-700 text-white/50'
                              : 'bg-brand-500/20 text-brand-300'
                          }`}>
                            {typeInfo?.label || task.task_type}
                          </span>
                          {task.server_name && (
                            <span className="px-2 py-0.5 rounded text-xs bg-gray-700 text-white/70 flex items-center gap-1">
                              <FaServer className="text-xs" /> {task.server_name}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-4 mt-1 text-sm text-white/50 flex-wrap">
                          <span className="flex items-center gap-1 font-mono bg-gray-900 px-2 py-0.5 rounded">
                            <FaClock className="text-xs" /> {task.cron_expression}
                          </span>
                          {task.command && (
                            <span className="font-mono text-xs truncate max-w-[300px]">Cmd: {task.command}</span>
                          )}
                          {task.next_run && (
                            <span className="flex items-center gap-1">
                              <FaClock className="text-xs" />
                              Next: {new Date(task.next_run).toLocaleString()}
                            </span>
                          )}
                          {task.last_run && (
                            <span className="flex items-center gap-1">
                              <FaHistory className="text-xs" />
                              Last: {new Date(task.last_run).toLocaleString()}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Run Now */}
                      <button
                        onClick={() => runTask(task)}
                        disabled={disabled || task.is_active === false}
                        className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1.5 transition-colors ${
                          disabled
                            ? 'bg-white/5 text-white/30 cursor-not-allowed'
                            : 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                        }`}
                        title={task.is_active === false ? 'Enable task first' : 'Run now'}
                      >
                        {isRunning ? (
                          <FaSpinner className="animate-spin" />
                        ) : (
                          <>
                            <FaPlay className="w-3 h-3" /> Run
                          </>
                        )}
                      </button>

                      {/* Enable/Disable Toggle */}
                      <button
                        onClick={() => toggleTask(task)}
                        disabled={isToggling || isDeleting}
                        className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1.5 transition-colors ${
                          isToggling ? 'bg-white/5 text-white/30 cursor-not-allowed' :
                          task.is_active
                            ? 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30'
                            : 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                        }`}
                        title={task.is_active ? 'Disable' : 'Enable'}
                      >
                        {isToggling ? (
                          <FaSpinner className="animate-spin" />
                        ) : task.is_active ? (
                          <FaToggleOn className="w-4 h-4" />
                        ) : (
                          <FaToggleOff className="w-4 h-4" />
                        )}
                      </button>

                      {/* Edit */}
                      <button
                        onClick={() => startEdit(task)}
                        disabled={disabled}
                        className={`p-2 rounded-lg transition-colors ${
                          disabled ? 'text-white/30 cursor-not-allowed' : 'text-white/60 hover:text-white hover:bg-white/10'
                        }`}
                        title="Edit"
                      >
                        <FaChevronDown className="w-4 h-4" />
                      </button>

                      {/* Delete */}
                      <button
                        onClick={() => deleteTask(task)}
                        disabled={disabled}
                        className={`p-2 rounded-lg transition-colors ${
                          disabled ? 'text-white/30 cursor-not-allowed' : 'text-red-400 hover:text-red-300 hover:bg-red-500/10'
                        }`}
                        title="Delete"
                      >
                        {isDeleting ? <FaSpinner className="animate-spin w-4 h-4" /> : <FaTrash className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Create/Edit Form Modal */}
      {(showForm || editingTask) && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={cancelEdit} />
          <form onSubmit={submitTask} className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-5">
            <div className="flex items-center justify-between mb-2 sticky top-0 bg-card/95 backdrop-blur pb-4 border-b border-white/10 z-10">
              <h3 className="text-xl font-bold text-white flex items-center gap-2">
                {editingTask ? <FaChevronDown /> : <FaPlus />} {editingTask ? 'Edit Task' : 'Create New Task'}
              </h3>
              <button
                type="button"
                onClick={cancelEdit}
                className="text-white/60 hover:text-white p-1"
              >
                <FaTimes className="w-5 h-5" />
              </button>
            </div>

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
                        onClick={() => handleInputChange('cron_expression', ex.expression)}
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

            {/* Active Toggle (only for edit) */}
            {editingTask && (
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
            )}

            {/* Submit Buttons */}
            <div className="flex justify-end gap-3 pt-4 border-t border-white/10 sticky bottom-0 bg-card/95 backdrop-blur mt-4">
              <button
                type="button"
                onClick={cancelEdit}
                className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80"
              >
                Cancel
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
                    {editingTask ? <FaSync /> : <FaPlus />} {editingTask ? 'Update Task' : 'Create Task'}
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Cron Help Modal */}
      {showCronHelp && !editingTask && !showForm && (
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
                  onClick={() => { handleInputChange('cron_expression', ex.expression); setShowForm(true); setShowCronHelp(false); }}
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