import React, { useState, useEffect } from 'react';
import {
  FaUserShield, FaPlus, FaTrash, FaEye, FaPlay, FaCog,
  FaCheck, FaSearch
} from 'react-icons/fa';
import { API, authHeaders } from '../../context/AppContext';

const PERMISSION_LABELS = {
  view: { label: 'View', desc: 'Read-only access', icon: FaEye, color: 'text-blue-400 bg-blue-500/20' },
  operate: { label: 'Operate', desc: 'Start/stop/console', icon: FaPlay, color: 'text-yellow-400 bg-yellow-500/20' },
  manage: { label: 'Manage', desc: 'Full access', icon: FaCog, color: 'text-green-400 bg-green-500/20' },
};

export default function ServerPermissionsPanel({ serverName }) {
  const [permissions, setPermissions] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedPerm, setSelectedPerm] = useState('manage');
  const [search, setSearch] = useState('');

  async function loadPermissions() {
    try {
      const r = await fetch(`${API}/api/permissions/servers/${encodeURIComponent(serverName)}`, {
        headers: authHeaders(),
      });
      if (r.ok) {
        const data = await r.json();
        setPermissions(data.permissions || []);
      }
    } catch {} finally {
      setLoading(false);
    }
  }

  async function loadUsers() {
    try {
      const r = await fetch(`${API}/users`, { headers: authHeaders() });
      if (r.ok) {
        const data = await r.json();
        setUsers(Array.isArray(data) ? data : data.users || []);
      }
    } catch {}
  }

  useEffect(() => {
    loadPermissions();
    loadUsers();
  }, [serverName]);

  async function grantPermission() {
    if (!selectedUserId) return;
    try {
      await fetch(`${API}/api/permissions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          user_id: parseInt(selectedUserId),
          server_name: serverName,
          permission: selectedPerm,
        }),
      });
      loadPermissions();
      setShowAdd(false);
      setSelectedUserId('');
    } catch {}
  }

  async function revokePermission(permId) {
    if (!confirm('Remove this user\'s access to this server?')) return;
    try {
      await fetch(`${API}/api/permissions/${permId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      loadPermissions();
    } catch {}
  }

  // Users that don't already have permissions for this server
  const existingUserIds = new Set(permissions.map(p => p.user_id));
  const availableUsers = users.filter(u =>
    !existingUserIds.has(u.id) &&
    u.role !== 'admin' && u.role !== 'owner' &&
    (search ? u.username.toLowerCase().includes(search.toLowerCase()) : true)
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-white/70 flex items-center gap-2">
          <FaUserShield className="text-brand-400" />
          Server Access Control
        </h4>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className={`px-3 py-1.5 rounded-lg flex items-center gap-2 text-sm transition-colors ${
            showAdd ? 'bg-brand-500/20 text-brand-400' : 'bg-white/10 hover:bg-white/20 text-white/70'
          }`}
        >
          <FaPlus className="w-3 h-3" />
          Add User
        </button>
      </div>

      {/* Add User Form */}
      {showAdd && (
        <div className="bg-white/5 border border-white/10 rounded-lg p-4 space-y-3">
          <div>
            <label className="block text-xs text-white/50 mb-1">Search Users</label>
            <div className="relative">
              <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30 w-3.5 h-3.5" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by username..."
                className="w-full pl-9 pr-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-white/50 mb-1">Select User</label>
            <select
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white text-sm"
            >
              <option value="">Choose a user...</option>
              {availableUsers.map(u => (
                <option key={u.id} value={u.id}>
                  {u.username} ({u.email || u.role})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-white/50 mb-1">Permission Level</label>
            <div className="flex gap-2">
              {Object.entries(PERMISSION_LABELS).map(([key, { label, desc, icon: Icon, color }]) => (
                <button
                  key={key}
                  onClick={() => setSelectedPerm(key)}
                  className={`flex-1 px-3 py-2 rounded-lg border text-sm flex items-center justify-center gap-2 transition-colors ${
                    selectedPerm === key
                      ? `border-brand-500 bg-brand-500/10 text-brand-400`
                      : 'border-white/10 bg-white/5 text-white/60 hover:bg-white/10'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <div className="text-left">
                    <div className="font-medium">{label}</div>
                    <div className="text-[10px] opacity-60">{desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={grantPermission}
            disabled={!selectedUserId}
            className="w-full py-2 bg-brand-500 hover:bg-brand-400 disabled:opacity-50 rounded-lg text-white text-sm flex items-center justify-center gap-2"
          >
            <FaCheck className="w-3 h-3" />
            Grant Access
          </button>
        </div>
      )}

      {/* Existing Permissions */}
      <div className="space-y-2">
        {loading ? (
          <div className="text-white/30 text-sm text-center py-6">Loading...</div>
        ) : permissions.length > 0 ? (
          permissions.map(p => {
            const pInfo = PERMISSION_LABELS[p.permission] || PERMISSION_LABELS.view;
            const PIcon = pInfo.icon;
            return (
              <div
                key={p.id}
                className="flex items-center justify-between bg-white/5 border border-white/10 rounded-lg px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center text-white/60 text-sm font-medium">
                    {(p.username || '?')[0].toUpperCase()}
                  </div>
                  <div>
                    <div className="text-white text-sm font-medium">{p.username}</div>
                    <div className="text-xs text-white/40">{p.email}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 ${pInfo.color}`}>
                    <PIcon className="w-3 h-3" />
                    {pInfo.label}
                  </span>
                  <button
                    onClick={() => revokePermission(p.id)}
                    className="p-1.5 rounded hover:bg-red-500/20 text-white/40 hover:text-red-400 transition-colors"
                    title="Remove access"
                  >
                    <FaTrash className="w-3 h-3" />
                  </button>
                </div>
              </div>
            );
          })
        ) : (
          <div className="text-center py-8 text-white/30">
            <FaUserShield className="text-2xl mb-2 mx-auto" />
            <p className="text-sm">No user permissions set</p>
            <p className="text-xs text-white/20 mt-1">Admins can always access all servers</p>
          </div>
        )}
      </div>
    </div>
  );
}
