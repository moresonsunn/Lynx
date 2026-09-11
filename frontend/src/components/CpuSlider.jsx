import React, { useEffect, useState } from 'react';
import { API, authHeaders } from '../context/AppContext';

/**
 * CPU core cap slider — null = unlimited.
 * Max defaults to host thread count (GET /api/health/system-info -> cpu_count).
 */
export default function CpuSlider({ value, onChange, label }) {
  const [hostMax, setHostMax] = useState(16);

  useEffect(() => {
    let cancelled = false;
    async function fetchHostCores() {
      try {
        const r = await fetch(`${API}/health/system-info`, { headers: authHeaders() });
        if (!r.ok) return;
        const data = await r.json();
        const total = data.cpu_count || data.cpu_threads;
        if (total && !cancelled) setHostMax(Math.max(2, Math.floor(total)));
      } catch {
        // keep default
      }
    }
    fetchHostCores();
    return () => { cancelled = true; };
  }, []);

  const limited = value !== null && value !== undefined;
  const current = limited ? Math.min(Math.max(parseInt(value, 10) || 1, 1), hostMax) : hostMax;
  const pct = ((current - 1) / Math.max(1, hostMax - 1)) * 100;

  return (
    <div className="w-full py-2">
      <label className="flex items-center gap-2 cursor-pointer mb-2">
        <input
          type="checkbox"
          checked={limited}
          onChange={(e) => { if (onChange) onChange(e.target.checked ? Math.min(2, hostMax) : null); }}
          className="accent-purple-500 w-4 h-4"
        />
        <span className="text-xs text-white/70">Limit CPU cores</span>
        {!limited && <span className="text-[11px] text-white/40">(unlimited — can use all {hostMax} threads)</span>}
      </label>
      {limited && (
        <>
          <div className="relative">
            <input
              type="range"
              min={1}
              max={hostMax}
              step={1}
              value={current}
              onChange={(e) => { if (onChange) onChange(parseInt(e.target.value, 10)); }}
              className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-purple-500"
              style={{
                background: `linear-gradient(to right, #a855f7 0%, #a855f7 ${pct}%, rgba(255,255,255,0.1) ${pct}%, rgba(255,255,255,0.1) 100%)`,
              }}
            />
            <style>{`
              input[type=range]::-webkit-slider-thumb {
                appearance: none;
                width: 20px;
                height: 20px;
                border-radius: 9999px;
                background: white;
                border: 4px solid #a855f7;
                box-shadow: 0 0 0 4px rgba(168,85,247,0.3);
                cursor: pointer;
              }
              input[type=range]::-moz-range-thumb {
                width: 20px;
                height: 20px;
                border-radius: 9999px;
                background: white;
                border: 4px solid #a855f7;
                box-shadow: 0 0 0 4px rgba(168,85,247,0.3);
                cursor: pointer;
              }
            `}</style>
          </div>
          <div className="flex justify-between mt-2 text-xs text-white/60">
            <span>1 core</span>
            <span className="text-white font-medium">{current} core{current === 1 ? '' : 's'}</span>
            <span>{hostMax} threads</span>
          </div>
        </>
      )}
      {label && <div className="text-[11px] text-white/40 mt-1">{label}</div>}
    </div>
  );
}
