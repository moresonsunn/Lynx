import React, { useState, useEffect, useRef, useCallback } from 'react';
import { FaBell, FaCheck, FaCheckDouble, FaServer, FaExclamationTriangle, FaInfoCircle, FaShieldAlt, FaDownload, FaClock, FaTimes } from 'react-icons/fa';
import { API, authHeaders } from '../context/AppContext';

const TYPE_CONFIG = {
  server_start:  { icon: FaServer, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Server Started' },
  server_stop:   { icon: FaServer, color: 'text-red-400',     bg: 'bg-red-500/10',     label: 'Server Stopped' },
  server_crash:  { icon: FaExclamationTriangle, color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'Server Crash' },
  backup:        { icon: FaDownload, color: 'text-blue-400',   bg: 'bg-blue-500/10',    label: 'Backup' },
  scheduled:     { icon: FaClock,    color: 'text-purple-400', bg: 'bg-purple-500/10',  label: 'Scheduled Task' },
  security:      { icon: FaShieldAlt, color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'Security' },
  info:          { icon: FaInfoCircle, color: 'text-blue-400', bg: 'bg-blue-500/10',    label: 'Info' },
  warning:       { icon: FaExclamationTriangle, color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'Warning' },
  error:         { icon: FaExclamationTriangle, color: 'text-red-400', bg: 'bg-red-500/10', label: 'Error' },
  success:       { icon: FaCheck, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Success' },
};

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const now = new Date();
  const date = new Date(dateStr);
  const seconds = Math.floor((now - date) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function NotificationItem({ notification, onMarkRead }) {
  const config = TYPE_CONFIG[notification.type] || TYPE_CONFIG.info;
  const Icon = config.icon;

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 transition-colors cursor-pointer hover:bg-white/5 ${
        !notification.is_read ? 'bg-white/[0.03]' : ''
      }`}
      onClick={() => !notification.is_read && onMarkRead?.(notification.id)}
    >
      <div className={`mt-0.5 p-1.5 rounded-lg ${config.bg} flex-shrink-0`}>
        <Icon className={`text-sm ${config.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium truncate ${!notification.is_read ? 'text-white' : 'text-white/70'}`}>
            {notification.title}
          </span>
          {!notification.is_read && (
            <span className="w-2 h-2 rounded-full bg-brand-500 flex-shrink-0" />
          )}
        </div>
        <p className="text-xs text-white/50 mt-0.5 line-clamp-2">{notification.message}</p>
        <span className="text-[10px] text-white/30 mt-1 block">{timeAgo(notification.created_at)}</span>
      </div>
    </div>
  );
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef(null);
  const pollRef = useRef(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await fetch(`${API}/realtime/notifications?limit=30`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        const items = data.notifications || [];
        setNotifications(items);
        setUnreadCount(items.filter(n => !n.is_read).length);
      }
    } catch (err) {
      // Silently fail — notifications are non-critical
    }
  }, []);

  // Poll every 30 seconds
  useEffect(() => {
    fetchNotifications();
    pollRef.current = setInterval(fetchNotifications, 30000);
    return () => clearInterval(pollRef.current);
  }, [fetchNotifications]);

  // Refresh when panel opens
  useEffect(() => {
    if (open) fetchNotifications();
  }, [open, fetchNotifications]);

  // Click-outside handler
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const markRead = useCallback(async (id) => {
    try {
      await fetch(`${API}/realtime/notifications/${id}/read`, {
        method: 'POST',
        headers: authHeaders(),
      });
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
      setUnreadCount(prev => Math.max(0, prev - 1));
    } catch { }
  }, []);

  const markAllRead = useCallback(async () => {
    try {
      await fetch(`${API}/realtime/notifications/read-all`, {
        method: 'POST',
        headers: authHeaders(),
      });
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch { }
  }, []);

  return (
    <div className="relative" ref={panelRef}>
      {/* Bell Button */}
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors"
        aria-label="Notifications"
      >
        <FaBell className="text-lg" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white px-1 shadow-lg animate-pulse">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown Panel */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-[360px] max-h-[480px] bg-card/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl z-50 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
            <div className="flex items-center gap-2">
              <FaBell className="text-brand-400 text-sm" />
              <span className="text-sm font-semibold text-white">Notifications</span>
              {unreadCount > 0 && (
                <span className="text-xs text-white/50">({unreadCount} unread)</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              {unreadCount > 0 && (
                <button
                  onClick={markAllRead}
                  className="p-1.5 rounded-lg text-white/50 hover:text-brand-400 hover:bg-white/10 transition-colors"
                  title="Mark all as read"
                >
                  <FaCheckDouble className="text-xs" />
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg text-white/50 hover:text-white hover:bg-white/10 transition-colors"
              >
                <FaTimes className="text-xs" />
              </button>
            </div>
          </div>

          {/* Notification List */}
          <div className="flex-1 overflow-y-auto overscroll-contain">
            {notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-white/30">
                <FaBell className="text-3xl mb-3" />
                <span className="text-sm">No notifications yet</span>
                <span className="text-xs mt-1">Server events will appear here</span>
              </div>
            ) : (
              <div className="divide-y divide-white/5">
                {notifications.map(n => (
                  <NotificationItem key={n.id} notification={n} onMarkRead={markRead} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
