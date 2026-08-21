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
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
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
                player_count INTEGER DEFAULT 0
            )
        """)
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
        return 0.0, 0.0  # First reading, no rate yet
    
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
        
        # Calculate network rates
        rx_mb = stats.get("network_rx_mb", 0)
        tx_mb = stats.get("network_tx_mb", 0)
        rx_rate, tx_rate = _calculate_network_rates(server_id, rx_mb, tx_mb)
        
        conn.execute(
            """INSERT INTO stats (ts, server_id, server_name, cpu_percent, memory_used_mb,
               memory_limit_mb, memory_percent, network_rx_mb, network_tx_mb,
               network_rx_rate_mbps, network_tx_rate_mbps, player_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            # Aggregate by time buckets
            rows = conn.execute(
                """SELECT
                     strftime('%%Y-%%m-%%dT%%H:', ts) || 
                       printf('%%02d', (CAST(strftime('%%M', ts) AS INTEGER) / ?) * ?) || ':00' AS bucket,
                   AVG(cpu_percent), AVG(memory_used_mb), AVG(memory_limit_mb),
                   AVG(memory_percent), AVG(network_rx_rate_mbps), AVG(network_tx_rate_mbps),
                   MAX(player_count)
                 FROM stats
                 WHERE server_id = ? AND ts >= ?
                 GROUP BY bucket
                 ORDER BY bucket""",
                (resolution, resolution, server_id, since),
            ).fetchall()
            return [
                {
                    "ts": r[0], "cpu": round(r[1] or 0, 2), "ram_used": round(r[2] or 0, 1),
                    "ram_limit": round(r[3] or 0, 1), "ram_pct": round(r[4] or 0, 1),
                    "net_rx_rate": round(r[5] or 0, 4), "net_tx_rate": round(r[6] or 0, 4),
                    "players": r[7] or 0,
                }
                for r in rows
            ]
        else:
            rows = conn.execute(
                """SELECT ts, cpu_percent, memory_used_mb, memory_limit_mb, memory_percent,
                          network_rx_rate_mbps, network_tx_rate_mbps, player_count
                     FROM stats
                     WHERE server_id = ? AND ts >= ?
                     ORDER BY ts""",
                (server_id, since),
            ).fetchall()
            return [
                {
                    "ts": r[0], "cpu": round(r[1] or 0, 2), "ram_used": round(r[2] or 0, 1),
                    "ram_limit": round(r[3] or 0, 1), "ram_pct": round(r[4] or 0, 1),
                    "net_rx_rate": round(r[5] or 0, 4), "net_tx_rate": round(r[6] or 0, 4),
                    "players": r[7] or 0,
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
    
    # Import here to avoid circular imports
    try:
        from runtime_adapter import get_runtime_manager
    except Exception as e:
        logger.error(f"Stats collector: Failed to import runtime adapter: {e}")
        return

    logger.info(f"Stats collector started (interval={_COLLECT_INTERVAL}s, retention={_RETENTION_HOURS}h)")

    while _running:
        cycle_start = time.time()
        try:
            # Try to get the runtime manager (handles both Docker and local)
            manager = get_runtime_manager_or_docker()
            if manager is None:
                logger.debug("Stats collector: No runtime manager available")
            else:
                servers = manager.list_servers()
                logger.debug(f"Stats collector: Found {len(servers)} servers")
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
                            logger.debug(f"Stats collector: Recorded stats for {name} ({cid}) - CPU: {s.get('cpu_percent', 0)}%")
                        else:
                            logger.debug(f"Stats collector: No stats for {cid} - {s.get('error') if s else 'None'}")
                    except Exception as e:
                        logger.warning(f"Stats collector: Failed to get stats for {cid}: {e}")
        except Exception as e:
            logger.error(f"Stats collector error: {e}")

        # Prune old stats every 100 cycles (~50 min at 30s interval)
        try:
            prune_old_stats()
        except Exception:
            pass

        # Sleep in small intervals so we can stop quickly
        elapsed = time.time() - cycle_start
        sleep_time = max(1, _COLLECT_INTERVAL - elapsed)
        for _ in range(int(sleep_time)):
            if not _running:
                break
            time.sleep(1)


def get_runtime_manager_or_docker():
    """Get runtime manager (local) or fall back to Docker manager."""
    try:
        from runtime_adapter import get_runtime_manager
        adapter = get_runtime_manager()
        if adapter is not None:
            return adapter
    except Exception:
        pass
    try:
        from docker_manager import DockerManager
        return DockerManager()
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