import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FaPlus,
  FaTrash,
  FaCheck,
  FaCopy,
  FaSync,
  FaSearch,
  FaShieldAlt,
} from 'react-icons/fa';
import { API, authHeaders, useAuth } from '../context/AppContext';
import { useTranslation } from '../i18n';
import ConfirmModal from '../components/ConfirmModal';
import {
  ShieldLockIcon,
  NetworkFirewallIcon,
  ApiKeyTokenIcon,
  AuditTrailIcon,
  CloseVectorIcon,
} from '../components/icons/LynxIcons';

export default function SecurityPage() {
  const { t, language } = useTranslation();
  const { currentUser } = useAuth();
  const locale = language === 'de' ? 'de-DE' : 'en-US';
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
  const [copiedSecret, setCopiedSecret] = useState(false);

  const [auditLogs, setAuditLogs] = useState([]);
  const [auditActions, setAuditActions] = useState([]);
  const [auditSearch, setAuditSearch] = useState('');
  const [selectedAction, setSelectedAction] = useState('');

  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  // Confirm modals for destructive actions
  const [confirmState, setConfirmState] = useState({ open: false, type: null, payload: null, busy: false });

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
      setNotice(t('security.notice2faEnabled'));
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
      setNotice(t('security.notice2faDisabled'));
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
      const addedIp = newIp.trim();
      const r = await fetch(`${API}/security/ip-whitelist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          ip_address: addedIp,
          description: newIpDesc.trim() || 'Allowed IP',
          enabled: true,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed to add IP');
      setNewIp('');
      setNewIpDesc('');
      setNotice(t('security.noticeIpAdded', { ip: addedIp }));
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function executeRemoveIp(ipAddress) {
    setError('');
    setConfirmState(prev => ({ ...prev, busy: true }));
    try {
      const r = await fetch(`${API}/security/ip-whitelist/${encodeURIComponent(ipAddress)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to remove IP');
      }
      setNotice(t('security.noticeIpRemoved', { ip: ipAddress }));
      setConfirmState({ open: false, type: null, payload: null, busy: false });
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
      setConfirmState(prev => ({ ...prev, busy: false }));
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
      setCopiedSecret(false);
      setNewKeyName('');
      setNotice(t('security.noticeKeyCreated', { name: d.name }));
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function executeRevokeApiKey(keyId) {
    if (!currentUser?.id) return;
    setError('');
    setConfirmState(prev => ({ ...prev, busy: true }));
    try {
      const r = await fetch(`${API}/users/${currentUser.id}/api-keys/${keyId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) throw new Error('Failed to revoke API key');
      setNotice(t('security.noticeKeyRevoked'));
      setConfirmState({ open: false, type: null, payload: null, busy: false });
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
      setConfirmState(prev => ({ ...prev, busy: false }));
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

  const tabs = [
    { id: 'audit', label: t('security.tabAudit'), count: auditLogs.length, Icon: AuditTrailIcon },
    { id: '2fa', label: t('security.tab2fa'), Icon: ShieldLockIcon },
    { id: 'ip', label: t('security.tabIp'), count: whitelist.length, Icon: NetworkFirewallIcon },
    { id: 'apikeys', label: t('security.tabApiKeys'), count: apiKeys.length, Icon: ApiKeyTokenIcon },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      {/* Lynx Hero Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-6">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-500 to-indigo-600 ring-4 ring-brand-500/20 flex items-center justify-center text-white shadow-lg flex-shrink-0">
            <ShieldLockIcon className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold gradient-text-brand tracking-tight">
              {t('security.title')}
            </h1>
            <p className="text-xs sm:text-sm text-white/60 mt-1">
              {t('security.subtitle')}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          {overview?.current_ip && (
            <span className="glassmorphism inline-flex items-center gap-2 text-xs px-3 py-2 rounded-xl text-white/75 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-400" />
              {t('security.yourIp', { ip: overview.current_ip })}
            </span>
          )}
          <button
            onClick={loadAll}
            disabled={loading}
            className="px-3.5 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-medium text-white/85 inline-flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <FaSync className={`text-[11px] text-brand-400 ${loading ? 'animate-spin' : ''}`} />
            <span>{t('security.refresh')}</span>
          </button>
        </div>
      </div>

      {/* Notices & Errors */}
      {notice && (
        <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/25 px-4 py-3 text-xs text-emerald-300 flex items-center justify-between gap-3">
          <span>{notice}</span>
          <button
            onClick={() => setNotice('')}
            className="p-1 rounded-lg text-emerald-300/70 hover:text-emerald-200 hover:bg-emerald-500/15 transition-colors"
            aria-label={t('common.close')}
          >
            <CloseVectorIcon className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/25 px-4 py-3 text-xs text-red-300 flex items-center justify-between gap-3">
          <span>{error}</span>
          <button
            onClick={() => setError('')}
            className="p-1 rounded-lg text-red-300/70 hover:text-red-200 hover:bg-red-500/15 transition-colors"
            aria-label={t('common.close')}
          >
            <CloseVectorIcon className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* KPI Status Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="glassmorphism rounded-xl p-4 sm:p-5 flex items-center justify-between gap-4 hover:bg-white/[0.07] transition-colors">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className={`w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0 ${
              twoFAStatus.enabled
                ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                : 'bg-brand-500/15 border-brand-500/25 text-brand-400'
            }`}>
              <ShieldLockIcon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-white/55 truncate">{t('security.twoFactorTitle')}</div>
              <div className="text-sm sm:text-base font-semibold text-white mt-0.5 truncate">
                {twoFAStatus.enabled ? t('security.twoFactorEnabledDesc') : t('security.twoFactorDisabledDesc')}
              </div>
            </div>
          </div>
          <span
            className={`text-xs px-2.5 py-1 rounded-lg border font-medium flex-shrink-0 ${
              twoFAStatus.enabled
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                : 'bg-white/5 text-white/60 border-white/10'
            }`}
          >
            {twoFAStatus.enabled ? t('security.statusActive') : t('security.statusOff')}
          </span>
        </div>

        <div className="glassmorphism rounded-xl p-4 sm:p-5 flex items-center justify-between gap-4 hover:bg-white/[0.07] transition-colors">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-brand-500/15 border border-brand-500/25 text-brand-400 flex items-center justify-center flex-shrink-0">
              <NetworkFirewallIcon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-white/55 truncate">{t('security.ipWhitelistTitle')}</div>
              <div className="text-sm sm:text-base font-semibold text-white mt-0.5 truncate">
                {whitelist.length > 0
                  ? t('security.ipRulesCount', { count: whitelist.length })
                  : t('security.allIpsAllowed')}
              </div>
            </div>
          </div>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-white/75 font-mono flex-shrink-0">
            {whitelist.length}
          </span>
        </div>

        <div className="glassmorphism rounded-xl p-4 sm:p-5 flex items-center justify-between gap-4 hover:bg-white/[0.07] transition-colors">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/15 border border-indigo-500/25 text-indigo-400 flex items-center justify-center flex-shrink-0">
              <ApiKeyTokenIcon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-white/55 truncate">{t('security.personalApiKeysTitle')}</div>
              <div className="text-sm sm:text-base font-semibold text-white mt-0.5 truncate">
                {t('security.activeKeysCount', { count: apiKeys.length })}
              </div>
            </div>
          </div>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-white/75 font-mono flex-shrink-0">
            {apiKeys.length}
          </span>
        </div>
      </div>

      {/* Lynx Segmented Pill Tabs */}
      <div className="glassmorphism rounded-xl p-1.5 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
        {tabs.map((tab) => {
          const active = activeTab === tab.id;
          const IconComponent = tab.Icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3.5 py-2 rounded-lg text-xs sm:text-sm font-medium flex items-center gap-2 whitespace-nowrap transition-all ${
                active
                  ? 'bg-brand-500 text-white shadow-sm shadow-brand-500/25'
                  : 'text-white/65 hover:text-white hover:bg-white/10'
              }`}
            >
              <IconComponent className={`w-4 h-4 flex-shrink-0 ${active ? 'text-white' : 'text-brand-400/80'}`} />
              <span>{tab.label}</span>
              {tab.count !== undefined && (
                <span
                  className={`text-[11px] px-1.5 py-0.5 rounded-md font-mono ${
                    active ? 'bg-white/20 text-white' : 'bg-white/5 text-white/65'
                  }`}
                >
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
          <div className="glassmorphism rounded-xl p-3.5 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-md">
              <FaSearch className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40 text-xs" />
              <input
                type="text"
                value={auditSearch}
                onChange={(e) => setAuditSearch(e.target.value)}
                placeholder={t('security.searchAuditPlaceholder')}
                className="w-full pl-9 pr-3 py-2 bg-black/25 border border-white/10 rounded-lg text-xs text-white placeholder-white/40 focus:outline-none focus:border-brand-500 transition-colors"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={selectedAction}
                onChange={(e) => setSelectedAction(e.target.value)}
                className="px-3 py-2 rounded-lg text-xs text-white focus:outline-none focus:border-brand-500"
              >
                <option value="">{t('security.allActions', { count: auditLogs.length })}</option>
                {auditActions.map((act) => (
                  <option key={act} value={act}>
                    {act}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="glassmorphism rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/50 bg-white/[0.03]">
                    <th className="py-3 px-4 font-semibold">{t('security.colTimestamp')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colUser')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colAction')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colResource')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colIp')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colDetails')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-xs">
                  {filteredAuditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-white/[0.04] transition-colors">
                      <td className="py-3 px-4 text-white/60 whitespace-nowrap font-mono">
                        {log.timestamp ? new Date(log.timestamp).toLocaleString(locale) : '—'}
                      </td>
                      <td className="py-3 px-4 text-white font-medium">
                        {log.user || log.username || t('usersPage.systemUser')}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2.5 py-0.5 rounded-md bg-brand-500/10 border border-brand-500/20 font-mono text-brand-300">
                          {log.action}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-white/65 font-mono">
                        {log.resource_type
                          ? `${log.resource_type}${log.resource_id ? `/${log.resource_id}` : ''}`
                          : '—'}
                      </td>
                      <td className="py-3 px-4 text-white/50 font-mono">
                        {log.ip_address || '—'}
                      </td>
                      <td className="py-3 px-4 text-white/50 font-mono max-w-xs truncate">
                        {log.details && Object.keys(log.details).length > 0
                          ? JSON.stringify(log.details)
                          : '—'}
                      </td>
                    </tr>
                  ))}
                  {filteredAuditLogs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-10 text-center text-white/45">
                        {t('security.noAuditMatch')}
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
        <div className="glassmorphism rounded-xl p-6 max-w-2xl space-y-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3.5">
              <div className="w-10 h-10 rounded-xl bg-brand-500/15 border border-brand-500/25 text-brand-400 flex items-center justify-center flex-shrink-0">
                <ShieldLockIcon className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-white">
                  {t('security.authAppTitle')}
                </h3>
                <p className="text-xs text-white/55 mt-1 leading-relaxed">
                  {t('security.authAppDesc')}
                </p>
              </div>
            </div>
            <span
              className={`text-xs px-2.5 py-1 rounded-lg border font-medium flex-shrink-0 ${
                twoFAStatus.enabled
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                  : 'bg-white/5 text-white/55 border-white/10'
              }`}
            >
              {twoFAStatus.enabled ? t('security.enabledBadge') : t('security.disabledBadge')}
            </span>
          </div>

          {!twoFAStatus.enabled && !setupData && (
            <div className="pt-2">
              <button
                onClick={start2FASetup}
                className="px-4 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-2 transition-colors shadow-lg shadow-brand-500/20"
              >
                <FaShieldAlt />
                <span>{t('security.setup2faBtn')}</span>
              </button>
            </div>
          )}

          {setupData && (
            <div className="space-y-4 pt-4 border-t border-white/10">
              <div className="flex flex-col sm:flex-row gap-5 items-start">
                {setupData.qr_code_url && (
                  <div className="bg-white p-2.5 rounded-xl flex-shrink-0 shadow-md">
                    <img
                      src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(
                        setupData.qr_code_url
                      )}`}
                      alt="2FA QR Code"
                      className="w-36 h-36"
                    />
                  </div>
                )}
                <div className="space-y-2.5 text-xs">
                  <div className="text-white font-semibold">{t('security.step1Title')}</div>
                  <p className="text-white/55">
                    {t('security.step1Desc')}
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-brand-300 font-mono select-all">
                      {setupData.secret}
                    </code>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(setupData.secret)}
                      className="px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/75 transition-colors"
                      title={t('security.copyBtn')}
                    >
                      <FaCopy />
                    </button>
                  </div>

                  {Array.isArray(setupData.backup_codes) && setupData.backup_codes.length > 0 && (
                    <div className="pt-2">
                      <div className="text-white/75 font-medium mb-1.5">
                        {t('security.recoveryCodesTitle')}
                      </div>
                      <div className="grid grid-cols-2 gap-1.5 p-3 rounded-xl bg-black/30 border border-white/10 font-mono text-[11px] text-white/80">
                        {setupData.backup_codes.map((c) => (
                          <span key={c}>{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <form onSubmit={confirm2FASetup} className="flex flex-wrap items-end gap-3 pt-2">
                <div>
                  <label className="block text-xs text-white/60 mb-1.5">
                    {t('security.step2Label')}
                  </label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    placeholder="123456"
                    value={verifyCode}
                    onChange={(e) => setVerifyCode(e.target.value)}
                    className="w-40 px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-sm text-white font-mono tracking-widest focus:outline-none focus:border-brand-500"
                  />
                </div>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-1.5 transition-colors"
                >
                  <FaCheck />
                  <span>{t('security.verifyActivateBtn')}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setSetupData(null)}
                  className="px-3.5 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 transition-colors"
                >
                  {t('common.cancel')}
                </button>
              </form>
            </div>
          )}

          {twoFAStatus.enabled && (
            <form onSubmit={handleDisable2FA} className="pt-4 border-t border-white/10 space-y-3">
              <div className="text-xs text-white/60">
                {t('security.disable2faPrompt')}
              </div>
              <div className="flex flex-wrap items-center gap-2.5">
                <input
                  type="password"
                  required
                  placeholder={t('security.currentPasswordPlaceholder')}
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  className="px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-xs text-white focus:outline-none focus:border-brand-500"
                />
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-red-500/15 hover:bg-red-500/25 border border-red-500/30 text-xs text-red-300 font-semibold transition-colors"
                >
                  {t('security.disable2faBtn')}
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
            className="glassmorphism rounded-xl p-4 sm:p-5 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-white/60 mb-1.5">
                {t('security.ipCidrLabel')}
              </label>
              <input
                type="text"
                required
                placeholder={t('security.ipCidrPlaceholder')}
                value={newIp}
                onChange={(e) => setNewIp(e.target.value)}
                className="w-full px-3 py-2 bg-black/25 border border-white/10 rounded-lg text-xs text-white font-mono focus:outline-none focus:border-brand-500"
              />
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-white/60 mb-1.5">{t('security.ipDescLabel')}</label>
              <input
                type="text"
                placeholder={t('security.ipDescPlaceholder')}
                value={newIpDesc}
                onChange={(e) => setNewIpDesc(e.target.value)}
                className="w-full px-3 py-2 bg-black/25 border border-white/10 rounded-lg text-xs text-white focus:outline-none focus:border-brand-500"
              />
            </div>
            {overview?.current_ip && (
              <button
                type="button"
                onClick={() => {
                  setNewIp(overview.current_ip);
                  setNewIpDesc(t('security.currentSessionIp'));
                }}
                className="px-3.5 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 transition-colors"
              >
                {t('security.useMyIpBtn', { ip: overview.current_ip })}
              </button>
            )}
            <button
              type="submit"
              className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-1.5 transition-colors shadow-sm shadow-brand-500/20"
            >
              <FaPlus className="text-[10px]" />
              <span>{t('security.addIpBtn')}</span>
            </button>
          </form>

          <div className="glassmorphism rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/50 bg-white/[0.03]">
                    <th className="py-3 px-4 font-semibold">{t('security.colIpCidr')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colDescription')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colAdded')}</th>
                    <th className="py-3 px-4 font-semibold text-right">{t('common.actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-xs">
                  {whitelist.map((item) => (
                    <tr key={item.ip_address} className="hover:bg-white/[0.04] transition-colors">
                      <td className="py-3 px-4 font-mono text-white font-medium">
                        {item.ip_address}
                      </td>
                      <td className="py-3 px-4 text-white/65">{item.description || '—'}</td>
                      <td className="py-3 px-4 text-white/50 font-mono">
                        {item.added_at ? new Date(item.added_at).toLocaleString(locale) : '—'}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => setConfirmState({ open: true, type: 'removeIp', payload: item.ip_address, busy: false })}
                          className="p-2 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-300 transition-colors"
                          title={t('security.removeIpTitle')}
                        >
                          <FaTrash />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {whitelist.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-10 text-center text-white/45">
                        {t('security.noIpRules')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: API KEYS */}
      {activeTab === 'apikeys' && (
        <div className="space-y-4">
          <form
            onSubmit={handleCreateApiKey}
            className="glassmorphism rounded-xl p-4 sm:p-5 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[240px]">
              <label className="block text-xs text-white/60 mb-1.5">{t('security.keyNameLabel')}</label>
              <input
                type="text"
                required
                placeholder={t('security.keyNamePlaceholder')}
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                className="w-full px-3 py-2 bg-black/25 border border-white/10 rounded-lg text-xs text-white focus:outline-none focus:border-brand-500"
              />
            </div>
            <button
              type="submit"
              className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-1.5 transition-colors shadow-sm shadow-brand-500/20"
            >
              <FaPlus className="text-[10px]" />
              <span>{t('security.generateKeyBtn')}</span>
            </button>
          </form>

          {createdKeySecret && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-2.5 text-xs">
              <div className="font-semibold text-amber-300">
                {t('security.copyKeyWarning')}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <code className="flex-1 min-w-[220px] px-3 py-2 rounded-lg bg-black/50 border border-white/10 text-white font-mono select-all">
                  {createdKeySecret}
                </code>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(createdKeySecret);
                    setCopiedSecret(true);
                  }}
                  className="px-3 py-2 rounded-lg bg-white/10 hover:bg-white/20 text-white inline-flex items-center gap-1.5 transition-colors"
                >
                  <FaCopy />
                  <span>{copiedSecret ? t('security.copiedBtn') : t('security.copyBtn')}</span>
                </button>
                <button
                  onClick={() => setCreatedKeySecret('')}
                  className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/65 transition-colors"
                >
                  {t('security.dismissBtn')}
                </button>
              </div>
            </div>
          )}

          <div className="glassmorphism rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/50 bg-white/[0.03]">
                    <th className="py-3 px-4 font-semibold">{t('security.colKeyName')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colPrefix')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colCreated')}</th>
                    <th className="py-3 px-4 font-semibold">{t('security.colLastUsed')}</th>
                    <th className="py-3 px-4 font-semibold text-right">{t('common.actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-xs">
                  {apiKeys.map((k) => (
                    <tr key={k.id} className="hover:bg-white/[0.04] transition-colors">
                      <td className="py-3 px-4 text-white font-medium">{k.name}</td>
                      <td className="py-3 px-4 font-mono text-white/65">{k.key_prefix}…</td>
                      <td className="py-3 px-4 text-white/50 font-mono">
                        {k.created_at ? new Date(k.created_at).toLocaleDateString(locale) : '—'}
                      </td>
                      <td className="py-3 px-4 text-white/50 font-mono">
                        {k.last_used_at ? new Date(k.last_used_at).toLocaleString(locale) : t('security.never')}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => setConfirmState({ open: true, type: 'revokeKey', payload: k.id, busy: false })}
                          className="p-2 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-300 transition-colors"
                          title={t('security.revokeKeyTitle')}
                        >
                          <FaTrash />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {apiKeys.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-10 text-center text-white/45">
                        {t('security.noApiKeys')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        isOpen={confirmState.open}
        title={confirmState.type === 'removeIp' ? t('security.removeIpTitle') : t('security.revokeKeyTitle')}
        message={
          confirmState.type === 'removeIp'
            ? t('security.confirmRemoveIp', { ip: confirmState.payload || '' })
            : t('security.confirmRevokeKey')
        }
        confirmText={t('common.delete')}
        cancelText={t('common.cancel')}
        confirmVariant="danger"
        isLoading={confirmState.busy}
        onCancel={() => setConfirmState({ open: false, type: null, payload: null, busy: false })}
        onConfirm={() => {
          if (confirmState.type === 'removeIp') executeRemoveIp(confirmState.payload);
          else if (confirmState.type === 'revokeKey') executeRevokeApiKey(confirmState.payload);
        }}
      />
    </div>
  );
}
