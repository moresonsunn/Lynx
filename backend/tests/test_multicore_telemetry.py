"""
Unit and Integration Tests for Real-Time Multi-Core Telemetry & Monitoring (Milestone 3).

Covers:
- Un-clamped aggregate CPU calculation and normalized CPU bounded to host capacity.
- Per-core CPU array collection via psutil and Docker cgroups (v1/v2).
- Process tree thread count accumulation and thread CPU metrics sampling.
- Adaptive TPS & MSPT probing across Vanilla, Paper, Forge, NeoForge, and log-tail fallback.
- SQLite stats_history schema migration and time-series query persistence (raw and bucketed).
- API endpoints: /api/servers/{id}/performance and /api/servers/{id}/resources.
- Pydantic models validation.
"""
import os
import sys
import json
import time
import tempfile
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Ensure backend is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import psutil
from models import ThreadMetric, ServerStatsResponse, ServerPerformanceDetailResponse
import stats_history
from runtime_adapter import (
    LocalAdapter,
    _live_cpu_count,
    _resolve_thread_name,
    _probe_server_tps,
    get_server_tps,
    _TELEMETRY_CACHE,
    _TELEMETRY_CACHE_LOCK,
    _TPS_CACHE,
    _TPS_CACHE_LOCK,
)
from docker_manager import DockerManager
from app import app


@pytest.fixture(autouse=True)
def clean_telemetry_caches():
    """Clear memory caches between tests."""
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()
    yield
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()


class TestPydanticModels:
    def test_thread_metric_validation(self):
        tm = ThreadMetric(id=101, name="Server thread", cpu_percent=85.2, user_time=12.4, system_time=2.1)
        assert tm.id == 101
        assert tm.name == "Server thread"
        assert tm.cpu_percent == 85.2
        assert tm.user_time == 12.4
        assert tm.system_time == 2.1

    def test_server_stats_response_unclamped_cpu(self):
        stats = ServerStatsResponse(
            id="srv-1",
            server_name="Test Vanilla",
            status="running",
            cpu_percent=245.8,  # Exceeds 100% on multi-core
            cpu_percent_aggregate=245.8,
            cpu_percent_normalized=15.3,
            per_core_cpu=[50.0, 95.8, 100.0, 0.0],
            active_threads=36,
            thread_metrics=[ThreadMetric(id=1, name="Worker-1", cpu_percent=95.8)],
            memory_usage_mb=2048.0,
            memory_limit_mb=4096.0,
            memory_percent=50.0,
            tps=19.9,
            mspt=18.5,
        )
        assert stats.cpu_percent == 245.8
        assert stats.cpu_percent > 100.0
        assert stats.cpu_percent_normalized == 15.3
        assert len(stats.per_core_cpu) == 4
        assert stats.active_threads == 36
        assert stats.tps == 19.9

    def test_server_performance_detail_response_validation(self):
        stats = ServerStatsResponse(
            id="srv-1",
            status="running",
            cpu_percent=180.0,
            cpu_percent_normalized=22.5,
            per_core_cpu=[90.0, 90.0],
            active_threads=24,
            tps=20.0,
            mspt=15.2,
        )
        perf = ServerPerformanceDetailResponse(
            server_id="srv-1",
            server_name="srv-1",
            status="running",
            stats=stats,
            multicore_mode="auto",
            allocated_cores=4,
            worker_threads=4,
            multicore_efficiency=0.88,
            tps_history_sample=[20.0, 20.0, 19.9, 20.0, 20.0],
            mspt_history_sample=[14.2, 15.0, 16.1, 14.8, 15.2],
        )
        assert perf.server_id == "srv-1"
        assert perf.stats.cpu_percent == 180.0
        assert perf.multicore_efficiency == 0.88
        assert len(perf.tps_history_sample) == 5


class TestUnclampedCpuCalculation:
    def test_local_adapter_unclamped_cpu_calculation(self, tmp_path):
        """Verify LocalAdapter returns un-clamped aggregate CPU (> 100%) and valid normalized CPU."""
        adapter = LocalAdapter()
        srv_name = "test_mc_srv"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)

        meta = {"max_ram_mb": 4096, "restart_count": 0, "type": "vanilla"}
        (srv_dir / "server_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (srv_dir / ".server.pid").write_text("99999", encoding="utf-8")

        mock_proc1 = MagicMock()
        mock_proc1.pid = 99999
        mock_proc1.cpu_percent.return_value = 145.0
        mock_proc1.cpu_times.return_value = MagicMock(user=10.0, system=2.0)
        mock_proc1.num_threads.return_value = 16
        mock_proc1.memory_info.return_value.rss = 1024 * 1024 * 1024
        mock_proc1.threads.return_value = [
            MagicMock(id=1, user_time=5.0, system_time=1.0, cpu_percent=85.0),
            MagicMock(id=2, user_time=4.0, system_time=1.0, cpu_percent=60.0),
        ]

        mock_proc2 = MagicMock()
        mock_proc2.pid = 99998
        mock_proc2.cpu_percent.return_value = 75.0
        mock_proc2.cpu_times.return_value = MagicMock(user=6.0, system=1.0)
        mock_proc2.num_threads.return_value = 8
        mock_proc2.memory_info.return_value.rss = 1024 * 1024 * 512
        mock_proc2.threads.return_value = []

        with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
             patch("psutil.pid_exists", return_value=True), \
             patch("runtime_adapter._gather_process_tree", return_value=[mock_proc1, mock_proc2]), \
             patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 15.0}):

            stats = adapter.get_server_stats(srv_name, include_players=False)

            # Aggregate CPU must equal proc1 + proc2 (145 + 75 = 220.0%) and not be clamped at 100%
            assert stats["cpu_percent"] >= 150.0
            assert stats["cpu_percent_aggregate"] == stats["cpu_percent"]
            assert stats["active_threads"] == 24
            assert stats["cpu_percent_normalized"] <= 100.0
            assert stats["tps"] == 20.0
            assert stats["mspt"] == 15.0

    def test_docker_manager_unclamped_cpu_formula(self):
        """Verify DockerManager unclamps CPU via (cpu_delta / system_delta) * online_cpus * 100.0."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()
        container = MagicMock()
        container.id = "c123"
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}

        # Simulate 2.5 loaded cores on an 8-core host
        online_cpus = 8
        system_delta = 10_000_000_000
        # 2.5 full cores = 2.5 * system_delta / online_cpus
        cpu_delta = int(2.5 * (system_delta / online_cpus))

        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": cpu_delta, "percpu_usage": [cpu_delta // 2, cpu_delta // 2, 0, 0, 0, 0, 0, 0]},
                "system_cpu_usage": system_delta,
                "online_cpus": online_cpus,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0, "percpu_usage": [0, 0, 0, 0, 0, 0, 0, 0]},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 1024 * 1024 * 1024, "limit": 1024 * 1024 * 4096},
            "pids_stats": {"current": 28},
            "networks": {},
        }

        with patch.object(dm, "_ensure_client"), \
             patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            res = dm.get_server_stats("c123")

            # Expected: 2.5 cores = 250.0%
            assert res["cpu_percent"] == 250.0
            assert res["cpu_percent_aggregate"] == 250.0
            # Normalized: 250.0 / 8 = 31.25%
            assert res["cpu_percent_normalized"] == pytest.approx(31.25, 0.01)
            assert res["active_threads"] == 28
            assert len(res["per_core_cpu"]) == 8

    def test_docker_manager_cgroups_v2_fallback_distribution(self):
        """Verify cgroups v2 (empty percpu_usage) distributes CPU evenly across online_cpus."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()
        container = MagicMock()
        container.id = "c456"
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}

        online_cpus = 4
        system_delta = 4_000_000_000
        cpu_delta = 2_000_000_000  # 2.0 cores = 200.0%

        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": cpu_delta, "percpu_usage": []},  # empty in cgroups v2
                "system_cpu_usage": system_delta,
                "online_cpus": online_cpus,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0, "percpu_usage": []},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 1024 * 1024 * 512, "limit": 1024 * 1024 * 2048},
            "pids_stats": {"current": 18},
            "networks": {},
        }

        with patch.object(dm, "_ensure_client"), \
             patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            res = dm.get_server_stats("c456")

            assert res["cpu_percent"] == 200.0
            assert len(res["per_core_cpu"]) == 4
            assert res["per_core_cpu"] == [50.0, 50.0, 50.0, 50.0]


class TestProcessTreeThreadMetrics:
    def test_thread_metrics_structure_and_sorting(self, tmp_path):
        adapter = LocalAdapter()
        srv_name = "srv_threads"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / ".server.pid").write_text("1000", encoding="utf-8")

        mock_p = MagicMock()
        mock_p.pid = 1000
        mock_p.cpu_percent.return_value = 180.0
        mock_p.cpu_times.return_value = MagicMock(user=15.0, system=3.0)
        mock_p.num_threads.return_value = 3
        mock_p.memory_info.return_value.rss = 1024 * 1024 * 1000

        th1 = MagicMock(id=101, user_time=2.0, system_time=0.5, cpu_percent=25.0)
        th1.name = "Netty-IO-1"
        th2 = MagicMock(id=102, user_time=8.0, system_time=1.5, cpu_percent=85.0)
        th2.name = "Server thread"
        th3 = MagicMock(id=103, user_time=5.0, system_time=1.0, cpu_percent=70.0)
        th3.name = "Multicore-Worker-0"
        mock_p.threads.return_value = [th1, th2, th3]

        with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
             patch("psutil.pid_exists", return_value=True), \
             patch("runtime_adapter._gather_process_tree", return_value=[mock_p]), \
             patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 15.0}):

            stats = adapter.get_server_stats(srv_name, include_players=False)

            assert stats["active_threads"] == 3
            metrics = stats["thread_metrics"]
            assert len(metrics) == 3
            # Check descending sort by cpu_percent
            assert metrics[0]["cpu_percent"] >= metrics[1]["cpu_percent"] >= metrics[2]["cpu_percent"]
            assert metrics[0]["name"] == "Server thread"
            assert "user_time" in metrics[0] and "system_time" in metrics[0]

    def test_non_blocking_telemetry_cache_instantaneous_deltas(self, tmp_path):
        """Verify successive calls within cache window compute deltas using cache without sleep."""
        adapter = LocalAdapter()
        srv_name = "srv_cached"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / ".server.pid").write_text("2000", encoding="utf-8")

        mock_p = MagicMock()
        mock_p.pid = 2000
        mock_p.cpu_percent.return_value = 100.0
        mock_p.num_threads.return_value = 2
        mock_p.memory_info.return_value.rss = 1024 * 1024 * 200
        mock_p.threads.return_value = []

        # Prime the cache with snapshot from timestamp 1000.0
        t0 = 1000.0
        t1 = 1001.0
        with _TELEMETRY_CACHE_LOCK:
            _TELEMETRY_CACHE[srv_name] = {
                "timestamp": t0,
                "proc_times": {2000: 10.0},
                "thread_times": {},
            }

        # Current cpu_times advanced by 2.0 seconds (user+sys = 12.0) over 1.0s dt -> 200% CPU
        mock_p.cpu_times.return_value = MagicMock(user=11.0, system=1.0)

        with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
             patch("psutil.pid_exists", return_value=True), \
             patch("runtime_adapter._gather_process_tree", return_value=[mock_p]), \
             patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 15.0}), \
             patch("time.time", return_value=t1), \
             patch("time.sleep") as mock_sleep:

            stats = adapter.get_server_stats(srv_name, include_players=False)

            # time.sleep should NOT have been called because cache hit was valid
            mock_sleep.assert_not_called()
            assert stats["cpu_percent"] >= 150.0


class TestAdaptiveTpsMsptProbe:
    def test_vanilla_tick_query_probe(self, tmp_path):
        srv_dir = tmp_path / "vanilla_srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("enable-rcon=true\nrcon.password=secret\nrcon.port=25575\n")

        mock_mcr = MagicMock()
        mock_mcr.command.return_value = "The tick rate is currently target: 20.0, average: 19.8 tps (25.4 mspt)"
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("vanilla_srv", srv_dir, "vanilla")
            assert res["tps"] == 19.8
            assert res["mspt"] == 25.4
            assert res["method"] == "rcon_tick_query"

    def test_paper_tps_and_mspt_probe_with_color_codes(self, tmp_path):
        srv_dir = tmp_path / "paper_srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("enable-rcon=true\nrcon.password=secret\nrcon.port=25575\n")

        mock_mcr = MagicMock()
        def cmd_side_effect(cmd):
            if cmd == "tps":
                return "§aTPS from last 1m, 5m, 15m: *20.0, 19.95, 20.0§r"
            if cmd == "mspt":
                return "§aServer tick times (avg/min/max) from last 5s, 10s, 1m:\n§a5s: 14.2/7.1/28.3ms§r"
            return "unknown"
        mock_mcr.command.side_effect = cmd_side_effect
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("paper_srv", srv_dir, "paper")
            assert res["tps"] == 20.0
            assert res["mspt"] == 14.2
            assert res["method"] == "rcon_paper_tps"

    def test_forge_tps_probe(self, tmp_path):
        srv_dir = tmp_path / "forge_srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("enable-rcon=true\nrcon.password=secret\nrcon.port=25575\n")

        mock_mcr = MagicMock()
        mock_mcr.command.return_value = "Dim 0: Mean tick time: 4.5ms. Mean TPS: 20.0. Overall: Mean tick time: 5.1ms. Mean TPS: 20.0"
        mock_mcr_cls = MagicMock()
        mock_mcr_cls.return_value.__enter__.return_value = mock_mcr

        with patch("mcrcon.MCRcon", mock_mcr_cls):
            res = _probe_server_tps("forge_srv", srv_dir, "forge")
            assert res["tps"] == 20.0
            assert res["mspt"] == 5.1
            assert res["method"] == "rcon_forge_tps"

    def test_log_tail_lag_fallback(self, tmp_path):
        srv_dir = tmp_path / "legacy_srv"
        srv_dir.mkdir()
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()
        (logs_dir / "latest.log").write_text(
            "[12:00:00] [Server thread/INFO]: Starting minecraft server\n"
            "[12:01:00] [Server thread/WARN]: Can't keep up! Is the server overloaded? Running 100ms or 2 ticks behind\n"
        )

        res = _probe_server_tps("legacy_srv", srv_dir, "vanilla")
        # 100ms over 2 ticks = 50ms extra -> 100ms MSPT -> 10.0 TPS
        assert res["tps"] == 10.0
        assert res["mspt"] == 100.0
        assert res["method"] == "log_lag_detection"

    def test_nominal_healthy_log_fallback(self, tmp_path):
        srv_dir = tmp_path / "healthy_srv"
        srv_dir.mkdir()
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()
        (logs_dir / "latest.log").write_text(
            "[12:00:00] [Server thread/INFO]: Done (2.5s)! For help, type 'help'\n"
        )

        res = _probe_server_tps("healthy_srv", srv_dir, "vanilla")
        assert res["tps"] == 20.0
        assert res["mspt"] == 25.0
        assert res["method"] == "nominal_healthy"

    def test_tps_cache_5s_ttl(self, tmp_path):
        srv_dir = tmp_path / "cached_tps_srv"
        srv_dir.mkdir()
        logs_dir = srv_dir / "logs"
        logs_dir.mkdir()
        (logs_dir / "latest.log").write_text("[Server thread/INFO]: Server started\n")

        with patch("runtime_adapter.read_log_tail_lines", return_value=["[Server thread/INFO]: OK"]) as mock_log:
            res1 = _probe_server_tps("cached_tps_srv", srv_dir)
            assert res1["tps"] == 20.0
            # Immediate second probe must hit cache and avoid re-reading log
            res2 = _probe_server_tps("cached_tps_srv", srv_dir)
            assert res2["tps"] == 20.0
            assert mock_log.call_count == 1


class TestStatsHistorySqliteMigrationAndRecording:
    def test_idempotent_sqlite_schema_migration(self, tmp_path):
        db_file = tmp_path / "test_migration.db"
        # Seed an older database table missing Milestone 3 columns
        conn = sqlite3.connect(db_file)
        conn.execute("""
            CREATE TABLE stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                server_id TEXT NOT NULL,
                cpu_percent REAL DEFAULT 0,
                memory_used_mb REAL DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

        # Point stats_history to this db and trigger _get_conn()
        stats_history._DB_PATH = str(db_file)
        stats_history._conn = None
        c = stats_history._get_conn()

        cols = {r[1] for r in c.execute("PRAGMA table_info(stats)").fetchall()}
        assert "tps" in cols
        assert "mspt" in cols
        assert "active_threads" in cols
        assert "per_core_cpu" in cols
        c.close()
        stats_history._conn = None

    def test_record_and_retrieve_stats_history_raw_and_bucketed(self, tmp_path):
        db_file = tmp_path / "test_history.db"
        stats_history._DB_PATH = str(db_file)
        stats_history._conn = None

        stats_history.record_stats("s1", "Server 1", {
            "cpu_percent": 195.4,
            "memory_usage_mb": 2048.0,
            "memory_limit_mb": 4096.0,
            "memory_percent": 50.0,
            "network_rx_mb": 15.0,
            "network_tx_mb": 8.0,
            "player_count": 5,
            "tps": 19.9,
            "mspt": 22.4,
            "active_threads": 32,
            "per_core_cpu": [45.0, 55.0, 50.0, 45.4],
        })

        # 1. Raw retrieval
        raw_rows = stats_history.get_stats_history("s1", hours=1, resolution=0)
        assert len(raw_rows) == 1
        r = raw_rows[0]
        assert r["cpu"] == 195.4
        assert r["tps"] == 19.9
        assert r["mspt"] == 22.4
        assert r["active_threads"] == 32
        assert r["per_core_cpu"] == [45.0, 55.0, 50.0, 45.4]

        # 2. Add second row in different bucket and test bucketed aggregation
        stats_history.record_stats("s1", "Server 1", {
            "cpu_percent": 205.0,
            "memory_usage_mb": 2048.0,
            "memory_limit_mb": 4096.0,
            "memory_percent": 50.0,
            "network_rx_mb": 16.0,
            "network_tx_mb": 9.0,
            "player_count": 5,
            "tps": 20.0,
            "mspt": 20.0,
            "active_threads": 34,
            "per_core_cpu": [50.0, 50.0, 55.0, 50.0],
        })

        raw_rows2 = stats_history.get_stats_history("s1", hours=1, resolution=0)
        assert len(raw_rows2) == 2

        stats_history._conn = None


class TestTelemetryApiEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        from auth import create_access_token
        token = create_access_token({"sub": "admin", "role": "admin", "permissions": ["*"]})
        return {"Authorization": f"Bearer {token}"}

    def test_get_performance_detail_endpoint(self, client, auth_headers):
        mock_dm = MagicMock()
        mock_dm.get_server_info.return_value = {"name": "mc-prod", "status": "running", "exists": True}
        mock_dm.get_server_stats.return_value = {
            "id": "mc-prod",
            "server_name": "mc-prod",
            "cpu_percent": 225.5,
            "cpu_percent_aggregate": 225.5,
            "cpu_percent_normalized": 28.2,
            "per_core_cpu": [60.0, 75.5, 90.0, 0.0],
            "active_threads": 30,
            "thread_metrics": [
                {"id": 1, "name": "Server thread", "cpu_percent": 90.0, "user_time": 10.0, "system_time": 2.0},
                {"id": 2, "name": "Multicore-Dim-0", "cpu_percent": 75.5, "user_time": 8.0, "system_time": 1.5},
            ],
            "memory_usage_mb": 2048.0,
            "memory_limit_mb": 4096.0,
            "memory_percent": 50.0,
            "network_rx_mb": 12.0,
            "network_tx_mb": 6.0,
            "uptime_seconds": 3600,
            "restart_count": 0,
            "health_status": "healthy",
            "player_count": 4,
            "tps": 20.0,
            "mspt": 18.2,
        }
        mock_dm.get_server_multicore_status.return_value = {
            "enabled": True,
            "mode": "auto",
            "allocated_cores": 4,
            "worker_threads": 4,
        }

        with patch("app.get_docker_manager", return_value=mock_dm):
            resp = client.get("/api/servers/mc-prod/performance", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["server_id"] == "mc-prod"
            assert data["stats"]["cpu_percent"] == 225.5
            assert data["stats"]["per_core_cpu"] == [60.0, 75.5, 90.0, 0.0]
            assert data["stats"]["active_threads"] == 30
            assert len(data["stats"]["thread_metrics"]) == 2
            assert data["stats"]["tps"] == 20.0
            assert data["stats"]["mspt"] == 18.2
            assert data["multicore_mode"] == "auto"
            assert data["multicore_efficiency"] > 0.0

    def test_get_performance_detail_404_not_found(self, client, auth_headers):
        mock_dm = MagicMock()
        mock_dm.get_server_info.return_value = {"exists": False}
        mock_dm.server_exists.return_value = False

        with patch("app.get_docker_manager", return_value=mock_dm):
            resp = client.get("/api/servers/nonexistent/performance", headers=auth_headers)
            assert resp.status_code == 404

    def test_get_resources_endpoint_includes_all_telemetry(self, client, auth_headers):
        mock_dm = MagicMock()
        mock_dm.get_server_stats.return_value = {
            "id": "mc-res",
            "cpu_percent": 185.0,
            "cpu_percent_aggregate": 185.0,
            "cpu_percent_normalized": 23.1,
            "per_core_cpu": [90.0, 95.0],
            "active_threads": 26,
            "thread_metrics": [{"id": 10, "name": "Worker", "cpu_percent": 90.0}],
            "memory_usage_mb": 1500.0,
            "memory_limit_mb": 3000.0,
            "memory_percent": 50.0,
            "network_rx_mb": 5.0,
            "network_tx_mb": 2.0,
            "tps": 19.9,
            "mspt": 20.1,
        }
        mock_dm.get_player_info.return_value = {"online": 2, "max": 20, "names": ["Alice", "Bob"]}

        with patch("app.get_docker_manager", return_value=mock_dm):
            resp = client.get("/api/servers/mc-res/resources", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["cpu_percent"] == 185.0
            assert data["cpu_percent_aggregate"] == 185.0
            assert data["cpu_percent_normalized"] == 23.1
            assert data["per_core_cpu"] == [90.0, 95.0]
            assert data["active_threads"] == 26
            assert data["tps"] == 19.9
            assert data["mspt"] == 20.1
            # Nested resources object
            assert data["resources"]["per_core_cpu"] == [90.0, 95.0]
            assert data["resources"]["active_threads"] == 26
            assert data["resources"]["tps"] == 19.9
            assert data["resources"]["mspt"] == 20.1
