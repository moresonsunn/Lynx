import React, { useEffect, useMemo, useState } from 'react';
import { FaChevronDown, FaChevronUp } from 'react-icons/fa';

/**
 * Friendly schedule builder — replaces raw cron text input.
 * Emits a cron string via onChange(cron) but the user never types cron.
 * Times are UTC (scheduler runs in UTC) — label says so explicitly.
 */

const DAYS = [
  { v: 'MON', label: 'Mon' },
  { v: 'TUE', label: 'Tue' },
  { v: 'WED', label: 'Wed' },
  { v: 'THU', label: 'Thu' },
  { v: 'FRI', label: 'Fri' },
  { v: 'SAT', label: 'Sat' },
  { v: 'SUN', label: 'Sun' },
];

function pad(n) {
  return String(n).padStart(2, '0');
}

export function cronToSummary(cron) {
  if (!cron) return '';
  try {
    const [mi, h, dom, mon, dow] = cron.trim().split(/\s+/);
    if (mi.startsWith('*/')) return `Every ${mi.slice(2)} minutes`;
    if (h.startsWith('*/')) return `Every ${h.slice(2)} hours at :${pad(mi)}`;
    if (dow !== '*' && dow !== '?') {
      const names = { MON: 'Mon', TUE: 'Tue', WED: 'Wed', THU: 'Thu', FRI: 'Fri', SAT: 'Sat', SUN: 'Sun', '1-5': 'Mon–Fri', '6,0': 'weekends', '0,6': 'weekends', '6,7': 'weekends' };
      return `Weekly on ${names[dow] || dow} at ${pad(h)}:${pad(mi)}`;
    }
    if (dom !== '*') return `Monthly on day ${dom} at ${pad(h)}:${pad(mi)}`;
    return `Daily at ${pad(h)}:${pad(mi)}`;
  } catch {
    return cron;
  }
}

export function cronToBuilder(cron) {
  const fallback = { mode: 'daily', hour: 2, minute: 0, days: ['MON'], dom: 1, everyH: 6, everyM: 30 };
  if (!cron) return fallback;
  try {
    const [mi, h, dom, , dow] = cron.trim().split(/\s+/);
    if (/^\*\/\d+$/.test(mi)) return { ...fallback, mode: 'minutes', everyM: parseInt(mi.slice(2), 10) || 30 };
    if (/^\*\/\d+$/.test(h)) return { ...fallback, mode: 'hours', everyH: parseInt(h.slice(2), 10) || 6, minute: parseInt(mi, 10) || 0 };
    if (dow && dow !== '*') {
      if (dow === '1-5' || dow === 'MON-FRI') return { ...fallback, mode: 'weekdays', hour: parseInt(h, 10) || 2, minute: parseInt(mi, 10) || 0 };
      if (dow === '6,0' || dow === '0,6' || dow === '6,7' || dow === 'SAT,SUN') return { ...fallback, mode: 'weekends', hour: parseInt(h, 10) || 2, minute: parseInt(mi, 10) || 0 };
      const single = dow.split(',')[0];
      return { ...fallback, mode: 'weekly', days: [single], hour: parseInt(h, 10) || 2, minute: parseInt(mi, 10) || 0 };
    }
    if (dom && dom !== '*') return { ...fallback, mode: 'monthly', dom: parseInt(dom, 10) || 1, hour: parseInt(h, 10) || 2, minute: parseInt(mi, 10) || 0 };
    return { ...fallback, mode: 'daily', hour: parseInt(h, 10) || 0, minute: parseInt(mi, 10) || 0 };
  } catch {
    return fallback;
  }
}

export function builderToCron(b) {
  const mi = pad(b.minute ?? 0);
  const h = String(b.hour ?? 2);
  switch (b.mode) {
    case 'minutes':
      return `*/${b.everyM || 30} * * * *`;
    case 'hours':
      return `${mi} */${b.everyH || 6} * * *`;
    case 'weekly': {
      const d = (b.days && b.days.length ? b.days : ['MON']).join(',');
      return `${mi} ${h} * * ${d}`;
    }
    case 'weekdays':
      return `${mi} ${h} * * 1-5`;
    case 'weekends':
      return `${mi} ${h} * * 6,0`;
    case 'monthly':
      return `${mi} ${h} ${b.dom || 1} * *`;
    case 'daily':
    default:
      return `${mi} ${h} * * *`;
  }
}

export default function ScheduleBuilder({ value, onChange }) {
  const [state, setState] = useState(() => cronToBuilder(value));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [raw, setRaw] = useState(value || '0 2 * * *');

  // sync when editing an existing task
  useEffect(() => {
    if (value && value !== raw) {
      setRaw(value);
      setState(cronToBuilder(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const emit = (next) => {
    setState(next);
    const cron = builderToCron(next);
    setRaw(cron);
    if (onChange) onChange(cron);
  };

  const summary = useMemo(() => cronToSummary(raw), [raw]);
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const minutes = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55];

  const set = (patch) => emit({ ...state, ...patch });

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1">Repeat</label>
          <select
            value={state.mode}
            onChange={(e) => set({ mode: e.target.value })}
            className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white"
          >
            <option value="daily">Daily</option>
            <option value="weekdays">Weekdays (Mon–Fri)</option>
            <option value="weekends">Weekends (Sat–Sun)</option>
            <option value="weekly">Weekly (pick day)</option>
            <option value="hours">Every X hours</option>
            <option value="minutes">Every X minutes</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
        {(state.mode === 'daily' || state.mode === 'weekdays' || state.mode === 'weekends' || state.mode === 'weekly' || state.mode === 'monthly') && (
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1">Time (UTC)</label>
            <div className="flex gap-2">
              <select value={state.hour} onChange={(e) => set({ hour: parseInt(e.target.value, 10) })} className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
                {hours.map((hh) => (<option key={hh} value={hh}>{pad(hh)}:00</option>))}
              </select>
              <select value={state.minute} onChange={(e) => set({ minute: parseInt(e.target.value, 10) })} className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
                {minutes.map((mm) => (<option key={mm} value={mm}>:{pad(mm)}</option>))}
              </select>
            </div>
          </div>
        )}
      </div>

      {state.mode === 'weekly' && (
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1">Day</label>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d) => {
              const active = (state.days || []).includes(d.v);
              return (
                <button
                  key={d.v}
                  type="button"
                  onClick={() => set({ days: [d.v] })}
                  className={`px-3 py-1.5 rounded-lg text-sm ${active ? 'bg-brand-500 text-white' : 'bg-white/10 text-white/70 hover:bg-white/20'}`}
                >
                  {d.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {state.mode === 'monthly' && (
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1">Day of month</label>
          <select value={state.dom} onChange={(e) => set({ dom: parseInt(e.target.value, 10) })} className="w-32 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
            {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (<option key={d} value={d}>{d}</option>))}
          </select>
        </div>
      )}

      {state.mode === 'hours' && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1">Every</label>
            <select value={state.everyH} onChange={(e) => set({ everyH: parseInt(e.target.value, 10) })} className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
              {[1, 2, 3, 4, 6, 8, 12].map((n) => (<option key={n} value={n}>{n} hours</option>))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1">At minute</label>
            <select value={state.minute} onChange={(e) => set({ minute: parseInt(e.target.value, 10) })} className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
              {minutes.map((mm) => (<option key={mm} value={mm}>:{pad(mm)}</option>))}
            </select>
          </div>
        </div>
      )}

      {state.mode === 'minutes' && (
        <div>
          <label className="block text-sm font-medium text-white/70 mb-1">Every</label>
          <select value={state.everyM} onChange={(e) => set({ everyM: parseInt(e.target.value, 10) })} className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white">
            {[5, 10, 15, 30].map((n) => (<option key={n} value={n}>{n} minutes</option>))}
          </select>
        </div>
      )}

      <div className="flex items-center gap-2 text-sm bg-brand-500/10 border border-brand-500/20 rounded-lg px-3 py-2">
        <span className="text-brand-300">Runs {summary.toLowerCase()} (UTC)</span>
        <code className="ml-auto font-mono text-xs text-white/50">{raw}</code>
      </div>

      <button type="button" onClick={() => setShowAdvanced(!showAdvanced)} className="text-xs text-white/50 hover:text-white flex items-center gap-1">
        {showAdvanced ? <FaChevronUp /> : <FaChevronDown />} Advanced (raw cron)
      </button>
      {showAdvanced && (
        <input
          value={raw}
          onChange={(e) => { setRaw(e.target.value); if (onChange) onChange(e.target.value); }}
          className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-white font-mono text-sm"
          spellCheck={false}
        />
      )}
    </div>
  );
}
