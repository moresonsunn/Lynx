import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FaUsers,
  FaUserShield,
  FaPlus,
  FaEdit,
  FaTrash,
  FaCheck,
  FaTimes,
  FaHistory,
  FaKey,
  FaEnvelope,
  FaShieldAlt,
  FaSearch,
  FaLock,
  FaUnlock,
  FaCopy,
  FaServer,
  FaTerminal,
  FaFolder,
  FaCube,
  FaClock,
  FaCog,
  FaCheckCircle,
} from 'react-icons/fa';
import { useTranslation } from '../i18n';
import { API, authHeaders, useAuth } from '../context/AppContext';

const ROLE_COLOR_PRESETS = [
  '#ef4444', // Red (Owner/Critical)
  '#f97316', // Orange
  '#eab308', // Amber
  '#22c55e', // Emerald
  '#06b6d4', // Cyan
  '#3b82f6', // Blue
  '#6366f1', // Indigo
  '#a855f7', // Purple
  '#ec4899', // Pink
];

function getCategoryMeta(categoryName = '') {
  const key = categoryName.toLowerCase();
  if (key.includes('server')) return { icon: FaServer, accent: 'text-blue-400', bg: 'bg-blue-500/15' };
  if (key.includes('console') || key.includes('command')) return { icon: FaTerminal, accent: 'text-emerald-400', bg: 'bg-emerald-500/15' };
  if (key.includes('file') || key.includes('config')) return { icon: FaFolder, accent: 'text-amber-400', bg: 'bg-amber-500/15' };
  if (key.includes('mod') || key.includes('plugin')) return { icon: FaCube, accent: 'text-purple-400', bg: 'bg-purple-500/15' };
  if (key.includes('backup') || key.includes('schedule')) return { icon: FaClock, accent: 'text-cyan-400', bg: 'bg-cyan-500/15' };
  if (key.includes('user') || key.includes('role') || key.includes('security')) return { icon: FaUserShield, accent: 'text-rose-400', bg: 'bg-rose-500/15' };
  return { icon: FaCog, accent: 'text-brand-400', bg: 'bg-brand-500/15' };
}

function formatRelativeDate(dateStr) {
  if (!dateStr) return 'Never';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return 'Never';
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 60000) return 'Just now';
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h ago`;
    if (diffMs < 604800000) return `${Math.floor(diffMs / 86400000)}d ago`;
    return d.toLocaleDateString();
  } catch {
    return 'Never';
  }
}

export default function UsersPage() {
  const { t } = useTranslation();
  const { currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [permissions, setPermissions] = useState({});
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('users');

  // Search & Filter states
  const [userSearch, setUserSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [selectedRoleKey, setSelectedRoleKey] = useState(null);
  const [permSearch, setPermSearch] = useState('');
  const [auditSearch, setAuditSearch] = useState('');

  // Modal states
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [showEditUser, setShowEditUser] = useState(null);
  const [showCreateRole, setShowCreateRole] = useState(false);
  const [showEditRole, setShowEditRole] = useState(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/users`, { headers: authHeaders() });
      if (!r.ok) throw new Error('Failed to load users');
      const data = await r.json();
      setUsers(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRoles = useCallback(async () => {
    try {
      const r = await fetch(`${API}/users/roles/list`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        const roleList = data.roles || [];
        setRoles(roleList);
        setSelectedRoleKey(prev => prev || (roleList[0]?.name ?? null));
      }
    } catch (e) {
      console.error('Failed to load roles:', e);
    }
  }, []);

  const loadPermissions = useCallback(async () => {
    try {
      const r = await fetch(`${API}/users/permissions/list`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        setPermissions(data.categories || {});
      }
    } catch (e) {
      console.error('Failed to load permissions:', e);
    }
  }, []);

  const loadAuditLogs = useCallback(async () => {
    try {
      const r = await fetch(`${API}/users/audit/logs?limit=100`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        setAuditLogs(data.logs || []);
      }
    } catch (e) {
      console.error('Failed to load audit logs:', e);
    }
  }, []);

  useEffect(() => {
    loadUsers();
    loadRoles();
    loadPermissions();
    loadAuditLogs();
  }, [loadUsers, loadRoles, loadPermissions, loadAuditLogs]);

  useEffect(() => {
    if (activeTab === 'audit') {
      loadAuditLogs();
    }
  }, [activeTab, loadAuditLogs]);

  const totalPermissionsCount = useMemo(() => {
    return Object.values(permissions).reduce((acc, arr) => acc + (Array.isArray(arr) ? arr.length : 0), 0);
  }, [permissions]);

  const filteredUsers = useMemo(() => {
    const q = userSearch.trim().toLowerCase();
    return users.filter(u => {
      if (roleFilter !== 'all' && u.role !== roleFilter) return false;
      if (!q) return true;
      return (
        (u.username && u.username.toLowerCase().includes(q)) ||
        (u.email && u.email.toLowerCase().includes(q)) ||
        (u.full_name && u.full_name.toLowerCase().includes(q)) ||
        (u.role && u.role.toLowerCase().includes(q))
      );
    });
  }, [users, userSearch, roleFilter]);

  const selectedRole = useMemo(() => {
    if (!roles.length) return null;
    return roles.find(r => r.name === selectedRoleKey) || roles[0];
  }, [roles, selectedRoleKey]);

  const userCountByRole = useMemo(() => {
    const counts = {};
    for (const u of users) {
      counts[u.role] = (counts[u.role] || 0) + 1;
    }
    return counts;
  }, [users]);

  const filteredAuditLogs = useMemo(() => {
    const q = auditSearch.trim().toLowerCase();
    if (!q) return auditLogs;
    return auditLogs.filter(log =>
      (log.action && log.action.toLowerCase().includes(q)) ||
      (log.username && log.username.toLowerCase().includes(q)) ||
      (log.ip_address && log.ip_address.toLowerCase().includes(q))
    );
  }, [auditLogs, auditSearch]);

  async function deleteUser(userId, username) {
    if (!window.confirm(`Are you sure you want to delete user "${username}"?`)) return;
    try {
      const r = await fetch(`${API}/users/${userId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to delete user');
      }
      loadUsers();
      loadAuditLogs();
    } catch (e) {
      alert(e.message);
    }
  }

  async function deleteRole(roleId, roleName) {
    if (!window.confirm(`Are you sure you want to delete role "${roleName}"?`)) return;
    try {
      const r = await fetch(`${API}/users/roles/${roleId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to delete role');
      }
      loadRoles();
      loadAuditLogs();
    } catch (e) {
      alert(e.message);
    }
  }

  function cloneRoleAsCustom(role) {
    setShowCreateRole({
      name: `${role.name}_copy`,
      display_name: `${role.display_name} (Copy)`,
      description: role.description || '',
      color: role.color || '#6366f1',
      permissions: [...(role.permissions || [])],
    });
  }

  const activeUsersCount = users.filter(u => u.is_active).length;
  const customRolesCount = roles.filter(r => !r.is_system).length;

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-brand-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-brand-500/20 text-white">
            <FaUsers className="text-xl" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">
              {t('users.title') || 'Access & User Management'}
            </h1>
            <p className="text-xs sm:text-sm text-white/55">
              Manage team accounts, granular role permissions, and administrative audit trails
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {activeTab === 'users' && (
            <button
              onClick={() => setShowCreateUser(true)}
              className="px-4 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-400 text-white text-sm font-semibold flex items-center gap-2 shadow-lg shadow-brand-500/25 transition-all"
            >
              <FaPlus className="text-xs" />
              <span>Add User</span>
            </button>
          )}
          {activeTab === 'roles' && (
            <button
              onClick={() => setShowCreateRole(true)}
              className="px-4 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-400 text-white text-sm font-semibold flex items-center gap-2 shadow-lg shadow-brand-500/25 transition-all"
            >
              <FaPlus className="text-xs" />
              <span>New Custom Role</span>
            </button>
          )}
        </div>
      </div>

      {/* KPI Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="glassmorphism rounded-2xl p-4 border border-white/10">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-white/50 uppercase tracking-wider">Total Users</span>
            <div className="w-8 h-8 rounded-lg bg-brand-500/15 text-brand-400 flex items-center justify-center">
              <FaUsers className="text-sm" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-white tabular-nums">{users.length}</span>
            <span className="text-xs text-emerald-400">{activeUsersCount} active</span>
          </div>
        </div>

        <div className="glassmorphism rounded-2xl p-4 border border-white/10">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-white/50 uppercase tracking-wider">Configured Roles</span>
            <div className="w-8 h-8 rounded-lg bg-purple-500/15 text-purple-400 flex items-center justify-center">
              <FaUserShield className="text-sm" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-white tabular-nums">{roles.length}</span>
            <span className="text-xs text-purple-300">
              {roles.length - customRolesCount} system · {customRolesCount} custom
            </span>
          </div>
        </div>

        <div className="glassmorphism rounded-2xl p-4 border border-white/10">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-white/50 uppercase tracking-wider">Permission Scopes</span>
            <div className="w-8 h-8 rounded-lg bg-amber-500/15 text-amber-400 flex items-center justify-center">
              <FaKey className="text-sm" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-white tabular-nums">{totalPermissionsCount}</span>
            <span className="text-xs text-white/45">{Object.keys(permissions).length} categories</span>
          </div>
        </div>

        <div className="glassmorphism rounded-2xl p-4 border border-white/10">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-white/50 uppercase tracking-wider">Audit Events</span>
            <div className="w-8 h-8 rounded-lg bg-cyan-500/15 text-cyan-400 flex items-center justify-center">
              <FaHistory className="text-sm" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-white tabular-nums">{auditLogs.length}</span>
            <span className="text-xs text-white/45">recent entries</span>
          </div>
        </div>
      </div>

      {/* Segmented Navigation Bar */}
      <div className="flex items-center gap-1.5 p-1.5 rounded-2xl bg-white/5 border border-white/10 w-fit max-w-full overflow-x-auto">
        {[
          { id: 'users', label: 'Team Members', icon: FaUsers, badge: users.length },
          { id: 'roles', label: 'Roles & Permissions', icon: FaUserShield, badge: roles.length },
          { id: 'audit', label: 'Audit Trail', icon: FaHistory, badge: auditLogs.length },
        ].map(tab => {
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
              <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-semibold tabular-nums ${
                active ? 'bg-white/20 text-white' : 'bg-white/10 text-white/60'
              }`}>
                {tab.badge}
              </span>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="bg-red-500/15 border border-red-500/30 text-red-200 p-4 rounded-xl text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={loadUsers} className="text-xs underline hover:text-white">Retry</button>
        </div>
      )}

      {/* ======================== USERS TAB ======================== */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          {/* Search & Filter Toolbar */}
          <div className="glassmorphism rounded-2xl p-4 border border-white/10 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1">
              <FaSearch className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
              <input
                type="text"
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="Search by username, email, or role..."
                className="w-full pl-9 pr-4 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-white placeholder-white/35 focus:outline-none focus:border-brand-500"
              />
            </div>
            <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0">
              <button
                type="button"
                onClick={() => setRoleFilter('all')}
                className={`px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition-colors ${
                  roleFilter === 'all'
                    ? 'bg-brand-500 text-white'
                    : 'bg-white/5 text-white/60 hover:text-white hover:bg-white/10'
                }`}
              >
                All Roles ({users.length})
              </button>
              {roles.map(r => (
                <button
                  key={r.name}
                  type="button"
                  onClick={() => setRoleFilter(r.name)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap flex items-center gap-1.5 transition-colors ${
                    roleFilter === r.name
                      ? 'bg-white/15 text-white border border-white/25'
                      : 'bg-white/5 text-white/60 hover:text-white hover:bg-white/10'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: r.color || '#6366f1' }} />
                  <span>{r.display_name}</span>
                  <span className="text-[10px] text-white/40">({userCountByRole[r.name] || 0})</span>
                </button>
              ))}
            </div>
          </div>

          {/* Users List */}
          {loading ? (
            <div className="glassmorphism rounded-2xl p-12 text-center text-white/50 text-sm">
              Loading users...
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="glassmorphism rounded-2xl p-12 text-center space-y-2 border border-white/10">
              <FaUsers className="text-3xl text-white/25 mx-auto" />
              <div className="text-white font-medium text-sm">No matching users found</div>
              <p className="text-xs text-white/45">Try adjusting your search or role filter.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              {filteredUsers.map(u => {
                const roleObj = roles.find(r => r.name === u.role);
                const roleColor = u.role_info?.color || roleObj?.color || '#6366f1';
                const roleLabel = u.role_info?.display_name || roleObj?.display_name || u.role;
                const isSelf = u.id === currentUser?.id;

                return (
                  <div
                    key={u.id}
                    className="glassmorphism rounded-2xl p-4 border border-white/10 hover:border-white/20 transition-all flex flex-col justify-between gap-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3.5 min-w-0">
                        <div
                          className="w-11 h-11 rounded-xl flex items-center justify-center text-white font-bold text-sm flex-shrink-0 shadow-inner"
                          style={{
                            backgroundColor: `${roleColor}28`,
                            border: `1px solid ${roleColor}66`,
                            color: roleColor,
                          }}
                        >
                          {(u.username || 'U').slice(0, 2).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-white truncate">{u.username}</span>
                            {isSelf && (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-brand-500/20 text-brand-300 border border-brand-500/30">
                                You
                              </span>
                            )}
                            <span
                              className="px-2.5 py-0.5 rounded-full text-[11px] font-medium inline-flex items-center gap-1.5"
                              style={{
                                backgroundColor: `${roleColor}20`,
                                color: roleColor,
                                border: `1px solid ${roleColor}40`,
                              }}
                            >
                              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: roleColor }} />
                              {roleLabel}
                            </span>
                          </div>
                          {u.full_name && (
                            <div className="text-xs text-white/65 truncate mt-0.5">{u.full_name}</div>
                          )}
                          <div className="text-xs text-white/45 flex items-center gap-1.5 truncate mt-1">
                            <FaEnvelope className="text-[10px] flex-shrink-0" />
                            <span className="truncate">{u.email}</span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <button
                          onClick={() => setShowEditUser(u)}
                          className="p-2 rounded-lg bg-white/5 hover:bg-white/15 text-white/75 hover:text-white transition-colors"
                          title="Edit user"
                        >
                          <FaEdit className="text-xs" />
                        </button>
                        {!isSelf && (
                          <button
                            onClick={() => deleteUser(u.id, u.username)}
                            className="p-2 rounded-lg bg-red-500/10 hover:bg-red-500/25 text-red-300 transition-colors"
                            title="Delete user"
                          >
                            <FaTrash className="text-xs" />
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="pt-3 border-t border-white/10 flex items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-2 flex-wrap">
                        {u.is_active ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300">
                            <FaCheck className="text-[9px]" /> Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-red-500/15 text-red-300">
                            <FaTimes className="text-[9px]" /> Disabled
                          </span>
                        )}
                        {u.must_change_password && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-300">
                            <FaKey className="text-[9px]" /> Password Reset Pending
                          </span>
                        )}
                      </div>
                      <div className="text-white/40 tabular-nums">
                        Last login: <span className="text-white/65">{formatRelativeDate(u.last_login)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ======================== ROLES & PERMISSIONS TAB ======================== */}
      {activeTab === 'roles' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
          {/* Left Column: Role Selector List */}
          <div className="lg:col-span-4 space-y-2.5">
            <div className="px-1 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-white/45">
                Available Roles ({roles.length})
              </span>
              <button
                type="button"
                onClick={() => setShowCreateRole(true)}
                className="text-xs text-brand-400 hover:text-brand-300 font-medium flex items-center gap-1"
              >
                <FaPlus className="text-[10px]" /> Create Role
              </button>
            </div>

            {roles.map(role => {
              const isSelected = selectedRole?.name === role.name;
              const permCount = (role.permissions || []).length;
              const coveragePct = totalPermissionsCount > 0
                ? Math.min(100, Math.round((permCount / totalPermissionsCount) * 100))
                : 0;
              const assignedCount = userCountByRole[role.name] || 0;

              return (
                <button
                  key={role.name}
                  type="button"
                  onClick={() => setSelectedRoleKey(role.name)}
                  className={`w-full text-left p-4 rounded-2xl transition-all border ${
                    isSelected
                      ? 'bg-white/10 border-brand-500/60 shadow-lg shadow-brand-500/10'
                      : 'glassmorphism border-white/10 hover:border-white/25 hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span
                        className="w-3.5 h-3.5 rounded-full flex-shrink-0 ring-4"
                        style={{
                          backgroundColor: role.color || '#6366f1',
                           '--tw-ring-color': `${role.color || '#6366f1'}30`,
                        }}
                      />
                      <span className="font-semibold text-white truncate">{role.display_name}</span>
                    </div>
                    <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider flex-shrink-0 ${
                      role.is_system
                        ? 'bg-white/10 text-white/60'
                        : 'bg-brand-500/20 text-brand-300 border border-brand-500/30'
                    }`}>
                      {role.is_system ? 'System' : 'Custom'}
                    </span>
                  </div>

                  <p className="text-xs text-white/50 line-clamp-2 mt-1.5">
                    {role.description || 'Custom access role'}
                  </p>

                  {/* Permission Coverage Bar */}
                  <div className="mt-3 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-white/45">
                        {permCount} permission{permCount !== 1 ? 's' : ''} ({coveragePct}%)
                      </span>
                      <span className="text-white/60 font-medium">
                        {assignedCount} user{assignedCount !== 1 ? 's' : ''}
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-300"
                        style={{
                          width: `${coveragePct}%`,
                          backgroundColor: role.color || '#6366f1',
                        }}
                      />
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Right Column: Selected Role Inspector & Visual Permission Matrix */}
          <div className="lg:col-span-8">
            {selectedRole ? (
              <div className="glassmorphism rounded-2xl border border-white/10 overflow-hidden">
                {/* Role Banner Header */}
                <div
                  className="p-5 sm:p-6 border-b border-white/10"
                  style={{
                    background: `linear-gradient(135deg, ${(selectedRole.color || '#6366f1')}22 0%, rgba(15, 23, 42, 0.4) 100%)`,
                  }}
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="flex items-start gap-3.5">
                      <div
                        className="w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0 shadow-lg"
                        style={{
                          backgroundColor: `${selectedRole.color || '#6366f1'}30`,
                          border: `1px solid ${selectedRole.color || '#6366f1'}66`,
                          color: selectedRole.color || '#6366f1',
                        }}
                      >
                        <FaShieldAlt className="text-xl" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2.5 flex-wrap">
                          <h2 className="text-xl font-bold text-white">{selectedRole.display_name}</h2>
                          <span className="font-mono text-xs px-2 py-0.5 rounded bg-black/30 text-white/55 border border-white/10">
                            {selectedRole.name}
                          </span>
                          {selectedRole.is_system && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-white/10 text-white/70">
                              <FaLock className="text-[9px]" /> Built-in System Role
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-white/65 mt-1">
                          {selectedRole.description || 'No description provided.'}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        type="button"
                        onClick={() => cloneRoleAsCustom(selectedRole)}
                        className="px-3 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-white text-xs font-medium flex items-center gap-1.5 transition-colors"
                        title="Duplicate this role as a customizable role"
                      >
                        <FaCopy className="text-[11px]" />
                        <span>Duplicate as Custom</span>
                      </button>
                      {!selectedRole.is_system && (
                        <>
                          <button
                            type="button"
                            onClick={() => setShowEditRole(selectedRole)}
                            className="px-3.5 py-2 rounded-xl bg-brand-500 hover:bg-brand-400 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors"
                          >
                            <FaEdit className="text-[11px]" />
                            <span>Edit Role</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteRole(selectedRole.id, selectedRole.display_name)}
                            className="p-2 rounded-xl bg-red-500/15 hover:bg-red-500/30 text-red-300 transition-colors"
                            title="Delete custom role"
                          >
                            <FaTrash className="text-xs" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {/* Permission Filter Bar */}
                <div className="px-5 py-3.5 bg-white/[0.02] border-b border-white/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="text-xs text-white/60">
                    Showing <span className="text-white font-semibold">{(selectedRole.permissions || []).length}</span> granted permissions out of <span className="text-white font-semibold">{totalPermissionsCount}</span> total scopes
                  </div>
                  <div className="relative w-full sm:w-64">
                    <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
                    <input
                      type="text"
                      value={permSearch}
                      onChange={(e) => setPermSearch(e.target.value)}
                      placeholder="Filter permissions..."
                      className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-white placeholder-white/35 focus:outline-none focus:border-brand-500"
                    />
                  </div>
                </div>

                {/* Categorized Permission Matrix */}
                <div className="p-5 space-y-5 max-h-[640px] overflow-y-auto">
                  {Object.entries(permissions).map(([category, perms]) => {
                    const q = permSearch.trim().toLowerCase();
                    const filteredPerms = (Array.isArray(perms) ? perms : []).filter(p =>
                      !q ||
                      p.name.toLowerCase().includes(q) ||
                      (p.description && p.description.toLowerCase().includes(q)) ||
                      category.toLowerCase().includes(q)
                    );
                    if (filteredPerms.length === 0) return null;

                    const grantedInCat = filteredPerms.filter(p => (selectedRole.permissions || []).includes(p.name)).length;
                    const meta = getCategoryMeta(category);
                    const CatIcon = meta.icon;

                    return (
                      <div key={category} className="rounded-xl bg-white/[0.03] border border-white/10 p-4">
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2.5">
                            <div className={`w-7 h-7 rounded-lg ${meta.bg} ${meta.accent} flex items-center justify-center`}>
                              <CatIcon className="text-xs" />
                            </div>
                            <h4 className="text-xs font-bold uppercase tracking-wider text-white">
                              {category}
                            </h4>
                          </div>
                          <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            grantedInCat === filteredPerms.length
                              ? 'bg-emerald-500/15 text-emerald-300'
                              : grantedInCat > 0
                                ? 'bg-brand-500/15 text-brand-300'
                                : 'bg-white/5 text-white/40'
                          }`}>
                            {grantedInCat} / {filteredPerms.length} granted
                          </span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {filteredPerms.map(perm => {
                            const hasPerm = (selectedRole.permissions || []).includes(perm.name);
                            return (
                              <div
                                key={perm.name}
                                className={`flex items-start gap-2.5 p-2.5 rounded-lg border text-xs transition-colors ${
                                  hasPerm
                                    ? 'bg-emerald-500/[0.08] border-emerald-500/25 text-white'
                                    : 'bg-black/20 border-white/5 text-white/35'
                                }`}
                              >
                                <div className={`w-4 h-4 rounded flex items-center justify-center flex-shrink-0 mt-0.5 ${
                                  hasPerm ? 'bg-emerald-500/25 text-emerald-400' : 'bg-white/5 text-white/25'
                                }`}>
                                  {hasPerm ? <FaCheck className="text-[9px]" /> : <FaTimes className="text-[9px]" />}
                                </div>
                                <div className="min-w-0">
                                  <div className={`font-medium leading-snug ${hasPerm ? 'text-white' : 'text-white/45'}`}>
                                    {perm.description || perm.name}
                                  </div>
                                  <div className="font-mono text-[10px] text-white/35 truncate mt-0.5">
                                    {perm.name}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="glassmorphism rounded-2xl p-12 text-center text-white/40">
                Select a role on the left to inspect its permissions.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ======================== AUDIT LOGS TAB ======================== */}
      {activeTab === 'audit' && (
        <div className="glassmorphism rounded-2xl border border-white/10 overflow-hidden">
          <div className="p-4 sm:p-5 border-b border-white/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-white">Administrative Audit Trail</h3>
              <p className="text-xs text-white/50">Chronological record of user, role, and authentication events</p>
            </div>
            <div className="relative w-full sm:w-72">
              <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/35 text-xs" />
              <input
                type="text"
                value={auditSearch}
                onChange={(e) => setAuditSearch(e.target.value)}
                placeholder="Search action, user, or IP..."
                className="w-full pl-8 pr-3 py-2 rounded-xl bg-white/5 border border-white/10 text-xs text-white placeholder-white/35 focus:outline-none focus:border-brand-500"
              />
            </div>
          </div>

          <div className="divide-y divide-white/10 max-h-[600px] overflow-y-auto">
            {filteredAuditLogs.length === 0 ? (
              <div className="p-12 text-center text-white/40 text-sm">
                No audit log events match your filter.
              </div>
            ) : (
              filteredAuditLogs.map(log => {
                const actionLower = (log.action || '').toLowerCase();
                const isDanger = actionLower.includes('delete') || actionLower.includes('fail') || actionLower.includes('disable');
                const isCreate = actionLower.includes('create') || actionLower.includes('enable');

                return (
                  <div key={log.id} className="p-4 hover:bg-white/[0.03] transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-start gap-3">
                      <span className={`px-2.5 py-1 rounded-lg text-xs font-mono font-medium flex-shrink-0 ${
                        isDanger
                          ? 'bg-red-500/15 text-red-300 border border-red-500/30'
                          : isCreate
                            ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                            : 'bg-brand-500/15 text-brand-300 border border-brand-500/30'
                      }`}>
                        {log.action}
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm text-white">
                          Executed by <span className="font-semibold text-brand-300">{log.username || 'System'}</span>
                          {log.ip_address && (
                            <span className="ml-2 font-mono text-xs px-2 py-0.5 rounded bg-white/5 text-white/50">
                              {log.ip_address}
                            </span>
                          )}
                        </div>
                        {log.details && Object.keys(log.details).length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mt-1.5">
                            {Object.entries(log.details).map(([k, v]) => (
                              <span key={k} className="text-[11px] px-2 py-0.5 rounded bg-white/5 text-white/60 font-mono">
                                {k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="text-xs text-white/45 tabular-nums flex-shrink-0">
                      {new Date(log.timestamp).toLocaleString()}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Create User Modal */}
      {showCreateUser && (
        <CreateUserModal
          roles={roles}
          onClose={() => setShowCreateUser(false)}
          onSuccess={() => {
            setShowCreateUser(false);
            loadUsers();
            loadAuditLogs();
          }}
        />
      )}

      {/* Edit User Modal */}
      {showEditUser && (
        <EditUserModal
          user={showEditUser}
          roles={roles}
          onClose={() => setShowEditUser(null)}
          onSuccess={() => {
            setShowEditUser(null);
            loadUsers();
            loadAuditLogs();
          }}
        />
      )}

      {/* Create / Clone Role Modal */}
      {showCreateRole && (
        <CreateRoleModal
          initialData={typeof showCreateRole === 'object' ? showCreateRole : null}
          permissions={permissions}
          onClose={() => setShowCreateRole(false)}
          onSuccess={(newRoleName) => {
            setShowCreateRole(false);
            loadRoles();
            loadAuditLogs();
            if (newRoleName) setSelectedRoleKey(newRoleName);
          }}
        />
      )}

      {/* Edit Role Modal */}
      {showEditRole && (
        <EditRoleModal
          role={showEditRole}
          permissions={permissions}
          onClose={() => setShowEditRole(null)}
          onSuccess={() => {
            setShowEditRole(null);
            loadRoles();
            loadAuditLogs();
          }}
        />
      )}
    </div>
  );
}

function CreateUserModal({ roles, onClose, onSuccess }) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState('user');
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          username,
          email,
          password,
          full_name: fullName || null,
          role,
          must_change_password: mustChangePassword,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to create user');
      }
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/65 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
      <div className="bg-[#141827] border border-white/15 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold text-white">Create Team Member</h3>
          <button onClick={onClose} className="p-1.5 text-white/50 hover:text-white rounded-lg">
            <FaTimes />
          </button>
        </div>

        {error && <div className="bg-red-500/20 border border-red-500/40 text-red-200 p-3 rounded-xl text-xs">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-3.5">
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Username *</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              required
              minLength={3}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Email *</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              required
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Password * (min 8 chars)</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              required
              minLength={8}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Full Name</label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Assigned Role *</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-xl bg-[#1c2237] border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
            >
              {roles.map((r) => (
                <option key={r.name} value={r.name}>{r.display_name}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2.5 text-xs text-white/75 pt-1 cursor-pointer">
            <input
              type="checkbox"
              checked={mustChangePassword}
              onChange={(e) => setMustChangePassword(e.target.checked)}
              className="rounded border-white/20"
            />
            <span>Require user to change password on first login</span>
          </label>
          <div className="flex gap-2.5 justify-end pt-3 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-medium text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-400 text-xs font-semibold text-white disabled:opacity-50"
            >
              {loading ? 'Creating...' : 'Create User'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditUserModal({ user, roles, onClose, onSuccess }) {
  const [email, setEmail] = useState(user.email);
  const [fullName, setFullName] = useState(user.full_name || '');
  const [role, setRole] = useState(user.role);
  const [isActive, setIsActive] = useState(user.is_active);
  const [newPassword, setNewPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const body = {
        email,
        full_name: fullName || null,
        role,
        is_active: isActive,
      };
      if (newPassword) body.password = newPassword;

      const r = await fetch(`${API}/users/${user.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update user');
      }
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/65 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
      <div className="bg-[#141827] border border-white/15 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold text-white">Edit User: {user.username}</h3>
          <button onClick={onClose} className="p-1.5 text-white/50 hover:text-white rounded-lg">
            <FaTimes />
          </button>
        </div>

        {error && <div className="bg-red-500/20 border border-red-500/40 text-red-200 p-3 rounded-xl text-xs">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-3.5">
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              required
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Full Name</label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-xl bg-[#1c2237] border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
            >
              {roles.map((r) => (
                <option key={r.name} value={r.name}>{r.display_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">New Password (leave blank to keep current)</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              minLength={8}
              placeholder="••••••••"
            />
          </div>
          <label className="flex items-center gap-2.5 text-xs text-white/75 pt-1 cursor-pointer">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="rounded border-white/20"
            />
            <span>Account is Active</span>
          </label>
          <div className="flex gap-2.5 justify-end pt-3 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-medium text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-400 text-xs font-semibold text-white disabled:opacity-50"
            >
              {loading ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function CreateRoleModal({ initialData, permissions, onClose, onSuccess }) {
  const [name, setName] = useState(initialData?.name || '');
  const [displayName, setDisplayName] = useState(initialData?.display_name || '');
  const [description, setDescription] = useState(initialData?.description || '');
  const [color, setColor] = useState(initialData?.color || '#6366f1');
  const [selectedPerms, setSelectedPerms] = useState(initialData?.permissions || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  function togglePerm(perm) {
    setSelectedPerms(prev =>
      prev.includes(perm) ? prev.filter(p => p !== perm) : [...prev, perm]
    );
  }

  function toggleCategory(permsInCat) {
    const names = permsInCat.map(p => p.name);
    const allSelected = names.every(n => selectedPerms.includes(n));
    if (allSelected) {
      setSelectedPerms(prev => prev.filter(p => !names.includes(p)));
    } else {
      setSelectedPerms(prev => Array.from(new Set([...prev, ...names])));
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const slug = name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '_');
      const r = await fetch(`${API}/users/roles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          name: slug,
          display_name: displayName,
          description,
          color,
          permissions: selectedPerms,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to create role');
      }
      onSuccess(slug);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/65 backdrop-blur-sm flex items-center justify-center p-4 z-50 overflow-y-auto animate-fade-in">
      <div className="bg-[#141827] border border-white/15 rounded-2xl max-w-3xl w-full p-6 space-y-5 my-8 shadow-2xl">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-white">Create Custom Role</h3>
            <p className="text-xs text-white/50">Define a tailored permission profile for your team</p>
          </div>
          <button onClick={onClose} className="p-1.5 text-white/50 hover:text-white rounded-lg">
            <FaTimes />
          </button>
        </div>

        {error && <div className="bg-red-500/20 border border-red-500/40 text-red-200 p-3 rounded-xl text-xs">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-white/70 block mb-1">Display Name *</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => {
                  setDisplayName(e.target.value);
                  if (!initialData) {
                    setName(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''));
                  }
                }}
                placeholder="e.g. Junior Moderator"
                className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
                required
              />
            </div>
            <div>
              <label className="text-xs font-medium text-white/70 block mb-1">Role Identifier (slug) *</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="junior_moderator"
                className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm font-mono text-white focus:outline-none focus:border-brand-500"
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-center">
            <div>
              <label className="text-xs font-medium text-white/70 block mb-1">Description</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this role responsible for?"
                className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-white/70 block mb-1.5">Badge Color</label>
              <div className="flex items-center gap-2 flex-wrap">
                {ROLE_COLOR_PRESETS.map(preset => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setColor(preset)}
                    className={`w-6 h-6 rounded-full transition-transform ${color === preset ? 'scale-125 ring-2 ring-white' : 'opacity-70 hover:opacity-100'}`}
                    style={{ backgroundColor: preset }}
                  />
                ))}
                <input
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="w-7 h-7 rounded cursor-pointer bg-transparent border-0"
                />
              </div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-white/60">
                Permissions ({selectedPerms.length} selected)
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedPerms(Object.values(permissions).flat().map(p => p.name))}
                  className="text-xs text-brand-400 hover:text-brand-300"
                >
                  Select All
                </button>
                <span className="text-white/20">·</span>
                <button
                  type="button"
                  onClick={() => setSelectedPerms([])}
                  className="text-xs text-white/50 hover:text-white"
                >
                  Clear All
                </button>
              </div>
            </div>

            <div className="space-y-3 max-h-80 overflow-y-auto bg-black/30 border border-white/10 p-3.5 rounded-xl">
              {Object.entries(permissions).map(([category, perms]) => {
                const list = Array.isArray(perms) ? perms : [];
                const allInCat = list.every(p => selectedPerms.includes(p.name));
                return (
                  <div key={category} className="rounded-xl bg-white/[0.03] border border-white/10 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-bold uppercase tracking-wider text-brand-300">{category}</span>
                      <button
                        type="button"
                        onClick={() => toggleCategory(list)}
                        className="text-[11px] text-white/55 hover:text-white"
                      >
                        {allInCat ? 'Deselect category' : 'Select category'}
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {list.map((perm) => {
                        const checked = selectedPerms.includes(perm.name);
                        return (
                          <label
                            key={perm.name}
                            className={`flex items-start gap-2.5 p-2 rounded-lg border text-xs cursor-pointer transition-colors ${
                              checked
                                ? 'bg-brand-500/15 border-brand-500/40 text-white'
                                : 'bg-white/[0.02] border-white/5 text-white/60 hover:bg-white/5'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => togglePerm(perm.name)}
                              className="mt-0.5 rounded"
                            />
                            <div className="min-w-0">
                              <div className="font-medium leading-tight">{perm.description}</div>
                              <div className="font-mono text-[10px] text-white/40 truncate">{perm.name}</div>
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

          <div className="flex gap-2.5 justify-end pt-3 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-medium text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-400 text-xs font-semibold text-white disabled:opacity-50"
            >
              {loading ? 'Creating...' : 'Create Role'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditRoleModal({ role, permissions, onClose, onSuccess }) {
  const [displayName, setDisplayName] = useState(role.display_name);
  const [description, setDescription] = useState(role.description || '');
  const [color, setColor] = useState(role.color || '#6366f1');
  const [selectedPerms, setSelectedPerms] = useState(role.permissions || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  function togglePerm(perm) {
    setSelectedPerms(prev =>
      prev.includes(perm) ? prev.filter(p => p !== perm) : [...prev, perm]
    );
  }

  function toggleCategory(permsInCat) {
    const names = permsInCat.map(p => p.name);
    const allSelected = names.every(n => selectedPerms.includes(n));
    if (allSelected) {
      setSelectedPerms(prev => prev.filter(p => !names.includes(p)));
    } else {
      setSelectedPerms(prev => Array.from(new Set([...prev, ...names])));
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/users/roles/${role.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          display_name: displayName,
          description,
          color,
          permissions: selectedPerms,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update role');
      }
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/65 backdrop-blur-sm flex items-center justify-center p-4 z-50 overflow-y-auto animate-fade-in">
      <div className="bg-[#141827] border border-white/15 rounded-2xl max-w-3xl w-full p-6 space-y-5 my-8 shadow-2xl">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-white">Edit Role: {role.display_name}</h3>
            <p className="text-xs text-white/50">Update role appearance and assigned permissions</p>
          </div>
          <button onClick={onClose} className="p-1.5 text-white/50 hover:text-white rounded-lg">
            <FaTimes />
          </button>
        </div>

        {error && <div className="bg-red-500/20 border border-red-500/40 text-red-200 p-3 rounded-xl text-xs">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-center">
            <div>
              <label className="text-xs font-medium text-white/70 block mb-1">Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
                required
              />
            </div>
            <div>
              <label className="text-xs font-medium text-white/70 block mb-1.5">Badge Color</label>
              <div className="flex items-center gap-2 flex-wrap">
                {ROLE_COLOR_PRESETS.map(preset => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setColor(preset)}
                    className={`w-6 h-6 rounded-full transition-transform ${color === preset ? 'scale-125 ring-2 ring-white' : 'opacity-70 hover:opacity-100'}`}
                    style={{ backgroundColor: preset }}
                  />
                ))}
                <input
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="w-7 h-7 rounded cursor-pointer bg-transparent border-0"
                />
              </div>
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-white/70 block mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-xl bg-white/5 border border-white/10 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-white/60">
                Permissions ({selectedPerms.length} selected)
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedPerms(Object.values(permissions).flat().map(p => p.name))}
                  className="text-xs text-brand-400 hover:text-brand-300"
                >
                  Select All
                </button>
                <span className="text-white/20">·</span>
                <button
                  type="button"
                  onClick={() => setSelectedPerms([])}
                  className="text-xs text-white/50 hover:text-white"
                >
                  Clear All
                </button>
              </div>
            </div>

            <div className="space-y-3 max-h-80 overflow-y-auto bg-black/30 border border-white/10 p-3.5 rounded-xl">
              {Object.entries(permissions).map(([category, perms]) => {
                const list = Array.isArray(perms) ? perms : [];
                const allInCat = list.every(p => selectedPerms.includes(p.name));
                return (
                  <div key={category} className="rounded-xl bg-white/[0.03] border border-white/10 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-bold uppercase tracking-wider text-brand-300">{category}</span>
                      <button
                        type="button"
                        onClick={() => toggleCategory(list)}
                        className="text-[11px] text-white/55 hover:text-white"
                      >
                        {allInCat ? 'Deselect category' : 'Select category'}
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {list.map((perm) => {
                        const checked = selectedPerms.includes(perm.name);
                        return (
                          <label
                            key={perm.name}
                            className={`flex items-start gap-2.5 p-2 rounded-lg border text-xs cursor-pointer transition-colors ${
                              checked
                                ? 'bg-brand-500/15 border-brand-500/40 text-white'
                                : 'bg-white/[0.02] border-white/5 text-white/60 hover:bg-white/5'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => togglePerm(perm.name)}
                              className="mt-0.5 rounded"
                            />
                            <div className="min-w-0">
                              <div className="font-medium leading-tight">{perm.description}</div>
                              <div className="font-mono text-[10px] text-white/40 truncate">{perm.name}</div>
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

          <div className="flex gap-2.5 justify-end pt-3 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-medium text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-400 text-xs font-semibold text-white disabled:opacity-50"
            >
              {loading ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
