import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../i18n';
import { API, authHeaders, useTheme } from '../context/AppContext';
import { 
  FaCog, FaSave, FaDatabase, FaBell, FaShieldAlt, FaServer, 
  FaPalette, FaDocker, FaTachometerAlt, FaTrash, FaSync,
  FaCheck, FaTimes, FaExclamationTriangle, FaJava, FaHdd,
  FaDiscord, FaSlack, FaEnvelope, FaUndo, FaDownload, FaUpload,
  FaKey, FaClock, FaMemory, FaMicrochip, FaGlobe, FaBroom,
  FaSteam
} from 'react-icons/fa';
import { useToast } from '../context/ToastContext';


function Tab({ active, onClick, icon: Icon, label }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all border-b-2 ${
        active 
          ? 'border-brand-500 text-brand-400 bg-brand-500/10' 
          : 'border-transparent text-white/60 hover:text-white/80 hover:bg-white/5'
      }`}
    >
      <Icon className="w-4 h-4" />
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}


function Section({ title, description, icon: Icon, children }) {
  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-6">
      <div className="flex items-start gap-3 mb-5">
        <div className="p-2 bg-brand-500/20 rounded-lg">
          <Icon className="w-5 h-5 text-brand-400" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-white">{title}</h3>
          {description && <p className="text-sm text-white/50 mt-0.5">{description}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}


function Input({ label, description, type = 'text', value, onChange, placeholder, disabled, suffix }) {
  return (
    <div>
      <label className="block text-sm font-medium text-white/70 mb-1.5">{label}</label>
      <div className="relative">
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(type === 'number' ? Number(e.target.value) : e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/30 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 disabled:opacity-50"
        />
        {suffix && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-white/40 text-sm">{suffix}</span>}
      </div>
      {description && <p className="text-xs text-white/40 mt-1">{description}</p>}
    </div>
  );
}

function Toggle({ label, description, checked, onChange }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex-1">
        <div className="text-sm font-medium text-white/80">{label}</div>
        {description && <p className="text-xs text-white/40 mt-0.5">{description}</p>}
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
          checked ? 'bg-brand-500' : 'bg-white/20'
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}

function Select({ label, description, value, onChange, options }) {
  return (
    <div>
      <label className="block text-sm font-medium text-white/70 mb-1.5">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} className="bg-gray-900">{opt.label}</option>
        ))}
      </select>
      {description && <p className="text-xs text-white/40 mt-1">{description}</p>}
    </div>
  );
}


function StorageBar({ label, used, total, unit = 'GB' }) {
  const percent = total > 0 ? (used / total) * 100 : 0;
  const color = percent > 90 ? 'bg-red-500' : percent > 75 ? 'bg-yellow-500' : 'bg-brand-500';
  
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-white/70">{label}</span>
        <span className="text-white/50">{used.toFixed(1)} / {total.toFixed(1)} {unit}</span>
      </div>
      <div className="h-2 bg-white/10 rounded-full overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${Math.min(percent, 100)}%` }} />
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const { themeMode, setThemeMode, accentColor, setAccentColor } = useTheme();
  const [activeTab, setActiveTab] = useState('general');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState(null);
  const [storageInfo, setStorageInfo] = useState(null);
  const [javaVersions, setJavaVersions] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [curseforgeKey, setCurseforgeKey] = useState('');
  const [nexusKey, setNexusKey] = useState('');
  const [modioKey, setModioKey] = useState('');
  const [steamKey, setSteamKey] = useState('');
  const [providersStatus, setProvidersStatus] = useState({
    curseforge: { configured: false },
    nexus: { configured: false },
    modio: { configured: false },
    steam: { configured: false },
  });

  
  useEffect(() => {
    loadSettings();
    loadStorageInfo();
    loadJavaVersions();
    loadSessions();
    loadIntegrations();
  }, []);

  async function loadSettings() {
    try {
      const r = await fetch(`${API}/settings`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        setSettings(data);
      }
    } catch (e) {
      console.error('Failed to load settings:', e);
    } finally {
      setLoading(false);
    }
  }

  async function loadStorageInfo() {
    try {
      const r = await fetch(`${API}/settings/system/storage`, { headers: authHeaders() });
      if (r.ok) setStorageInfo(await r.json());
    } catch (e) {
      console.error('Failed to load storage info:', e);
    }
  }

  async function loadJavaVersions() {
    try {
      const r = await fetch(`${API}/settings/java`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        setJavaVersions(data.versions || []);
      }
    } catch (e) {
      console.error('Failed to load Java versions:', e);
    }
  }

  async function loadSessions() {
    try {
      setSessionsLoading(true);
      const r = await fetch(`${API}/auth/sessions`, { headers: authHeaders() });
      if (r.ok) setSessions(await r.json());
    } catch (e) {
      console.error('Failed to load sessions:', e);
    } finally {
      setSessionsLoading(false);
    }
  }

  async function loadIntegrations() {
    try {
      const r = await fetch(`${API}/integrations/status`);
      if (r.ok) setProvidersStatus(await r.json());
    } catch {}
  }

  async function saveSettings() {
    setSaving(true);
    try {
      const r = await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(settings)
      });
      if (r.ok) {
        showToast('success', 'Settings saved successfully');
      } else {
        const err = await r.json().catch(() => ({}));
        showToast('error', err.detail || 'Failed to save settings');
      }
    } catch (e) {
      showToast('error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  }

  async function resetSettings() {
    if (!confirm('Reset all settings to defaults? This cannot be undone.')) return;
    try {
      const r = await fetch(`${API}/settings/reset`, {
        method: 'POST',
        headers: authHeaders()
      });
      if (r.ok) {
        showToast('success', 'Settings reset to defaults');
        loadSettings();
      }
    } catch (e) {
      showToast('error', 'Failed to reset settings');
    }
  }

  async function testNotification() {
    try {
      const r = await fetch(`${API}/settings/notifications/test`, {
        method: 'POST',
        headers: authHeaders()
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        showToast('success', 'Test notification sent!');
      } else {
        showToast('error', data.detail || 'Failed to send test notification');
      }
    } catch (e) {
      showToast('error', 'Failed to send test notification');
    }
  }

  async function cleanupLogs() {
    try {
      const r = await fetch(`${API}/settings/system/cleanup-logs`, {
        method: 'POST',
        headers: authHeaders()
      });
      const data = await r.json();
      showToast('success', `Cleaned up ${data.cleaned} old log files`);
    } catch (e) {
      showToast('error', 'Failed to cleanup logs');
    }
  }

  async function cleanupBackups() {
    try {
      const r = await fetch(`${API}/settings/system/cleanup-backups`, {
        method: 'POST',
        headers: authHeaders()
      });
      const data = await r.json();
      showToast('success', `Removed ${data.cleaned} old backups, freed ${data.freed_mb} MB`);
      loadStorageInfo();
    } catch (e) {
      showToast('error', 'Failed to cleanup backups');
    }
  }

  async function revokeSession(id) {
    try {
      const r = await fetch(`${API}/auth/sessions/${id}`, { method: 'DELETE', headers: authHeaders() });
      if (r.ok) {
        setSessions((prev) => prev.filter((s) => s.id !== id));
        showToast('success', 'Session revoked');
      }
    } catch (e) {
      showToast('error', 'Failed to revoke session');
    }
  }

  async function revokeAllSessions() {
    if (!confirm('Revoke all other sessions? You will stay logged in.')) return;
    for (const s of sessions) {
      if (!s.is_current) {
        await revokeSession(s.id);
      }
    }
  }

  async function saveCurseforgeKey() {
    try {
      const r = await fetch(`${API}/integrations/curseforge-key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ api_key: curseforgeKey })
      });
      if (r.ok) {
        showToast('success', 'CurseForge API key saved');
        loadIntegrations();
        setCurseforgeKey('');
      } else {
        const err = await r.json().catch(() => ({}));
        showToast('error', err.detail || 'Failed to save key');
      }
    } catch (e) {
      showToast('error', 'Failed to save key');
    }
  }

  async function saveIntegrationKey(provider, key, setter, label) {
    try {
      const r = await fetch(`${API}/integrations/${provider}-key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ api_key: key })
      });
      if (r.ok) {
        showToast('success', `${label} API key saved`);
        loadIntegrations();
        setter('');
      } else {
        const err = await r.json().catch(() => ({}));
        showToast('error', err.detail || 'Failed to save key');
      }
    } catch (e) {
      showToast('error', 'Failed to save key');
    }
  }

  
  const updateSetting = useCallback((category, key, value) => {
    setSettings(prev => ({
      ...prev,
      [category]: {
        ...prev[category],
        [key]: value
      }
    }));
  }, []);

  if (loading || !settings) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-500"></div>
      </div>
    );
  }

  const tabs = [
    { id: 'general', label: 'General', icon: FaCog },
    { id: 'servers', label: 'Server Defaults', icon: FaServer },
    { id: 'backup', label: 'Backups', icon: FaDatabase },
    { id: 'notifications', label: 'Notifications', icon: FaBell },
    { id: 'security', label: 'Security', icon: FaShieldAlt },
    { id: 'integrations', label: 'Integrations', icon: FaKey },
    { id: 'system', label: 'System', icon: FaTachometerAlt },
  ];

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <FaCog className="text-brand-500" />
            <span className="gradient-text-brand">Settings</span>
          </h1>
          <p className="text-white/60 mt-1">Configure system preferences and integrations</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={resetSettings}
            className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg flex items-center gap-2 text-white/70 hover:text-white transition-colors"
          >
            <FaUndo className="w-4 h-4" />
            <span className="hidden sm:inline">Reset</span>
          </button>
          <button
            onClick={saveSettings}
            disabled={saving}
            className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg flex items-center gap-2 text-white font-medium transition-colors"
          >
            <FaSave className="w-4 h-4" />
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-white/10 overflow-x-auto">
        <div className="flex min-w-max">
          {tabs.map((tab) => (
            <Tab
              key={tab.id}
              active={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              icon={tab.icon}
              label={tab.label}
            />
          ))}
        </div>
      </div>

      {/* Tab Content */}
      <div className="space-y-6">
        {/* General Tab */}
        {activeTab === 'general' && (
          <>
            <Section title="Appearance" description="Customize the look and feel" icon={FaPalette}>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <Select
                  label="Theme"
                  value={themeMode}
                  onChange={(v) => {
                    setThemeMode(v);
                    updateSetting('appearance', 'theme', v);
                  }}
                  options={[
                    { value: 'dark', label: 'Dark' },
                    { value: 'light', label: 'Light' },
                    { value: 'system', label: 'System' }
                  ]}
                />
                {/* Accent Color Picker with visual swatches */}
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-1.5">Accent Color</label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { value: 'blue', color: '#3a86ff' },
                      { value: 'purple', color: '#8b5cf6' },
                      { value: 'green', color: '#22c55e' },
                      { value: 'orange', color: '#f97316' },
                      { value: 'red', color: '#ef4444' },
                      { value: 'pink', color: '#ec4899' },
                      { value: 'cyan', color: '#06b6d4' }
                    ].map((c) => (
                      <button
                        key={c.value}
                        onClick={() => {
                          setAccentColor(c.value);
                          updateSetting('appearance', 'accent_color', c.value);
                        }}
                        className={`w-8 h-8 rounded-lg transition-all ${
                          accentColor === c.value 
                            ? 'ring-2 ring-white ring-offset-2 ring-offset-gray-900 scale-110' 
                            : 'hover:scale-105'
                        }`}
                        style={{ backgroundColor: c.color }}
                        title={c.value.charAt(0).toUpperCase() + c.value.slice(1)}
                      />
                    ))}
                  </div>
                  <p className="text-xs text-white/40 mt-1">Select your preferred accent color</p>
                </div>
                <Select
                  label="Timezone"
                  value={settings.appearance?.timezone || 'UTC'}
                  onChange={(v) => updateSetting('appearance', 'timezone', v)}
                  options={[
                    { value: 'UTC', label: 'UTC' },
                    { value: 'America/New_York', label: 'Eastern Time' },
                    { value: 'America/Los_Angeles', label: 'Pacific Time' },
                    { value: 'Europe/London', label: 'London' },
                    { value: 'Europe/Berlin', label: 'Berlin' },
                    { value: 'Asia/Tokyo', label: 'Tokyo' }
                  ]}
                />
                <Select
                  label="Time Format"
                  value={settings.appearance?.time_format || '24h'}
                  onChange={(v) => updateSetting('appearance', 'time_format', v)}
                  options={[
                    { value: '24h', label: '24 Hour' },
                    { value: '12h', label: '12 Hour (AM/PM)' }
                  ]}
                />
                <Select
                  label="Date Format"
                  value={settings.appearance?.date_format || 'YYYY-MM-DD'}
                  onChange={(v) => updateSetting('appearance', 'date_format', v)}
                  options={[
                    { value: 'YYYY-MM-DD', label: '2026-01-13' },
                    { value: 'DD/MM/YYYY', label: '13/01/2026' },
                    { value: 'MM/DD/YYYY', label: '01/13/2026' }
                  ]}
                />
              </div>
            </Section>

            <Section title="Performance" description="API and caching settings" icon={FaTachometerAlt}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Input
                  label="API Rate Limit"
                  description="Maximum API requests per minute per user"
                  type="number"
                  value={settings.performance?.api_rate_limit || 100}
                  onChange={(v) => updateSetting('performance', 'api_rate_limit', v)}
                  suffix="/min"
                />
                <Input
                  label="Cache TTL"
                  description="How long to cache API responses"
                  type="number"
                  value={settings.performance?.cache_ttl_seconds || 300}
                  onChange={(v) => updateSetting('performance', 'cache_ttl_seconds', v)}
                  suffix="sec"
                />
                <Select
                  label="Log Level"
                  value={settings.performance?.log_level || 'INFO'}
                  onChange={(v) => updateSetting('performance', 'log_level', v)}
                  options={[
                    { value: 'DEBUG', label: 'Debug' },
                    { value: 'INFO', label: 'Info' },
                    { value: 'WARNING', label: 'Warning' },
                    { value: 'ERROR', label: 'Error' }
                  ]}
                />
                <Input
                  label="Log Retention"
                  description="Days to keep log files"
                  type="number"
                  value={settings.performance?.log_retention_days || 30}
                  onChange={(v) => updateSetting('performance', 'log_retention_days', v)}
                  suffix="days"
                />
                <div className="md:col-span-2 space-y-4">
                  <Toggle
                    label="Enable Caching"
                    description="Cache API responses to improve performance"
                    checked={settings.performance?.cache_enabled ?? true}
                    onChange={(v) => updateSetting('performance', 'cache_enabled', v)}
                  />
                  <Toggle
                    label="WebSocket Support"
                    description="Enable real-time updates via WebSocket"
                    checked={settings.performance?.websocket_enabled ?? true}
                    onChange={(v) => updateSetting('performance', 'websocket_enabled', v)}
                  />
                </div>
              </div>
            </Section>
          </>
        )}

        {/* Server Defaults Tab */}
        {activeTab === 'servers' && (
          <Section title="Default Server Settings" description="Default configuration for new servers" icon={FaServer}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Input
                label="Minimum Memory"
                description="Default minimum RAM allocation"
                type="number"
                value={settings.server_defaults?.memory_min_mb || 1024}
                onChange={(v) => updateSetting('server_defaults', 'memory_min_mb', v)}
                suffix="MB"
              />
              <Input
                label="Maximum Memory"
                description="Default maximum RAM allocation"
                type="number"
                value={settings.server_defaults?.memory_max_mb || 4096}
                onChange={(v) => updateSetting('server_defaults', 'memory_max_mb', v)}
                suffix="MB"
              />
              <Input
                label="Crash Restart Delay"
                description="Seconds to wait before restarting after crash"
                type="number"
                value={settings.server_defaults?.crash_restart_delay || 30}
                onChange={(v) => updateSetting('server_defaults', 'crash_restart_delay', v)}
                suffix="sec"
              />
              <Input
                label="Max Crash Restarts"
                description="Maximum auto-restarts before giving up"
                type="number"
                value={settings.server_defaults?.max_crash_restarts || 3}
                onChange={(v) => updateSetting('server_defaults', 'max_crash_restarts', v)}
              />
              <div className="md:col-span-2">
                <Input
                  label="Default Java Arguments"
                  description="JVM arguments for server startup"
                  value={settings.server_defaults?.java_args || ''}
                  onChange={(v) => updateSetting('server_defaults', 'java_args', v)}
                  placeholder="-XX:+UseG1GC -XX:MaxGCPauseMillis=200"
                />
              </div>
              <div className="md:col-span-2 space-y-4">
                <Toggle
                  label="Auto Start Servers"
                  description="Automatically start servers when Lynx starts"
                  checked={settings.server_defaults?.auto_start ?? false}
                  onChange={(v) => updateSetting('server_defaults', 'auto_start', v)}
                />
                <Toggle
                  label="Restart on Crash"
                  description="Automatically restart servers after crashes"
                  checked={settings.server_defaults?.restart_on_crash ?? true}
                  onChange={(v) => updateSetting('server_defaults', 'restart_on_crash', v)}
                />
              </div>
            </div>

            {/* Java Versions */}
            {javaVersions.length > 0 && (
              <div className="mt-6 pt-6 border-t border-white/10">
                <h4 className="text-sm font-medium text-white/70 mb-3 flex items-center gap-2">
                  <FaJava className="text-orange-500" /> Available Java Versions
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {javaVersions.map((java, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm p-2 bg-white/5 rounded-lg">
                      <FaCheck className="text-green-500 w-3 h-3" />
                      <span className="text-white/60 font-mono text-xs">{java.path}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Section>
        )}

        {/* Backup Tab */}
        {activeTab === 'backup' && (
          <Section title="Backup Configuration" description="Automatic backup settings" icon={FaDatabase}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Input
                label="Backup Interval"
                description="Hours between automatic backups"
                type="number"
                value={settings.backup?.interval_hours || 24}
                onChange={(v) => updateSetting('backup', 'interval_hours', v)}
                suffix="hours"
              />
              <Input
                label="Retention Period"
                description="Days to keep old backups"
                type="number"
                value={settings.backup?.retention_days || 7}
                onChange={(v) => updateSetting('backup', 'retention_days', v)}
                suffix="days"
              />
              <Input
                label="Backup Location"
                description="Path where backups are stored"
                value={settings.backup?.location || '/data/backups'}
                onChange={(v) => updateSetting('backup', 'location', v)}
              />
              <Input
                label="Max Backup Size"
                description="Maximum total size of all backups"
                type="number"
                value={settings.backup?.max_backup_size_gb || 50}
                onChange={(v) => updateSetting('backup', 'max_backup_size_gb', v)}
                suffix="GB"
              />
              <div className="md:col-span-2 space-y-4">
                <Toggle
                  label="Enable Automatic Backups"
                  description="Automatically backup servers on schedule"
                  checked={settings.backup?.enabled ?? true}
                  onChange={(v) => updateSetting('backup', 'enabled', v)}
                />
                <Toggle
                  label="Compress Backups"
                  description="Create compressed ZIP archives"
                  checked={settings.backup?.compress ?? true}
                  onChange={(v) => updateSetting('backup', 'compress', v)}
                />
                <Toggle
                  label="Include World Data"
                  description="Include world/save files in backups"
                  checked={settings.backup?.include_worlds ?? true}
                  onChange={(v) => updateSetting('backup', 'include_worlds', v)}
                />
                <Toggle
                  label="Include Mods"
                  description="Include mods folder in backups"
                  checked={settings.backup?.include_mods ?? true}
                  onChange={(v) => updateSetting('backup', 'include_mods', v)}
                />
                <Toggle
                  label="Include Configs"
                  description="Include config files in backups"
                  checked={settings.backup?.include_configs ?? true}
                  onChange={(v) => updateSetting('backup', 'include_configs', v)}
                />
              </div>
            </div>
          </Section>
        )}

        {/* Notifications Tab */}
        {activeTab === 'notifications' && (
          <>
            <Section title="Webhook Notifications" description="Send alerts to Discord, Slack, or other services" icon={FaBell}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="md:col-span-2">
                  <Input
                    label="Webhook URL"
                    description="Discord, Slack, or generic webhook endpoint"
                    value={settings.notifications?.webhook_url || ''}
                    onChange={(v) => updateSetting('notifications', 'webhook_url', v)}
                    placeholder="https://discord.com/api/webhooks/..."
                  />
                </div>
                <Select
                  label="Webhook Type"
                  value={settings.notifications?.webhook_type || 'discord'}
                  onChange={(v) => updateSetting('notifications', 'webhook_type', v)}
                  options={[
                    { value: 'discord', label: 'Discord' },
                    { value: 'slack', label: 'Slack' },
                    { value: 'generic', label: 'Generic JSON' }
                  ]}
                />
                <div className="flex items-end">
                  <button
                    onClick={testNotification}
                    className="px-4 py-2 bg-brand-500 hover:bg-brand-600 rounded-lg flex items-center gap-2 text-white"
                  >
                    <FaBell className="w-4 h-4" />
                    Send Test Notification
                  </button>
                </div>
              </div>

              <div className="mt-6 pt-6 border-t border-white/10">
                <h4 className="text-sm font-medium text-white/70 mb-4">Alert Types</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Toggle
                    label="Server Crashes"
                    checked={settings.notifications?.alert_server_crash ?? true}
                    onChange={(v) => updateSetting('notifications', 'alert_server_crash', v)}
                  />
                  <Toggle
                    label="Server Start"
                    checked={settings.notifications?.alert_server_start ?? false}
                    onChange={(v) => updateSetting('notifications', 'alert_server_start', v)}
                  />
                  <Toggle
                    label="Server Stop"
                    checked={settings.notifications?.alert_server_stop ?? false}
                    onChange={(v) => updateSetting('notifications', 'alert_server_stop', v)}
                  />
                  <Toggle
                    label="High CPU Usage"
                    checked={settings.notifications?.alert_high_cpu ?? true}
                    onChange={(v) => updateSetting('notifications', 'alert_high_cpu', v)}
                  />
                  <Toggle
                    label="High Memory Usage"
                    checked={settings.notifications?.alert_high_memory ?? true}
                    onChange={(v) => updateSetting('notifications', 'alert_high_memory', v)}
                  />
                  <Toggle
                    label="Low Disk Space"
                    checked={settings.notifications?.alert_disk_space ?? true}
                    onChange={(v) => updateSetting('notifications', 'alert_disk_space', v)}
                  />
                </div>
              </div>

              <div className="mt-6 pt-6 border-t border-white/10">
                <h4 className="text-sm font-medium text-white/70 mb-4">Alert Thresholds</h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <Input
                    label="CPU Threshold"
                    type="number"
                    value={settings.notifications?.cpu_threshold || 90}
                    onChange={(v) => updateSetting('notifications', 'cpu_threshold', v)}
                    suffix="%"
                  />
                  <Input
                    label="Memory Threshold"
                    type="number"
                    value={settings.notifications?.memory_threshold || 90}
                    onChange={(v) => updateSetting('notifications', 'memory_threshold', v)}
                    suffix="%"
                  />
                  <Input
                    label="Disk Threshold"
                    type="number"
                    value={settings.notifications?.disk_threshold || 90}
                    onChange={(v) => updateSetting('notifications', 'disk_threshold', v)}
                    suffix="%"
                  />
                </div>
              </div>
            </Section>

            <Section title="Email Notifications" description="SMTP email configuration" icon={FaEnvelope}>
              <div className="space-y-6">
                <Toggle
                  label="Enable Email Notifications"
                  description="Send alerts via email"
                  checked={settings.notifications?.email_enabled ?? false}
                  onChange={(v) => updateSetting('notifications', 'email_enabled', v)}
                />
                
                {settings.notifications?.email_enabled && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
                    <Input
                      label="SMTP Host"
                      value={settings.notifications?.smtp_host || ''}
                      onChange={(v) => updateSetting('notifications', 'smtp_host', v)}
                      placeholder="smtp.gmail.com"
                    />
                    <Input
                      label="SMTP Port"
                      type="number"
                      value={settings.notifications?.smtp_port || 587}
                      onChange={(v) => updateSetting('notifications', 'smtp_port', v)}
                    />
                    <Input
                      label="SMTP Username"
                      value={settings.notifications?.smtp_user || ''}
                      onChange={(v) => updateSetting('notifications', 'smtp_user', v)}
                    />
                    <Input
                      label="SMTP Password"
                      type="password"
                      value={settings.notifications?.smtp_pass || ''}
                      onChange={(v) => updateSetting('notifications', 'smtp_pass', v)}
                    />
                    <Input
                      label="From Address"
                      value={settings.notifications?.smtp_from || ''}
                      onChange={(v) => updateSetting('notifications', 'smtp_from', v)}
                      placeholder="alerts@example.com"
                    />
                    <Input
                      label="To Address"
                      value={settings.notifications?.smtp_to || ''}
                      onChange={(v) => updateSetting('notifications', 'smtp_to', v)}
                      placeholder="admin@example.com"
                    />
                  </div>
                )}
              </div>
            </Section>
          </>
        )}

        {/* Security Tab */}
        {activeTab === 'security' && (
          <>
            <Section title="Session Settings" description="Authentication and session management" icon={FaShieldAlt}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Input
                  label="Session Timeout"
                  description="Hours before sessions expire"
                  type="number"
                  value={settings.security?.session_timeout_hours || 24}
                  onChange={(v) => updateSetting('security', 'session_timeout_hours', v)}
                  suffix="hours"
                />
                <Input
                  label="Max Sessions per User"
                  description="Maximum concurrent sessions"
                  type="number"
                  value={settings.security?.max_sessions_per_user || 5}
                  onChange={(v) => updateSetting('security', 'max_sessions_per_user', v)}
                />
                <Input
                  label="Failed Login Attempts"
                  description="Attempts before account lockout"
                  type="number"
                  value={settings.security?.lockout_attempts || 5}
                  onChange={(v) => updateSetting('security', 'lockout_attempts', v)}
                />
                <Input
                  label="Lockout Duration"
                  description="Minutes to lock account after failed attempts"
                  type="number"
                  value={settings.security?.lockout_duration_minutes || 15}
                  onChange={(v) => updateSetting('security', 'lockout_duration_minutes', v)}
                  suffix="min"
                />
                <Input
                  label="Minimum Password Length"
                  type="number"
                  value={settings.security?.min_password_length || 8}
                  onChange={(v) => updateSetting('security', 'min_password_length', v)}
                  suffix="chars"
                />
                <div className="flex items-center">
                  <Toggle
                    label="Require Strong Password"
                    description="Uppercase, lowercase, number, special char"
                    checked={settings.security?.require_strong_password ?? true}
                    onChange={(v) => updateSetting('security', 'require_strong_password', v)}
                  />
                </div>
              </div>
            </Section>

            <Section title="Active Sessions" description="Manage logged-in sessions" icon={FaClock}>
              <div className="flex justify-end mb-4">
                <button
                  onClick={revokeAllSessions}
                  className="px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2"
                >
                  <FaTimes className="w-3 h-3" />
                  Revoke All Other Sessions
                </button>
              </div>
              
              {sessionsLoading ? (
                <div className="text-white/60 text-center py-4">Loading sessions...</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="text-left text-white/50 border-b border-white/10">
                        <th className="px-3 py-2">IP Address</th>
                        <th className="px-3 py-2">Device</th>
                        <th className="px-3 py-2">Created</th>
                        <th className="px-3 py-2">Expires</th>
                        <th className="px-3 py-2">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/10">
                      {sessions.length === 0 ? (
                        <tr>
                          <td className="px-3 py-4 text-white/40 text-center" colSpan={5}>No active sessions</td>
                        </tr>
                      ) : (
                        sessions.map((s) => (
                          <tr key={s.id} className={`text-white/70 ${s.is_current ? 'bg-brand-500/10' : ''}`}>
                            <td className="px-3 py-2 font-mono text-xs">{s.ip_address || '—'}</td>
                            <td className="px-3 py-2 max-w-[200px] truncate text-xs" title={s.user_agent}>{s.user_agent?.split(' ')[0] || '—'}</td>
                            <td className="px-3 py-2 text-xs">{s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
                            <td className="px-3 py-2 text-xs">{s.expires_at ? new Date(s.expires_at).toLocaleString() : '—'}</td>
                            <td className="px-3 py-2">
                              {s.is_current ? (
                                <span className="text-brand-400 text-xs">Current</span>
                              ) : (
                                <button
                                  onClick={() => revokeSession(s.id)}
                                  className="px-2 py-1 rounded bg-red-600/80 hover:bg-red-600 text-white text-xs"
                                >
                                  Revoke
                                </button>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          </>
        )}

        {/* Integrations Tab */}
        {activeTab === 'integrations' && (
          <>
            <Section title="CurseForge" description="API access for modpack installation" icon={FaKey}>
              <div className="flex gap-4 items-end">
                <div className="flex-1">
                  <Input
                    label="API Key"
                    type="password"
                    value={curseforgeKey}
                    onChange={setCurseforgeKey}
                    placeholder={providersStatus?.curseforge?.configured ? '••••••••••••••••' : 'Enter your CurseForge API key'}
                  />
                </div>
                <button
                  onClick={saveCurseforgeKey}
                  disabled={!curseforgeKey}
                  className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg flex items-center gap-2 text-white"
                >
                  <FaSave className="w-4 h-4" />
                  Save Key
                </button>
              </div>
              <div className="mt-3 flex items-center gap-2">
                {providersStatus?.curseforge?.configured ? (
                  <>
                    <FaCheck className="text-green-500 w-4 h-4" />
                    <span className="text-green-400 text-sm">CurseForge API configured</span>
                  </>
                ) : (
                  <>
                    <FaTimes className="text-yellow-500 w-4 h-4" />
                    <span className="text-yellow-400 text-sm">
                      Not configured - Get a key from{' '}
                      <a
                        href="https://www.curseforge.com/minecraft/mc-mods"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        CurseForge
                      </a>
                    </span>
                  </>
                )}
              </div>
            </Section>

            <Section title="Nexus Mods" description="API access for Nexus Mods integration" icon={FaGlobe}>
              <div className="flex gap-4 items-end">
                <div className="flex-1">
                  <Input
                    label="API Key"
                    type="password"
                    value={nexusKey}
                    onChange={setNexusKey}
                    placeholder={providersStatus?.nexus?.configured ? '••••••••••••••••' : 'Enter your Nexus Mods API key'}
                  />
                </div>
                <button
                  onClick={() => saveIntegrationKey('nexus', nexusKey, setNexusKey, 'Nexus Mods')}
                  disabled={!nexusKey}
                  className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg flex items-center gap-2 text-white"
                >
                  <FaSave className="w-4 h-4" />
                  Save Key
                </button>
              </div>
              <div className="mt-3 flex items-center gap-2">
                {providersStatus?.nexus?.configured ? (
                  <>
                    <FaCheck className="text-green-500 w-4 h-4" />
                    <span className="text-green-400 text-sm">Nexus Mods API configured</span>
                  </>
                ) : (
                  <>
                    <FaTimes className="text-yellow-500 w-4 h-4" />
                    <span className="text-yellow-400 text-sm">
                      Not configured - Get a key from{' '}
                      <a
                        href="https://www.nexusmods.com/users/myaccount?tab=api+access"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        Nexus Mods
                      </a>
                    </span>
                  </>
                )}
              </div>
            </Section>

            <Section title="mod.io" description="API access for mod.io integration" icon={FaKey}>
              <div className="flex gap-4 items-end">
                <div className="flex-1">
                  <Input
                    label="API Key"
                    type="password"
                    value={modioKey}
                    onChange={setModioKey}
                    placeholder={providersStatus?.modio?.configured ? '••••••••••••••••' : 'Enter your mod.io API key'}
                  />
                </div>
                <button
                  onClick={() => saveIntegrationKey('modio', modioKey, setModioKey, 'mod.io')}
                  disabled={!modioKey}
                  className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg flex items-center gap-2 text-white"
                >
                  <FaSave className="w-4 h-4" />
                  Save Key
                </button>
              </div>
              <div className="mt-3 flex items-center gap-2">
                {providersStatus?.modio?.configured ? (
                  <>
                    <FaCheck className="text-green-500 w-4 h-4" />
                    <span className="text-green-400 text-sm">mod.io API configured</span>
                  </>
                ) : (
                  <>
                    <FaTimes className="text-yellow-500 w-4 h-4" />
                    <span className="text-yellow-400 text-sm">
                      Not configured - Get a key from{' '}
                      <a
                        href="https://mod.io/me/access"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        mod.io
                      </a>
                    </span>
                  </>
                )}
              </div>
            </Section>

            <Section title="Steam Web API" description="API access for Steam Workshop integration" icon={FaSteam}>
              <div className="flex gap-4 items-end">
                <div className="flex-1">
                  <Input
                    label="API Key"
                    type="password"
                    value={steamKey}
                    onChange={setSteamKey}
                    placeholder={providersStatus?.steam?.configured ? '••••••••••••••••' : 'Enter your Steam Web API key'}
                  />
                </div>
                <button
                  onClick={() => saveIntegrationKey('steam', steamKey, setSteamKey, 'Steam')}
                  disabled={!steamKey}
                  className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg flex items-center gap-2 text-white"
                >
                  <FaSave className="w-4 h-4" />
                  Save Key
                </button>
              </div>
              <div className="mt-3 flex items-center gap-2">
                {providersStatus?.steam?.configured ? (
                  <>
                    <FaCheck className="text-green-500 w-4 h-4" />
                    <span className="text-green-400 text-sm">Steam Web API configured</span>
                  </>
                ) : (
                  <>
                    <FaTimes className="text-yellow-500 w-4 h-4" />
                    <span className="text-yellow-400 text-sm">
                      Not configured - Get a key from{' '}
                      <a
                        href="https://steamcommunity.com/dev/apikey"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        Steam
                      </a>
                    </span>
                  </>
                )}
              </div>
            </Section>

            <Section title="Docker" description="Container runtime configuration" icon={FaDocker}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Select
                  label="Network Mode"
                  value={settings.docker?.network_mode || 'bridge'}
                  onChange={(v) => updateSetting('docker', 'network_mode', v)}
                  options={[
                    { value: 'bridge', label: 'Bridge (Recommended)' },
                    { value: 'host', label: 'Host' },
                    { value: 'none', label: 'None' }
                  ]}
                />
                <Select
                  label="Restart Policy"
                  value={settings.docker?.container_restart_policy || 'unless-stopped'}
                  onChange={(v) => updateSetting('docker', 'container_restart_policy', v)}
                  options={[
                    { value: 'unless-stopped', label: 'Unless Stopped' },
                    { value: 'always', label: 'Always' },
                    { value: 'on-failure', label: 'On Failure' },
                    { value: 'no', label: 'Never' }
                  ]}
                />
                <div className="md:col-span-2 space-y-4">
                  <Toggle
                    label="Auto Pull Images"
                    description="Automatically pull latest images when starting servers"
                    checked={settings.docker?.auto_pull_images ?? true}
                    onChange={(v) => updateSetting('docker', 'auto_pull_images', v)}
                  />
                  <Toggle
                    label="Cleanup Unused Images"
                    description="Periodically remove unused Docker images"
                    checked={settings.docker?.cleanup_unused_images ?? false}
                    onChange={(v) => updateSetting('docker', 'cleanup_unused_images', v)}
                  />
                  <Toggle
                    label="Enable Resource Limits"
                    description="Apply CPU and memory limits to containers"
                    checked={settings.docker?.resource_limits_enabled ?? true}
                    onChange={(v) => updateSetting('docker', 'resource_limits_enabled', v)}
                  />
                </div>
              </div>
            </Section>
          </>
        )}

        {/* System Tab */}
        {activeTab === 'system' && (
          <>
            <Section title="Storage Usage" description="Disk space overview" icon={FaHdd}>
              {storageInfo ? (
                <div className="space-y-4">
                  <StorageBar
                    label="System Disk"
                    used={storageInfo.disk?.used_gb || 0}
                    total={storageInfo.disk?.total_gb || 1}
                  />
                  <StorageBar
                    label={`Servers (${storageInfo.servers?.count || 0} servers)`}
                    used={storageInfo.servers?.size_gb || 0}
                    total={storageInfo.disk?.total_gb || 1}
                  />
                  <StorageBar
                    label={`Backups (${storageInfo.backups?.count || 0} files)`}
                    used={storageInfo.backups?.size_gb || 0}
                    total={settings.backup?.max_backup_size_gb || 50}
                  />
                </div>
              ) : (
                <div className="text-white/40">Loading storage info...</div>
              )}
            </Section>

            <Section title="Maintenance" description="System cleanup and maintenance tasks" icon={FaBroom}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <button
                  onClick={cleanupLogs}
                  className="p-4 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-orange-500/20 rounded-lg group-hover:bg-orange-500/30">
                      <FaTrash className="w-5 h-5 text-orange-400" />
                    </div>
                    <div>
                      <div className="font-medium text-white">Cleanup Old Logs</div>
                      <div className="text-sm text-white/50">Remove logs older than {settings.performance?.log_retention_days || 30} days</div>
                    </div>
                  </div>
                </button>
                
                <button
                  onClick={cleanupBackups}
                  className="p-4 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-red-500/20 rounded-lg group-hover:bg-red-500/30">
                      <FaDatabase className="w-5 h-5 text-red-400" />
                    </div>
                    <div>
                      <div className="font-medium text-white">Cleanup Old Backups</div>
                      <div className="text-sm text-white/50">Remove backups older than {settings.backup?.retention_days || 7} days</div>
                    </div>
                  </div>
                </button>

                <button
                  onClick={() => { loadStorageInfo(); showToast('success', 'Storage info refreshed'); }}
                  className="p-4 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-blue-500/20 rounded-lg group-hover:bg-blue-500/30">
                      <FaSync className="w-5 h-5 text-blue-400" />
                    </div>
                    <div>
                      <div className="font-medium text-white">Refresh Storage Info</div>
                      <div className="text-sm text-white/50">Recalculate disk usage statistics</div>
                    </div>
                  </div>
                </button>

                <button
                  onClick={loadJavaVersions}
                  className="p-4 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-orange-500/20 rounded-lg group-hover:bg-orange-500/30">
                      <FaJava className="w-5 h-5 text-orange-400" />
                    </div>
                    <div>
                      <div className="font-medium text-white">Detect Java Versions</div>
                      <div className="text-sm text-white/50">Scan for available Java installations</div>
                    </div>
                  </div>
                </button>
              </div>
            </Section>

            <Section title="About" description="Lynx system information" icon={FaCog}>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 bg-white/5 rounded-lg">
                  <div className="text-xs text-white/40">Version</div>
                  <div className="text-white font-mono">1.0.0</div>
                </div>
                <div className="p-3 bg-white/5 rounded-lg">
                  <div className="text-xs text-white/40">API Status</div>
                  <div className="text-green-400 flex items-center gap-1">
                    <FaCheck className="w-3 h-3" /> Online
                  </div>
                </div>
                <div className="p-3 bg-white/5 rounded-lg">
                  <div className="text-xs text-white/40">Servers</div>
                  <div className="text-white">{storageInfo?.servers?.count || 0}</div>
                </div>
                <div className="p-3 bg-white/5 rounded-lg">
                  <div className="text-xs text-white/40">Disk Free</div>
                  <div className="text-white">{storageInfo?.disk?.free_gb?.toFixed(1) || '—'} GB</div>
                </div>
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}
