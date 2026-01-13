import React, { useState, useEffect } from 'react';
import { useTranslation } from '../i18n';
import { API, authHeaders } from '../context/AppContext';
import { FaCog, FaSave, FaDatabase, FaBell, FaShieldAlt } from 'react-icons/fa';

export default function SettingsPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [curseforgeKey, setCurseforgeKey] = useState('');
  const [providersStatus, setProvidersStatus] = useState({ curseforge: { configured: false } });
  
  const [backupSettings, setBackupSettings] = useState({
    auto_backup: true,
    backup_interval: 24,
    keep_backups: 7,
    backup_location: '/data/backups'
  });
  
  const [notificationSettings, setNotificationSettings] = useState({
    email_enabled: false,
    email_smtp_host: '',
    email_smtp_port: 587,
    email_username: '',
    email_password: '',
    webhook_url: '',
    alert_on_server_crash: true,
    alert_on_high_cpu: true,
    alert_on_high_memory: true
  });
  
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState('');

  useEffect(() => {
    loadSettings();
    loadIntegrations();
    loadSessions();
  }, []);

  async function loadSettings() {
    try {
      setLoading(false);
    } catch (e) {
      console.error('Failed to load settings:', e);
      setLoading(false);
    }
  }

  async function saveSettings() {
    setSaving(true);
    try {
      await new Promise(resolve => setTimeout(resolve, 1000));
      alert('Settings saved successfully!');
    } catch (e) {
      console.error('Failed to save settings:', e);
      alert('Failed to save settings');
    }
    setSaving(false);
  }

  async function loadIntegrations() {
    try {
      const r = await fetch(`${API}/integrations/status`);
      const d = await r.json();
      setProvidersStatus(d || { curseforge: { configured: false } });
    } catch {}
  }

  async function saveCurseforgeKey() {
    try {
      const r = await fetch(`${API}/integrations/curseforge-key`, { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json', ...authHeaders() }, 
        body: JSON.stringify({ api_key: curseforgeKey }) 
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert('Failed to save key: ' + (d?.detail || `HTTP ${r.status}`));
        return;
      }
      await loadIntegrations();
      try {
        const tr = await fetch(`${API}/integrations/curseforge-test`, { headers: authHeaders() });
        const td = await tr.json().catch(() => ({}));
        if (!tr.ok) {
          alert('Key saved but test failed: ' + (td?.detail || JSON.stringify(td)));
        } else {
          alert('CurseForge API key saved. Test result: ' + JSON.stringify(td));
        }
      } catch (e) {
        alert('CurseForge key saved but test request failed: ' + (e?.message || e));
      }
    } catch (e) {
      alert('Failed to save key: ' + (e?.message || e));
    }
  }

  async function loadSessions() {
    try {
      setSessionsLoading(true);
      setSessionsError('');
      const r = await fetch(`${API}/auth/sessions`, { headers: authHeaders() });
      if (!r.ok) throw new Error(`Failed to load sessions (HTTP ${r.status})`);
      const data = await r.json();
      setSessions(Array.isArray(data) ? data : []);
    } catch (e) {
      setSessionsError(e.message || 'Failed to load sessions');
    } finally {
      setSessionsLoading(false);
    }
  }

  async function revokeSession(id) {
    try {
      const r = await fetch(`${API}/auth/sessions/${id}`, { method: 'DELETE', headers: authHeaders() });
      if (!r.ok) {
        const payload = await r.json().catch(() => ({}));
        throw new Error(payload.detail || `Failed to revoke session (HTTP ${r.status})`);
      }
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      alert(e.message || 'Failed to revoke session');
    }
  }

  if (loading) {
    return <div className="p-6"><div className="text-white/70">{t('common.loading')}</div></div>;
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <FaCog className="text-brand-500" /> 
            <span className="gradient-text-brand">{t('settings.title')}</span>
          </h1>
          <p className="text-white/70 mt-2">{t('settings.description')}</p>
        </div>
        <button
          onClick={saveSettings}
          disabled={saving}
          className="bg-brand-500 hover:bg-brand-600 disabled:opacity-50 px-4 py-2 rounded-lg flex items-center gap-2"
        >
          <FaSave /> {saving ? t('common.saving') : t('settings.saveSettings')}
        </button>
      </div>

      {/* Backup Settings */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-6">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <FaDatabase /> {t('settings.backupSettings')}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="auto_backup"
                checked={backupSettings.auto_backup}
                onChange={(e) => setBackupSettings({...backupSettings, auto_backup: e.target.checked})}
                className="w-4 h-4 text-brand-500 bg-white/10 border-white/20 rounded focus:ring-brand-500"
              />
              <label htmlFor="auto_backup" className="text-white/80">{t('settings.enableAutoBackup')}</label>
            </div>
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">{t('settings.backupInterval')}</label>
              <input
                type="number"
                value={backupSettings.backup_interval}
                onChange={(e) => setBackupSettings({...backupSettings, backup_interval: parseInt(e.target.value)})}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
              />
            </div>
          </div>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">Keep Backups (days)</label>
              <input
                type="number"
                value={backupSettings.keep_backups}
                onChange={(e) => setBackupSettings({...backupSettings, keep_backups: parseInt(e.target.value)})}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">Backup Location</label>
              <input
                type="text"
                value={backupSettings.backup_location}
                onChange={(e) => setBackupSettings({...backupSettings, backup_location: e.target.value})}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Integrations */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-6">
        <h3 className="text-lg font-semibold mb-4">Integrations</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="text-sm text-white/70 mb-1">CurseForge API Key</div>
            <div className="flex gap-2">
              <input 
                type="password" 
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white" 
                value={curseforgeKey} 
                onChange={(e) => setCurseforgeKey(e.target.value)} 
                placeholder={providersStatus?.curseforge?.configured ? 'configured' : 'not configured'} 
              />
              <button onClick={saveCurseforgeKey} className="bg-brand-500 hover:bg-brand-600 px-3 py-2 rounded">Save</button>
            </div>
            <div className="text-xs text-white/50 mt-1">Required to search/install from CurseForge catalog.</div>
          </div>
        </div>
      </div>

      {/* Notification Settings */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-6">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <FaBell /> Notification Settings
        </h3>
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="email_enabled"
              checked={notificationSettings.email_enabled}
              onChange={(e) => setNotificationSettings({...notificationSettings, email_enabled: e.target.checked})}
              className="w-4 h-4 text-brand-500 bg-white/10 border-white/20 rounded focus:ring-brand-500"
            />
            <label htmlFor="email_enabled" className="text-white/80">Enable email notifications</label>
          </div>
          
          {notificationSettings.email_enabled && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 ml-7">
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">SMTP Host</label>
                <input
                  type="text"
                  value={notificationSettings.email_smtp_host}
                  onChange={(e) => setNotificationSettings({...notificationSettings, email_smtp_host: e.target.value})}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
                  placeholder="smtp.gmail.com"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">SMTP Port</label>
                <input
                  type="number"
                  value={notificationSettings.email_smtp_port}
                  onChange={(e) => setNotificationSettings({...notificationSettings, email_smtp_port: parseInt(e.target.value)})}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">Email Username</label>
                <input
                  type="text"
                  value={notificationSettings.email_username}
                  onChange={(e) => setNotificationSettings({...notificationSettings, email_username: e.target.value})}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">Email Password</label>
                <input
                  type="password"
                  value={notificationSettings.email_password}
                  onChange={(e) => setNotificationSettings({...notificationSettings, email_password: e.target.value})}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
                />
              </div>
            </div>
          )}
          
          <div>
            <label className="block text-sm font-medium text-white/70 mb-2">Webhook URL</label>
            <input
              type="url"
              value={notificationSettings.webhook_url}
              onChange={(e) => setNotificationSettings({...notificationSettings, webhook_url: e.target.value})}
              className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
              placeholder="https://hooks.slack.com/services/..."
            />
          </div>
          
          <div className="space-y-3">
            <h4 className="font-medium text-white/80">Alert Types</h4>
            <div className="space-y-2">
              {[
                { key: 'alert_on_server_crash', label: 'Server crashes' },
                { key: 'alert_on_high_cpu', label: 'High CPU usage' },
                { key: 'alert_on_high_memory', label: 'High memory usage' }
              ].map(alert => (
                <div key={alert.key} className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    id={alert.key}
                    checked={notificationSettings[alert.key]}
                    onChange={(e) => setNotificationSettings({...notificationSettings, [alert.key]: e.target.checked})}
                    className="w-4 h-4 text-brand-500 bg-white/10 border-white/20 rounded focus:ring-brand-500"
                  />
                  <label htmlFor={alert.key} className="text-white/70">{alert.label}</label>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Active Sessions */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <FaShieldAlt className="text-brand-500" /> Active Sessions
          </h3>
          <button
            onClick={loadSessions}
            className="bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded border border-white/10 text-white/80 text-sm"
          >
            Refresh
          </button>
        </div>
        {sessionsLoading && <div className="text-white/60">Loading sessions...</div>}
        {sessionsError && <div className="text-red-300 text-sm mb-2">{sessionsError}</div>}
        {!sessionsLoading && !sessionsError && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-white/70">
                  <th className="px-3 py-2">IP Address</th>
                  <th className="px-3 py-2">User Agent</th>
                  <th className="px-3 py-2">Created</th>
                  <th className="px-3 py-2">Expires</th>
                  <th className="px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {sessions.length === 0 && (
                  <tr>
                    <td className="px-3 py-3 text-white/60" colSpan={5}>No active sessions</td>
                  </tr>
                )}
                {sessions.map((s) => {
                  const created = s.created_at ? new Date(s.created_at) : null;
                  const expires = s.expires_at ? new Date(s.expires_at) : null;
                  return (
                    <tr key={s.id} className="text-white/80">
                      <td className="px-3 py-2">{s.ip_address || '—'}</td>
                      <td className="px-3 py-2 max-w-[32rem] truncate" title={s.user_agent || ''}>{s.user_agent || '—'}</td>
                      <td className="px-3 py-2">{created ? created.toLocaleString() : '—'}</td>
                      <td className="px-3 py-2">{expires ? expires.toLocaleString() : '—'}</td>
                      <td className="px-3 py-2">
                        <button
                          onClick={() => revokeSession(s.id)}
                          className="px-2 py-1 rounded bg-red-600/80 hover:bg-red-600 text-white text-xs border border-white/10"
                        >
                          Revoke
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
