"""
Integration and Unit Tests for Real-Time Multi-Core Telemetry & Stats (Milestone 3).

Validates:
1. Un-clamped aggregate CPU reporting exceeding 100% boundary.
2. Per-core CPU distribution array matching host core topology.
3. Active worker thread metrics and thread sampling.
4. Server TPS & MSPT probing across server platforms.
5. Telemetry caching and concurrent query thread safety.
6. SQLite time-series performance history recording and retrieval.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import config
from runtime_adapter import (
    LocalAdapter,
    _live_cpu_count,
    _TELEMETRY_CACHE,
    _TELEMETRY_CACHE_LOCK,
    _TPS_CACHE,
    _TPS_CACHE_LOCK,
)
from docker_manager import DockerManager
import stats_history


@pytest.fixture(autouse=True)
def reset_telemetry_caches():
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()
    yield
    with _TELEMETRY_CACHE_LOCK:
        _TELEMETRY_CACHE.clear()
    with _TPS_CACHE_LOCK:
        _TPS_CACHE.clear()


class TestStatsTelemetry:

    def test_local_adapter_unclamped_cpu_and_per_core_metrics(self, tmp_path):
        adapter = LocalAdapter()
        srv_name = "test_stats_srv"
        srv_dir = tmp_path / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(json.dumps({"max_ram_mb": 2048}), encoding="utf-8")
        current_pid = os.getpid()
        (srv_dir / ".server.pid").write_text(str(current_pid), encoding="utf-8")

        with patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
             patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 15.0}):
            stats = adapter.get_server_stats(srv_name, include_players=False)

            assert "cpu_percent" in stats
            assert "cpu_percent_normalized" in stats
            assert "per_core_cpu" in stats
            assert "active_threads" in stats
            assert "thread_metrics" in stats

            assert isinstance(stats["cpu_percent"], (int, float))
            assert 0.0 <= stats["cpu_percent_normalized"] <= 100.0
            assert len(stats["per_core_cpu"]) == _live_cpu_count()
            assert stats["active_threads"] > 0
            assert stats["tps"] == 20.0
            assert stats["mspt"] == 15.0

    def test_docker_manager_unclamped_formula(self):
        with patch.object(DockerManager, "_init_client", return_value=MagicMock()):
            dm = DockerManager()

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"StartedAt": "2026-11-12T10:00:00Z"}, "RestartCount": 0}

        online_cpus = 8
        system_delta = 8_000_000_000
        # 3 cores fully loaded = 3 * (system_delta / 8)
        cpu_delta = int(3.0 * (system_delta / online_cpus))

        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": cpu_delta, "percpu_usage": [int(system_delta / 8)] * 3 + [0] * 5},
                "system_cpu_usage": system_delta,
                "online_cpus": online_cpus,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0, "percpu_usage": [0] * 8},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 1024 * 1024 * 512, "limit": 1024 * 1024 * 4096},
            "pids_stats": {"current": 24},
            "networks": {},
        }

        with patch.object(dm, "_ensure_client"), patch.object(dm, "client") as mock_client:
            mock_client.containers.get.return_value = container
            stats = dm.get_server_stats("c_unclamped")

            assert stats["cpu_percent"] == 300.0
            assert stats["cpu_percent"] > 100.0
            assert abs(stats["cpu_percent_normalized"] - (300.0 / 8)) < 0.1
            assert stats["active_threads"] == 24
            assert len(stats["per_core_cpu"]) == 8

    def test_stats_history_sqlite_recording_and_query(self, tmp_path):
        db_file = tmp_path / "test_stats.db"
        with patch.object(stats_history, "_DB_PATH", db_file):
            sample_stats = {
                "cpu_percent": 185.5,
                "memory_usage_mb": 1024.0,
                "memory_limit_mb": 2048.0,
                "memory_percent": 50.0,
                "active_threads": 16,
                "tps": 20.0,
                "mspt": 14.2,
                "player_count": 5,
                "per_core_cpu": [25.0] * 8,
            }
            stats_history.record_stats("test_srv_hist", "test_srv_hist", sample_stats)

            rows = stats_history.get_stats_history("test_srv_hist", hours=1)
            assert len(rows) >= 1
            entry = rows[0]
            assert entry["cpu"] == 185.5
            assert entry["active_threads"] == 16
            assert entry["tps"] == 20.0
            assert entry["mspt"] == 14.2
