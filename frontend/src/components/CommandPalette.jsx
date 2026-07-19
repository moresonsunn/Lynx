import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FaSearch,
  FaServer,
  FaHome,
  FaCube,
  FaSteam,
  FaDungeon,
  FaObjectGroup,
  FaChartBar,
  FaShieldAlt,
  FaUsers,
  FaCog,
} from 'react-icons/fa';
import { useServers } from '../context/GlobalDataContext';
import { useAuth } from '../context/AppContext';

// Static navigation targets exposed as palette commands.
const NAV_COMMANDS = [
  { id: 'nav-dashboard', label: 'Dashboard', path: '/', icon: FaHome },
  { id: 'nav-servers', label: 'My Servers', path: '/servers', icon: FaServer },
  { id: 'nav-minecraft', label: 'Minecraft', path: '/templates', icon: FaCube },
  { id: 'nav-steam', label: 'Steam', path: '/steam', icon: FaSteam },
  { id: 'nav-hytale', label: 'Hytale', path: '/hytale', icon: FaDungeon },
  { id: 'nav-multi', label: 'Multi-Server', path: '/multi-server', icon: FaObjectGroup },
  { id: 'nav-monitoring', label: 'Monitoring', path: '/monitoring', icon: FaChartBar },
  { id: 'nav-security', label: 'Security', path: '/security', icon: FaShieldAlt },
  { id: 'nav-settings', label: 'Settings', path: '/settings', icon: FaCog },
];

/**
 * Command palette (Ctrl/⌘+K).
 *
 * Opens on the `lynx:open-command-palette` window event (dispatched by the
 * header search bar's shortcut handler), so there is a single Ctrl+K owner and
 * no double-trigger. Lets the user fuzzy-search servers and jump to any page,
 * fully keyboard-navigable.
 */
export default function CommandPalette() {
  const navigate = useNavigate();
  const servers = useServers();
  const { isAdmin } = useAuth();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Toggle on the global shortcut event.
  useEffect(() => {
    const onEvt = () => setOpen((o) => !o);
    window.addEventListener('lynx:open-command-palette', onEvt);
    return () => window.removeEventListener('lynx:open-command-palette', onEvt);
  }, []);

  // Reset + focus when opened.
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setHighlight(0);
    const id = setTimeout(() => inputRef.current?.focus(), 20);
    return () => clearTimeout(id);
  }, [open]);

  const navCommands = useMemo(() => {
    const cmds = [...NAV_COMMANDS];
    if (isAdmin) {
      cmds.push({ id: 'nav-users', label: 'User Management', path: '/users', icon: FaUsers });
    }
    return cmds;
  }, [isAdmin]);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    const serverItems = (Array.isArray(servers) ? servers : []).map((s) => ({
      id: `srv-${s.id}`,
      label: s.name,
      sub: String(s.id).slice(0, 12),
      icon: FaServer,
      path: `/servers/${s.id}`,
      group: 'Servers',
      status: s.status,
    }));
    const navItems = navCommands.map((c) => ({ ...c, group: 'Navigation', sub: c.path }));
    let all = [...serverItems, ...navItems];
    if (q) {
      all = all.filter(
        (it) =>
          (it.label && it.label.toLowerCase().includes(q)) ||
          (it.sub && it.sub.toLowerCase().includes(q))
      );
    }
    return all;
  }, [query, servers, navCommands]);

  const activate = useCallback(
    (item) => {
      if (!item) return;
      setOpen(false);
      if (item.path) navigate(item.path);
    },
    [navigate]
  );

  // Keyboard navigation while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHighlight((h) => Math.min(h + 1, items.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHighlight((h) => Math.max(h - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        activate(items[highlight]);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, items, highlight, activate]);

  // Keep the highlighted row valid and scrolled into view.
  useEffect(() => {
    setHighlight((h) => Math.min(h, Math.max(items.length - 1, 0)));
  }, [items.length]);

  useEffect(() => {
    const el = listRef.current?.children?.[highlight];
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }, [highlight]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[12vh] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-xl bg-ink border border-white/10 ring-1 ring-black/40 rounded-xl shadow-2xl overflow-hidden animate-fade-in">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-white/10">
          <FaSearch className="text-white/40 flex-shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setHighlight(0);
            }}
            placeholder="Search servers or jump to a page…"
            className="flex-1 bg-transparent text-white placeholder-white/30 outline-none text-sm"
          />
          <kbd className="text-[10px] text-white/30 border border-white/15 rounded px-1.5 py-0.5 flex-shrink-0">Esc</kbd>
        </div>
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto py-1">
          {items.length === 0 ? (
            <div className="px-4 py-10 text-center text-white/40 text-sm">No matches</div>
          ) : (
            items.map((item, i) => {
              const Icon = item.icon || FaServer;
              const active = i === highlight;
              return (
                <button
                  key={item.id}
                  type="button"
                  onMouseEnter={() => setHighlight(i)}
                  onClick={() => activate(item)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    active ? 'bg-brand-500/20' : 'hover:bg-white/5'
                  }`}
                >
                  <span
                    className={`w-7 h-7 rounded-md inline-flex items-center justify-center flex-shrink-0 ${
                      active ? 'bg-brand-500 text-white' : 'bg-white/10 text-white/60'
                    }`}
                  >
                    <Icon className="text-xs" />
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm text-white truncate">{item.label}</span>
                    {item.sub && <span className="block text-[11px] text-white/40 truncate">{item.sub}</span>}
                  </span>
                  {item.status && (
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full flex-shrink-0 ${
                        item.status === 'running'
                          ? 'bg-green-500/15 text-green-300'
                          : 'bg-yellow-500/15 text-yellow-300'
                      }`}
                    >
                      {item.status}
                    </span>
                  )}
                  <span className="text-[10px] text-white/25 flex-shrink-0 hidden sm:inline">{item.group}</span>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
