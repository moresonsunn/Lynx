"""Regression tests: deleting a server must remove its folder on disk.

Previously runtime_adapter.delete_server() called local.stop_server() for
local-runtime servers — the process died (so the website dropped it) but
/data/servers/<name> stayed behind with the jar, world, everything.
"""
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production-0123456789")

import local_runtime  # noqa: E402


def _make_server(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "server.properties").write_text("motd=test\n", encoding="utf-8")
    (d / "server_meta.json").write_text(
        json.dumps({"name": name, "host_port": 59999}), encoding="utf-8"
    )
    return d


def test_delete_server_removes_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", tmp_path)
    d = _make_server(tmp_path, "FakeSrv")
    mgr = local_runtime.LocalRuntimeManager()
    result = mgr.delete_server("FakeSrv")
    assert result.get("deleted") is True, result
    assert result.get("dir_removed") is True, result
    assert not d.exists(), "server folder survived deletion"


def test_delete_server_missing_dir_reports_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", tmp_path)
    mgr = local_runtime.LocalRuntimeManager()
    result = mgr.delete_server("GhostSrv")
    assert result.get("deleted") is True, result
    assert result.get("dir_removed") is True, result


def test_delete_server_refuses_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", tmp_path)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    mgr = local_runtime.LocalRuntimeManager()
    result = mgr.delete_server("..")
    assert result.get("dir_removed") is False, result
    assert sentinel.exists(), "traversal deleted outside SERVERS_ROOT"


def test_delete_server_with_spaces_and_readonly_files(tmp_path, monkeypatch):
    import stat
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", tmp_path)
    d = _make_server(tmp_path, "COBBLEVERSE 1.8.0")
    mods_dir = d / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    ro_file = mods_dir / "locked-mod.jar"
    ro_file.write_bytes(b"PK\x03\x04dummy")
    os.chmod(ro_file, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    mgr = local_runtime.LocalRuntimeManager()
    result = mgr.delete_server("COBBLEVERSE 1.8.0")
    assert result.get("deleted") is True, result
    assert result.get("dir_removed") is True, result
    assert not d.exists(), "server folder with spaces & read-only files survived deletion"


def test_delete_server_kills_child_process_holding_directory(tmp_path, monkeypatch):
    import subprocess
    import time
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", tmp_path)
    d = _make_server(tmp_path, "HolderSrv")
    lock_file = d / "console.in"
    lock_file.write_text("", encoding="utf-8")

    # Spawn a subprocess whose cwd is inside the server directory holding console.in open
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; f = open('console.in', 'r'); time.sleep(30)"],
        cwd=str(d),
    )
    try:
        (d / ".server.pid").write_text(str(proc.pid), encoding="utf-8")
        time.sleep(0.25)

        mgr = local_runtime.LocalRuntimeManager()
        result = mgr.delete_server("HolderSrv")
        assert result.get("deleted") is True, result
        assert result.get("dir_removed") is True, result
        assert not d.exists(), "server directory with active process survived deletion"
        assert proc.poll() is not None, "child process holding directory was not terminated"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_local_adapter_and_api_delete_server_with_spaces(tmp_path, monkeypatch):
    """End-to-end check: DELETE /api/servers/{container_id} deletes server folder on disk
    including spaces in name and removes it from subsequent server listings."""
    import runtime_adapter
    import config
    import app as app_module
    from auth import require_auth
    from database import get_db
    from models import User
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base

    monkeypatch.setattr(config, "SERVERS_ROOT", tmp_path)
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", tmp_path)
    monkeypatch.setattr(runtime_adapter, "SERVERS_ROOT", tmp_path)
    monkeypatch.setattr(app_module, "SERVERS_ROOT", tmp_path)

    srv_dir = _make_server(tmp_path, "COBBLEVERSE 1.8.0")
    (srv_dir / "mods").mkdir(parents=True, exist_ok=True)
    (srv_dir / "mods" / "sample.jar").write_bytes(b"jar-bytes")

    adapter = runtime_adapter.LocalAdapter()
    monkeypatch.setattr(app_module, "get_docker_manager", lambda: adapter)

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    SessionLocalTest = sessionmaker(bind=eng, autoflush=False)
    db_sess = SessionLocalTest()

    owner = User(id=1, username="admin", email="admin@localhost", hashed_password="x", role="owner", is_active=True)

    def _override_db():
        yield db_sess

    app_module.app.dependency_overrides[get_db] = _override_db
    app_module.app.dependency_overrides[require_auth] = lambda: owner
    try:
        with TestClient(app_module.app) as client:
            listed_before = client.get("/api/servers")
            assert listed_before.status_code == 200
            names_before = [s["name"] for s in listed_before.json()]
            assert "COBBLEVERSE 1.8.0" in names_before

            res = client.delete("/api/servers/COBBLEVERSE%201.8.0")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["deleted"] is True
            assert body["dir_removed"] is True
            assert not srv_dir.exists(), "server folder survived DELETE /api/servers/{id}"

            listed_after = client.get("/api/servers")
            assert listed_after.status_code == 200
            names_after = [s["name"] for s in listed_after.json()]
            assert "COBBLEVERSE 1.8.0" not in names_after
    finally:
        app_module.app.dependency_overrides.pop(get_db, None)
        app_module.app.dependency_overrides.pop(require_auth, None)
        db_sess.close()
