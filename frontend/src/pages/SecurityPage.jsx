import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../i18n';
import { API, authHeaders, useAuth } from '../context/AppContext';
import {
  FaShieldAlt, FaKey, FaLock, FaUnlock, FaQrcode, FaCopy,
  FaCheck, FaTimes, FaExclamationTriangle, FaClipboard,
  FaNetworkWired, FaPlus, FaTrash, FaSearch, FaHistory,
  FaUserShield, FaChartPie, FaEye, FaSpinner, FaChevronDown,
  FaChevronUp, FaCheckCircle, FaTimesCircle
} from 'react-icons/fa';

// ─── Shared UI ────────────────────────────────────────────

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

function Card({ title, description, icon: Icon, children, className = '' }) {
  return (
    <div className={`bg-white/5 border border-white/10 rounded-xl p-6 ${className}`}>
      {title && (
        <div className="flex items-start gap-3 mb-5">
          <div className="p-2 bg-brand-500/20 rounded-lg">
            <Icon className="w-5 h-5 text-brand-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">{title}</h3>
            {description && <p className="text-sm text-white/50 mt-0.5">{description}</p>}
          </div>
        </div>
      )}
      {children}
    </div>
  );
}

// ─── 2FA Panel ────────────────────────────────────────────

function TwoFactorPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupData, setSetupData] = useState(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [disablePassword, setDisablePassword] = useState('');
  const [disabling, setDisabling] = useState(false);
  const [showBackup, setShowBackup] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/2fa/status`, { headers: authHeaders() });
      if (r.ok) setStatus(await r.json());
    } catch { }
    setLoading(false);
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const startSetup = async () => {
    setError('');
    setSuccess('');
    try {
      const r = await fetch(`${API}/security/2fa/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
      });
      if (r.ok) {
        setSetupData(await r.json());
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || 'Failed to start 2FA setup');
      }
    } catch {
      setError('Network error');
    }
  };

  const verifySetup = async () => {
    setVerifying(true);
    setError('');
    try {
      const r = await fetch(`${API}/security/2fa/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ code: verifyCode }),
      });
      if (r.ok) {
        setSuccess('2FA enabled successfully!');
        setSetupData(null);
        setVerifyCode('');
        fetchStatus();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || 'Invalid code');
      }
    } catch {
      setError('Network error');
    }
    setVerifying(false);
  };

  const disable2FA = async () => {
    setDisabling(true);
    setError('');
    try {
      const r = await fetch(`${API}/security/2fa/disable?password=${encodeURIComponent(disablePassword)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
      });
      if (r.ok) {
        setSuccess('2FA disabled');
        setDisablePassword('');
        fetchStatus();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || 'Failed to disable 2FA');
      }
    } catch {
      setError('Network error');
    }
    setDisabling(false);
  };

  const copySecret = () => {
    if (setupData?.secret) {
      navigator.clipboard.writeText(setupData.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) return <div className="text-white/50 text-center py-8"><FaSpinner className="animate-spin inline mr-2" />Loading…</div>;

  return (
    <Card title="Two-Factor Authentication" description="Secure your account with TOTP" icon={FaKey}>
      {error && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/40 rounded-lg text-red-300 text-sm flex items-center gap-2">
          <FaTimesCircle /> {error}
        </div>
      )}
      {success && (
        <div className="mb-4 p-3 bg-green-500/20 border border-green-500/40 rounded-lg text-green-300 text-sm flex items-center gap-2">
          <FaCheckCircle /> {success}
        </div>
      )}

      {/* Status Badge */}
      <div className="flex items-center gap-3 mb-6 p-4 bg-white/5 rounded-lg border border-white/10">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center ${status?.enabled ? 'bg-green-500/20' : 'bg-yellow-500/20'}`}>
          {status?.enabled ? <FaLock className="text-green-400" /> : <FaUnlock className="text-yellow-400" />}
        </div>
        <div>
          <div className={`font-semibold ${status?.enabled ? 'text-green-400' : 'text-yellow-400'}`}>
            {status?.enabled ? 'Enabled' : 'Not Enabled'}
          </div>
          {status?.verified_at && (
            <div className="text-xs text-white/40">Verified {new Date(status.verified_at).toLocaleDateString()}</div>
          )}
        </div>
      </div>

      {/* If 2FA is enabled → show disable */}
      {status?.enabled && !setupData && (
        <div className="space-y-3">
          <p className="text-sm text-white/60">Enter your password to disable 2FA.</p>
          <div className="flex gap-2">
            <input
              type="password"
              value={disablePassword}
              onChange={e => setDisablePassword(e.target.value)}
              placeholder="Password"
              className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm"
            />
            <button
              onClick={disable2FA}
              disabled={disabling || !disablePassword}
              className="px-4 py-2 bg-red-500/20 border border-red-500/40 text-red-300 rounded-lg text-sm hover:bg-red-500/30 disabled:opacity-50 flex items-center gap-2"
            >
              {disabling ? <FaSpinner className="animate-spin" /> : <FaUnlock />} Disable
            </button>
          </div>
        </div>
      )}

      {/* If 2FA is NOT enabled and no setup in progress → show setup button */}
      {!status?.enabled && !setupData && (
        <button
          onClick={startSetup}
          className="w-full py-3 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg hover:bg-brand-500/30 flex items-center justify-center gap-2 transition-colors"
        >
          <FaQrcode /> Set Up Two-Factor Authentication
        </button>
      )}

      {/* Setup Wizard */}
      {setupData && (
        <div className="space-y-5">
          {/* Step 1: QR / Secret */}
          <div className="p-4 bg-white/5 rounded-lg border border-white/10">
            <h4 className="text-sm font-semibold text-white mb-3">1. Scan with your authenticator app</h4>
            <div className="flex flex-col items-center gap-4">
              <div className="p-4 bg-white rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(setupData.qr_code_url)}`}
                  alt="2FA QR Code"
                  className="w-48 h-48"
                />
              </div>
              <div className="text-center">
                <p className="text-xs text-white/40 mb-1">Or enter this code manually:</p>
                <div className="flex items-center gap-2 bg-black/30 rounded-lg px-3 py-2">
                  <code className="text-sm text-brand-300 font-mono tracking-wider">{setupData.secret}</code>
                  <button onClick={copySecret} className="text-white/40 hover:text-white transition-colors">
                    {copied ? <FaCheck className="text-green-400" /> : <FaCopy />}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Step 2: Verify */}
          <div className="p-4 bg-white/5 rounded-lg border border-white/10">
            <h4 className="text-sm font-semibold text-white mb-3">2. Enter the 6-digit code from your app</h4>
            <div className="flex gap-2">
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={verifyCode}
                onChange={e => setVerifyCode(e.target.value.replace(/\D/g, ''))}
                placeholder="000000"
                className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-center text-lg tracking-[0.3em] font-mono"
              />
              <button
                onClick={verifySetup}
                disabled={verifying || verifyCode.length !== 6}
                className="px-5 py-2 bg-brand-500 text-white rounded-lg hover:bg-brand-600 disabled:opacity-50 flex items-center gap-2 transition-colors"
              >
                {verifying ? <FaSpinner className="animate-spin" /> : <FaCheck />} Verify
              </button>
            </div>
          </div>

          {/* Backup Codes */}
          <div className="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
            <button
              onClick={() => setShowBackup(!showBackup)}
              className="w-full flex items-center justify-between text-yellow-300 text-sm font-semibold"
            >
              <span className="flex items-center gap-2"><FaExclamationTriangle /> Backup Codes — Save these!</span>
              {showBackup ? <FaChevronUp /> : <FaChevronDown />}
            </button>
            {showBackup && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                {setupData.backup_codes.map((code, i) => (
                  <div key={i} className="bg-black/20 rounded px-3 py-1.5 text-center font-mono text-sm text-yellow-200">{code}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ─── IP Whitelist Panel ────────────────────────────────────

function IPWhitelistPanel() {
  const [whitelist, setWhitelist] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newIP, setNewIP] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [adding, setAdding] = useState(false);
  const [myIP, setMyIP] = useState(null);
  const [error, setError] = useState('');

  const fetchWhitelist = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/ip-whitelist`, { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setWhitelist(d.whitelist || []);
      }
    } catch { }
    setLoading(false);
  }, []);

  const fetchMyIP = useCallback(async () => {
    try {
      const r = await fetch(`${API}/security/ip-whitelist/check`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) {
        const d = await r.json();
        setMyIP(d.ip);
      }
    } catch { }
  }, []);

  useEffect(() => { fetchWhitelist(); fetchMyIP(); }, [fetchWhitelist, fetchMyIP]);

  const addIP = async () => {
    if (!newIP.trim()) return;
    setAdding(true);
    setError('');
    try {
      const r = await fetch(`${API}/security/ip-whitelist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ ip_address: newIP.trim(), description: newDesc.trim() || null }),
      });
      if (r.ok) {
        setNewIP('');
        setNewDesc('');
        fetchWhitelist();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || 'Failed to add IP');
      }
    } catch {
      setError('Network error');
    }
    setAdding(false);
  };

  const removeIP = async (ip) => {
    try {
      await fetch(`${API}/security/ip-whitelist/${encodeURIComponent(ip)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      fetchWhitelist();
    } catch { }
  };

  return (
    <Card title="IP Whitelist" description="Restrict access by IP address" icon={FaNetworkWired}>
      {myIP && (
        <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-300 text-sm">
          Your current IP: <code className="font-mono bg-black/20 px-1.5 py-0.5 rounded">{myIP}</code>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/40 rounded-lg text-red-300 text-sm">{error}</div>
      )}

      {/* Add IP form */}
      <div className="flex gap-2 mb-4">
        <input
          value={newIP}
          onChange={e => setNewIP(e.target.value)}
          placeholder="IP address (e.g. 192.168.1.0/24)"
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm"
        />
        <input
          value={newDesc}
          onChange={e => setNewDesc(e.target.value)}
          placeholder="Description"
          className="w-40 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-white/30 text-sm"
        />
        <button
          onClick={addIP}
          disabled={adding || !newIP.trim()}
          className="px-4 py-2 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg text-sm hover:bg-brand-500/30 disabled:opacity-50 flex items-center gap-2"
        >
          {adding ? <FaSpinner className="animate-spin" /> : <FaPlus />}
        </button>
      </div>

      {/* Whitelist Table */}
      {loading ? (
        <div className="text-white/40 text-center py-4"><FaSpinner className="animate-spin inline mr-2" />Loading…</div>
      ) : whitelist.length === 0 ? (
        <div className="text-white/40 text-center py-6 text-sm">No IP restrictions. All IPs are allowed.</div>
      ) : (
        <div className="space-y-2">
          {whitelist.map((item, i) => (
            <div key={i} className="flex items-center justify-between p-3 bg-white/5 rounded-lg border border-white/10">
              <div>
                <code className="text-sm text-white font-mono">{item.ip_address}</code>
                {item.description && <span className="text-xs text-white/40 ml-2">— {item.description}</span>}
                <div className="text-xs text-white/30 mt-0.5">Added {new Date(item.added_at).toLocaleDateString()}</div>
              </div>
              <button
                onClick={() => removeIP(item.ip_address)}
                className="p-2 text-red-400/60 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
              >
                <FaTrash className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─── Audit Log Panel ───────────────────────────────────────

function AuditLogPanel() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState({ action: '', limit: 50 });
  const [expanded, setExpanded] = useState(null);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const body = { limit: filter.limit };
      if (filter.action) body.action = filter.action;
      const r = await fetch(`${API}/security/audit-logs/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        const d = await r.json();
        setLogs(d.logs || []);
      }
    } catch { }
    setLoading(false);
  }, [filter]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const ACTION_COLORS = {
    login: 'text-green-400',
    failed_login: 'text-red-400',
    enable_2fa: 'text-blue-400',
    disable_2fa: 'text-yellow-400',
    delete_server: 'text-red-400',
    create_server: 'text-green-400',
    update_permissions: 'text-purple-400',
  };

  return (
    <Card title="Audit Logs" description="Track all security events" icon={FaHistory}>
      {/* Filter */}
      <div className="flex gap-2 mb-4">
        <div className="relative flex-1">
          <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            value={filter.action}
            onChange={e => setFilter(prev => ({ ...prev, action: e.target.value }))}
            placeholder="Filter by action (e.g. login, delete_server)"
            className="w-full bg-white/5 border border-white/10 rounded-lg pl-9 pr-3 py-2 text-white placeholder-white/30 text-sm"
          />
        </div>
        <select
          value={filter.limit}
          onChange={e => setFilter(prev => ({ ...prev, limit: parseInt(e.target.value) }))}
          className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
        >
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
        <button
          onClick={fetchLogs}
          className="px-3 py-2 bg-brand-500/20 border border-brand-500/40 text-brand-300 rounded-lg text-sm hover:bg-brand-500/30"
        >
          <FaSearch />
        </button>
      </div>

      {loading ? (
        <div className="text-white/40 text-center py-6"><FaSpinner className="animate-spin inline mr-2" />Loading…</div>
      ) : logs.length === 0 ? (
        <div className="text-white/40 text-center py-6 text-sm">No audit logs found.</div>
      ) : (
        <div className="space-y-1 max-h-[500px] overflow-y-auto pr-1">
          {logs.map(log => (
            <div key={log.id} className="group">
              <button
                onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                className="w-full flex items-center justify-between p-3 bg-white/5 hover:bg-white/8 rounded-lg text-left transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`text-xs font-mono px-2 py-0.5 rounded bg-black/20 ${ACTION_COLORS[log.action] || 'text-white/60'}`}>
                    {log.action}
                  </span>
                  <span className="text-sm text-white/70 truncate">{log.user}</span>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-xs text-white/30">{new Date(log.timestamp).toLocaleString()}</span>
                  {expanded === log.id ? <FaChevronUp className="text-white/30 w-3 h-3" /> : <FaChevronDown className="text-white/30 w-3 h-3" />}
                </div>
              </button>
              {expanded === log.id && (
                <div className="mx-3 mb-2 p-3 bg-black/20 rounded-b-lg border-x border-b border-white/5 text-xs text-white/50 space-y-1">
                  {log.resource_type && <div>Resource: <span className="text-white/70">{log.resource_type}{log.resource_id ? ` / ${log.resource_id}` : ''}</span></div>}
                  {log.ip_address && <div>IP: <span className="text-white/70 font-mono">{log.ip_address}</span></div>}
                  {log.details && <div>Details: <code className="text-white/70">{JSON.stringify(log.details)}</code></div>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─── Security Dashboard Panel ─────────────────────────────

function SecurityDashboardPanel() {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/security/dashboard`, { headers: authHeaders() });
        if (r.ok) setDashboard(await r.json());
      } catch { }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-white/40 text-center py-8"><FaSpinner className="animate-spin inline mr-2" />Loading…</div>;
  if (!dashboard) return <div className="text-white/40 text-center py-8">Failed to load security dashboard.</div>;

  return (
    <div className="space-y-6">
      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Users', value: dashboard.users.total, color: 'text-blue-400', icon: FaUserShield },
          { label: 'Active Users', value: dashboard.users.active, color: 'text-green-400', icon: FaCheckCircle },
          { label: '2FA Adoption', value: `${dashboard.users['2fa_percentage']}%`, color: 'text-purple-400', icon: FaLock },
          { label: 'Active API Keys', value: dashboard.api_keys.active, color: 'text-yellow-400', icon: FaKey },
        ].map((stat, i) => (
          <div key={i} className="bg-white/5 border border-white/10 rounded-xl p-4 text-center">
            <stat.icon className={`w-6 h-6 ${stat.color} mx-auto mb-2`} />
            <div className={`text-2xl font-bold ${stat.color}`}>{stat.value}</div>
            <div className="text-xs text-white/40 mt-1">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Failed Logins */}
      {dashboard.failed_logins.length > 0 && (
        <Card title="Failed Login Attempts" icon={FaExclamationTriangle}>
          <div className="space-y-2">
            {dashboard.failed_logins.map((item, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-red-500/10 rounded-lg border border-red-500/20">
                <span className="text-sm text-white">{item.username}</span>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-red-300">{item.attempts} attempts</span>
                  {item.locked_until && (
                    <span className="text-xs text-yellow-400 bg-yellow-500/10 px-2 py-0.5 rounded">
                      Locked until {new Date(item.locked_until).toLocaleString()}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Recent Events */}
      <Card title="Recent Security Events" icon={FaHistory}>
        {dashboard.recent_events.length === 0 ? (
          <div className="text-white/40 text-center py-4 text-sm">No recent events.</div>
        ) : (
          <div className="space-y-2">
            {dashboard.recent_events.map((evt, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-white/5 rounded-lg">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-black/20 text-white/60">{evt.action}</span>
                  <span className="text-sm text-white/70">{evt.user}</span>
                </div>
                <div className="text-xs text-white/30 flex items-center gap-2">
                  {evt.ip && <code className="font-mono">{evt.ip}</code>}
                  <span>{new Date(evt.timestamp).toLocaleString()}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ─── Main Security Page ────────────────────────────────────

export default function SecurityPage() {
  const { isAdmin } = useAuth();
  const [tab, setTab] = useState('2fa');

  const tabs = [
    { id: '2fa', label: 'Two-Factor Auth', icon: FaKey },
    ...(isAdmin ? [
      { id: 'dashboard', label: 'Overview', icon: FaChartPie },
      { id: 'whitelist', label: 'IP Whitelist', icon: FaNetworkWired },
      { id: 'audit', label: 'Audit Logs', icon: FaHistory },
    ] : []),
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="p-2 bg-brand-500/20 rounded-lg">
          <FaShieldAlt className="w-6 h-6 text-brand-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Security</h1>
          <p className="text-sm text-white/50">Manage authentication, access control & audit</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10 overflow-x-auto">
        {tabs.map(t => (
          <Tab key={t.id} active={tab === t.id} onClick={() => setTab(t.id)} icon={t.icon} label={t.label} />
        ))}
      </div>

      {/* Content */}
      <div className="pb-8">
        {tab === '2fa' && <TwoFactorPanel />}
        {tab === 'dashboard' && <SecurityDashboardPanel />}
        {tab === 'whitelist' && <IPWhitelistPanel />}
        {tab === 'audit' && <AuditLogPanel />}
      </div>
    </div>
  );
}
