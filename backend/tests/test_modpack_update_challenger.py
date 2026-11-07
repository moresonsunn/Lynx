"""Adversarial stress and edge-case test suite for Milestone 2:
Modpack Update Engine, Outdated Mod Cleanup, Protected Files Invariants, and Allowlist Filtering.
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

os.environ.setdefault("SECRET_KEY", "test-secret-key-modpack-update-stress-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_update_stress"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_update_stress.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

from client_mod_filter import add_to_allowlist, is_mod_allowlisted, get_allowlist_entries
from mod_side_resolver import ModSideResolver, inspect_jar_metadata
import modpack_routes
from modpack_routes import (
    get_server_modpack_info,
    save_server_modpack_info,
    reconcile_and_cleanup_modpack,
    is_path_protected,
    ModpackUpdateRequest,
    PROTECTED_EXACT_FILES,
    PROTECTED_PREFIXES,
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
    provided_mods: Optional[List[str]] = None,
) -> Path:
    """Creates a real valid mod JAR file with metadata for inspection."""
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if loader == "fabric":
            f_mod: Dict[str, Any] = {
                "schemaVersion": 1,
                "id": mod_id,
                "version": version,
                "name": mod_id.capitalize(),
                "environment": environment,
            }
            if provided_mods:
                f_mod["provides"] = provided_mods
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
            "versionId": "v2.0",
            "name": "Stress Test Pack 2.0",
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
    server_dir = servers_root / "ChallengerTestServer"
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
# 1. Outdated Mod Cleanup: Complex Version Changes & Duplicate Removal
# ============================================================================

def test_stress_complex_version_cleanup_appleskin(mock_server: Path, client, monkeypatch):
    """
    Stress-test outdated mod cleanup on complex version transition:
    appleskin-fabric-mc1.20.1-2.5.0.jar -> appleskin-fabric-mc1.20.1-2.5.1.jar.
    Assert old jar is unlinked, new jar exists, exactly 1 jar in mods/, no duplicates remain.
    """
    mods_dir = mock_server / "mods"
    old_jar = make_dummy_jar(
        mods_dir / "appleskin-fabric-mc1.20.1-2.5.0.jar",
        mod_id="appleskin",
        version="2.5.0",
        environment="client",
    )
    # Also add an even older obsolete jar that might have lingered
    ancient_jar = make_dummy_jar(
        mods_dir / "appleskin-fabric-mc1.20.1-2.4.0.jar",
        mod_id="appleskin",
        version="2.4.0",
        environment="client",
    )
    assert old_jar.exists()
    assert ancient_jar.exists()

    save_server_modpack_info(
        "ChallengerTestServer",
        {
            "provider": "modrinth",
            "pack_id": "test-pack-appleskin",
            "version_id": "v1.0",
            "installed_files": [
                "mods/appleskin-fabric-mc1.20.1-2.5.0.jar",
                "mods/appleskin-fabric-mc1.20.1-2.4.0.jar",
            ],
        },
    )

    # Allowlist appleskin so it stays in mods/ after client-mod filter
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin")

    # v2 delivers appleskin-fabric-mc1.20.1-2.5.1.jar
    mrpack_bytes = create_mock_mrpack_bytes(
        [("appleskin-fabric-mc1.20.1-2.5.1.jar", "appleskin", "2.5.1", "client")]
    )
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0",
            "name": "2.0.0",
            "files": [{"filename": "pack.mrpack", "url": "https://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/ChallengerTestServer/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200, res.text
    data = res.json()

    # Assert old jars were marked cleaned
    assert "appleskin-fabric-mc1.20.1-2.5.0.jar" in data["mods_cleaned"]
    assert "appleskin-fabric-mc1.20.1-2.4.0.jar" in data["mods_cleaned"]
    assert "appleskin-fabric-mc1.20.1-2.5.1.jar" in data["mods_added"]

    # Assert old jars are physically deleted from mods/
    assert not old_jar.exists(), "Old appleskin 2.5.0 jar must not exist!"
    assert not ancient_jar.exists(), "Ancient appleskin 2.4.0 jar must not exist!"

    # Assert new jar is physically present
    new_jar = mods_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar"
    assert new_jar.exists(), "New appleskin 2.5.1 jar must exist!"

    # Assert NO duplicate jars in mods/
    remaining_jars = list(mods_dir.glob("*.jar"))
    assert len(remaining_jars) == 1, f"Expected exactly 1 jar, found: {remaining_jars}"
    assert remaining_jars[0].name == "appleskin-fabric-mc1.20.1-2.5.1.jar"


def test_stress_mod_id_case_insensitivity_and_naming_scheme_change(mock_server: Path):
    """
    Test reconcile_and_cleanup_modpack when mod ID casing varies:
    e.g. Existing jar had uppercase mod_id 'AppleSkin' or 'SODIUM_EXTRA',
    while incoming jar has lowercased 'appleskin' or 'sodium_extra'.
    """
    mods_dir = mock_server / "mods"
    old_jar = make_dummy_jar(
        mods_dir / "AppleSkin-1.20.1-2.0.0.jar",
        mod_id="AppleSkin",
        version="2.0.0",
    )

    staging_dir = mock_server / "_staging_case"
    staging_mods = staging_dir / "mods"
    make_dummy_jar(
        staging_mods / "appleskin-fabric-1.20.1-2.5.1.jar",
        mod_id="appleskin",
        version="2.5.1",
    )

    cleanup_res = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging_dir,
        previous_meta=None,  # Method B only!
    )

    assert "AppleSkin-1.20.1-2.0.0.jar" in cleanup_res["mods_cleaned"]
    assert not old_jar.exists(), "Old jar with different casing must be cleaned up!"


# ============================================================================
# 2. Mod Removal Between Versions (Method A Pruning)
# ============================================================================

def test_stress_mod_removal_between_versions(mock_server: Path, client, monkeypatch):
    """
    Test when mods and configs present in v1 are removed in v2.
    Assert both the jar and its associated configuration file are completely removed.
    """
    mods_dir = mock_server / "mods"
    cfg_dir = mock_server / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # v1 has Waystones mod + Balm mod + their config files
    waystones_jar = make_dummy_jar(mods_dir / "waystones-fabric-1.20.1-14.1.3.jar", mod_id="waystones")
    balm_jar = make_dummy_jar(mods_dir / "balm-fabric-1.20.1-7.2.2.jar", mod_id="balm")
    waystones_cfg = cfg_dir / "waystones.json"
    waystones_cfg.write_text('{"teleport_cost": 0}', encoding="utf-8")

    save_server_modpack_info(
        "ChallengerTestServer",
        {
            "provider": "modrinth",
            "pack_id": "test-pack-removal",
            "version_id": "v1.0",
            "installed_files": [
                "mods/waystones-fabric-1.20.1-14.1.3.jar",
                "mods/balm-fabric-1.20.1-7.2.2.jar",
                "config/waystones.json",
            ],
        },
    )

    # v2 completely removes Waystones and waystones.json, keeps only balm (updated to 7.2.3)
    mrpack_bytes = create_mock_mrpack_bytes(
        [("balm-fabric-1.20.1-7.2.3.jar", "balm", "7.2.3", "*")]
    )
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0",
            "name": "2.0.0",
            "files": [{"filename": "pack.mrpack", "url": "https://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/ChallengerTestServer/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200, res.text
    data = res.json()

    # Assert Waystones was cleaned up (Method A) and old Balm was cleaned up (Method B)
    assert "waystones-fabric-1.20.1-14.1.3.jar" in data["mods_cleaned"]
    assert "balm-fabric-1.20.1-7.2.2.jar" in data["mods_cleaned"]
    assert "config/waystones.json" in data.get("files_removed", []) or not waystones_cfg.exists()

    assert not waystones_jar.exists(), "Removed mod jar must be unlinked!"
    assert not balm_jar.exists(), "Old version of kept mod must be unlinked!"
    assert not waystones_cfg.exists(), "Removed mod's config must be unlinked!"

    # Assert new balm jar exists
    assert (mods_dir / "balm-fabric-1.20.1-7.2.3.jar").exists()


def test_stress_dropped_mod_previously_quarantined_cleanup(mock_server: Path):
    """
    Test when a mod was previously quarantined in mods-disabled-client/,
    and is subsequently removed in the new modpack version.
    Assert it is cleaned up from mods-disabled-client/.
    """
    disabled_dir = mock_server / "mods-disabled-client"
    disabled_dir.mkdir(parents=True, exist_ok=True)
    quarantined_jar = make_dummy_jar(disabled_dir / "old-client-only-mod-1.0.jar", mod_id="oldclient", environment="client")

    staging_dir = mock_server / "_staging_prune_disabled"
    staging_mods = staging_dir / "mods"
    make_dummy_jar(staging_mods / "unrelated-mod.jar", mod_id="unrelated", version="1.0")

    prev_meta = {
        "installed_files": [
            "mods/old-client-only-mod-1.0.jar",
        ]
    }

    res = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging_dir,
        previous_meta=prev_meta,
    )

    assert "old-client-only-mod-1.0.jar" in res["mods_cleaned"]
    assert not quarantined_jar.exists(), "Quarantined mod must be cleaned up when dropped!"


# ============================================================================
# 3. Protected Files Invariants (Zero File Deletion Guarantee)
# ============================================================================

def test_stress_protected_files_never_deleted_during_cleanup(mock_server: Path):
    """
    Adversarial stress test:
    Inject ALL protected files and user configs into previous_meta["installed_files"].
    The new staging version contains NONE of them.
    reconcile_and_cleanup_modpack MUST NEVER delete any protected file.
    """
    # 1. Populate protected exact files
    files_to_verify: Dict[str, str] = {}
    for exact_f in PROTECTED_EXACT_FILES:
        target = mock_server / exact_f
        target.parent.mkdir(parents=True, exist_ok=True)
        content = f"content_of_{exact_f}_secret"
        target.write_text(content, encoding="utf-8")
        files_to_verify[exact_f] = content

    # 2. Populate protected prefix directories
    prefix_samples = [
        "world/level.dat",
        "world/region/r.0.0.mca",
        "world_nether/DIM-1/data.dat",
        "world_the_end/DIM1/level.dat",
        "backups/pre-update-backup.zip",
        "logs/latest.log",
        "logs/debug.log",
        "crash-reports/crash-2026-11-07.txt",
    ]
    for rel_p in prefix_samples:
        target = mock_server / rel_p
        target.parent.mkdir(parents=True, exist_ok=True)
        content = f"content_of_{rel_p}"
        target.write_text(content, encoding="utf-8")
        files_to_verify[rel_p] = content

    # 3. User custom config file (NOT in installed_files)
    user_cfg = mock_server / "config" / "user_custom_server_rules.json"
    user_cfg.parent.mkdir(parents=True, exist_ok=True)
    user_cfg.write_text('{"pvp": false, "custom": true}', encoding="utf-8")

    # 4. Craft malicious previous_meta claiming that ALL protected files belong to modpack v1
    malicious_installed_files = list(files_to_verify.keys())
    # Add regular mod that SHOULD be cleaned up
    doomed_mod = make_dummy_jar(mock_server / "mods" / "doomed-1.0.jar", mod_id="doomed")
    malicious_installed_files.append("mods/doomed-1.0.jar")

    staging_dir = mock_server / "_staging_empty_new_pack"
    staging_mods = staging_dir / "mods"
    make_dummy_jar(staging_mods / "survivor-2.0.jar", mod_id="survivor")

    res = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging_dir,
        previous_meta={"installed_files": malicious_installed_files},
    )

    # Doomed mod must be cleaned up
    assert "doomed-1.0.jar" in res["mods_cleaned"]
    assert not doomed_mod.exists()

    # NONE of the protected files should be in mods_cleaned or files_removed
    for rel_p in files_to_verify.keys():
        assert rel_p not in res["files_removed"], f"Protected file {rel_p} was marked as removed!"
        assert rel_p not in res["mods_cleaned"], f"Protected file {rel_p} was marked as cleaned!"

        # File MUST still exist with exact original content!
        target = mock_server / rel_p
        assert target.exists(), f"Protected file {rel_p} was DELETED!"
        assert target.read_text(encoding="utf-8") == files_to_verify[rel_p], f"Protected file {rel_p} was corrupted!"

    # User custom config must remain completely intact
    assert user_cfg.exists(), "User custom config was deleted!"
    assert '{"pvp": false, "custom": true}' in user_cfg.read_text(encoding="utf-8")


def test_stress_path_traversal_attempts_in_candidates(mock_server: Path):
    """
    Adversarial test:
    Malicious previous_meta containing path traversal attacks (e.g. ../../etc/passwd).
    Verify they are safely rejected and no exceptions are raised.
    """
    staging_dir = mock_server / "_staging_traversal"
    staging_dir.mkdir(parents=True, exist_ok=True)

    malicious_entries = [
        "../../etc/shadow",
        "..\\..\\windows\\system32\\calc.exe",
        "/absolute/path/override.txt",
        "mods/../../outside_server_file.txt",
        "world/../escaped.txt",
    ]

    res = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging_dir,
        previous_meta={"installed_files": malicious_entries},
    )
    assert res["mods_cleaned"] == []
    assert res["files_removed"] == []


# ============================================================================
# 4. Post-Update Client Mod Filtering & Whitelist Preservation
# ============================================================================

def test_stress_post_update_client_mod_filtering_and_allowlist(mock_server: Path, client, monkeypatch):
    """
    Complex stress scenario:
    1. appleskin (client-only): pattern 'appleskin*' active -> PRESERVED in mods/
    2. sodium-extra (client-only): pattern 'sodium-*' active -> PRESERVED in mods/
    3. iris (client-only): pattern 'iris*' INACTIVE -> FILTERED to mods-disabled-client/
    4. dynamicfps (client-only): NOT on allowlist -> FILTERED to mods-disabled-client/
    5. fabric-api (server-compatible): -> KEPT in mods/
    6. [1.20.1]zoomify-2.1.jar (special characters / brackets): pattern '[1.20.1]zoomify*' active -> PRESERVED in mods/
    """
    # Configure allowlist
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin", status="active")
    add_to_allowlist(mock_server, pattern="sodium-*", mod_name="Sodium Extra", status="active")
    add_to_allowlist(mock_server, pattern="iris*", mod_name="Iris Shaders", status="inactive")  # INACTIVE!
    add_to_allowlist(mock_server, pattern="[1.20.1]zoomify*", mod_name="Zoomify", status="active")

    save_server_modpack_info(
        "ChallengerTestServer",
        {"provider": "modrinth", "pack_id": "test-filter-pack", "version_id": "v1.0", "installed_files": []},
    )

    # v2 delivers the mix of mods
    mrpack_bytes = create_mock_mrpack_bytes(
        [
            ("appleskin-fabric-mc1.20.1-2.5.1.jar", "appleskin", "2.5.1", "client"),
            ("sodium-extra-0.5.1.jar", "sodium-extra", "0.5.1", "client"),
            ("iris-fabric-1.6.4.jar", "iris", "1.6.4", "client"),
            ("dynamic-fps-3.2.0.jar", "dynamicfps", "3.2.0", "client"),
            ("fabric-api-0.92.0.jar", "fabric-api", "0.92.0", "*"),
            ("[1.20.1]zoomify-2.1.jar", "zoomify", "2.1.0", "client"),
        ]
    )
    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0",
            "name": "2.0.0",
            "files": [{"filename": "pack.mrpack", "url": "https://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/ChallengerTestServer/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200, res.text
    data = res.json()

    filtered = data["client_mods_filtered"]

    # Filtered mods (unwhitelisted or inactive whitelist)
    assert "iris-fabric-1.6.4.jar" in filtered, "Inactive allowlist mod should be filtered!"
    assert "dynamic-fps-3.2.0.jar" in filtered, "Unwhitelisted client mod should be filtered!"

    # Preserved mods (active whitelist or server-compatible)
    assert "appleskin-fabric-mc1.20.1-2.5.1.jar" not in filtered
    assert "sodium-extra-0.5.1.jar" not in filtered
    assert "[1.20.1]zoomify-2.1.jar" not in filtered
    assert "fabric-api-0.92.0.jar" not in filtered

    # Verify physical file locations
    mods_dir = mock_server / "mods"
    disabled_dir = mock_server / "mods-disabled-client"

    assert (mods_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar").exists(), "Whitelisted appleskin must be in mods/!"
    assert (mods_dir / "sodium-extra-0.5.1.jar").exists(), "Whitelisted sodium-extra must be in mods/!"
    assert (mods_dir / "[1.20.1]zoomify-2.1.jar").exists(), "Whitelisted zoomify must be in mods/!"
    assert (mods_dir / "fabric-api-0.92.0.jar").exists(), "Fabric API must be in mods/!"

    assert (disabled_dir / "iris-fabric-1.6.4.jar").exists(), "Iris must be quarantined in mods-disabled-client/!"
    assert (disabled_dir / "dynamic-fps-3.2.0.jar").exists(), "Dynamic FPS must be in mods-disabled-client/!"
    assert not (mods_dir / "iris-fabric-1.6.4.jar").exists()
    assert not (mods_dir / "dynamic-fps-3.2.0.jar").exists()


# ============================================================================
# 5. Backup Failure & Error Handling
# ============================================================================

def test_stress_backup_failure_aborts_update(mock_server: Path, client, monkeypatch):
    """
    When pre-update safety backup fails (e.g. disk full),
    the update endpoint MUST abort immediately with HTTP 500,
    leaving the server files and metadata 100% untouched.
    """
    orig_jar = make_dummy_jar(mock_server / "mods" / "orig-1.0.jar", mod_id="orig")
    save_server_modpack_info(
        "ChallengerTestServer",
        {"provider": "modrinth", "pack_id": "pack-bk-fail", "version_id": "v1.0", "installed_files": ["mods/orig-1.0.jar"]},
    )

    import backup_manager
    async def broken_backup(*a, **kw):
        raise OSError("Simulated disk full during backup")
    monkeypatch.setattr(backup_manager, "create_backup_async", broken_backup)

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {"id": "v2.0", "name": "2.0.0", "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack"}]}
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/ChallengerTestServer/update",
        json={"target_version_id": "v2.0", "create_backup": True},
        headers=admin_h,
    )
    assert res.status_code == 500
    assert "Safety backup failed before update" in res.json()["detail"]

    # Invariant: Server must remain completely unchanged
    assert orig_jar.exists(), "Original mod jar was deleted despite backup failure!"
    meta = get_server_modpack_info("ChallengerTestServer")
    assert meta["version_id"] == "v1.0", "Metadata was modified despite update failure!"


def test_stress_corrupted_jar_in_mods_directory(mock_server: Path):
    """
    Server directory contains a 0-byte corrupt jar or arbitrary binary junk.
    reconcile_and_cleanup_modpack must NOT crash with BadZipFile.
    """
    mods_dir = mock_server / "mods"
    corrupt_jar = mods_dir / "corrupted_mod.jar"
    corrupt_jar.write_bytes(b"\x00\x01\x02\x03\xff\xfeNotAZipFile")

    staging_dir = mock_server / "_staging_corrupt"
    staging_mods = staging_dir / "mods"
    make_dummy_jar(staging_mods / "valid_mod-1.0.jar", mod_id="validmod")

    # Should run cleanly without uncaught exception
    res = reconcile_and_cleanup_modpack(
        server_dir=mock_server,
        staging_dir=staging_dir,
        previous_meta=None,
    )
    assert corrupt_jar.exists()  # Corrupt jar remains unless tracked in previous_meta
    assert res is not None
