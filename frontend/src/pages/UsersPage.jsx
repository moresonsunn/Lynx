import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  FaUsers,
  FaUserShield,
  FaHistory,
  FaPlus,
  FaSearch,
  FaEdit,
  FaTrash,
  FaKey,
  FaLock,
  FaUnlock,
  FaCheck,
  FaTimes,
  FaSync,
} from 'react-icons/fa';
import { API, authHeaders } from '../context/AppContext';
import { useTranslation } from '../i18n';

const ROLE_BADGE_STYLES = {
  owner: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  admin: 'bg-red-500/15 text-red-300 border-red-500/30',
  moderator: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  helper: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  user: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  guest: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
};

const CATEGORY_LABELS = {
  server: 'Server Management',
  user: 'User Accounts',
  role: 'Roles & Access',
  backup: 'Backups',
  schedule: 'Scheduled Tasks',
  player: 'Player Management',
  world: 'Worlds',
  plugin: 'Mods & Plugins',
  system: 'System & Audit',
};

export default function UsersPage({ currentUser }) {
  const { t } = useTranslation();
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
      setNotice(editingUser ? `Updated user ${editingUser.username}` : `Created user ${userForm.username}`);
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
        throw new Error(d.detail || `Failed to update role`);
      }
      setNotice(`Role for ${user.username} changed to ${newRole}`);
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function handleDeleteUser(user) {
    if (!confirm(`Deactivate/delete user "${user.username}"?`)) return;
    setError('');
    try {
      const r = await fetch(`${API}/users/${user.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Failed to delete user`);
      }
      setNotice(`User ${user.username} deactivated`);
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function handleUnlockUser(user) {
    try {
      const r = await fetch(`${API}/users/${user.id}/unlock`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (r.ok) {
        setNotice(`Unlocked ${user.username}`);
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
        throw new Error(d.detail || `Password reset failed`);
      }
      setNotice(`Password updated for ${resetPasswordUser.username}`);
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
        throw new Error(d.detail || `Failed to update role`);
      }
      setNotice(`Saved permissions for role "${selectedRole.name}"`);
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
        throw new Error(d.detail || `Failed to create role`);
      }
      const createdName = newRoleForm.name.trim().toLowerCase().replace(/\s+/g, '_');
      setShowCreateRoleModal(false);
      setNewRoleForm({ name: '', description: '', permissions: [] });
      setNotice(`Created custom role "${createdName}"`);
      await loadAll();
      setSelectedRoleName(createdName);
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function handleDeleteRole(role) {
    if (role.is_system) return;
    if (!confirm(`Delete custom role "${role.name}"?`)) return;
    setError('');
    try {
      const r = await fetch(`${API}/users/roles/${encodeURIComponent(role.name)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Failed to delete role`);
      }
      setNotice(`Deleted role "${role.name}"`);
      setSelectedRoleName('owner');
      await loadAll();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      {/* Clean Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <h1 className="text-xl font-semibold text-white">
            {t('nav.users') || 'User Management'}
          </h1>
          <p className="text-xs text-white/50 mt-0.5">
            Manage accounts, role-based access control ({roles.length} roles, {permissions.length} permissions), and administrative audit logs.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={loadAll}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
          >
            <FaSync className={`text-[11px] ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          {activeTab === 'roles' ? (
            <button
              onClick={() => setShowCreateRoleModal(true)}
              className="px-3 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-1.5 transition-colors"
            >
              <FaPlus className="text-[11px]" />
              New Custom Role
            </button>
          ) : (
            <button
              onClick={openCreateUser}
              className="px-3 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-1.5 transition-colors"
            >
              <FaPlus className="text-[11px]" />
              Add User
            </button>
          )}
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

      {/* Clean Underline Tabs */}
      <div className="flex items-center gap-6 border-b border-white/10 text-sm">
        {[
          { id: 'users', label: 'Users', count: users.length, icon: FaUsers },
          { id: 'roles', label: 'Roles & Permissions', count: roles.length, icon: FaUserShield },
          { id: 'audit', label: 'Audit Log', count: auditLogs.length, icon: FaHistory },
        ].map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 -mb-px flex items-center gap-2 border-b-2 font-medium transition-colors ${
                active
                  ? 'border-brand-500 text-white'
                  : 'border-transparent text-white/55 hover:text-white/85'
              }`}
            >
              <tab.icon className={`text-xs ${active ? 'text-brand-400' : 'text-white/40'}`} />
              <span>{tab.label}</span>
              <span className="text-xs px-1.5 py-0.2 rounded bg-white/5 text-white/60 font-mono">
                {tab.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* TAB 1: USERS TABLE */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
            <div className="relative flex-1 max-w-sm">
              <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
              <input
                type="text"
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="Search by username or email…"
                className="w-full pl-8 pr-3 py-1.5 bg-white/[0.03] border border-white/10 rounded-lg text-xs text-white placeholder-white/35 focus:outline-none focus:border-brand-500"
              />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-white/45">Role:</span>
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                className="px-2.5 py-1.5 bg-[#141824] border border-white/10 rounded-lg text-xs text-white"
              >
                <option value="all">All Roles</option>
                {roles.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.display_name || r.name}
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
                    <th className="py-2.5 px-4 font-medium">User</th>
                    <th className="py-2.5 px-4 font-medium">Role</th>
                    <th className="py-2.5 px-4 font-medium">Status</th>
                    <th className="py-2.5 px-4 font-medium">Last Login</th>
                    <th className="py-2.5 px-4 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-sm">
                  {filteredUsers.map((u) => {
                    const isLocked = u.locked_until && new Date(u.locked_until) > new Date();
                    return (
                      <tr key={u.id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center text-xs font-semibold text-white uppercase">
                              {(u.username || '?').slice(0, 2)}
                            </div>
                            <div>
                              <div className="font-medium text-white flex items-center gap-2">
                                {u.username}
                                {currentUser?.id === u.id && (
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-500/20 text-brand-300">
                                    You
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-white/45">{u.email}</div>
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <select
                            value={u.role}
                            onChange={(e) => handleQuickRoleChange(u, e.target.value)}
                            className={`text-xs px-2.5 py-1 rounded-md border font-medium bg-[#141824] cursor-pointer ${
                              ROLE_BADGE_STYLES[u.role] || 'bg-white/5 text-white border-white/15'
                            }`}
                          >
                            {roles.map((r) => (
                              <option key={r.name} value={r.name} className="bg-[#141824] text-white">
                                {r.display_name || r.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-3 px-4">
                          {isLocked ? (
                            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-300 border border-red-500/25">
                              <FaLock className="text-[10px]" /> Locked
                            </span>
                          ) : u.is_active !== false ? (
                            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                              Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-xs text-white/40">
                              <span className="w-1.5 h-1.5 rounded-full bg-white/30" />
                              Inactive
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-xs text-white/50">
                          {u.last_login ? new Date(u.last_login).toLocaleString() : 'Never'}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            {isLocked && (
                              <button
                                onClick={() => handleUnlockUser(u)}
                                className="p-1.5 rounded hover:bg-white/10 text-amber-300 text-xs"
                                title="Unlock account"
                              >
                                <FaUnlock />
                              </button>
                            )}
                            <button
                              onClick={() => {
                                setResetPasswordUser(u);
                                setNewPasswordValue('');
                              }}
                              className="p-1.5 rounded hover:bg-white/10 text-white/65 hover:text-white text-xs"
                              title="Reset password"
                            >
                              <FaKey />
                            </button>
                            <button
                              onClick={() => openEditUser(u)}
                              className="p-1.5 rounded hover:bg-white/10 text-white/65 hover:text-white text-xs"
                              title="Edit user"
                            >
                              <FaEdit />
                            </button>
                            {currentUser?.id !== u.id && (
                              <button
                                onClick={() => handleDeleteUser(u)}
                                className="p-1.5 rounded hover:bg-red-500/15 text-red-400/80 hover:text-red-300 text-xs"
                                title="Deactivate user"
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
                      <td colSpan={5} className="py-8 text-center text-xs text-white/45">
                        No users match your filter.
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
          <div className="lg:col-span-4 space-y-2">
            <div className="flex items-center justify-between px-1 mb-1">
              <span className="text-xs font-medium uppercase tracking-wider text-white/45">
                Roles ({roles.length})
              </span>
              <button
                onClick={() => setShowCreateRoleModal(true)}
                className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1"
              >
                <FaPlus className="text-[10px]" /> Create Role
              </button>
            </div>

            <div className="rounded-xl border border-white/10 bg-white/[0.02] divide-y divide-white/10 overflow-hidden">
              {roles.map((r) => {
                const isSelected = selectedRole && selectedRole.name === r.name;
                const userCount = users.filter((u) => u.role === r.name).length;
                return (
                  <button
                    key={r.name}
                    type="button"
                    onClick={() => setSelectedRoleName(r.name)}
                    className={`w-full text-left px-4 py-3 transition-colors flex items-center justify-between gap-2 ${
                      isSelected ? 'bg-brand-500/15' : 'hover:bg-white/[0.03]'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
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
                          <span className="text-[10px] text-white/35">system</span>
                        )}
                      </div>
                      <p className="text-xs text-white/45 truncate mt-0.5">
                        {r.description || 'No description'}
                      </p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <div className="text-xs font-mono text-white/75">
                        {(r.permissions || []).length} perms
                      </div>
                      <div className="text-[11px] text-white/40">
                        {userCount} user{userCount === 1 ? '' : 's'}
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
              <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
                <div className="px-5 py-4 border-b border-white/10 flex flex-wrap items-center justify-between gap-3 bg-white/[0.02]">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-semibold text-white">
                        {selectedRole.display_name || selectedRole.name}
                      </h3>
                      <span className="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-white/60 font-mono">
                        {editingRolePerms.length} / {permissions.length} permissions enabled
                      </span>
                      {selectedRole.is_system && (
                        <span className="text-xs px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300">
                          Built-in System Role (Read-only)
                        </span>
                      )}
                    </div>
                    {selectedRole.is_system ? (
                      <p className="text-xs text-white/50 mt-1">{selectedRole.description}</p>
                    ) : (
                      <input
                        type="text"
                        value={editingRoleDesc}
                        onChange={(e) => setEditingRoleDesc(e.target.value)}
                        placeholder="Role description…"
                        className="mt-2 w-full sm:w-96 px-2.5 py-1 bg-black/30 border border-white/10 rounded text-xs text-white"
                      />
                    )}
                  </div>

                  {!selectedRole.is_system && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={saveRoleChanges}
                        disabled={savingRole}
                        className="px-3 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-medium text-white inline-flex items-center gap-1.5 disabled:opacity-50"
                      >
                        <FaCheck className="text-[10px]" />
                        {savingRole ? 'Saving…' : 'Save Changes'}
                      </button>
                      <button
                        onClick={() => handleDeleteRole(selectedRole)}
                        className="px-2.5 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-xs text-red-300 inline-flex items-center gap-1"
                      >
                        <FaTrash className="text-[10px]" />
                        Delete
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
                      <div key={category} className="space-y-2">
                        <div className="flex items-center justify-between border-b border-white/10 pb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold uppercase tracking-wider text-white/75">
                              {CATEGORY_LABELS[category] || category}
                            </span>
                            <span className="text-[11px] font-mono text-white/40">
                              ({enabledInCat}/{catPerms.length})
                            </span>
                          </div>
                          {!selectedRole.is_system && (
                            <button
                              type="button"
                              onClick={() => toggleCategoryPermissions(catPerms)}
                              className="text-[11px] text-brand-400 hover:text-brand-300"
                            >
                              {enabledInCat === catPerms.length ? 'Clear category' : 'Select all'}
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
                                    : 'bg-white/[0.01] border-white/5 text-white/45'
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
                                    <div className="text-[11px] text-white/45 mt-0.5">
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
              <div className="rounded-xl border border-white/10 bg-white/[0.02] p-8 text-center text-xs text-white/45">
                Select a role on the left to inspect its permissions.
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: AUDIT LOG */}
      {activeTab === 'audit' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="relative flex-1 max-w-sm">
              <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
              <input
                type="text"
                value={auditSearch}
                onChange={(e) => setAuditSearch(e.target.value)}
                placeholder="Filter by user, action, resource, or IP…"
                className="w-full pl-8 pr-3 py-1.5 bg-white/[0.03] border border-white/10 rounded-lg text-xs text-white placeholder-white/35 focus:outline-none focus:border-brand-500"
              />
            </div>
            <span className="text-xs text-white/45">{filteredAuditLogs.length} events</span>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/45 bg-white/[0.02]">
                    <th className="py-2.5 px-4 font-medium">Timestamp</th>
                    <th className="py-2.5 px-4 font-medium">User</th>
                    <th className="py-2.5 px-4 font-medium">Action</th>
                    <th className="py-2.5 px-4 font-medium">Resource</th>
                    <th className="py-2.5 px-4 font-medium">IP Address</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10 text-xs">
                  {filteredAuditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-white/[0.02]">
                      <td className="py-2.5 px-4 text-white/55 whitespace-nowrap font-mono">
                        {log.timestamp ? new Date(log.timestamp).toLocaleString() : '—'}
                      </td>
                      <td className="py-2.5 px-4 text-white font-medium">
                        {log.username || (log.user_id ? `User #${log.user_id}` : 'System')}
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
                    </tr>
                  ))}
                  {filteredAuditLogs.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-white/40">
                        No audit events recorded yet.
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
          <div className="bg-[#141824] border border-white/15 rounded-xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                {editingUser ? `Edit User: ${editingUser.username}` : 'Create New User'}
              </h3>
              <button
                onClick={() => setShowUserModal(false)}
                className="text-white/50 hover:text-white"
              >
                <FaTimes />
              </button>
            </div>
            <form onSubmit={saveUser} className="p-5 space-y-3.5 text-xs">
              {!editingUser && (
                <div>
                  <label className="block text-white/60 mb-1">Username</label>
                  <input
                    type="text"
                    required
                    value={userForm.username}
                    onChange={(e) => setUserForm((p) => ({ ...p, username: e.target.value }))}
                    className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                  />
                </div>
              )}
              <div>
                <label className="block text-white/60 mb-1">Email</label>
                <input
                  type="email"
                  required
                  value={userForm.email}
                  onChange={(e) => setUserForm((p) => ({ ...p, email: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                />
              </div>
              <div>
                <label className="block text-white/60 mb-1">Full Name (optional)</label>
                <input
                  type="text"
                  value={userForm.full_name}
                  onChange={(e) => setUserForm((p) => ({ ...p, full_name: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                />
              </div>
              <div>
                <label className="block text-white/60 mb-1">
                  {editingUser ? 'New Password (leave blank to keep current)' : 'Password (min. 8 chars, upper+lower+number)'}
                </label>
                <input
                  type="password"
                  required={!editingUser}
                  value={userForm.password}
                  onChange={(e) => setUserForm((p) => ({ ...p, password: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-white/60 mb-1">Role</label>
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm((p) => ({ ...p, role: e.target.value }))}
                    className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
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
                      <span className="text-white">Account Active</span>
                    </label>
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-2 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowUserModal(false)}
                  className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/70"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-medium"
                >
                  {editingUser ? 'Save Changes' : 'Create User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Create Custom Role */}
      {showCreateRoleModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#141824] border border-white/15 rounded-xl w-full max-w-lg overflow-hidden shadow-2xl">
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">Create Custom Role</h3>
              <button
                onClick={() => setShowCreateRoleModal(false)}
                className="text-white/50 hover:text-white"
              >
                <FaTimes />
              </button>
            </div>
            <form onSubmit={handleCreateRole} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block text-white/60 mb-1">Role Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. developer, backup_operator"
                  value={newRoleForm.name}
                  onChange={(e) => setNewRoleForm((p) => ({ ...p, name: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                />
              </div>
              <div>
                <label className="block text-white/60 mb-1">Description</label>
                <input
                  type="text"
                  placeholder="Short summary of what this role can do"
                  value={newRoleForm.description}
                  onChange={(e) => setNewRoleForm((p) => ({ ...p, description: e.target.value }))}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                />
              </div>
              <div>
                <label className="block text-white/60 mb-1.5">
                  Initial Permissions ({newRoleForm.permissions.length} selected)
                </label>
                <div className="max-h-56 overflow-y-auto border border-white/10 rounded-lg p-3 space-y-2 bg-black/20">
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
                        <span className="text-white/40 truncate">— {perm.description}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowCreateRoleModal(false)}
                  className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/70"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-medium"
                >
                  Create Role
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Admin Reset Password */}
      {resetPasswordUser && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#141824] border border-white/15 rounded-xl w-full max-w-sm overflow-hidden shadow-2xl">
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                Reset Password: {resetPasswordUser.username}
              </h3>
              <button
                onClick={() => setResetPasswordUser(null)}
                className="text-white/50 hover:text-white"
              >
                <FaTimes />
              </button>
            </div>
            <form onSubmit={handleAdminResetPassword} className="p-5 space-y-3 text-xs">
              <div>
                <label className="block text-white/60 mb-1">New Password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  placeholder="Min. 8 characters"
                  value={newPasswordValue}
                  onChange={(e) => setNewPasswordValue(e.target.value)}
                  className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setResetPasswordUser(null)}
                  className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/70"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-medium"
                >
                  Set Password
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
