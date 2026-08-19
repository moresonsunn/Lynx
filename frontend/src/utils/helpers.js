// Utility functions for Lynx Game Server Panel

/**
 * URL-encode a server name for use in API paths
 * Handles spaces, special characters, etc.
 */
export const encodeServerName = (name) => {
  if (!name) return '';
  return encodeURIComponent(name);
};

/**
 * Build a full API URL for a server-specific endpoint
 * Automatically encodes the server name
 */
export const buildServerUrl = (serverName, endpoint) => {
  const base = '/api/servers';
  return `${base}/${encodeServerName(serverName)}${endpoint}`;
};

/**
 * Build a full API URL for a schedule endpoint
 */
export const buildScheduleUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/schedules')}${endpoint}`;
};

/**
 * Build a full API URL for a config endpoint
 */
export const buildConfigUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/config')}${endpoint}`;
};

/**
 * Build a full API URL for a files endpoint
 */
export const buildFilesUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/files')}${endpoint}`;
};

/**
 * Build a full API URL for a console/logs endpoint
 */
export const buildConsoleUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/console')}${endpoint}`;
};

/**
 * Build a full API URL for a backups endpoint
 */
export const buildBackupsUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/backups')}${endpoint}`;
};

/**
 * Build a full API URL for a players endpoint
 */
export const buildPlayersUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/players')}${endpoint}`;
};

/**
 * Build a full API URL for a worlds endpoint
 */
export const buildWorldsUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/worlds')}${endpoint}`;
};

/**
 * Build a full API URL for a stats endpoint
 */
export const buildStatsUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/stats')}${endpoint}`;
};

/**
 * Build a full API URL for a power endpoint (start/stop/restart)
 */
export const buildPowerUrl = (serverName, endpoint = '') => {
  return `${buildServerUrl(serverName, '/power')}${endpoint}`;
};

/**
 * Build a full API URL for a java-versions endpoint
 */
export const buildJavaVersionsUrl = (serverName) => {
  return buildServerUrl(serverName, '/java-versions');
};

/**
 * Build a full API URL for a java-args endpoint
 */
export const buildJavaArgsUrl = (serverName) => {
  return buildServerUrl(serverName, '/java-args');
};

/**
 * Build a full API URL for a file endpoint
 */
export const buildFileUrl = (serverName, path) => {
  return buildServerUrl(serverName, `/file?path=${encodeURIComponent(path)}`);
};

/**
 * Build a full API URL for an upload endpoint
 */
export const buildUploadUrl = (serverName, path) => {
  return buildServerUrl(serverName, `/upload?path=${encodeURIComponent(path)}`);
};

/**
 * Build a full API URL for a download endpoint
 */
export const buildDownloadUrl = (serverName, path) => {
  return buildServerUrl(serverName, `/download?path=${encodeURIComponent(path)}`);
};

/**
 * Build a full API URL for a rename endpoint
 */
export const buildRenameUrl = (serverName) => {
  return buildServerUrl(serverName, '/rename');
};

/**
 * Build a full API URL for a zip endpoint
 */
export const buildZipUrl = (serverName) => {
  return buildServerUrl(serverName, '/zip');
};

/**
 * Build a full API URL for an unzip endpoint
 */
export const buildUnzipUrl = (serverName) => {
  return buildServerUrl(serverName, '/unzip');
};

/**
 * Build a full API URL for a mkdir endpoint
 */
export const buildMkdirUrl = (serverName) => {
  return buildServerUrl(serverName, '/mkdir');
};

/**
 * Build a full API URL for a server info endpoint
 */
export const buildServerInfoUrl = (serverName) => {
  return buildServerUrl(serverName, '/info');
};

/**
 * Build a full API URL for a server logs endpoint
 */
export const buildLogsUrl = (serverName, tail = 200) => {
  return buildServerUrl(serverName, `/logs?tail=${tail}`);
};

/**
 * Build a full API URL for a send command endpoint
 */
export const buildCommandUrl = (serverName) => {
  return buildServerUrl(serverName, '/command');
};

/**
 * Build a full API URL for a world endpoint
 */
export const buildWorldUrl = (serverName, worldName, endpoint = '') => {
  return buildServerUrl(serverName, `/worlds/${encodeServerName(worldName)}${endpoint}`);
};

/**
 * Build a full API URL for a backup schedule endpoint
 */
export const buildBackupScheduleUrl = (serverName, endpoint = '') => {
  return buildServerUrl(serverName, `/backup-schedule${endpoint}`);
};

/**
 * Generic helper to create URL with query parameters
 */
export const buildUrlWithQuery = (baseUrl, params = {}) => {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, value);
    }
  });
  const queryString = searchParams.toString();
  return queryString ? `${baseUrl}?${queryString}` : baseUrl;
};

/**
 * Parse server name from various server object formats
 */
export const getServerName = (server) => {
  if (!server) return '';
  return server.name || server.server_name || server.container_name || server.id || '';
};

/**
 * Validate server name is safe for use in URLs
 */
export const isValidServerName = (name) => {
  if (!name || typeof name !== 'string') return false;
  // Allow alphanumeric, spaces, dashes, underscores, dots
  return /^[a-zA-Z0-9\s\-_.]+$/.test(name);
};

/**
 * Sanitize server name for display
 */
export const sanitizeServerName = (name) => {
  if (!name) return 'Unknown Server';
  return name.trim();
};

/**
 * Format server status for display
 */
export const formatServerStatus = (status) => {
  const statusMap = {
    running: { label: 'Running', color: 'text-green-400', bg: 'bg-green-500/20' },
    stopped: { label: 'Stopped', color: 'text-red-400', bg: 'bg-red-500/20' },
    starting: { label: 'Starting', color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
    stopping: { label: 'Stopping', color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
    restarting: { label: 'Restarting', color: 'text-blue-400', bg: 'bg-blue-500/20' },
    error: { label: 'Error', color: 'text-red-400', bg: 'bg-red-500/20' },
    unknown: { label: 'Unknown', color: 'text-white/50', bg: 'bg-white/10' },
  };
  return statusMap[status?.toLowerCase()] || statusMap.unknown;
};

/**
 * Format bytes to human readable string
 */
export const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

/**
 * Format duration in seconds to human readable string
 */
export const formatDuration = (seconds) => {
  if (!seconds || seconds < 0) return '0s';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
};

/**
 * Format date string to relative time or absolute date
 */
export const formatDate = (dateStr) => {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
};

/**
 * Generate a random ID
 */
export const generateId = () => {
  return Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
};

/**
 * Debounce function
 */
export const debounce = (fn, delay) => {
  let timeoutId;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
};

/**
 * Throttle function
 */
export const throttle = (fn, limit) => {
  let inThrottle;
  return (...args) => {
    if (!inThrottle) {
      fn(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
};

/**
 * Deep clone an object
 */
export const deepClone = (obj) => {
  return JSON.parse(JSON.stringify(obj));
};

/**
 * Check if object is empty
 */
export const isEmpty = (obj) => {
  if (!obj) return true;
  if (Array.isArray(obj)) return obj.length === 0;
  return Object.keys(obj).length === 0;
};

/**
 * Get nested value from object using dot notation path
 */
export const getNestedValue = (obj, path, defaultValue = undefined) => {
  if (!obj || !path) return defaultValue;
  const keys = path.split('.');
  let current = obj;
  for (const key of keys) {
    if (current === null || current === undefined || typeof current !== 'object') {
      return defaultValue;
    }
    current = current[key];
  }
  return current !== undefined ? current : defaultValue;
};

/**
 * Set nested value in object using dot notation path
 */
export const setNestedValue = (obj, path, value) => {
  if (!obj || !path) return obj;
  const keys = path.split('.');
  let current = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    if (!(key in current) || typeof current[key] !== 'object') {
      current[key] = {};
    }
    current = current[key];
  }
  current[keys[keys.length - 1]] = value;
  return obj;
};

export default {
  encodeServerName,
  buildServerUrl,
  buildScheduleUrl,
  buildConfigUrl,
  buildFilesUrl,
  buildConsoleUrl,
  buildBackupsUrl,
  buildPlayersUrl,
  buildWorldsUrl,
  buildStatsUrl,
  buildPowerUrl,
  buildJavaVersionsUrl,
  buildJavaArgsUrl,
  buildFileUrl,
  buildUploadUrl,
  buildDownloadUrl,
  buildRenameUrl,
  buildZipUrl,
  buildUnzipUrl,
  buildMkdirUrl,
  buildServerInfoUrl,
  buildLogsUrl,
  buildCommandUrl,
  buildWorldUrl,
  buildBackupScheduleUrl,
  buildUrlWithQuery,
  getServerName,
  isValidServerName,
  sanitizeServerName,
  formatServerStatus,
  formatBytes,
  formatDuration,
  formatDate,
  generateId,
  debounce,
  throttle,
  deepClone,
  isEmpty,
  getNestedValue,
  setNestedValue,
};