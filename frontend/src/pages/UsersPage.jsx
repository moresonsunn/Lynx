import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  FaPlus,
  FaSearch,
  FaEdit,
  FaTrash,
  FaKey,
  FaLock,
  FaUnlock,
  FaCheck,
  FaSync,
} from 'react-icons/fa';
import { API, authHeaders } from '../context/AppContext';
import { useTranslation } from '../i18n';
import ConfirmModal from '../components/ConfirmModal';
import {
  UsersBadgeIcon,
  RoleMatrixIcon,
  AuditTrailIcon,
  CloseVectorIcon,
} from '../components/icons/LynxIcons';

const ROLE_BADGE_STYLES = {
  owner: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  admin: 'bg-red-500/15 text-red-300 border-red-500/30',
  moderator: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  helper: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  user: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  guest: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
};

export default function UsersPage({ currentUser }) {
  const { t, language } = useTranslation();
  const locale = language === 'de' ? 'de-DE' : 'en-US';
  const [activeTab, setActiveTab] = useState('users'); // 'users' | 'roles' | 'audit'

  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [permissions, setPermissions] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Filters
  const [userSearch, setUserSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [auditSearch, setAuditSearch] = useState('');

  // Selected role in Roles & Permissions tab
  const [selectedRoleName, setSelectedRoleName] = useState('owner');
  const [editingRolePerms, setEditingRolePerms] = useState([]);
  const [editingRoleDesc, setEditingRoleDesc] = useState('');
  const [savingRole, setSavingRole] = useState(false);

  // Modals
  const [showUserModal, setShowUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [userForm, setUserForm] = useState({
    username: '',
    email: '',
    full_name: '',
    password: '',
    role: 'user',
    is_active: true,
  });

  const [showCreateRoleModal, setShowCreateRoleModal] = useState(false);
  const [newRoleForm, setNewRoleForm] = useState({
    name: '',
    description: '',
    permissions: [],
  });

  const [resetPasswordUser, setResetPasswordUser] = useState(null);
  const [newPasswordValue, setNewPasswordValue] = useState('');

  const [confirmState, setConfirmState] = useState({ open: false, type: null, target: null, busy: false });

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const headers = authHeaders();
      const [uRes, rRes, pRes, aRes] = await Promise.all([
        fetch(`${API}/users?include_inactive=true&page_size=100`, { headers }),
        fetch(`${API}/users/roles`, { headers }),
        fetch(`${API}/users/permissions`, { headers }),
        fetch(`${API}/users/audit-logs?page_size=100`, { headers }),
      ]);

      if (uRes.ok) {
        const uData = await uRes.json();
        setUsers(Array.isArray(uData) ? uData : uData.users || []);
      }
      if (rRes.ok) {
        const rData = await rRes.json();
        const rList = Array.isArray(rData) ? rData : rData.roles || [];
        setRoles(rList);
        if (rList.length > 0 && !rList.some((r) => r.name === selectedRoleName)) {
          setSelectedRoleName(rList[0].name);
        }
      }
      if (pRes.ok) {
        const pData = await pRes.json();
        setPermissions(Array.isArray(pData) ? pData : pData.permissions || []);
      }
      if (aRes.ok) {
        const aData = await aRes.json();
        setAuditLogs(Array.isArray(aData) ? aData : aData.logs || []);
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [selectedRoleName]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const selectedRole = useMemo(
    () => roles.find((r) => r.name === selectedRoleName) || roles[0] || null,
    [roles, selectedRoleName]
  );

  useEffect(() => {
    if (selectedRole) {
      setEditingRolePerms(Array.isArray(selectedRole.permissions) ? [...selectedRole.permissions] : []);
      setEditingRoleDesc(selectedRole.description || '');
    }
  }, [selectedRole]);

  const groupedPermissions = useMemo(() => {
    const groups = {};
    for (const perm of permissions) {
      const cat = perm.category || perm.name.split('.')[0] || 'general';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(perm);
    }
    return groups;
  }, [permissions]);

  const filteredUsers = useMemo(() => {
    return users.filter((u) => {
      if (roleFilter !== 'all' && u.role !== roleFilter) return false;
      if (userSearch.trim()) {
        const q = userSearch.toLowerCase();
        return (
          (u.username || '').toLowerCase().includes(q) ||
          (u.email || '').toLowerCase().includes(q) ||
          (u.full_name || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [users, roleFilter, userSearch]);

  const filteredAuditLogs = useMemo(() => {
    if (!auditSearch.trim()) return auditLogs;
    const q = auditSearch.toLowerCase();
    return auditLogs.filter(
      (log) =>
        (log.action || '').toLowerCase().includes(q) ||
        (log.username || '').toLowerCase().includes(q) ||
        (log.resource_type || '').toLowerCase().includes(q) ||
        (log.ip_address || '').toLowerCase().includes(q)
    );
  }, [auditLogs, auditSearch]);

  const activeUsersCount = useMemo(
    () => users.filter((u) => u.is_active !== false).length,
    [users]
  );

  function getCategoryLabel(category) {
    const key = `usersPage.categories.${category}`;
    const translated = t(key);
    return translated && translated !== key ? translated : category;
  }

  function openCreateUser() {
    setEditingUser(null);
    setUserForm({
      username: '',
      email: '',
      full_name: '',
      password: '',
      role: 'user',
      is_active: true,
    });
    setShowUserModal(true);
  }

  function openEditUser(u) {
    setEditingUser(u);
    setUserForm({
      username: u.username || '',
      email: u.email || '',
      full_name: u.full_name || '',
      password: '',
      role: u.role || 'user',
      is_active: u.is_active !== false,
    });
    setShowUserModal(true);
  }

  async function saveUser(e) {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const url = editingUser ? `${API}/users/${editingUser.id}` : `${API}/users`;
      const method = editingUser ? 'PUT' : 'POST';
      const payload = editingUser
        ? {
            email: userForm.email,
            full_name: userForm.full_name || null,
            role: userForm.role,
            is_active: userForm.is_active,
            ...(userForm.password ? { password: userForm.password } : {}),
          }
        : {
            username: userForm.username,
            email: userForm.email,
            full_name: userForm.full_name || null,
            password: userForm.password,
            role: userForm.role,
          };

      const r = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Failed (HTTP ${r.status})`);
      }
      setShowUserModal(false);
      setNotice(
        editingUser
          ? t('usersPage.noticeUserUpdated', { username: editingUser.username })
          : t('usersPage.noticeUserCreated', { username: userForm.username })
      );
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function handleQuickRoleChange(user, newRole) {
    setError('');
    try {
      const r = await fetch(`${API}/users/${user.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ role: newRole }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to update role');
      }
      setNotice(t('usersPage.noticeRoleChanged', { username: user.username, role: newRole }));
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function executeDeleteUser(user) {
    if (!user) return;
    setError('');
    setConfirmState((prev) => ({ ...prev, busy: true }));
    try {
      const r = await fetch(`${API}/users/${user.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to delete user');
      }
      setNotice(t('usersPage.noticeUserDeactivated', { username: user.username }));
      setConfirmState({ open: false, type: null, target: null, busy: false });
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
      setConfirmState((prev) => ({ ...prev, busy: false }));
    }
  }

  async function handleUnlockUser(user) {
    try {
      const r = await fetch(`${API}/users/${user.id}/unlock`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) {
        setNotice(t('usersPage.noticeUserUnlocked', { username: user.username }));
        await loadAll();
      }
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function handleAdminResetPassword(e) {
    e.preventDefault();
    if (!resetPasswordUser || !newPasswordValue) return;
    setError('');
    try {
      const r = await fetch(`${API}/users/${resetPasswordUser.id}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ new_password: newPasswordValue, force_change: false }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Password reset failed');
      }
      setNotice(t('usersPage.noticePasswordUpdated', { username: resetPasswordUser.username }));
      setResetPasswordUser(null);
      setNewPasswordValue('');
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  function toggleRolePermission(permName) {
    if (!selectedRole || selectedRole.is_system) return;
    setEditingRolePerms((prev) =>
      prev.includes(permName) ? prev.filter((p) => p !== permName) : [...prev, permName]
    );
  }

  function toggleCategoryPermissions(catPerms) {
    if (!selectedRole || selectedRole.is_system) return;
    const names = catPerms.map((p) => p.name);
    const allSelected = names.every((n) => editingRolePerms.includes(n));
    if (allSelected) {
      setEditingRolePerms((prev) => prev.filter((p) => !names.includes(p)));
    } else {
      setEditingRolePerms((prev) => Array.from(new Set([...prev, ...names])));
    }
  }

  async function saveRoleChanges() {
    if (!selectedRole || selectedRole.is_system) return;
    setSavingRole(true);
    setError('');
    try {
      const r = await fetch(`${API}/users/roles/${encodeURIComponent(selectedRole.name)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          description: editingRoleDesc,
          permissions: editingRolePerms,
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to update role');
      }
      setNotice(t('usersPage.noticeRoleSaved', { name: selectedRole.name }));
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSavingRole(false);
    }
  }

  async function handleCreateRole(e) {
    e.preventDefault();
    if (!newRoleForm.name.trim()) return;
    setError('');
    try {
      const r = await fetch(`${API}/users/roles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(newRoleForm),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to create role');
      }
      const createdName = newRoleForm.name.trim().toLowerCase().replace(/\s+/g, '_');
      setShowCreateRoleModal(false);
      setNewRoleForm({ name: '', description: '', permissions: [] });
      setNotice(t('usersPage.noticeRoleCreated', { name: createdName }));
      await loadAll();
      setSelectedRoleName(createdName);
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function executeDeleteRole(role) {
    if (!role || role.is_system) return;
    setError('');
    setConfirmState((prev) => ({ ...prev, busy: true }));
    try {
      const r = await fetch(`${API}/users/roles/${encodeURIComponent(role.name)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Failed to delete role');
      }
      setNotice(t('usersPage.noticeRoleDeleted', { name: role.name }));
      setSelectedRoleName('owner');
      setConfirmState({ open: false, type: null, target: null, busy: false });
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
      setConfirmState((prev) => ({ ...prev, busy: false }));
    }
  }

  const tabs = [
    { id: 'users', label: t('usersPage.tabUsers'), count: users.length, Icon: UsersBadgeIcon },
    { id: 'roles', label: t('usersPage.tabRoles'), count: roles.length, Icon: RoleMatrixIcon },
    { id: 'audit', label: t('usersPage.tabAudit'), count: auditLogs.length, Icon: AuditTrailIcon },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      {/* Lynx Hero Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-6">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-500 to-indigo-600 ring-4 ring-brand-500/20 flex items-center justify-center text-white shadow-lg flex-shrink-0">
            <UsersBadgeIcon className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold gradient-text-brand tracking-tight">
              {t('nav.users')}
            </h1>
            <p className="text-xs sm:text-sm text-white/60 mt-1">
              {t('usersPage.subtitle', { roles: roles.length, permissions: permissions.length })}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            onClick={loadAll}
            disabled={loading}
            className="px-3.5 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-medium text-white/85 inline-flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <FaSync className={`text-[11px] text-brand-400 ${loading ? 'animate-spin' : ''}`} />
            <span>{t('common.refresh')}</span>
          </button>
          {activeTab === 'roles' ? (
            <button
              onClick={() => setShowCreateRoleModal(true)}
              className="px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-2 transition-colors shadow-lg shadow-brand-500/20"
            >
              <FaPlus className="text-[11px]" />
              <span>{t('usersPage.newCustomRole')}</span>
            </button>
          ) : (
            <button
              onClick={openCreateUser}
              className="px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-2 transition-colors shadow-lg shadow-brand-500/20"
            >
              <FaPlus className="text-[11px]" />
              <span>{t('usersPage.addUser')}</span>
            </button>
          )}
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

      {/* Glassmorphic Overview KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="glassmorphism rounded-xl p-4 sm:p-5 flex items-center justify-between gap-4 hover:bg-white/[0.07] transition-colors">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-brand-500/15 border border-brand-500/25 text-brand-400 flex items-center justify-center flex-shrink-0">
              <UsersBadgeIcon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-white/55 truncate">{t('usersPage.kpiUsersTitle')}</div>
              <div className="text-xl font-semibold text-white mt-0.5">{users.length}</div>
            </div>
          </div>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 border border-emerald-500/25 text-emerald-300 font-medium flex-shrink-0">
            {t('usersPage.kpiActiveSub', { active: activeUsersCount })}
          </span>
        </div>

        <div className="glassmorphism rounded-xl p-4 sm:p-5 flex items-center justify-between gap-4 hover:bg-white/[0.07] transition-colors">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/15 border border-indigo-500/25 text-indigo-400 flex items-center justify-center flex-shrink-0">
              <RoleMatrixIcon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-white/55 truncate">{t('usersPage.kpiRolesTitle')}</div>
              <div className="text-xl font-semibold text-white mt-0.5">{roles.length}</div>
            </div>
          </div>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-white/70 font-mono flex-shrink-0">
            {t('usersPage.kpiPermsSub', { count: permissions.length })}
          </span>
        </div>

        <div className="glassmorphism rounded-xl p-4 sm:p-5 flex items-center justify-between gap-4 hover:bg-white/[0.07] transition-colors">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 text-white/75 flex items-center justify-center flex-shrink-0">
              <AuditTrailIcon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-white/55 truncate">{t('usersPage.kpiAuditTitle')}</div>
              <div className="text-xl font-semibold text-white mt-0.5">{auditLogs.length}</div>
            </div>
          </div>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-white/60 flex-shrink-0">
            {t('usersPage.kpiAuditSub')}
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
              <span
                className={`text-[11px] px-1.5 py-0.5 rounded-md font-mono ${
                  active ? 'bg-white/20 text-white' : 'bg-white/5 text-white/65'
                }`}
              >
                {tab.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* TAB 1: USERS TABLE */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          <div className="glassmorphism rounded-xl p-3.5 flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
            <div className="relative flex-1 max-w-md">
              <FaSearch className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40 text-xs" />
              <input
                type="text"
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder={t('usersPage.searchUsers')}
                className="w-full pl-9 pr-3 py-2 bg-black/25 border border-white/10 rounded-lg text-xs text-white placeholder-white/40 focus:outline-none focus:border-brand-500 transition-colors"
              />
            </div>

            <div className="flex items-center gap-2.5">
              <span className="text-xs text-white/55">{t('usersPage.roleFilterLabel')}</span>
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                className="px-3 py-2 rounded-lg text-xs text-white focus:outline-none focus:border-brand-500"
              >
                <option value="all">{t('usersPage.allRoles')}</option>
                {roles.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.display_name || r.name}
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
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colUser')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colRole')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colStatus')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colLastLogin')}</th>
                    <th className="py-3 px-4 font-semibold text-right">{t('usersPage.colActions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-sm">
                  {filteredUsers.map((u) => {
                    const isLocked = u.locked_until && new Date(u.locked_until) > new Date();
                    return (
                      <tr key={u.id} className="hover:bg-white/[0.04] transition-colors">
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-3">
                            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-500/25 to-indigo-500/25 border border-brand-500/25 flex items-center justify-center text-xs font-bold text-white uppercase flex-shrink-0">
                              {(u.username || '?').slice(0, 2)}
                            </div>
                            <div className="min-w-0">
                              <div className="font-medium text-white flex items-center gap-2">
                                <span className="truncate">{u.username}</span>
                                {currentUser?.id === u.id && (
                                  <span className="text-[10px] px-2 py-0.5 rounded-md bg-brand-500/20 border border-brand-500/30 text-brand-300 font-medium">
                                    {t('usersPage.badgeYou')}
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-white/50 truncate">{u.email}</div>
                            </div>
                          </div>
                        </td>
                        <td className="py-3.5 px-4">
                          <select
                            value={u.role}
                            onChange={(e) => handleQuickRoleChange(u, e.target.value)}
                            className={`text-xs px-2.5 py-1.5 rounded-lg border font-medium cursor-pointer ${
                              ROLE_BADGE_STYLES[u.role] || 'bg-white/5 text-white border-white/15'
                            }`}
                          >
                            {roles.map((r) => (
                              <option key={r.name} value={r.name}>
                                {r.display_name || r.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-3.5 px-4">
                          {isLocked ? (
                            <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/25">
                              <FaLock className="text-[10px]" /> {t('usersPage.statusLocked')}
                            </span>
                          ) : u.is_active !== false ? (
                            <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                              {t('usersPage.statusActive')}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/50">
                              <span className="w-1.5 h-1.5 rounded-full bg-white/30" />
                              {t('usersPage.statusInactive')}
                            </span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-xs text-white/55 font-mono">
                          {u.last_login ? new Date(u.last_login).toLocaleString(locale) : t('usersPage.never')}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            {isLocked && (
                              <button
                                onClick={() => handleUnlockUser(u)}
                                className="p-2 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/25 text-amber-300 text-xs transition-colors"
                                title={t('usersPage.unlockAccount')}
                              >
                                <FaUnlock />
                              </button>
                            )}
                            <button
                              onClick={() => {
                                setResetPasswordUser(u);
                                setNewPasswordValue('');
                              }}
                              className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/75 hover:text-white text-xs transition-colors"
                              title={t('usersPage.resetPassword')}
                            >
                              <FaKey />
                            </button>
                            <button
                              onClick={() => openEditUser(u)}
                              className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/75 hover:text-white text-xs transition-colors"
                              title={t('usersPage.editUser')}
                            >
                              <FaEdit />
                            </button>
                            {currentUser?.id !== u.id && (
                              <button
                                onClick={() => setConfirmState({ open: true, type: 'deleteUser', target: u, busy: false })}
                                className="p-2 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-300 text-xs transition-colors"
                                title={t('usersPage.deactivateUser')}
                              >
                                <FaTrash />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredUsers.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-10 text-center text-xs text-white/45">
                        {t('usersPage.noUsersMatch')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: ROLES & PERMISSIONS */}
      {activeTab === 'roles' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Left column: Role list */}
          <div className="lg:col-span-4 space-y-2.5">
            <div className="flex items-center justify-between px-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-white/55">
                {t('usersPage.rolesHeader', { count: roles.length })}
              </span>
              <button
                onClick={() => setShowCreateRoleModal(true)}
                className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1 font-medium"
              >
                <FaPlus className="text-[10px]" /> {t('usersPage.createRole')}
              </button>
            </div>

            <div className="glassmorphism rounded-xl divide-y divide-white/10 overflow-hidden">
              {roles.map((r) => {
                const isSelected = selectedRole && selectedRole.name === r.name;
                const userCount = users.filter((u) => u.role === r.name).length;
                return (
                  <button
                    key={r.name}
                    type="button"
                    onClick={() => setSelectedRoleName(r.name)}
                    className={`w-full text-left px-4 py-3.5 transition-colors flex items-center justify-between gap-2 border-l-2 ${
                      isSelected
                        ? 'bg-brand-500/15 border-brand-500'
                        : 'hover:bg-white/[0.04] border-transparent'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-white">
                          {r.display_name || r.name}
                        </span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${
                            ROLE_BADGE_STYLES[r.name] || 'bg-white/5 text-white/60 border-white/10'
                          }`}
                        >
                          {r.name}
                        </span>
                        {r.is_system && (
                          <span className="text-[10px] text-white/40">{t('usersPage.systemBadge')}</span>
                        )}
                      </div>
                      <p className="text-xs text-white/50 truncate mt-0.5">
                        {r.description || t('usersPage.noDescription')}
                      </p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <div className="text-xs font-mono text-white/80">
                        {t('usersPage.permsCount', { count: (r.permissions || []).length })}
                      </div>
                      <div className="text-[11px] text-white/45">
                        {t('usersPage.userCount', { count: userCount })}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Right column: Permission Matrix for Selected Role */}
          <div className="lg:col-span-8">
            {selectedRole ? (
              <div className="glassmorphism rounded-xl overflow-hidden">
                <div className="px-5 py-4 border-b border-white/10 flex flex-wrap items-center justify-between gap-3 bg-white/[0.03]">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-base font-semibold text-white">
                        {selectedRole.display_name || selectedRole.name}
                      </h3>
                      <span className="text-xs px-2.5 py-0.5 rounded-lg bg-white/5 border border-white/10 text-white/70 font-mono">
                        {t('usersPage.permsEnabled', { enabled: editingRolePerms.length, total: permissions.length })}
                      </span>
                      {selectedRole.is_system && (
                        <span className="text-xs px-2.5 py-0.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300">
                          {t('usersPage.builtInReadOnly')}
                        </span>
                      )}
                    </div>
                    {selectedRole.is_system ? (
                      <p className="text-xs text-white/55 mt-1">{selectedRole.description}</p>
                    ) : (
                      <input
                        type="text"
                        value={editingRoleDesc}
                        onChange={(e) => setEditingRoleDesc(e.target.value)}
                        placeholder={t('usersPage.roleDescPlaceholder')}
                        className="mt-2 w-full sm:w-96 px-3 py-1.5 bg-black/30 border border-white/10 rounded-lg text-xs text-white focus:outline-none focus:border-brand-500"
                      />
                    )}
                  </div>

                  {!selectedRole.is_system && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={saveRoleChanges}
                        disabled={savingRole}
                        className="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-600 text-xs font-semibold text-white inline-flex items-center gap-1.5 disabled:opacity-50 transition-colors"
                      >
                        <FaCheck className="text-[10px]" />
                        <span>{savingRole ? t('usersPage.saving') : t('usersPage.saveChanges')}</span>
                      </button>
                      <button
                        onClick={() => setConfirmState({ open: true, type: 'deleteRole', target: selectedRole, busy: false })}
                        className="px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-xs text-red-300 inline-flex items-center gap-1.5 transition-colors"
                      >
                        <FaTrash className="text-[10px]" />
                        <span>{t('common.delete')}</span>
                      </button>
                    </div>
                  )}
                </div>

                {/* Permission Categories */}
                <div className="p-5 space-y-5 max-h-[640px] overflow-y-auto">
                  {Object.entries(groupedPermissions).map(([category, catPerms]) => {
                    const enabledInCat = catPerms.filter((p) =>
                      editingRolePerms.includes(p.name)
                    ).length;
                    return (
                      <div key={category} className="space-y-2.5">
                        <div className="flex items-center justify-between border-b border-white/10 pb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold uppercase tracking-wider text-white/80">
                              {getCategoryLabel(category)}
                            </span>
                            <span className="text-[11px] font-mono text-white/45">
                              ({enabledInCat}/{catPerms.length})
                            </span>
                          </div>
                          {!selectedRole.is_system && (
                            <button
                              type="button"
                              onClick={() => toggleCategoryPermissions(catPerms)}
                              className="text-[11px] text-brand-400 hover:text-brand-300 font-medium"
                            >
                              {enabledInCat === catPerms.length
                                ? t('usersPage.clearCategory')
                                : t('usersPage.selectAll')}
                            </button>
                          )}
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {catPerms.map((perm) => {
                            const checked = editingRolePerms.includes(perm.name);
                            return (
                              <label
                                key={perm.name}
                                onClick={() => !selectedRole.is_system && toggleRolePermission(perm.name)}
                                className={`flex items-start gap-2.5 p-2.5 rounded-lg border text-xs transition-colors ${
                                  selectedRole.is_system ? 'cursor-default' : 'cursor-pointer'
                                } ${
                                  checked
                                    ? 'bg-brand-500/10 border-brand-500/30 text-white'
                                    : 'bg-white/[0.02] border-white/10 text-white/50'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  disabled={selectedRole.is_system}
                                  onChange={() => {}}
                                  className="mt-0.5 rounded bg-white/10 border-white/20 text-brand-500"
                                />
                                <div className="min-w-0">
                                  <div className="font-mono text-[11px] font-medium truncate">
                                    {perm.name}
                                  </div>
                                  {perm.description && (
                                    <div className="text-[11px] text-white/50 mt-0.5">
                                      {perm.description}
                                    </div>
                                  )}
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="glassmorphism rounded-xl p-8 text-center text-xs text-white/50">
                {t('usersPage.selectRoleHint')}
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: AUDIT LOG */}
      {activeTab === 'audit' && (
        <div className="space-y-4">
          <div className="glassmorphism rounded-xl p-3.5 flex flex-wrap items-center justify-between gap-3">
            <div className="relative flex-1 max-w-md">
              <FaSearch className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40 text-xs" />
              <input
                type="text"
                value={auditSearch}
                onChange={(e) => setAuditSearch(e.target.value)}
                placeholder={t('usersPage.auditFilterPlaceholder')}
                className="w-full pl-9 pr-3 py-2 bg-black/25 border border-white/10 rounded-lg text-xs text-white placeholder-white/40 focus:outline-none focus:border-brand-500"
              />
            </div>
            <span className="text-xs px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-white/65 font-mono">
              {t('usersPage.eventsCount', { count: filteredAuditLogs.length })}
            </span>
          </div>

          <div className="glassmorphism rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/50 bg-white/[0.03]">
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colTimestamp')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colUser')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colAction')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colResource')}</th>
                    <th className="py-3 px-4 font-semibold">{t('usersPage.colIp')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-xs">
                  {filteredAuditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-white/[0.04] transition-colors">
                      <td className="py-3 px-4 text-white/60 whitespace-nowrap font-mono">
                        {log.timestamp ? new Date(log.timestamp).toLocaleString(locale) : '—'}
                      </td>
                      <td className="py-3 px-4 text-white font-medium">
                        {log.username || (log.user_id ? `#${log.user_id}` : t('usersPage.systemUser'))}
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
                    </tr>
                  ))}
                  {filteredAuditLogs.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-10 text-center text-white/45">
                        {t('usersPage.noAuditEvents')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Create / Edit User */}
      {showUserModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-ink-900 border border-white/15 rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                {editingUser
                  ? t('usersPage.editUserTitle', { username: editingUser.username })
                  : t('usersPage.createUserTitle')}
              </h3>
              <button
                onClick={() => setShowUserModal(false)}
                className="p-1.5 rounded-lg text-white/55 hover:text-white hover:bg-white/10 transition-colors"
                aria-label={t('common.close')}
              >
                <CloseVectorIcon className="w-3.5 h-3.5" />
              </button>
            </div>
            <form onSubmit={saveUser} className="p-5 space-y-3.5 text-xs">
              {!editingUser && (
                <div>
                  <label className="block text-white/65 mb-1.5">{t('usersPage.usernameLabel')}</label>
                  <input
                    type="text"
                    required
                    value={userForm.username}
                    onChange={(e) => setUserForm((p) => ({ ...p, username: e.target.value }))}
                    className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                  />
                </div>
              )}
              <div>
                <label className="block text-white/65 mb-1.5">{t('usersPage.emailLabel')}</label>
                <input
                  type="email"
                  required
                  value={userForm.email}
                  onChange={(e) => setUserForm((p) => ({ ...p, email: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label className="block text-white/65 mb-1.5">{t('usersPage.fullNameLabel')}</label>
                <input
                  type="text"
                  value={userForm.full_name}
                  onChange={(e) => setUserForm((p) => ({ ...p, full_name: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label className="block text-white/65 mb-1.5">
                  {editingUser ? t('usersPage.newPasswordHint') : t('usersPage.passwordHint')}
                </label>
                <input
                  type="password"
                  required={!editingUser}
                  value={userForm.password}
                  onChange={(e) => setUserForm((p) => ({ ...p, password: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-white/65 mb-1.5">{t('usersPage.roleLabel')}</label>
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm((p) => ({ ...p, role: e.target.value }))}
                    className="w-full px-3 py-2 rounded-lg text-white"
                  >
                    {roles.map((r) => (
                      <option key={r.name} value={r.name}>
                        {r.display_name || r.name}
                      </option>
                    ))}
                  </select>
                </div>
                {editingUser && (
                  <div className="flex items-end pb-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={userForm.is_active}
                        onChange={(e) => setUserForm((p) => ({ ...p, is_active: e.target.checked }))}
                        className="rounded bg-white/10 border-white/20 text-brand-500"
                      />
                      <span className="text-white">{t('usersPage.accountActive')}</span>
                    </label>
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-2 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowUserModal(false)}
                  className="px-3.5 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/75"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-white font-semibold"
                >
                  {editingUser ? t('usersPage.saveChanges') : t('usersPage.createUserBtn')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Create Custom Role */}
      {showCreateRoleModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-ink-900 border border-white/15 rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl">
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">{t('usersPage.createRoleTitle')}</h3>
              <button
                onClick={() => setShowCreateRoleModal(false)}
                className="p-1.5 rounded-lg text-white/55 hover:text-white hover:bg-white/10 transition-colors"
                aria-label={t('common.close')}
              >
                <CloseVectorIcon className="w-3.5 h-3.5" />
              </button>
            </div>
            <form onSubmit={handleCreateRole} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block text-white/65 mb-1.5">{t('usersPage.roleNameLabel')}</label>
                <input
                  type="text"
                  required
                  placeholder={t('usersPage.roleNamePlaceholder')}
                  value={newRoleForm.name}
                  onChange={(e) => setNewRoleForm((p) => ({ ...p, name: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label className="block text-white/65 mb-1.5">{t('usersPage.roleDescLabel')}</label>
                <input
                  type="text"
                  placeholder={t('usersPage.roleDescFieldPlaceholder')}
                  value={newRoleForm.description}
                  onChange={(e) => setNewRoleForm((p) => ({ ...p, description: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label className="block text-white/65 mb-1.5">
                  {t('usersPage.initialPermsLabel', { count: newRoleForm.permissions.length })}
                </label>
                <div className="max-h-56 overflow-y-auto border border-white/10 rounded-xl p-3 space-y-2 bg-black/25">
                  {permissions.map((perm) => {
                    const checked = newRoleForm.permissions.includes(perm.name);
                    return (
                      <label key={perm.name} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setNewRoleForm((prev) => ({
                              ...prev,
                              permissions: checked
                                ? prev.permissions.filter((p) => p !== perm.name)
                                : [...prev.permissions, perm.name],
                            }))
                          }
                          className="rounded bg-white/10 border-white/20 text-brand-500"
                        />
                        <span className="font-mono text-white">{perm.name}</span>
                        <span className="text-white/45 truncate">— {perm.description}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowCreateRoleModal(false)}
                  className="px-3.5 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/75"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-white font-semibold"
                >
                  {t('usersPage.createRole')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Admin Reset Password */}
      {resetPasswordUser && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-ink-900 border border-white/15 rounded-2xl w-full max-w-sm overflow-hidden shadow-2xl">
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                {t('usersPage.resetPasswordTitle', { username: resetPasswordUser.username })}
              </h3>
              <button
                onClick={() => setResetPasswordUser(null)}
                className="p-1.5 rounded-lg text-white/55 hover:text-white hover:bg-white/10 transition-colors"
                aria-label={t('common.close')}
              >
                <CloseVectorIcon className="w-3.5 h-3.5" />
              </button>
            </div>
            <form onSubmit={handleAdminResetPassword} className="p-5 space-y-3.5 text-xs">
              <div>
                <label className="block text-white/65 mb-1.5">{t('usersPage.newPasswordLabel')}</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  placeholder={t('usersPage.min8CharsPlaceholder')}
                  value={newPasswordValue}
                  onChange={(e) => setNewPasswordValue(e.target.value)}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white focus:outline-none focus:border-brand-500"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setResetPasswordUser(null)}
                  className="px-3.5 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/75"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-white font-semibold"
                >
                  {t('usersPage.setPasswordBtn')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirmation Modal for Delete User / Delete Role */}
      <ConfirmModal
        isOpen={confirmState.open}
        title={confirmState.type === 'deleteUser' ? t('usersPage.deactivateUser') : t('common.delete')}
        message={
          confirmState.type === 'deleteUser'
            ? t('usersPage.confirmDeleteUser', { username: confirmState.target?.username || '' })
            : t('usersPage.confirmDeleteRole', { name: confirmState.target?.name || '' })
        }
        confirmText={t('common.delete')}
        cancelText={t('common.cancel')}
        confirmVariant="danger"
        isLoading={confirmState.busy}
        onCancel={() => setConfirmState({ open: false, type: null, target: null, busy: false })}
        onConfirm={() => {
          if (confirmState.type === 'deleteUser') executeDeleteUser(confirmState.target);
          else if (confirmState.type === 'deleteRole') executeDeleteRole(confirmState.target);
        }}
      />
    </div>
  );
}
