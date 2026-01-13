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
const ACCENT_COLOR_KEY = 'lynx_accent_color';

export function ThemeProvider({ children }) {
  const [themeMode, setThemeModeInternal] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(THEME_MODE_KEY) || 'dark';
    }
    return 'dark';
  });

  const [accentColor, setAccentColorInternal] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(ACCENT_COLOR_KEY) || 'blue';
    }
    return 'blue';
  });

  const [colorblindMode, setColorblindMode] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(COLORBLIND_KEY) === 'on';
    }
    return false;
  });

  // Apply theme mode
  useEffect(() => {
    if (typeof document !== 'undefined') {
      let effectiveTheme = themeMode;
      // Handle system preference
      if (themeMode === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        effectiveTheme = prefersDark ? 'dark' : 'light';
      }
      document.documentElement.setAttribute('data-theme', effectiveTheme);
      if (document.body) {
        document.body.setAttribute('data-theme', effectiveTheme);
      }
    }
    if (typeof window !== 'undefined') {
      localStorage.setItem(THEME_MODE_KEY, themeMode);
    }
  }, [themeMode]);

  // Apply accent color
  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-accent', accentColor);
      if (document.body) {
        document.body.setAttribute('data-accent', accentColor);
      }
    }
    if (typeof window !== 'undefined') {
      localStorage.setItem(ACCENT_COLOR_KEY, accentColor);
    }
  }, [accentColor]);

  // Listen for system theme changes
  useEffect(() => {
    if (themeMode !== 'system' || typeof window === 'undefined') return;
    
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) => {
      const effectiveTheme = e.matches ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', effectiveTheme);
      if (document.body) {
        document.body.setAttribute('data-theme', effectiveTheme);
      }
    };
    
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
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

  const setThemeMode = useCallback((mode) => {
    setThemeModeInternal(mode);
  }, []);

  const setAccentColor = useCallback((color) => {
    setAccentColorInternal(color);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeModeInternal(prev => prev === 'dark' ? 'light' : 'dark');
  }, []);

  const toggleColorblind = useCallback(() => {
    setColorblindMode(prev => !prev);
  }, []);

  const value = useMemo(() => ({
    themeMode,
    accentColor,
    colorblindMode,
    setThemeMode,
    setAccentColor,
    toggleTheme,
    toggleColorblind,
  }), [themeMode, accentColor, colorblindMode, setThemeMode, setAccentColor, toggleTheme, toggleColorblind]);

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
