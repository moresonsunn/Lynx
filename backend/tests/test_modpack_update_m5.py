"""Comprehensive Test Suite for Milestone 5:
Modpack Update Incremental Sync, Modloader Migration & Dynamic World/Config Preservation.
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import requests
import tempfile

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-modpack-update-m5-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_m5"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_m5.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

from client_mod_filter import add_to_allowlist, is_mod_allowlisted
from mod_side_resolver import ModSideResolver, inspect_jar_metadata
import modpack_routes
from modpack_routes import (
    _get_server_level_name,
    get_server_level_name,
    is_world_path,
    is_path_protected,
    clean_obsolete_loader_artifacts,
    _infer_java_version,
    _index_local_server_mods,
    _stage_modpack_version,
    reconcile_and_cleanup_modpack,
    get_server_modpack_info,
    save_server_modpack_info,
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
    loader_version: str = "0.15.11",
) -> bytes:
    """Builds a real in-memory .mrpack archive with overrides and index."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        deps = {"minecraft": mc_version}
        if loader == "neoforge":
            deps["neoforge"] = loader_version
        elif loader == "forge":
            deps["forge"] = loader_version
        else:
            deps["fabric-loader"] = loader_version

        index_data = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": "v2.0",
            "name": "Test Pack 2.0",
            "dependencies": deps,
            "files": [],
        }

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
            jar_bytes = jar_buf.getvalue()
            sha1_hash = hashlib.sha1(jar_bytes).hexdigest()
            sha512_hash = hashlib.sha512(jar_bytes).hexdigest()

            index_data["files"].append({
                "path": f"mods/{fname}",
                "hashes": {"sha1": sha1_hash, "sha512": sha512_hash},
                "env": {"client": "required" if env == "client" else "optional", "server": "unsupported" if env == "client" else "required"},
                "downloads": [f"http://example.com/dl/{fname}"],
                "fileSize": len(jar_bytes),
            })

        zf.writestr("modrinth.index.json", json.dumps(index_data, indent=2))

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
def m5_server(tmp_path: Path, monkeypatch) -> Path:
    """Prepares a clean mock server directory under modpack_routes.SERVERS_ROOT."""
    servers_root = tmp_path / "servers"
    servers_root.mkdir(parents=True, exist_ok=True)
    server_dir = servers_root / "M5Server"
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
# Task 1 Tests: Dynamic World & Protected Path Invariants
# ============================================================================

def test_dynamic_level_name_resolution(tmp_path: Path):
    """Verifies that _get_server_level_name dynamically reads level-name with fallback."""
    srv = tmp_path / "srv1"
    srv.mkdir()

    # Fallback when server.properties missing
    assert _get_server_level_name(srv) == "world"
    assert get_server_level_name(srv) == "world"
    assert _get_server_level_name(None) == "world"

    # Exact level-name
    (srv / "server.properties").write_text("difficulty=hard\nlevel-name=custom_realm\ngamemode=survival\n", encoding="utf-8")
    assert _get_server_level_name(srv) == "custom_realm"

    # Quotes and spaces
    (srv / "server.properties").write_text('level-name = "Sky Block 2" \n', encoding="utf-8")
    assert _get_server_level_name(srv) == "Sky Block 2"

    # Empty value fallback
    (srv / "server.properties").write_text("level-name=\n", encoding="utf-8")
    assert _get_server_level_name(srv) == "world"


def test_dynamic_protected_paths_evaluation(tmp_path: Path):
    """Verifies is_path_protected protects custom worlds, standard worlds, configs, and wildcards."""
    srv = tmp_path / "srv2"
    srv.mkdir()
    (srv / "server.properties").write_text("level-name=space_quest\n", encoding="utf-8")

    # Dynamic custom world protection
    assert is_path_protected("space_quest/level.dat", server_dir=srv) is True
    assert is_path_protected("space_quest/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("space_quest_nether/DIM-1/data.dat", server_dir=srv) is True
    assert is_path_protected("space_quest_the_end/DIM1/data.dat", server_dir=srv) is True

    # Standard world folders & saves/
    assert is_path_protected("world/level.dat", server_dir=srv) is True
    assert is_path_protected("world_nether/DIM-1", server_dir=srv) is True
    assert is_path_protected("world2/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("world_custom/level.dat", server_dir=srv) is True
    assert is_path_protected("saves/adventure1/level.dat", server_dir=srv) is True

    # Critical system & configuration files
    assert is_path_protected("server.properties", server_dir=srv) is True
    assert is_path_protected("user_jvm_args.txt", server_dir=srv) is True
    assert is_path_protected("mc-multicore-agent.jar", server_dir=srv) is True
    assert is_path_protected("server_meta.json", server_dir=srv) is True
    assert is_path_protected("modpack.meta.json", server_dir=srv) is True
    assert is_path_protected(".mod_side_report.json", server_dir=srv) is True
    assert is_path_protected("whitelist.json", server_dir=srv) is True
    assert is_path_protected("ops.json", server_dir=srv) is True

    # Wildcards
    assert is_path_protected("banned-ips.json", server_dir=srv) is True
    assert is_path_protected("banned-custom.json", server_dir=srv) is True
    assert is_path_protected("client-only-allow.json", server_dir=srv) is True
    assert is_path_protected("client-only-allow.yaml", server_dir=srv) is True
    assert is_path_protected("client-only-allow.yml", server_dir=srv) is True

    # Logs, backups, crash-reports
    assert is_path_protected("logs/latest.log", server_dir=srv) is True
    assert is_path_protected("backups/2026-world.zip", server_dir=srv) is True
    assert is_path_protected("crash-reports/crash-1.txt", server_dir=srv) is True

    # Mod files & ordinary configs are NOT protected (they should be updatable)
    assert is_path_protected("mods/jei.jar", server_dir=srv) is False
    assert is_path_protected("config/jei.ini", server_dir=srv) is False


def test_staging_copy_immutability_guard(m5_server: Path, client, monkeypatch):
    """
    CRITICAL INVARIANT TEST:
    Verifies that staged files can NEVER overwrite live server world data, server.properties,
    user_jvm_args.txt, or ops.json during update_server_modpack.
    """
    # Setup live server with custom level-name and specific configs
    (m5_server / "server.properties").write_text("server-port=25577\nlevel-name=quest_world\n", encoding="utf-8")
    (m5_server / "user_jvm_args.txt").write_text("-Xmx8G -XX:+UseG1GC # LIVE_CONFIG\n", encoding="utf-8")
    (m5_server / "ops.json").write_text('[{"uuid": "live-admin"}]', encoding="utf-8")

    live_world = m5_server / "quest_world"
    live_world.mkdir(parents=True, exist_ok=True)
    (live_world / "level.dat").write_bytes(b"LIVE_SACRED_PLAYER_WORLD_DATA")

    save_server_modpack_info(
        "M5Server",
        {
            "provider": "modrinth",
            "pack_id": "pack-inv",
            "version_id": "v1.0",
            "installed_files": [],
        },
    )

    # Staged pack maliciously/accidentally includes overrides for server.properties, quest_world, world, and user_jvm_args
    overrides = {
        "server.properties": "server-port=25565\nlevel-name=default_world\n",
        "user_jvm_args.txt": "-Xmx2G # OVERWRITE_ATTEMPT\n",
        "ops.json": "[]",
        "quest_world/level.dat": "CORRUPTED_OVERWRITE_WORLD_DATA",
        "world/level.dat": "BUNDLED_STARTER_MAP_WORLD_DATA",
    }
    mrpack_bytes = create_mock_mrpack_bytes(
        mods=[("valid-mod-1.0.jar", "validmod", "1.0.0", "*")],
        overrides_files=overrides,
    )

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
        "/api/modpacks/server/M5Server/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # ASSERTIONS: Live world, server.properties, and ops are completely preserved
    assert (live_world / "level.dat").read_bytes() == b"LIVE_SACRED_PLAYER_WORLD_DATA"
    assert "server-port=25577" in (m5_server / "server.properties").read_text(encoding="utf-8")
    assert "live-admin" in (m5_server / "ops.json").read_text(encoding="utf-8")
    # Bundled world/ should NOT be injected into the server directory
    assert not (m5_server / "world" / "level.dat").exists()
    # The new mod was properly installed
    assert (m5_server / "mods" / "valid-mod-1.0.jar").exists()


# ============================================================================
# Task 2 Tests: Incremental Mod Diffing & Zero Re-download Verification
# ============================================================================

def test_incremental_mod_diff_reuses_local_jars_without_download(tmp_path: Path):
    """
    Verifies that _stage_modpack_version reuses unchanged mods from server_dir/mods
    and server_dir/mods-disabled-client by hash/size without performing remote HTTP downloads.
    """
    srv = tmp_path / "srv_inc"
    srv.mkdir()
    mods_d = srv / "mods"
    disabled_d = srv / "mods-disabled-client"
    mods_d.mkdir()
    disabled_d.mkdir()

    # Local mod A in mods/
    mod_a = make_dummy_jar(mods_d / "mod-alpha-1.0.jar", mod_id="alpha", version="1.0.0")
    # Local mod B in mods-disabled-client/
    mod_b = make_dummy_jar(disabled_d / "mod-beta-1.0.jar", mod_id="beta", version="1.0.0")

    # Index local server mods
    index = _index_local_server_mods(srv)
    sha1_a = hashlib.sha1(mod_a.read_bytes()).hexdigest().lower()
    sha1_b = hashlib.sha1(mod_b.read_bytes()).hexdigest().lower()

    assert sha1_a in index["by_sha1"]
    assert sha1_b in index["by_sha1"]

    # Target modpack specifies mod-alpha (unchanged), mod-beta (unchanged, previously quarantined),
    # and mod-gamma (brand new, needs download)
    gamma_buf = io.BytesIO()
    with zipfile.ZipFile(gamma_buf, "w") as gz:
        gz.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "gamma", "version": "1.0.0"}))
    gamma_bytes = gamma_buf.getvalue()

    mrpack_bytes = create_mock_mrpack_bytes([
        ("mod-alpha-1.0.jar", "alpha", "1.0.0", "*"),
        ("mod-beta-1.0.jar", "beta", "1.0.0", "*"),
        ("mod-gamma-1.0.jar", "gamma", "1.0.0", "*"),
    ])

    staging_dir = tmp_path / "staging_inc"
    tmpdir = tmp_path / "tmp_inc"
    staging_dir.mkdir()
    tmpdir.mkdir()

    target_ver_obj = {
        "id": "v2.0",
        "loaders": ["fabric"],
        "game_versions": ["1.20.1"],
        "files": [{"filename": "pack.mrpack", "url": "http://example.com/pack.mrpack"}],
    }

    downloaded_urls = []
    def fake_download_to(dest_file, url, timeout=120):
        downloaded_urls.append(url)
        if "mod-gamma" in url:
            dest_file.write_bytes(gamma_bytes)
        else:
            dest_file.write_bytes(b"DOWNLOADED_DATA")

    with patch("requests.get", return_value=MockHttpResponse(mrpack_bytes)):
        with patch("modpack_routes._download_to", side_effect=fake_download_to):
            result = _stage_modpack_version(
                provider_id="modrinth",
                provider=MagicMock(),
                pack_id="test-pack",
                target_version_obj=target_ver_obj,
                staging_dir=staging_dir,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    # ASSERTIONS:
    # 2 mods (alpha and beta) were reused locally!
    assert result["reused_mods_count"] == 2
    # Only mod-gamma was downloaded remotely!
    assert len(downloaded_urls) == 1
    assert "mod-gamma" in downloaded_urls[0]

    # Staging contains all 3 valid mods
    assert (staging_dir / "mods" / "mod-alpha-1.0.jar").exists()
    assert (staging_dir / "mods" / "mod-beta-1.0.jar").exists()
    assert (staging_dir / "mods" / "mod-gamma-1.0.jar").exists()
    # Content of reused files matches local files exactly
    assert (staging_dir / "mods" / "mod-alpha-1.0.jar").read_bytes() == mod_a.read_bytes()
    assert (staging_dir / "mods" / "mod-beta-1.0.jar").read_bytes() == mod_b.read_bytes()


# ============================================================================
# Task 3 Tests: Stale Mod Cleanup Enhancements
# ============================================================================

def test_stale_cleanup_recovers_from_mod_side_report(tmp_path: Path):
    """
    When previous_meta has empty installed_files, reconcile_and_cleanup_modpack
    recovers previously installed mods from .mod_side_report.json and prunes them.
    """
    srv = tmp_path / "srv_rep"
    srv.mkdir()
    mods_d = srv / "mods"
    mods_d.mkdir()

    old_mod = make_dummy_jar(mods_d / "dropped-mod-1.0.jar", mod_id="droppedmod")
    retained_mod = make_dummy_jar(mods_d / "retained-mod-1.0.jar", mod_id="retained")

    # .mod_side_report.json tracks both mods
    side_report = {
        "kept_mods": [{"file_name": "dropped-mod-1.0.jar"}, {"file_name": "retained-mod-1.0.jar"}],
        "excluded_mods": [],
    }
    (srv / ".mod_side_report.json").write_text(json.dumps(side_report), encoding="utf-8")

    staging = tmp_path / "staging_rep"
    staging_mods = staging / "mods"
    staging_mods.mkdir(parents=True)
    make_dummy_jar(staging_mods / "retained-mod-1.0.jar", mod_id="retained")
    make_dummy_jar(staging_mods / "brand-new-1.0.jar", mod_id="brandnew")

    # Call with empty installed_files in previous_meta
    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={"provider": "modrinth", "pack_id": "test", "installed_files": []},
    )

    # ASSERTIONS:
    assert "dropped-mod-1.0.jar" in res["mods_cleaned"]
    assert not old_mod.exists()
    assert retained_mod.exists()


def test_stale_cleanup_recovers_from_server_meta_json(tmp_path: Path):
    """
    When previous_meta is None, reconcile_and_cleanup_modpack recovers
    installed_files from server_meta.json and prunes removed mods.
    """
    srv = tmp_path / "srv_sm"
    srv.mkdir()
    mods_d = srv / "mods"
    mods_d.mkdir()

    legacy_mod = make_dummy_jar(mods_d / "legacy-mod-1.0.jar", mod_id="legacymod")

    server_meta = {
        "server_type": "fabric",
        "version": "1.20.1",
        "installed_files": ["mods/legacy-mod-1.0.jar"],
    }
    (srv / "server_meta.json").write_text(json.dumps(server_meta), encoding="utf-8")

    staging = tmp_path / "staging_sm"
    staging_mods = staging / "mods"
    staging_mods.mkdir(parents=True)
    make_dummy_jar(staging_mods / "current-mod-1.0.jar", mod_id="current")

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta=None,
    )

    assert "legacy-mod-1.0.jar" in res["mods_cleaned"]
    assert not legacy_mod.exists()


def test_stale_cleanup_unlinks_quarantine_duplicate_when_mod_staged(tmp_path: Path):
    """
    When incoming staging has a mod that exists in mods-disabled-client/,
    the quarantine copy is unlinked so duplicate copies do not persist.
    """
    srv = tmp_path / "srv_quar"
    srv.mkdir()
    dis_d = srv / "mods-disabled-client"
    dis_d.mkdir()

    quarantined = make_dummy_jar(dis_d / "voice-chat-fabric-1.0.jar", mod_id="voicechat")

    staging = tmp_path / "staging_quar"
    staging_mods = staging / "mods"
    staging_mods.mkdir(parents=True)
    make_dummy_jar(staging_mods / "voice-chat-fabric-1.0.jar", mod_id="voicechat")

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={"installed_files": []},
    )

    assert "voice-chat-fabric-1.0.jar" in res["mods_cleaned"]
    assert not quarantined.exists()


def test_stale_cleanup_respects_client_only_allowlist(tmp_path: Path):
    """
    Allowlisted client mods are NEVER deleted during modpack cleanup even if dropped from pack.
    """
    srv = tmp_path / "srv_al"
    srv.mkdir()
    mods_d = srv / "mods"
    mods_d.mkdir()

    custom_mod = make_dummy_jar(mods_d / "my-custom-hud-1.0.jar", mod_id="customhud")
    add_to_allowlist(srv, pattern="*custom-hud*", mod_name="Custom HUD")

    staging = tmp_path / "staging_al"
    staging.mkdir()

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={"installed_files": ["mods/my-custom-hud-1.0.jar"]},
    )

    assert "my-custom-hud-1.0.jar" not in res["mods_cleaned"]
    assert custom_mod.exists()


# ============================================================================
# Task 4 Tests: Modloader & Minecraft Version Migration
# ============================================================================

def test_clean_obsolete_loader_artifacts_forge_to_neoforge(tmp_path: Path):
    """
    clean_obsolete_loader_artifacts purges old Forge run scripts and libraries
    while leaving worlds and configs untouched.
    """
    srv = tmp_path / "srv_forge"
    srv.mkdir()

    # Old Forge artifacts
    (srv / "forge-1.20.1-47.2.0.jar").write_bytes(b"FORGE_BIN")
    (srv / "run.sh").write_text("#!/bin/sh\nrun forge", encoding="utf-8")
    (srv / "run.bat").write_text("@echo off\nrun forge", encoding="utf-8")
    (srv / "win_args.txt").write_text("-cp forge.jar", encoding="utf-8")

    forge_lib = srv / "libraries" / "net" / "minecraftforge"
    forge_lib.mkdir(parents=True, exist_ok=True)
    (forge_lib / "dummy.jar").write_bytes(b"LIB")

    # Sacred world and configs
    (srv / "world").mkdir()
    (srv / "world" / "level.dat").write_bytes(b"SACRED_WORLD")
    (srv / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    cleaned = clean_obsolete_loader_artifacts(
        server_dir=srv,
        current_loader="forge",
        target_loader="neoforge",
        mc_version_changed=True,
    )

    # Obsolete artifacts cleaned
    assert "run.sh" in cleaned
    assert "forge-1.20.1-47.2.0.jar" in cleaned
    assert "libraries/net/minecraftforge" in cleaned
    assert not (srv / "run.sh").exists()
    assert not (srv / "forge-1.20.1-47.2.0.jar").exists()
    assert not forge_lib.exists()

    # World and config intact
    assert (srv / "world" / "level.dat").read_bytes() == b"SACRED_WORLD"
    assert (srv / "server.properties").exists()


def test_infer_java_version_matrix():
    """Verifies Java version inference across loaders and MC versions."""
    # Forge rules
    assert _infer_java_version(None, "forge", "1.12.2") == 8
    assert _infer_java_version(None, "forge", "1.16.5") == 8
    assert _infer_java_version(None, "forge", "1.20.1") == 17
    assert _infer_java_version(None, "forge", "1.20.6") == 21
    assert _infer_java_version(None, "forge", "1.21.1") == 21

    # NeoForge rules
    assert _infer_java_version(None, "neoforge", "1.20.4") == 17
    assert _infer_java_version(None, "neoforge", "20.4.253") == 17
    assert _infer_java_version(None, "neoforge", "1.20.6") == 21
    assert _infer_java_version(None, "neoforge", "1.21.1") == 21
    assert _infer_java_version(None, "neoforge", "21.1.266") == 21

    # Fabric / Vanilla rules
    assert _infer_java_version(None, "fabric", "1.16.5") == 8
    assert _infer_java_version(None, "fabric", "1.18.2") == 17
    assert _infer_java_version(None, "fabric", "1.20.1") == 17
    assert _infer_java_version(None, "fabric", "1.21.1") == 21


def test_modloader_migration_forge_to_neoforge_e2e(m5_server: Path, client, monkeypatch):
    """
    E2E migration test: Forge 1.20.1 -> NeoForge 1.20.4.
    Verifies old loader cleanup, installer provisioning, server_meta.json sync,
    Multi-Core user_jvm_args.txt generation, and world preservation.
    """
    # 1. Initial Forge 1.20.1 server setup
    (m5_server / "forge-1.20.1-47.2.0.jar").write_bytes(b"OLD_FORGE_BIN")
    (m5_server / "run.sh").write_text("#!/bin/sh\nrun old forge", encoding="utf-8")
    (m5_server / "server.properties").write_text("level-name=world\nserver-port=25565\n", encoding="utf-8")

    world_d = m5_server / "world"
    world_d.mkdir()
    (world_d / "level.dat").write_bytes(b"SACRED_SURVIVAL_WORLD")

    save_server_modpack_info(
        "M5Server",
        {
            "provider": "modrinth",
            "pack_id": "pack-mig",
            "version_id": "v1.0",
            "loader": "forge",
            "loader_version": "47.2.0",
            "minecraft_version": "1.20.1",
            "installed_files": [],
        },
    )

    (m5_server / "server_meta.json").write_text(json.dumps({
        "server_type": "forge",
        "mc_type": "forge",
        "version": "1.20.1",
        "java_version": "17",
        "cpu_cores": 4,
        "max_ram_mb": 4096,
    }), encoding="utf-8")

    # 2. Target version specifies NeoForge 1.20.4
    mrpack_bytes = create_mock_mrpack_bytes(
        mods=[("neoforge-mod-1.0.jar", "neomod", "1.0.0", "*")],
        mc_version="1.20.4",
        loader="neoforge",
        loader_version="20.4.253",
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0",
            "name": "NeoForge 2.0.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    # Spy and intercept installer jar download
    def fake_download_to(dest_file, url, timeout=120):
        dest_file.write_bytes(b"NEOFORGE_INSTALLER_JAR")

    monkeypatch.setattr(modpack_routes, "_download_to", fake_download_to)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/M5Server/update",
        json={"target_version_id": "v2.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    # ASSERTIONS:
    assert data["status"] == "success"
    assert data["loader_migrated"] is True
    assert data["loader"] == "neoforge"
    assert data["minecraft_version"] == "1.20.4"
    assert data["mc_version_changed"] is True

    # Old Forge binary and run script are removed
    assert not (m5_server / "forge-1.20.1-47.2.0.jar").exists()
    assert not (m5_server / "run.sh").exists()

    # NeoForge installer provisioned
    assert (m5_server / "neoforge-20.4.253-installer.jar").exists()

    # server_meta.json updated accurately
    sm = json.loads((m5_server / "server_meta.json").read_text(encoding="utf-8"))
    assert sm["server_type"] == "neoforge"
    assert sm["mc_version"] == "1.20.4"
    assert sm["loader_version"] == "20.4.253"
    assert sm["java_version"] == "17"

    # Multi-Core configuration user_jvm_args.txt regenerated
    assert (m5_server / "user_jvm_args.txt").exists()

    # Sacred world intact!
    assert (world_d / "level.dat").read_bytes() == b"SACRED_SURVIVAL_WORLD"


def test_modloader_migration_neoforge_to_fabric_java21_e2e(m5_server: Path, client, monkeypatch):
    """
    E2E migration test: NeoForge 1.20.4 -> Fabric 1.21.1 (Java 17 -> Java 21).
    Verifies Java 21 inference, multicore Generational ZGC profile update,
    and server_meta.json synchronization.
    """
    (m5_server / "neoforge-20.4.253-installer.jar").write_bytes(b"NEO_INSTALLER")
    (m5_server / "run.sh").write_text("#!/bin/sh\nrun neoforge", encoding="utf-8")
    (m5_server / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    world_d = m5_server / "world"
    world_d.mkdir()
    (world_d / "level.dat").write_bytes(b"WORLD_LEVEL_DATA")

    save_server_modpack_info(
        "M5Server",
        {
            "provider": "modrinth",
            "pack_id": "pack-mig2",
            "version_id": "v1.0",
            "loader": "neoforge",
            "loader_version": "20.4.253",
            "minecraft_version": "1.20.4",
            "installed_files": [],
        },
    )

    (m5_server / "server_meta.json").write_text(json.dumps({
        "server_type": "neoforge",
        "mc_type": "neoforge",
        "version": "1.20.4",
        "java_version": "17",
        "cpu_cores": 8,
        "max_ram_mb": 8192,
    }), encoding="utf-8")

    mrpack_bytes = create_mock_mrpack_bytes(
        mods=[("fabric-mod-1.0.jar", "fabricmod", "1.0.0", "*")],
        mc_version="1.21.1",
        loader="fabric",
        loader_version="0.16.5",
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v3.0",
            "name": "Fabric 3.0.0",
            "files": [{"filename": "p.mrpack", "url": "http://example.com/p.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    def fake_download_to(dest_file, url, timeout=120):
        dest_file.write_bytes(b"FABRIC_SERVER_JAR")

    monkeypatch.setattr(modpack_routes, "_download_to", fake_download_to)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/M5Server/update",
        json={"target_version_id": "v3.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200
    data = res.json()

    assert data["loader_migrated"] is True
    assert data["loader"] == "fabric"
    assert data["minecraft_version"] == "1.21.1"

    # Old NeoForge installer removed
    assert not (m5_server / "neoforge-20.4.253-installer.jar").exists()

    # server_meta.json updated with Java 21 for MC 1.21.1
    sm = json.loads((m5_server / "server_meta.json").read_text(encoding="utf-8"))
    assert sm["server_type"] == "fabric"
    assert sm["mc_version"] == "1.21.1"
    assert sm["java_version"] == "21"

    # World intact
    assert (world_d / "level.dat").read_bytes() == b"WORLD_LEVEL_DATA"


# ============================================================================
# Task 5 Tests: Version Query API Loader Exposure
# ============================================================================

def test_versions_api_exposes_current_loader_and_mc(m5_server: Path, client):
    """
    GET /api/modpacks/server/{name}/versions returns current_loader,
    current_loader_version, and current_minecraft_version for frontend modal.
    """
    save_server_modpack_info(
        "M5Server",
        {
            "provider": "modrinth",
            "pack_id": "pack-meta",
            "version_id": "v1.0",
            "version_name": "1.0.0",
            "loader": "neoforge",
            "loader_version": "20.4.253",
            "minecraft_version": "1.20.4",
            "installed_files": [],
        },
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {"id": "v1.0", "name": "1.0.0", "game_versions": ["1.20.4"], "loaders": ["neoforge"]},
        {"id": "v2.0", "name": "2.0.0", "game_versions": ["1.21.1"], "loaders": ["fabric"]},
    ]
    with patch("catalog_routes.get_providers_live", return_value={"modrinth": mock_provider}):
        admin_h = _login(client, "admin", "AdminPass123")
        res = client.get("/api/modpacks/server/M5Server/versions", headers=admin_h)

    assert res.status_code == 200
    data = res.json()
    assert data["current_loader"] == "neoforge"
    assert data["current_loader_version"] == "20.4.253"
    assert data["current_minecraft_version"] == "1.20.4"
    assert len(data["versions"]) == 2


# ============================================================================
# Task 6 Tests: Fabric 3-Segment URL + Full Mod/Override Replacement & Missing server.jar
# ============================================================================

def test_ensure_server_jar_fabric_uses_installer_segment_and_creates_server_jar(tmp_path: Path, monkeypatch):
    """Regression (Cobbleverse 1.8.0): Fabric requires /{mc}/{lver}/{installer}/server/jar and server.jar alias."""
    srv = tmp_path / "cobbleverse_srv"
    srv.mkdir()

    requested_urls = []

    def fake_get(url, *args, **kwargs):
        requested_urls.append(url)
        if url.endswith("/versions/loader/1.21.1"):
            return MockHttpResponse(json.dumps([{"loader": {"version": "0.16.10", "stable": True}}]).encode("utf-8"))
        if url.endswith("/versions/installer"):
            return MockHttpResponse(json.dumps([{"version": "1.0.3", "stable": True}]).encode("utf-8"))
        raise AssertionError(f"Unexpected requests.get URL: {url}")

    downloaded = []

    def fake_dl(dest_file, url, timeout=180):
        downloaded.append((Path(dest_file), url))
        Path(dest_file).write_bytes(b"VALID_FABRIC_SERVER_JAR")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(modpack_routes, "_download_to", fake_dl)

    modpack_routes._ensure_server_jar(srv, loader="fabric", mc_version="1.21.1", loader_version=None)

    assert len(downloaded) == 1
    assert downloaded[0][1] == "https://meta.fabricmc.net/v2/versions/loader/1.21.1/0.16.10/1.0.3/server/jar"
    assert (srv / "fabric-server-mc.1.21.1-loader.0.16.10.jar").is_file()
    assert (srv / "server.jar").is_file()
    assert (srv / "server.jar").read_bytes() == b"VALID_FABRIC_SERVER_JAR"
    assert (srv / "fabric-server-launch.jar").is_file()


def test_update_modpack_replaces_mods_with_partial_report_wrapped_overrides_and_missing_server_jar(
    m5_server: Path, client, monkeypatch
):
    """
    Update replaces dropped/updated mods even when old_files only has partial .mod_side_report.json,
    merges wrapped PackName/overrides and PackName/server-overrides, keeps world/level.dat,
    and provisions missing server.jar even on same loader + MC version.
    """
    world_dat = m5_server / "world" / "level.dat"
    world_dat.parent.mkdir(parents=True, exist_ok=True)
    world_dat.write_bytes(b"SACRED_COBBLEVERSE_WORLD")

    # Pre-existing partial state: server.jar missing, old mods in mods/, partial .mod_side_report.json
    old_only_in_dir = make_dummy_jar(m5_server / "mods" / "old-cobblemon-1.5.jar", mod_id="oldcobblemon", version="1.5")
    tracked_old = make_dummy_jar(m5_server / "mods" / "partial-tracked-1.0.jar", mod_id="partialmod", version="1.0")
    (m5_server / ".mod_side_report.json").write_text(
        json.dumps({"kept_mods": [{"file_name": "partial-tracked-1.0.jar"}], "excluded_mods": []}),
        encoding="utf-8",
    )

    save_server_modpack_info(
        "M5Server",
        {
            "provider": "modrinth",
            "pack_id": "cobbleverse",
            "version_id": "1.7.0",
            "version_name": "1.7.0",
            "loader": "fabric",
            "loader_version": "0.16.9",
            "minecraft_version": "1.21.1",
            "installed_files": [],
        },
    )

    # New version zip uses a wrapped top-level folder PackName/overrides/... and PackName/server-overrides/...
    new_mod_buf = io.BytesIO()
    with zipfile.ZipFile(new_mod_buf, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "newcobblemon", "version": "1.6.0"}))
    new_mod_bytes = new_mod_buf.getvalue()

    mr_index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.8.0",
        "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16.10"},
        "files": [
            {
                "path": "mods/cobblemon-1.6.0.jar",
                "hashes": {"sha1": hashlib.sha1(new_mod_bytes).hexdigest()},
                "downloads": ["http://example.com/cobblemon-1.6.0.jar"],
                "fileSize": len(new_mod_bytes),
            }
        ],
    }
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("Cobbleverse-1.8.0/modrinth.index.json", json.dumps(mr_index))
        zf.writestr("Cobbleverse-1.8.0/overrides/config/pack.toml", "source = 'overrides'\n")
        zf.writestr("Cobbleverse-1.8.0/server-overrides/config/pack.toml", "source = 'server-overrides'\n")
        zf.writestr("Cobbleverse-1.8.0/overrides/world/level.dat", b"MUST_NOT_OVERWRITE_WORLD")
    pack_bytes = zip_buf.getvalue()

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "1.8.0",
            "name": "Cobbleverse 1.8.0",
            "loaders": ["fabric"],
            "game_versions": ["1.21.1"],
            "files": [{"filename": "cobbleverse-1.8.0.mrpack", "url": "http://example.com/cobbleverse.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    def fake_get(url, *args, **kwargs):
        if "versions/installer" in url:
            return MockHttpResponse(json.dumps([{"version": "1.0.3", "stable": True}]).encode("utf-8"))
        return MockHttpResponse(pack_bytes)

    def fake_dl(dest_file, url, timeout=180):
        dest = Path(dest_file)
        if "meta.fabricmc.net" in url:
            dest.write_bytes(b"FABRIC_1_8_0_SERVER_JAR")
        else:
            dest.write_bytes(new_mod_bytes)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(modpack_routes, "_download_to", fake_dl)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/M5Server/update",
        json={"target_version_id": "1.8.0", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200, res.text
    data = res.json()

    # Old mods replaced even though old_files only listed partial-tracked-1.0.jar
    assert not old_only_in_dir.exists()
    assert not tracked_old.exists()
    assert (m5_server / "mods" / "cobblemon-1.6.0.jar").is_file()
    assert "old-cobblemon-1.5.jar" in data["mods_cleaned"]

    # Wrapped overrides merged cleanly and server-overrides took precedence
    cfg_file = m5_server / "config" / "pack.toml"
    assert cfg_file.is_file()
    assert "server-overrides" in cfg_file.read_text(encoding="utf-8")

    # Missing server.jar was downloaded cleanly
    assert (m5_server / "server.jar").is_file()
    assert (m5_server / "server.jar").read_bytes() == b"FABRIC_1_8_0_SERVER_JAR"

    # World was strictly preserved
    assert world_dat.read_bytes() == b"SACRED_COBBLEVERSE_WORLD"
