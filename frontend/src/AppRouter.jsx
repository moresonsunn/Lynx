import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation, NavLink } from 'react-router-dom';
import { I18nProvider, useTranslation, LanguageSwitcherCompact } from './i18n';
import { AppProviders, useAuth, API, authHeaders } from './context/AppContext';
import { GlobalDataProvider, useGlobalData } from './context/GlobalDataContext';
import { ToastProvider, useToast } from './context/ToastContext';
import {
  FaHome,
  FaServer,
  FaLayerGroup,
  FaUsers,
  FaCog,
  FaBars,
  FaArrowLeft,
  FaBackward,
  FaForward,
} from 'react-icons/fa';


import LoginPage from './pages/LoginPage';
import MustChangePasswordPage from './pages/MustChangePasswordPage';
import DashboardPage from './pages/DashboardPage';
import ServersPage from './pages/ServersPage';
import ServerDetailsPage from './pages/ServerDetailsPage';
import SettingsPage from './pages/SettingsPage';
import UsersPage from './pages/UsersPage';


import GlobalSearchBar from './components/GlobalSearchBar';


const TemplatesPageLazy = React.lazy(() => import('./pages/TemplatesPage'));


const PageLoader = () => (
  <div className="flex items-center justify-center h-screen bg-ink">
    <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full"></div>
  </div>
);

const APP_NAME = 'Lynx';


function AppLayout({ children }) {
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
      { id: 'dashboard', path: '/', label: t('nav.dashboard'), icon: FaHome, end: true },
      { id: 'servers', path: '/servers', label: t('nav.servers'), icon: FaServer },
      { id: 'templates', path: '/templates', label: t('nav.templates'), icon: FaLayerGroup },
    ];
    
    if (isAdmin) {
      items.push({ id: 'users', path: '/users', label: t('nav.users'), icon: FaUsers });
    }
    
    items.push({ id: 'settings', path: '/settings', label: t('nav.settings'), icon: FaCog });
    
    return items;
  }, [isAdmin, t]);

  
  const currentPageLabel = useMemo(() => {
    const currentPath = location.pathname;
    const item = sidebarItems.find(i => 
      i.end ? currentPath === i.path : currentPath.startsWith(i.path)
    );
    return item?.label || t('nav.dashboard');
  }, [location.pathname, sidebarItems, t]);

  
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

  
  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Sidebar Header */}
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-md bg-brand-500 inline-flex items-center justify-center shadow-card">
            <FaServer className="text-white" />
          </div>
          {(!isMobile && sidebarOpen) && <div className="font-semibold text-white">{APP_NAME}</div>}
        </div>
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto">
        <nav className="p-4">
          <div className="space-y-2">
            {sidebarItems.map(item => (
              <NavLink
                key={item.id}
                to={item.path}
                end={item.end}
                onClick={() => isMobile && setSidebarOpen(false)}
                className={({ isActive }) => `
                  w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
                  ${isActive ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}
                  ${(!isMobile && !sidebarOpen) ? 'justify-center' : ''}
                `}
                title={(!isMobile && !sidebarOpen) ? item.label : undefined}
              >
                <item.icon className="text-lg flex-shrink-0" />
                {(!isMobile && sidebarOpen) && (
                  <div className="flex items-center justify-between w-full min-w-0">
                    <span className="truncate">{item.label}</span>
                  </div>
                )}
              </NavLink>
            ))}
          </div>
        </nav>
      </div>

      {/* Sidebar Footer */}
      <div className="mt-auto p-4 border-t border-white/10 bg-black/30 backdrop-blur supports-[backdrop-filter]:bg-black/20">
        {/* Language Switcher */}
        <div className={`mb-3 ${(!isMobile && !sidebarOpen) ? 'flex justify-center' : ''}`}>
          <LanguageSwitcherCompact />
        </div>

        {/* User Section */}
        <div
          className={`flex items-center gap-3 mb-3 cursor-pointer hover:bg-white/10 rounded-lg p-2 ${(!isMobile && !sidebarOpen) ? 'justify-center' : ''}`}
          onClick={() => { navigate('/settings'); if (isMobile) setSidebarOpen(false); }}
          role="button"
          tabIndex={0}
        >
          {currentUser && (
            <>
              <div className="w-8 h-8 bg-brand-500 rounded-full flex items-center justify-center flex-shrink-0">
                <FaUsers className="text-sm text-white" />
              </div>
              {(!isMobile && sidebarOpen) && (
                <div className="text-sm min-w-0">
                  <div className="text-white font-medium truncate">{currentUser.username}</div>
                  <div className="text-white/60 truncate">{currentUser.role}</div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Logout Button */}
        <button
          onClick={logout}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors ${(!isMobile && !sidebarOpen) ? 'justify-center' : ''}`}
          title={(!isMobile && !sidebarOpen) ? 'Logout' : undefined}
        >
          <FaArrowLeft className="flex-shrink-0" />
          {(!isMobile && sidebarOpen) && <span>Logout</span>}
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
              <div className="absolute inset-0 bg-black/60" onClick={() => setSidebarOpen(false)} />
              <div className="relative w-64 bg-black/20 border-r border-white/10">{sidebarContent}</div>
            </div>
          ) : null;
        }

        return (
          <div className={`${sidebarOpen ? 'w-64' : 'w-16'} bg-black/20 border-r border-white/10 transition-all duration-300 flex flex-col sticky top-0 h-screen`}>
            {sidebarContent}
          </div>
        );
      })()}

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        <header className="border-b border-white/10 bg-ink/80 backdrop-blur supports-[backdrop-filter]:bg-ink/60">
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
              <div className="hidden sm:block text-sm text-white/70">
                Welcome back, {currentUser?.username || 'User'}
              </div>
            </div>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 min-h-0 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}


function ProtectedRoute({ children }) {
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
  
  return <AppLayout>{children}</AppLayout>;
}


function AdminRoute({ children }) {
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
  
  return <AppLayout>{children}</AppLayout>;
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
      } catch {}
    }
    
    fetchVersions();
    return () => { cancelled = true; };
  }, [selectedType]);

  
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
        } catch {}
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
  }, [name, selectedType, version, hostPort, minRam, maxRam, loaderVersion, installerVersion, globalData, showToast, navigate]);

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
        loaderVersion={loaderVersion}
        setLoaderVersion={setLoaderVersion}
        loaderVersionsData={loaderVersionsData}
        installerVersion={installerVersion}
        setInstallerVersion={setInstallerVersion}
      />
    </React.Suspense>
  );
}


function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPageWrapper />} />
      <Route path="/change-password" element={<MustChangePasswordPage />} />
      
      {/* Protected routes */}
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/servers" element={<ProtectedRoute><ServersPage /></ProtectedRoute>} />
      <Route path="/servers/:serverId" element={<ProtectedRoute><ServerDetailsPage /></ProtectedRoute>} />
      <Route path="/servers/:serverId/:tab" element={<ProtectedRoute><ServerDetailsPage /></ProtectedRoute>} />
      <Route path="/templates" element={<ProtectedRoute><TemplatesPageWrapper /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
      
      {/* Admin routes */}
      <Route path="/users" element={<AdminRoute><UsersPage /></AdminRoute>} />
      
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
