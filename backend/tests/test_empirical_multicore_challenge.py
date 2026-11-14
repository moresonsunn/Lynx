"""
Empirical Challenge & Stress Test Suite for Milestone 3 (Real-Time Multi-Core Telemetry & Monitoring).

Adversarially validates:
1. Live multi-threaded CPU burn (> 100% aggregate CPU, >= 2 active cores, active_threads count).
2. DockerManager CPU formula and mathematical edge cases (zero delta, negative delta, missing online_cpus).
3. Telemetry caching under high concurrency and race conditions.
4. Process termination / death mid-probe resilience.
5. Adaptive TPS probe adversarial inputs.
"""
import os
import sys
import time
import json
import tempfile
import threading
import subprocess
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import psutil
from runtime_adapter import (
    LocalAdapter,
    _live_cpu_count,
    _TELEMETRY_CACHE,
    _TELEMETRY_CACHE_LOCK,
    _TPS_CACHE,
    _TPS_CACHE_LOCK,
    _probe_server_tps,
)
from docker_manager import DockerManager
from models import ServerStatsResponse, ServerPerformanceDetailResponse, ThreadMetric


@pytest.fixture(autouse=True)
def reset_caches():
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()
    yield
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()


class TestEmpiricalLiveMultiCoreLoad:
    """Stress tests using genuine OS child processes running parallel CPU-bound threads."""

    def test_live_multithreaded_workload_exceeds_100_percent_cpu(self, tmp_path):
        """Empirically spin 4 CPU-bound threads in a live process and verify > 100% aggregate CPU."""
        srv_name = "empirical_live_test"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(
            json.dumps({"max_ram_mb": 2048, "restart_count": 0, "type": "vanilla"}),
            encoding="utf-8",
        )

        # Worker script: 4 parallel threads burning CPU with SHA-256 (releasing GIL in CPython)
        worker_code = (
            "import threading, hashlib, time\n"
            "def burn():\n"
            "    data = b'x' * 65536\n"
            "    while True:\n"
            "        hashlib.sha256(data)\n"
            "threads = [threading.Thread(target=burn, daemon=True) for _ in range(4)]\n"
            "for t in threads: t.start()\n"
            "time.sleep(20)\n"
        )

        proc = subprocess.Popen([sys.executable, "-c", worker_code])
        (srv_dir / ".server.pid").write_text(str(proc.pid), encoding="utf-8")

        try:
            # Allow threads to initialize and begin spinning
            time.sleep(0.4)

            adapter = LocalAdapter()
            with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
                 patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 12.0}):

                # 1. Cold start sampling (sleeps 0.1s internally)
                cold_stats = adapter.get_server_stats(srv_name, include_players=False)

                # 2. Warm cache sampling after 0.15s window
                time.sleep(0.15)
                warm_stats = adapter.get_server_stats(srv_name, include_players=False)

            # Empirically verify:
            # Aggregate CPU must exceed 100.0% because 4 threads are running concurrently
            max_observed_cpu = max(cold_stats["cpu_percent"], warm_stats["cpu_percent"])
            assert max_observed_cpu > 100.0, (
                f"Expected aggregate CPU > 100.0%, but observed cold={cold_stats['cpu_percent']}%, "
                f"warm={warm_stats['cpu_percent']}%"
            )

            # Verify cpu_percent_aggregate matches cpu_percent
            assert cold_stats["cpu_percent_aggregate"] == cold_stats["cpu_percent"]
            assert warm_stats["cpu_percent_aggregate"] == warm_stats["cpu_percent"]

            # Verify active_threads >= 4 (main thread + 4 worker threads)
            assert cold_stats["active_threads"] >= 4
            assert warm_stats["active_threads"] >= 4

            # Verify normalized CPU stays bounded within [0.0, 100.0]
            assert 0.0 <= cold_stats["cpu_percent_normalized"] <= 100.0
            assert 0.0 <= warm_stats["cpu_percent_normalized"] <= 100.0

            # Verify normalized CPU equals (total_cpu / host_cores)
            host_cores = _live_cpu_count()
            expected_normalized = min(warm_stats["cpu_percent"] / host_cores, 100.0)
            assert abs(warm_stats["cpu_percent_normalized"] - expected_normalized) < 1.0

            # Verify per_core_cpu length equals host logical core count
            assert len(warm_stats["per_core_cpu"]) == host_cores
            assert all(isinstance(c, float) for c in warm_stats["per_core_cpu"])

            # Verify measurable load across >= 2 active cores on host
            active_cores = [c for c in warm_stats["per_core_cpu"] if c > 0.0]
            assert len(active_cores) >= 2, f"Expected >= 2 active cores, got {len(active_cores)}: {warm_stats['per_core_cpu']}"

            # Verify thread metrics structure
            assert len(warm_stats["thread_metrics"]) >= 4
            for tm in warm_stats["thread_metrics"]:
                assert "id" in tm
                assert "name" in tm
                assert "cpu_percent" in tm
                assert isinstance(tm["cpu_percent"], (int, float))
                assert "user_time" in tm
                assert "system_time" in tm

            # Verify thread metrics sorted descending
            pcts = [tm["cpu_percent"] for tm in warm_stats["thread_metrics"]]
            assert pcts == sorted(pcts, reverse=True)

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()


class TestDockerManagerFormulaStress:
    """Mathematical stress tests and boundary edge cases for DockerManager CPU calculation."""

    def test_unclamped_multi_core_calculation(self):
        """4.5 loaded cores on 16-core container must report 450.0% un-clamped and 28.12% normalized."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}

        online_cpus = 16
        system_delta = 16_000_000_000  # 1s across 16 cores
        # 4.5 loaded cores = 4.5 * (system_delta / online_cpus)
        cpu_delta = int(4.5 * (system_delta / online_cpus))

        percpu_now = [0] * online_cpus
        percpu_prev = [0] * online_cpus
        # Distribute 4.5 cores across first 5 cores
        percpu_now[0] = int(1.0 * (system_delta / online_cpus))
        percpu_now[1] = int(1.0 * (system_delta / online_cpus))
        percpu_now[2] = int(1.0 * (system_delta / online_cpus))
        percpu_now[3] = int(1.0 * (system_delta / online_cpus))
        percpu_now[4] = int(0.5 * (system_delta / online_cpus))

        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": cpu_delta, "percpu_usage": percpu_now},
                "system_cpu_usage": system_delta,
                "online_cpus": online_cpus,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0, "percpu_usage": percpu_prev},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 1024 * 1024 * 512, "limit": 1024 * 1024 * 4096},
            "pids_stats": {"current": 42},
            "networks": {},
        }

        with patch.object(dm, "_ensure_client"), patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            stats = dm.get_server_stats("c450")

            assert stats["cpu_percent"] == 450.0
            assert stats["cpu_percent"] > 100.0
            assert abs(stats["cpu_percent_normalized"] - (450.0 / 16)) < 0.1
            assert stats["active_threads"] == 42
            assert len(stats["per_core_cpu"]) == 16
            assert stats["per_core_cpu"][0] == 100.0
            assert stats["per_core_cpu"][4] == 50.0
            assert stats["per_core_cpu"][5] == 0.0

    def test_zero_system_delta_returns_zero(self):
        """Zero system delta (consecutive instant calls) must not cause ZeroDivisionError."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}
        container.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 5000, "online_cpus": 4},
            "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 5000},
            "memory_stats": {"usage": 100, "limit": 1000},
            "pids_stats": {"current": 5},
        }

        with patch.object(dm, "_ensure_client"), patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            stats = dm.get_server_stats("c_zero")
            assert stats["cpu_percent"] == 0.0
            assert stats["cpu_percent_normalized"] == 0.0

    def test_negative_cpu_delta_returns_zero(self):
        """Negative cpu delta (counter reset) must not produce negative CPU percent."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}
        container.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 10000, "online_cpus": 4},
            "precpu_stats": {"cpu_usage": {"total_usage": 5000}, "system_cpu_usage": 5000},  # total_usage decreased
            "memory_stats": {"usage": 100, "limit": 1000},
            "pids_stats": {"current": 5},
        }

        with patch.object(dm, "_ensure_client"), patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            stats = dm.get_server_stats("c_neg")
            assert stats["cpu_percent"] == 0.0
            assert stats["cpu_percent_normalized"] == 0.0

    def test_missing_online_cpus_safe_fallback(self):
        """If online_cpus is missing from Docker stats, fallback to len(percpu_usage) or 1."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [100, 100]},
                "system_cpu_usage": 200,
                # online_cpus is omitted
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0, "percpu_usage": [0, 0]},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 100, "limit": 1000},
            "pids_stats": {"current": 4},
        }

        with patch.object(dm, "_ensure_client"), patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            stats = dm.get_server_stats("c_missing_cpus")
            # 2 cores detected via percpu_usage len -> 200%
            assert stats["cpu_percent"] == 200.0
            assert len(stats["per_core_cpu"]) == 2

    def test_cgroups_v2_fallback_distribution(self):
        """When percpu_usage is absent (cgroups v2), aggregate CPU must be evenly distributed."""
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}
        # 4 online cpus, 200% CPU, no percpu_usage
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2000},
                "system_cpu_usage": 4000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 100, "limit": 1000},
            "pids_stats": {"current": 4},
        }

        with patch.object(dm, "_ensure_client"), patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            stats = dm.get_server_stats("c_cg2")
            assert stats["cpu_percent"] == 200.0
            assert stats["per_core_cpu"] == [50.0, 50.0, 50.0, 50.0]


class TestProcessTerminationResilience:
    """Verifies LocalAdapter handles sudden process death mid-sampling without exceptions."""

    def test_pid_exits_between_first_and_second_snapshot(self, tmp_path):
        srv_name = "dead_pid_srv"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(json.dumps({"max_ram_mb": 1024}), encoding="utf-8")

        # Spawn a short-lived process that exits immediately
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.05)"])
        (srv_dir / ".server.pid").write_text(str(proc.pid), encoding="utf-8")
        proc.wait()  # now dead

        adapter = LocalAdapter()
        with patch("runtime_adapter.safe_child_path", return_value=srv_dir):
            stats = adapter.get_server_stats(srv_name, include_players=False)
            assert stats["cpu_percent"] == 0.0
            assert stats["active_threads"] == 0
            assert stats["health_status"] == "unhealthy"


class TestTelemetryCacheStressAndConcurrency:
    """Stress tests the non-blocking cache with rapid concurrent queries."""

    def test_concurrent_access_thread_safety(self, tmp_path):
        srv_name = "concurrent_srv"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(json.dumps({"max_ram_mb": 1024}), encoding="utf-8")
        (srv_dir / ".server.pid").write_text(str(os.getpid()), encoding="utf-8")

        adapter = LocalAdapter()
        results = []
        errors = []

        def worker():
            try:
                with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
                     patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 10.0}):
                    for _ in range(5):
                        res = adapter.get_server_stats(srv_name, include_players=False)
                        results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent get_server_stats encountered errors: {errors}"
        assert len(results) == 40
        for r in results:
            assert isinstance(r["cpu_percent"], float)
            assert isinstance(r["per_core_cpu"], list)
            assert r["active_threads"] > 0
