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

function formatTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z');
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts.slice(11, 16);
  }
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card/95 backdrop-blur border border-white/10 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-white/60 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium">
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}
          {p.name.includes('CPU') ? '%' : p.name.includes('RAM') ? ' MB' : p.name.includes('Net') ? ' MB' : ''}
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
        `${API}/servers/${serverId}/stats/history?hours=${range.hours}&resolution=${range.resolution}`,
        { headers: authHeaders() }
      );
      if (res.ok) {
        const json = await res.json();
        const rows = (json.data || []).map(r => ({
          ...r,
          time: formatTime(r.ts),
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

  // Auto-refresh every 30s for 1h view
  useEffect(() => {
    if (range.hours > 1) return;
    const iv = setInterval(fetchHistory, 30000);
    return () => clearInterval(iv);
  }, [fetchHistory, range.hours]);

  const chartCommon = useMemo(() => ({
    data,
    margin: { top: 5, right: 5, left: -15, bottom: 0 },
  }), [data]);

  if (!serverId) return null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <FaChartArea className="text-brand-400" />
          Resource History
        </h3>
        <div className="flex items-center gap-2">
          {TIME_RANGES.map(tr => (
            <button
              key={tr.label}
              onClick={() => setRange(tr)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                range.label === tr.label
                  ? 'bg-brand-500 text-white'
                  : 'bg-white/10 text-white/60 hover:text-white hover:bg-white/20'
              }`}
            >
              <FaClock className="inline mr-1" />{tr.label}
            </button>
          ))}
          <button onClick={fetchHistory} className="p-1.5 rounded bg-white/10 hover:bg-white/20 text-white/60 hover:text-white">
            <FaSyncAlt className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {data.length === 0 && !loading && (
        <div className="text-center py-8 text-white/40 text-sm">
          No data yet — stats are collected every 30 seconds.
        </div>
      )}

      {data.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* CPU Chart */}
          <div className="bg-white/5 border border-white/10 rounded-xl p-4">
            <h4 className="text-sm font-medium text-white/70 mb-3">CPU Usage (%)</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="cpu" name="CPU" stroke="#3b82f6" fill="url(#cpuGrad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* RAM Chart */}
          <div className="bg-white/5 border border-white/10 rounded-xl p-4">
            <h4 className="text-sm font-medium text-white/70 mb-3">Memory Usage (MB)</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="ramGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <YAxis tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="ram_used" name="RAM Used" stroke="#a855f7" fill="url(#ramGrad)" strokeWidth={2} />
                <Area type="monotone" dataKey="ram_limit" name="RAM Limit" stroke="#6b7280" fill="none" strokeWidth={1} strokeDasharray="4 4" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Network Chart */}
          <div className="bg-white/5 border border-white/10 rounded-xl p-4">
            <h4 className="text-sm font-medium text-white/70 mb-3">Network I/O (MB)</h4>
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
                <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <YAxis tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }} />
                <Area type="monotone" dataKey="net_rx" name="Net RX" stroke="#22c55e" fill="url(#rxGrad)" strokeWidth={2} />
                <Area type="monotone" dataKey="net_tx" name="Net TX" stroke="#f59e0b" fill="url(#txGrad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Players Chart */}
          <div className="bg-white/5 border border-white/10 rounded-xl p-4">
            <h4 className="text-sm font-medium text-white/70 mb-3">Players Online</h4>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart {...chartCommon}>
                <defs>
                  <linearGradient id="playersGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <YAxis allowDecimals={false} tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="stepAfter" dataKey="players" name="Players" stroke="#06b6d4" fill="url(#playersGrad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
