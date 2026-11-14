"""Adversarial stress and verification test harness for Process Tree CPU Affinity.

Empirically challenges:
1. Real OS-level process tree affinity on Windows (Leader -> Child -> Grandchild).
2. Live affinity re-configuration (cores=2 -> cores=None [all cores] -> cores=1).
3. Concurrency & race conditions with rapidly dying/exiting child processes.
4. Transient processes (PID dying midway through discovery/affinity application).
5. Permission issues (AccessDenied at leader vs child level).
6. Non-supported OS / platforms (AttributeError / NotImplementedError).
7. Extreme core counts (cores > physical/logical cores, cores <= 0, None).
8. Parameter edge cases (string numbers, invalid types, negative PIDs).
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from local_runtime import _apply_cpu_affinity, _normalize_cpu_cores, apply_process_tree_affinity


class TestEmpiricalRealProcessTreeAffinity:
    """Stress tests using REAL operating system processes and REAL psutil affinity calls on Windows."""

    def test_real_process_tree_three_levels(self):
        """Spawn real Leader -> Child -> Grandchild process tree and verify OS affinity applies to all levels."""
        total_cores = psutil.cpu_count(logical=True) or 1
        if total_cores < 2:
            pytest.skip("Test requires at least 2 logical CPU cores")

        # Grandchild script: sleeps
        # Child script: spawns grandchild and sleeps
        # Leader script: spawns child and sleeps
        py_code = """
import sys, subprocess, time
if len(sys.argv) > 1 and sys.argv[1] == "child":
    gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    time.sleep(30)
"""
        # Start leader
        leader_code = """
import sys, subprocess, time
c = subprocess.Popen([sys.executable, "-c", '''
import sys, subprocess, time
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
time.sleep(30)
'''])
time.sleep(30)
"""
        leader = subprocess.Popen([sys.executable, "-c", leader_code])
        try:
            # Wait briefly for process tree to form
            time.sleep(1.0)
            leader_proc = psutil.Process(leader.pid)
            children = leader_proc.children(recursive=True)
            assert len(children) >= 1, "Child processes failed to spawn"

            target_cores = 2 if total_cores >= 2 else 1
            # Apply affinity to 2 cores
            ok = _apply_cpu_affinity(leader.pid, cores=target_cores)
            assert ok is True

            # Verify leader affinity in OS
            assert leader_proc.cpu_affinity() == list(range(target_cores))

            # Verify all children affinity in OS
            for ch in children:
                try:
                    if ch.is_running():
                        assert ch.cpu_affinity() == list(range(target_cores))
                except psutil.NoSuchProcess:
                    pass

            # Live switch to 1 core
            ok = _apply_cpu_affinity(leader.pid, cores=1)
            assert ok is True
            assert leader_proc.cpu_affinity() == [0]
            for ch in children:
                try:
                    if ch.is_running():
                        assert ch.cpu_affinity() == [0]
                except psutil.NoSuchProcess:
                    pass

            # Live switch to None (restore all cores)
            ok = _apply_cpu_affinity(leader.pid, cores=None)
            assert ok is True
            assert leader_proc.cpu_affinity() == list(range(total_cores))
            for ch in children:
                try:
                    if ch.is_running():
                        assert ch.cpu_affinity() == list(range(total_cores))
                except psutil.NoSuchProcess:
                    pass

        finally:
            # Clean up all spawned processes
            try:
                for c in psutil.Process(leader.pid).children(recursive=True):
                    try:
                        c.kill()
                    except psutil.NoSuchProcess:
                        pass
                leader.kill()
                leader.wait(timeout=3)
            except Exception:
                pass

    def test_rapidly_dying_children_race_condition(self):
        """Leader continuously spawns short-lived children while _apply_cpu_affinity is invoked repeatedly."""
        total_cores = psutil.cpu_count(logical=True) or 1
        target_cores = 1 if total_cores < 2 else 2

        # Leader script that spawns short-lived children in a loop
        leader_code = """
import sys, subprocess, time
for _ in range(50):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.05)"])
    time.sleep(0.02)
time.sleep(10)
"""
        leader = subprocess.Popen([sys.executable, "-c", leader_code])
        try:
            time.sleep(0.1)
            # Repeatedly apply affinity during rapid spawn/death churn
            for _ in range(15):
                ok = _apply_cpu_affinity(leader.pid, cores=target_cores)
                # It should succeed without any unhandled exception (NoSuchProcess from dead children caught)
                assert ok is True
                time.sleep(0.05)
        finally:
            try:
                for c in psutil.Process(leader.pid).children(recursive=True):
                    try:
                        c.kill()
                    except psutil.NoSuchProcess:
                        pass
                leader.kill()
                leader.wait(timeout=3)
            except Exception:
                pass


class TestProcessAffinityAdversarialEdgeCases:
    """Adversarial challenge tests covering edge cases, exceptions, and platform differences."""

    def test_nonexistent_pid(self):
        assert _apply_cpu_affinity(99999999, cores=2) is False

    def test_negative_or_zero_cores(self):
        assert _apply_cpu_affinity(os.getpid(), cores=0) is False
        assert _apply_cpu_affinity(os.getpid(), cores=-1) is False
        assert _apply_cpu_affinity(os.getpid(), cores=-999) is False

    def test_invalid_type_cores(self):
        assert _apply_cpu_affinity(os.getpid(), cores="not_a_number") is False
        assert _apply_cpu_affinity(os.getpid(), cores={}) is False
        assert _apply_cpu_affinity(os.getpid(), cores=[1, 2]) is False

    def test_oversized_cores_capped_at_system_max(self, monkeypatch):
        mock_proc = MagicMock()
        mock_proc.children.return_value = []
        monkeypatch.setattr(psutil, "Process", lambda pid: mock_proc)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        # Request 128 cores on a 4-core system -> should cap at 4 cores [0, 1, 2, 3]
        ok = _apply_cpu_affinity(1234, cores=128)
        assert ok is True
        mock_proc.cpu_affinity.assert_called_once_with([0, 1, 2, 3])

    def test_access_denied_on_leader(self, monkeypatch):
        def _mock_proc(pid):
            raise psutil.AccessDenied(pid=pid)

        monkeypatch.setattr(psutil, "Process", _mock_proc)
        assert _apply_cpu_affinity(1234, cores=2) is False

    def test_access_denied_on_child_survives(self, monkeypatch):
        mock_leader = MagicMock()
        mock_child1 = MagicMock()
        mock_child2 = MagicMock()

        mock_child1.cpu_affinity.side_effect = psutil.AccessDenied(pid=5555)
        mock_child2.cpu_affinity.return_value = None
        mock_leader.children.return_value = [mock_child1, mock_child2]

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        ok = _apply_cpu_affinity(1234, cores=2)
        assert ok is True
        mock_leader.cpu_affinity.assert_called_once_with([0, 1])
        mock_child2.cpu_affinity.assert_called_once_with([0, 1])

    def test_access_denied_on_all_targets(self, monkeypatch):
        mock_leader = MagicMock()
        mock_child = MagicMock()
        mock_leader.cpu_affinity.side_effect = psutil.AccessDenied(pid=1234)
        mock_child.cpu_affinity.side_effect = psutil.AccessDenied(pid=5555)
        mock_leader.children.return_value = [mock_child]

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        ok = _apply_cpu_affinity(1234, cores=2)
        # If all processes failed to set affinity, returns False
        assert ok is False

    def test_children_raises_nosuchprocess_falls_back_to_leader(self, monkeypatch):
        mock_leader = MagicMock()
        mock_leader.children.side_effect = psutil.NoSuchProcess(pid=1234)

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        ok = _apply_cpu_affinity(1234, cores=2)
        assert ok is True
        mock_leader.cpu_affinity.assert_called_once_with([0, 1])

    def test_children_raises_accessdenied_falls_back_to_leader(self, monkeypatch):
        mock_leader = MagicMock()
        mock_leader.children.side_effect = psutil.AccessDenied(pid=1234)

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        ok = _apply_cpu_affinity(1234, cores=2)
        assert ok is True
        mock_leader.cpu_affinity.assert_called_once_with([0, 1])

    def test_unsupported_platform_not_implemented_error(self, monkeypatch):
        mock_leader = MagicMock()
        mock_leader.children.return_value = []
        mock_leader.cpu_affinity.side_effect = NotImplementedError()

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        assert _apply_cpu_affinity(1234, cores=2) is False

    def test_normalize_cpu_cores_adversarial_inputs(self):
        assert _normalize_cpu_cores(None) is None
        assert _normalize_cpu_cores("") is None
        assert _normalize_cpu_cores("   ") is None
        assert _normalize_cpu_cores("unlimited") is None
        assert _normalize_cpu_cores("UNLIMITED") is None
        assert _normalize_cpu_cores("none") is None
        assert _normalize_cpu_cores("0") is None
        assert _normalize_cpu_cores(0) is None
        assert _normalize_cpu_cores(-5) is None
        assert _normalize_cpu_cores("-5") is None
        assert _normalize_cpu_cores("invalid") is None
        assert _normalize_cpu_cores(4) == 4
        assert _normalize_cpu_cores("4") == 4
        assert _normalize_cpu_cores(" 8 ") == 8
        assert _normalize_cpu_cores(3.9) == 3
        # Upper bound limit 1024
        assert _normalize_cpu_cores(9999) == 1024
