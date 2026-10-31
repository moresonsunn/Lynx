import React, { useEffect, useState } from 'react';
import {
  FaUpload,
  FaDownload,
  FaFolderOpen,
  FaArchive,
  FaSync,
  FaGlobe,
  FaCheckCircle,
} from 'react-icons/fa';
import { API, authHeaders, getStoredToken } from '../../lib/api';
import { useTranslation } from '../../i18n';

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 MB';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb.toFixed(1)} MB`;
}

export default function WorldsPanel({ serverName, onOpenInFiles }) {
  const { t } = useTranslation();
  const sName = serverName || '';
  const [worlds, setWorlds] = useState([]);
  const [activeLevel, setActiveLevel] = useState('world');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [backingUpWorld, setBackingUpWorld] = useState('');
  const [statusMessage, setStatusMessage] = useState('');

  async function refresh() {
    setLoading(true);
    setError('');
    try {
      if (!sName) {
        setWorlds([]);
        return;
      }
      const r = await fetch(`${API}/worlds/${encodeURIComponent(sName)}`, {
        headers: authHeaders(),
      });
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const d = await r.json();
      setWorlds(Array.isArray(d.worlds) ? d.worlds : []);
      if (d.active_level) setActiveLevel(d.active_level);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [serverName]);

  async function upload(e) {
    const file = e.target.files && e.target.files[0];
    if (!file || !sName) return;
    setUploading(true);
    setUploadPct(0);
    setError('');
    try {
      const token = getStoredToken();
      const targetWorld = activeLevel || 'world';
      const xhr = new XMLHttpRequest();
      xhr.open(
        'POST',
        `${API}/worlds/${encodeURIComponent(sName)}/upload?world_name=${encodeURIComponent(targetWorld)}`,
        true
      );
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          setUploadPct(Math.round((ev.loaded / ev.total) * 100));
        }
      };
      xhr.onload = async () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setStatusMessage(`World archive uploaded into "${targetWorld}"`);
          await refresh();
        } else {
          setError(`Upload failed (HTTP ${xhr.status})`);
        }
      };
      xhr.onerror = () => setError('Upload failed');
      const fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    } finally {
      setTimeout(() => {
        setUploading(false);
        setUploadPct(0);
      }, 400);
    }
  }

  async function download(worldPath) {
    if (!sName) return;
    try {
      const r = await fetch(
        `${API}/worlds/${encodeURIComponent(sName)}/download?world=${encodeURIComponent(worldPath)}`,
        { headers: authHeaders() }
      );
      if (!r.ok) throw new Error(`Download failed (HTTP ${r.status})`);
      const blob = await r.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const cleanName = String(worldPath || 'world').replace(/[\\/]/g, '_');
      a.download = `${sName}-${cleanName}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function backup(worldPath) {
    if (!sName) return;
    setBackingUpWorld(worldPath);
    setError('');
    setStatusMessage('');
    try {
      const r = await fetch(
        `${API}/worlds/${encodeURIComponent(sName)}/backup?world=${encodeURIComponent(worldPath)}&compression=zip`,
        { method: 'POST', headers: authHeaders() }
      );
      if (!r.ok) throw new Error(`Backup failed (HTTP ${r.status})`);
      const data = await r.json();
      setStatusMessage(`World backup created: ${data?.backup?.file || worldPath}`);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBackingUpWorld('');
    }
  }

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="rounded-xl bg-white/[0.03] border border-white/10 p-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FaGlobe className="text-brand-400 text-sm" />
            <h3 className="text-base font-semibold text-white">
              {t('servers.worlds') || 'Server Worlds'}
            </h3>
            {activeLevel && (
              <span className="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-white/60 font-mono">
                level-name={activeLevel}
              </span>
            )}
          </div>
          <p className="text-xs text-white/45 mt-1">
            Connected directly to the server directory ({worlds.length} world folder{worlds.length === 1 ? '' : 's'} detected).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
          >
            <FaSync className={`text-[11px] ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <label className="rounded-lg bg-brand-500 hover:bg-brand-400 px-3 py-1.5 cursor-pointer inline-flex items-center gap-2 text-xs font-medium text-white transition-colors">
            <FaUpload className="text-[11px]" /> {t('servers.uploadWorld') || 'Upload World Archive'}
            <input type="file" className="hidden" accept=".zip,.tar,.gz" onChange={upload} />
          </label>
        </div>
      </div>

      {statusMessage && (
        <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-3.5 py-2 text-xs text-emerald-300 flex items-center justify-between">
          <span>{statusMessage}</span>
          <button onClick={() => setStatusMessage('')} className="text-emerald-300/70 hover:text-emerald-200">✕</button>
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3.5 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      {uploading && (
        <div className="rounded-lg bg-white/5 border border-white/10 p-3">
          <div className="text-xs text-white/70 mb-1.5">
            {t('servers.uploading') || 'Uploading'} {uploadPct}%
          </div>
          <div className="w-full h-1.5 bg-white/10 rounded overflow-hidden">
            <div className="h-full bg-brand-500 transition-all" style={{ width: `${uploadPct}%` }} />
          </div>
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white/[0.02] border border-white/10 p-8 text-center text-white/50 text-sm">
          Scanning world directories…
        </div>
      ) : worlds.length > 0 ? (
        <div className="divide-y divide-white/10 rounded-xl bg-white/[0.02] border border-white/10 overflow-hidden">
          {worlds.map((w) => {
            const worldPath = w.path || w.name;
            const isBackingUp = backingUpWorld === worldPath;
            return (
              <div
                key={worldPath}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5 hover:bg-white/[0.03] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-white">{w.name}</span>
                    <span className="text-xs font-mono text-white/40 bg-white/5 px-1.5 py-0.5 rounded">
                      /{worldPath}
                    </span>
                    {w.is_active && (
                      <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
                        <FaCheckCircle className="text-[10px]" /> Active World
                      </span>
                    )}
                    {Array.isArray(w.dimensions) &&
                      w.dimensions.map((dim) => (
                        <span
                          key={dim}
                          className="text-[11px] px-2 py-0.5 rounded bg-white/5 text-white/60 border border-white/10"
                        >
                          {dim}
                        </span>
                      ))}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-white/45 mt-1">
                    <span>Size: {formatBytes(w.size)}</span>
                    {w.modified && (
                      <span>Modified: {new Date(w.modified * 1000).toLocaleString()}</span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {onOpenInFiles && (
                    <button
                      onClick={() => onOpenInFiles(worldPath)}
                      className="rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 px-2.5 py-1.5 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
                      title={`Open /${worldPath} in File Manager`}
                    >
                      <FaFolderOpen className="text-amber-400/80" />
                      Open Folder
                    </button>
                  )}
                  <button
                    onClick={() => backup(worldPath)}
                    disabled={isBackingUp}
                    className="rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 px-2.5 py-1.5 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    <FaArchive className="text-brand-400" />
                    {isBackingUp ? 'Backing up…' : 'Backup World'}
                  </button>
                  <button
                    onClick={() => download(worldPath)}
                    className="rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 px-2.5 py-1.5 text-xs text-white/80 inline-flex items-center gap-1.5 transition-colors"
                  >
                    <FaDownload className="text-emerald-400" />
                    Download ZIP
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-xl bg-white/[0.02] border border-white/10 p-8 text-center">
          <div className="text-sm text-white/60">
            {t('servers.noWorlds') || 'No world folders found yet.'}
          </div>
          <div className="text-xs text-white/35 mt-1">
            Start the server once to generate the world folder or upload an existing world archive.
          </div>
        </div>
      )}
    </div>
  );
}
