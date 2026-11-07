"""Comprehensive pytest test suite for Milestone 2:
Modpack Update Engine, Version APIs, Duplicate/Dropped Mod Cleanup, and Filter Integration.
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
import requests

import tempfile

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-modpack-update-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_update"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_update.db"))
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
    environment: str = "*",  # "*", "client", "server"
) -> Path:
    """Creates a real valid mod JAR file with metadata for inspection."""
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
def mock_server(tmp_path: Path, monkeypatch) -> Path:
    """Prepares a clean mock server directory under modpack_routes.SERVERS_ROOT."""
    servers_root = tmp_path / "servers"
    servers_root.mkdir(parents=True, exist_ok=True)
    server_dir = servers_root / "TestUpdateServer"
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
# 1. Version Query Endpoint Tests
# ============================================================================

def test_query_available_versions_modrinth(mock_server: Path, client, monkeypatch):
    """Test GET /api/modpacks/server/{name}/versions returns target versions with is_current flag."""
    meta = {
        "provider": "modrinth",
        "pack_id": "test-pack-123",
        "version_id": "v1.0",
        "version_name": "1.0.0",
        "installed_files": ["mods/foo.jar"],
    }
    save_server_modpack_info("TestUpdateServer", meta)

    mock_versions = [
        {
            "id": "v1.1",
            "name": "1.1.0",
            "version_number": "1.1.0",
            "game_versions": ["1.20.1"],
            "loaders": ["fabric"],
            "date_published": "2026-11-01T12:00:00Z",
            "changelog": "New performance tweaks",
            "files": [{"filename": "pack.mrpack", "url": "https://example.com/pack.mrpack", "primary": True}],
        },
        {
            "id": "v1.0",
            "name": "1.0.0",
            "version_number": "1.0.0",
            "game_versions": ["1.20.1"],
            "loaders": ["fabric"],
            "date_published": "2026-10-15T10:00:00Z",
            "changelog": "Initial release",
            "files": [{"filename": "pack-1.0.mrpack", "url": "https://example.com/pack1.mrpack", "primary": True}],
        },
    ]

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = mock_versions

    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.get("/api/modpacks/server/TestUpdateServer/versions", headers=admin_h)
    assert res.status_code == 200
    data = res.json()

    assert data["server_name"] == "TestUpdateServer"
    assert data["provider"] == "modrinth"
    assert data["pack_id"] == "test-pack-123"
    assert data["current_version_id"] == "v1.0"
    assert data["current_version_name"] == "1.0.0"
    assert len(data["versions"]) == 2

    # Check version items
    v1_1 = next(v for v in data["versions"] if v["version_id"] == "v1.1")
    assert v1_1["is_current"] is False
    assert v1_1["changelog"] == "New performance tweaks"
    assert v1_1["loaders"] == ["fabric"]

    v1_0 = next(v for v in data["versions"] if v["version_id"] == "v1.0")
    assert v1_0["is_current"] is True
    assert v1_0["changelog"] == "Initial release"


def test_query_available_versions_fallback_docker_labels(mock_server: Path, client, monkeypatch):
    """Test GET versions resolves modpack details from Docker container labels when metadata file is absent."""
    # Ensure no modpack.meta.json or server_meta.json exists
    meta_path = mock_server / "modpack.meta.json"
    if meta_path.exists():
        meta_path.unlink()

    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [
        {
            "name": "TestUpdateServer",
            "id": "container-xyz",
            "status": "running",
            "labels": {
                "mc.modpack.provider": "modrinth",
                "mc.modpack.id": "pack-from-labels",
                "mc.modpack.version_id": "v0.9",
            },
        }
    ]
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {"id": "v0.9", "name": "0.9.0", "version_number": "0.9.0", "files": []}
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.get("/api/modpacks/server/TestUpdateServer/versions", headers=admin_h)
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "modrinth"
    assert data["pack_id"] == "pack-from-labels"
    assert data["current_version_id"] == "v0.9"
    assert data["versions"][0]["is_current"] is True


def test_query_versions_not_a_modpack_server(mock_server: Path, client, monkeypatch):
    """Querying a server without any modpack metadata or labels returns 404."""
    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [{"name": "TestUpdateServer", "id": "c1", "labels": {}}]
    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.get("/api/modpacks/server/TestUpdateServer/versions", headers=admin_h)
    assert res.status_code == 404
    assert "does not have a tracked modpack" in res.json()["detail"]


# ============================================================================
# 2. Safety Backup Invocation Tests
# ============================================================================

def test_update_triggers_automatic_backup(mock_server: Path, client, monkeypatch):
    """Calling update with create_backup=True invokes create_backup_async with tag='pre-update'."""
    save_server_modpack_info(
        "TestUpdateServer",
        {"provider": "modrinth", "pack_id": "pack-1", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("new-mod.jar", "newmod", "1.0.0", "*")])
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

    import backup_manager
    backup_mock = MagicMock()
    async def fake_backup(name, compression="zip", tag=None):
        return {"file": f"{name}-{tag}-20261107-160000.zip", "name": f"{name}-{tag}-20261107-160000.zip"}
    backup_mock.side_effect = fake_backup
    monkeypatch.setattr(backup_manager, "create_backup_async", fake_backup)

    def fake_get(url, *args, **kwargs):
        return MockHttpResponse(mrpack_bytes)
    monkeypatch.setattr(requests, "get", fake_get)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1", "create_backup": True},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["backup_created"] == "TestUpdateServer-pre-update-20261107-160000.zip"
    assert data["updated_version"] == "v1.1"


def test_update_with_backup_disabled(mock_server: Path, client, monkeypatch):
    """Calling update with create_backup=False bypasses backup creation."""
    save_server_modpack_info(
        "TestUpdateServer",
        {"provider": "modrinth", "pack_id": "pack-1", "version_id": "v1.0", "installed_files": []},
    )

    mrpack_bytes = create_mock_mrpack_bytes([("new-mod.jar", "newmod", "1.0.0", "*")])
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

    import backup_manager
    backup_spy = MagicMock()
    monkeypatch.setattr(backup_manager, "create_backup_async", backup_spy)

    def fake_get(url, *args, **kwargs):
        return MockHttpResponse(mrpack_bytes)
    monkeypatch.setattr(requests, "get", fake_get)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["backup_created"] is None
    backup_spy.assert_not_called()


# ============================================================================
# 3. Duplicate Mod Cleanup (Method B) & Dropped Mod Cleanup (Method A)
# ============================================================================

def test_duplicate_mod_cleanup_method_b(mock_server: Path, client, monkeypatch):
    """
    Test Method B: Updating jei-1.20.1-15.0.0.jar to jei-1.20.1-15.1.0.jar
    detects shared mod_id 'jei', unlinks the old jar, and leaves only the new jar.
    """
    old_jar = make_dummy_jar(mock_server / "mods" / "jei-1.20.1-15.0.0.jar", mod_id="jei", version="15.0.0")
    assert old_jar.exists()

    save_server_modpack_info(
        "TestUpdateServer",
        {
            "provider": "modrinth",
            "pack_id": "pack-jei",
            "version_id": "v1.0",
            "installed_files": ["mods/jei-1.20.1-15.0.0.jar"],
        },
    )

    # v2 delivers jei-1.20.1-15.1.0.jar
    mrpack_bytes = create_mock_mrpack_bytes([("jei-1.20.1-15.1.0.jar", "jei", "15.1.0", "*")])
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
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    assert "jei-1.20.1-15.0.0.jar" in data["mods_cleaned"]
    assert "jei-1.20.1-15.1.0.jar" in data["mods_added"]

    # File system assertions
    assert not old_jar.exists(), "Old JEI jar should have been deleted!"
    new_jar = mock_server / "mods" / "jei-1.20.1-15.1.0.jar"
    assert new_jar.exists(), "New JEI jar must exist!"

    # Exactly 1 jar in mods
    jars = list((mock_server / "mods").glob("*.jar"))
    assert len(jars) == 1
    assert jars[0].name == "jei-1.20.1-15.1.0.jar"


def test_removed_mod_cleanup_method_a(mock_server: Path, client, monkeypatch):
    """
    Test Method A: Files present in v1 installed_files but absent in v2 are safely deleted.
    """
    dropped_jar = make_dummy_jar(mock_server / "mods" / "dropped-mod-1.0.jar", mod_id="droppedmod")
    dropped_config = mock_server / "config" / "dropped.json"
    dropped_config.parent.mkdir(parents=True, exist_ok=True)
    dropped_config.write_text('{"old_config": true}', encoding="utf-8")

    save_server_modpack_info(
        "TestUpdateServer",
        {
            "provider": "modrinth",
            "pack_id": "pack-drop",
            "version_id": "v1.0",
            "installed_files": ["mods/dropped-mod-1.0.jar", "config/dropped.json"],
        },
    )

    # v2 delivers a new unrelated mod, completely omitting dropped-mod and dropped.json
    mrpack_bytes = create_mock_mrpack_bytes([("newmod-1.0.jar", "newmod", "1.0.0", "*")])
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
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    assert "dropped-mod-1.0.jar" in data["mods_cleaned"]
    assert not dropped_jar.exists(), "Dropped jar must be deleted!"
    assert not dropped_config.exists(), "Dropped config file must be pruned!"
    assert (mock_server / "mods" / "newmod-1.0.jar").exists()


def test_combined_cleanup_and_deduplication(mock_server: Path):
    """
    Direct unit test of reconcile_and_cleanup_modpack combining Method B (collision deduplication)
    and Method A (manifest pruning).
    """
    mods_dir = mock_server / "mods"
    # Old version jar (will collide on mod_id 'jei')
    old_jei = make_dummy_jar(mods_dir / "jei-15.0.jar", mod_id="jei", version="15.0")
    # Dropped mod (no collision, but dropped from manifest)
    dropped = make_dummy_jar(mods_dir / "obsolete-mod.jar", mod_id="obsolete", version="1.0")
    # Custom / kept mod
    kept = make_dummy_jar(mods_dir / "kept-mod.jar", mod_id="kept", version="1.0")

    staging_dir = mock_server / "_staging_tmp"
    staging_mods = staging_dir / "mods"
    # New version jar with same mod_id 'jei'
    make_dummy_jar(staging_mods / "jei-15.1.jar", mod_id="jei", version="15.1")
    # Kept mod in new version
    make_dummy_jar(staging_mods / "kept-mod.jar", mod_id="kept", version="1.0")

    prev_meta = {
        "installed_files": [
            "mods/jei-15.0.jar",
            "mods/obsolete-mod.jar",
            "mods/kept-mod.jar",
        ]
    }

    result = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging_dir,
        previous_meta=prev_meta,
    )

    cleaned = result["mods_cleaned"]
    assert "jei-15.0.jar" in cleaned
    assert "obsolete-mod.jar" in cleaned
    assert "kept-mod.jar" not in cleaned

    assert not old_jei.exists()
    assert not dropped.exists()
    assert kept.exists()


# ============================================================================
# 4. Client Mod Filtering & Whitelist Preservation
# ============================================================================

def test_post_update_client_mod_filtering(mock_server: Path, client, monkeypatch):
    """
    Updating modpack introduces a client-only mod (environment='client').
    ModSideResolver filters it to mods-disabled-client/, listed in client_mods_filtered.
    """
    save_server_modpack_info(
        "TestUpdateServer",
        {"provider": "modrinth", "pack_id": "pack-1", "version_id": "v1.0", "installed_files": []},
    )

    # v2 introduces a client-side mod (environment='client') and a common mod
    mrpack_bytes = create_mock_mrpack_bytes(
        [
            ("sodium-extra-0.5.1.jar", "sodium-extra", "0.5.1", "client"),
            ("fabric-api-0.92.0.jar", "fabric-api", "0.92.0", "*"),
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
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    assert "sodium-extra-0.5.1.jar" in data["client_mods_filtered"]

    # File should be in mods-disabled-client, NOT in mods
    disabled_jar = mock_server / "mods-disabled-client" / "sodium-extra-0.5.1.jar"
    assert disabled_jar.exists(), "Client mod should be moved to mods-disabled-client"
    assert not (mock_server / "mods" / "sodium-extra-0.5.1.jar").exists()

    # Common mod must stay in mods
    assert (mock_server / "mods" / "fabric-api-0.92.0.jar").exists()


def test_post_update_preserves_allowlisted_mod(mock_server: Path, client, monkeypatch):
    """
    When a client-only mod matches an active entry in client-only-allow.json,
    it is strictly preserved in mods/ and NOT included in client_mods_filtered.
    """
    # 1. Add allowlist rule for appleskin*
    add_to_allowlist(
        server_dir=mock_server,
        pattern="appleskin*",
        mod_name="AppleSkin",
        notes="Allowed for convenience",
    )
    assert is_mod_allowlisted(mock_server, "appleskin-fabric-2.5.1.jar") is True

    save_server_modpack_info(
        "TestUpdateServer",
        {"provider": "modrinth", "pack_id": "pack-allow", "version_id": "v1.0", "installed_files": []},
    )

    # v2 introduces appleskin (client-side) and an unwhitelisted client mod
    mrpack_bytes = create_mock_mrpack_bytes(
        [
            ("appleskin-fabric-2.5.1.jar", "appleskin", "2.5.1", "client"),
            ("unlisted-client-1.0.jar", "unlisted", "1.0.0", "client"),
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
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    # Unlisted client mod filtered
    assert "unlisted-client-1.0.jar" in data["client_mods_filtered"]
    assert (mock_server / "mods-disabled-client" / "unlisted-client-1.0.jar").exists()

    # Whitelisted client mod preserved in mods/!
    assert "appleskin-fabric-2.5.1.jar" not in data["client_mods_filtered"]
    assert (mock_server / "mods" / "appleskin-fabric-2.5.1.jar").exists(), "Whitelisted mod must remain in mods/!"
    assert not (mock_server / "mods-disabled-client" / "appleskin-fabric-2.5.1.jar").exists()


# ============================================================================
# 5. Metadata Lifecycle & Path Traversal Security
# ============================================================================

def test_modpack_meta_lifecycle(mock_server: Path, client, monkeypatch):
    """Updating modpack updates modpack.meta.json with version details, timestamps, and files."""
    initial_meta = {
        "provider": "modrinth",
        "pack_id": "test-pack-life",
        "version_id": "v1.0",
        "version_name": "1.0.0",
        "installed_at": "2026-11-01T10:00:00Z",
        "installed_files": ["mods/old.jar"],
    }
    save_server_modpack_info("TestUpdateServer", initial_meta)

    mrpack_bytes = create_mock_mrpack_bytes([("new-life.jar", "newlife", "2.0.0", "*")])
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

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200

    # Read updated modpack.meta.json
    saved_info = get_server_modpack_info("TestUpdateServer")
    assert saved_info is not None
    assert saved_info["version_id"] == "v2.0"
    assert saved_info["version_name"] == "2.0.0"
    assert saved_info["installed_at"] == "2026-11-01T10:00:00Z"  # Preserved
    assert saved_info["updated_at"] is not None
    assert "mods/new-life.jar" in saved_info["installed_files"]


def test_security_path_traversal_protection(mock_server: Path):
    """is_path_protected prevents deletion of server identity files, world saves, and traversal paths."""
    assert is_path_protected("server.properties") is True
    assert is_path_protected("eula.txt") is True
    assert is_path_protected("client-only-allow.json") is True
    assert is_path_protected("client-only-allow.txt") is True
    assert is_path_protected("modpack.meta.json") is True
    assert is_path_protected("world/level.dat") is True
    assert is_path_protected("world_nether/data.dat") is True
    assert is_path_protected("backups/backup.zip") is True
    assert is_path_protected("logs/latest.log") is True

    # Unprotected mod and config files
    assert is_path_protected("mods/test-mod.jar") is False
    assert is_path_protected("config/pack-settings.json") is False

    # Path traversal candidates are rejected in reconcile_and_cleanup_modpack
    (mock_server / "server.properties").write_text("server-port=25565", encoding="utf-8")
    (mock_server / "world").mkdir(parents=True, exist_ok=True)
    (mock_server / "world" / "level.dat").write_text("world_data", encoding="utf-8")

    staging = mock_server / "_staging_empty"
    staging.mkdir(parents=True, exist_ok=True)

    prev_meta = {
        "installed_files": [
            "server.properties",
            "world/level.dat",
            "../../etc/passwd",
            "client-only-allow.json",
        ]
    }

    res = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging,
        previous_meta=prev_meta,
    )
    assert res["mods_cleaned"] == []
    assert res["files_removed"] == []
    assert (mock_server / "server.properties").exists()
    assert (mock_server / "world" / "level.dat").exists()


# ============================================================================
# 6. Role-Based Permissions & Authentication
# ============================================================================

def test_api_permissions_and_auth(mock_server: Path, client, db_session):
    """Verify auth requirements: anonymous requests get 401, regular users cannot trigger updates (403)."""
    # 1. Anonymous GET versions -> 401
    r = client.get("/api/modpacks/server/TestUpdateServer/versions")
    assert r.status_code == 401

    # 2. Anonymous POST update -> 401
    r = client.post(
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1"},
    )
    assert r.status_code == 401

    # 3. Regular non-moderator user
    admin_h = _login(client, "admin", "AdminPass123")
    client.post(
        "/api/users",
        json={"username": "plain_user_update", "email": "puu@localhost", "password": "UserPass123", "role": "user"},
        headers=admin_h,
    )
    user_h = _login(client, "plain_user_update", "UserPass123")

    # Regular user can GET versions (require_auth)
    save_server_modpack_info(
        "TestUpdateServer",
        {"provider": "modrinth", "pack_id": "p1", "version_id": "v1.0", "installed_files": []},
    )
    with patch("catalog_routes.get_providers_live") as mock_live:
        prov = MagicMock()
        prov.get_versions.return_value = [{"id": "v1.0", "name": "1.0", "files": []}]
        mock_live.return_value = {"modrinth": prov}
        r = client.get("/api/modpacks/server/TestUpdateServer/versions", headers=user_h)
        assert r.status_code == 200

    # Regular user CANNOT POST update (require_moderator -> 403)
    r = client.post(
        "/api/modpacks/server/TestUpdateServer/update",
        json={"target_version_id": "v1.1"},
        headers=user_h,
    )
    assert r.status_code == 403
