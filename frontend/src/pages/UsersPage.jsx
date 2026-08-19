import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '../i18n';
import { useGlobalData, useGlobalActions } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import {
  FaShieldAlt,
  FaPlus,
  FaTimes,
  FaUsers,
  FaHistory,
  FaCheckCircle,
  FaExclamationTriangle,
  FaSearch,
  FaEye,
  FaTrash,
  FaUserCheck,
  FaUserSlash,
  FaKey,
  FaEnvelope,
  FaUser,
  FaEdit,
  FaLock,
  FaSave,
  FaSpinner,
  FaCog,
  FaBan,
  FaUserPlus,
  FaUserMinus,
} from 'react-icons/fa';

async function parseError(resp) {
  try {
    const payload = await resp.json();
    if (payload && payload.detail) {
      if (Array.isArray(payload.detail)) {
        return payload.detail.map(err => {
          const field = err.loc ? err.loc.join('.') : '';
          return `${field ? field + ': ' : ''}${err.msg}`;
        }).join(', ');
      }
      return payload.detail;
    }
  } catch (_) {}
  return `HTTP ${resp.status}`;
}

const SYSTEM_ROLES = ['owner', 'admin', 'moderator', 'helper', 'user', 'guest'];

function RoleBadge({ role, roles }) {
  const roleData = roles.find(r => r.name === role);
  const color = roleData?.color || '#6b7280';
  const isSystem = SYSTEM_ROLES.includes(role);
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium" style={{ color }}>
      {role}
      {isSystem && <span className="bg-blue-500/20 text-blue-300 px-1 rounded">SYS</span>}
    </span>
  );
}

export default function UsersPage() {
  const { t } = useTranslation();
  const globalData = useGlobalData();
  const { showToast } = useToast();

  const safeUsers = Array.isArray(globalData.users) ? globalData.users : [];
  const safeRoles = Array.isArray(globalData.roles) ? globalData.roles : [];
  const safeAuditLogs = Array.isArray(globalData.auditLogs) ? globalData.auditLogs : [];

  const [searchTerm, setSearchTerm] = useState('');
  const [filterRole, setFilterRole] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [activeTab, setActiveTab] = useState('users');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Create User modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newUser, setNewUser] = useState({
    username: '', email: '', password: '', confirmPassword: '',
    role: 'user', mustChangePassword: true,
  });
  const [creating, setCreating] = useState(false);

  // Edit User modal
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [editForm, setEditForm] = useState({
    email: '', password: '', confirmPassword: '', role: '', full_name: '', is_active: true,
  });
  const [editing, setEditing] = useState(false);

  // Create Role modal
  const [showCreateRoleModal, setShowCreateRoleModal] = useState(false);
  const [newRole, setNewRole] = useState({ name: '', description: '', permissions: [] });
  const [creatingRole, setCreatingRole] = useState(false);

  // Edit Role modal
  const [showEditRoleModal, setShowEditRoleModal] = useState(false);
  const [editingRole, setEditingRole] = useState(null);
  const [editRoleForm, setEditRoleForm] = useState({ description: '', permissions: [] });
  const [editingRolePerms, setEditingRolePerms] = useState(false);

  // Delete confirmations
  const [deleteConfirm, setDeleteConfirm] = useState(null); // { type: 'user'|'role', item }

  // Load data
  const { __refreshBG } = useGlobalActions();
  const loadData = useCallback(() => {
    __refreshBG('users', `${API}/users`, (d) => d.users || []);
    __refreshBG('roles', `${API}/users/roles`, (d) => d.roles || []);
    __refreshBG('auditLogs', `${API}/users/audit-logs?page=1&page_size=50`, (d) => d.logs || []);
  }, [__refreshBG]);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 15000);
    return () => clearInterval(id);
  }, [loadData]);

  const filteredUsers = safeUsers.filter(user => {
    const matchesSearch = user.username?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      user.email?.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = filterRole === 'all' || user.role === filterRole;
    const matchesStatus = filterStatus === 'all' ||
      (filterStatus === 'active' && user.is_active) ||
      (filterStatus === 'inactive' && !user.is_active);
    return matchesSearch && matchesRole && matchesStatus;
  });

  // --- User Actions ---
  const toggleUserActive = async (userId, isActive) => {
    try {
      const resp = await fetch(`${API}/users/${userId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: isActive }),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      showToast('success', `User ${isActive ? 'activated' : 'deactivated'}`);
      loadData();
    } catch (e) {
      showToast('error', 'Failed to update user: ' + e.message);
    }
  };

  const deleteUser = async (userId) => {
    try {
      const resp = await fetch(`${API}/users/${userId}`, { method: 'DELETE', headers: authHeaders() });
      if (!resp.ok) throw new Error(await parseError(resp));
      showToast('success', 'User deleted');
      loadData();
    } catch (e) {
      showToast('error', 'Failed to delete user: ' + e.message);
    }
  };

  const openEditUser = (user) => {
    setEditingUser(user);
    setEditForm({
      email: user.email || '',
      password: '',
      confirmPassword: '',
      role: user.role,
      full_name: user.full_name || '',
      is_active: user.is_active,
    });
    setShowEditModal(true);
  };

  const submitEditUser = async () => {
    if (editForm.password && editForm.password.length < 8) {
      showToast('error', 'Password must be at least 8 characters');
      return;
    }
    if (editForm.password !== editForm.confirmPassword) {
      showToast('error', 'Passwords do not match');
      return;
    }
    setEditing(true);
    try {
      const updates = {};
      if (editForm.email !== editingUser.email) updates.email = editForm.email;
      if (editForm.role !== editingUser.role) updates.role = editForm.role;
      if (editForm.full_name !== editingUser.full_name) updates.full_name = editForm.full_name;
      if (editForm.is_active !== editingUser.is_active) updates.is_active = editForm.is_active;
      if (editForm.password) updates.password = editForm.password;

      if (Object.keys(updates).length === 0) {
        showToast('info', 'No changes made');
        setShowEditModal(false);
        return;
      }

      const resp = await fetch(`${API}/users/${editingUser.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(updates),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      showToast('success', 'User updated');
      setShowEditModal(false);
      setEditingUser(null);
      loadData();
    } catch (e) {
      showToast('error', 'Failed to update user: ' + e.message);
    } finally {
      setEditing(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setCreating(true);
    setError('');
    try {
      if (!newUser.username.trim() || !newUser.email.trim()) throw new Error('Username and email are required');
      if (!newUser.password) throw new Error('Password is required');
      if (newUser.password.length < 8) throw new Error('Password must be at least 8 characters');
      if (newUser.password !== newUser.confirmPassword) throw new Error('Passwords do not match');
      const resp = await fetch(`${API}/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          username: newUser.username,
          email: newUser.email,
          password: newUser.password,
          role: newUser.role,
          full_name: newUser.username,
        }),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      setShowCreateModal(false);
      setNewUser({ username: '', email: '', password: '', confirmPassword: '', role: 'user', mustChangePassword: true });
      showToast('success', 'User created');
      loadData();
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setCreating(false);
    }
  };

  // --- Role Actions ---
  const openCreateRole = () => {
    setNewRole({ name: '', description: '', permissions: [] });
    setShowCreateRoleModal(true);
  };

  const submitCreateRole = async () => {
    if (!newRole.name.trim()) { showToast('error', 'Role name is required'); return; }
    if (!/^[a-z0-9_]+$/.test(newRole.name)) { showToast('error', 'Role name must be lowercase, numbers, underscores only'); return; }
    setCreatingRole(true);
    try {
      const resp = await fetch(`${API}/users/roles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: newRole.name, description: newRole.description, permissions: newRole.permissions }),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      showToast('success', 'Role created');
      setShowCreateRoleModal(false);
      loadData();
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setCreatingRole(false);
    }
  };

  const openEditRole = (role) => {
    setEditingRole(role);
    setEditRoleForm({ description: role.description || '', permissions: role.permissions || [] });
    setShowEditRoleModal(true);
  };

  const submitEditRole = async () => {
    setEditingRolePerms(true);
    try {
      const resp = await fetch(`${API}/users/roles/${editingRole.name}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ description: editRoleForm.description, permissions: editRoleForm.permissions }),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      showToast('success', 'Role updated');
      setShowEditRoleModal(false);
      setEditingRole(null);
      loadData();
    } catch (e) {
      showToast('error', e.message);
    } finally {
      setEditingRolePerms(false);
    }
  };

  const deleteRole = async (roleName) => {
    try {
      const resp = await fetch(`${API}/users/roles/${roleName}`, { method: 'DELETE', headers: authHeaders() });
      if (!resp.ok) throw new Error(await parseError(resp));
      showToast('success', 'Role deleted');
      loadData();
    } catch (e) {
      showToast('error', e.message);
    }
  };

  const confirmDelete = (type, item) => setDeleteConfirm({ type, item });
  const executeDelete = () => {
    if (!deleteConfirm) return;
    if (deleteConfirm.type === 'user') deleteUser(deleteConfirm.item.id);
    else if (deleteConfirm.type === 'role') deleteRole(deleteConfirm.item.name);
    setDeleteConfirm(null);
  };

  // Permissions list for role editing
  const allPermissions = [
    'server.view', 'server.create', 'server.start', 'server.stop', 'server.restart', 'server.kill', 'server.delete', 'server.clone',
    'server.console.view', 'server.console.send', 'server.console.history',
    'server.config.view', 'server.config.edit', 'server.properties.edit', 'server.startup.edit',
    'server.files.view', 'server.files.download', 'server.files.upload', 'server.files.edit', 'server.files.delete', 'server.files.create', 'server.files.compress',
    'server.players.view', 'server.players.kick', 'server.players.ban', 'server.players.whitelist', 'server.players.op', 'server.players.chat',
    'server.backup.view', 'server.backup.create', 'server.backup.restore', 'server.backup.delete', 'server.backup.download', 'server.backup.schedule',
    'user.view', 'user.create', 'user.edit', 'user.delete', 'user.password.reset', 'user.sessions.view', 'user.sessions.revoke',
    'role.view', 'role.create', 'role.edit', 'role.delete', 'role.assign',
    'system.monitoring.view', 'system.logs.view', 'system.audit.view', 'system.settings.view', 'system.settings.edit', 'system.maintenance', 'system.updates',
    'schedule.view', 'schedule.create', 'schedule.edit', 'schedule.delete', 'schedule.execute',
    'plugins.view', 'plugins.install', 'plugins.remove', 'plugins.configure', 'plugins.update',
  ];

  const permissionCategories = {
    server_control: ['server.view', 'server.create', 'server.start', 'server.stop', 'server.restart', 'server.kill', 'server.delete', 'server.clone'],
    server_console: ['server.console.view', 'server.console.send', 'server.console.history'],
    server_config: ['server.config.view', 'server.config.edit', 'server.properties.edit', 'server.startup.edit'],
    server_files: ['server.files.view', 'server.files.download', 'server.files.upload', 'server.files.edit', 'server.files.delete', 'server.files.create', 'server.files.compress'],
    server_players: ['server.players.view', 'server.players.kick', 'server.players.ban', 'server.players.whitelist', 'server.players.op', 'server.players.chat'],
    server_backup: ['server.backup.view', 'server.backup.create', 'server.backup.restore', 'server.backup.delete', 'server.backup.download', 'server.backup.schedule'],
    user_management: ['user.view', 'user.create', 'user.edit', 'user.delete', 'user.password.reset', 'user.sessions.view', 'user.sessions.revoke'],
    role_management: ['role.view', 'role.create', 'role.edit', 'role.delete', 'role.assign'],
    system_admin: ['system.monitoring.view', 'system.logs.view', 'system.audit.view', 'system.settings.view', 'system.settings.edit', 'system.maintenance', 'system.updates'],
    automation: ['schedule.view', 'schedule.create', 'schedule.edit', 'schedule.delete', 'schedule.execute'],
    plugin_management: ['plugins.view', 'plugins.install', 'plugins.remove', 'plugins.configure', 'plugins.update'],
  };

  return (
    <div className="p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <FaShieldAlt className="text-brand-500" />
            <span className="gradient-text-brand">User Management</span>
          </h1>
          <p className="text-white/70 mt-2">Manage users, roles, permissions, and audit logs</p>
        </div>
        <div className="flex items-center gap-3">
          {activeTab === 'users' && (
            <button onClick={() => { setEditingUser(null); setShowCreateModal(true); }} className="bg-brand-500 hover:bg-brand-600 px-4 py-2 rounded-lg flex items-center gap-2">
              <FaUserPlus /> Create User
            </button>
          )}
          {activeTab === 'roles' && (
            <button onClick={openCreateRole} className="bg-brand-500 hover:bg-brand-600 px-4 py-2 rounded-lg flex items-center gap-2">
              <FaPlus /> Create Role
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-300 p-4 rounded-lg flex items-center gap-3">
          <FaExclamationTriangle />
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-auto text-red-400 hover:text-red-300"><FaTimes /></button>
        </div>
      )}
      {success && (
        <div className="bg-green-500/10 border border-green-500/20 text-green-300 p-4 rounded-lg flex items-center gap-3">
          <FaCheckCircle />
          <span>{success}</span>
          <button onClick={() => setSuccess('')} className="ml-auto text-green-400 hover:text-green-300"><FaTimes /></button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-1 flex">
        <button onClick={() => setActiveTab('users')} className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 transition-all ${activeTab === 'users' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}`}>
          <FaUsers /> Users ({safeUsers.length})
        </button>
        <button onClick={() => setActiveTab('roles')} className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 transition-all ${activeTab === 'roles' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}`}>
          <FaShieldAlt /> Roles ({safeRoles.length})
        </button>
        <button onClick={() => setActiveTab('audit')} className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 transition-all ${activeTab === 'audit' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}`}>
          <FaHistory /> Audit Logs ({safeAuditLogs.length})
        </button>
      </div>

      {/* USERS TAB */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          {/* Search and Filters */}
          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="relative">
                <FaSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-white/50" />
                <input type="text" placeholder="Search users..." className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/50" value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
              </div>
              <select value={filterRole} onChange={e => setFilterRole(e.target.value)} className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
                <option value="all">All Roles</option>
                {safeRoles.map(role => <option key={role.name} value={role.name}>{role.name}</option>)}
              </select>
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
                <option value="all">All Status</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
          </div>

          {/* Users Table */}
          <div className="bg-white/5 border border-white/10 rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-white/10">
                  <tr>
                    <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-white/70 uppercase">User</th>
                    <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-white/70 uppercase">Role</th>
                    <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-white/70 uppercase">Status</th>
                    <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-white/70 uppercase">Last Login</th>
                    <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-white/70 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10">
                  {filteredUsers.map((user) => (
                    <tr key={user.id} className="hover:bg-white/5">
                      <td className="px-3 sm:px-6 py-4">
                        <div className="flex items-center">
                          <div className="w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold" style={{ backgroundColor: (safeRoles.find(r => r.name === user.role)?.color || '#6b7280') }}>
                            {user.username?.charAt(0)?.toUpperCase() || '?'}
                          </div>
                          <div className="ml-3">
                            <div className="text-sm font-medium text-white">{user.username || 'Unknown'}</div>
                            <div className="text-sm text-white/60">{user.email || 'No email'}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 sm:px-6 py-4">
                        <RoleBadge role={user.role} roles={safeRoles} />
                      </td>
                      <td className="px-3 sm:px-6 py-4">
                        <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${user.is_active ? 'bg-green-500/20 text-green-300' : 'bg-red-500/20 text-red-300'}`}>
                          {user.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-3 sm:px-6 py-4 text-sm text-white/70">
                        {user.last_login ? new Date(user.last_login).toLocaleString() : 'Never'}
                      </td>
                      <td className="px-3 sm:px-6 py-4">
                        <div className="flex items-center gap-1">
                          <button onClick={() => openEditUser(user)} className="p-2 text-blue-400 hover:bg-blue-500/10 rounded" title="Edit"><FaEdit /></button>
                          <button onClick={() => toggleUserActive(user.id, !user.is_active)} className={`p-2 rounded ${user.is_active ? 'text-red-400 hover:bg-red-500/10' : 'text-green-400 hover:bg-green-500/10'}`} title={user.is_active ? 'Deactivate' : 'Activate'}>
                            {user.is_active ? <FaUserSlash /> : <FaUserCheck />}
                          </button>
                          <button onClick={() => confirmDelete('user', user)} className="p-2 text-red-400 hover:bg-red-500/10 rounded" title="Delete"><FaTrash /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {filteredUsers.length === 0 && (
              <div className="text-center py-12 text-white/60">
                <FaUsers className="text-4xl mx-auto mb-3 text-white/30" />
                <p>No users found</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ROLES TAB */}
      {activeTab === 'roles' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="font-medium text-white">Roles</h3>
            <button onClick={openCreateRole} className="px-3 py-1.5 bg-brand-500 hover:bg-brand-600 rounded text-white text-sm flex items-center gap-2">
              <FaPlus /> Create Role
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {safeRoles.map((role) => (
              <div key={role.name} className="bg-white/5 border border-white/10 rounded-lg p-6 hover:bg-white/10 transition-colors">
                <div className="flex items-center gap-4 mb-4">
                  <div className="w-12 h-12 rounded-lg flex items-center justify-center" style={{ backgroundColor: role.color || '#6b7280' }}>
                    <FaShieldAlt className="text-xl text-white" />
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-lg" style={{ color: role.color || '#ffffff' }}>{role.name}</h3>
                    <p className="text-sm text-white/60">{role.description || 'No description'}</p>
                  </div>
                  {role.is_system && <div className="bg-blue-500/20 text-blue-300 px-2 py-1 rounded text-xs">System</div>}
                </div>
                <div className="space-y-3 mb-4">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-white/70">Permissions</span>
                    <span className="text-sm font-medium text-white">{role.permissions?.length || 0}</span>
                  </div>
                  <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                    {role.permissions?.slice(0, 10).map(p => (
                      <span key={p} className="px-2 py-0.5 bg-white/10 rounded text-xs text-white/70">{p}</span>
                    ))}
                    {(role.permissions?.length || 0) > 10 && <span className="px-2 py-0.5 bg-white/10 rounded text-xs text-white/50">+{(role.permissions?.length || 0) - 10} more</span>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => openEditRole(role)} className="flex-1 py-2 px-4 bg-white/10 hover:bg-white/20 rounded-lg text-sm">Edit</button>
                  {!role.is_system && (
                    <button onClick={() => confirmDelete('role', role)} className="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
                      <FaTrash /> Delete
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {safeRoles.length === 0 && (
            <div className="text-center py-12 text-white/60">
              <FaShieldAlt className="text-4xl mx-auto mb-3 text-white/30" />
              <p>No roles configured</p>
            </div>
          )}
        </div>
      )}

      {/* AUDIT LOGS TAB */}
      {activeTab === 'audit' && (
        <div className="bg-white/5 border border-white/10 rounded-lg p-6">
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {safeAuditLogs.length > 0 ? (
              safeAuditLogs.map((log, idx) => (
                <div key={idx} className="flex items-center gap-4 p-3 bg-white/5 rounded-lg">
                  <div className="w-8 h-8 bg-brand-500/20 rounded-full flex items-center justify-center">
                    <FaHistory className="text-xs text-brand-400" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-medium text-white">{log.action}</span>
                      <span className="text-white/60">by user {log.user_id}</span>
                      <span className="text-xs text-brand-400">{new Date(log.timestamp).toLocaleString()}</span>
                    </div>
                    {log.details && (
                      <div className="text-xs text-white/50 mt-1">
                        {typeof log.details === 'object' ? JSON.stringify(log.details) : log.details}
                      </div>
                    )}
                  </div>
                  <div className="text-xs text-white/40">{log.resource_type && `${log.resource_type}:${log.resource_id}`}</div>
                </div>
              ))
            ) : (
              <div className="text-center py-8 text-white/60">
                <FaHistory className="text-3xl mx-auto mb-2 text-white/30" />
                <p className="text-sm">No audit logs available</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* CREATE USER MODAL */}
      {showCreateModal && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowCreateModal(false)} />
          <form onSubmit={handleCreateUser} className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-white flex items-center gap-2"><FaUserPlus className="text-brand-400" /> Create New User</h2>
              <button type="button" onClick={() => setShowCreateModal(false)} className="text-white/60 hover:text-white"><FaTimes /></button>
            </div>
            <div><label className="block text-sm text-white/70 mb-1">Username</label><div className="relative"><FaUser className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="text" required autoFocus className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="johndoe" value={newUser.username} onChange={e => setNewUser(p => ({ ...p, username: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Email</label><div className="relative"><FaEnvelope className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="email" required className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="john@example.com" value={newUser.email} onChange={e => setNewUser(p => ({ ...p, email: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Password</label><div className="relative"><FaKey className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="password" required minLength={8} className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="Min. 8 chars (A-Z, a-z, 0-9)" value={newUser.password} onChange={e => setNewUser(p => ({ ...p, password: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Confirm Password</label><div className="relative"><FaKey className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="password" required minLength={8} className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="Repeat password" value={newUser.confirmPassword} onChange={e => setNewUser(p => ({ ...p, confirmPassword: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Role</label><select className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white" value={newUser.role} onChange={e => setNewUser(p => ({ ...p, role: e.target.value }))}>{safeRoles.length > 0 ? safeRoles.map(r => <option key={r.name} value={r.name}>{r.name}</option>) : (<><option value="user">user</option><option value="moderator">moderator</option><option value="admin">admin</option></>) }</select></div>
            <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={newUser.mustChangePassword} onChange={e => setNewUser(p => ({ ...p, mustChangePassword: e.target.checked }))} className="accent-brand-500" /><span className="text-sm text-white/70">Must change password on first login</span></label>
            <div className="flex justify-end gap-3 pt-2"><button type="button" onClick={() => setShowCreateModal(false)} className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80">Cancel</button><button type="submit" disabled={creating} className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg text-white flex items-center gap-2">{creating ? 'Creating...' : <><FaPlus /> Create User</>}</button></div>
          </form>
        </div>
      )}

      {/* EDIT USER MODAL */}
      {showEditModal && editingUser && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => { setShowEditModal(false); setEditingUser(null); }} />
          <form onSubmit={submitEditUser} className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-white flex items-center gap-2"><FaEdit className="text-brand-400" /> Edit User: {editingUser.username}</h2>
              <button type="button" onClick={() => { setShowEditModal(false); setEditingUser(null); }} className="text-white/60 hover:text-white"><FaTimes /></button>
            </div>
            <div><label className="block text-sm text-white/70 mb-1">Email</label><div className="relative"><FaEnvelope className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="email" className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" value={editForm.email} onChange={e => setEditForm(p => ({ ...p, email: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Full Name</label><div className="relative"><FaUser className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="text" className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" value={editForm.full_name} onChange={e => setEditForm(p => ({ ...p, full_name: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">New Password (leave blank to keep current)</label><div className="relative"><FaLock className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="password" minLength={8} className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="Min. 8 chars" value={editForm.password} onChange={e => setEditForm(p => ({ ...p, password: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Confirm New Password</label><div className="relative"><FaLock className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" /><input type="password" minLength={8} className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="Repeat password" value={editForm.confirmPassword} onChange={e => setEditForm(p => ({ ...p, confirmPassword: e.target.value }))} /></div></div>
            <div><label className="block text-sm text-white/70 mb-1">Role</label><select className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white" value={editForm.role} onChange={e => setEditForm(p => ({ ...p, role: e.target.value }))}>{safeRoles.map(r => <option key={r.name} value={r.name}>{r.name}</option>)}</select></div>
            <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={editForm.is_active} onChange={e => setEditForm(p => ({ ...p, is_active: e.target.checked }))} className="accent-brand-500" /><span className="text-sm text-white/70">Active</span></label>
            <div className="flex justify-end gap-3 pt-2"><button type="button" onClick={() => { setShowEditModal(false); setEditingUser(null); }} className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80">Cancel</button><button type="submit" disabled={editing} className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg text-white flex items-center gap-2">{editing ? <><FaSpinner className="animate-spin w-4 h-4" /> Saving...</> : <><FaSave /> Save Changes</>}</button></div>
          </form>
        </div>
      )}

      {/* CREATE ROLE MODAL */}
      {showCreateRoleModal && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowCreateRoleModal(false)} />
          <form onSubmit={submitCreateRole} className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4">
            <div className="flex items-center justify-between mb-2 sticky top-0 bg-card/95 backdrop-blur pb-4 border-b border-white/10 z-10">
              <h2 className="text-xl font-bold text-white flex items-center gap-2"><FaPlus className="text-brand-400" /> Create Custom Role</h2>
              <button type="button" onClick={() => setShowCreateRoleModal(false)} className="text-white/60 hover:text-white"><FaTimes /></button>
            </div>
            <div><label className="block text-sm text-white/70 mb-1">Role Name <span className="text-red-400">*</span></label><input type="text" required className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" placeholder="custom_role" value={newRole.name} onChange={e => setNewRole(p => ({ ...p, name: e.target.value }))} /><p className="text-xs text-white/50 mt-1">Lowercase, numbers, underscores only</p></div>
            <div><label className="block text-sm text-white/70 mb-1">Description</label><textarea className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" rows={2} value={newRole.description} onChange={e => setNewRole(p => ({ ...p, description: e.target.value }))} /></div>
            <div><label className="block text-sm text-white/70 mb-1">Permissions</label><div className="max-h-64 overflow-y-auto space-y-3">{Object.entries(permissionCategories).map(([cat, perms]) => (<div key={cat}><h4 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-2">{cat.replace('_', ' ')}</h4><div className="grid grid-cols-2 gap-2">{perms.map(p => (<label key={p} className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={newRole.permissions.includes(p)} onChange={e => setNewRole(prev => ({ ...prev, permissions: e.target.checked ? [...prev.permissions, p] : prev.permissions.filter(x => x !== p) }))} className="accent-brand-500" /><span className="text-xs text-white/70">{p}</span></label>))}</div></div>))}</div></div>
            <div className="flex justify-end gap-3 pt-2"><button type="button" onClick={() => setShowCreateRoleModal(false)} className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80">Cancel</button><button type="submit" disabled={creatingRole} className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg text-white flex items-center gap-2">{creatingRole ? <><FaSpinner className="animate-spin w-4 h-4" /> Creating...</> : <><FaPlus /> Create Role</>}</button></div>
          </form>
        </div>
      )}

      {/* EDIT ROLE MODAL */}
      {showEditRoleModal && editingRole && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => { setShowEditRoleModal(false); setEditingRole(null); }} />
          <form onSubmit={submitEditRole} className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4">
            <div className="flex items-center justify-between mb-2 sticky top-0 bg-card/95 backdrop-blur pb-4 border-b border-white/10 z-10">
              <h2 className="text-xl font-bold text-white flex items-center gap-2"><FaEdit className="text-brand-400" /> Edit Role: {editingRole.name}</h2>
              <button type="button" onClick={() => { setShowEditRoleModal(false); setEditingRole(null); }} className="text-white/60 hover:text-white"><FaTimes /></button>
            </div>
            {editingRole.is_system && <div className="bg-blue-500/20 border border-blue-500/30 text-blue-300 p-3 rounded-lg text-sm">System role - only description and permissions can be modified</div>}
            <div><label className="block text-sm text-white/70 mb-1">Description</label><textarea className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40" rows={2} value={editRoleForm.description} onChange={e => setEditRoleForm(p => ({ ...p, description: e.target.value }))} /></div>
            <div><label className="block text-sm text-white/70 mb-1">Permissions</label><div className="max-h-64 overflow-y-auto space-y-3">{Object.entries(permissionCategories).map(([cat, perms]) => (<div key={cat}><h4 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-2">{cat.replace('_', ' ')}</h4><div className="grid grid-cols-2 gap-2">{perms.map(p => (<label key={p} className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={editRoleForm.permissions.includes(p)} onChange={e => setEditRoleForm(prev => ({ ...prev, permissions: e.target.checked ? [...prev.permissions, p] : prev.permissions.filter(x => x !== p) }))} className="accent-brand-500" /><span className="text-xs text-white/70">{p}</span></label>))}</div></div>))}</div></div>
            <div className="flex justify-end gap-3 pt-2"><button type="button" onClick={() => { setShowEditRoleModal(false); setEditingRole(null); }} className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80">Cancel</button><button type="submit" disabled={editingRolePerms} className="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg text-white flex items-center gap-2">{editingRolePerms ? <><FaSpinner className="animate-spin w-4 h-4" /> Saving...</> : <><FaSave /> Save Changes</>}</button></div>
          </form>
        </div>
      )}

      {/* DELETE CONFIRM MODAL */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setDeleteConfirm(null)} />
          <div className="relative bg-card border border-white/10 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-lg font-bold text-white">Confirm Delete</h3>
            <p className="text-white/70">Are you sure you want to delete {deleteConfirm.type === 'user' ? 'user' : 'role'} <strong>{deleteConfirm.type === 'user' ? deleteConfirm.item.username : deleteConfirm.item.name}</strong>? This action cannot be undone.</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteConfirm(null)} className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white/80">Cancel</button>
              <button onClick={executeDelete} className="px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg text-white flex items-center gap-2"><FaTrash /> Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}