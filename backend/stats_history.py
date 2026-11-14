"""
Stats History — collects per-server resource metrics every N seconds and exposes
time-series data for frontend resource graphs.

Uses a separate lightweight SQLite database so it doesn't bloat the main DB.
Old data is pruned automatically based on retention settings.
"""
import sqlite3
import threading
import time
import logging
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Store stats DB alongside the main database
_DB_PATH = os.getenv("STATS_DB_PATH", "/data/stats_history.db")
_COLLECT_INTERVAL = int(os.getenv("STATS_COLLECT_INTERVAL", "30"))  # seconds
_RETENTION_HOURS = int(os.getenv("STATS_RETENTION_HOURS", "168"))   # 7 days

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_collector_thread: Optional[threading.Thread] = None
_running = False

# Track last network counters per server to calculate rates
_last_net_counters = {}


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=15.0)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA busy_timeout=15000")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                server_id TEXT NOT NULL,
                server_name TEXT,
                cpu_percent REAL DEFAULT 0,
                memory_used_mb REAL DEFAULT 0,
                memory_limit_mb REAL DEFAULT 0,
                memory_percent REAL DEFAULT 0,
                network_rx_mb REAL DEFAULT 0,
                network_tx_mb REAL DEFAULT 0,
                network_rx_rate_mbps REAL DEFAULT 0,
                network_tx_rate_mbps REAL DEFAULT 0,
                player_count INTEGER DEFAULT 0,
                tps REAL DEFAULT NULL,
                mspt REAL DEFAULT NULL,
                active_threads INTEGER DEFAULT 0,
                per_core_cpu TEXT DEFAULT NULL
            )
        """)
        # Idempotently alter SQLite stats table on connection to guarantee new columns exist
        cols = {row[1] for row in _conn.execute("PRAGMA table_info(stats)").fetchall()}
        for col_name, col_def in [
            ("tps", "REAL DEFAULT NULL"),
            ("mspt", "REAL DEFAULT NULL"),
            ("active_threads", "INTEGER DEFAULT 0"),
            ("per_core_cpu", "TEXT DEFAULT NULL"),
        ]:
            if col_name not in cols:
                try:
                    _conn.execute(f"ALTER TABLE stats ADD COLUMN {col_name} {col_def}")
                except Exception as e:
                    logger.debug(f"Column {col_name} migration note: {e}")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_stats_server_ts ON stats(server_id, ts)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_stats_ts ON stats(ts)")
        _conn.commit()
    return _conn


def _calculate_network_rates(server_id: str, rx_mb: float, tx_mb: float) -> tuple:
    """Calculate network rates in MB/s based on previous counters."""
    global _last_net_counters
    now = time.time()

    if server_id not in _last_net_counters:
        _last_net_counters[server_id] = {
            'rx_mb': rx_mb,
            'tx_mb': tx_mb,
            'timestamp': now
        }
        return 0.0, 0.0

    last = _last_net_counters[server_id]
    time_diff = now - last['timestamp']

    if time_diff > 0:
        rx_rate = max(0, (rx_mb - last['rx_mb']) / time_diff)
        tx_rate = max(0, (tx_mb - last['tx_mb']) / time_diff)
    else:
        rx_rate = 0.0
        tx_rate = 0.0

    _last_net_counters[server_id] = {
        'rx_mb': rx_mb,
        'tx_mb': tx_mb,
        'timestamp': now
    }

    return rx_rate, tx_rate


def record_stats(server_id: str, server_name: str, stats: dict):
    """Insert one stats snapshot."""
    with _lock:
        conn = _get_conn()

        rx_mb = stats.get("network_rx_mb", 0)
        tx_mb = stats.get("network_tx_mb", 0)
        rx_rate, tx_rate = _calculate_network_rates(server_id, rx_mb, tx_mb)

        tps = stats.get("tps")
        mspt = stats.get("mspt")
        active_threads = stats.get("active_threads", 0)
        per_core_cpu = stats.get("per_core_cpu")
        per_core_cpu_raw = json.dumps(per_core_cpu) if per_core_cpu is not None else None

        conn.execute(
            """INSERT INTO stats (ts, server_id, server_name, cpu_percent, memory_used_mb,
               memory_limit_mb, memory_percent, network_rx_mb, network_tx_mb,
               network_rx_rate_mbps, network_tx_rate_mbps, player_count,
               tps, mspt, active_threads, per_core_cpu)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                server_id,
                server_name or "",
                stats.get("cpu_percent", 0),
                stats.get("memory_usage_mb", 0),
                stats.get("memory_limit_mb", 0),
                stats.get("memory_percent", 0),
                rx_mb,
                tx_mb,
                rx_rate,
                tx_rate,
                stats.get("player_count", 0),
                tps,
                mspt,
                active_threads,
                per_core_cpu_raw,
            ),
        )
        conn.commit()


def get_stats_history(server_id: str, hours: int = 1, resolution: int = 0) -> list[dict]:
    """
    Return time-series data for a server.
    hours: how far back to look
    resolution: if > 0, aggregate into N-minute buckets (avg). 0 = raw data.
    """
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with _lock:
        conn = _get_conn()
        if resolution > 0:
            if resolution >= 60:
                bucket_expr = "strftime('%Y-%m-%dT%H:00:00', ts)"
                params = (server_id, server_id, since)
            else:
                bucket_expr = (
                    "strftime('%Y-%m-%dT%H:', ts) || "
                    "printf('%02d', (CAST(strftime('%M', ts) AS INTEGER) / ?) * ?) || ':00'"
                )
                params = (resolution, resolution, server_id, server_id, since)

            rows = conn.execute(
                f"""SELECT
                     {bucket_expr} AS bucket,
                     AVG(cpu_percent), AVG(memory_used_mb), AVG(memory_limit_mb),
                     AVG(memory_percent), AVG(network_rx_rate_mbps), AVG(network_tx_rate_mbps),
                     MAX(player_count),
                     AVG(tps), AVG(mspt), AVG(active_threads)
                   FROM stats
                   WHERE (server_id = ? OR server_name = ?) AND ts >= ?
                   GROUP BY bucket
                   ORDER BY bucket""",
                params,
            ).fetchall()

            # If at least 2 buckets exist, return the aggregated buckets.
            # Otherwise fall back to raw data points so newly started servers
            # still display a continuous line in 6h / 24h / 7d views.
            if len(rows) >= 2:
                return [
                    {
                        "ts": r[0], "cpu": round(r[1] or 0, 2), "ram_used": round(r[2] or 0, 1),
                        "ram_limit": round(r[3] or 0, 1), "ram_pct": round(r[4] or 0, 1),
                        "net_rx_rate": round(r[5] or 0, 4), "net_tx_rate": round(r[6] or 0, 4),
                        "players": r[7] or 0,
                        "tps": round(r[8], 2) if r[8] is not None else None,
                        "mspt": round(r[9], 2) if r[9] is not None else None,
                        "active_threads": int(round(r[10])) if r[10] is not None else 0,
                        "per_core_cpu": None,
                    }
                    for r in rows
                ]

        rows = conn.execute(
            """SELECT ts, cpu_percent, memory_used_mb, memory_limit_mb, memory_percent,
                      network_rx_rate_mbps, network_tx_rate_mbps, player_count,
                      tps, mspt, active_threads, per_core_cpu
                 FROM stats
                 WHERE (server_id = ? OR server_name = ?) AND ts >= ?
                 ORDER BY ts""",
            (server_id, server_id, since),
        ).fetchall()
        return [
            {
                "ts": r[0], "cpu": round(r[1] or 0, 2), "ram_used": round(r[2] or 0, 1),
                "ram_limit": round(r[3] or 0, 1), "ram_pct": round(r[4] or 0, 1),
                "net_rx_rate": round(r[5] or 0, 4), "net_tx_rate": round(r[6] or 0, 4),
                "players": r[7] or 0,
                "tps": round(r[8], 2) if r[8] is not None else None,
                "mspt": round(r[9], 2) if r[9] is not None else None,
                "active_threads": int(round(r[10])) if r[10] is not None else 0,
                "per_core_cpu": json.loads(r[11]) if r[11] else None,
            }
            for r in rows
        ]


def prune_old_stats():
    """Remove stats older than retention period."""
    cutoff = (datetime.utcnow() - timedelta(hours=_RETENTION_HOURS)).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM stats WHERE ts < ?", (cutoff,))
        conn.commit()


def _collector_loop():
    """Background thread that periodically collects stats from all running servers."""
    global _running

    try:
        from runtime_adapter import get_runtime_manager
    except Exception as e:
        logger.error(f"Stats collector: Failed to import runtime adapter: {e}")
        return

    logger.info(f"Stats collector started (interval={_COLLECT_INTERVAL}s, retention={_RETENTION_HOURS}h)")
    _cycle_count = 0

    while _running:
        cycle_start = time.time()
        _cycle_count += 1
        try:
            manager = get_runtime_manager_or_docker()
            if manager is not None:
                servers = manager.list_servers()
                alive_ids = {str(s.get("id") or s.get("container_id") or s.get("name")) for s in servers}
                for dead in list(_last_net_counters.keys()):
                    if dead not in alive_ids:
                        _last_net_counters.pop(dead, None)
                for srv in servers:
                    if not _running:
                        break
                    if srv.get("status") != "running":
                        continue
                    cid = srv.get("id") or srv.get("container_id") or srv.get("name")
                    name = srv.get("name") or srv.get("server_name") or ""
                    if not cid:
                        continue
                    try:
                        s = manager.get_server_stats(str(cid))
                        if s and not s.get("error"):
                            record_stats(str(cid), name, s)
                    except Exception as e:
                        logger.warning(f"Stats collection failed for {cid}: {e}")
        except Exception as e:
            logger.error(f"Stats collector error: {e}")

        if _cycle_count % 100 == 0:
            try:
                prune_old_stats()
                try:
                    with _lock:
                        _get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
            except Exception:
                pass

        elapsed = time.time() - cycle_start
        sleep_time = max(1, _COLLECT_INTERVAL - elapsed)
        for _ in range(int(sleep_time)):
            if not _running:
                break
            time.sleep(1)


_manager_singleton = None


def get_runtime_manager_or_docker():
    """Get runtime manager (local) or fall back to Docker manager (cached)."""
    global _manager_singleton
    try:
        from runtime_adapter import get_runtime_manager
        adapter = get_runtime_manager()
        if adapter is not None:
            return adapter
    except Exception:
        pass
    if _manager_singleton is not None:
        try:
            _manager_singleton._ensure_client()  # type: ignore[attr-defined]
            _manager_singleton.client.ping()
            return _manager_singleton
        except Exception:
            try:
                _manager_singleton.client.close()
            except Exception:
                pass
            _manager_singleton = None
    try:
        from docker_manager import DockerManager
        _manager_singleton = DockerManager()
        return _manager_singleton
    except Exception as e:
        logger.error(f"Failed to get Docker manager: {e}")
        return None


def start_collector():
    """Start the background stats collection thread."""
    global _running, _collector_thread
    if _running:
        logger.debug("Stats collector already running")
        return
    _running = True
    _collector_thread = threading.Thread(target=_collector_loop, daemon=True, name="stats-collector")
    _collector_thread.start()


def stop_collector():
    """Stop the background stats collection thread."""
    global _running
    _running = False
