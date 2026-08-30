import React, { useEffect, useState, useMemo } from 'react';
import { API, authHeaders } from '../context/AppContext';

function parseRamToGb(value) {
  if (!value) return 4;
  const s = String(value).trim().toUpperCase();
  const m = s.match(/^(\d+(?:\.\d+)?)\s*([KMG]?)/);
  if (!m) return 4;
  const n = parseFloat(m[1]);
  const u = m[2] || 'M';
  if (u === 'G') return Math.round(n);
  if (u === 'M') return Math.max(1, Math.round(n / 1024));
  if (u === 'K') return Math.max(1, Math.round(n / 1024 / 1024));
  return Math.round(n / 1024);
}

function gbToRamString(gb) {
  return `${gb}G`;
}

export default function RamSlider({ value, onChange, showCategories = true, label }) {
  const [hostMax, setHostMax] = useState(25); // fallback matches picture
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function fetchHostRam() {
      try {
        // Try system-info (detailed) then quick health as fallback
        const headers = authHeaders();
        let r = await fetch(`${API}/health/system-info`, { headers });
        if (!r.ok) r = await fetch(`${API}/health/quick`);
        if (!r.ok) throw new Error('no health');
        const data = await r.json();
        // data.memory_total_gb or data.system_info.memory_total_gb or data.memory_total_gb
        let total = null;
        if (typeof data.memory_total_gb === 'number') total = data.memory_total_gb;
        else if (data.system_info && typeof data.system_info.memory_total_gb === 'number') total = data.system_info.memory_total_gb;
        else if (data.system_info && typeof data.system_info.memory_total_gb === 'number') total = data.system_info.memory_total_gb;
        // quick health doesn't give memory_total, so peek at diagnostics or fallback to 32
        if (!total && data.checks) {
          // try another endpoint: database pool? no
        }
        // If still no total, try /api/system-info alternative via psutil directly? Use 32
        if (!total) {
          // try to infer from /api/servers/stats? not
          total = 0;
        }
        if (total && !cancelled) {
          const gb = Math.max(4, Math.floor(total));
          setHostMax(gb);
        }
      } catch {
        // keep default 25
      } finally {
        if (!cancelled) setFetching(false);
      }
    }
    fetchHostRam();
    return () => { cancelled = true; };
  }, []);

  const currentGb = useMemo(() => parseRamToGb(value), [value]);
  const maxGb = hostMax;
  const minGb = 1;

  const handleSlider = (e) => {
    const gb = parseInt(e.target.value, 10);
    if (onChange) onChange(gbToRamString(gb));
  };

  // Category markers — evenly spaced so ticks are visually balanced
  // (accurate to the *picture*, not to absolute GB). Host max still drives the slider range.
  const categories = [
    { label: 'Vanilla Servers', pos: 0 },
    { label: 'Plugin Servers', pos: 25 },
    { label: 'Modpacks', pos: 50 },
    { label: 'Large Modpacks', pos: 75 },
    { label: 'Communities', pos: 100 },
  ];

  // For edit mode without categories, max is just hostMax
  const pct = ((currentGb - minGb) / Math.max(1, maxGb - minGb)) * 100;

  return (
    <div className="w-full py-2">
      {showCategories && (
        <div className="relative mb-6 h-10">
          {/* labels + ticks evenly spaced */}
          {categories.map((c) => (
            <div
              key={c.label}
              className="absolute flex flex-col items-center"
              style={{
                left: `${c.pos}%`,
                transform: c.pos === 0 ? 'translateX(0)' : c.pos === 100 ? 'translateX(-100%)' : 'translateX(-50%)',
              }}
            >
              <span className="bg-[#1e2440] text-white/80 px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap">
                {c.label}
              </span>
              <span className="mt-1 w-px h-3 bg-white/25" />
            </div>
          ))}
          {/* subtle baseline for ticks */}
          <div className="absolute left-0 right-0 top-[34px] h-px bg-white/10" />
        </div>
      )}
      <div className="relative">
        <input
          type="range"
          min={minGb}
          max={maxGb}
          step={1}
          value={Math.min(Math.max(currentGb, minGb), maxGb)}
          onChange={handleSlider}
          className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-purple-500"
          style={{
            background: `linear-gradient(to right, #a855f7 0%, #a855f7 ${pct}%, rgba(255,255,255,0.1) ${pct}%, rgba(255,255,255,0.1) 100%)`,
          }}
        />
        {/* custom thumb via CSS */}
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
        <span>1GB</span>
        <span className="text-white font-medium">{currentGb}GB</span>
        <span>{maxGb}GB {fetching ? '' : ''}</span>
      </div>
      {label && <div className="text-[11px] text-white/40 mt-1">{label}</div>}
    </div>
  );
}
