import React, { useState, useRef, useCallback, useEffect } from 'react';
import { FaSave, FaTimes } from 'react-icons/fa';
import { API } from '../../lib/api';
import { authHeaders } from '../../context/AppContext';
import { useTranslation } from '../../i18n';

export default function EditingPanel({ serverName, filePath, initialContent, onClose }) {
  const { t } = useTranslation();
  const [content, setContent] = useState(initialContent || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [cursorLine, setCursorLine] = useState(1);
  const [cursorCol, setCursorCol] = useState(1);
  const textareaRef = useRef(null);
  const lineNumbersRef = useRef(null);

  const lineCount = content.split('\n').length;

  const updateCursorPos = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const pos = ta.selectionStart;
    const textBefore = content.substring(0, pos);
    const line = textBefore.split('\n').length;
    const lastNewline = textBefore.lastIndexOf('\n');
    const col = pos - lastNewline;
    setCursorLine(line);
    setCursorCol(col);
  }, [content]);

  // Sync line-number gutter scroll with textarea scroll
  const handleScroll = useCallback(() => {
    if (lineNumbersRef.current && textareaRef.current) {
      lineNumbersRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  }, []);

  // Set initial cursor position
  useEffect(() => {
    updateCursorPos();
  }, []);

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

  // Handle Tab key for indentation
  function handleKeyDown(e) {
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = textareaRef.current;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const newContent = content.substring(0, start) + '  ' + content.substring(end);
      setContent(newContent);
      // Restore cursor position after state update
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2;
        updateCursorPos();
      });
    }
  }

  return (
    <div className="bg-black/20 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-white/70">
          {t('servers.editing')}: <span className="text-white font-mono">{filePath}</span>
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

      <div className="relative rounded bg-black/40 border border-white/10 overflow-hidden">
        <div className="flex h-96">
          {/* Line numbers gutter */}
          <div
            ref={lineNumbersRef}
            className="flex-shrink-0 overflow-hidden select-none bg-white/5 border-r border-white/10 text-right py-2 px-2"
            style={{ width: `${Math.max(3, String(lineCount).length + 1)}ch` }}
            aria-hidden="true"
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div
                key={i + 1}
                className={`text-xs font-mono leading-[20px] ${
                  i + 1 === cursorLine ? 'text-white' : 'text-white/30'
                }`}
              >
                {i + 1}
              </div>
            ))}
          </div>
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            className="flex-1 bg-transparent p-2 text-sm font-mono text-white resize-none outline-none"
            style={{ lineHeight: '20px', tabSize: 2 }}
            value={content}
            onChange={(e) => { setContent(e.target.value); requestAnimationFrame(updateCursorPos); }}
            onKeyUp={updateCursorPos}
            onClick={updateCursorPos}
            onScroll={handleScroll}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            wrap="off"
          />
        </div>
        {/* Status bar */}
        <div className="flex items-center justify-between px-3 py-1 bg-white/5 border-t border-white/10 text-xs text-white/50 font-mono">
          <span>Ln {cursorLine}, Col {cursorCol}</span>
          <span>{lineCount} lines · {content.length} chars</span>
        </div>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded bg-brand-500 hover:bg-brand-400 disabled:opacity-50 px-4 py-2 inline-flex items-center gap-2 text-sm font-medium"
        >
          <FaSave />
          {saving ? t('servers.saving') : t('servers.save')}
        </button>
        <button
          onClick={onClose}
          className="rounded bg-white/10 hover:bg-white/20 px-4 py-2 text-sm"
        >
          {t('servers.cancel')}
        </button>
      </div>
    </div>
  );
}
