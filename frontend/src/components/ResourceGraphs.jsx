import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { API, authHeaders } from '../context/AppContext';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { FaChartArea, FaSyncAlt, FaClock } from 'react-icons/fa';

const TIME_RANGES = [
  { label: '1h', hours: 1, resolution: 0 },
  { label: '6h', hours: 6, resolution: 5 },
  { label: '24h', hours: 24, resolution: 15 },
  { label: '7d', hours: 168, resolution: 60 },
];

function formatTime(ts, hours = 1) {
  if (!ts) return '';
  try {
    const normalized = ts.endsWith('Z') || ts.includes('+') ? ts : `${ts}Z`;
    const d = new Date(normalized);
    if (isNaN(d.getTime())) return String(ts).slice(11, 16);
    if (hours >= 24) {
      return d.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    }
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return String(ts).slice(11, 16);
  }
}

const CustomTooltip = ({ active, payload, label, hours }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#141827]/95 backdrop-blur border border-white/15 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-white/60 mb-1">{formatTime(label, hours)}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium tabular-nums">
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
          {p.name.includes('CPU') ? '%' : p.name.includes('RAM') ? ' MB' : p.name.includes('Net') ? ' MB/s' : ''}
        </p>
      ))}
    </div>
  );
};

export default function ResourceGraphs({ serverId }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState(TIME_RANGES[0]);

  const fetchHistory = useCallback(async () => {
    if (!serverId) return;
    setLoading(true);
    try {
      const res = await fetch(
        `${API}/servers/${encodeURIComponent(serverId)}/stats/history?hours=${range.hours}&resolution=${range.resolution}`,
        { headers: authHeaders() }
      );
      if (res.ok) {
        const json = await res.json();
        const rows = (json.data || []).map((r, i) => ({
          ...r,
          time: formatTime(r.ts, range.hours),
          __id: r.ts || i,
        }));
        setData(rows);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [serverId, range]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Auto-refresh every 30s
  useEffect(() => {
    const iv = setInterval(fetchHistory, 30000);
    return () => clearInterval(iv);
  }, [fetchHistory]);

  const chartCommon = useMemo(() => ({
    data,
    margin: { top: 5, right: 5, left: -15, bottom: 0 },
  }), [data]);

  const tickFormatter = useCallback((ts) => formatTime(ts, range.hours), [range.hours]);
  const showDots = data.length <= 3;

  if (!serverId) return null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <FaChartArea className="text-brand-400" />
            Resource History ({range.label})
          </h3>
          <p className="text-xs text-white/45">
            {data.length > 0 ? `${data.length} data points loaded` : 'Metrics sampled every 30 seconds while server is running'}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {TIME_RANGES.map(tr => (
            <button
              key={tr.label}
              type="button"
              onClick={() => setRange(tr)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                range.label === tr.label
                  ? 'bg-brand-500 text-white'
                  : 'bg-white/5 border border-white/10 text-white/65 hover:text-white hover:bg-white/10'
              }`}
            >
              <FaClock className="inline mr-1 text-[10px]" />{tr.label}
            </button>
          ))}
          <button
            type="button"
            onClick={fetchHistory}
            className="p-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 text-white/65 hover:text-white"
            title="Refresh metrics"
          >
            <FaSyncAlt className={`text-xs ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {data.length === 0 && !loading && (
        <div className="text-center py-12 bg-white/[0.02] border border-white/10 rounded-xl text-white/45 text-sm">
          No metrics recorded for this time window yet — start the server to begin collecting telemetry.
        </div>
      )}

      {data.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* CPU Chart */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-white/60 mb-3">CPU Usage (%)</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="ts" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} tickFormatter={tickFormatter} />
                <YAxis domain={[0, 100]} tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip hours={range.hours} />} />
                <Area type="monotone" dataKey="cpu" name="CPU" stroke="#3b82f6" fill="url(#cpuGrad)" strokeWidth={2} dot={showDots} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* RAM Chart */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-white/60 mb-3">Memory Usage (MB)</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="ramGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="ts" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} tickFormatter={tickFormatter} />
                <YAxis tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip hours={range.hours} />} />
                <Area type="monotone" dataKey="ram_used" name="RAM Used" stroke="#a855f7" fill="url(#ramGrad)" strokeWidth={2} dot={showDots} />
                <Area type="monotone" dataKey="ram_limit" name="RAM Limit" stroke="#6b7280" fill="none" strokeWidth={1} strokeDasharray="4 4" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Network Chart */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-white/60 mb-3">Network I/O (MB/s)</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="rxGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="txGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="ts" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} tickFormatter={tickFormatter} />
                <YAxis tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip hours={range.hours} />} />
                <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }} />
                <Area type="monotone" dataKey="net_rx_rate" name="Net RX" stroke="#22c55e" fill="url(#rxGrad)" strokeWidth={2} dot={showDots} />
                <Area type="monotone" dataKey="net_tx_rate" name="Net TX" stroke="#f59e0b" fill="url(#txGrad)" strokeWidth={2} dot={showDots} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Players Chart */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-white/60 mb-3">Players Online</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="playersGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="ts" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} tickFormatter={tickFormatter} />
                <YAxis allowDecimals={false} tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip hours={range.hours} />} />
                <Area type="stepAfter" dataKey="players" name="Players" stroke="#06b6d4" fill="url(#playersGrad)" strokeWidth={2} dot={showDots} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
