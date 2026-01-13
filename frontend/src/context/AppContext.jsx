import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';

// API configuration
const _defaultOrigin = (typeof window !== 'undefined' && window.location && window.location.origin)
  ? window.location.origin
  : 'http://localhost:8000';

export const API = (typeof window !== 'undefined') ? '/api' : 'http://localhost:8000';

// Token storage keys
const TOKEN_KEY = 'lynx_auth_token';
const THEME_MODE_KEY = 'lynx_theme_mode';
const COLORBLIND_KEY = 'lynx_colorblind_mode';

// Token management functions
export function getStoredToken() {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setStoredToken(token) {
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearStoredToken() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY);
  }
}

// Auth headers helper
export function authHeaders() {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Auth Context
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [authToken, setAuthToken] = useState(getStoredToken());
  const [currentUser, setCurrentUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  const isAuthenticated = !!authToken;
  const isAdmin = currentUser?.is_admin || currentUser?.role === 'admin' || currentUser?.roles?.includes('admin');

  // Validate token and fetch current user
  useEffect(() => {
    let cancelled = false;
    
    async function validate() {
      if (!authToken) {
        setLoading(false);
        return;
      }
      
      try {
        const r = await fetch(`${API}/auth/me`, { headers: authHeaders() });
        if (!r.ok) throw new Error('invalid');
        const user = await r.json();
        
        if (!cancelled) {
          setCurrentUser(user);
          setMustChangePassword(user.must_change_password || false);
        }
      } catch (_) {
        clearStoredToken();
        if (!cancelled) {
          setAuthToken('');
          setCurrentUser(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    
    validate();
    return () => { cancelled = true; };
  }, [authToken]);

  const login = useCallback(async (username, password) => {
    const body = new URLSearchParams({ username, password });
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body
    });
    
    if (!r.ok) {
      const payload = await r.json().catch(() => null);
      throw new Error((payload && (payload.detail || payload.message)) || `HTTP ${r.status}`);
    }
    
    const data = await r.json();
    const token = data && data.access_token;
    
    if (!token) throw new Error('Invalid login response');
    
    setStoredToken(token);
    setAuthToken(token);
    
    return data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API}/auth/logout`, { method: 'POST', headers: authHeaders() });
    } catch (_) {}
    
    clearStoredToken();
    setAuthToken('');
    setCurrentUser(null);
    
    // Reload to clear any in-memory state
    if (typeof window !== 'undefined') {
      window.location.href = '/login';
    }
  }, []);

  // Auto-logout after inactivity
  useEffect(() => {
    if (!isAuthenticated || typeof window === 'undefined') return undefined;
    
    let timeoutId = null;
    const INACTIVITY_TIMEOUT = 5 * 60 * 1000; // 5 minutes
    
    const resetTimer = () => {
      if (timeoutId) clearTimeout(timeoutId);
      timeoutId = setTimeout(logout, INACTIVITY_TIMEOUT);
    };

    const events = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'];
    events.forEach((evt) => window.addEventListener(evt, resetTimer, { passive: true }));
    resetTimer();

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      events.forEach((evt) => window.removeEventListener(evt, resetTimer));
    };
  }, [isAuthenticated, logout]);

  const value = useMemo(() => ({
    authToken,
    currentUser,
    isAuthenticated,
    isAdmin,
    loading,
    mustChangePassword,
    login,
    logout,
    authHeaders,
  }), [authToken, currentUser, isAuthenticated, isAdmin, loading, mustChangePassword, login, logout]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}

// Theme Context
const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  const [themeMode, setThemeMode] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(THEME_MODE_KEY) || 'dark';
    }
    return 'dark';
  });

  const [colorblindMode, setColorblindMode] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(COLORBLIND_KEY) === 'on';
    }
    return false;
  });

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', themeMode);
      if (document.body) {
        document.body.setAttribute('data-theme', themeMode);
      }
    }
    if (typeof window !== 'undefined') {
      localStorage.setItem(THEME_MODE_KEY, themeMode);
    }
  }, [themeMode]);

  useEffect(() => {
    const flag = colorblindMode ? 'on' : 'off';
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-colorblind', flag);
      if (document.body) {
        document.body.setAttribute('data-colorblind', flag);
      }
    }
    if (typeof window !== 'undefined') {
      localStorage.setItem(COLORBLIND_KEY, flag);
    }
  }, [colorblindMode]);

  const toggleTheme = useCallback(() => {
    setThemeMode(prev => prev === 'dark' ? 'light' : 'dark');
  }, []);

  const toggleColorblind = useCallback(() => {
    setColorblindMode(prev => !prev);
  }, []);

  const value = useMemo(() => ({
    themeMode,
    colorblindMode,
    toggleTheme,
    toggleColorblind,
  }), [themeMode, colorblindMode, toggleTheme, toggleColorblind]);

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
}

// Combined App Providers
export function AppProviders({ children }) {
  return (
    <ThemeProvider>
      <AuthProvider>
        {children}
      </AuthProvider>
    </ThemeProvider>
  );
}

export default AppProviders;
