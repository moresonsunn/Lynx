"""Empirical Adversarial Test Suite for Milestone 5 (Instance 2):
Focus Areas:
1. Hostile Modpack Staging Attack: Bundled worlds, conflicting configs, malicious jvm args, attacker ops/bans
2. Dynamic level-name Resolution Matrix: Quotes, spaces, comments, UTF-8, dimension folders (_nether, _the_end)
3. Multi-Hop Loader Migration Lifecycle: Forge -> NeoForge -> Fabric -> Forge, launcher/library pruning, world/config preservation, multicore regeneration
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
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
import requests
import tempfile

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-modpack-challenger-m5-2-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_challenger_m5_2"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_challenger_m5_2.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

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


def create_adversarial_mrpack_bytes(
    mods: List[Tuple[str, str, str, str]],  # (filename, mod_id, version, environment)
    overrides_files: Optional[Dict[str, bytes]] = None,
    mc_version: str = "1.20.1",
    loader: str = "fabric",
    loader_version: str = "0.15.11",
) -> bytes:
    """Builds a real in-memory .mrpack archive with hostile overrides and index."""
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
            "versionId": "v_adv",
            "name": "Adversarial Test Pack",
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
def adv_server(tmp_path: Path, monkeypatch) -> Path:
    """Creates a temporary isolated server environment for adversarial testing."""
    servers_root = tmp_path / "servers_root"
    servers_root.mkdir()
    server_dir = servers_root / "AdvChallengerServer"
    server_dir.mkdir()
    (server_dir / "mods").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(modpack_routes, "SERVERS_ROOT", servers_root)
    import config
    monkeypatch.setattr(config, "SERVERS_ROOT", servers_root)
    import backup_manager
    monkeypatch.setattr(backup_manager, "SERVERS_ROOT", servers_root)
    monkeypatch.setattr(backup_manager, "DEFAULT_BACKUPS_ROOT", tmp_path / "backups")

    mock_dm = MagicMock()
    mock_dm.list_servers.return_value = [
        {"id": "c_adv", "name": "AdvChallengerServer", "status": "running"}
    ]
    mock_dm.stop_server.return_value = True
    mock_dm.start_server.return_value = True
    mock_dm.recreate_server_with_env.return_value = True

    monkeypatch.setattr(modpack_routes, "get_docker_manager", lambda: mock_dm)
    monkeypatch.setattr(modpack_routes, "get_runtime_manager_or_docker", lambda: mock_dm)

    return server_dir


# ============================================================================
# Adversarial Tests
# ============================================================================

def test_adv_hostile_staging_tree_world_and_config_preservation(adv_server: Path, client, monkeypatch):
    """
    CRITICAL ADVERSARIAL STAGING ATTACK:
    Constructs a malicious/hostile modpack staging archive containing conflicting configs,
    bundled destructive starter worlds, malicious jvm args, and attacker ops/bans.
    Verifies that update_server_modpack preserves 100% of live worlds, dimensions,
    player inventories, ops, bans, and multicore configurations.
    """
    # 1. Setup precious live server files
    live_props_content = (
        "# Live Production Minecraft Server Properties\n"
        "server-port=28999\n"
        'level-name = "Omega Kingdom" \n'
        "online-mode=true\n"
        "difficulty=hard\n"
        "motd=Precious Production Server\n"
    )
    (adv_server / "server.properties").write_text(live_props_content, encoding="utf-8")

    # Precious world files across Overworld, Nether, and The End
    overworld_dir = adv_server / "Omega Kingdom"
    (overworld_dir / "region").mkdir(parents=True)
    (overworld_dir / "playerdata").mkdir(parents=True)
    (overworld_dir / "poi").mkdir(parents=True)

    level_dat_bytes = b"PREVIOUS_SURVIVAL_LEVEL_DAT_HEADER_BYTE_CONTENT_123456789"
    region_mca_bytes = b"PREVIOUS_CHUNK_REGION_COORDINATES_0_0_MCA_PRECIOUS_DATA"
    player_dat_bytes = b"PLAYER_UUID_INVENTORY_NETHERITE_SWORD_DATA"
    poi_mca_bytes = b"VILLAGER_POI_RECORDS_DATA"

    (overworld_dir / "level.dat").write_bytes(level_dat_bytes)
    (overworld_dir / "region" / "r.0.0.mca").write_bytes(region_mca_bytes)
    (overworld_dir / "playerdata" / "player1.dat").write_bytes(player_dat_bytes)
    (overworld_dir / "poi" / "r.0.0.mca").write_bytes(poi_mca_bytes)

    # Nether & The End dimensions
    nether_dir = adv_server / "Omega Kingdom_nether" / "DIM-1"
    nether_dir.mkdir(parents=True)
    nether_mca_bytes = b"NETHER_FORTRESS_REGION_DATA"
    (nether_dir / "r.0.0.mca").write_bytes(nether_mca_bytes)

    end_dir = adv_server / "Omega Kingdom_the_end" / "DIM1"
    end_dir.mkdir(parents=True)
    end_mca_bytes = b"ENDER_DRAGON_FIGHT_DATA"
    (end_dir / "r.0.0.mca").write_bytes(end_mca_bytes)

    # Standard secondary world & saves
    secondary_world = adv_server / "world" / "region"
    secondary_world.mkdir(parents=True)
    world_mca_bytes = b"SECONDARY_STANDARD_WORLD_DATA"
    (secondary_world / "r.0.0.mca").write_bytes(world_mca_bytes)

    saves_dir = adv_server / "saves" / "custom_adventure"
    saves_dir.mkdir(parents=True)
    save_dat_bytes = b"SAVED_ADVENTURE_MAP_DATA"
    (saves_dir / "level.dat").write_bytes(save_dat_bytes)

    # Critical security configs
    ops_bytes = b'[{"uuid": "admin-1", "name": "SuperAdmin", "level": 4}]'
    bans_bytes = b'[{"uuid": "griefer-1", "name": "NaughtyUser", "reason": "TNT Griefing"}]'
    banned_ips_bytes = b'[{"ip": "198.51.100.1", "reason": "DDoS attempt"}]'
    whitelist_bytes = b'[{"uuid": "vip-1", "name": "VipPlayer"}]'
    eula_bytes = b"eula=true\n"
    allowlist_bytes = b'{"patterns": ["custom-client-hud*.jar"]}'
    user_jvm_bytes = b"# Original JVM Args\n-XX:+UseG1GC -Xms4G -Xmx4G\n"
    agent_bytes = b"PK_GENUINE_AGENT_BYTECODE_ORCHESTRATOR"

    (adv_server / "ops.json").write_bytes(ops_bytes)
    (adv_server / "banned-players.json").write_bytes(bans_bytes)
    (adv_server / "banned-ips.json").write_bytes(banned_ips_bytes)
    (adv_server / "whitelist.json").write_bytes(whitelist_bytes)
    (adv_server / "eula.txt").write_bytes(eula_bytes)
    (adv_server / "client-only-allow.json").write_bytes(allowlist_bytes)
    (adv_server / "user_jvm_args.txt").write_bytes(user_jvm_bytes)
    (adv_server / "mc-multicore-agent.jar").write_bytes(agent_bytes)

    # System directories: backups, logs, crash-reports
    (adv_server / "backups").mkdir(parents=True)
    (adv_server / "logs").mkdir(parents=True)
    (adv_server / "crash-reports").mkdir(parents=True)
    backup_safe_bytes = b"PRECIOUS_PRE_UPDATE_BACKUP_ZIP_PAYLOAD"
    (adv_server / "backups" / "safe_2026.zip").write_bytes(backup_safe_bytes)
    (adv_server / "logs" / "latest.log").write_text("[20:00:00] Server started safely", encoding="utf-8")
    (adv_server / "crash-reports" / "crash-1.txt").write_text("No crash", encoding="utf-8")

    # Initial metadata
    save_server_modpack_info(
        "AdvChallengerServer",
        {
            "provider": "modrinth",
            "pack_id": "adversarial-pack",
            "version_id": "v1.0",
            "loader": "fabric",
            "loader_version": "0.15.11",
            "minecraft_version": "1.20.1",
            "installed_files": [],
        },
    )
    (adv_server / "server_meta.json").write_text(json.dumps({
        "server_type": "fabric",
        "mc_type": "fabric",
        "version": "1.20.1",
        "java_version": "17",
        "cpu_cores": 4,
        "max_ram_mb": 4096,
        "multicore_enabled": True,
    }), encoding="utf-8")

    # 2. CONSTRUCT HOSTILE OVERRIDES IN MODPACK ARCHIVE
    hostile_overrides = {
        "server.properties": b"server-port=6666\nlevel-name=ATTACKER_OVERWRITE\ndifficulty=peaceful\nonline-mode=false\n",
        "world/level.dat": b"MALICIOUS_WIPED_WORLD_LEVEL_DAT",
        "world/region/r.0.0.mca": b"MALICIOUS_CORRUPTED_WORLD_CHUNKS",
        "Omega Kingdom/level.dat": b"ATTACKER_WIPED_OMEGA_KINGDOM_LEVEL_DAT",
        "Omega Kingdom/region/r.0.0.mca": b"ATTACKER_WIPED_OMEGA_KINGDOM_CHUNKS",
        "Omega Kingdom/playerdata/player1.dat": b"ATTACKER_WIPED_PLAYER_INVENTORY",
        "Omega Kingdom/poi/r.0.0.mca": b"ATTACKER_WIPED_VILLAGER_POI",
        "Omega Kingdom_nether/DIM-1/r.0.0.mca": b"ATTACKER_WIPED_NETHER",
        "Omega Kingdom_the_end/DIM1/r.0.0.mca": b"ATTACKER_WIPED_THE_END",
        "saves/custom_adventure/level.dat": b"ATTACKER_WIPED_SAVES",
        "ops.json": b'[{"uuid": "attacker-666", "name": "AttackerAdmin", "level": 4}]',
        "banned-players.json": b"[]",
        "banned-ips.json": b"[]",
        "whitelist.json": b'[{"uuid": "attacker-666", "name": "AttackerAdmin"}]',
        "eula.txt": b"eula=false\n",
        "user_jvm_args.txt": b"-Xmx16M -XX:+DisableExplicitGC\n",
        "mc-multicore-agent.jar": b"CORRUPTED_DUMMY_AGENT_BYTES",
        "client-only-allow.json": b'{"patterns": []}',
        "backups/safe_2026.zip": b"CORRUPT_BACKUP_PAYLOAD",
        "logs/latest.log": b"ATTACKER_FAKE_LOG_MESSAGES",
        "crash-reports/crash-1.txt": b"ATTACKER_CORRUPT_CRASH_REPORT",
    }

    legitimate_mod_filename = "useful_content_mod-1.0.jar"
    mrpack_bytes = create_adversarial_mrpack_bytes(
        mods=[(legitimate_mod_filename, "useful_content", "1.0.0", "*")],
        overrides_files=hostile_overrides,
        mc_version="1.20.1",
        loader="fabric",
        loader_version="0.15.11",
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v2.0_adv",
            "name": "Hostile Attack Pack 2.0",
            "files": [{"filename": "attack.mrpack", "url": "http://example.com/attack.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_bytes))

    def fake_download_to(dest_file, url, timeout=120):
        make_dummy_jar(dest_file, "useful_content", "1.0.0", loader="fabric")

    monkeypatch.setattr(modpack_routes, "_download_to", fake_download_to)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvChallengerServer/update",
        json={"target_version_id": "v2.0_adv", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}: {res.text}"
    resp_data = res.json()
    assert resp_data["status"] == "success"

    # 3. VERIFY ALL LIVE WORLDS AND CONFIGS ARE 100% IMMUTABLE & CORRUPTION-FREE
    # A. server.properties strictly preserved
    assert (adv_server / "server.properties").read_text(encoding="utf-8") == live_props_content

    # B. Overworld files completely unchanged byte-for-byte
    assert (overworld_dir / "level.dat").read_bytes() == level_dat_bytes
    assert (overworld_dir / "region" / "r.0.0.mca").read_bytes() == region_mca_bytes
    assert (overworld_dir / "playerdata" / "player1.dat").read_bytes() == player_dat_bytes
    assert (overworld_dir / "poi" / "r.0.0.mca").read_bytes() == poi_mca_bytes

    # C. Nether & End dimensions completely unchanged byte-for-byte
    assert (nether_dir / "r.0.0.mca").read_bytes() == nether_mca_bytes
    assert (end_dir / "r.0.0.mca").read_bytes() == end_mca_bytes

    # D. Secondary standard worlds & saves/ unchanged
    assert (secondary_world / "r.0.0.mca").read_bytes() == world_mca_bytes
    assert (saves_dir / "level.dat").read_bytes() == save_dat_bytes

    # E. Security configs (ops, bans, whitelist, eula, allowlist) unchanged
    assert (adv_server / "ops.json").read_bytes() == ops_bytes
    assert (adv_server / "banned-players.json").read_bytes() == bans_bytes
    assert (adv_server / "banned-ips.json").read_bytes() == banned_ips_bytes
    assert (adv_server / "whitelist.json").read_bytes() == whitelist_bytes
    assert (adv_server / "eula.txt").read_bytes() == eula_bytes
    assert (adv_server / "client-only-allow.json").read_bytes() == allowlist_bytes

    # F. Backups, logs, crash-reports preserved
    assert (adv_server / "backups" / "safe_2026.zip").read_bytes() == backup_safe_bytes
    assert "[20:00:00] Server started safely" in (adv_server / "logs" / "latest.log").read_text(encoding="utf-8")

    # G. Legitimate mod was installed
    assert (adv_server / "mods" / legitimate_mod_filename).is_file()

    # H. Metadata audit: None of the protected paths should be in installed_files
    meta = json.loads((adv_server / "modpack.meta.json").read_text(encoding="utf-8"))
    installed = meta["installed_files"]
    for hostile_p in hostile_overrides.keys():
        assert hostile_p not in installed, f"Protected path {hostile_p} must not be in installed_files"


def test_adv_dynamic_level_name_stress_matrix(tmp_path: Path):
    """
    STRESS-TESTS DYNAMIC LEVEL-NAME RESOLUTION:
    Evaluates quotes, spaces, trailing whitespace, multiline comments,
    UTF-8/non-ASCII characters, and Windows path separators.
    """
    srv = tmp_path / "matrix_srv"
    srv.mkdir()
    props = srv / "server.properties"

    # Case 1: Trailing spaces, spaces around '=' and double quotes
    props.write_text('level-name  =  "Custom Galaxy 2026"   \n', encoding="utf-8")
    assert _get_server_level_name(srv) == "Custom Galaxy 2026"
    assert is_world_path("Custom Galaxy 2026/level.dat", level_name="Custom Galaxy 2026") is True
    assert is_world_path("Custom Galaxy 2026_nether/DIM-1/r.0.0.mca", level_name="Custom Galaxy 2026") is True
    assert is_world_path("Custom Galaxy 2026_the_end/DIM1/r.0.0.mca", level_name="Custom Galaxy 2026") is True
    # Windows backslashes
    assert is_path_protected("Custom Galaxy 2026\\region\\r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("Custom Galaxy 2026_nether\\DIM-1\\r.0.0.mca", server_dir=srv) is True

    # Case 2: Single quotes with spaces
    props.write_text("level-name = 'Realm of Champions' \n", encoding="utf-8")
    assert _get_server_level_name(srv) == "Realm of Champions"
    assert is_path_protected("Realm of Champions/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("realm of champions_nether/DIM-1/data", server_dir=srv) is True

    # Case 3: Decoy comments before and after real level-name
    props.write_text(
        "# level-name=decoy_comment_world_1\n"
        "# Another comment\n"
        '   level-name  = "Deep_Dark_Abyss"  \n'
        "# level-name=decoy_comment_world_2\n",
        encoding="utf-8",
    )
    assert _get_server_level_name(srv) == "Deep_Dark_Abyss"
    assert is_path_protected("Deep_Dark_Abyss/level.dat", server_dir=srv) is True
    assert is_path_protected("Deep_Dark_Abyss_the_end/DIM1/r.0.0.mca", server_dir=srv) is True
    # Decoys are not protected
    assert is_world_path("decoy_comment_world_1/level.dat", level_name="Deep_Dark_Abyss") is False

    # Case 4: Non-ASCII UTF-8 encoding (German umlauts, Cyrillic, Japanese CJK)
    props.write_text("level-name=Abenteuer_in_Österreich\n", encoding="utf-8")
    assert _get_server_level_name(srv) == "Abenteuer_in_Österreich"
    assert is_path_protected("Abenteuer_in_Österreich/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("Abenteuer_in_Österreich_nether/DIM-1/r.0.0.mca", server_dir=srv) is True

    props.write_text('level-name = "Мир_Мечты" \n', encoding="utf-8")
    assert _get_server_level_name(srv) == "Мир_Мечты"
    assert is_path_protected("Мир_Мечты/level.dat", server_dir=srv) is True
    assert is_path_protected("Мир_Мечты_nether/DIM-1/r.0.0.mca", server_dir=srv) is True

    props.write_text('level-name = "幻想郷_サーバー" \n', encoding="utf-8")
    assert _get_server_level_name(srv) == "幻想郷_サーバー"
    assert is_path_protected("幻想郷_サーバー/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("幻想郷_サーバー_the_end/DIM1/r.0.0.mca", server_dir=srv) is True

    # Case 5: Path traversal and odd path representations
    assert is_path_protected("/world/level.dat", server_dir=srv) is True
    assert is_path_protected("world/playerdata/alice.dat", server_dir=srv) is True
    assert is_path_protected("saves/skyblock/level.dat", server_dir=srv) is True


def test_adv_loader_migration_lifecycle_forge_neoforge_fabric(adv_server: Path, client, monkeypatch):
    """
    CONTINUOUS 3-HOP MODLOADER MIGRATION LIFECYCLE ATTACK:
    Step 1: Forge 1.20.1 (Java 17)
    Step 2: Migrate to NeoForge 1.20.4 (Java 17)
    Step 3: Migrate to Fabric 1.21.1 (Java 21)
    Step 4: Migrate back to Forge 1.20.1 (Java 17)

    Verifies across all transitions:
    - Obsolete launcher scripts and loader binaries are purged at each step
    - Loader-specific libraries (net/minecraftforge, net/neoforged, net/fabricmc, .fabric) purged
    - Third-party libraries (e.g. com/google/guava) are preserved
    - Sacred world saves and playerdata are never lost or corrupted
    - Multi-core profile user_jvm_args.txt regenerated with appropriate Java/loader flags
    - server_meta.json accurately reflects new server_type, mc_version, and java_version
    """
    # ------------------------------------------------------------------------
    # Initial State: Forge 1.20.1
    # ------------------------------------------------------------------------
    (adv_server / "forge-1.20.1-47.2.0.jar").write_bytes(b"FORGE_LAUNCHER_JAR")
    (adv_server / "run.sh").write_text("#!/bin/sh\nrun forge", encoding="utf-8")
    (adv_server / "run.bat").write_text("@echo off\nrun forge", encoding="utf-8")
    (adv_server / "win_args.txt").write_text("-Xmx4G", encoding="utf-8")
    (adv_server / "unix_args.txt").write_text("-Xmx4G", encoding="utf-8")

    # Forge loader library
    forge_lib_dir = adv_server / "libraries" / "net" / "minecraftforge" / "forge" / "1.20.1-47.2.0"
    forge_lib_dir.mkdir(parents=True)
    (forge_lib_dir / "forge-1.20.1-47.2.0-server.jar").write_bytes(b"FORGE_LIB_BYTES")

    # Third-party common library (must NOT be pruned during migration)
    common_lib_dir = adv_server / "libraries" / "com" / "google" / "guava" / "guava" / "31.1-jre"
    common_lib_dir.mkdir(parents=True)
    common_lib_jar = common_lib_dir / "guava-31.1-jre.jar"
    common_lib_jar.write_bytes(b"GUAVA_COMMON_LIBRARY_BYTES")

    # Sacred world data
    world_dir = adv_server / "world" / "region"
    world_dir.mkdir(parents=True)
    playerdata_dir = adv_server / "world" / "playerdata"
    playerdata_dir.mkdir(parents=True)
    sacred_level_dat = b"IMMUTABLE_SACRED_SURVIVAL_LEVEL_DAT"
    sacred_player_dat = b"IMMUTABLE_SACRED_PLAYER_INVENTORY_DAT"
    (adv_server / "world" / "level.dat").write_bytes(sacred_level_dat)
    (playerdata_dir / "player_steve.dat").write_bytes(sacred_player_dat)

    # Initial configs & multicore
    (adv_server / "server.properties").write_text("level-name=world\nserver-port=25565\n", encoding="utf-8")
    (adv_server / "user_jvm_args.txt").write_text(
        "# Custom JVM setting\n-Dforge.logging.console.level=debug\n# Lynx Multi-Core Engine (LMCE)\n-XX:ActiveProcessorCount=4\n",
        encoding="utf-8",
    )

    save_server_modpack_info(
        "AdvChallengerServer",
        {
            "provider": "modrinth",
            "pack_id": "lifecycle-pack",
            "version_id": "v1.0",
            "loader": "forge",
            "loader_version": "47.2.0",
            "minecraft_version": "1.20.1",
            "installed_files": [],
        },
    )

    (adv_server / "server_meta.json").write_text(json.dumps({
        "server_type": "forge",
        "mc_type": "forge",
        "version": "1.20.1",
        "java_version": "17",
        "cpu_cores": 4,
        "max_ram_mb": 4096,
        "multicore_enabled": True,
    }), encoding="utf-8")

    admin_h = _login(client, "admin", "AdminPass123")

    # ------------------------------------------------------------------------
    # HOP 1: Forge 1.20.1 -> NeoForge 1.20.4
    # ------------------------------------------------------------------------
    mrpack_hop1 = create_adversarial_mrpack_bytes(
        mods=[("neoforge-content-1.0.jar", "neocontent", "1.0.0", "*")],
        mc_version="1.20.4",
        loader="neoforge",
        loader_version="20.4.80",
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {"id": "v_hop1", "name": "NeoForge 20.4.80", "files": [{"filename": "p1.mrpack", "url": "http://example.com/p1.mrpack", "primary": True}]},
        {"id": "v_hop2", "name": "Fabric 0.16.0", "files": [{"filename": "p2.mrpack", "url": "http://example.com/p2.mrpack", "primary": True}]},
        {"id": "v_hop3", "name": "Forge 47.2.0", "files": [{"filename": "p3.mrpack", "url": "http://example.com/p3.mrpack", "primary": True}]},
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})

    active_mrpack = {"bytes": mrpack_hop1}
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(active_mrpack["bytes"]))

    def fake_download_hop(dest_file, url, timeout=120):
        dest_file.write_bytes(b"DUMMY_PROVISIONED_INSTALLER_OR_JAR")

    monkeypatch.setattr(modpack_routes, "_download_to", fake_download_hop)

    # Execute Hop 1
    res1 = client.post(
        "/api/modpacks/server/AdvChallengerServer/update",
        json={"target_version_id": "v_hop1", "create_backup": False},
        headers=admin_h,
    )
    assert res1.status_code == 200, f"Hop 1 failed: {res1.text}"
    d1 = res1.json()
    assert d1["loader_migrated"] is True
    assert d1["loader"] == "neoforge"
    assert d1["minecraft_version"] == "1.20.4"

    # Verifications for Hop 1:
    # 1. Forge launcher jar & scripts deleted
    assert not (adv_server / "forge-1.20.1-47.2.0.jar").exists()
    assert not (adv_server / "run.sh").exists()
    assert not (adv_server / "run.bat").exists()
    assert not (adv_server / "win_args.txt").exists()
    assert not (adv_server / "unix_args.txt").exists()
    # 2. Forge library deleted
    assert not (adv_server / "libraries" / "net" / "minecraftforge").exists()
    # 3. Third-party common library preserved
    assert common_lib_jar.exists()
    assert common_lib_jar.read_bytes() == b"GUAVA_COMMON_LIBRARY_BYTES"
    # 4. Sacred world data 100% intact
    assert (adv_server / "world" / "level.dat").read_bytes() == sacred_level_dat
    assert (playerdata_dir / "player_steve.dat").read_bytes() == sacred_player_dat
    # 5. NeoForge installer provisioned
    assert (adv_server / "neoforge-20.4.80-installer.jar").exists()
    # 6. server_meta updated
    sm1 = json.loads((adv_server / "server_meta.json").read_text(encoding="utf-8"))
    assert sm1["server_type"] == "neoforge"
    assert sm1["mc_version"] == "1.20.4"
    assert sm1["java_version"] == "17"
    # 7. user_jvm_args.txt regenerated with multicore profile and custom user flag preserved
    assert (adv_server / "user_jvm_args.txt").exists()
    uj1 = (adv_server / "user_jvm_args.txt").read_text(encoding="utf-8")
    assert "-Dforge.logging.console.level=debug" in uj1
    assert "LMCE_HEADER_START" in uj1 or "Lynx Multi-Core Engine" in uj1

    # ------------------------------------------------------------------------
    # HOP 2: NeoForge 1.20.4 -> Fabric 1.21.1 (Java 17 -> Java 21)
    # ------------------------------------------------------------------------
    neo_lib_dir = adv_server / "libraries" / "net" / "neoforged" / "neoforge"
    neo_lib_dir.mkdir(parents=True)
    (neo_lib_dir / "neoforge-lib.jar").write_bytes(b"NEO_LIB")

    mrpack_hop2 = create_adversarial_mrpack_bytes(
        mods=[("fabric-content-1.0.jar", "fabriccontent", "1.0.0", "*")],
        mc_version="1.21.1",
        loader="fabric",
        loader_version="0.16.0",
    )
    active_mrpack["bytes"] = mrpack_hop2

    res2 = client.post(
        "/api/modpacks/server/AdvChallengerServer/update",
        json={"target_version_id": "v_hop2", "create_backup": False},
        headers=admin_h,
    )
    assert res2.status_code == 200, f"Hop 2 failed: {res2.text}"
    d2 = res2.json()
    assert d2["loader_migrated"] is True
    assert d2["loader"] == "fabric"
    assert d2["minecraft_version"] == "1.21.1"

    # Verifications for Hop 2:
    # 1. NeoForge installer deleted
    assert not (adv_server / "neoforge-20.4.80-installer.jar").exists()
    # 2. NeoForge library deleted
    assert not (adv_server / "libraries" / "net" / "neoforged").exists()
    # 3. Third-party common library preserved
    assert common_lib_jar.exists()
    # 4. Sacred world data 100% intact
    assert (adv_server / "world" / "level.dat").read_bytes() == sacred_level_dat
    assert (playerdata_dir / "player_steve.dat").read_bytes() == sacred_player_dat
    # 5. Fabric server jar provisioned
    assert (adv_server / "fabric-server-mc.1.21.1-loader.0.16.0.jar").exists()
    # 6. server_meta updated with Java 21
    sm2 = json.loads((adv_server / "server_meta.json").read_text(encoding="utf-8"))
    assert sm2["server_type"] == "fabric"
    assert sm2["mc_version"] == "1.21.1"
    assert sm2["java_version"] == "21"

    # ------------------------------------------------------------------------
    # HOP 3: Fabric 1.21.1 -> Forge 1.20.1 (Reverse Migration to Forge, Java 17)
    # ------------------------------------------------------------------------
    fab_lib_dir = adv_server / "libraries" / "net" / "fabricmc"
    fab_lib_dir.mkdir(parents=True)
    (fab_lib_dir / "fabric-loader.jar").write_bytes(b"FAB_LOADER_LIB")
    fab_dot_dir = adv_server / ".fabric"
    fab_dot_dir.mkdir(parents=True)
    (fab_dot_dir / "processed_mods.json").write_bytes(b"FABRIC_METADATA")

    mrpack_hop3 = create_adversarial_mrpack_bytes(
        mods=[("forge-content-1.0.jar", "forgecontent", "1.0.0", "*")],
        mc_version="1.20.1",
        loader="forge",
        loader_version="47.2.0",
    )
    active_mrpack["bytes"] = mrpack_hop3

    res3 = client.post(
        "/api/modpacks/server/AdvChallengerServer/update",
        json={"target_version_id": "v_hop3", "create_backup": False},
        headers=admin_h,
    )
    assert res3.status_code == 200, f"Hop 3 failed: {res3.text}"
    d3 = res3.json()
    assert d3["loader_migrated"] is True
    assert d3["loader"] == "forge"
    assert d3["minecraft_version"] == "1.20.1"

    # Verifications for Hop 3:
    # 1. Fabric launcher jar deleted
    assert not (adv_server / "fabric-server-mc.1.21.1-loader.0.16.0.jar").exists()
    # 2. Fabric libraries and .fabric directory deleted
    assert not (adv_server / "libraries" / "net" / "fabricmc").exists()
    assert not (adv_server / ".fabric").exists()
    # 3. Third-party common library preserved
    assert common_lib_jar.exists()
    # 4. Sacred world data 100% intact through entire 3-hop migration!
    assert (adv_server / "world" / "level.dat").read_bytes() == sacred_level_dat
    assert (playerdata_dir / "player_steve.dat").read_bytes() == sacred_player_dat
    # 5. Forge installer provisioned
    assert (adv_server / "forge-1.20.1-47.2.0-installer.jar").exists()
    # 6. server_meta updated back to forge/17
    sm3 = json.loads((adv_server / "server_meta.json").read_text(encoding="utf-8"))
    assert sm3["server_type"] == "forge"
    assert sm3["mc_version"] == "1.20.1"
    assert sm3["java_version"] == "17"
    # 7. user_jvm_args.txt regenerated
    assert (adv_server / "user_jvm_args.txt").exists()


def test_adv_clean_obsolete_loader_artifacts_precision(tmp_path: Path):
    """
    VERIFIES SURGICAL PRECISION OF clean_obsolete_loader_artifacts:
    Ensures ONLY obsolete loader artifacts are removed and never worlds,
    configs, multicore agents, or common library JARs.
    """
    srv = tmp_path / "surgical_srv"
    srv.mkdir()

    # Create dummy artifacts
    (srv / "run.sh").write_text("#!/bin/sh", encoding="utf-8")
    (srv / "run.bat").write_text("@echo off", encoding="utf-8")
    (srv / "run.ps1").write_text("powershell run", encoding="utf-8")
    (srv / "win_args.txt").write_text("args", encoding="utf-8")
    (srv / "unix_args.txt").write_text("args", encoding="utf-8")
    (srv / "forge-1.20.1.jar").write_bytes(b"FORGE")
    (srv / "neoforge-20.4.jar").write_bytes(b"NEOFORGE")
    (srv / "fabric-server-launch.jar").write_bytes(b"FABRIC")
    (srv / "forge-installer.jar").write_bytes(b"INSTALLER")
    (srv / "server.jar").write_bytes(b"SERVER")

    # Protected files (MUST NOT BE REMOVED)
    (srv / "mc-multicore-agent.jar").write_bytes(b"AGENT")
    (srv / "user_jvm_args.txt").write_text("-Xmx4G", encoding="utf-8")
    (srv / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    # Libraries
    libs = srv / "libraries"
    (libs / "net" / "minecraftforge").mkdir(parents=True)
    (libs / "net" / "minecraftforge" / "f.jar").write_bytes(b"F")
    (libs / "com" / "google" / "gson").mkdir(parents=True)
    (libs / "com" / "google" / "gson" / "gson.jar").write_bytes(b"GSON")

    # Clean from Forge to NeoForge
    cleaned = clean_obsolete_loader_artifacts(srv, current_loader="forge", target_loader="neoforge")

    # Cleans scripts
    assert "run.sh" in cleaned
    assert "run.bat" in cleaned
    assert "run.ps1" in cleaned
    assert "win_args.txt" in cleaned
    assert "unix_args.txt" in cleaned
    # Cleans forge / neoforge / fabric jars and installer
    assert "forge-1.20.1.jar" in cleaned
    assert "neoforge-20.4.jar" in cleaned
    assert "fabric-server-launch.jar" in cleaned
    assert "forge-installer.jar" in cleaned
    assert "server.jar" in cleaned
    # Cleans forge libraries
    assert "libraries/net/minecraftforge" in cleaned

    # VERIFY PROTECTED ARTIFACTS WERE PRESERVED
    assert (srv / "mc-multicore-agent.jar").is_file()
    assert (srv / "user_jvm_args.txt").is_file()
    assert (srv / "server.properties").is_file()
    assert (libs / "com" / "google" / "gson" / "gson.jar").is_file()


def test_adv_staging_traversal_and_sneaky_world_patterns(tmp_path: Path):
    """
    STRESS-TESTS SNEAKY PATHS AND WILDCARDS:
    Verifies that uppercase variants, deep saves subdirectories,
    custom dimension directories, and allowlist files are protected.
    """
    srv = tmp_path / "sneaky_srv"
    srv.mkdir()
    (srv / "server.properties").write_text("level-name=Aether_Realm\n", encoding="utf-8")

    # Dynamic level name dimension paths
    assert is_path_protected("Aether_Realm/DIM-1/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("AETHER_REALM/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("aether_realm_nether/data/raids.dat", server_dir=srv) is True
    assert is_path_protected("Aether_Realm_the_end/entities/r.0.0.mca", server_dir=srv) is True

    # Standard world folders & wildcards
    assert is_path_protected("world_the_end/DIM1/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("saves/sky_islands/level.dat", server_dir=srv) is True
    assert is_path_protected("saves/adventure_2026/region/r.0.0.mca", server_dir=srv) is True
    assert is_path_protected("world_custom_dimension/region/r.0.0.mca", server_dir=srv) is True

    # System & Allowlist variations
    assert is_path_protected("banned-players.json", server_dir=srv) is True
    assert is_path_protected("banned-ips.json", server_dir=srv) is True
    assert is_path_protected("banned-custom-ips.json", server_dir=srv) is True
    assert is_path_protected("client-only-allow.json", server_dir=srv) is True
    assert is_path_protected("client-only-allow.txt", server_dir=srv) is True
    assert is_path_protected("client-only-allow.yaml", server_dir=srv) is True
    assert is_path_protected("client-only-allow.yml", server_dir=srv) is True
    assert is_path_protected("usercache.json", server_dir=srv) is True
    assert is_path_protected("server-icon.png", server_dir=srv) is True
    assert is_path_protected(".mod_side_report.json", server_dir=srv) is True

    # Traversal attempts & backslashes
    assert is_path_protected("Aether_Realm\\playerdata\\steve.dat", server_dir=srv) is True
    assert is_path_protected("saves\\hardcore\\level.dat", server_dir=srv) is True

    # Normal mod and normal config should NOT be protected (they can be updated)
    assert is_path_protected("mods/botania.jar", server_dir=srv) is False
    assert is_path_protected("config/botania.cfg", server_dir=srv) is False


def test_adv_migration_downgrade_to_legacy_forge_java8(adv_server: Path, client, monkeypatch):
    """
    ADVERSARIAL MIGRATION TEST: Modern NeoForge 1.20.4 -> Legacy Forge 1.16.5.
    Verifies that downgrading/switching to legacy Minecraft/Forge properly infers Java 8,
    cleans modern NeoForge libraries, regenerates Java 8 multicore profiles,
    and preserves world saves.
    """
    (adv_server / "server.properties").write_text("level-name=world\n", encoding="utf-8")
    (adv_server / "neoforge-20.4.80-installer.jar").write_bytes(b"NEOFORGE_JAR")
    (adv_server / "run.sh").write_text("#!/bin/sh\nrun neoforge", encoding="utf-8")

    world_dir = adv_server / "world" / "region"
    world_dir.mkdir(parents=True)
    (adv_server / "world" / "level.dat").write_bytes(b"LEGACY_TEST_WORLD")

    neo_lib = adv_server / "libraries" / "net" / "neoforged" / "neoforge"
    neo_lib.mkdir(parents=True)
    (neo_lib / "lib.jar").write_bytes(b"NEO_LIB")

    save_server_modpack_info(
        "AdvChallengerServer",
        {
            "provider": "modrinth",
            "pack_id": "legacy-pack",
            "version_id": "v1.0",
            "loader": "neoforge",
            "loader_version": "20.4.80",
            "minecraft_version": "1.20.4",
            "installed_files": [],
        },
    )

    (adv_server / "server_meta.json").write_text(json.dumps({
        "server_type": "neoforge",
        "mc_type": "neoforge",
        "version": "1.20.4",
        "java_version": "17",
        "cpu_cores": 4,
        "max_ram_mb": 4096,
        "multicore_enabled": True,
    }), encoding="utf-8")

    mrpack_legacy = create_adversarial_mrpack_bytes(
        mods=[("legacy-forge-mod-1.0.jar", "legacymod", "1.0.0", "*")],
        mc_version="1.16.5",
        loader="forge",
        loader_version="36.2.39",
    )

    mock_provider = MagicMock()
    mock_provider.get_versions.return_value = [
        {
            "id": "v_legacy",
            "name": "Legacy Forge 1.16.5",
            "files": [{"filename": "legacy.mrpack", "url": "http://example.com/legacy.mrpack", "primary": True}],
        }
    ]
    import catalog_routes
    monkeypatch.setattr(catalog_routes, "get_providers_live", lambda: {"modrinth": mock_provider})
    monkeypatch.setattr(requests, "get", lambda *a, **kw: MockHttpResponse(mrpack_legacy))

    def fake_download(dest_file, url, timeout=120):
        dest_file.write_bytes(b"FORGE_1_16_5_INSTALLER_JAR")

    monkeypatch.setattr(modpack_routes, "_download_to", fake_download)

    admin_h = _login(client, "admin", "AdminPass123")
    res = client.post(
        "/api/modpacks/server/AdvChallengerServer/update",
        json={"target_version_id": "v_legacy", "create_backup": False},
        headers=admin_h,
    )
    assert res.status_code == 200, f"Legacy migration failed: {res.text}"
    data = res.json()
    assert data["loader_migrated"] is True
    assert data["loader"] == "forge"
    assert data["minecraft_version"] == "1.16.5"
    assert data["mc_version_changed"] is True

    # Obsolete NeoForge files purged
    assert not (adv_server / "neoforge-20.4.80-installer.jar").exists()
    assert not (adv_server / "run.sh").exists()
    assert not (adv_server / "libraries" / "net" / "neoforged").exists()

    # Forge installer provisioned
    assert (adv_server / "forge-1.16.5-36.2.39-installer.jar").exists()

    # Java 8 inferred for Forge 1.16.5
    sm = json.loads((adv_server / "server_meta.json").read_text(encoding="utf-8"))
    assert sm["server_type"] == "forge"
    assert sm["mc_version"] == "1.16.5"
    assert sm["java_version"] == "8"

    # Multicore user_jvm_args.txt regenerated
    assert (adv_server / "user_jvm_args.txt").exists()

    # World data intact
    assert (adv_server / "world" / "level.dat").read_bytes() == b"LEGACY_TEST_WORLD"


def test_adv_dynamic_level_name_property_edge_cases(tmp_path: Path):
    """
    Tests edge cases in server.properties:
    - Empty file
    - UTF-8 with BOM (\ufeff)
    - CRLF mixed with LF
    - Multiple level-name keys (first valid non-comment key wins)
    - Unclosed quotes: level-name="Unclosed World
    """
    srv = tmp_path / "props_edge_srv"
    srv.mkdir()
    props = srv / "server.properties"

    # 1. Empty file defaults to 'world'
    props.write_text("", encoding="utf-8")
    assert _get_server_level_name(srv) == "world"

    # 2. File with BOM and CRLF
    bom_content = "\ufeff# Server Properties with BOM\r\nlevel-name =  Realm_With_BOM  \r\ngamemode=0\r\n"
    props.write_text(bom_content, encoding="utf-8")
    assert _get_server_level_name(srv) == "Realm_With_BOM"
    assert is_path_protected("Realm_With_BOM/level.dat", server_dir=srv) is True

    # 3. Unclosed quote: level-name="Unclosed World
    props.write_text('level-name="Unclosed World\n', encoding="utf-8")
    assert _get_server_level_name(srv) == "Unclosed World"

    # 4. First valid key wins over subsequent lines
    props.write_text("level-name=FirstRealm\nlevel-name=SecondRealm\n", encoding="utf-8")
    assert _get_server_level_name(srv) == "FirstRealm"

