import errno
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-multicore-integration-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")

from local_runtime import LocalRuntimeManager


class TestEmpiricalChallengerM2:
    """Empirical challenge suite for Milestone 2: Controller & Runtime Integration."""

    def test_defect1_regular_file_append_exact_bytes(self, tmp_path, monkeypatch):
        """Empirically test Defect 1:
        When console.in is a regular file, sequential commands ('save-all flush\\n'
        followed by 'stop\\n') must append cleanly without overwriting offset 0.
        Exact byte contents and byte positions must be verified.
        """
        srv_dir = tmp_path / "defect1-srv"
        srv_dir.mkdir(parents=True)
        console_in = srv_dir / "console.in"
        console_in.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        # 1. Send first command: 'save-all flush'
        r1 = mgr.send_command("defect1-srv", "save-all flush")
        assert r1["ok"] is True
        assert r1["method"] == "console_file"

        # Check file after command 1
        b1 = console_in.read_bytes()
        assert b1 == b"save-all flush\n"
        assert len(b1) == 15
        assert b"\r" not in b1

        # 2. Send second command: 'stop'
        r2 = mgr.send_command("defect1-srv", "stop")
        assert r2["ok"] is True
        assert r2["method"] == "console_file"

        # Check file after command 2
        b2 = console_in.read_bytes()
        expected = b"save-all flush\nstop\n"
        assert b2 == expected
        assert b"\r" not in b2

        # Check that Defect 1 corrupted string 'stop\nll flush\n' or 'stop\r\nll flush\r\n' is NOT present
        assert b"stop\nll flush" not in b2
        assert b"stop\r\nll flush" not in b2
        assert b2.startswith(b"save-all flush\n")
        assert b2.endswith(b"stop\n")

        # Check decoded text
        text = console_in.read_text(encoding="utf-8")
        assert text == "save-all flush\nstop\n"

    def test_defect1_burst_sequential_commands(self, tmp_path, monkeypatch):
        """Stress test: burst of 100 sequential commands of varying lengths to regular console.in."""
        srv_dir = tmp_path / "burst-srv"
        srv_dir.mkdir(parents=True)
        console_in = srv_dir / "console.in"
        console_in.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        commands = [f"tellraw @a {{\"text\":\"msg_{i}_{'x'* (i % 20)}\"}}" for i in range(100)]
        for cmd in commands:
            res = mgr.send_command("burst-srv", cmd)
            assert res["ok"] is True
            assert res["method"] == "console_file"

        read_lines = console_in.read_text(encoding="utf-8").splitlines()
        assert len(read_lines) == 100
        assert read_lines == commands

    def test_defect2_fifo_missing_reader_no_hang(self, tmp_path, monkeypatch):
        """Empirically test Defect 2:
        When console.in is a FIFO and no reader is connected, send_command must
        return immediately with ok=False, error indicating no reader, and must
        NOT attempt to call open(..., 'a') which causes permanent thread deadlock.
        """
        srv_dir = tmp_path / "defect2-srv"
        srv_dir.mkdir(parents=True)
        fifo_file = srv_dir / "console.in"
        fifo_file.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        # Force stat.S_ISFIFO to report True
        monkeypatch.setattr(stat, "S_ISFIFO", lambda mode: True)

        # Mock os.open to raise ENXIO (POSIX behavior when opening O_NONBLOCK FIFO with no reader)
        def _mock_os_open(path, flags, *args, **kwargs):
            raise OSError(errno.ENXIO, "No such device or address")

        monkeypatch.setattr(os, "open", _mock_os_open)

        # Guard builtins.open to verify append mode is NEVER called
        import builtins
        real_builtin_open = builtins.open
        append_calls = []

        def _guarded_open(*args, **kwargs):
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            if "a" in mode:
                append_calls.append((args, kwargs))
            return real_builtin_open(*args, **kwargs)

        monkeypatch.setattr(builtins, "open", _guarded_open)

        t0 = time.perf_counter()
        res = mgr.send_command("defect2-srv", "stop")
        elapsed_sec = time.perf_counter() - t0

        assert elapsed_sec < 0.2, f"Execution took {elapsed_sec}s, expected instantaneous non-blocking return"
        assert res["ok"] is False
        assert res["method"] == "console_fifo"
        assert "No reader connected to console FIFO" in res["error"]
        assert len(append_calls) == 0, f"open() in append mode was called on FIFO: {append_calls}"

    def test_defect2_fifo_broken_pipe_epipe(self, tmp_path, monkeypatch):
        """Empirically test FIFO write failure (EPIPE / broken pipe) when reader disconnects."""
        srv_dir = tmp_path / "fifo-epipe-srv"
        srv_dir.mkdir(parents=True)
        fifo_file = srv_dir / "console.in"
        fifo_file.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(stat, "S_ISFIFO", lambda mode: True)

        mock_fd = 9999
        monkeypatch.setattr(os, "open", lambda path, flags, *args, **kwargs: mock_fd)

        class BrokenPipeWriter:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                raise OSError(errno.EPIPE, "Broken pipe")

        monkeypatch.setattr(os, "fdopen", lambda fd, mode, *args, **kwargs: BrokenPipeWriter())

        t0 = time.perf_counter()
        res = mgr.send_command("fifo-epipe-srv", "stop")
        elapsed_sec = time.perf_counter() - t0

        assert elapsed_sec < 0.2
        assert res["ok"] is False
        assert res["method"] == "console_fifo"
        assert "No reader connected to console FIFO" in res["error"]

    def test_defect2_fifo_unexpected_exception_closes_fd(self, tmp_path, monkeypatch):
        """Empirically test that if an unexpected exception occurs during FIFO write,
        the open fd is closed and not leaked."""
        srv_dir = tmp_path / "fifo-leak-srv"
        srv_dir.mkdir(parents=True)
        fifo_file = srv_dir / "console.in"
        fifo_file.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(stat, "S_ISFIFO", lambda mode: True)

        mock_fd = 8888
        monkeypatch.setattr(os, "open", lambda path, flags, *args, **kwargs: mock_fd)

        closed_fds = []
        real_close = os.close
        monkeypatch.setattr(os, "close", lambda fd: closed_fds.append(fd))

        def _exploding_fdopen(fd, mode, *args, **kwargs):
            raise RuntimeError("Unexpected failure during stream initialization")

        monkeypatch.setattr(os, "fdopen", _exploding_fdopen)

        # LocalRuntimeManager.send_command catches general Exception at the outer level and logs
        res = mgr.send_command("fifo-leak-srv", "stop")
        assert res["ok"] is False
        assert mock_fd in closed_fds, f"FD {mock_fd} was not closed on exception! Closed: {closed_fds}"

    def test_missing_console_in_fails_cleanly(self, tmp_path, monkeypatch):
        """When console.in does not exist and RCON is disabled, returns ok=False cleanly."""
        srv_dir = tmp_path / "no-console-srv"
        srv_dir.mkdir(parents=True)

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        res = mgr.send_command("no-console-srv", "help")
        assert res["ok"] is False
        assert "No available command channel" in res["error"]

    def test_rcon_failure_falls_back_to_console_in_append(self, tmp_path, monkeypatch):
        """When RCON is enabled in server.properties but connection fails, falls back to console.in append."""
        srv_dir = tmp_path / "rcon-fallback-srv"
        srv_dir.mkdir(parents=True)
        props = srv_dir / "server.properties"
        props.write_text("enable-rcon=true\nrcon.password=secret\nrcon.port=25575\n", encoding="utf-8")
        console_in = srv_dir / "console.in"
        console_in.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        # Mock MCRcon to fail
        class FailingMCRcon:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                raise ConnectionRefusedError("RCON not listening")
            def __exit__(self, *args):
                pass

        monkeypatch.setattr("mcrcon.MCRcon", FailingMCRcon)

        res = mgr.send_command("rcon-fallback-srv", "save-all flush")
        assert res["ok"] is True
        assert res["method"] == "console_file"
        assert "save-all flush" in console_in.read_text(encoding="utf-8")

    def test_stop_server_with_unread_fifo_does_not_deadlock(self, tmp_path, monkeypatch):
        """Verify that stop_server does not deadlock even if console.in is a FIFO without a reader.
        It should attempt command delivery non-blockingly, fail gracefully, and escalate."""
        srv_dir = tmp_path / "stop-fifo-srv"
        srv_dir.mkdir(parents=True)
        pid_file = srv_dir / ".server.pid"
        pid_file.write_text("55555", encoding="utf-8")
        fifo_path = srv_dir / "console.in"
        fifo_path.write_text("", encoding="utf-8")

        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(stat, "S_ISFIFO", lambda mode: True)

        # Mock os.open to raise ENXIO (no reader)
        def _mock_os_open(path, flags, *args, **kwargs):
            raise OSError(errno.ENXIO, "No such device or address")
        monkeypatch.setattr(os, "open", _mock_os_open)

        # Server exits after 1 check
        checks = 0
        def _mock_is_running(pid):
            nonlocal checks
            checks += 1
            return checks < 2
        monkeypatch.setattr(mgr, "_is_running", _mock_is_running)

        start_t = time.perf_counter()
        result = mgr.stop_server("stop-fifo-srv", timeout=2)
        elapsed = time.perf_counter() - start_t

        assert elapsed < 3.0, f"stop_server hung for {elapsed}s on unread FIFO!"
        assert result["status"] == "stopped"
