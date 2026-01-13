import React, { useState } from 'react';
import { useTranslation } from '../i18n';
import { useGlobalData } from '../context/GlobalDataContext';
import { API, authHeaders } from '../context/AppContext';
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
  FaUserSlash
} from 'react-icons/fa';

export default function UsersPage() {
  const { t } = useTranslation();
  const globalData = useGlobalData();
  
  const safeUsers = Array.isArray(globalData.users) ? globalData.users : [];
  const safeRoles = Array.isArray(globalData.roles) ? globalData.roles : [];
  const safeAuditLogs = Array.isArray(globalData.auditLogs) ? globalData.auditLogs : [];

  const [searchTerm, setSearchTerm] = useState('');
  const [filterRole, setFilterRole] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [activeTab, setActiveTab] = useState('users');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Refresh user data
  const loadUsers = async () => {
    try {
      const refresher = globalData.__refreshBG;
      if (refresher) {
        refresher('users', `${API}/users`, (d) => d.users || []);
        refresher('roles', `${API}/users/roles`, (d) => d.roles || []);
        refresher('auditLogs', `${API}/users/audit-logs?page=1&page_size=50`, (d) => d.logs || []);
      }
    } catch (error) {
      console.error('Failed to refresh users data:', error);
    }
  };

  // Filtered users
  const filteredUsers = safeUsers.filter(user => {
    const matchesSearch = user.username?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         user.email?.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = filterRole === 'all' || user.role === filterRole;
    const matchesStatus = filterStatus === 'all' || 
                         (filterStatus === 'active' && user.is_active) ||
                         (filterStatus === 'inactive' && !user.is_active);
    return matchesSearch && matchesRole && matchesStatus;
  });

  // User actions
  async function toggleUserActive(userId, isActive) {
    try {
      await fetch(`${API}/users/${userId}`, {
        method: 'PUT', 
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: isActive }),
      });
      setSuccess(`User ${isActive ? 'activated' : 'deactivated'} successfully`);
      loadUsers();
    } catch (e) {
      setError('Failed to update user status: ' + e.message);
    }
  }

  async function deleteUser(userId) {
    if (!window.confirm('Are you sure you want to delete this user? This action cannot be undone.')) return;
    try {
      await fetch(`${API}/users/${userId}`, { method: 'DELETE', headers: authHeaders() });
      setSuccess('User deleted successfully');
      loadUsers();
    } catch (e) {
      setError('Failed to delete user: ' + e.message);
    }
  }

  return (
    <div className="p-4 sm:p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <FaShieldAlt className="text-brand-500" /> 
            <span className="gradient-text-brand">Advanced User Management</span>
          </h1>
          <p className="text-white/70 mt-2">Comprehensive user, role, and permission management system</p>
        </div>
        <div className="flex items-center gap-3">
          <button className="bg-brand-500 hover:bg-brand-600 px-4 py-2 rounded-lg flex items-center gap-2">
            <FaPlus /> Create User
          </button>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-300 p-4 rounded-lg flex items-center gap-3">
          <FaExclamationTriangle />
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-auto text-red-400 hover:text-red-300">
            <FaTimes />
          </button>
        </div>
      )}
      
      {success && (
        <div className="bg-green-500/10 border border-green-500/20 text-green-300 p-4 rounded-lg flex items-center gap-3">
          <FaCheckCircle />
          <span>{success}</span>
          <button onClick={() => setSuccess('')} className="ml-auto text-green-400 hover:text-green-300">
            <FaTimes />
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-1 flex">
        <button
          onClick={() => setActiveTab('users')}
          className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 transition-all ${
            activeTab === 'users' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'
          }`}
        >
          <FaUsers /> Users ({safeUsers.length})
        </button>
        <button
          onClick={() => setActiveTab('roles')}
          className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 transition-all ${
            activeTab === 'roles' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'
          }`}
        >
          <FaShieldAlt /> Roles ({safeRoles.length})
        </button>
        <button
          onClick={() => setActiveTab('audit')}
          className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 transition-all ${
            activeTab === 'audit' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'
          }`}
        >
          <FaHistory /> Audit Logs ({safeAuditLogs.length})
        </button>
      </div>

      {/* Content placeholder */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          {/* Search and Filters */}
          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="relative">
                <FaSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-white/50" />
                <input
                  type="text"
                  placeholder="Search users..."
                  className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/50"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              </div>
              <select
                value={filterRole}
                onChange={(e) => setFilterRole(e.target.value)}
                className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white"
              >
                <option value="all">All Roles</option>
                {safeRoles.map(role => (
                  <option key={role.name} value={role.name}>{role.name}</option>
                ))}
              </select>
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white"
              >
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
                  {filteredUsers.map((user) => {
                    const userRole = safeRoles.find(r => r.name === user.role);
                    return (
                      <tr key={user.id} className="hover:bg-white/5">
                        <td className="px-3 sm:px-6 py-4">
                          <div className="flex items-center">
                            <div 
                              className="w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold"
                              style={{ backgroundColor: userRole?.color || '#6b7280' }}
                            >
                              {user.username?.charAt(0)?.toUpperCase() || '?'}
                            </div>
                            <div className="ml-3">
                              <div className="text-sm font-medium text-white">{user.username || 'Unknown'}</div>
                              <div className="text-sm text-white/60">{user.email || 'No email'}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 sm:px-6 py-4">
                          <span className="text-sm font-medium" style={{ color: userRole?.color || '#6b7280' }}>
                            {user.role}
                          </span>
                        </td>
                        <td className="px-3 sm:px-6 py-4">
                          <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                            user.is_active
                              ? 'bg-green-500/20 text-green-300'
                              : 'bg-red-500/20 text-red-300'
                          }`}>
                            {user.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td className="px-3 sm:px-6 py-4 text-sm text-white/70">
                          {user.last_login ? new Date(user.last_login).toLocaleString() : 'Never'}
                        </td>
                        <td className="px-3 sm:px-6 py-4">
                          <div className="flex items-center gap-2">
                            <button className="p-2 text-blue-400 hover:bg-blue-500/10 rounded" title="View">
                              <FaEye />
                            </button>
                            <button
                              onClick={() => toggleUserActive(user.id, !user.is_active)}
                              className={`p-2 rounded ${user.is_active ? 'text-red-400 hover:bg-red-500/10' : 'text-green-400 hover:bg-green-500/10'}`}
                              title={user.is_active ? 'Deactivate' : 'Activate'}
                            >
                              {user.is_active ? <FaUserSlash /> : <FaUserCheck />}
                            </button>
                            <button
                              onClick={() => deleteUser(user.id)}
                              className="p-2 text-red-400 hover:bg-red-500/10 rounded"
                              title="Delete"
                            >
                              <FaTrash />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
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

      {activeTab === 'roles' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="font-medium text-white">Roles</h3>
            <button className="px-3 py-1.5 bg-brand-500 hover:bg-brand-600 rounded text-white text-sm flex items-center gap-2">
              <FaPlus /> Create Role
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {safeRoles.map((role) => (
              <div key={role.name} className="bg-white/5 border border-white/10 rounded-lg p-6 hover:bg-white/10 transition-colors">
                <div className="flex items-center gap-4 mb-4">
                  <div 
                    className="w-12 h-12 rounded-lg flex items-center justify-center"
                    style={{ backgroundColor: role.color || '#6b7280' }}
                  >
                    <FaShieldAlt className="text-xl text-white" />
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-lg" style={{ color: role.color || '#ffffff' }}>
                      {role.name}
                    </h3>
                    <p className="text-sm text-white/60">{role.description}</p>
                  </div>
                  {role.is_system && (
                    <div className="bg-blue-500/20 text-blue-300 px-2 py-1 rounded text-xs">System</div>
                  )}
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-white/70">Permissions</span>
                    <span className="text-sm font-medium text-white">{role.permissions?.length || 0}</span>
                  </div>
                </div>
                <div className="mt-4 pt-4 border-t border-white/10">
                  <button className="w-full py-2 px-4 bg-white/10 hover:bg-white/20 rounded-lg text-sm">
                    View / Edit
                  </button>
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
                      <span className="text-xs text-brand-400">
                        {new Date(log.timestamp).toLocaleString()}
                      </span>
                    </div>
                    {log.details && (
                      <div className="text-xs text-white/50 mt-1">
                        {typeof log.details === 'object' ? JSON.stringify(log.details) : log.details}
                      </div>
                    )}
                  </div>
                  <div className="text-xs text-white/40">
                    {log.resource_type && `${log.resource_type}:${log.resource_id}`}
                  </div>
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
    </div>
  );
}
