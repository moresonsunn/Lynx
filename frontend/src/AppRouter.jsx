import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useNavigate, useLocation, NavLink } from 'react-router-dom';
import { I18nProvider, useTranslation, LanguageSwitcherCompact } from './i18n';
import { AppProviders, useAuth, API, authHeaders } from './context/AppContext';
import { GlobalDataProvider, useGlobalData } from './context/GlobalDataContext';
import { ToastProvider, useToast } from './context/ToastContext';
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

import LoginPage from './pages/LoginPage';
import MustChangePasswordPage from './pages/MustChangePasswordPage';
import DashboardPage from './pages/DashboardPage';
import ServersPage from './pages/ServersPage';
import ServerDetailsPage from './pages/ServerDetailsPage';
import SettingsPage from './pages/SettingsPage';
import UsersPage from './pages/UsersPage';
import SteamGamesPage from './pages/SteamGamesPage';
import CreateSchedulePage from './pages/CreateSchedulePage';

import GlobalSearchBar from './components/GlobalSearchBar';
import NotificationCenter from './components/NotificationCenter';
import CommandPalette from './components/CommandPalette';
import SecurityPage from './pages/SecurityPage';
import PublicStatusPage from './pages/PublicStatusPage';

const TemplatesPageLazy = React.lazy(() => import('./pages/TemplatesPage'));

const PageLoader = () => (
  <div className="flex items-center justify-center h-screen bg-ink">
    <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full"></div>
  </div>
);

const APP_NAME = 'Lynx';

function AppLayout() {
  const { currentUser, isAdmin, logout } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const [sidebarOpen, setSidebarOpen] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  );
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false
  );

  useEffect(() => {
    function handleResize() {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (mobile) setSidebarOpen(false);
    }
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const sidebarItems = useMemo(() => {
    const items = [
      { id: 'dashboard', path: '/', label: t('nav.dashboard'), icon: FaHome, end: true, group: 'Overview' },
      { id: 'servers', path: '/servers', label: t('nav.servers'), icon: FaServer, group: 'Overview' },
      { id: 'minecraft', path: '/templates', label: 'Minecraft', icon: FaCube, group: 'Game Catalog' },
      { id: 'steam', path: '/steam', label: 'Steam', icon: FaSteam, group: 'Game Catalog' },
      { id: 'security', path: '/security', label: 'Security', icon: FaShieldAlt, group: 'Administration' },
    ];

    if (isAdmin) {
      items.push({ id: 'users', path: '/users', label: t('nav.users') || 'User Management', icon: FaUsers, group: 'Administration' });
    }

    items.push({ id: 'settings', path: '/settings', label: t('nav.settings') || 'Settings', icon: FaCog, group: 'Administration' });

    return items;
  }, [isAdmin, t]);

  const groupedSidebarItems = useMemo(() => {
    const groups = [];
    let currentGroup = null;
    for (const item of sidebarItems) {
      if (!currentGroup || currentGroup.name !== item.group) {
        currentGroup = { name: item.group, items: [] };
        groups.push(currentGroup);
      }
      currentGroup.items.push(item);
    }
    return groups;
  }, [sidebarItems]);

  const currentPageLabel = useMemo(() => {
    const currentPath = location.pathname;
    const item = sidebarItems.find(i =>
      i.end ? currentPath === i.path : currentPath.startsWith(i.path)
    );
    return item?.label || t('nav.dashboard');
  }, [location.pathname, sidebarItems, t]);

  // Animate page transitions, but keep the same key across server-detail tabs
  // so switching tabs within a server does not re-trigger the fade.
  const transitionKey = useMemo(() => {
    const parts = location.pathname.split('/').filter(Boolean);
    if (parts[0] === 'servers' && parts.length >= 2) return `/servers/${parts[1]}`;
    return location.pathname;
  }, [location.pathname]);

  const handleGlobalNavigate = useCallback((target) => {
    if (!target) return;

    if (target.type === 'server' && target.id) {
      navigate(`/servers/${target.id}`);
    } else if (target.type === 'player' && target.serverId) {
      navigate(`/servers/${target.serverId}/players`);
    } else if (target.type === 'config' && target.serverId) {
      navigate(`/servers/${target.serverId}/config`);
    } else if (typeof target === 'string') {
      navigate(`/${target}`);
    }
  }, [navigate]);

  const showLabels = isMobile || sidebarOpen;

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Sidebar Header */}
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-indigo-600 inline-flex items-center justify-center shadow-card">
            <FaServer className="text-white text-sm" />
          </div>
          {showLabels && <div className="font-semibold text-white tracking-tight">{APP_NAME}</div>}
        </div>
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto">
        <nav className="p-3 space-y-5">
          {groupedSidebarItems.map((group) => (
            <div key={group.name}>
              {showLabels && (
                <div className="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/35">
                  {group.name}
                </div>
              )}
              <div className="space-y-1">
                {group.items.map(item => (
                  <NavLink
                    key={item.id}
                    to={item.path}
                    end={item.end}
                    onClick={() => isMobile && setSidebarOpen(false)}
                    className={({ isActive }) => `
                      w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all text-sm font-medium
                      ${isActive
                        ? 'bg-brand-500 text-white shadow-sm shadow-brand-500/25'
                        : 'text-white/70 hover:text-white hover:bg-white/10'}
                      ${!showLabels ? 'justify-center' : ''}
                    `}
                    title={!showLabels ? item.label : undefined}
                  >
                    <item.icon className="text-base flex-shrink-0" />
                    {showLabels && (
                      <div className="flex items-center justify-between w-full min-w-0">
                        <span className="truncate">{item.label}</span>
                      </div>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </div>

      {/* Sidebar Footer */}
      <div className="mt-auto p-4 border-t border-white/10 bg-sidebar-footer backdrop-blur supports-[backdrop-filter]:bg-sidebar-footer">
        {/* Language Switcher */}
        <div className={`mb-3 ${!showLabels ? 'flex justify-center' : ''}`}>
          <LanguageSwitcherCompact />
        </div>

        {/* User Section */}
        <div
          className={`flex items-center gap-3 mb-3 cursor-pointer hover:bg-white/10 rounded-lg p-2 ${!showLabels ? 'justify-center' : ''}`}
          onClick={() => { navigate('/settings'); if (isMobile) setSidebarOpen(false); }}
          role="button"
          tabIndex={0}
        >
          {currentUser && (
            <>
              <div className="w-8 h-8 bg-brand-500 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold text-white uppercase">
                {(currentUser.username || 'U').slice(0, 2)}
              </div>
              {showLabels && (
                <div className="text-sm min-w-0">
                  <div className="text-white font-medium truncate">{currentUser.username}</div>
                  <div className="text-white/50 text-xs truncate capitalize">{currentUser.role}</div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Logout Button */}
        <button
          onClick={logout}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors ${!showLabels ? 'justify-center' : ''}`}
          title={!showLabels ? 'Logout' : undefined}
        >
          <FaArrowLeft className="flex-shrink-0" />
          {showLabels && <span>Logout</span>}
        </button>
      </div>
    </div>
  );

  return (
    <div className="h-screen bg-ink bg-hero-gradient flex overflow-hidden">
      {/* Sidebar */}
      {(() => {
        if (isMobile) {
          return sidebarOpen ? (
            <div className="fixed inset-0 z-50 flex">
              <div className="absolute inset-0 bg-black/60 backdrop-blur-xs" onClick={() => setSidebarOpen(false)} />
              <div className="relative w-64 bg-sidebar border-r border-white/10">{sidebarContent}</div>
            </div>
          ) : null;
        }

        return (
          <div className={`${sidebarOpen ? 'w-64' : 'w-16'} bg-sidebar border-r border-white/10 transition-all duration-300 flex flex-col sticky top-0 h-screen`}>
            {sidebarContent}
          </div>
        );
      })()}

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        <header className="relative z-40 border-b border-white/10 bg-topbar backdrop-blur supports-[backdrop-filter]:bg-topbar">
          <div className="px-4 md:px-6 flex items-center justify-between h-14 gap-3">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
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
            <div className="flex items-center gap-2 sm:gap-3 flex-1 justify-end min-w-0">
              <GlobalSearchBar onNavigate={handleGlobalNavigate} className="w-full max-w-[10rem] sm:max-w-[16rem] md:max-w-[20rem]" />
              <NotificationCenter />
              <div className="hidden sm:block text-sm text-white/70">
                Welcome back, {currentUser?.username || 'User'}
              </div>
            </div>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 min-h-0 overflow-y-auto">
          <div key={transitionKey} className="min-h-full animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>

      {/* Global command palette (Ctrl/⌘+K) */}
      <CommandPalette />
    </div>
  );
}

function ProtectedLayout() {
  const { isAuthenticated, loading, mustChangePassword } = useAuth();
  const location = useLocation();

  if (loading) {
    return <PageLoader />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (mustChangePassword && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  return <AppLayout />;
}

function AdminLayout() {
  const { isAuthenticated, isAdmin, loading } = useAuth();

  if (loading) {
    return <PageLoader />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <AppLayout />;
}

function LoginPageWrapper() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated) {
      const from = location.state?.from?.pathname || '/';
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, location]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(username, password);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <LoginPage
      appName={APP_NAME}
      username={username}
      password={password}
      onUsernameChange={setUsername}
      onPasswordChange={setPassword}
      onSubmit={handleSubmit}
      error={error}
      loading={loading}
    />
  );
}

function TemplatesPageWrapper() {
  const globalData = useGlobalData();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [selectedType, setSelectedType] = useState('vanilla');
  const [name, setName] = useState('');
  const [version, setVersion] = useState('');
  const [hostPort, setHostPort] = useState('');
  const [minRam, setMinRam] = useState('2048M');
  const [maxRam, setMaxRam] = useState('4096M');
  const [cpuCores, setCpuCores] = useState(null);
  const [loaderVersion, setLoaderVersion] = useState('');
  const [loaderVersionsData, setLoaderVersionsData] = useState(null);
  const [installerVersion, setInstallerVersion] = useState('');
  const [versionsData, setVersionsData] = useState(null);

  const types = globalData?.serverTypes || [];

  useEffect(() => {
    if (!selectedType) return;
    let cancelled = false;

    async function fetchVersions() {
      try {
        const r = await fetch(`${API}/server-types/${selectedType}/versions`, { headers: authHeaders() });
        if (r.ok && !cancelled) {
          const data = await r.json();
          setVersionsData(data);
          if (data?.versions?.length > 0) {
            setVersion(data.versions[0].id || data.versions[0]);
          }
        }
      } catch { }
    }

    fetchVersions();
    return () => { cancelled = true; };
  }, [selectedType]);

  useEffect(() => {
    if (!['fabric', 'forge', 'neoforge'].includes(selectedType) || !version) {
      setLoaderVersionsData(null);
      return;
    }

    let cancelled = false;
    async function fetchLoaders() {
      try {
        const r = await fetch(`${API}/server-types/${selectedType}/loader-versions?version=${version}`, { headers: authHeaders() });
        if (r.ok && !cancelled) {
          const data = await r.json();
          setLoaderVersionsData(data);
          if (data?.loader_versions?.length > 0) {
            setLoaderVersion(data.loader_versions[0]);
          }
          if (selectedType === 'fabric' && data?.latest_installer_version) {
            setInstallerVersion(data.latest_installer_version);
          }
        }
      } catch (e) {
        console.error("Failed to fetch loader versions", e);
      }
    }

    fetchLoaders();
    return () => { cancelled = true; };
  }, [selectedType, version]);

  const createServer = useCallback(async () => {
    const serverName = name.trim();
    if (!serverName) {
      showToast('error', 'Please enter a server name');
      return;
    }

    showToast('info', `Creating server "${serverName}"...`, 10000);

    try {
      const body = {
        name: serverName,
        type: selectedType,
        version: version,
        host_port: hostPort ? Number(hostPort) : null,
        min_ram: minRam,
        max_ram: maxRam,
        cpu_cores: cpuCores,
        loader_version: loaderVersion || null,
        installer_version: installerVersion || null,
      };

      const r = await fetch(`${API}/servers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body)
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }

      const startTime = Date.now();
      const timeoutMs = 15000;
      const intervalMs = 500;
      let foundServer = null;

      while (Date.now() - startTime < timeoutMs) {
        try {
          const serversRes = await fetch(`${API}/servers`, { headers: authHeaders() });
          if (serversRes.ok) {
            const servers = await serversRes.json();
            foundServer = Array.isArray(servers) ? servers.find(s => s && s.name === serverName) : null;

            if (globalData?.__setGlobalData) {
              globalData.__setGlobalData(cur => ({ ...cur, servers: Array.isArray(servers) ? servers : cur.servers }));
            }

            if (foundServer) break;
          }
        } catch { }
        await new Promise(res => setTimeout(res, intervalMs));
      }

      setName('');

      if (foundServer) {
        showToast('success', `Server "${serverName}" created successfully!`);
        navigate(`/servers/${foundServer.id}`);
      } else {
        showToast('info', `Server "${serverName}" is being created. It will appear shortly.`);
        if (globalData?.__refreshServers) {
          globalData.__refreshServers();
        }
        navigate('/servers');
      }
    } catch (e) {
      showToast('error', `Failed to create server: ${e.message}`);
    }
  }, [name, selectedType, version, hostPort, minRam, maxRam, cpuCores, loaderVersion, installerVersion, globalData, showToast, navigate]);

  return (
    <React.Suspense fallback={<PageLoader />}>
      <TemplatesPageLazy
        API={API}
        authHeaders={authHeaders}
        onCreateServer={createServer}
        types={types}
        versionsData={versionsData}
        selectedType={selectedType}
        setSelectedType={setSelectedType}
        name={name}
        setName={setName}
        version={version}
        setVersion={setVersion}
        hostPort={hostPort}
        setHostPort={setHostPort}
        minRam={minRam}
        setMinRam={setMinRam}
        maxRam={maxRam}
        setMaxRam={setMaxRam}
        cpuCores={cpuCores}
        setCpuCores={setCpuCores}
        loaderVersion={loaderVersion}
        setLoaderVersion={setLoaderVersion}
        loaderVersionsData={loaderVersionsData}
        installerVersion={installerVersion}
        setInstallerVersion={setInstallerVersion}
      />
    </React.Suspense>
  );
}

function MustChangePasswordWrapper() {
  const { logout, authHeaders } = useAuth();

  const handleComplete = () => {
    window.location.href = '/';
  };

  return (
    <MustChangePasswordPage
      appName={APP_NAME}
      apiBaseUrl={API}
      onLogout={logout}
      onComplete={handleComplete}
      authHeaders={authHeaders}
    />
  );
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPageWrapper />} />
      <Route path="/change-password" element={<MustChangePasswordWrapper />} />
      <Route path="/status" element={<PublicStatusPage />} />

      {/* Protected routes share a single persistent layout (Outlet) */}
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/servers" element={<ServersPage />} />
        <Route path="/servers/:serverId" element={<ServerDetailsPage />} />
        <Route path="/servers/:serverId/:tab" element={<ServerDetailsPage />} />
        <Route path="/servers/:serverId/schedules/new" element={<CreateSchedulePage />} />
        <Route path="/templates" element={<TemplatesPageWrapper />} />
        <Route path="/steam" element={<SteamGamesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/security" element={<SecurityPage />} />
      </Route>

      {/* Admin routes */}
      <Route element={<AdminLayout />}>
        <Route path="/users" element={<UsersPage />} />
      </Route>

      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function AppWithRouter() {
  return (
    <BrowserRouter>
      <I18nProvider>
        <AppProviders>
          <GlobalDataProvider>
            <ToastProvider>
              <AppRoutes />
            </ToastProvider>
          </GlobalDataProvider>
        </AppProviders>
      </I18nProvider>
    </BrowserRouter>
  );
}

export default AppWithRouter;
