import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { API, authHeaders, useAuth } from '../context/AppContext';
import {
  FaShieldAlt,
  FaKey,
  FaLock,
  FaUnlock,
  FaListAlt,
  FaNetworkWired,
  FaCopy,
  FaCheck,
  FaPlus,
  FaTrash,
  FaExclamationTriangle,
  FaSearch,
  FaSyncAlt,
  FaQrcode,
  FaCheckCircle,
  FaTimesCircle,
  FaUserShield,
  FaGlobe,
  FaArrowRight,
} from 'react-icons/fa';

export default function SecurityPage() {
  const { isAdmin } = useAuth();
  const [activeTab, setActiveTab] = useState('overview');
  const [overview, setOverview] = useState(null);
  const [twoFAStatus, setTwoFAStatus] = useState(null);
  const [twoFASetup, setTwoFASetup] = useState(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [regenCode, setRegenCode] = useState('');
  const [backupCodes, setBackupCodes] = useState(null);
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);

  // Audit logs
  const [auditLogs, setAuditLogs] = useState([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(0);
  const [auditAction, setAuditAction] = useState('');
  const [auditActions, setAuditActions] = useState([]);
  const [auditSearch, setAuditSearch] = useState('');

  // IP whitelist
  const [whitelist, setWhitelist] = useState([]);
  const [newIP, setNewIP] = useState('');
  const [newIPDesc, setNewIPDesc] = useState('');

  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const showMsg = (msg) => {
    setMessage(msg);
    setError(null);
    setTimeout(() => setMessage(null), 5000);
  };
  const showErr = (msg) => {
    setError(msg);
    setMessage(null);
    setTimeout(() => setError(null), 5000);
  };

  const fetchOverview = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/overview`, { headers: authHeaders() });
      if (r.ok) setOverview(await r.json());
    } catch { }
  }, []);

  const fetch2FAStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/2fa/status`, { headers: authHeaders() });
      if (r.ok) setTwoFAStatus(await r.json());
    } catch { }
  }, []);

  const fetchAuditLogs = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: '50', offset: String(auditPage * 50) });
      if (auditAction) params.set('action', auditAction);
      const r = await fetch(`${API}/security/audit-logs?${params}`, { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setAuditLogs(d.logs || []);
        setAuditTotal(d.total || 0);
      }
    } catch { }
  }, [auditPage, auditAction]);

  const fetchAuditActions = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/audit-actions`, { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setAuditActions(d.actions || []);
      }
    } catch { }
  }, []);

  const fetchWhitelist = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/ip-whitelist`, { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setWhitelist(d.entries || []);
      }
    } catch { }
  }, []);

  useEffect(() => {
    fetchOverview();
    fetch2FAStatus();
    if (isAdmin) {
      fetchWhitelist();
      fetchAuditLogs();
      fetchAuditActions();
    }
  }, [fetchOverview, fetch2FAStatus, fetchWhitelist, fetchAuditLogs, fetchAuditActions, isAdmin]);

  useEffect(() => {
    if (activeTab === 'audit' && isAdmin) {
      fetchAuditLogs();
      fetchAuditActions();
    }
    if (activeTab === 'ip-whitelist' && isAdmin) {
      fetchWhitelist();
    }
  }, [activeTab, isAdmin, fetchAuditLogs, fetchAuditActions, fetchWhitelist]);

  // 2FA actions
  const handleSetup2FA = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/security/2fa/setup`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) {
        const d = await r.json();
        setTwoFASetup(d);
        setBackupCodes(d.backup_codes);
      } else {
        const err = await r.json().catch(() => ({}));
        showErr(err.detail || 'Failed to setup 2FA');
      }
    } catch (e) {
      showErr(e.message);
    }
    setLoading(false);
  };

  const handleVerify2FA = async () => {
    if (!verifyCode || verifyCode.length < 6) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/security/2fa/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ code: verifyCode }),
      });
      if (r.ok) {
        showMsg('Two-factor authentication enabled successfully!');
        setTwoFASetup(null);
        setVerifyCode('');
        fetch2FAStatus();
        fetchOverview();
      } else {
        const err = await r.json().catch(() => ({}));
        showErr(err.detail || 'Invalid verification code');
      }
    } catch (e) {
      showErr(e.message);
    }
    setLoading(false);
  };

  const handleDisable2FA = async () => {
    if (!disableCode) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/security/2fa/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ code: disableCode }),
      });
      if (r.ok) {
        showMsg('Two-factor authentication disabled.');
        setDisableCode('');
        setBackupCodes(null);
        fetch2FAStatus();
        fetchOverview();
      } else {
        const err = await r.json().catch(() => ({}));
        showErr(err.detail || 'Invalid code');
      }
    } catch (e) {
      showErr(e.message);
    }
    setLoading(false);
  };

  const handleRegenBackupCodes = async () => {
    if (!regenCode) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/security/2fa/regenerate-backup-codes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ code: regenCode }),
      });
      if (r.ok) {
        const d = await r.json();
        setBackupCodes(d.backup_codes);
        setRegenCode('');
        showMsg('New backup codes generated!');
      } else {
        const err = await r.json().catch(() => ({}));
        showErr(err.detail || 'Invalid code');
      }
    } catch (e) {
      showErr(e.message);
    }
    setLoading(false);
  };

  // IP whitelist actions
  const handleAddIP = async (ipOverride, descOverride) => {
    const ipToSave = (ipOverride ?? newIP).trim();
    const descToSave = descOverride ?? newIPDesc;
    if (!ipToSave) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/security/ip-whitelist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ ip_address: ipToSave, description: descToSave }),
      });
      if (r.ok) {
        showMsg(`Added ${ipToSave} to IP whitelist`);
        if (!ipOverride) {
          setNewIP('');
          setNewIPDesc('');
        }
        fetchWhitelist();
        fetchOverview();
      } else {
        const err = await r.json().catch(() => ({}));
        showErr(err.detail || 'Failed to add IP');
      }
    } catch (e) {
      showErr(e.message);
    }
    setLoading(false);
  };

  const handleRemoveIP = async (id) => {
    try {
      const r = await fetch(`${API}/security/ip-whitelist/${id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (r.ok) {
        showMsg('IP removed from whitelist');
        fetchWhitelist();
        fetchOverview();
      }
    } catch (e) {
      showErr(e.message);
    }
  };

  const handleToggleIP = async (id) => {
    try {
      const r = await fetch(`${API}/security/ip-whitelist/${id}/toggle`, {
        method: 'PATCH',
        headers: authHeaders(),
      });
      if (r.ok) {
        fetchWhitelist();
        fetchOverview();
      }
    } catch (e) {
      showErr(e.message);
    }
  };

  const copyBackupCodes = () => {
    if (backupCodes) {
      navigator.clipboard.writeText(backupCodes.join('\n'));
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 2000);
    }
  };

  const copySecretKey = () => {
    if (twoFASetup?.secret) {
      navigator.clipboard.writeText(twoFASetup.secret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2000);
    }
  };

  // Compute Security Score
  const securityScore = useMemo(() => {
    let score = 50; // Base authenticated + RBAC score
    if (twoFAStatus?.enabled || overview?.two_factor_enabled) score += 35;
    if ((overview?.recent_failed_logins || 0) === 0) score += 10;
    if (overview?.ip_whitelist_active || whitelist.some(w => w.is_active)) score += 5;
    return Math.min(100, score);
  }, [twoFAStatus, overview, whitelist]);

  const tabs = [
    { id: 'overview', label: 'Security Posture', icon: FaShieldAlt },
    { id: '2fa', label: 'Two-Factor Auth (2FA)', icon: FaKey },
    ...(isAdmin ? [
      { id: 'ip-whitelist', label: 'IP Access Control', icon: FaNetworkWired, badge: whitelist.length },
      { id: 'audit', label: 'Security Audit Log', icon: FaListAlt, badge: auditTotal },
    ] : []),
  ];

  const filteredLogs = useMemo(() => {
    const q = auditSearch.trim().toLowerCase();
    if (!q) return auditLogs;
    return auditLogs.filter(l =>
      (l.action || '').toLowerCase().includes(q) ||
      (l.ip_address || '').toLowerCase().includes(q) ||
      JSON.stringify(l.details || {}).toLowerCase().includes(q)
    );
  }, [auditLogs, auditSearch]);

  const twoFAEnabled = Boolean(twoFAStatus?.enabled ?? overview?.two_factor_enabled);

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/20 text-white">
            <FaShieldAlt className="text-xl" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Security Center</h1>
            <p className="text-xs sm:text-sm text-white/55">
              Two-factor authentication, network access rules, and real-time security monitoring
            </p>
          </div>
        </div>

        {/* Security Score Pill */}
        <div className="glassmorphism rounded-2xl px-4 py-2.5 border border-white/10 flex items-center gap-3 self-start sm:self-auto">
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center font-bold text-sm tabular-nums ${
            securityScore >= 85
              ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
              : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
          }`}>
            {securityScore}%
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-white/45">Protection Level</div>
            <div className="text-xs font-semibold text-white">
              {securityScore >= 85 ? 'Strong Protection' : 'Standard (Enable 2FA recommended)'}
            </div>
          </div>
        </div>
      </div>

      {/* Messages */}
      {message && (
        <div className="p-4 bg-emerald-500/15 border border-emerald-500/30 rounded-xl text-emerald-300 text-sm flex items-center gap-2.5">
          <FaCheckCircle className="flex-shrink-0" />
          <span>{message}</span>
        </div>
      )}
      {error && (
        <div className="p-4 bg-red-500/15 border border-red-500/30 rounded-xl text-red-300 text-sm flex items-center gap-2.5">
          <FaExclamationTriangle className="flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Segmented Navigation */}
      <div className="flex items-center gap-1.5 p-1.5 rounded-2xl bg-white/5 border border-white/10 w-fit max-w-full overflow-x-auto">
        {tabs.map(tab => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-medium flex items-center gap-2 transition-all whitespace-nowrap ${
                active
                  ? 'bg-brand-500 text-white shadow-sm shadow-brand-500/30'
                  : 'text-white/65 hover:text-white hover:bg-white/5'
              }`}
            >
              <tab.icon className="text-xs" />
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-semibold tabular-nums ${
                  active ? 'bg-white/20 text-white' : 'bg-white/10 text-white/60'
                }`}>
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* ======================== OVERVIEW TAB ======================== */}
      {activeTab === 'overview' && (
        <div className="space-y-5">
          {/* Status KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="glassmorphism rounded-2xl p-5 border border-white/10 flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-white/50 uppercase tracking-wider">2FA Protection</span>
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                  twoFAEnabled ? 'bg-emerald-500/15 text-emerald-400' : 'bg-amber-500/15 text-amber-400'
                }`}>
                  {twoFAEnabled ? <FaLock /> : <FaUnlock />}
                </div>
              </div>
              <div className="mt-4">
                <div className={`text-xl font-bold ${twoFAEnabled ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {twoFAEnabled ? 'Enabled' : 'Not Configured'}
                </div>
                <button
                  type="button"
                  onClick={() => setActiveTab('2fa')}
                  className="mt-2 text-xs text-brand-400 hover:text-brand-300 font-medium inline-flex items-center gap-1"
                >
                  <span>{twoFAEnabled ? 'Manage 2FA settings' : 'Enable 2FA now'}</span>
                  <FaArrowRight className="text-[10px]" />
                </button>
              </div>
            </div>

            <div className="glassmorphism rounded-2xl p-5 border border-white/10 flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-white/50 uppercase tracking-wider">IP Whitelist</span>
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                  overview?.ip_whitelist_active ? 'bg-blue-500/15 text-blue-400' : 'bg-white/10 text-white/50'
                }`}>
                  <FaNetworkWired />
                </div>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold text-white">
                  {overview?.ip_whitelist_active ? `${overview.ip_whitelist_count || whitelist.length} Active Rules` : 'Open Access'}
                </div>
                <div className="text-xs text-white/45 mt-1">
                  {overview?.ip_whitelist_active ? 'Restricted to whitelisted IPs' : 'All network IPs permitted'}
                </div>
              </div>
            </div>

            <div className="glassmorphism rounded-2xl p-5 border border-white/10 flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-white/50 uppercase tracking-wider">Active API Keys</span>
                <div className="w-9 h-9 rounded-xl bg-purple-500/15 text-purple-400 flex items-center justify-center">
                  <FaKey />
                </div>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold text-white tabular-nums">
                  {overview?.active_api_keys ?? 0}
                </div>
                <div className="text-xs text-white/45 mt-1">
                  Programmatic access tokens
                </div>
              </div>
            </div>

            <div className="glassmorphism rounded-2xl p-5 border border-white/10 flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-white/50 uppercase tracking-wider">Failed Logins (24h)</span>
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                  (overview?.recent_failed_logins || 0) > 5
                    ? 'bg-red-500/15 text-red-400'
                    : 'bg-emerald-500/15 text-emerald-400'
                }`}>
                  <FaExclamationTriangle />
                </div>
              </div>
              <div className="mt-4">
                <div className={`text-xl font-bold tabular-nums ${
                  (overview?.recent_failed_logins || 0) > 5 ? 'text-red-400' : 'text-emerald-400'
                }`}>
                  {overview?.recent_failed_logins ?? 0}
                </div>
                <div className="text-xs text-white/45 mt-1">
                  {(overview?.recent_failed_logins || 0) === 0 ? 'No suspicious attempts' : 'Blocked authentication attempts'}
                </div>
              </div>
            </div>
          </div>

          {/* Security Checklist & Current Session */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 glassmorphism rounded-2xl p-5 border border-white/10 space-y-4">
              <h3 className="text-sm font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                <FaUserShield className="text-brand-400" />
                Security Hardening Checklist
              </h3>

              <div className="space-y-2.5">
                <div className="flex items-center justify-between p-3.5 rounded-xl bg-white/[0.03] border border-white/10">
                  <div className="flex items-center gap-3">
                    {twoFAEnabled ? (
                      <FaCheckCircle className="text-emerald-400 text-lg flex-shrink-0" />
                    ) : (
                      <FaTimesCircle className="text-amber-400 text-lg flex-shrink-0" />
                    )}
                    <div>
                      <div className="text-sm font-medium text-white">Authenticator Two-Factor Authentication (TOTP)</div>
                      <div className="text-xs text-white/50">Protects your account even if your password is compromised</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveTab('2fa')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap ${
                      twoFAEnabled
                        ? 'bg-white/10 text-white/75 hover:text-white'
                        : 'bg-brand-500 hover:bg-brand-400 text-white'
                    }`}
                  >
                    {twoFAEnabled ? 'Configured' : 'Setup 2FA'}
                  </button>
                </div>

                {isAdmin && (
                  <div className="flex items-center justify-between p-3.5 rounded-xl bg-white/[0.03] border border-white/10">
                    <div className="flex items-center gap-3">
                      {overview?.ip_whitelist_active ? (
                        <FaCheckCircle className="text-emerald-400 text-lg flex-shrink-0" />
                      ) : (
                        <FaGlobe className="text-blue-400 text-lg flex-shrink-0" />
                      )}
                      <div>
                        <div className="text-sm font-medium text-white">Network IP Access Control</div>
                        <div className="text-xs text-white/50">
                          {overview?.ip_whitelist_active
                            ? `${overview.ip_whitelist_count || whitelist.length} allowed IP/CIDR ranges enforced`
                            : 'Optional: Restrict panel access to trusted LAN/VPN subnets'}
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setActiveTab('ip-whitelist')}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white/10 hover:bg-white/15 text-white whitespace-nowrap"
                    >
                      Configure IPs
                    </button>
                  </div>
                )}

                <div className="flex items-center justify-between p-3.5 rounded-xl bg-white/[0.03] border border-white/10">
                  <div className="flex items-center gap-3">
                    <FaCheckCircle className="text-emerald-400 text-lg flex-shrink-0" />
                    <div>
                      <div className="text-sm font-medium text-white">Isolated Docker Runtime & Path Sanitization</div>
                      <div className="text-xs text-white/50">Unix socket isolation and path-traversal guards active</div>
                    </div>
                  </div>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-emerald-500/15 text-emerald-300">
                    Active
                  </span>
                </div>
              </div>
            </div>

            {/* Session Info Card */}
            <div className="glassmorphism rounded-2xl p-5 border border-white/10 flex flex-col justify-between space-y-4">
              <div>
                <h3 className="text-sm font-semibold text-white uppercase tracking-wider flex items-center gap-2 mb-4">
                  <FaGlobe className="text-cyan-400" />
                  Current Session
                </h3>
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between items-center py-2 border-b border-white/10">
                    <span className="text-white/50">Your IP Address</span>
                    <span className="font-mono text-xs px-2.5 py-1 rounded bg-white/10 text-white">
                      {overview?.your_ip || 'Detected on request'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-white/10">
                    <span className="text-white/50">Authentication</span>
                    <span className="text-emerald-300 text-xs font-medium">JWT Bearer Token</span>
                  </div>
                  <div className="flex justify-between items-center py-2">
                    <span className="text-white/50">2FA Status</span>
                    <span className={twoFAEnabled ? 'text-emerald-300 text-xs font-medium' : 'text-amber-300 text-xs font-medium'}>
                      {twoFAEnabled ? 'Verified / Active' : 'Standard Password'}
                    </span>
                  </div>
                </div>
              </div>

              {isAdmin && (
                <button
                  type="button"
                  onClick={() => setActiveTab('audit')}
                  className="w-full py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-medium text-white flex items-center justify-center gap-2 transition-colors"
                >
                  <FaListAlt />
                  <span>View Full Security Audit Log</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======================== 2FA TAB ======================== */}
      {activeTab === '2fa' && (
        <div className="glassmorphism rounded-2xl p-6 border border-white/10 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-white/10">
            <div className="flex items-start gap-3.5">
              <div className={`w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0 ${
                twoFAEnabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-brand-500/20 text-brand-400'
              }`}>
                <FaQrcode className="text-xl" />
              </div>
              <div>
                <div className="flex items-center gap-2.5">
                  <h3 className="text-lg font-bold text-white">Two-Factor Authentication (TOTP)</h3>
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    twoFAEnabled
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  }`}>
                    {twoFAEnabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                <p className="text-xs sm:text-sm text-white/55 mt-1">
                  Use Google Authenticator, Authy, 1Password, or Bitwarden to generate 6-digit verification codes.
                </p>
              </div>
            </div>

            {!twoFAEnabled && !twoFASetup && (
              <button
                onClick={handleSetup2FA}
                disabled={loading}
                className="px-5 py-2.5 bg-brand-500 hover:bg-brand-400 text-white rounded-xl font-semibold text-sm flex items-center gap-2 shadow-lg shadow-brand-500/25 transition-all"
              >
                <FaKey />
                <span>Begin 2FA Setup</span>
              </button>
            )}
          </div>

          {!twoFAEnabled ? (
            <div>
              {twoFASetup ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Step 1: QR & Secret */}
                  <div className="rounded-2xl bg-white/[0.03] border border-white/10 p-5 space-y-4">
                    <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-brand-300">
                      <span className="w-5 h-5 rounded-full bg-brand-500 text-white flex items-center justify-center text-[10px]">1</span>
                      <span>Scan QR Code in Authenticator App</span>
                    </div>

                    {twoFASetup.qr_code && (
                      <div className="flex justify-center py-2">
                        <img
                          src={twoFASetup.qr_code}
                          alt="2FA QR Code"
                          className="w-48 h-48 rounded-2xl border-4 border-white bg-white p-2 shadow-xl"
                        />
                      </div>
                    )}

                    <div>
                      <div className="text-xs text-white/50 mb-1.5">Or enter this setup key manually:</div>
                      <div className="flex items-center gap-2">
                        <code className="flex-1 px-3.5 py-2 bg-black/40 border border-white/10 rounded-xl text-xs font-mono text-brand-300 select-all break-all">
                          {twoFASetup.secret}
                        </code>
                        <button
                          type="button"
                          onClick={copySecretKey}
                          className="px-3 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs text-white flex items-center gap-1.5"
                        >
                          {copiedSecret ? <FaCheck className="text-emerald-400" /> : <FaCopy />}
                          <span>{copiedSecret ? 'Copied' : 'Copy'}</span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Step 2: Verify Code & Backup Codes */}
                  <div className="space-y-4">
                    <div className="rounded-2xl bg-white/[0.03] border border-white/10 p-5 space-y-4">
                      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-brand-300">
                        <span className="w-5 h-5 rounded-full bg-brand-500 text-white flex items-center justify-center text-[10px]">2</span>
                        <span>Confirm 6-Digit Code</span>
                      </div>
                      <p className="text-xs text-white/55">
                        Enter the 6-digit code shown in your authenticator app to activate 2FA:
                      </p>
                      <div className="flex gap-2.5">
                        <input
                          type="text"
                          maxLength={6}
                          value={verifyCode}
                          onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ''))}
                          placeholder="000000"
                          className="w-40 px-4 py-2.5 bg-black/40 border border-white/15 rounded-xl text-white text-center text-lg font-mono tracking-widest focus:outline-none focus:border-brand-500"
                        />
                        <button
                          onClick={handleVerify2FA}
                          disabled={loading || verifyCode.length < 6}
                          className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl text-sm font-semibold transition-colors"
                        >
                          Verify & Activate
                        </button>
                      </div>
                    </div>

                    {backupCodes && (
                      <div className="p-5 bg-amber-500/10 border border-amber-500/30 rounded-2xl space-y-3">
                        <div className="flex items-center justify-between">
                          <h4 className="text-xs font-bold uppercase tracking-wider text-amber-300 flex items-center gap-2">
                            <FaExclamationTriangle /> Emergency Backup Codes
                          </h4>
                          <button
                            onClick={copyBackupCodes}
                            className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-amber-500/20 text-amber-200 hover:bg-amber-500/30"
                          >
                            {copiedCode ? <FaCheck /> : <FaCopy />}
                            {copiedCode ? 'Copied!' : 'Copy All'}
                          </button>
                        </div>
                        <p className="text-xs text-white/60">
                          Store these single-use recovery codes in a safe place in case you lose your phone:
                        </p>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                          {backupCodes.map((code, i) => (
                            <code key={i} className="px-2.5 py-1.5 bg-black/40 rounded-lg text-center font-mono text-xs text-white">
                              {code}
                            </code>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="rounded-2xl bg-white/[0.02] border border-white/10 p-8 text-center space-y-3">
                  <FaShieldAlt className="text-3xl text-brand-400 mx-auto" />
                  <div className="text-base font-semibold text-white">Protect your admin account with 2FA</div>
                  <p className="text-xs text-white/50 max-w-md mx-auto">
                    Click &ldquo;Begin 2FA Setup&rdquo; above to generate a QR code and recovery keys for your authenticator app.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {/* Regenerate Backup Codes */}
              <div className="rounded-2xl bg-white/[0.03] border border-white/10 p-5 space-y-3">
                <h4 className="text-sm font-semibold text-white">Regenerate Backup Codes</h4>
                <p className="text-xs text-white/50">
                  Enter your current 6-digit 2FA code to invalidate old recovery codes and generate a fresh set.
                </p>
                <div className="flex gap-2.5">
                  <input
                    type="text"
                    maxLength={6}
                    value={regenCode}
                    onChange={(e) => setRegenCode(e.target.value.replace(/\D/g, ''))}
                    placeholder="2FA Code"
                    className="w-36 px-3.5 py-2 bg-black/40 border border-white/15 rounded-xl text-white text-center font-mono text-sm"
                  />
                  <button
                    onClick={handleRegenBackupCodes}
                    disabled={loading || !regenCode}
                    className="px-4 py-2 bg-brand-500 hover:bg-brand-400 disabled:opacity-50 text-white rounded-xl text-xs font-semibold"
                  >
                    Regenerate Codes
                  </button>
                </div>
              </div>

              {/* Disable 2FA */}
              <div className="rounded-2xl bg-red-500/[0.05] border border-red-500/20 p-5 space-y-3">
                <h4 className="text-sm font-semibold text-red-300">Disable Two-Factor Authentication</h4>
                <p className="text-xs text-white/50">
                  Enter a valid 2FA code or backup recovery code to turn off two-factor authentication.
                </p>
                <div className="flex gap-2.5">
                  <input
                    type="text"
                    value={disableCode}
                    onChange={(e) => setDisableCode(e.target.value)}
                    placeholder="2FA or backup code"
                    className="w-44 px-3.5 py-2 bg-black/40 border border-white/15 rounded-xl text-white text-center font-mono text-sm"
                  />
                  <button
                    onClick={handleDisable2FA}
                    disabled={loading || !disableCode}
                    className="px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold"
                  >
                    Disable 2FA
                  </button>
                </div>
              </div>

              {backupCodes && (
                <div className="md:col-span-2 p-5 bg-amber-500/10 border border-amber-500/30 rounded-2xl space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-amber-300">New Backup Codes</h4>
                    <button
                      onClick={copyBackupCodes}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-amber-500/20 text-amber-200"
                    >
                      {copiedCode ? <FaCheck /> : <FaCopy />}
                      {copiedCode ? 'Copied!' : 'Copy All'}
                    </button>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {backupCodes.map((code, i) => (
                      <code key={i} className="px-2.5 py-1.5 bg-black/40 rounded-lg text-center font-mono text-xs text-white">
                        {code}
                      </code>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ======================== IP WHITELIST TAB ======================== */}
      {activeTab === 'ip-whitelist' && isAdmin && (
        <div className="space-y-4">
          <div className="glassmorphism rounded-2xl p-6 border border-white/10 space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-bold text-white">Network IP Access Control</h3>
                <p className="text-xs sm:text-sm text-white/55">
                  When at least one rule is active, only listed IP addresses or CIDR subnets can access the panel.
                </p>
              </div>
              {overview?.your_ip && (
                <button
                  type="button"
                  onClick={() => handleAddIP(overview.your_ip, 'My Admin Workstation')}
                  disabled={loading || whitelist.some(w => w.ip_address === overview.your_ip)}
                  className="px-3.5 py-2 rounded-xl bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/30 text-brand-300 text-xs font-semibold flex items-center gap-2 disabled:opacity-40 whitespace-nowrap self-start sm:self-auto"
                >
                  <FaPlus className="text-[10px]" />
                  <span>Whitelist My IP ({overview.your_ip})</span>
                </button>
              )}
            </div>

            {/* Add IP Form */}
            <div className="flex flex-col sm:flex-row gap-2.5 p-4 rounded-xl bg-white/[0.03] border border-white/10">
              <input
                type="text"
                value={newIP}
                onChange={(e) => setNewIP(e.target.value)}
                placeholder="IP or CIDR (e.g. 192.168.2.0/24)"
                className="flex-1 px-3.5 py-2 bg-black/40 border border-white/10 rounded-xl text-white text-sm font-mono focus:outline-none focus:border-brand-500"
              />
              <input
                type="text"
                value={newIPDesc}
                onChange={(e) => setNewIPDesc(e.target.value)}
                placeholder="Label (e.g. Home LAN / VPN)"
                className="flex-1 px-3.5 py-2 bg-black/40 border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-brand-500"
              />
              <button
                onClick={() => handleAddIP()}
                disabled={loading || !newIP.trim()}
                className="px-5 py-2 bg-brand-500 hover:bg-brand-400 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 whitespace-nowrap"
              >
                <FaPlus /> Add Rule
              </button>
            </div>

            {/* Whitelist Entries */}
            {whitelist.length === 0 ? (
              <div className="text-center py-10 text-white/40 text-sm border border-dashed border-white/10 rounded-xl">
                No IP restrictions configured — all network addresses are currently allowed.
              </div>
            ) : (
              <div className="space-y-2">
                {whitelist.map((entry) => (
                  <div
                    key={entry.id}
                    className="flex items-center justify-between p-3.5 bg-white/[0.03] rounded-xl border border-white/10 hover:border-white/20 transition-colors"
                  >
                    <div className="flex items-center gap-3.5 min-w-0">
                      <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${entry.is_active ? 'bg-emerald-400' : 'bg-white/25'}`} />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <code className="text-white font-mono text-sm font-semibold">{entry.ip_address}</code>
                          {entry.ip_address === overview?.your_ip && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] bg-brand-500/20 text-brand-300">
                              Current IP
                            </span>
                          )}
                        </div>
                        {entry.description && (
                          <div className="text-xs text-white/50 truncate">{entry.description}</div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleToggleIP(entry.id)}
                        className={`px-3 py-1 rounded-lg text-xs font-medium ${
                          entry.is_active
                            ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                            : 'bg-white/5 text-white/45'
                        }`}
                      >
                        {entry.is_active ? 'Active' : 'Disabled'}
                      </button>
                      <button
                        onClick={() => handleRemoveIP(entry.id)}
                        className="p-2 text-red-400 hover:bg-red-500/15 rounded-lg transition-colors"
                        title="Remove IP rule"
                      >
                        <FaTrash className="text-xs" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ======================== AUDIT LOGS TAB ======================== */}
      {activeTab === 'audit' && isAdmin && (
        <div className="glassmorphism rounded-2xl border border-white/10 overflow-hidden">
          <div className="p-4 sm:p-5 border-b border-white/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5 flex-1">
              <div className="relative flex-1 min-w-[200px]">
                <FaSearch className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
                <input
                  type="text"
                  value={auditSearch}
                  onChange={(e) => setAuditSearch(e.target.value)}
                  placeholder="Search events, IPs, or details..."
                  className="w-full pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-white text-xs focus:outline-none focus:border-brand-500"
                />
              </div>
              <select
                value={auditAction}
                onChange={(e) => { setAuditAction(e.target.value); setAuditPage(0); }}
                className="px-3 py-2 bg-[#1c2237] border border-white/10 rounded-xl text-white text-xs"
              >
                <option value="">All Event Types</option>
                {auditActions.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
              <button
                onClick={fetchAuditLogs}
                className="p-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-white/70 hover:text-white"
                title="Refresh logs"
              >
                <FaSyncAlt className="text-xs" />
              </button>
            </div>
            <span className="text-xs text-white/45 tabular-nums">{auditTotal} total events</span>
          </div>

          <div className="divide-y divide-white/10 max-h-[600px] overflow-y-auto">
            {filteredLogs.length === 0 ? (
              <div className="p-12 text-center text-white/40 text-sm">No security audit logs found.</div>
            ) : (
              filteredLogs.map((log) => (
                <div key={log.id} className="p-4 hover:bg-white/[0.03] transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-start gap-3 min-w-0">
                    <span className="px-2.5 py-1 rounded-lg bg-brand-500/15 border border-brand-500/30 text-brand-300 font-mono text-xs flex-shrink-0">
                      {log.action}
                    </span>
                    <div className="min-w-0">
                      <div className="text-xs text-white/60 flex items-center gap-2 flex-wrap">
                        <span>IP: <code className="text-white/80 font-mono">{log.ip_address || '-'}</code></span>
                        {log.details && Object.keys(log.details).length > 0 && (
                          <span className="text-white/45 font-mono truncate max-w-md">
                            {JSON.stringify(log.details)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-white/45 tabular-nums flex-shrink-0">
                    {log.timestamp ? new Date(log.timestamp).toLocaleString() : '-'}
                  </div>
                </div>
              ))
            )}
          </div>

          {auditTotal > 50 && (
            <div className="p-4 border-t border-white/10 flex items-center justify-between">
              <button
                onClick={() => setAuditPage(Math.max(0, auditPage - 1))}
                disabled={auditPage === 0}
                className="px-3 py-1.5 bg-white/5 hover:bg-white/10 disabled:opacity-30 rounded-lg text-xs text-white"
              >
                Previous
              </button>
              <span className="text-xs text-white/50">
                Page {auditPage + 1} of {Math.ceil(auditTotal / 50)}
              </span>
              <button
                onClick={() => setAuditPage(auditPage + 1)}
                disabled={(auditPage + 1) * 50 >= auditTotal}
                className="px-3 py-1.5 bg-white/5 hover:bg-white/10 disabled:opacity-30 rounded-lg text-xs text-white"
              >
                Next
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
