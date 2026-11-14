"""Integration tests for Milestone 2: Controller & Runtime Integration.

Covers:
1. Pydantic models & schema validation with multicore fields.
2. Cross-platform process-tree CPU affinity using psutil.
3. Server creation & import with multicore env & user_jvm_args.txt generation.
4. GET and POST /api/servers/{id}/multicore FastAPI endpoints.
5. 6-stage non-destructive graceful shutdown sequence with chunk flush.
"""

import errno
import json
import os
import stat
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Isolate environment for testing
os.environ.setdefault("SECRET_KEY", "test-secret-key-multicore-integration-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models import (
    Permission,
    Role,
    ServerCreateRequest,
    ServerImportRequest,
    ServerMulticoreStatusResponse,
    ServerMulticoreUpdateRequest,
    User,
)
from local_runtime import (
    LocalRuntimeManager,
    _apply_cpu_affinity,
    _infer_java_version,
    apply_process_tree_affinity,
)


# ---------------------------------------------------------------------------
# Test Fixtures: In-Memory DB & FastAPI Client
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db_session(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False)
    session = TestingSession()

    from user_service import DEFAULT_PERMISSIONS, DEFAULT_ROLES

    for perm_name, perm_data in DEFAULT_PERMISSIONS.items():
        if not session.query(Permission).filter(Permission.name == perm_name).first():
            session.add(
                Permission(
                    name=perm_name,
                    description=perm_data["description"],
                    category=perm_data["category"],
                )
            )

    for role_name, role_data in DEFAULT_ROLES.items():
        existing = session.query(Role).filter(Role.name == role_name).first()
        if not existing:
            session.add(
                Role(
                    name=role_name,
                    description=role_data["description"],
                    permissions=list(role_data["permissions"]),
                    is_system=True,
                )
            )

    if not session.query(User).filter(User.username == "admin").first():
        from auth import get_password_hash

        session.add(
            User(
                username="admin",
                email="admin@localhost",
                hashed_password=get_password_hash("AdminPass123!"),
                role="owner",
                is_active=True,
            )
        )
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db_session, monkeypatch, tmp_path):
    """TestClient wired to isolated DB and temporary SERVERS_ROOT."""
    import app as app_module
    import config

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "SERVERS_ROOT", servers_dir)
    monkeypatch.setattr(app_module, "SERVERS_ROOT", servers_dir)

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app_module.app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app_module.app, raise_server_exceptions=False) as c:
        yield c
    app_module.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def auth_headers(client):
    r = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "AdminPass123!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test Class 1: Server Models and Schemas
# ---------------------------------------------------------------------------
class TestServerModelsAndSchemas:
    def test_server_create_request_multicore_defaults(self):
        req = ServerCreateRequest(name="mc-test", type="vanilla", version="1.21.1")
        assert req.name == "mc-test"
        assert req.multicore_enabled is True
        assert req.multicore_mode == "auto"
        assert req.worker_threads is None

    def test_server_create_request_custom_values(self):
        req = ServerCreateRequest(
            name="forge-perf",
            type="forge",
            version="1.20.1",
            multicore_enabled=False,
            multicore_mode="parallel_entities",
            worker_threads=8,
            cpu_cores=4,
        )
        assert req.multicore_enabled is False
        assert req.multicore_mode == "parallel_entities"
        assert req.worker_threads == 8
        assert req.cpu_cores == 4

    def test_server_import_request_multicore_fields(self):
        req = ServerImportRequest(
            name="existing-srv",
            multicore_enabled=True,
            multicore_mode="high_throughput",
            worker_threads=6,
        )
        assert req.name == "existing-srv"
        assert req.multicore_enabled is True
        assert req.multicore_mode == "high_throughput"
        assert req.worker_threads == 6

    def test_multicore_update_request_validation(self):
        req = ServerMulticoreUpdateRequest(
            enabled=True,
            mode="parallel_dimensions",
            worker_threads=4,
            cpu_cores=4,
        )
        assert req.enabled is True
        assert req.mode == "parallel_dimensions"
        assert req.worker_threads == 4
        assert req.cpu_cores == 4

    def test_multicore_status_response_schema(self):
        resp = ServerMulticoreStatusResponse(
            enabled=True,
            mode="auto",
            allocated_cores=4,
            worker_threads=4,
            jvm_flags=["-Dmulticore.enabled=true"],
            active=True,
            live_applied=True,
        )
        assert resp.enabled is True
        assert resp.allocated_cores == 4
        assert resp.active is True
        assert resp.live_applied is True


# ---------------------------------------------------------------------------
# Test Class 2: Process Tree CPU Affinity
# ---------------------------------------------------------------------------
class TestProcessTreeAffinity:
    def test_apply_process_tree_affinity_recursive(self, monkeypatch):
        mock_leader = MagicMock()
        mock_child1 = MagicMock()
        mock_child2 = MagicMock()

        mock_leader.children.return_value = [mock_child1, mock_child2]
        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 8)

        ok = _apply_cpu_affinity(1234, cores=4)
        assert ok is True

        expected_mask = [0, 1, 2, 3]
        mock_leader.cpu_affinity.assert_called_once_with(expected_mask)
        mock_child1.cpu_affinity.assert_called_once_with(expected_mask)
        mock_child2.cpu_affinity.assert_called_once_with(expected_mask)

    def test_apply_process_tree_affinity_alias(self):
        assert apply_process_tree_affinity is _apply_cpu_affinity

    def test_apply_process_tree_affinity_child_exit_resilience(self, monkeypatch):
        mock_leader = MagicMock()
        mock_child_exited = MagicMock()
        mock_child_survived = MagicMock()

        mock_child_exited.cpu_affinity.side_effect = psutil.NoSuchProcess(pid=9999)
        mock_leader.children.return_value = [mock_child_exited, mock_child_survived]

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 8)

        ok = _apply_cpu_affinity(1234, cores=2)
        assert ok is True
        mock_leader.cpu_affinity.assert_called_once_with([0, 1])
        mock_child_survived.cpu_affinity.assert_called_once_with([0, 1])

    def test_apply_process_tree_affinity_unsupported_platform(self, monkeypatch):
        mock_leader = MagicMock()
        mock_leader.children.return_value = []
        mock_leader.cpu_affinity.side_effect = AttributeError("cpu_affinity not supported on Darwin")

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

        ok = _apply_cpu_affinity(1234, cores=2)
        assert ok is False

    def test_apply_process_tree_affinity_none_cores_restores_all(self, monkeypatch):
        mock_leader = MagicMock()
        mock_leader.children.return_value = []

        monkeypatch.setattr(psutil, "Process", lambda pid: mock_leader)
        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 6)

        ok = _apply_cpu_affinity(1234, cores=None)
        assert ok is True
        mock_leader.cpu_affinity.assert_called_once_with([0, 1, 2, 3, 4, 5])

    def test_apply_process_tree_affinity_invalid_cores(self):
        assert _apply_cpu_affinity(1234, cores=0) is False
        assert _apply_cpu_affinity(1234, cores=-3) is False

    def test_apply_process_tree_affinity_nonexistent_pid(self, monkeypatch):
        def _mock_proc(pid):
            raise psutil.NoSuchProcess(pid=pid)

        monkeypatch.setattr(psutil, "Process", _mock_proc)
        assert _apply_cpu_affinity(999999, cores=2) is False


# ---------------------------------------------------------------------------
# Test Class 3: Server Creation Multicore Integration
# ---------------------------------------------------------------------------
class TestServerCreationMulticoreIntegration:
    def test_infer_java_version(self, tmp_path):
        srv_dir = tmp_path / "test_srv"
        srv_dir.mkdir(parents=True)

        # Vanilla legacy
        assert _infer_java_version(srv_dir, "vanilla", "1.12.2") == 8
        assert _infer_java_version(srv_dir, "vanilla", "1.16.5") == 8

        # Vanilla modern
        assert _infer_java_version(srv_dir, "vanilla", "1.20.4") == 21
        assert _infer_java_version(srv_dir, "paper", "1.21.1") == 21

        # Forge legacy & modern
        assert _infer_java_version(srv_dir, "forge", "1.12.2") == 8
        assert _infer_java_version(srv_dir, "forge", "1.20.1") == 17
        assert _infer_java_version(srv_dir, "neoforge", "1.20.6") == 21

        # Explicit overrides
        assert _infer_java_version(srv_dir, "vanilla", "1.21", explicit_jvm="17") == 17

    def test_create_server_vanilla_multicore_env(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: tmp_path / name)
        monkeypatch.setattr(mgr, "_spawn", lambda name, env: {"id": name, "status": "running", "env": env})

        result = mgr.create_server(
            name="vanilla-m2",
            server_type="vanilla",
            version="1.21.1",
            host_port=25565,
            cpu_cores=4,
            multicore_enabled=True,
            multicore_mode="auto",
        )

        assert result["status"] == "running"
        env = result["env"]
        assert env["MULTICORE_ENABLED"] == "1"
        assert env["MULTICORE_THREADS"] == "4"
        assert "ALL_JAVA_ARGS" in env
        assert "-Dmulticore.enabled=true" in env["ALL_JAVA_ARGS"]

        # Verify server_meta.json
        meta_file = tmp_path / "vanilla-m2" / "server_meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["multicore_enabled"] is True
        assert meta["multicore_mode"] == "auto"
        assert meta["allocated_cores"] == 4
        assert meta["multicore_threads"] == 4

        # Verify agent jar is deployed
        agent_jar = tmp_path / "vanilla-m2" / "mc-multicore-agent.jar"
        assert agent_jar.exists()
        assert agent_jar.stat().st_size > 0

    def test_create_server_forge_writes_user_jvm_args(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        monkeypatch.setattr(mgr, "_server_dir", lambda name: tmp_path / name)
        monkeypatch.setattr(mgr, "_spawn", lambda name, env: {"id": name, "status": "running", "env": env})

        result = mgr.create_server(
            name="forge-m2",
            server_type="forge",
            version="1.20.1",
            host_port=25566,
            cpu_cores=6,
            multicore_enabled=True,
            multicore_mode="high_throughput",
        )

        assert result["status"] == "running"
        # In high_throughput mode: worker_threads = effective_cores + 2 = 6 + 2 = 8
        env = result["env"]
        assert env["MULTICORE_THREADS"] == "8"

        # Verify user_jvm_args.txt was created with LMCE flags
        user_jvm_args = tmp_path / "forge-m2" / "user_jvm_args.txt"
        assert user_jvm_args.exists()
        content = user_jvm_args.read_text(encoding="utf-8")
        assert "Lynx Multi-Core Engine" in content
        assert "-Dmulticore.threads=8" in content
        assert "-javaagent:" in content

    def test_create_server_from_existing_refreshes_multicore(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "existing-m2"
        srv_dir.mkdir(parents=True)
        meta_file = srv_dir / "server_meta.json"
        meta_file.write_text(
            json.dumps({"name": "existing-m2", "type": "vanilla", "version": "1.21.1", "host_port": 25567}),
            encoding="utf-8",
        )

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(mgr, "_spawn", lambda name, env: {"id": name, "status": "running", "env": env})

        result = mgr.create_server_from_existing(
            name="existing-m2",
            cpu_cores=4,
            multicore_enabled=True,
            multicore_mode="parallel_dimensions",
            worker_threads=5,
        )

        assert result["status"] == "running"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["multicore_enabled"] is True
        assert meta["multicore_mode"] == "parallel_dimensions"
        assert meta["worker_threads"] == 5
        assert meta["multicore_threads"] == 5

    def test_start_server_method(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "test-start"
        srv_dir.mkdir(parents=True)
        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        # 1. When already running
        pid_file = srv_dir / ".server.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr(mgr, "_is_running", lambda pid: True)

        res = mgr.start_server("test-start")
        assert res["status"] == "running"
        assert res["pid"] == 12345

        # 2. When stopped, calls create_server_from_existing
        monkeypatch.setattr(mgr, "_is_running", lambda pid: False)
        called = False

        def _mock_create_from_existing(name, **kwargs):
            nonlocal called
            called = True
            return {"id": name, "status": "spawned"}

        monkeypatch.setattr(mgr, "create_server_from_existing", _mock_create_from_existing)
        res2 = mgr.start_server("test-start")
        assert called is True
        assert res2["status"] == "spawned"


# ---------------------------------------------------------------------------
# Test Class 4: Multicore API Endpoints
# ---------------------------------------------------------------------------
class TestMulticoreApiEndpoints:
    def test_get_multicore_endpoint_existing_stopped(self, client, auth_headers, tmp_path, monkeypatch):
        import config

        srv_dir = config.SERVERS_ROOT / "stopped-server"
        srv_dir.mkdir(parents=True)
        meta_file = srv_dir / "server_meta.json"
        meta_file.write_text(
            json.dumps(
                {
                    "name": "stopped-server",
                    "type": "vanilla",
                    "version": "1.21.1",
                    "multicore_enabled": True,
                    "multicore_mode": "auto",
                    "allocated_cores": 4,
                    "worker_threads": 4,
                    "jvm_flags": ["-Dmulticore.enabled=true", "-XX:+UseG1GC"],
                }
            ),
            encoding="utf-8",
        )

        resp = client.get("/api/servers/stopped-server/multicore", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["enabled"] is True
        assert data["mode"] == "auto"
        assert data["allocated_cores"] == 4
        assert data["worker_threads"] == 4
        assert data["active"] is False
        assert len(data["jvm_flags"]) > 0

    def test_get_multicore_endpoint_existing_running(self, client, auth_headers, monkeypatch):
        import config

        srv_dir = config.SERVERS_ROOT / "running-server"
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(
            json.dumps(
                {
                    "name": "running-server",
                    "type": "vanilla",
                    "version": "1.21.1",
                    "multicore_enabled": True,
                    "multicore_mode": "auto",
                    "allocated_cores": 4,
                    "worker_threads": 4,
                    "jvm_flags": ["-Dmulticore.enabled=true"],
                }
            ),
            encoding="utf-8",
        )
        (srv_dir / ".server.pid").write_text(str(os.getpid()), encoding="utf-8")

        resp = client.get("/api/servers/running-server/multicore", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["active"] is True

    def test_get_multicore_endpoint_not_found(self, client, auth_headers):
        resp = client.get("/api/servers/nonexistent-srv/multicore", headers=auth_headers)
        assert resp.status_code == 404

    def test_post_multicore_endpoint_valid_update(self, client, auth_headers):
        import config

        srv_dir = config.SERVERS_ROOT / "update-srv"
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(
            json.dumps(
                {
                    "name": "update-srv",
                    "type": "vanilla",
                    "version": "1.21.1",
                    "multicore_enabled": True,
                    "multicore_mode": "auto",
                    "allocated_cores": 2,
                    "worker_threads": 2,
                }
            ),
            encoding="utf-8",
        )

        resp = client.post(
            "/api/servers/update-srv/multicore",
            json={
                "enabled": True,
                "mode": "parallel_dimensions",
                "worker_threads": 6,
                "cpu_cores": 6,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["enabled"] is True
        assert data["mode"] == "parallel_dimensions"
        assert data["worker_threads"] == 6
        assert data["allocated_cores"] == 6

        # Check updated server_meta.json
        meta = json.loads((srv_dir / "server_meta.json").read_text(encoding="utf-8"))
        assert meta["multicore_mode"] == "parallel_dimensions"
        assert meta["worker_threads"] == 6

    def test_post_multicore_endpoint_invalid_mode(self, client, auth_headers):
        import config

        srv_dir = config.SERVERS_ROOT / "invalid-mode-srv"
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text("{}", encoding="utf-8")

        resp = client.post(
            "/api/servers/invalid-mode-srv/multicore",
            json={"mode": "turbo_hyper_unsupported"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "Invalid multicore mode" in resp.json()["detail"]

    def test_post_multicore_endpoint_invalid_threads(self, client, auth_headers):
        import config

        srv_dir = config.SERVERS_ROOT / "invalid-threads-srv"
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text("{}", encoding="utf-8")

        resp = client.post(
            "/api/servers/invalid-threads-srv/multicore",
            json={"worker_threads": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "worker_threads must be >= 1" in resp.json()["detail"]

    def test_post_multicore_endpoint_live_affinity_applied(self, client, auth_headers, monkeypatch):
        import config

        srv_dir = config.SERVERS_ROOT / "live-srv"
        srv_dir.mkdir(parents=True)
        (srv_dir / "server_meta.json").write_text(
            json.dumps({"name": "live-srv", "type": "vanilla", "version": "1.21.1"}),
            encoding="utf-8",
        )
        (srv_dir / ".server.pid").write_text(str(os.getpid()), encoding="utf-8")

        # Mock affinity success
        import local_runtime

        monkeypatch.setattr(local_runtime, "_apply_cpu_affinity", lambda pid, cores: True)

        resp = client.post(
            "/api/servers/live-srv/multicore",
            json={"enabled": True, "mode": "high_throughput", "cpu_cores": 4},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["active"] is True
        assert data["live_applied"] is True


# ---------------------------------------------------------------------------
# Test Class 5: Graceful Stop & Chunk Flush Guard
# ---------------------------------------------------------------------------
class TestGracefulStopChunkFlush:
    def test_send_command_console_fifo(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "fifo-srv"
        srv_dir.mkdir(parents=True)
        fifo_file = srv_dir / "console.in"
        fifo_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        res = mgr.send_command("fifo-srv", "say Hello World")
        assert res["ok"] is True
        content = fifo_file.read_text(encoding="utf-8")
        assert "say Hello World" in content

    def test_send_command_regular_file_append_sequential(self, tmp_path, monkeypatch):
        """Verifies that sequential commands append cleanly to console.in regular files
        without overwriting offset 0 (preventing 'stop\\nll flush\\n' corruption)."""
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "append-srv"
        srv_dir.mkdir(parents=True)
        console_in = srv_dir / "console.in"
        console_in.write_text("", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        res1 = mgr.send_command("append-srv", "save-all flush")
        assert res1["ok"] is True
        assert res1["method"] == "console_file"

        res2 = mgr.send_command("append-srv", "stop")
        assert res2["ok"] is True
        assert res2["method"] == "console_file"

        content = console_in.read_text(encoding="utf-8")
        assert content == "save-all flush\nstop\n"
        assert "stop\nll flush\n" not in content
        raw_bytes = console_in.read_bytes()
        assert raw_bytes == b"save-all flush\nstop\n"
        assert b"\r" not in raw_bytes

    def test_send_command_regular_file_exact_lf_bytes_no_crlf(self, tmp_path, monkeypatch):
        """Verifies that send_command on regular console.in writes exact byte content
        b"cmd\n" without Windows CRLF (\\r\\n) line-ending expansion."""
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "lf-srv"
        srv_dir.mkdir(parents=True)
        console_in = srv_dir / "console.in"
        console_in.write_text("", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        res = mgr.send_command("lf-srv", "say hello")
        assert res["ok"] is True
        assert res["method"] == "console_file"

        raw_bytes = console_in.read_bytes()
        assert raw_bytes == b"say hello\n"
        assert b"\r" not in raw_bytes

    def test_send_command_fifo_missing_reader_no_hang(self, tmp_path, monkeypatch):
        """Verifies that when console.in is a FIFO and no reader is open (raising ENXIO),
        send_command fails immediately with a descriptive error without falling back
        to blocking open('...','a') which would deadlock."""
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "fifo-srv"
        srv_dir.mkdir(parents=True)
        fifo_path = srv_dir / "console.in"
        fifo_path.write_text("", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        # Force stat.S_ISFIFO to report True for this path
        monkeypatch.setattr(stat, "S_ISFIFO", lambda mode: True)

        # Mock os.open to raise ENXIO (as POSIX does on FIFO with no reader under O_NONBLOCK)
        def _mock_os_open(path, flags, *args, **kwargs):
            raise OSError(errno.ENXIO, "No such device or address")

        monkeypatch.setattr(os, "open", _mock_os_open)

        # Verify open() builtin is never called in append mode
        real_open = open
        open_calls = []

        def _guarded_open(*args, **kwargs):
            open_calls.append((args, kwargs))
            return real_open(*args, **kwargs)

        monkeypatch.setattr("builtins.open", _guarded_open)

        res = mgr.send_command("fifo-srv", "save-all flush")

        assert res["ok"] is False
        assert res["method"] == "console_fifo"
        assert "No reader connected to console FIFO" in res["error"]
        # Ensure open() was NOT called in append mode to avoid POSIX blocking hang
        assert not any("a" in str(call[0]) or call[1].get("mode") == "a" for call in open_calls)

    def test_send_command_fifo_success(self, tmp_path, monkeypatch):
        """Verifies successful write to a FIFO with reader connected."""
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "fifo-ok-srv"
        srv_dir.mkdir(parents=True)
        fifo_path = srv_dir / "console.in"
        fifo_path.write_text("", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(stat, "S_ISFIFO", lambda mode: True)

        written_data = []
        mock_fd = 9999
        monkeypatch.setattr(os, "open", lambda path, flags, *args, **kwargs: mock_fd)

        class MockFdFile:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                written_data.append(data)

        monkeypatch.setattr(os, "fdopen", lambda fd, mode, *args, **kwargs: MockFdFile())

        res = mgr.send_command("fifo-ok-srv", "list")
        assert res["ok"] is True
        assert res["method"] == "console_fifo"
        assert written_data == ["list\n"]

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
    def test_send_command_real_posix_fifo_missing_reader(self, tmp_path, monkeypatch):
        """Verifies genuine POSIX FIFO non-blocking failure when no reader is attached."""
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "posix-fifo-srv"
        srv_dir.mkdir(parents=True)
        fifo_path = srv_dir / "console.in"
        os.mkfifo(str(fifo_path))

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        start_t = time.time()
        res = mgr.send_command("posix-fifo-srv", "stop")
        elapsed = time.time() - start_t

        assert elapsed < 1.0  # Must not block!
        assert res["ok"] is False
        assert res["method"] == "console_fifo"
        assert "No reader connected to console FIFO" in res["error"]

    def test_stop_server_regular_file_console_in_no_corruption(self, tmp_path, monkeypatch):
        """Verifies stop_server against a regular console.in file appends save-all flush
        and stop in sequence without offset 0 overwrite."""
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "full-stop-srv"
        srv_dir.mkdir(parents=True)
        pid_file = srv_dir / ".server.pid"
        pid_file.write_text("12345", encoding="utf-8")
        console_in = srv_dir / "console.in"
        console_in.write_text("", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        call_count = 0

        def _mock_is_running(pid):
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        monkeypatch.setattr(mgr, "_is_running", _mock_is_running)
        monkeypatch.setattr(mgr, "_wait_for_port_release", lambda port, timeout=15, interval=0.5: True)

        res = mgr.stop_server("full-stop-srv", timeout=5)

        assert res["status"] == "stopped"
        assert res["method"] == "graceful_flush"
        content = console_in.read_text(encoding="utf-8")
        assert content == "save-all flush\nstop\n"
        assert "stop\nll flush\n" not in content

    def test_send_command_rcon(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "rcon-srv"
        srv_dir.mkdir(parents=True)
        props = srv_dir / "server.properties"
        props.write_text("enable-rcon=true\nrcon.password=secret123\nrcon.port=25575\n", encoding="utf-8")

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)

        mock_mcr = MagicMock()
        mock_mcr.command.return_value = "Command executed via RCON"

        mock_mcrcon_cls = MagicMock()
        mock_mcrcon_cls.return_value.__enter__.return_value = mock_mcr

        with patch.dict("sys.modules", {"mcrcon": MagicMock(MCRcon=mock_mcrcon_cls)}):
            res = mgr.send_command("rcon-srv", "list")
            assert res["ok"] is True
            assert res["method"] == "rcon"
            assert res["output"] == "Command executed via RCON"

    def test_graceful_stop_executes_save_all_flush_sequence(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "flush-srv"
        srv_dir.mkdir(parents=True)
        pid_file = srv_dir / ".server.pid"
        pid_file.write_text("55555", encoding="utf-8")

        commands_sent = []

        def _mock_send_command(name, cmd):
            commands_sent.append(cmd)
            return {"id": name, "ok": True}

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(mgr, "send_command", _mock_send_command)
        # Server is running during check, but exits on stop
        call_count = 0

        def _mock_is_running(pid):
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        monkeypatch.setattr(mgr, "_is_running", _mock_is_running)
        monkeypatch.setattr(mgr, "_wait_for_port_release", lambda port, timeout=15, interval=0.5: True)

        res = mgr.stop_server("flush-srv", timeout=5)

        assert res["status"] == "stopped"
        assert res["method"] == "graceful_flush"
        assert commands_sent == ["save-all flush", "stop"]
        assert not pid_file.exists()

    def test_graceful_stop_fallback_to_save_all(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "legacy-flush-srv"
        srv_dir.mkdir(parents=True)
        pid_file = srv_dir / ".server.pid"
        pid_file.write_text("66666", encoding="utf-8")

        commands_sent = []

        def _mock_send_command(name, cmd):
            commands_sent.append(cmd)
            if cmd == "save-all flush":
                return {"id": name, "ok": False, "error": "Unknown command"}
            return {"id": name, "ok": True}

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(mgr, "send_command", _mock_send_command)

        call_count = 0

        def _mock_is_running(pid):
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        monkeypatch.setattr(mgr, "_is_running", _mock_is_running)
        monkeypatch.setattr(mgr, "_wait_for_port_release", lambda port, timeout=15, interval=0.5: True)

        res = mgr.stop_server("legacy-flush-srv", timeout=5)

        assert res["status"] == "stopped"
        assert commands_sent == ["save-all flush", "save-all", "stop"]

    def test_graceful_stop_escalates_on_hang(self, tmp_path, monkeypatch):
        mgr = LocalRuntimeManager()
        srv_dir = tmp_path / "hung-srv"
        srv_dir.mkdir(parents=True)
        pid_file = srv_dir / ".server.pid"
        pid_file.write_text("77777", encoding="utf-8")

        killed_pid = None

        def _mock_kill_tree(pid, timeout=10):
            nonlocal killed_pid
            killed_pid = pid

        monkeypatch.setattr(mgr, "_server_dir", lambda name: srv_dir)
        monkeypatch.setattr(mgr, "send_command", lambda name, cmd: {"id": name, "ok": True})
        # Server remains stubbornly running
        monkeypatch.setattr(mgr, "_is_running", lambda pid: True)
        monkeypatch.setattr(mgr, "_kill_process_tree", _mock_kill_tree)
        monkeypatch.setattr(mgr, "_wait_for_port_release", lambda port, timeout=15, interval=0.5: True)

        res = mgr.stop_server("hung-srv", timeout=1)

        assert res["status"] == "stopped"
        assert res["method"] == "process_tree"
        assert killed_pid == 77777
        assert not pid_file.exists()
