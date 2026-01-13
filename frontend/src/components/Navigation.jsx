import React from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from '../i18n';
import {
  FaHome,
  FaServer,
  FaLayerGroup,
  FaUsers,
  FaCog,
  FaBars,
  FaTimes,
} from 'react-icons/fa';

// Sidebar navigation items configuration
export const getNavItems = (isAdmin) => {
  const items = [
    { id: 'dashboard', path: '/', label: 'nav.dashboard', icon: FaHome },
    { id: 'servers', path: '/servers', label: 'nav.servers', icon: FaServer },
    { id: 'templates', path: '/templates', label: 'nav.templates', icon: FaLayerGroup },
  ];
  
  if (isAdmin) {
    items.push({ id: 'users', path: '/users', label: 'nav.users', icon: FaUsers });
  }
  
  items.push({ id: 'settings', path: '/settings', label: 'nav.settings', icon: FaCog });
  
  return items;
};

// Navigation hook for programmatic navigation
export function useAppNavigation() {
  const navigate = useNavigate();
  const location = useLocation();
  
  return {
    navigateTo: (path) => navigate(path),
    navigateToServer: (serverId, tab = 'overview') => navigate(`/servers/${serverId}/${tab}`),
    navigateToServers: () => navigate('/servers'),
    navigateToDashboard: () => navigate('/'),
    navigateToSettings: () => navigate('/settings'),
    navigateToTemplates: () => navigate('/templates'),
    navigateToUsers: () => navigate('/users'),
    currentPath: location.pathname,
    isActive: (path) => location.pathname === path || 
      (path !== '/' && location.pathname.startsWith(path)),
  };
}

// Sidebar component
export function Sidebar({ 
  isOpen, 
  onToggle, 
  isAdmin, 
  isMobile, 
  currentUser,
  onLogout,
}) {
  const { t } = useTranslation();
  const navItems = getNavItems(isAdmin);
  
  return (
    <>
      {/* Mobile overlay */}
      {isMobile && isOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-40"
          onClick={onToggle}
        />
      )}
      
      {/* Sidebar */}
      <aside 
        className={`
          fixed top-0 left-0 h-full bg-ink-dark border-r border-white/10 
          transition-transform duration-300 ease-in-out z-50
          ${isOpen ? 'translate-x-0' : '-translate-x-full'}
          ${isMobile ? 'w-64' : 'w-64'}
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10">
          <h1 className="text-xl font-bold text-white">Lynx</h1>
          {isMobile && (
            <button 
              onClick={onToggle}
              className="p-2 text-white/70 hover:text-white"
            >
              <FaTimes />
            </button>
          )}
        </div>
        
        {/* Navigation */}
        <nav className="p-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.id}
              to={item.path}
              onClick={() => isMobile && onToggle()}
              className={({ isActive }) => `
                flex items-center gap-3 px-4 py-3 rounded-lg transition-colors
                ${isActive 
                  ? 'bg-brand-500 text-white' 
                  : 'text-white/70 hover:bg-white/10 hover:text-white'
                }
              `}
            >
              <item.icon className="w-5 h-5" />
              <span>{t(item.label)}</span>
            </NavLink>
          ))}
        </nav>
        
        {/* User section at bottom */}
        {currentUser && (
          <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-white/10">
            <div className="flex items-center justify-between">
              <div className="text-sm">
                <div className="text-white font-medium">{currentUser.username}</div>
                <div className="text-white/50 text-xs">{currentUser.role || 'User'}</div>
              </div>
              <button
                onClick={onLogout}
                className="px-3 py-1 text-xs bg-white/10 hover:bg-white/20 rounded text-white/70 hover:text-white"
              >
                Logout
              </button>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}

// Mobile header with hamburger menu
export function MobileHeader({ onToggleSidebar }) {
  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-ink-dark border-b border-white/10 flex items-center px-4 z-30 md:hidden">
      <button 
        onClick={onToggleSidebar}
        className="p-2 text-white/70 hover:text-white"
      >
        <FaBars />
      </button>
      <h1 className="ml-3 text-lg font-bold text-white">Lynx</h1>
    </header>
  );
}

// Layout wrapper that includes sidebar
export function AppLayout({ 
  children, 
  sidebarOpen, 
  onToggleSidebar, 
  isAdmin, 
  isMobile,
  currentUser,
  onLogout,
}) {
  return (
    <div className="min-h-screen bg-ink">
      {/* Mobile header */}
      {isMobile && (
        <MobileHeader onToggleSidebar={onToggleSidebar} />
      )}
      
      {/* Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={onToggleSidebar}
        isAdmin={isAdmin}
        isMobile={isMobile}
        currentUser={currentUser}
        onLogout={onLogout}
      />
      
      {/* Main content */}
      <main 
        className={`
          transition-all duration-300 min-h-screen
          ${isMobile ? 'pt-14' : ''}
          ${sidebarOpen && !isMobile ? 'ml-64' : 'ml-0'}
        `}
      >
        {children}
      </main>
    </div>
  );
}

export default Sidebar;
