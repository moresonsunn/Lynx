// Centralized API client for Lynx Game Server Panel
// Provides consistent authentication and error handling across all API calls

import { API, getStoredToken, clearStoredToken } from '../lib/api';

const API_BASE = API;

/**
 * Get authentication headers for API requests
 * Reads token from localStorage
 */
export const getAuthHeaders = () => {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/**
 * Build full URL for a server-specific endpoint
 * Properly encodes the server name
 */
export const buildServerUrl = (serverName, endpoint) => {
  return `${API_BASE}/servers/${encodeURIComponent(serverName)}${endpoint}`;
};

/**
 * Handle 401 Unauthorized responses
 * Clears token and redirects to login
 */
const handleUnauthorized = () => {
  clearStoredToken();
  // Use window.location to force full page reload and reset app state
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
};

/**
 * Generic fetch wrapper with authentication and error handling
 */
async function fetchWithAuth(url, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
    ...(options.headers || {}),
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  // Handle 401 - token expired/invalid
  if (response.status === 401) {
    handleUnauthorized();
    throw new Error('Session expired. Please log in again.');
  }

  // Handle 422 - validation error
  if (response.status === 422) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Validation error');
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP ${response.status}`);
  }

  return response;
}

/**
 * API client with common HTTP methods
 */
export const apiClient = {
  /**
   * GET request
   */
  get: (endpoint) => fetchWithAuth(endpoint, { method: 'GET' }),

  /**
   * POST request with JSON body
   */
  post: (endpoint, data) => fetchWithAuth(endpoint, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  /**
   * PUT request with JSON body
   */
  put: (endpoint, data) => fetchWithAuth(endpoint, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),

  /**
   * PATCH request with JSON body
   */
  patch: (endpoint, data) => fetchWithAuth(endpoint, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),

  /**
   * DELETE request
   */
  delete: (endpoint) => fetchWithAuth(endpoint, { method: 'DELETE' }),

  /**
   * POST request with FormData (for file uploads)
   */
  postForm: (endpoint, formData) => {
    const token = getStoredToken();
    return fetch(endpoint, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    }).then(response => {
      if (response.status === 401) {
        handleUnauthorized();
        throw new Error('Session expired. Please log in again.');
      }
      if (!response.ok) {
        return response.json().catch(() => ({})).then(err => {
          throw new Error(err.detail || `HTTP ${response.status}`);
        });
      }
      return response;
    });
  },

  /**
   * GET request for server-specific endpoints with encoded server name
   */
  getServer: (serverName, endpoint) => {
    const url = buildServerUrl(serverName, endpoint);
    return fetchWithAuth(url, { method: 'GET' });
  },

  /**
   * POST request for server-specific endpoints with encoded server name
   */
  postServer: (serverName, endpoint, data) => {
    const url = buildServerUrl(serverName, endpoint);
    return fetchWithAuth(url, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * PUT request for server-specific endpoints with encoded server name
   */
  putServer: (serverName, endpoint, data) => {
    const url = buildServerUrl(serverName, endpoint);
    return fetchWithAuth(url, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /**
   * DELETE request for server-specific endpoints with encoded server name
   */
  deleteServer: (serverName, endpoint) => {
    const url = buildServerUrl(serverName, endpoint);
    return fetchWithAuth(url, { method: 'DELETE' });
  },

  /**
   * POST request with FormData for server-specific endpoints
   */
  postServerForm: (serverName, endpoint, formData) => {
    const url = buildServerUrl(serverName, endpoint);
    const token = getStoredToken();
    return fetch(url, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    }).then(response => {
      if (response.status === 401) {
        handleUnauthorized();
        throw new Error('Session expired. Please log in again.');
      }
      if (!response.ok) {
        return response.json().catch(() => ({})).then(err => {
          throw new Error(err.detail || `HTTP ${response.status}`);
        });
      }
      return response;
    });
  },
};

/**
 * Helper to get server name from server object or ID
 */
export const getServerName = (server) => {
  if (!server) return '';
  return server.name || server.server_name || '';
};

/**
 * Helper to check if user is authenticated
 */
export const isAuthenticated = () => {
  return !!getStoredToken();
};

/**
 * Helper to get current auth token
 */
export const getAuthToken = () => getStoredToken();

export default apiClient;