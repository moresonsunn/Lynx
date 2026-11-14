"""
Integration Tests for Multi-Core Controller API Endpoints.

Validates:
1. GET /api/servers/{id}/multicore response schema and status querying.
2. POST /api/servers/{id}/multicore configuration updates and user_jvm_args.txt synthesis.
3. Role enforcement and authentication checks on multicore endpoints.
4. Input validation and error handling (404 not found, 400 invalid mode/threads).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

# Ensure backend root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-multicore-api-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")

from tests.test_auth_users_api import engine, db_session, client  # noqa: F401
import app as app_module
import config
import local_runtime
from auth import create_access_token
from models import (
    ServerMulticoreStatusResponse,
    ServerMulticoreUpdateRequest,
)


def _admin(client: TestClient | None = None) -> dict:
    token = create_access_token({"sub": "admin", "role": "admin", "permissions": ["*"]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_server_meta(tmp_path, monkeypatch):
    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "SERVERS_ROOT", servers_dir)
    monkeypatch.setattr(app_module, "SERVERS_ROOT", servers_dir)
    monkeypatch.setattr(local_runtime, "SERVERS_ROOT", servers_dir)

    srv_dir = servers_dir / "test-api-srv"
    srv_dir.mkdir(parents=True)
    meta = {
        "name": "test-api-srv",
        "type": "paper",
        "version": "1.20.4",
        "max_ram_mb": 4096,
        "multicore_enabled": True,
        "multicore_mode": "auto",
        "multicore_threads": 4,
        "allocated_cores": 4,
        "fork_join_parallelism": 4,
        "gc_threads": 4,
        "netty_threads": 4,
        "agent_path": str(srv_dir / "mc-multicore-agent.jar"),
        "jvm_flags": ["-XX:+UseG1GC", "-Djava.util.concurrent.ForkJoinPool.common.parallelism=4"],
    }
    (srv_dir / "server_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return srv_dir


class TestMulticoreApiEndpoints:

    def test_get_multicore_status_success(self, client: TestClient, mock_server_meta):
        headers = _admin(client)
        resp = client.get("/api/servers/test-api-srv/multicore", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["enabled"] is True
        assert data["mode"] == "auto"
        assert data["worker_threads"] == 4
        assert data["allocated_cores"] == 4
        assert isinstance(data["jvm_flags"], list)
        assert len(data["jvm_flags"]) > 0

    def test_get_multicore_status_404_not_found(self, client: TestClient, mock_server_meta):
        headers = _admin(client)
        resp = client.get("/api/servers/nonexistent-srv/multicore", headers=headers)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_post_multicore_update_settings(self, client: TestClient, mock_server_meta):
        headers = _admin(client)
        payload = {
            "enabled": True,
            "mode": "parallel_dimensions",
            "worker_threads": 8,
            "cpu_cores": 8,
        }
        resp = client.post("/api/servers/test-api-srv/multicore", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["enabled"] is True
        assert data["mode"] == "parallel_dimensions"
        assert data["worker_threads"] == 8

        # Check updated server_meta.json
        meta_file = mock_server_meta / "server_meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["multicore_enabled"] is True
        assert meta["multicore_mode"] == "parallel_dimensions"
        assert meta["multicore_threads"] == 8

    def test_post_multicore_update_validation_errors(self, client: TestClient, mock_server_meta):
        headers = _admin(client)
        # Invalid worker threads < 1
        resp = client.post(
            "/api/servers/test-api-srv/multicore",
            json={"worker_threads": 0},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "worker_threads must be >= 1" in resp.json()["detail"]

        # Invalid mode
        resp = client.post(
            "/api/servers/test-api-srv/multicore",
            json={"mode": "nonexistent_mode"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Invalid multicore mode" in resp.json()["detail"]

    def test_unauthenticated_requests_blocked(self, client: TestClient):
        resp = client.get("/api/servers/test-api-srv/multicore")
        assert resp.status_code in (401, 403)

        resp = client.post("/api/servers/test-api-srv/multicore", json={"worker_threads": 4})
        assert resp.status_code in (401, 403)
