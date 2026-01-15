import React, { useState } from 'react';
import { FaSave, FaTimes } from 'react-icons/fa';
import { API } from '../../lib/api';
import { authHeaders } from '../../context/AppContext';

export default function EditingPanel({ serverName, filePath, initialContent, onClose }) {
  const [content, setContent] = useState(initialContent || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSave() {
    if (!serverName || !filePath) {
      setError('Server name or file path missing');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('content', content);
      const r = await fetch(
        `${API}/servers/${encodeURIComponent(serverName)}/file?path=${encodeURIComponent(filePath)}`,
        {
          method: 'POST',
          headers: authHeaders(),
          body: formData,
        }
      );
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${r.status}`);
      }
      onClose?.();
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-black/20 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-white/70">
          Editing: <span className="text-white font-mono">{filePath}</span>
        </div>
        <button
          onClick={onClose}
          className="text-white/60 hover:text-white p-1"
          title="Close"
        >
          <FaTimes />
        </button>
      </div>

      {error && (
        <div className="mb-3 text-sm text-red-400 bg-red-400/10 rounded px-3 py-2">
          {error}
        </div>
      )}

      <textarea
        className="w-full h-96 rounded bg-black/40 border border-white/10 p-3 text-sm font-mono text-white resize-y"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        spellCheck={false}
      />

      <div className="mt-3 flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded bg-brand-500 hover:bg-brand-400 disabled:opacity-50 px-4 py-2 inline-flex items-center gap-2 text-sm font-medium"
        >
          <FaSave />
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button
          onClick={onClose}
          className="rounded bg-white/10 hover:bg-white/20 px-4 py-2 text-sm"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
