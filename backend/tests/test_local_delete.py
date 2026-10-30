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
