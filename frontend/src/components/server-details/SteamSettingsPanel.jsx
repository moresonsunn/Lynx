import React, { useState, useEffect, useCallback } from 'react';
import { API, authHeaders } from '../../context/AppContext';
import {
  FaCog,
  FaSave,
  FaSync,
  FaUndo,
  FaExclamationTriangle,
  FaCheckCircle,
  FaInfoCircle,
  FaSlidersH,
} from 'react-icons/fa';

export default function SteamSettingsPanel({ serverName, serverId, gameSlug }) {
  const [schema, setSchema] = useState([]);
  const [settings, setSettings] = useState({});
  const [originalSettings, setOriginalSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [hasSettings, setHasSettings] = useState(true);
  const [configFile, setConfigFile] = useState('');
  const [gameName, setGameName] = useState('');
  const [configExists, setConfigExists] = useState(false);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const slug = (gameSlug || '').replace(/^steam:/i, '');
      const qp = slug ? `?game=${encodeURIComponent(slug)}` : '';
      const res = await fetch(`${API}/steam/server/${serverName}/settings${qp}`, {
        headers: authHeaders(),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Failed to load settings: ${res.status}`);
      }
      const data = await res.json();
      if (data.error || !data.schema || data.schema.length === 0) {
        setHasSettings(false);
        setLoading(false);
        return;
      }
      setSchema(data.schema || []);
      setSettings(data.settings || {});
      setOriginalSettings(data.settings || {});
      setConfigFile(data.config_file || '');
      setGameName(data.display_name || '');
      setConfigExists(data.config_exists ?? false);
      setHasSettings(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [serverName, gameSlug]);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleChange = (key, value, field) => {
    setSettings(prev => {
      const next = { ...prev };
      if (field.type === 'float') {
        next[key] = value === '' ? field.default : parseFloat(value);
      } else if (field.type === 'int') {
        next[key] = value === '' ? field.default : parseInt(value, 10);
      } else if (field.type === 'bool') {
        next[key] = value;
      } else {
        next[key] = value;
      }
      return next;
    });
    setSuccess(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const slug = (gameSlug || '').replace(/^steam:/i, '');
      const qp = slug ? `?game=${encodeURIComponent(slug)}` : '';
      const res = await fetch(`${API}/steam/server/${serverName}/settings${qp}`, {
        method: 'PUT',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Failed to save: ${res.status}`);
      }
      const data = await res.json();
      setSuccess(data.message || 'Settings saved successfully!');
      setOriginalSettings({ ...settings });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setSettings({ ...originalSettings });
    setSuccess(null);
    setError(null);
  };

  const handleResetToDefaults = () => {
    const defaults = {};
    schema.forEach(field => {
      defaults[field.key] = field.default;
    });
    setSettings(defaults);
    setSuccess(null);
  };

  const hasChanges = JSON.stringify(settings) !== JSON.stringify(originalSettings);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <FaSync className="animate-spin text-2xl text-white/40 mr-3" />
        <span className="text-white/60">Loading game settings...</span>
      </div>
    );
  }

  if (!hasSettings) {
    return (
      <div className="glassmorphism rounded-xl p-8 text-center">
        <FaCog className="text-4xl text-white/20 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-white/70 mb-2">No Configurable Settings</h3>
        <p className="text-white/40 text-sm max-w-md mx-auto">
          This game doesn't have configurable world settings yet.
          You can still edit config files directly via the Files tab.
        </p>
      </div>
    );
  }

  // Group settings by category (based on type patterns)
  const groups = [];
  const boolSettings = schema.filter(s => s.type === 'bool');
  const numberSettings = schema.filter(s => s.type === 'float' || s.type === 'int');
  const selectSettings = schema.filter(s => s.type === 'select');
  const stringSettings = schema.filter(s => s.type === 'string');

  if (stringSettings.length > 0) groups.push({ label: 'Server', fields: stringSettings });
  if (selectSettings.length > 0) groups.push({ label: 'Game Mode', fields: selectSettings });
  if (numberSettings.length > 0) groups.push({ label: 'Rates & Values', fields: numberSettings });
  if (boolSettings.length > 0) groups.push({ label: 'Toggles', fields: boolSettings });

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <FaSlidersH className="text-brand-400" />
            {gameName || 'Game'} Settings
          </h2>
          {configFile && (
            <p className="text-xs text-white/40 mt-1 font-mono">{configFile}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleResetToDefaults}
            className="px-3 py-1.5 rounded-lg text-xs bg-white/5 hover:bg-white/10 text-white/60 hover:text-white transition-all flex items-center gap-1.5"
            title="Reset all to defaults"
          >
            <FaUndo className="text-[10px]" />
            Defaults
          </button>
          {hasChanges && (
            <button
              onClick={handleReset}
              className="px-3 py-1.5 rounded-lg text-xs bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-300 transition-all flex items-center gap-1.5"
            >
              <FaUndo className="text-[10px]" />
              Undo
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium flex items-center gap-2 transition-all ${
              hasChanges
                ? 'bg-brand-600 hover:bg-brand-500 text-white'
                : 'bg-white/5 text-white/30 cursor-not-allowed'
            }`}
          >
            {saving ? <FaSync className="animate-spin text-xs" /> : <FaSave className="text-xs" />}
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>

      {/* Status Messages */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 text-sm">
          <FaExclamationTriangle className="flex-shrink-0" />
          {error}
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-green-500/10 border border-green-500/20 text-green-300 text-sm">
          <FaCheckCircle className="flex-shrink-0" />
          {success}
        </div>
      )}
      {!configExists && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-300 text-sm">
          <FaInfoCircle className="flex-shrink-0" />
          Config file doesn't exist yet. Settings will be created when you save. Start the server first to generate default files.
        </div>
      )}

      {/* Settings Groups */}
      {groups.map(group => (
        <div key={group.label} className="glassmorphism rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-white/5">
            <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider">
              {group.label}
            </h3>
          </div>
          <div className="p-5 space-y-4">
            {group.fields.map(field => (
              <SettingField
                key={field.key}
                field={field}
                value={settings[field.key]}
                originalValue={originalSettings[field.key]}
                onChange={(val) => handleChange(field.key, val, field)}
              />
            ))}
          </div>
        </div>
      ))}

      {/* Restart reminder */}
      {hasChanges && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm">
          <FaExclamationTriangle className="flex-shrink-0" />
          <span>Remember to <strong>restart</strong> the server after saving for changes to take effect.</span>
        </div>
      )}
    </div>
  );
}


function SettingField({ field, value, originalValue, onChange }) {
  const isModified = value !== originalValue;
  const { type, label, key } = field;

  if (type === 'bool') {
    return (
      <div className="flex items-center justify-between group">
        <div className="flex-1">
          <label className="text-sm text-white/80 group-hover:text-white transition-colors">
            {label}
          </label>
          {isModified && <span className="ml-2 text-[10px] text-amber-400">modified</span>}
        </div>
        <button
          onClick={() => onChange(!value)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            value ? 'bg-brand-600' : 'bg-white/10'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              value ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </div>
    );
  }

  if (type === 'select') {
    return (
      <div className="flex items-center justify-between gap-4 group">
        <div className="flex-1 min-w-0">
          <label className="text-sm text-white/80 group-hover:text-white transition-colors">
            {label}
          </label>
          {isModified && <span className="ml-2 text-[10px] text-amber-400">modified</span>}
        </div>
        <select
          value={value ?? field.default}
          onChange={e => onChange(e.target.value)}
          className="bg-white/5 border border-white/10 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500 min-w-[140px]"
        >
          {(field.options || []).map(opt => (
            <option key={opt} value={opt} className="bg-[#1a1a2e] text-white">{opt}</option>
          ))}
        </select>
      </div>
    );
  }

  if (type === 'float' || type === 'int') {
    const numVal = value ?? field.default;
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const step = type === 'float' ? 0.1 : 1;

    return (
      <div className="group">
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm text-white/80 group-hover:text-white transition-colors">
            {label}
          </label>
          <div className="flex items-center gap-2">
            {isModified && <span className="text-[10px] text-amber-400">modified</span>}
            <input
              type="number"
              value={numVal}
              min={min}
              max={max}
              step={step}
              onChange={e => onChange(e.target.value)}
              className="w-20 bg-white/5 border border-white/10 text-white text-sm text-right rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
        </div>
        <input
          type="range"
          value={numVal}
          min={min}
          max={max}
          step={step}
          onChange={e => onChange(e.target.value)}
          className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer accent-brand-500"
        />
        <div className="flex justify-between text-[10px] text-white/30 mt-1">
          <span>{min}</span>
          <span className="text-white/40">{field.default}</span>
          <span>{max}</span>
        </div>
      </div>
    );
  }

  // string
  return (
    <div className="flex items-center justify-between gap-4 group">
      <div className="flex-shrink-0">
        <label className="text-sm text-white/80 group-hover:text-white transition-colors">
          {label}
        </label>
        {isModified && <span className="ml-2 text-[10px] text-amber-400">modified</span>}
      </div>
      <input
        type="text"
        value={value ?? ''}
        onChange={e => onChange(e.target.value)}
        placeholder={field.default || ''}
        className="flex-1 max-w-xs bg-white/5 border border-white/10 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
    </div>
  );
}
