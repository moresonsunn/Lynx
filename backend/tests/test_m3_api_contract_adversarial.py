"""Empirical Adversarial Contract & Schema Testing Suite for Milestone 3.

Validates exact request/response schema alignment and adversarial error resilience between:
- Frontend components: ModpackUpdateModal.jsx, ClientModFilterPanel.jsx, ServerDetailsPage.jsx
- Backend routes: modpack_routes.py, client_mod_routes.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TMP_ROOT = Path(tempfile.gettempdir()) / "_tmp_m3_contract_stress"
os.environ["SECRET_KEY"] = "test-secret-key-m3-adversarial-123456789"
os.environ["RUNTIME_MODE"] = "local"
os.environ["SERVERS_CONTAINER_ROOT"] = str(TMP_ROOT / "servers")
os.environ["STATS_DB_PATH"] = str(TMP_ROOT / "stats.db")
os.environ["STATS_COLLECTOR_ENABLED"] = "0"

from tests.test_auth_users_api import engine, db_session, client, _login, _admin  # noqa: F401
import config
from client_mod_filter import add_to_allowlist, get_allowlist_entries
from modpack_routes import save_server_modpack_info, get_server_modpack_info


@pytest.fixture(autouse=True)
def setup_m3_workspace():
    """Ensure clean servers container root."""
    srv_root = Path(config.SERVERS_ROOT)
    if srv_root.exists():
        shutil.rmtree(srv_root, ignore_errors=True)
    srv_root.mkdir(parents=True, exist_ok=True)
    yield
    if srv_root.exists():
        shutil.rmtree(srv_root, ignore_errors=True)


def _auth_headers(client: TestClient) -> Dict[str, str]:
    return _admin(client)


class MockProviderSuccess:
    def __init__(self, pack_id: str = "test-pack"):
        self.pack_id = pack_id

    def get_versions(self, pack_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return [
            {
                "id": "v2.0",
                "name": "Version 2.0",
                "version_number": "2.0.0",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "date_published": "2026-11-05T12:00:00Z",
                "changelog": "# Version 2.0\n- Big performance improvements\n* Fixed crash",
                "files": [{"url": "http://example.com/pack2.mrpack", "primary": True}],
            },
            {
                "id": "v1.0",
                "name": "Version 1.0",
                "version_number": "1.0.0",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "date_published": "2026-11-01T12:00:00Z",
                "changelog": "Initial release",
                "files": [{"url": "http://example.com/pack1.mrpack", "primary": True}],
            },
        ]


class MockProviderAdversarial:
    def __init__(self):
        pass

    def get_versions(self, pack_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        # Adversarial payload: missing name, missing changelog, null game_versions, empty loaders
        return [
            {
                "id": "v_adv",
                "name": None,
                "version_number": None,
                "game_versions": None,
                "loaders": None,
                "date_published": None,
                "changelog": None,
            }
        ]


def _mock_stage(provider_id, provider, pack_id, target_version_obj, staging_dir, tmpdir):
    staging_dir.mkdir(parents=True, exist_ok=True)
    mods_dir = staging_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    new_jar = mods_dir / "new-mod-2.0.jar"
    with zipfile.ZipFile(new_jar, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "new-mod", "name": "New Mod", "environment": "*"}))
    return {"loader": "fabric", "minecraft_version": "1.20.1", "loader_version": "0.15.11"}


# ============================================================================
# Contract Tests: GET /api/modpacks/server/{server_name}/versions
# ============================================================================

def test_contract_get_versions_nonexistent_server(client: TestClient):
    headers = _auth_headers(client)
    resp = client.get("/api/modpacks/server/nonexistent/versions", headers=headers)
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "nonexistent" in data["detail"]


def test_contract_get_versions_server_without_modpack(client: TestClient):
    headers = _auth_headers(client)
    srv_dir = Path(config.SERVERS_ROOT) / "vanilla-server"
    srv_dir.mkdir(parents=True, exist_ok=True)

    resp = client.get("/api/modpacks/server/vanilla-server/versions", headers=headers)
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "does not have a tracked modpack" in data["detail"]


def test_contract_get_versions_schema_alignment(client: TestClient):
    headers = _auth_headers(client)
    server_name = "test-pack-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    save_server_modpack_info(server_name, {
        "provider": "modrinth",
        "pack_id": "test-pack",
        "version_id": "v1.0",
        "version_name": "Version 1.0",
    })

    with patch("catalog_routes.get_providers_live", return_value={"modrinth": MockProviderSuccess()}):
        resp = client.get(f"/api/modpacks/server/{server_name}/versions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        # Check top-level contract keys expected by ModpackUpdateModal.jsx & ServerDetailsPage.jsx
        assert data["server_name"] == server_name
        assert data["provider"] == "modrinth"
        assert data["pack_id"] == "test-pack"
        assert data["current_version_id"] == "v1.0"
        assert data["current_version_name"] == "Version 1.0"
        assert isinstance(data["versions"], list)
        assert len(data["versions"]) == 2

        # Check version object schema
        v0 = data["versions"][0]
        assert v0["version_id"] == "v2.0"
        assert v0["version_name"] == "Version 2.0"
        assert v0["version_number"] == "2.0.0"
        assert v0["game_versions"] == ["1.20.1"]
        assert v0["loaders"] == ["fabric"]
        assert v0["date_published"] == "2026-11-05T12:00:00Z"
        assert "Big performance improvements" in v0["changelog"]
        assert v0["is_current"] is False

        v1 = data["versions"][1]
        assert v1["version_id"] == "v1.0"
        assert v1["is_current"] is True


def test_contract_get_versions_adversarial_null_fields(client: TestClient):
    headers = _auth_headers(client)
    server_name = "null-pack-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    save_server_modpack_info(server_name, {
        "provider": "modrinth",
        "pack_id": "null-pack",
        "version_id": None,
    })

    with patch("catalog_routes.get_providers_live", return_value={"modrinth": MockProviderAdversarial()}):
        resp = client.get(f"/api/modpacks/server/{server_name}/versions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["current_version_id"] is None
        assert data["current_version_name"] is None
        assert len(data["versions"]) == 1

        v = data["versions"][0]
        assert v["version_id"] == "v_adv"
        # Version name should safely fall back to version_id
        assert v["version_name"] == "v_adv"
        assert v["version_number"] == "v_adv"
        assert v["game_versions"] == []
        assert v["loaders"] == []
        assert v["date_published"] is None
        assert v["changelog"] == ""
        assert v["is_current"] is False


# ============================================================================
# Contract Tests: POST /api/modpacks/server/{server_name}/update
# ============================================================================

def test_contract_post_update_validation_errors(client: TestClient):
    headers = _auth_headers(client)
    server_name = "val-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    # Missing target_version_id
    resp = client.post(f"/api/modpacks/server/{server_name}/update", json={}, headers=headers)
    assert resp.status_code == 422

    # Malformed body
    resp = client.post(
        f"/api/modpacks/server/{server_name}/update",
        content="not-json",
        headers={"Content-Type": "application/json", **headers},
    )
    assert resp.status_code == 422

    # Server without modpack metadata
    resp = client.post(
        f"/api/modpacks/server/{server_name}/update",
        json={"target_version_id": "v2"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "does not have modpack metadata" in resp.json()["detail"]


def test_contract_post_update_success_payload(client: TestClient):
    headers = _auth_headers(client)
    server_name = "up-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)
    mods_dir = srv_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)

    # Put an old jar to verify cleanup
    old_jar = mods_dir / "old-mod-1.0.jar"
    with zipfile.ZipFile(old_jar, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "old-mod", "name": "Old Mod"}))

    save_server_modpack_info(server_name, {
        "provider": "modrinth",
        "pack_id": "test-pack",
        "version_id": "v1.0",
        "version_name": "Version 1.0",
        "loader": "fabric",
        "minecraft_version": "1.20.1",
        "installed_files": ["mods/old-mod-1.0.jar"],
    })

    with patch("catalog_routes.get_providers_live", return_value={"modrinth": MockProviderSuccess()}):
        with patch("modpack_routes._stage_modpack_version", side_effect=_mock_stage):
            with patch("backup_manager.create_backup_async", return_value={"file": "up-server-pre-update-123.zip"}):
                with patch("runtime_adapter.get_runtime_manager_or_docker"):
                    resp = client.post(
                        f"/api/modpacks/server/{server_name}/update",
                        json={"target_version_id": "v2.0", "create_backup": True},
                        headers=headers,
                    )
                    assert resp.status_code == 200
                    data = resp.json()

                    # Verify exact contract response fields expected by ModpackUpdateModal.jsx
                    assert data["status"] == "success"
                    assert data["server_name"] == server_name
                    assert data["previous_version"] == "v1.0"
                    assert data["updated_version"] == "v2.0"
                    assert data["backup_created"] == "up-server-pre-update-123.zip"
                    assert isinstance(data["mods_cleaned"], list)
                    assert isinstance(data["mods_added"], list)
                    assert isinstance(data["client_mods_filtered"], list)

                    # Verify disk metadata updated
                    meta = get_server_modpack_info(server_name)
                    assert meta["version_id"] == "v2.0"
                    assert meta["version_name"] == "Version 2.0"


def test_contract_post_update_no_backup(client: TestClient):
    headers = _auth_headers(client)
    server_name = "nobk-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    save_server_modpack_info(server_name, {
        "provider": "modrinth",
        "pack_id": "test-pack",
        "version_id": "v1.0",
    })

    with patch("catalog_routes.get_providers_live", return_value={"modrinth": MockProviderSuccess()}):
        with patch("modpack_routes._stage_modpack_version", side_effect=_mock_stage):
            with patch("runtime_adapter.get_runtime_manager_or_docker"):
                resp = client.post(
                    f"/api/modpacks/server/{server_name}/update",
                    json={"target_version_id": "v2.0", "create_backup": False},
                    headers=headers,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["backup_created"] is None


# ============================================================================
# Contract Tests: GET /api/client-mods/whitelist/{server_name}
# ============================================================================

def test_contract_get_whitelist_empty(client: TestClient):
    headers = _auth_headers(client)
    server_name = "empty-wl-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    resp = client.get(f"/api/client-mods/whitelist/{server_name}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Must contain patterns and entries
    assert "patterns" in data
    assert "entries" in data
    assert data["patterns"] == []
    assert data["entries"] == []


def test_contract_get_whitelist_structured(client: TestClient):
    headers = _auth_headers(client)
    server_name = "wl-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    add_to_allowlist(
        srv_dir,
        pattern="appleskin*",
        mod_name="AppleSkin",
        added_by="admin",
        notes="Helpful HUD",
        status="active",
    )

    resp = client.get(f"/api/client-mods/whitelist/{server_name}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["patterns"] == ["appleskin*"]
    assert len(data["entries"]) == 1
    e = data["entries"][0]

    # Required structured fields
    assert e["pattern"] == "appleskin*"
    assert e["mod_name"] == "AppleSkin"
    assert e["added_by"] == "admin"
    assert e["notes"] == "Helpful HUD"
    assert e["status"] == "active"
    assert "added_at" in e and e["added_at"]


# ============================================================================
# Contract Tests: POST /api/client-mods/whitelist/{server_name}
# ============================================================================

def test_contract_post_whitelist_validation(client: TestClient):
    headers = _auth_headers(client)
    server_name = "post-wl-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    # Empty pattern
    resp = client.post(f"/api/client-mods/whitelist/{server_name}", json={"pattern": ""}, headers=headers)
    assert resp.status_code == 400

    # Pattern with newline
    resp = client.post(f"/api/client-mods/whitelist/{server_name}", json={"pattern": "bad\npattern"}, headers=headers)
    assert resp.status_code == 400

    # Nonexistent server
    resp = client.post("/api/client-mods/whitelist/missing-server", json={"pattern": "valid*"}, headers=headers)
    assert resp.status_code == 404


def test_contract_post_whitelist_exact_payload(client: TestClient):
    headers = _auth_headers(client)
    server_name = "add-wl-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    # Exact payload structure sent by ClientModFilterPanel.jsx handleAddEntry
    payload = {
        "pattern": "jei*",
        "mod_name": "Just Enough Items",
        "notes": "Essential recipe viewer",
        "status": "active",
    }

    resp = client.post(f"/api/client-mods/whitelist/{server_name}", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "message" in data
    assert data["pattern"] == "jei*"
    assert data["entry"]["pattern"] == "jei*"
    assert data["entry"]["mod_name"] == "Just Enough Items"
    assert data["entry"]["notes"] == "Essential recipe viewer"
    assert data["entry"]["status"] == "active"
    assert data["entry"]["added_by"] == "admin"


# ============================================================================
# Contract Tests: DELETE /api/client-mods/whitelist/{server_name}
# ============================================================================

def test_contract_delete_whitelist_query_param(client: TestClient):
    """ClientModFilterPanel.jsx calls DELETE /api/client-mods/whitelist/{server_name}?pattern={pattern}."""
    headers = _auth_headers(client)
    server_name = "del-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    add_to_allowlist(srv_dir, pattern="sodium*")
    assert len(get_allowlist_entries(srv_dir)) == 1

    resp = client.delete(f"/api/client-mods/whitelist/{server_name}?pattern=sodium*", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["pattern"] == "sodium*"
    assert "Removed 'sodium*' from whitelist" in data["message"]
    assert len(get_allowlist_entries(srv_dir)) == 0


def test_contract_delete_whitelist_body_param(client: TestClient):
    """Backend also supports JSON body DELETE."""
    headers = _auth_headers(client)
    server_name = "del-server-body"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    add_to_allowlist(srv_dir, pattern="iris*")

    resp = client.request("DELETE", f"/api/client-mods/whitelist/{server_name}", json={"pattern": "iris*"}, headers=headers)
    assert resp.status_code == 200
    assert len(get_allowlist_entries(srv_dir)) == 0


def test_contract_delete_whitelist_errors(client: TestClient):
    headers = _auth_headers(client)
    server_name = "del-err-server"
    srv_dir = Path(config.SERVERS_ROOT) / server_name
    srv_dir.mkdir(parents=True, exist_ok=True)

    # Missing pattern
    resp = client.delete(f"/api/client-mods/whitelist/{server_name}", headers=headers)
    assert resp.status_code == 400

    # Pattern not found
    resp = client.delete(f"/api/client-mods/whitelist/{server_name}?pattern=nonexistent*", headers=headers)
    assert resp.status_code == 404
