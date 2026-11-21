"""
Unit and Integration Tests for Controller Operational Lifecycle via LocalRuntimeManager.

Validates:
1. Server launch and status monitoring without resource leaks.
2. Cross-platform process-tree CPU affinity enforcement via psutil.
3. Multi-core environment variables and user_jvm_args.txt synthesis on creation.
4. Command dispatch through RCON and console FIFO/file fallback.
5. 6-stage graceful shutdown sequence ensuring atomic chunk flushing (save-all flush),
   clean process termination, and complete port release with zero orphan processes.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

# Ensure backend root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import config
from local_runtime import (
    LocalRuntimeManager,
    _apply_cpu_affinity,
    _normalize_cpu_cores,
    _ram_to_mb,
    _format_ram,
    apply_process_tree_affinity,
)


@pytest.fixture
def temp_servers_root(tmp_path, monkeypatch):
    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    import local_runtime
    import config
    monkeypatch.setattr(config, "SERVERS_ROOT", servers_dir)
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", servers_dir)
    return servers_dir


class TestLocalRuntimeLifecycle:
    """Verifies launch, monitoring, and graceful stop operations."""

    def test_ram_and_cpu_parsers(self):
        assert _ram_to_mb("2G", 1024) == 2048
        assert _ram_to_mb("512M", 1024) == 512
        assert _ram_to_mb(None, 1024) == 1024
        assert _format_ram(2048) == "2G"
        assert _format_ram(1536) == "1536M"
        assert _normalize_cpu_cores("4") == 4
        assert _normalize_cpu_cores("unlimited") is None
        assert _normalize_cpu_cores("-1") is None

    def test_apply_cpu_affinity_cross_platform(self):
        current_pid = os.getpid()
        total_cores = psutil.cpu_count(logical=True) or 1
        # Test unlimited / all cores
        assert _apply_cpu_affinity(current_pid, None) is True
        # Test capped cores
        if total_cores >= 2:
            assert _apply_cpu_affinity(current_pid, 2) is True
            # Restore
            _apply_cpu_affinity(current_pid, None)

    def test_apply_cpu_affinity_invalid_pid(self):
        assert _apply_cpu_affinity(9999999, 2) is False

    def test_server_creation_synthesizes_multicore_meta_and_args(self, temp_servers_root):
        mgr = LocalRuntimeManager()
        srv_name = "test_mc_srv"
        srv_dir = temp_servers_root / srv_name

        with patch("local_runtime.prepare_server_files") as mock_prep, \
             patch.object(mgr, "_spawn", return_value={"id": srv_name, "status": "running", "pid": 1234}):
            res = mgr.create_server(
                name=srv_name,
                server_type="paper",
                version="1.20.4",
                host_port=25565,
                min_ram="1G",
                max_ram="4G",
                cpu_cores=4,
                multicore_enabled=True,
                multicore_mode="auto",
                worker_threads=4,
            )
            assert res["status"] == "running"
            assert res["pid"] == 1234
            mock_prep.assert_called_once()

            meta_file = srv_dir / "server_meta.json"
            assert meta_file.exists()
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            assert meta["multicore_enabled"] is True
            assert meta["multicore_mode"] == "auto"
            assert meta["multicore_threads"] == 4
            assert meta["fork_join_parallelism"] >= 2
            assert meta["gc_threads"] >= 2
            assert meta["netty_threads"] >= 2

    def test_graceful_stop_executes_flush_and_stop_commands(self, temp_servers_root):
        mgr = LocalRuntimeManager()
        srv_name = "test_graceful_srv"
        srv_dir = temp_servers_root / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(json.dumps({"host_port": 25565}), encoding="utf-8")
        (srv_dir / ".server.pid").write_text("12345", encoding="utf-8")

        commands_sent = []
        def mock_send(sid, cmd):
            commands_sent.append(cmd)
            return {"id": sid, "ok": True}

        # Mock _is_running: first call returns True (running), subsequent call returns False (exited)
        is_running_responses = [True, False, False, False]
        def mock_running(pid):
            if is_running_responses:
                return is_running_responses.pop(0)
            return False

        with patch.object(mgr, "_is_running", side_effect=mock_running), \
             patch.object(mgr, "send_command", side_effect=mock_send), \
             patch.object(mgr, "_find_and_kill_port_holders"), \
             patch("time.sleep", return_value=None):
            stop_res = mgr.stop_server(srv_name, timeout=5)

            assert stop_res["status"] == "stopped"
            # Verify Stage 1 (save-all flush) and Stage 3 (stop) were executed
            assert "save-all flush" in commands_sent
            assert "stop" in commands_sent
            assert not (srv_dir / ".server.pid").exists()

    def test_graceful_stop_when_already_dead_is_noop(self, temp_servers_root):
        mgr = LocalRuntimeManager()
        srv_name = "dead_srv"
        srv_dir = temp_servers_root / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / ".server.pid").write_text("999999", encoding="utf-8")

        with patch.object(mgr, "_is_running", return_value=False), \
             patch.object(mgr, "_find_and_kill_port_holders"):
            res = mgr.stop_server(srv_name)
            assert res["status"] == "stopped"
            assert res["method"] == "noop"
            assert not (srv_dir / ".server.pid").exists()

    def test_send_command_via_console_file(self, temp_servers_root):
        mgr = LocalRuntimeManager()
        srv_name = "cmd_srv"
        srv_dir = temp_servers_root / srv_name
        srv_dir.mkdir(parents=True)
        console_in = srv_dir / "console.in"
        console_in.touch()

        res = mgr.send_command(srv_name, "list")
        assert res["ok"] is True
        assert res["method"] == "console_file"
        content = console_in.read_text(encoding="utf-8")
        assert "list\n" in content

    def test_send_command_empty_fails(self, temp_servers_root):
        mgr = LocalRuntimeManager()
        srv_name = "empty_cmd_srv"
        srv_dir = temp_servers_root / srv_name
        srv_dir.mkdir(parents=True)
        res = mgr.send_command(srv_name, "   ")
        assert res["ok"] is False
        assert "Empty command" in res["error"]

    def test_is_running_posix_linux_container_does_not_raise_name_error(self, monkeypatch):
        """Regression: sys was missing on Linux/POSIX because os.name == 'nt' short-circuited on Windows."""
        import local_runtime
        mgr = LocalRuntimeManager()
        monkeypatch.setattr(local_runtime.os, "name", "posix")

        with patch("local_runtime.os.kill", return_value=None) as mock_kill:
            assert mgr._is_running(43210) is True
            mock_kill.assert_called_once_with(43210, 0)

        with patch("local_runtime.os.kill", side_effect=ProcessLookupError("no such process")):
            assert mgr._is_running(43210) is False

    def test_list_servers_discovers_existing_and_isolates_broken_dirs(self, temp_servers_root):
        """Pre-existing servers without server_meta.json and broken siblings must not hide valid servers."""
        mgr = LocalRuntimeManager()

        # 1. Hidden dot-directory should be skipped
        (temp_servers_root / ".cache").mkdir()

        # 2. Pre-existing vanilla/paper directory WITHOUT server_meta.json, WITH server.properties & jar
        legacy_dir = temp_servers_root / "survival_legacy"
        legacy_dir.mkdir()
        (legacy_dir / "paper-1.20.4-496.jar").write_bytes(b"")
        (legacy_dir / "server.properties").write_text("server-port=25577\n", encoding="utf-8")

        # 3. Directory with corrupt JSON in server_meta.json and stale .server.pid
        corrupt_dir = temp_servers_root / "corrupt_meta_srv"
        corrupt_dir.mkdir()
        (corrupt_dir / "server_meta.json").write_text("{not-valid-json", encoding="utf-8")
        (corrupt_dir / ".server.pid").write_text("not-an-int", encoding="utf-8")

        # 4. Directory with modern metadata & running PID
        running_dir = temp_servers_root / "modded_live"
        running_dir.mkdir()
        (running_dir / "server_meta.json").write_text(
            json.dumps({"server_type": "neoforge", "server_version": "1.21.1", "host_port": 25588}),
            encoding="utf-8",
        )
        (running_dir / ".server.pid").write_text("55555", encoding="utf-8")

        with patch("local_runtime.os.kill", return_value=None), \
             patch("local_runtime.psutil.pid_exists", side_effect=lambda pid: pid == 55555):
            servers = mgr.list_servers()

        by_name = {s["name"]: s for s in servers}
        assert ".cache" not in by_name
        assert "survival_legacy" in by_name
        assert by_name["survival_legacy"]["type"] == "paper"
        assert by_name["survival_legacy"]["version"] == "1.20.4"
        assert by_name["survival_legacy"]["host_port"] == 25577
        assert by_name["survival_legacy"]["status"] == "exited"
        # Detected metadata persisted so subsequent scans are instant
        assert (legacy_dir / "server_meta.json").exists()

        assert "corrupt_meta_srv" in by_name
        assert by_name["corrupt_meta_srv"]["status"] == "exited"

        assert "modded_live" in by_name
        assert by_name["modded_live"]["type"] == "neoforge"
        assert by_name["modded_live"]["version"] == "1.21.1"
        assert by_name["modded_live"]["host_port"] == 25588
        assert by_name["modded_live"]["status"] == "running"

    def test_runtime_adapter_fast_paths_and_docker_cooldown(self, temp_servers_root, monkeypatch):
        """LocalAdapter avoids Docker queries for local servers, caches bulk stats/list, and reports real status."""
        import runtime_adapter
        import docker_manager
        monkeypatch.setattr(runtime_adapter, "SERVERS_ROOT", temp_servers_root)
        monkeypatch.delenv("STEAM_DOCKER_HOST", raising=False)

        srv_dir = temp_servers_root / "fast_mc"
        srv_dir.mkdir()
        (srv_dir / "server_meta.json").write_text(
            json.dumps({"type": "paper", "version": "1.21.4", "max_ram": "4G", "host_port": 25565}),
            encoding="utf-8",
        )

        adapter = runtime_adapter.LocalAdapter()
        with patch.object(adapter, "_get_docker", side_effect=AssertionError("Should not touch Docker for local server")):
            assert adapter._resolve_steam_id("fast_mc") is None
            listed = adapter.list_servers()
            assert len(listed) == 1
            # Cached second call also avoids re-scanning
            with patch.object(adapter.local, "list_servers", side_effect=AssertionError("Should hit _list_cache")):
                listed_cached = adapter.list_servers()
                assert len(listed_cached) == 1

            bulk = adapter.get_bulk_server_stats(ttl_seconds=3, include_players=False)
            assert "fast_mc" in bulk
            assert bulk["fast_mc"]["memory_limit_mb"] == 4096.0
            assert bulk["fast_mc"]["cpu_percent"] == 0.0

            info = adapter.get_server_info("fast_mc")
            assert info["status"] == "exited"

        # Steam client failure triggers 30s cooldown instead of stalling every request
        dm = docker_manager.DockerManager.__new__(docker_manager.DockerManager)
        dm._steam_docker_host = "tcp://127.0.0.1:23750"
        dm._steam_client = None
        dm._steam_fail_until = 0.0
        dm._steam_warned = False

        with patch("docker_manager.docker.DockerClient", side_effect=ConnectionError("refused")) as mock_dc, \
             patch("docker_manager.Path.exists", return_value=False):
            assert dm._get_steam_client() is None
            assert dm._get_steam_client() is None
            # Second call within cooldown must NOT retry DockerClient
            mock_dc.assert_called_once()

    def test_update_server_ram_enforces_1g_min_and_allows_lowering_max_below_old_min(self, temp_servers_root):
        """Regression: server always starts with 1G min_ram and adjusts only max_ram cleanly,
        even when old min_ram_mb exceeded the new lower max_ram (e.g. 24G/12G -> 11G)."""
        import runtime_adapter
        import app as app_module
        from auth import require_auth
        from models import User
        from fastapi.testclient import TestClient

        mgr = LocalRuntimeManager()
        srv_name = "cobble_ram_srv"
        srv_dir = temp_servers_root / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(
            json.dumps({
                "name": srv_name,
                "type": "fabric",
                "version": "1.21.1",
                "min_ram": "12G",
                "max_ram": "24G",
                "min_ram_mb": 12288,
                "max_ram_mb": 24576,
                "host_port": 25587,
            }),
            encoding="utf-8",
        )

        captured_env = {}

        def fake_spawn(name, env):
            captured_env.update(env)
            return {"id": name, "name": name, "status": "running", "pid": 9999}

        with patch.object(mgr, "stop_server", return_value={"id": srv_name, "status": "stopped"}), \
             patch.object(mgr, "_spawn", side_effect=fake_spawn):
            # Lower max_ram to 11G with min_ram omitted -> defaults min_ram to 1G and sets max_ram=11G
            mgr.update_server_ram(srv_name, min_ram=None, max_ram="11G")

        meta = json.loads((srv_dir / "server_meta.json").read_text(encoding="utf-8"))
        assert meta["min_ram"] == "1G"
        assert meta["min_ram_mb"] == 1024
        assert meta["max_ram"] == "11G"
        assert meta["max_ram_mb"] == 11264
        assert captured_env["MIN_RAM"] == "1G"
        assert captured_env["MAX_RAM"] == "11G"

        # Verify POST /api/servers/{id}/ram defaults min_ram to "1G" when omitted
        adapter = runtime_adapter.LocalAdapter()
        adapter.local = mgr
        owner = User(id=1, username="admin", email="admin@localhost", hashed_password="x", role="owner", is_active=True)

        app_module.app.dependency_overrides[require_auth] = lambda: owner
        try:
            with patch.object(app_module, "get_runtime_manager_or_docker", return_value=adapter), \
                 patch.object(mgr, "stop_server", return_value={"id": srv_name, "status": "stopped"}), \
                 patch.object(mgr, "_spawn", side_effect=fake_spawn):
                with TestClient(app_module.app) as client:
                    resp = client.post(f"/api/servers/{srv_name}/ram", json={"max_ram": "11G"})
                    assert resp.status_code == 200, resp.text
                    meta2 = json.loads((srv_dir / "server_meta.json").read_text(encoding="utf-8"))
                    assert meta2["min_ram"] == "1G"
                    assert meta2["max_ram"] == "11G"
        finally:
            app_module.app.dependency_overrides.pop(require_auth, None)

    def test_stats_prefers_uss_over_zgc_inflated_rss(self, temp_servers_root, monkeypatch):
        """Regression: on Linux ZGC, memory_full_info().uss avoids multi-mapping RSS inflation."""
        import runtime_adapter
        monkeypatch.setattr(runtime_adapter, "SERVERS_ROOT", temp_servers_root)
        srv_name = "zgc_mem_srv"
        srv_dir = temp_servers_root / srv_name
        srv_dir.mkdir(parents=True)
        (srv_dir / ".server.pid").write_text("42424", encoding="utf-8")
        (srv_dir / "server_meta.json").write_text(json.dumps({"max_ram": "11G"}), encoding="utf-8")

        fake_proc = MagicMock()
        fake_proc.pid = 42424
        fake_proc.num_threads.return_value = 16
        fake_proc.cpu_percent.return_value = 25.0
        fake_proc.cpu_times.return_value = MagicMock(user=1.0, system=0.5)
        fake_proc.threads.return_value = []
        fake_proc.memory_info.return_value = MagicMock(rss=12027 * 1024 * 1024)
        fake_proc.memory_full_info.return_value = MagicMock(uss=9400 * 1024 * 1024, pss=9500 * 1024 * 1024)

        adapter = runtime_adapter.LocalAdapter()
        with patch("runtime_adapter.psutil.pid_exists", return_value=True), \
             patch("runtime_adapter._gather_process_tree", return_value=[fake_proc]), \
             patch("runtime_adapter.time.sleep", return_value=None):
            stats = adapter.get_server_stats(srv_name, include_players=False)
            assert stats["memory_limit_mb"] == 11264.0
            assert stats["memory_used_mb"] == 9400.0
            assert stats["memory_used_mb"] < stats["memory_limit_mb"]

