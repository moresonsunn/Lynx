"""Empirical Adversarial Stress-Testing Suite for Milestone 2:
Modpack Update Engine, Version APIs, Lifecycle Handling, and Error Conditions.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-modpack-update-adv-987654321")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_update_adv"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_update_adv.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

from client_mod_filter import add_to_allowlist, is_mod_allowlisted
from mod_side_resolver import ModSideResolver, inspect_jar_metadata
import modpack_routes
from modpack_routes import (
    get_server_modpack_info,
    save_server_modpack_info,
    reconcile_and_cleanup_modpack,
    is_path_protected,
    ModpackUpdateRequest,
)
from tests.test_auth_users_api import engine, db_session, client, _login  # noqa: F401


# ============================================================================
# Helpers & Fixtures
# ============================================================================

def make_dummy_jar(
    jar_path: Path,
    mod_id: str,
    version: str = "1.0.0",
    loader: str = "fabric",
    environment: str = "*",
) -> Path:
    """Creates a valid mod JAR file with metadata for inspection."""
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if loader == "fabric":
            f_mod = {
                "schemaVersion": 1,
                "id": mod_id,
                "version": version,
                "name": mod_id.capitalize(),
                "environment": environment,
            }
            zf.writestr("fabric.mod.json", json.dumps(f_mod))
        elif loader in ("forge", "neoforge"):
            toml_content = f"""
modLoader="javafml"
loaderVersion="[1,)"
[[mods]]
modId="{mod_id}"
version="{version}"
displayName="{mod_id.capitalize()}"
{"clientSideOnly=true" if environment == "client" else ""}
"""
            fname = "META-INF/neoforge.mods.toml" if loader == "neoforge" else "META-INF/mods.toml"
            zf.writestr(fname, toml_content.strip())
    return jar_path


def create_mock_mrpack_bytes(
    mods: List[Tuple[str, str, str, str]],  # (filename, mod_id, version, environment)
    overrides_files: Optional[Dict[str, str]] = None,
    mc_version: str = "1.20.1",
    loader: str = "fabric",
) -> bytes:
    """Builds a real in-memory .mrpack archive with overrides and index."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        index_data = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": "v1.1",
            "name": "Test Pack 1.1",
            "dependencies": {
                "minecraft": mc_version,
                "fabric-loader": "0.15.11",
            },
            "files": [],
        }
        zf.writestr("modrinth.index.json", json.dumps(index_data))

        for fname, mid, ver, env in mods:
            jar_buf = io.BytesIO()
            with zipfile.ZipFile(jar_buf, "w", compression=zipfile.ZIP_DEFLATED) as jz:
                f_mod = {
                    "schemaVersion": 1,
                    "id": mid,
                    "version": ver,
                    "name": mid.capitalize(),
                    "environment": env,
                }
                jz.writestr("fabric.mod.json", json.dumps(f_mod))
            zf.writestr(f"overrides/mods/{fname}", jar_buf.getvalue())

        if overrides_files:
            for rel_p, content in overrides_files.items():
                zf.writestr(f"overrides/{rel_p}", content)

    return buf.getvalue()


class MockHttpResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.ok = (200 <= status_code < 300)

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i : i + chunk_size]

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def adv_server(tmp_path: Path, monkeypatch) -> Path:
    """Prepares an isolated mock server environment."""
    servers_root = tmp_path / "servers"
    servers_root.mkdir(parents=True, exist_ok=True)
    server_dir = servers_root / "AdvServer"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "mods").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(modpack_routes, "SERVERS_ROOT", servers_root)
    import config
    monkeypatch.setattr(config, "SERVERS_ROOT", servers_root)
    import backup_manager
    monkeypatch.setattr(backup_manager, "SERVERS_ROOT", servers_root)
    monkeypatch.setattr(backup_manager, "DEFAULT_BACKUPS_ROOT", tmp_path / "backups")
    return server_dir


# ============================================================================
# 1. Adversarial Non-Modpack Server Tests
# ============================================================================

def test_adv_get_versions_nonexistent_server(adv_server: Path, client, monkeypatch):
    """GET /versions on non-existent server name returns 404 cleanly."""
    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = []
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.get("/api/modpacks/server/GhostServerDoesNotExist/versions", headers=admin_h)
    assert res.status_code == 404
    data = res.json()
    assert "does not have a tracked modpack" in data["detail"]


def test_adv_get_versions_vanilla_server(adv_server: Path, client, monkeypatch):
    """GET /versions on an existing server without modpack metadata/labels returns 404 cleanly."""
    # adv_server exists on disk, but has no modpack.meta.json or docker labels
    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [{"name": "AdvServer", "id": "c_vanilla", "labels": {}}]
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.get("/api/modpacks/server/AdvServer/versions", headers=admin_h)
    assert res.status_code == 404
    data = res.json()
    assert "does not have a tracked modpack" in data["detail"]


def test_adv_post_update_nonexistent_server(adv_server: Path, client, monkeypatch):
    """POST /update on non-existent server returns 404 cleanly."""
    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = []
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/GhostServerDoesNotExist/update",
        json={"target_version_id": "v1.1", "create_backup": True},
        headers=admin_h,
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_adv_post_update_vanilla_server(adv_server: Path, client, monkeypatch):
    """POST /update on existing vanilla server (no modpack installed) returns 400 cleanly."""
    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [{"name": "AdvServer", "id": "c_vanilla", "labels": {}}]
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": True},
        headers=admin_h,
    )
    assert res.status_code == 400
    assert "does not have modpack metadata installed" in res.json()["detail"]


# ============================================================================
# 2. Adversarial Target Version ID Tests
# ============================================================================

def test_adv_post_update_unknown_target_version(adv_server: Path, client, monkeypatch):
    """POST /update with non-existent target version ID returns 404 cleanly."""
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-1", "version_id": "v1.0", "installed_files": []},
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {"id": "v1.0", "name": "1.0.0", "files": []},
        {"id": "v1.1", "name": "1.1.0", "files": []},
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v999.nonexistent.id", "create_backup": True},
        headers=admin_h,
    )
    assert res.status_code == 404
    assert "Target version 'v999.nonexistent.id' not found" in res.json()["detail"]


def test_adv_post_update_malicious_target_version_id(adv_server: Path, client, monkeypatch):
    """POST /update with path traversal/injection in target_version_id is safely handled (404)."""
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-1", "version_id": "v1.0", "installed_files": []},
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [{"id": "v1.0", "name": "1.0.0", "files": []}]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")

    malicious_ids = [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "'; DROP TABLE users; --",
        "<script>alert(1)</script>",
        "\x00nullbyte",
    ]

    for mal_id in malicious_ids:
        res = client.post(
            "/api/modpacks/server/AdvServer/update",
            json={"target_version_id": mal_id, "create_backup": False},
            headers=admin_h,
        )
        assert res.status_code in (404, 422)


# ============================================================================
# 3. Update with create_backup=False Tests
# ============================================================================

def test_adv_post_update_create_backup_false(adv_server: Path, client, monkeypatch):
    """POST /update with create_backup=False succeeds without calling create_backup_async."""
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-nobk", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("newmod.jar", "newmod", "1.0.0", "*")])
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0",
            "name": "2.0.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    import backup_manager
    backup_mock = MagicMock()
    monkeypatch.setattr(backup_manager, "create_backup_async", backup_mock)

    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["backup_created"] is None
    assert data["updated_version"] == "v2.0"
    backup_mock.assert_not_called()
    assert (adv_server / "mods" / "newmod.jar").exists()


# ============================================================================
# 4. Backup Creation Failure Simulation (Update Abort & File Integrity)
# ============================================================================

def test_adv_backup_failure_aborts_update_and_preserves_files(adv_server: Path, client, monkeypatch):
    """
    Simulate pre-update backup failure (e.g. disk quota full or I/O error).
    The update must abort with 500, and existing server files/metadata must remain completely intact.
    """
    # 1. Establish initial server state
    initial_jar = make_dummy_jar(adv_server / "mods" / "preserve-me-1.0.jar", mod_id="preservemod")
    config_file = adv_server / "config" / "server-config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"important": "state"}', encoding="utf-8")

    initial_meta = {
        "provider": "modrinth",
        "pack_id": "pack-preserve",
        "version_id": "v1.0",
        "version_name": "1.0.0",
        "installed_files": ["mods/preserve-me-1.0.jar", "config/server-config.json"],
    }
    save_server_modpack_info("AdvServer", initial_meta)

    # 2. Setup mock target version that would delete preserve-me if update ran
    mrpack_bytes = create_mock_mrpack_bytes([("incoming-mod-2.0.jar", "incomingmod", "2.0.0", "*")])
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0",
            "name": "2.0.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    # 3. Simulate backup failure (raises RuntimeError or IOError)
    import backup_manager
    async def failing_backup(*args, **kwargs):
        raise OSError("Disk quota exceeded: failed to create archive")
    monkeypatch.setattr(backup_manager, "create_backup_async", failing_backup)

    # 4. Execute update
    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v2.0", "create_backup": True},
        headers=admin_h,
    )

    # 5. Assertions: 500 error returned
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert "Safety backup failed before update" in detail
    assert "Update aborted" in detail

    # 6. File system integrity verification: server files must be 100% untouched
    assert initial_jar.exists(), "Original mod jar must not be deleted when backup fails!"
    assert config_file.exists(), "Config file must not be modified when backup fails!"
    assert not (adv_server / "mods" / "incoming-mod-2.0.jar").exists(), "New version files must not be installed!"

    # 7. Metadata integrity verification: metadata must still reflect v1.0
    saved_meta = get_server_modpack_info("AdvServer")
    assert saved_meta["version_id"] == "v1.0"
    assert saved_meta["version_name"] == "1.0.0"
    assert "mods/preserve-me-1.0.jar" in saved_meta["installed_files"]


# ============================================================================
# 5. Target Server Running vs Stopped Container Lifecycle Handling
# ============================================================================

def test_adv_container_lifecycle_running_server(adv_server: Path, client, monkeypatch):
    """
    Target server container is RUNNING:
    Lifecycle engine must stop server before staging/applying files and restart server after update.
    """
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-life", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("newmod.jar", "newmod", "1.0.0", "*")])
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    # Mock Docker Manager
    stop_called_with = []
    start_called_with = []

    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [
        {"name": "AdvServer", "id": "container_running_123", "status": "running"}
    ]
    mock_dm.stop_server.side_effect = lambda cid, timeout=60: stop_called_with.append((cid, timeout))
    mock_dm.start_server.side_effect = lambda cid: start_called_with.append(cid)

    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Verify lifecycle calls
    assert len(stop_called_with) == 1
    assert stop_called_with[0] == ("container_running_123", 60)

    assert len(start_called_with) == 1
    assert start_called_with[0] == "container_running_123"


def test_adv_container_lifecycle_stopped_server(adv_server: Path, client, monkeypatch):
    """
    Target server container is STOPPED (exited):
    Lifecycle engine must NOT call stop_server, and must NOT start the server after update.
    """
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-life", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("newmod.jar", "newmod", "1.0.0", "*")])
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [
        {"name": "AdvServer", "id": "container_stopped_456", "status": "exited"}
    ]

    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Container was stopped: neither stop nor start should be called!
    mock_dm.stop_server.assert_not_called()
    mock_dm.start_server.assert_not_called()


def test_adv_container_lifecycle_stop_error_resilience(adv_server: Path, client, monkeypatch):
    """
    If stop_server raises an exception (e.g. timeout or Docker daemon error),
    the error is logged and the update proceeds safely.
    """
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-life", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("newmod.jar", "newmod", "1.0.0", "*")])
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [
        {"name": "AdvServer", "id": "container_err", "status": "running"}
    ]
    mock_dm.stop_server.side_effect = RuntimeError("Docker API timeout waiting for stop")
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    # Update should still succeed despite stop_server warning
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    mock_dm.start_server.assert_called_once_with("container_err")


def test_adv_container_lifecycle_start_error_resilience(adv_server: Path, client, monkeypatch):
    """
    If start_server raises an exception after update,
    the update response still returns 200 success with the new version details.
    """
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-life", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("newmod.jar", "newmod", "1.0.0", "*")])
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [
        {"name": "AdvServer", "id": "container_err_start", "status": "running"}
    ]
    mock_dm.start_server.side_effect = RuntimeError("Port already allocated during restart")
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["updated_version"] == "v1.1"


# ============================================================================
# 6. Failure Modes during Staging, Download, and Provider Communication
# ============================================================================

def test_adv_update_provider_get_versions_error(adv_server: Path, client, monkeypatch):
    """When modpack provider raises an error fetching versions, 502 Bad Gateway is returned."""
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-fail", "version_id": "v1.0", "installed_files": []},
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.side_effect = requests.RequestException("Modrinth API is down 503")
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 502
    assert "Failed to fetch versions from provider" in res.json()["detail"]


def test_adv_update_no_downloadable_artifact(adv_server: Path, client, monkeypatch):
    """When target version has no downloadable files/urls, 400 Bad Request is returned."""
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-no-art", "version_id": "v1.0", "installed_files": []},
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {"id": "v1.1", "name": "1.1.0", "files": []}  # Empty files list!
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 400
    assert "No downloadable artifact found" in res.json()["detail"]


def test_adv_update_corrupt_zip_artifact(adv_server: Path, client, monkeypatch):
    """When downloaded artifact is corrupted bytes, staging raises an error and files remain intact."""
    initial_jar = make_dummy_jar(adv_server / "mods" / "oldmod.jar", mod_id="oldmod")
    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-corrupt", "version_id": "v1.0", "installed_files": ["mods/oldmod.jar"]},
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "files": [{"filename": "corrupt.mrpack", "url": "http://example.com/corrupt.mrpack"}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    # Deliver completely corrupted non-zip bytes
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(b"THIS_IS_NOT_A_VALID_ZIP_HEADER"))

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 500

    # Server files must remain intact
    assert initial_jar.exists()
    assert get_server_modpack_info("AdvServer")["version_id"] == "v1.0"


# ============================================================================
# 7. Obsolete Mod Cleanup Edge Cases
# ============================================================================

def test_adv_cleanup_case_insensitive_mod_id(adv_server: Path):
    """Method B deduplication matches mod IDs case-insensitively (e.g. 'JEI' vs 'jei')."""
    mods_dir = adv_server / "mods"
    old_jar = make_dummy_jar(mods_dir / "JEI-1.20.1-15.0.0.jar", mod_id="JEI", version="15.0.0")

    staging_dir = adv_server / "_staging_case"
    staging_mods = staging_dir / "mods"
    new_jar = make_dummy_jar(staging_mods / "jei-1.20.1-15.1.0.jar", mod_id="jei", version="15.1.0")

    result = reconcile_and_cleanup_modpack(
        server_dir=adv_server,
        staging_dir=staging_dir,
        previous_meta={"installed_files": ["mods/JEI-1.20.1-15.0.0.jar"]},
    )

    assert "JEI-1.20.1-15.0.0.jar" in result["mods_cleaned"]
    assert not old_jar.exists(), "Old JEI jar should have been deleted despite uppercase mod_id!"


def test_adv_cleanup_corrupted_jar_in_mods_skipped(adv_server: Path):
    """A corrupted 0-byte or truncated jar in mods/ does not crash reconcile_and_cleanup_modpack."""
    corrupt_jar = adv_server / "mods" / "corrupted-mod.jar"
    corrupt_jar.write_bytes(b"\x00\x01\x02\x03\x04")  # Invalid jar

    staging_dir = adv_server / "_staging_corrupt"
    make_dummy_jar(staging_dir / "mods" / "valid-mod.jar", mod_id="validmod")

    # Should not raise exception
    result = reconcile_and_cleanup_modpack(
        server_dir=adv_server,
        staging_dir=staging_dir,
        previous_meta={"installed_files": []},
    )
    assert isinstance(result["mods_cleaned"], list)


def test_adv_cleanup_empty_and_null_installed_files(adv_server: Path):
    """When previous_meta has None or missing installed_files, cleanup executes safely."""
    make_dummy_jar(adv_server / "mods" / "sample.jar", mod_id="sample")
    staging_dir = adv_server / "_staging_null"
    staging_dir.mkdir(parents=True, exist_ok=True)

    res1 = reconcile_and_cleanup_modpack(
        server_dir=adv_server,
        staging_dir=staging_dir,
        previous_meta=None,
    )
    assert res1["mods_cleaned"] == []

    res2 = reconcile_and_cleanup_modpack(
        server_dir=adv_server,
        staging_dir=staging_dir,
        previous_meta={"installed_files": None},
    )
    assert res2["mods_cleaned"] == []


# ============================================================================
# 8. Post-Update Allowlist Preservation & Client Mod Quarantine
# ============================================================================

def test_adv_update_preserves_wildcard_allowlist(adv_server: Path, client, monkeypatch):
    """
    Wildcard pattern in allowlist (e.g. '*voice*') protects matching client mods during update
    while unwhitelisted client mods are quarantined to mods-disabled-client/.
    """
    add_to_allowlist(
        server_dir=adv_server,
        pattern="*voice*",
        mod_name="Simple Voice Chat",
        notes="Permitted for proximity audio",
    )

    save_server_modpack_info(
        "AdvServer",
        {"provider": "modrinth", "pack_id": "pack-wild", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes(
        [
            ("voicechat-fabric-1.20.1-2.4.32.jar", "voicechat", "2.4.32", "client"),
            ("unauthorized-hud-1.0.jar", "unauthorized-hud", "1.0.0", "client"),
            ("server-core-1.0.jar", "server-core", "1.0.0", "*"),
        ]
    )
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    # Allowed voicechat remains in mods/
    assert "voicechat-fabric-1.20.1-2.4.32.jar" not in data["client_mods_filtered"]
    assert (adv_server / "mods" / "voicechat-fabric-1.20.1-2.4.32.jar").exists()

    # Unauthorized client mod is filtered to mods-disabled-client/
    assert "unauthorized-hud-1.0.jar" in data["client_mods_filtered"]
    assert (adv_server / "mods-disabled-client" / "unauthorized-hud-1.0.jar").exists()
    assert not (adv_server / "mods" / "unauthorized-hud-1.0.jar").exists()

    # Server mod remains in mods/
    assert (adv_server / "mods" / "server-core-1.0.jar").exists()
