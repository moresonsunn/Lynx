import React, { useMemo } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AppContext';
import { useTranslation, LanguageSwitcherCompact } from '../i18n';
import {
  FaHome,
  FaServer,
  FaUsers,
  FaCog,
  FaBars,
  FaArrowLeft,
  FaBackward,
  FaForward,
  FaSteam,
  FaCube,
  FaShieldAlt,
} from 'react-icons/fa';
import GlobalSearchBar from './GlobalSearchBar';
import NotificationCenter from './NotificationCenter';
import { APP_NAME } from '../lib/api';

export function Sidebar({ isOpen, isMobile, onClose }) {
  const { currentUser, isAdmin, logout } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();

  const sidebarItems = useMemo(() => {
    const items = [
      { id: 'dashboard', path: '/', label: t('nav.dashboard'), icon: FaHome, end: true },
      { id: 'servers', path: '/servers', label: t('nav.servers'), icon: FaServer },
      { id: 'minecraft', path: '/templates', label: 'Minecraft', icon: FaCube },
      { id: 'steam', path: '/steam', label: 'Steam', icon: FaSteam },
      { id: 'security', path: '/security', label: 'Security', icon: FaShieldAlt },
    ];

    if (isAdmin) {
      items.push({ id: 'users', path: '/users', label: t('nav.users'), icon: FaUsers });
    }

    items.push({ id: 'settings', path: '/settings', label: t('nav.settings'), icon: FaCog });

    return items;
  }, [isAdmin, t]);

  const content = (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-md bg-brand-500 inline-flex items-center justify-center shadow-card">
            <FaServer className="text-white" />
          </div>
          {(!isMobile && isOpen) && <div className="font-semibold text-white">{APP_NAME}</div>}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <nav className="p-4">
          <div className="space-y-2">
            {sidebarItems.map(item => (
              <NavLink
                key={item.id}
                to={item.path}
                end={item.end}
                onClick={() => isMobile && onClose?.()}
                className={({ isActive }) => `
                  w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
                  ${isActive ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}
                  ${(!isMobile && !isOpen) ? 'justify-center' : ''}
                `}
                title={(!isMobile && !isOpen) ? item.label : undefined}
              >
                <item.icon className="text-lg flex-shrink-0" />
                {(!isMobile && isOpen) && (
                  <div className="flex items-center justify-between w-full min-w-0">
                    <span className="truncate">{item.label}</span>
                  </div>
                )}
              </NavLink>
            ))}
          </div>
        </nav>
      </div>

      <div className="mt-auto p-4 border-t border-white/10 bg-sidebar-footer backdrop-blur supports-[backdrop-filter]:bg-sidebar-footer">
        <div className={`mb-3 ${(!isMobile && !isOpen) ? 'flex justify-center' : ''}`}>
          <LanguageSwitcherCompact />
        </div>

        <div
          className={`flex items-center gap-3 mb-3 cursor-pointer hover:bg-white/10 rounded-lg p-2 ${(!isMobile && !isOpen) ? 'justify-center' : ''}`}
          onClick={() => { navigate('/settings'); if (isMobile) onClose?.(); }}
          role="button"
          tabIndex={0}
        >
          {currentUser && (
            <>
              <div className="w-8 h-8 bg-brand-500 rounded-full flex items-center justify-center flex-shrink-0">
                <FaUsers className="text-sm text-white" />
              </div>
              {(!isMobile && isOpen) && (
                <div className="text-sm min-w-0">
                  <div className="text-white font-medium truncate">{currentUser.username}</div>
                  <div className="text-white/60 truncate">{currentUser.role}</div>
                </div>
              )}
            </>
          )}
        </div>

        <button
          onClick={logout}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors ${(!isMobile && !isOpen) ? 'justify-center' : ''}`}
          title={(!isMobile && !isOpen) ? 'Logout' : undefined}
        >
          <FaArrowLeft className="flex-shrink-0" />
          {(!isMobile && isOpen) && <span>Logout</span>}
        </button>
      </div>
    </div>
  );

  if (isMobile) {
    return isOpen ? (
      <div className="fixed inset-0 z-50 flex">
        <div className="absolute inset-0 bg-black/60" onClick={onClose} />
        <div className="relative w-64 bg-sidebar border-r border-white/10">{content}</div>
      </div>
    ) : null;
  }

  return (
    <div className={`${isOpen ? 'w-64' : 'w-16'} bg-sidebar border-r border-white/10 transition-all duration-300 flex flex-col sticky top-0 h-screen`}>
      {content}
    </div>
  );
}

export function TopHeader({ sidebarOpen, isMobile, onToggleSidebar, onGlobalNavigate }) {
  const { currentUser } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();

  const currentPageLabel = useMemo(() => {
    const path = location.pathname;
    if (path === '/') return t('nav.dashboard');
    if (path.startsWith('/servers')) return t('nav.servers');
    if (path.startsWith('/templates')) return 'Minecraft';
    if (path.startsWith('/steam')) return 'Steam';
    if (path.startsWith('/security')) return 'Security';
    if (path.startsWith('/users')) return t('nav.users');
    if (path.startsWith('/settings')) return t('nav.settings');
    return t('nav.dashboard');
  }, [location.pathname, t]);

  return (
    <header className="border-b border-white/10 bg-topbar backdrop-blur supports-[backdrop-filter]:bg-topbar">
      <div className="px-4 md:px-6 flex items-center justify-between h-14">
        <div className="flex items-center gap-4">
          <button
            onClick={onToggleSidebar}
            className="p-2 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors"
            aria-label={
              isMobile
                ? (sidebarOpen ? 'Close navigation' : 'Open navigation')
                : (sidebarOpen ? 'Collapse navigation' : 'Expand navigation')
            }
          >
            {isMobile ? <FaBars /> : (sidebarOpen ? <FaBackward /> : <FaForward />)}
          </button>
          <h1 className="text-lg font-semibold text-white">
            {currentPageLabel}
          </h1>
        </div>
        <div className="flex items-center gap-3 flex-1 justify-end max-w-2xl">
          <GlobalSearchBar onNavigate={onGlobalNavigate} className="w-full max-w-xs" />
          <NotificationCenter />
          <div className="hidden sm:block text-sm text-white/70">
            Welcome back, {currentUser?.username || 'User'}
          </div>
        </div>
      </div>
    </header>
  );
}

export default { Sidebar, TopHeader };
