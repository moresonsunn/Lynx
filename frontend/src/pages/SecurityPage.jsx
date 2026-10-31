import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FaShieldAlt,
  FaKey,
  FaNetworkWired,
  FaHistory,
  FaPlus,
  FaTrash,
  FaCheck,
  FaCopy,
  FaSync,
  FaSearch,
  FaLock,
} from 'react-icons/fa';
import { API, authHeaders, useAuth } from '../context/AppContext';
import { useTranslation } from '../i18n';

export default function SecurityPage() {
  const { t } = useTranslation();
  const { currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState('audit'); // 'audit' | '2fa' | 'ip' | 'apikeys'

  const [overview, setOverview] = useState(null);
  const [twoFAStatus, setTwoFAStatus] = useState({ enabled: false, verified_at: null });
  const [setupData, setSetupData] = useState(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [disablePassword, setDisablePassword] = useState('');

  const [whitelist, setWhitelist] = useState([]);
  const [newIp, setNewIp] = useState('');
  const [newIpDesc, setNewIpDesc] = useState('');

  const [apiKeys, setApiKeys] = useState([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [createdKeySecret, setCreatedKeySecret] = useState('');

  const [auditLogs, setAuditLogs] = useState([]);
  const [auditActions, setAuditActions] = useState([]);
  const [auditSearch, setAuditSearch] = useState('');
  const [selectedAction, setSelectedAction] = useState('');

  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const headers = authHeaders();
      const requests = [
        fetch(`${API}/security/overview`, { headers }),
        fetch(`${API}/security/2fa/status`, { headers }),
        fetch(`${API}/security/ip-whitelist`, { headers }),
        fetch(`${API}/security/audit-logs?limit=150`, { headers }),
        fetch(`${API}/security/audit-actions`, { headers }),
      ];
      if (currentUser?.id) {
        requests.push(fetch(`${API}/users/${currentUser.id}/api-keys`, { headers }));
      }

      const [ovRes, tfaRes, ipRes, audRes, actRes, keysRes] = await Promise.all(requests);

      if (ovRes && ovRes.ok) {
        setOverview(await ovRes.json());
      }
      if (tfaRes && tfaRes.ok) {
        setTwoFAStatus(await tfaRes.json());
      }
      if (ipRes && ipRes.ok) {
        const ipData = await ipRes.json();
        setWhitelist(ipData.whitelist || ipData.entries || []);
      }
      if (audRes && audRes.ok) {
        const audData = await audRes.json();
        setAuditLogs(audData.logs || []);
      } else {
        // Fallback to /api/users/audit-logs
        const fallbackRes = await fetch(`${API}/users/audit-logs?page_size=100`, { headers });
        if (fallbackRes.ok) {
          const fbData = await fallbackRes.json();
          setAuditLogs(fbData.logs || []);
        }
      }
      if (actRes && actRes.ok) {
        const actData = await actRes.json();
        setAuditActions(actData.actions || []);
      }
      if (keysRes && keysRes.ok) {
        const kData = await keysRes.json();
        setApiKeys(kData.api_keys || []);
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [currentUser?.id]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // 2FA Handlers
  async function start2FASetup() {
    setError('');
    setNotice('');
    try {
      const r = await fetch(`${API}/security/2fa/setup`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed to initialize 2FA');
      setSetupData(d);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function confirm2FASetup(e) {
    e.preventDefault();
    if (!verifyCode.trim()) return;
    setError('');
    try {
      const r = await fetch(`${API}/security/2fa/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ code: verifyCode.trim() }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Invalid verification code');
      setSetupData(null);
      setVerifyCode('');
      setNotice('Two-Factor Authentication enabled.');
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function handleDisable2FA(e) {
    e.preventDefault();
    if (!disablePassword) return;
    setError('');
    try {
      const r = await fetch(`${API}/security/2fa/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ password: disablePassword }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed to disable 2FA');
      setDisablePassword('');
      setNotice('Two-Factor Authentication disabled.');
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  // IP Whitelist Handlers
  async function handleAddIp(e) {
    e.preventDefault();
    if (!newIp.trim()) return;
    setError('');
    try {
      const r = await fetch(`${API}/security/ip-whitelist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          ip_address: newIp.trim(),
          description: newIpDesc.trim() || 'Allowed IP',
          enabled: true,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed to add IP');
      setNewIp('');
      setNewIpDesc('');
      setNotice(`Added ${newIp.trim()} to IP whitelist.`);
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function handleRemoveIp(ipAddress) {
    if (!confirm(`Remove ${ipAddress} from whitelist?`)) return;
    setError('');
    try {
      const r = await fetch(`${API}/security/ip-whitelist/${encodeURIComponent(ipAddress)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to remove IP');
      }
      setNotice(`Removed ${ipAddress} from whitelist.`);
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  // API Key Handlers
  async function handleCreateApiKey(e) {
    e.preventDefault();
    if (!newKeyName.trim() || !currentUser?.id) return;
    setError('');
    try {
      const r = await fetch(`${API}/users/${currentUser.id}/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: newKeyName.trim(), expires_days: 90 }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed to create API key');
      setCreatedKeySecret(d.key || '');
      setNewKeyName('');
      setNotice(`Created API key "${d.name}"`);
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function handleRevokeApiKey(keyId) {
    if (!currentUser?.id || !confirm('Revoke this API key?')) return;
    setError('');
    try {
      const r = await fetch(`${API}/users/${currentUser.id}/api-keys/${keyId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) throw new Error('Failed to revoke API key');
      setNotice('API key revoked.');
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  const filteredAuditLogs = useMemo(() => {
    return auditLogs.filter((log) => {
      if (selectedAction && log.action !== selectedAction) return false;
      if (auditSearch.trim()) {
        const q = auditSearch.toLowerCase();
        const userStr = (log.user || log.username || '').toLowerCase();
        const actionStr = (log.action || '').toLowerCase();
        const resStr = `${log.resource_type || ''}/${log.resource_id || ''}`.toLowerCase();
        const ipStr = (log.ip_address || '').toLowerCase();
        return (
          userStr.includes(q) ||
          actionStr.includes(q) ||
          resStr.includes(q) ||
          ipStr.includes(q)
        );
      }
      return true;
    });
  }, [auditLogs, selectedAction, auditSearch]);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      {/* Clean Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <h1 className="text-xl font-semibold text-white">
            {t('security.title') || 'Security & Audit'}
          </h1>
          <p className="text-xs text-white/50 mt-0.5">
            Security audit trail, Two-Factor Authentication (TOTP), IP access control, and personal API keys.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {overview?.current_ip && (
            <span className="text-xs px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-white/60 font-mono">
              Your IP: {overview.current_ip}
            </span>
          )}
          <button
            onClick={loadAll}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
          >
            <FaSync className={`text-[11px] ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Notices & Errors */}
      {notice && (
        <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-4 py-2.5 text-xs text-emerald-300 flex items-center justify-between">
          <span>{notice}</span>
          <button onClick={() => setNotice('')} className="text-emerald-300/60 hover:text-emerald-200">✕</button>
        </div>
      )}
      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-xs text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-300/60 hover:text-red-200">✕</button>
        </div>
      )}

      {/* Compact Status Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-white/45">Two-Factor Auth (2FA)</div>
            <div className="text-sm font-medium text-white mt-0.5">
              {twoFAStatus.enabled ? 'Enabled on your account' : 'Not configured'}
            </div>
          </div>
          <span
            className={`text-xs px-2 py-0.5 rounded border ${twoFAStatus.enabled
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                : 'bg-white/5 text-white/50 border-white/10'
              }`}
          >
            {twoFAStatus.enabled ? 'Active' : 'Off'}
          </span>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-white/45">IP Whitelist</div>
            <div className="text-sm font-medium text-white mt-0.5">
              {whitelist.length > 0 ? `${whitelist.length} allowed rule(s)` : 'All IPs allowed'}
            </div>
          </div>
          <span className="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-white/60 font-mono">
            {whitelist.length}
          </span>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-white/45">Personal API Keys</div>
            <div className="text-sm font-medium text-white mt-0.5">
              {apiKeys.length} active key{apiKeys.length === 1 ? '' : 's'}
            </div>
          </div>
          <span className="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-white/60 font-mono">
            {apiKeys.length}
          </span>
        </div>
      </div>

      {/* Clean Underline Tabs */}
      <div className="flex items-center gap-6 border-b border-white/10 text-sm overflow-x-auto no-scrollbar">
        {[
          { id: 'audit', label: 'Security Audit Log', count: auditLogs.length, icon: FaHistory },
          { id: '2fa', label: 'Two-Factor Auth (2FA)', icon: FaShieldAlt },
          { id: 'ip', label: 'IP Whitelist', count: whitelist.length, icon: FaNetworkWired },
          { id: 'apikeys', label: 'API Keys', count: apiKeys.length, icon: FaKey },
        ].map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 -mb-px flex items-center gap-2 border-b-2 font-medium whitespace-nowrap transition-colors ${active
                  ? 'border-brand-500 text-white'
                  : 'border-transparent text-white/55 hover:text-white/85'
                }`}
            >
              <tab.icon className={`text-xs ${active ? 'text-brand-400' : 'text-white/40'}`} />
              <span>{tab.label}</span>
              {tab.count !== undefined && (
                <span className="text-xs px-1.5 py-0.2 rounded bg-white/5 text-white/60 font-mono">
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* TAB 1: SECURITY AUDIT LOG */}
      {activeTab === 'audit' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-sm">
              <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
              <input
                type="text"
                value={auditSearch}
                onChange={(e) => setAuditSearch(e.target.value)}
                placeholder="Search user, action, resource, or IP…"
                className="w-full pl-8 pr-3 py-1.5 bg-white/[0.03] border border-white/10 rounded-lg text-xs text-white placeholder-white/35 focus:outline-none focus:border-brand-500"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={selectedAction}
                onChange={(e) => setSelectedAction(e.target.value)}
                className="px-2.5 py-1.5 bg-[#141824] border border-white/10 rounded-lg text-xs text-white"
              >
                <option value="">All Actions ({auditLogs.length})</option>
                {auditActions.map((act) => (
                  <option key={act} value={act}>
                    {act}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/45 bg-white/[0.02]">
                    <th className="py-2.5 px-4 font-medium">Timestamp</th>
                    <th className="py-2.5 px-4 font-medium">User</th>
                    <th className="py-2.5 px-4 font-medium">Action</th>
                    <th className="py-2.5 px-4 font-medium">Target Resource</th>
                    <th className="py-2.5 px-4 font-medium">IP Address</th>
                    <th className="py-2.5 px-4 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-xs">
                  {filteredAuditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-white/[0.02]">
                      <td className="py-2.5 px-4 text-white/55 whitespace-nowrap font-mono">
                        {log.timestamp ? new Date(log.timestamp).toLocaleString() : '—'}
                      </td>
                      <td className="py-2.5 px-4 text-white font-medium">
                        {log.user || log.username || 'System'}
                      </td>
                      <td className="py-2.5 px-4">
                        <span className="px-2 py-0.5 rounded bg-white/5 border border-white/10 font-mono text-brand-300">
                          {log.action}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-white/60 font-mono">
                        {log.resource_type
                          ? `${log.resource_type}${log.resource_id ? `/${log.resource_id}` : ''}`
                          : '—'}
                      </td>
                      <td className="py-2.5 px-4 text-white/45 font-mono">
                        {log.ip_address || '—'}
                      </td>
                      <td className="py-2.5 px-4 text-white/45 font-mono max-w-xs truncate">
                        {log.details && Object.keys(log.details).length > 0
                          ? JSON.stringify(log.details)
                          : '—'}
                      </td>
                    </tr>
                  ))}
                  {filteredAuditLogs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-white/40">
                        No audit log entries match your filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: TWO-FACTOR AUTHENTICATION */}
      {activeTab === '2fa' && (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5 max-w-2xl space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-white">
                Authenticator App (TOTP)
              </h3>
              <p className="text-xs text-white/50 mt-1">
                Protect your account with a time-based 6-digit verification code from Google Authenticator, Authy, 1Password, or Bitwarden.
              </p>
            </div>
            <span
              className={`text-xs px-2.5 py-1 rounded border font-medium ${twoFAStatus.enabled
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                  : 'bg-white/5 text-white/50 border-white/10'
                }`}
            >
              {twoFAStatus.enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>

          {!twoFAStatus.enabled && !setupData && (
            <div className="pt-2">
              <button
                onClick={start2FASetup}
                className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-2 transition-colors"
              >
                <FaShieldAlt /> Set Up Two-Factor Authentication
              </button>
            </div>
          )}

          {setupData && (
            <div className="space-y-4 pt-3 border-t border-white/10">
              <div className="flex flex-col sm:flex-row gap-5 items-start">
                {setupData.qr_code_url && (
                  <div className="bg-white p-2.5 rounded-lg flex-shrink-0">
                    <img
                      src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(
                        setupData.qr_code_url
                      )}`}
                      alt="2FA QR Code"
                      className="w-36 h-36"
                    />
                  </div>
                )}
                <div className="space-y-2 text-xs">
                  <div className="text-white font-medium">1. Scan QR Code or Enter Secret Key</div>
                  <p className="text-white/50">
                    Scan the QR code with your authenticator app, or manually enter this secret key:
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="px-2.5 py-1.5 rounded bg-black/40 border border-white/10 text-brand-300 font-mono select-all">
                      {setupData.secret}
                    </code>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(setupData.secret)}
                      className="px-2.5 py-1.5 rounded bg-white/5 hover:bg-white/10 text-white/70"
                    >
                      <FaCopy />
                    </button>
                  </div>

                  {Array.isArray(setupData.backup_codes) && setupData.backup_codes.length > 0 && (
                    <div className="pt-2">
                      <div className="text-white/70 font-medium mb-1">
                        Save your recovery backup codes:
                      </div>
                      <div className="grid grid-cols-2 gap-1.5 p-2.5 rounded bg-black/30 border border-white/10 font-mono text-[11px] text-white/75">
                        {setupData.backup_codes.map((c) => (
                          <span key={c}>{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <form onSubmit={confirm2FASetup} className="flex items-end gap-3 pt-2">
                <div>
                  <label className="block text-xs text-white/60 mb-1">
                    2. Enter 6-digit code from app
                  </label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    placeholder="123456"
                    value={verifyCode}
                    onChange={(e) => setVerifyCode(e.target.value)}
                    className="w-40 px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-sm text-white font-mono tracking-widest"
                  />
                </div>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-1.5"
                >
                  <FaCheck /> Verify & Activate
                </button>
                <button
                  type="button"
                  onClick={() => setSetupData(null)}
                  className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white/60"
                >
                  Cancel
                </button>
              </form>
            </div>
          )}

          {twoFAStatus.enabled && (
            <form onSubmit={handleDisable2FA} className="pt-3 border-t border-white/10 space-y-3">
              <div className="text-xs text-white/60">
                Enter your account password to disable Two-Factor Authentication:
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  required
                  placeholder="Current password"
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  className="px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-xs text-white"
                />
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg bg-red-500/15 hover:bg-red-500/25 border border-red-500/25 text-xs text-red-300 font-medium"
                >
                  Disable 2FA
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* TAB 3: IP WHITELIST */}
      {activeTab === 'ip' && (
        <div className="space-y-4">
          <form
            onSubmit={handleAddIp}
            className="rounded-xl border border-white/10 bg-white/[0.02] p-4 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-white/55 mb-1">
                IP Address or CIDR Range
              </label>
              <input
                type="text"
                required
                placeholder="e.g. 192.168.2.100 or 192.168.2.0/24"
                value={newIp}
                onChange={(e) => setNewIp(e.target.value)}
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-xs text-white font-mono"
              />
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-white/55 mb-1">Description</label>
              <input
                type="text"
                placeholder="e.g. Home LAN / Admin Workstation"
                value={newIpDesc}
                onChange={(e) => setNewIpDesc(e.target.value)}
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-xs text-white"
              />
            </div>
            {overview?.current_ip && (
              <button
                type="button"
                onClick={() => {
                  setNewIp(overview.current_ip);
                  setNewIpDesc('Current session IP');
                }}
                className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/75"
              >
                Use My IP ({overview.current_ip})
              </button>
            )}
            <button
              type="submit"
              className="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-1.5"
            >
              <FaPlus className="text-[10px]" /> Add IP
            </button>
          </form>

          <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/45 bg-white/[0.02]">
                  <th className="py-2.5 px-4 font-medium">IP Address / CIDR</th>
                  <th className="py-2.5 px-4 font-medium">Description</th>
                  <th className="py-2.5 px-4 font-medium">Added</th>
                  <th className="py-2.5 px-4 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10 text-xs">
                {whitelist.map((item) => (
                  <tr key={item.ip_address} className="hover:bg-white/[0.02]">
                    <td className="py-3 px-4 font-mono text-white font-medium">
                      {item.ip_address}
                    </td>
                    <td className="py-3 px-4 text-white/65">{item.description || '—'}</td>
                    <td className="py-3 px-4 text-white/45">
                      {item.added_at ? new Date(item.added_at).toLocaleString() : '—'}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => handleRemoveIp(item.ip_address)}
                        className="p-1.5 rounded hover:bg-red-500/15 text-red-400 hover:text-red-300"
                        title="Remove IP"
                      >
                        <FaTrash />
                      </button>
                    </td>
                  </tr>
                ))}
                {whitelist.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-white/40">
                      No IP restrictions configured — connections from all IP addresses are currently allowed.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 4: API KEYS */}
      {activeTab === 'apikeys' && (
        <div className="space-y-4">
          <form
            onSubmit={handleCreateApiKey}
            className="rounded-xl border border-white/10 bg-white/[0.02] p-4 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[240px]">
              <label className="block text-xs text-white/55 mb-1">Key Name / Label</label>
              <input
                type="text"
                required
                placeholder="e.g. CI Deployment Script, Discord Bot"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                className="w-full px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-xs text-white"
              />
            </div>
            <button
              type="submit"
              className="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-1.5"
            >
              <FaPlus className="text-[10px]" /> Generate API Key
            </button>
          </form>

          {createdKeySecret && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-2 text-xs">
              <div className="font-semibold text-amber-300">
                Copy your new API key now — it will not be shown again:
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 px-3 py-2 rounded bg-black/50 border border-white/10 text-white font-mono select-all">
                  {createdKeySecret}
                </code>
                <button
                  onClick={() => navigator.clipboard.writeText(createdKeySecret)}
                  className="px-3 py-2 rounded bg-white/10 hover:bg-white/20 text-white inline-flex items-center gap-1.5"
                >
                  <FaCopy /> Copy
                </button>
                <button
                  onClick={() => setCreatedKeySecret('')}
                  className="px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-white/60"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/45 bg-white/[0.02]">
                  <th className="py-2.5 px-4 font-medium">Name</th>
                  <th className="py-2.5 px-4 font-medium">Prefix</th>
                  <th className="py-2.5 px-4 font-medium">Created</th>
                  <th className="py-2.5 px-4 font-medium">Last Used</th>
                  <th className="py-2.5 px-4 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10 text-xs">
                {apiKeys.map((k) => (
                  <tr key={k.id} className="hover:bg-white/[0.02]">
                    <td className="py-3 px-4 text-white font-medium">{k.name}</td>
                    <td className="py-3 px-4 font-mono text-white/60">{k.key_prefix}…</td>
                    <td className="py-3 px-4 text-white/45">
                      {k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-3 px-4 text-white/45">
                      {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'Never'}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => handleRevokeApiKey(k.id)}
                        className="p-1.5 rounded hover:bg-red-500/15 text-red-400 hover:text-red-300"
                        title="Revoke API key"
                      >
                        <FaTrash />
                      </button>
                    </td>
                  </tr>
                ))}
                {apiKeys.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-white/40">
                      No personal API keys created yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
