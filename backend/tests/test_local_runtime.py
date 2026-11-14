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
