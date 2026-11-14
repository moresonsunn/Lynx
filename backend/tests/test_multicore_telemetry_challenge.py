"""
Adversarial Challenge & Empirical Stress Harness for Milestone 3 Telemetry & Monitoring.

Author: challenger_m3_2
Focus:
- Multi-platform autonomous TPS/MSPT polling, command prioritization, and color stripping.
- Modern Vanilla / NeoForge /tick query parsing with various formats and edge cases.
- Paper / Purpur / Folia /tps + /mspt parsing with Minecraft color codes and asterisks.
- Forge /forge tps overall vs multi-dimension parsing.
- Fallback log-tail parsing under simulated lag, extreme lag, and clean responsive logs.
- Stopped server PID validation.
- TTL caching in _TPS_CACHE, working command memory, mutation immunity, and multi-threaded stress.
- SQLite stats history idempotent migration, un-clamped stats persistence, bucketed time-series aggregation, and concurrent write/read stress.
"""
import os
import sys
import json
import time
import tempfile
import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Ensure backend on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import stats_history
from runtime_adapter import (
    LocalAdapter,
    get_server_tps,
    _probe_server_tps,
    _TPS_CACHE,
    _TPS_CACHE_LOCK,
    _TELEMETRY_CACHE,
    _TELEMETRY_CACHE_LOCK,
)


@pytest.fixture(autouse=True)
def clean_caches():
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    yield
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()


# ============================================================================
# 1. Multi-Platform Autonomous TPS/MSPT Polling & RCON Output Variations
# ============================================================================

class TestAutonomousTpsMsptProbeMatrix:
    """Stress-test RCON parsing across platforms, formats, colors, and error conditions."""

    def _setup_server_dir(self, tmp_path, name="test_srv"):
        srv_dir = tmp_path / name
        srv_dir.mkdir(parents=True, exist_ok=True)
        (srv_dir / "server.properties").write_text(
            "enable-rcon=true\nrcon.password=secret123\nrcon.port=25575\n",
            encoding="utf-8",
        )
        return srv_dir

    def test_vanilla_tick_query_various_output_formats(self, tmp_path):
        """Verify modern Vanilla / NeoForge /tick query under different output formats."""
        srv_dir = self._setup_server_dir(tmp_path, "vanilla_fmt")

        # Variation A: Standard 1.20.3+ output
        mock_mcr = MagicMock()
        mock_mcr.command.return_value = "The tick rate is currently target: 20.0, average: 19.8 tps (25.4 mspt)"
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("vanilla_fmt", srv_dir, "vanilla")
            assert res["tps"] == 19.8
            assert res["mspt"] == 25.4
            assert res["method"] == "rcon_tick_query"

        # Variation B: ANSI escape sequences and Minecraft color codes
        with _TPS_CACHE_LOCK:
            _TPS_CACHE.clear()
        mock_mcr.command.return_value = "\x1b[33m§6Target: 20.0§r\x1b[0m. §aAverage: 20.0 TPS (15.2 mspt)§r"
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("vanilla_fmt", srv_dir, "vanilla")
            assert res["tps"] == 20.0
            assert res["mspt"] == 15.2
            assert res["method"] == "rcon_tick_query"

        # Variation C: Format with "Average tick time: X ms"
        with _TPS_CACHE_LOCK:
            _TPS_CACHE.clear()
        mock_mcr.command.return_value = "Average: 18.5 TPS. Average tick time: 31.8 ms"
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("vanilla_fmt", srv_dir, "vanilla")
            assert res["tps"] == 18.5
            assert res["mspt"] == 31.8
            assert res["method"] == "rcon_tick_query"

        # Variation D: Output without mspt reported -> derived from 1000/tps capped at 50ms
        with _TPS_CACHE_LOCK:
            _TPS_CACHE.clear()
        mock_mcr.command.return_value = "Current average: 10.0 TPS"
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("vanilla_fmt", srv_dir, "vanilla")
            assert res["tps"] == 10.0
            assert res["mspt"] == 50.0  # capped at 50.0
            assert res["method"] == "rcon_tick_query"

    def test_neoforge_command_priority(self, tmp_path):
        """Verify NeoForge server type prioritizes /tick query first."""
        srv_dir = self._setup_server_dir(tmp_path, "neoforge_srv")
        mock_mcr = MagicMock()
        executed_cmds = []

        def side_effect(cmd):
            executed_cmds.append(cmd)
            if cmd == "tick query":
                return "Current average: 20.0 TPS (12.0 mspt)"
            return "unknown command"

        mock_mcr.command.side_effect = side_effect
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("neoforge_srv", srv_dir, "neoforge")
            assert res["tps"] == 20.0
            assert res["mspt"] == 12.0
            assert res["method"] == "rcon_tick_query"
            assert executed_cmds[0] == "tick query"

    def test_paper_purpur_folia_formats(self, tmp_path):
        """Verify Paper/Purpur/Folia /tps and /mspt parsing with colors and asterisks."""
        srv_dir = self._setup_server_dir(tmp_path, "paper_formats")

        # Case A: Purpur with asterisks and color codes
        mock_mcr = MagicMock()
        def cmd_purpur(cmd):
            if cmd == "tps":
                return "§6TPS from last 1m, 5m, 15m: §a*19.85§r, §a*20.0§r, §a*20.0§r"
            if cmd == "mspt":
                return "§6Server tick times from last 5s, 10s, 1m:\n§a5s: 18.5/12.0/40.0ms§r"
            return "unknown"

        mock_mcr.command.side_effect = cmd_purpur
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("paper_formats", srv_dir, "purpur")
            assert res["tps"] == 19.9  # rounded to 1 decimal place
            assert res["mspt"] == 18.5
            assert res["method"] == "rcon_paper_tps"

        # Case B: Plain comma separated values (legacy Paper format)
        with _TPS_CACHE_LOCK:
            _TPS_CACHE.clear()
        def cmd_legacy(cmd):
            if cmd == "tps":
                return "19.5, 19.8, 20.0"
            if cmd == "mspt":
                return "unknown command"
            return "unknown"

        mock_mcr.command.side_effect = cmd_legacy
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("paper_formats", srv_dir, "paper")
            assert res["tps"] == 19.5
            # mspt derived from 1000/19.5 = 51.28 capped at 50.0
            assert res["mspt"] == 50.0
            assert res["method"] == "rcon_paper_tps"

    def test_forge_overall_and_dimension_tps_parsing(self, tmp_path):
        """Verify Forge /forge tps with overall line vs dimension averaging."""
        srv_dir = self._setup_server_dir(tmp_path, "forge_tps_srv")
        mock_mcr = MagicMock()
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        # Format A: Overall line present
        mock_mcr.command.return_value = (
            "Dim 0 (Overworld): Mean tick time: 10.0ms. Mean TPS: 20.0\n"
            "Overall: Mean tick time: 14.5ms. Mean TPS: 20.0\n"
        )
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("forge_tps_srv", srv_dir, "forge")
            assert res["tps"] == 20.0
            assert res["mspt"] == 14.5
            assert res["method"] == "rcon_forge_tps"

        # Format B: Overall line absent, 3 dimensions averaged
        with _TPS_CACHE_LOCK:
            _TPS_CACHE.clear()
        mock_mcr.command.return_value = (
            "Dim 0 (Overworld): Mean tick time: 10.0ms. Mean TPS: 20.0\n"
            "Dim -1 (Nether): Mean tick time: 30.0ms. Mean TPS: 20.0\n"
            "Dim 1 (The End): Mean tick time: 20.0ms. Mean TPS: 20.0\n"
        )
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("forge_tps_srv", srv_dir, "forge")
            assert res["tps"] == 20.0
            # (10 + 30 + 20) / 3 = 20.0ms
            assert res["mspt"] == 20.0
            assert res["method"] == "rcon_forge_tps"

    def test_rcon_unknown_command_fallback_cascade(self, tmp_path):
        """When the first command returns 'unknown command', next candidates are tried."""
        srv_dir = self._setup_server_dir(tmp_path, "cascade_srv")
        mock_mcr = MagicMock()
        calls = []

        def side_effect(cmd):
            calls.append(cmd)
            if cmd == "tick query":
                return "Unknown command: tick query"
            if cmd == "tps":
                return "§aTPS from last 1m: §a20.0§r"
            return "error"

        mock_mcr.command.side_effect = side_effect
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        # Vanilla tries /tick query first, fails, then tries /tps and succeeds
        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("cascade_srv", srv_dir, "vanilla")
            assert res["tps"] == 20.0
            assert res["method"] == "rcon_paper_tps"
            assert "tick query" in calls
            assert "tps" in calls


# ============================================================================
# 2. Log-Tail Fallback Parser Empirical Stress Testing
# ============================================================================

class TestLogTailFallbackLagAndNominal:
    """Stress-test fallback to logs/latest.log under simulated lag and nominal conditions."""

    def test_log_tail_simulated_lag_various_delays(self, tmp_path):
        """Verify lag calculation: Running 60ms or 1 ticks behind -> TPS < 20.0, MSPT > 50.0."""
        srv_dir = tmp_path / "lag_srv"
        srv_dir.mkdir(parents=True)
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()

        # Simulated 60ms behind over 1 tick -> extra 60ms -> MSPT 110.0ms -> TPS 9.1
        (logs_dir / "latest.log").write_text(
            "[15:00:00] [Server thread/INFO]: Server loaded.\n"
            "[15:01:00] [Server thread/WARN]: Can't keep up! Running 60ms or 1 ticks behind\n",
            encoding="utf-8",
        )

        res = _probe_server_tps("lag_srv", srv_dir, "vanilla")
        assert res["mspt"] == 110.0
        assert res["tps"] == 9.1
        assert res["mspt"] > 50.0
        assert res["tps"] < 20.0
        assert res["method"] == "log_lag_detection"

    def test_log_tail_picks_latest_lag_warning_out_of_multiple(self, tmp_path):
        """Verify the parser picks the most recent lag warning in the tail lines."""
        srv_dir = tmp_path / "multi_lag_srv"
        srv_dir.mkdir(parents=True)
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()

        (logs_dir / "latest.log").write_text(
            "[10:00:00] [Server thread/WARN]: Can't keep up! Running 1000ms or 20 ticks behind\n"
            "[10:01:00] [Server thread/INFO]: Chunk saved\n"
            "[10:02:00] [Server thread/WARN]: Can't keep up! Running 40ms or 2 ticks behind\n",
            encoding="utf-8",
        )

        # Latest warning: 40ms over 2 ticks = 20ms extra -> MSPT = 70.0, TPS = 14.3
        res = _probe_server_tps("multi_lag_srv", srv_dir, "vanilla")
        assert res["mspt"] == 70.0
        assert res["tps"] == 14.3
        assert res["method"] == "log_lag_detection"

    def test_log_tail_clean_responsive_nominal_healthy(self, tmp_path):
        """Verify nominal healthy log tail yields 20.0 TPS, 25.0 MSPT."""
        srv_dir = tmp_path / "nominal_srv"
        srv_dir.mkdir(parents=True)
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()

        (logs_dir / "latest.log").write_text(
            "[10:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1\n"
            "[10:00:05] [Server thread/INFO]: Preparing start region for dimension minecraft:overworld\n"
            "[10:00:10] [Server thread/INFO]: Done (5.421s)! For help, type 'help'\n"
            "[10:01:00] [Server thread/INFO]: Player Steve joined the game\n",
            encoding="utf-8",
        )

        res = _probe_server_tps("nominal_srv", srv_dir, "vanilla")
        assert res["tps"] == 20.0
        assert res["mspt"] == 25.0
        assert res["method"] == "nominal_healthy"

    def test_log_tail_missing_or_empty_log_nominal_fallback(self, tmp_path):
        """Missing or empty log falls back to nominal 20.0 TPS, 25.0 MSPT."""
        srv_dir = tmp_path / "no_log_srv"
        srv_dir.mkdir(parents=True)

        res = _probe_server_tps("no_log_srv", srv_dir, "vanilla")
        assert res["tps"] == 20.0
        assert res["mspt"] == 25.0
        assert res["method"] == "nominal_fallback"

    def test_stopped_server_returns_stopped_method_and_none_tps(self, tmp_path):
        """LocalAdapter.get_server_tps verifies PID and returns None TPS for stopped server."""
        adapter = LocalAdapter()
        srv_dir = tmp_path / "stopped_srv"
        srv_dir.mkdir(parents=True)
        # No .server.pid file or PID points to non-existent process
        (srv_dir / ".server.pid").write_text("99999999", encoding="utf-8")

        with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
             patch("psutil.pid_exists", return_value=False):
            res = adapter.get_server_tps("stopped_srv")
            assert res["tps"] is None
            assert res["mspt"] is None
            assert res["method"] == "stopped"


# ============================================================================
# 3. TTL Caching Mechanics & Concurrency Stress Testing
# ============================================================================

class TestTpsCacheMechanicsAndConcurrency:
    """Stress-test _TPS_CACHE TTL expiration, working command retention, and thread concurrency."""

    def test_tps_cache_hit_and_ttl_expiration(self, tmp_path):
        """Verify cache returns identical result within 5.0s, and re-probes after 5.0s."""
        srv_dir = tmp_path / "cache_ttl_srv"
        srv_dir.mkdir(parents=True)
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()
        (logs_dir / "latest.log").write_text("[Server thread/INFO]: OK\n", encoding="utf-8")

        t0 = 1000.0
        with patch("time.time", return_value=t0), \
             patch("runtime_adapter.read_log_tail_lines", return_value=["[Server thread/INFO]: OK"]) as mock_read:
            res1 = _probe_server_tps("cache_ttl_srv", srv_dir)
            assert res1["tps"] == 20.0
            assert mock_read.call_count == 1

            # At t0 + 4.9s -> within 5.0s TTL -> hit cache without re-reading
            with patch("time.time", return_value=t0 + 4.9):
                res2 = _probe_server_tps("cache_ttl_srv", srv_dir)
                assert res2["tps"] == 20.0
                assert mock_read.call_count == 1  # No additional read

            # At t0 + 5.1s -> TTL expired -> re-probe
            with patch("time.time", return_value=t0 + 5.1):
                res3 = _probe_server_tps("cache_ttl_srv", srv_dir)
                assert res3["tps"] == 20.0
                assert mock_read.call_count == 2  # Fresh read invoked

    def test_cache_mutation_isolation_on_hit_and_miss_behavior(self, tmp_path):
        """Mutating the dictionary returned from _probe_server_tps on cache hit vs miss."""
        srv_dir = tmp_path / "mutate_srv"
        srv_dir.mkdir(parents=True)
        (srv_dir / "logs").mkdir()
        (srv_dir / "logs" / "latest.log").write_text("[Server thread/INFO]: Done\n", encoding="utf-8")

        # Call 1 (Cache miss): returns raw reference stored in _TPS_CACHE
        res1 = _probe_server_tps("mutate_srv", srv_dir)
        assert res1["tps"] == 20.0

        # Call 2 (Cache hit): returns dict(cached["result"])
        res2 = _probe_server_tps("mutate_srv", srv_dir)
        assert res2["tps"] == 20.0

        # Mutating res2 (cache hit) does NOT corrupt cache because line 62 made a shallow copy
        res2["tps"] = 999.9
        res2["method"] = "corrupted"

        res3 = _probe_server_tps("mutate_srv", srv_dir)
        assert res3["tps"] == 20.0
        assert res3["method"] == "nominal_healthy"

        # Now test mutating res1 (cache miss return value):
        # NOTE: This reveals an implementation vulnerability: on cache miss (line 231),
        # _probe_server_tps returns the raw internal dict without copying.
        res1["tps"] = 777.7
        res4 = _probe_server_tps("mutate_srv", srv_dir)
        # Demonstrates that Call 1 reference leak contaminated the cache
        assert res4["tps"] == 777.7, "Empirically confirmed: Call 1 raw reference leaks into cache"
        assert res4["method"] == "nominal_healthy"

    def test_working_command_retained_across_cache_refresh(self, tmp_path):
        """Working command is remembered and prioritized when cache refreshes."""
        srv_dir = tmp_path / "cmd_remember_srv"
        srv_dir.mkdir(parents=True)
        (srv_dir / "server.properties").write_text(
            "enable-rcon=true\nrcon.password=secret\nrcon.port=25575\n",
            encoding="utf-8",
        )

        mock_mcr = MagicMock()
        history = []

        def side_effect(cmd):
            history.append(cmd)
            if cmd == "forge tps":
                return "Overall: Mean tick time: 15.0ms. Mean TPS: 20.0"
            return "unknown"

        mock_mcr.command.side_effect = side_effect
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        t0 = 2000.0
        with patch("time.time", return_value=t0), \
             patch("mcrcon.MCRcon", mock_mcr_cls):
            # Vanilla starts with /tick query, fails, /tps fails, /forge tps succeeds
            res = _probe_server_tps("cmd_remember_srv", srv_dir, "vanilla")
            assert res["tps"] == 20.0
            assert res["method"] == "rcon_forge_tps"

        # Check working command saved in cache
        with _TPS_CACHE_LOCK:
            cached = _TPS_CACHE.get("cmd_remember_srv")
            assert cached is not None
            assert cached["working_command"] == "/forge tps"

        # When cache expires at t0 + 6.0s, /forge tps should be prioritized FIRST in candidates
        history.clear()
        with patch("time.time", return_value=t0 + 6.0), \
             patch("mcrcon.MCRcon", mock_mcr_cls):
            res2 = _probe_server_tps("cmd_remember_srv", srv_dir, "vanilla")
            assert res2["tps"] == 20.0
            assert history[0] == "forge tps"  # Immediately tried first!

    def test_concurrent_multithreaded_tps_polling(self, tmp_path):
        """25 threads concurrently probing _probe_server_tps without deadlocks or errors."""
        srv_dirs = {}
        for i in range(5):
            s_name = f"conc_srv_{i}"
            s_dir = tmp_path / s_name
            s_dir.mkdir(parents=True)
            logs = s_dir / "logs"
            logs.mkdir()
            (logs / "latest.log").write_text(f"[Server thread/INFO]: Server {i} up\n", encoding="utf-8")
            srv_dirs[s_name] = s_dir

        results = []
        errors = []

        def worker(thread_idx):
            try:
                s_name = f"conc_srv_{thread_idx % 5}"
                s_dir = srv_dirs[s_name]
                r = _probe_server_tps(s_name, s_dir)
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=5.0)

        assert len(errors) == 0, f"Concurrent polling raised errors: {errors}"
        assert len(results) == 25
        for r in results:
            assert r["tps"] == 20.0
            assert r["mspt"] == 25.0


# ============================================================================
# 4. SQLite Stats History Database Empirical Stress Testing
# ============================================================================

class TestStatsHistorySqliteStressHarness:
    """Stress-test SQLite schema migrations, un-clamped stats persistence, downsampling & concurrency."""

    def test_idempotent_schema_migration_preserves_preexisting_rows(self, tmp_path):
        """Verify migration adds tps, mspt, active_threads, per_core_cpu without data loss."""
        db_path = tmp_path / "legacy_migration.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                server_id TEXT NOT NULL,
                server_name TEXT,
                cpu_percent REAL DEFAULT 0,
                memory_used_mb REAL DEFAULT 0
            )
        """)
        conn.execute("INSERT INTO stats (ts, server_id, server_name, cpu_percent, memory_used_mb) VALUES (?, ?, ?, ?, ?)",
                     ("2026-11-12T10:00:00", "old_srv", "Old Server", 125.5, 1024.0))
        conn.commit()
        conn.close()

        # Connect through stats_history
        stats_history._DB_PATH = str(db_path)
        stats_history._conn = None
        c = stats_history._get_conn()

        # Verify new columns exist
        cols = {r[1] for r in c.execute("PRAGMA table_info(stats)").fetchall()}
        for expected_col in ["tps", "mspt", "active_threads", "per_core_cpu"]:
            assert expected_col in cols

        # Verify old record is preserved
        row = c.execute("SELECT id, server_id, cpu_percent, tps, active_threads FROM stats WHERE server_id = 'old_srv'").fetchone()
        assert row is not None
        assert row[1] == "old_srv"
        assert row[2] == 125.5
        assert row[3] is None  # Defaults to NULL
        assert row[4] == 0     # Defaults to 0

        # Calling _get_conn multiple times must be strictly idempotent
        c2 = stats_history._get_conn()
        assert c2 is c

        c.close()
        stats_history._conn = None

    def test_record_and_retrieve_unclamped_and_nullable_telemetry(self, tmp_path):
        """Verify un-clamped CPU (> 100%), per-core JSON serialization, and NULL handling."""
        db_path = tmp_path / "unclamped_history.db"
        stats_history._DB_PATH = str(db_path)
        stats_history._conn = None

        # Record snapshot with 350% un-clamped CPU across 4 cores
        per_core = [95.0, 85.5, 90.0, 79.5]
        stats_history.record_stats("bench_srv", "Benchmark Server", {
            "cpu_percent": 350.0,
            "memory_usage_mb": 4096.0,
            "memory_limit_mb": 8192.0,
            "memory_percent": 50.0,
            "network_rx_mb": 50.0,
            "network_tx_mb": 25.0,
            "player_count": 12,
            "tps": 19.95,
            "mspt": 24.2,
            "active_threads": 48,
            "per_core_cpu": per_core,
        })

        # Record second snapshot with None TPS / MSPT / per_core_cpu
        stats_history.record_stats("bench_srv", "Benchmark Server", {
            "cpu_percent": 0.0,
            "memory_usage_mb": 100.0,
            "memory_limit_mb": 8192.0,
            "memory_percent": 1.2,
            "tps": None,
            "mspt": None,
            "active_threads": 0,
            "per_core_cpu": None,
        })

        # Query raw time-series (resolution = 0)
        hist = stats_history.get_stats_history("bench_srv", hours=1, resolution=0)
        assert len(hist) == 2

        entry1 = hist[0]
        assert entry1["cpu"] == 350.0
        assert entry1["cpu"] > 100.0
        assert entry1["tps"] == 19.95  # round(19.95, 2)
        assert entry1["mspt"] == 24.2
        assert entry1["active_threads"] == 48
        assert entry1["per_core_cpu"] == per_core

        entry2 = hist[1]
        assert entry2["cpu"] == 0.0
        assert entry2["tps"] is None
        assert entry2["mspt"] is None
        assert entry2["active_threads"] == 0
        assert entry2["per_core_cpu"] is None

        stats_history._conn.close()
        stats_history._conn = None

    def test_bucketed_aggregation_with_resolution_variations(self, tmp_path):
        """Verify time-series downsampling: resolution=5 (5-minute) and resolution=60 (hourly)."""
        db_path = tmp_path / "bucketed_history.db"
        stats_history._DB_PATH = str(db_path)
        stats_history._conn = None

        conn = stats_history._get_conn()
        # Seed 4 snapshots spaced across two 5-minute buckets
        # Bucket 1: 12:01 and 12:03
        # Bucket 2: 12:06 and 12:08
        now = "2026-11-12T"
        samples = [
            (f"{now}12:01:00", "srv_agg", 200.0, 19.8, 25.0, 20),
            (f"{now}12:03:00", "srv_agg", 220.0, 20.0, 23.0, 24),
            (f"{now}12:06:00", "srv_agg", 180.0, 19.5, 30.0, 16),
            (f"{now}12:08:00", "srv_agg", 160.0, 19.9, 28.0, 18),
        ]
        for ts, s_id, cpu, tps, mspt, threads in samples:
            conn.execute(
                """INSERT INTO stats (ts, server_id, server_name, cpu_percent, memory_used_mb,
                   memory_limit_mb, memory_percent, network_rx_mb, network_tx_mb,
                   network_rx_rate_mbps, network_tx_rate_mbps, player_count,
                   tps, mspt, active_threads, per_core_cpu)
                   VALUES (?, ?, ?, ?, 1000, 2000, 50, 0, 0, 0, 0, 2, ?, ?, ?, NULL)""",
                (ts, s_id, "Agg Server", cpu, tps, mspt, threads)
            )
        conn.commit()

        # Query with resolution=5 and 24 hours window
        # Mock datetime.utcnow() to 2026-11-12T13:00:00
        from datetime import datetime
        with patch("stats_history.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 11, 12, 13, 0, 0)
            mock_dt.fromtimestamp = datetime.fromtimestamp

            buckets = stats_history.get_stats_history("srv_agg", hours=2, resolution=5)
            assert len(buckets) == 2

            # Bucket 1: avg CPU = (200 + 220)/2 = 210.0, avg TPS = (19.8 + 20.0)/2 = 19.9
            # avg MSPT = (25.0 + 23.0)/2 = 24.0, avg threads = (20 + 24)/2 = 22
            b1 = buckets[0]
            assert b1["cpu"] == 210.0
            assert b1["tps"] == 19.9
            assert b1["mspt"] == 24.0
            assert b1["active_threads"] == 22
            assert b1["per_core_cpu"] is None  # Bucketed mode leaves per_core_cpu None

            # Bucket 2: avg CPU = (180 + 160)/2 = 170.0, avg TPS = (19.5 + 19.9)/2 = 19.7
            b2 = buckets[1]
            assert b2["cpu"] == 170.0
            assert b2["tps"] == 19.7
            assert b2["mspt"] == 29.0
            assert b2["active_threads"] == 17

        stats_history._conn.close()
        stats_history._conn = None

    def test_concurrent_stats_recording_and_reading(self, tmp_path):
        """Stress-test concurrent writes and reads without sqlite3.OperationalError locks."""
        db_path = tmp_path / "concurrent_stress.db"
        stats_history._DB_PATH = str(db_path)
        stats_history._conn = None

        errors = []
        stop_event = threading.Event()

        def writer_thread(idx):
            try:
                for j in range(20):
                    stats_history.record_stats(f"srv_thread_{idx}", "Concurrent Server", {
                        "cpu_percent": 150.0 + j,
                        "memory_usage_mb": 2048.0,
                        "memory_limit_mb": 4096.0,
                        "memory_percent": 50.0,
                        "network_rx_mb": 1.0,
                        "network_tx_mb": 1.0,
                        "player_count": 1,
                        "tps": 20.0,
                        "mspt": 20.0,
                        "active_threads": 16,
                        "per_core_cpu": [75.0, 75.0],
                    })
                    time.sleep(0.005)
            except Exception as e:
                errors.append(f"Writer-{idx}: {e}")

        def reader_thread():
            try:
                while not stop_event.is_set():
                    _ = stats_history.get_stats_history("srv_thread_0", hours=1, resolution=0)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(f"Reader: {e}")

        threads = [threading.Thread(target=writer_thread, args=(i,)) for i in range(5)]
        r_th = threading.Thread(target=reader_thread)
        r_th.start()
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10.0)
        stop_event.set()
        r_th.join(timeout=5.0)

        assert len(errors) == 0, f"Concurrent database stress failed: {errors}"
        stats_history._conn.close()
        stats_history._conn = None
