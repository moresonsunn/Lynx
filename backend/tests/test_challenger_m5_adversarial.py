"""Empirical Adversarial Test Suite for Milestone 5:
Incremental Mod Diffing, Stale Mod Pruning, Modloader Migration & Dynamic World Preservation.
Authored by challenger_m5_1 (critic, specialist).
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

os.environ.setdefault("SECRET_KEY", "test-secret-key-challenger-m5-adversarial-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_challenger_m5"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_challenger_m5.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

from client_mod_filter import add_to_allowlist, is_mod_allowlisted
from mod_side_resolver import ModSideResolver, inspect_jar_metadata
import modpack_routes
from modpack_routes import (
    _get_server_level_name,
    is_world_path,
    is_path_protected,
    clean_obsolete_loader_artifacts,
    _infer_java_version,
    _index_local_server_mods,
    _stage_modpack_version,
    reconcile_and_cleanup_modpack,
    _safe_is_mod_allowlisted,
    save_server_modpack_info,
)


def make_dummy_jar(
    jar_path: Path,
    mod_id: str,
    version: str = "1.0.0",
    loader: str = "fabric",
    environment: str = "*",
    provided_mods: Optional[List[str]] = None,
    extra_bytes: bytes = b"",
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
        if extra_bytes:
            zf.writestr("data/extra.bin", extra_bytes)
    return jar_path


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
def test_server(tmp_path: Path, monkeypatch) -> Path:
    srv = tmp_path / "TestServer"
    srv.mkdir(parents=True, exist_ok=True)
    (srv / "mods").mkdir(parents=True, exist_ok=True)
    (srv / "mods-disabled-client").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(modpack_routes, "SERVERS_ROOT", tmp_path)
    return srv


# ============================================================================
# Category 1: Adversarial Stress of _index_local_server_mods
# ============================================================================

def test_adv_index_zero_byte_corrupted_and_unusual_jars(tmp_path: Path):
    """
    Stress test _index_local_server_mods with:
    1. Zero-byte jar file
    2. Corrupted jar (non-zip arbitrary binary)
    3. Uppercase .JAR extension
    4. Subdirectory (must not be treated as a jar)
    """
    srv = tmp_path / "adv_index_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    # 1. Zero-byte file
    zero_jar = mods_d / "zero_byte.jar"
    zero_jar.write_bytes(b"")

    # 2. Corrupted non-zip jar
    corrupt_jar = mods_d / "corrupt.jar"
    corrupt_jar.write_bytes(b"\x7fELF\x02\x01\x01\x00NotAZipHeaderAtAll\xff\x00\xaa\xbb")

    # 3. Uppercase extension file
    upper_jar = mods_d / "UPPERCASE_MOD.JAR"
    upper_jar.write_bytes(b"PK\x03\x04somebytes")

    # 4. Directory named fake.jar (must be skipped, not crash stat or open)
    fake_dir = mods_d / "not_a_file.jar"
    fake_dir.mkdir()

    idx = _index_local_server_mods(srv)

    # Assertions
    assert "by_sha1" in idx
    assert "by_sha256" in idx
    assert "by_name_and_size" in idx
    assert "by_murmur2" in idx

    # Zero-byte file is indexed safely
    zero_sha1 = hashlib.sha1(b"").hexdigest().lower()
    assert zero_sha1 in idx["by_sha1"]
    assert idx["by_sha1"][zero_sha1] == zero_jar
    assert ("zero_byte.jar", 0) in idx["by_name_and_size"]

    # Corrupt file is indexed safely by hash
    corrupt_sha1 = hashlib.sha1(corrupt_jar.read_bytes()).hexdigest().lower()
    assert corrupt_sha1 in idx["by_sha1"]
    assert idx["by_sha1"][corrupt_sha1] == corrupt_jar

    # Fake directory was safely skipped
    for entry in idx["all_mods"]:
        assert entry["name"] != "not_a_file.jar"


def test_adv_index_symlinks_and_hardlinks(tmp_path: Path):
    """
    Verify _index_local_server_mods handling of hardlinks and broken symlinks.
    """
    srv = tmp_path / "adv_link_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    real_jar = mods_d / "real_mod.jar"
    real_jar.write_bytes(b"REAL_JAR_BYTES_CONTENT_12345")

    # Create hardlink
    hardlink_jar = mods_d / "hardlink_mod.jar"
    try:
        os.link(real_jar, hardlink_jar)
        has_hardlink = True
    except OSError:
        has_hardlink = False

    # Create broken symlink if OS permissions allow
    broken_symlink = mods_d / "broken_mod.jar"
    has_broken_symlink = False
    try:
        broken_symlink.symlink_to(mods_d / "non_existent_file.jar")
        has_broken_symlink = True
    except (OSError, NotImplementedError):
        pass

    idx = _index_local_server_mods(srv)

    real_sha1 = hashlib.sha1(b"REAL_JAR_BYTES_CONTENT_12345").hexdigest().lower()
    assert real_sha1 in idx["by_sha1"]

    if has_hardlink:
        assert ("hardlink_mod.jar", len(b"REAL_JAR_BYTES_CONTENT_12345")) in idx["by_name_and_size"]

    if has_broken_symlink:
        # Broken symlink must NOT crash the indexer and must NOT be in all_mods
        indexed_names = [m["name"] for m in idx["all_mods"]]
        assert "broken_mod.jar" not in indexed_names


def test_adv_index_empty_and_nonexistent_directories():
    """Verify resilience against None, nonexistent path, or empty server directory."""
    assert _index_local_server_mods(None) == {
        "by_sha1": {},
        "by_sha256": {},
        "by_name_and_size": {},
        "by_murmur2": {},
        "all_mods": [],
    }

    assert _index_local_server_mods("/non/existent/path/987654321") == {
        "by_sha1": {},
        "by_sha256": {},
        "by_name_and_size": {},
        "by_murmur2": {},
        "all_mods": [],
    }


# ============================================================================
# Category 2: Zero HTTP Download Local Reuse Across mods/ and mods-disabled-client/
# ============================================================================

def test_adv_local_reuse_across_disabled_quarantine_with_zero_downloads(tmp_path: Path):
    """
    Adversarial verification:
    Modpack requires 2 mods:
    - Mod 1 is present in server_dir/mods/
    - Mod 2 is present ONLY in server_dir/mods-disabled-client/
    Both must be reused locally with ZERO remote HTTP downloads!
    """
    srv = tmp_path / "adv_reuse_srv"
    mods_d = srv / "mods"
    dis_d = srv / "mods-disabled-client"
    mods_d.mkdir(parents=True)
    dis_d.mkdir(parents=True)

    jar1 = make_dummy_jar(mods_d / "active-mod-1.0.jar", mod_id="activemod", version="1.0.0")
    jar2 = make_dummy_jar(dis_d / "quarantined-mod-1.0.jar", mod_id="quarantined", version="1.0.0")

    sha1_jar1 = hashlib.sha1(jar1.read_bytes()).hexdigest().lower()
    sha1_jar2 = hashlib.sha1(jar2.read_bytes()).hexdigest().lower()

    staging = tmp_path / "staging"
    tmpdir = tmp_path / "tmp"
    staging.mkdir()
    tmpdir.mkdir()

    # Modrinth pack targeting both mods
    mr_index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "v1.0",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
        "files": [
            {
                "path": "mods/active-mod-1.0.jar",
                "hashes": {"sha1": sha1_jar1},
                "downloads": ["http://remote.cdn/active-mod-1.0.jar"],
                "fileSize": jar1.stat().st_size,
            },
            {
                "path": "mods/quarantined-mod-1.0.jar",
                "hashes": {"sha1": sha1_jar2},
                "downloads": ["http://remote.cdn/quarantined-mod-1.0.jar"],
                "fileSize": jar2.stat().st_size,
            },
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(mr_index))
    mrpack_bytes = buf.getvalue()

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(b"REMOTE_DOWNLOADED")

    with patch("requests.get", return_value=MockHttpResponse(mrpack_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="modrinth",
                provider=MagicMock(),
                pack_id="pack-adv",
                target_version_obj={"files": [{"url": "http://remote.cdn/pack.mrpack"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    # STRICT ASSERTIONS:
    assert result["reused_mods_count"] == 2
    assert len(remote_download_calls) == 0, f"Expected 0 remote downloads, but got: {remote_download_calls}"
    assert (staging / "mods" / "active-mod-1.0.jar").read_bytes() == jar1.read_bytes()
    assert (staging / "mods" / "quarantined-mod-1.0.jar").read_bytes() == jar2.read_bytes()


def test_adv_curseforge_murmur2_local_reuse_with_zero_downloads(tmp_path: Path):
    """
    Adversarial verification for CurseForge:
    Manifest provides fingerprint (Murmur2) and no SHA1.
    Must match local mod by Murmur2 with ZERO remote HTTP downloads!
    """
    from compat.evidence.collectors.remote import _cf_fingerprint

    srv = tmp_path / "adv_cf_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    jar_cf = make_dummy_jar(mods_d / "cf-mod-1.0.0.jar", mod_id="cfmod", version="1.0.0")
    fp = _cf_fingerprint(str(jar_cf))
    assert fp is not None

    staging = tmp_path / "staging_cf"
    tmpdir = tmp_path / "tmp_cf"
    staging.mkdir()
    tmpdir.mkdir()

    # CurseForge manifest.json
    cf_mani = {
        "minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.2.0"}]},
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": "CF Pack",
        "version": "1.0",
        "files": [{"projectID": 12345, "fileID": 67890, "required": True}],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(cf_mani))
    cf_zip_bytes = buf.getvalue()

    mock_provider = MagicMock()
    # Provider expand_manifest_files returns resolved files with fingerprint and NO SHA1
    mock_provider.expand_manifest_files.return_value = [
        {
            "id": 67890,
            "fileName": "cf-mod-1.0.0.jar",
            "downloadUrl": "http://cf.cdn/cf-mod-1.0.0.jar",
            "fingerprint": fp,
            "fileLength": jar_cf.stat().st_size,
            "hashes": [],  # NO SHA1 PROVIDED!
        }
    ]

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(b"DOWNLOADED")

    with patch("requests.get", return_value=MockHttpResponse(cf_zip_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="curseforge",
                provider=mock_provider,
                pack_id="12345",
                target_version_obj={"files": [{"url": "http://cf.cdn/pack.zip"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    # STRICT ASSERTIONS:
    assert result["reused_mods_count"] == 1
    assert len(remote_download_calls) == 0, f"Expected 0 remote downloads, but got: {remote_download_calls}"
    assert (staging / "mods" / "cf-mod-1.0.0.jar").read_bytes() == jar_cf.read_bytes()


def test_adv_name_and_size_reuse_when_no_hashes_in_manifest(tmp_path: Path):
    """
    When manifest specifies NO hashes at all, matching by (filename, size) works.
    """
    srv = tmp_path / "adv_namesize_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    jar = make_dummy_jar(mods_d / "simple-mod-1.0.jar", mod_id="simple", version="1.0.0")

    staging = tmp_path / "staging_ns"
    tmpdir = tmp_path / "tmp_ns"
    staging.mkdir()
    tmpdir.mkdir()

    mr_index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "v1.0",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
        "files": [
            {
                "path": "mods/simple-mod-1.0.jar",
                "hashes": {},  # NO HASHES
                "downloads": ["http://remote.cdn/simple-mod-1.0.jar"],
                "fileSize": jar.stat().st_size,
            }
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(mr_index))
    mrpack_bytes = buf.getvalue()

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(b"DOWNLOADED")

    with patch("requests.get", return_value=MockHttpResponse(mrpack_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="modrinth",
                provider=MagicMock(),
                pack_id="pack-ns",
                target_version_obj={"files": [{"url": "http://remote.cdn/pack.mrpack"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    assert result["reused_mods_count"] == 1
    assert len(remote_download_calls) == 0


# ============================================================================
# Category 3: Stale Cleanup Multi-Tier Recovery & Quarantine Pruning
# ============================================================================

def test_adv_stale_cleanup_tier3_modpack_meta_recovery(tmp_path: Path):
    """
    Adversarial challenge:
    previous_meta is None, .mod_side_report.json is missing, server_meta.json has empty installed_files.
    Verify Tier 3 recovery from modpack.meta.json prunes dropped mod.
    """
    srv = tmp_path / "srv_tier3"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    old_mod = make_dummy_jar(mods_d / "obsolete-tier3-1.0.jar", mod_id="tier3obs")
    kept_mod = make_dummy_jar(mods_d / "kept-tier3-1.0.jar", mod_id="tier3kept")

    # server_meta.json has empty installed_files
    (srv / "server_meta.json").write_text(json.dumps({"installed_files": []}), encoding="utf-8")

    # modpack.meta.json has the installed files
    (srv / "modpack.meta.json").write_text(json.dumps({
        "pack_id": "test-pack",
        "installed_files": ["mods/obsolete-tier3-1.0.jar", "mods/kept-tier3-1.0.jar"]
    }), encoding="utf-8")

    staging = tmp_path / "staging_tier3"
    staging_mods = staging / "mods"
    staging_mods.mkdir(parents=True)
    make_dummy_jar(staging_mods / "kept-tier3-1.0.jar", mod_id="tier3kept")

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta=None,
    )

    assert "obsolete-tier3-1.0.jar" in res["mods_cleaned"]
    assert not old_mod.exists()
    assert kept_mod.exists()


def test_adv_stale_cleanup_tier4_managed_pack_fallback(tmp_path: Path):
    """
    Adversarial challenge:
    ALL metadata files (previous_meta, .mod_side_report.json, server_meta.json, modpack.meta.json)
    have missing or empty installed_files, BUT the server is marked as managed modpack.
    reconcile_and_cleanup_modpack falls back to comparing existing JARs vs staged JARs.
    """
    srv = tmp_path / "srv_tier4"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    abandoned_mod = make_dummy_jar(mods_d / "abandoned-mod-1.0.jar", mod_id="abandoned")
    persisting_mod = make_dummy_jar(mods_d / "persisting-mod-1.0.jar", mod_id="persisting")

    # modpack.meta.json exists indicating managed pack, but installed_files is empty
    (srv / "modpack.meta.json").write_text(json.dumps({
        "pack_id": "managed-test-pack",
        "installed_files": []
    }), encoding="utf-8")

    staging = tmp_path / "staging_tier4"
    staging_mods = staging / "mods"
    staging_mods.mkdir(parents=True)
    make_dummy_jar(staging_mods / "persisting-mod-1.0.jar", mod_id="persisting")

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={"provider": "modrinth", "pack_id": "managed-test-pack", "installed_files": []},
    )

    assert "abandoned-mod-1.0.jar" in res["mods_cleaned"]
    assert not abandoned_mod.exists()
    assert persisting_mod.exists()


def test_adv_quarantine_duplicate_pruning_different_version(tmp_path: Path):
    """
    Adversarial challenge:
    mods-disabled-client/ has an older version of a mod (e.g. voicechat-1.0.0.jar).
    Staging brings voicechat-2.0.0.jar (same mod_id: 'voicechat').
    reconcile_and_cleanup_modpack must prune the old quarantined copy via Method B!
    """
    srv = tmp_path / "srv_quar_adv"
    dis_d = srv / "mods-disabled-client"
    dis_d.mkdir(parents=True)

    old_quarantined = make_dummy_jar(
        dis_d / "voicechat-fabric-1.20.1-1.0.0.jar",
        mod_id="voicechat",
        version="1.0.0",
        environment="client",
    )

    staging = tmp_path / "staging_quar_adv"
    staging_mods = staging / "mods"
    staging_mods.mkdir(parents=True)
    make_dummy_jar(
        staging_mods / "voicechat-fabric-1.20.1-2.5.0.jar",
        mod_id="voicechat",
        version="2.5.0",
        environment="client",
    )

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={"installed_files": []},
    )

    assert "voicechat-fabric-1.20.1-1.0.0.jar" in res["mods_cleaned"]
    assert not old_quarantined.exists()


def test_adv_allowlist_preserves_mod_in_both_mods_and_quarantine(tmp_path: Path):
    """
    Allowlisted client mods are strictly immune to deletion in both mods/
    and mods-disabled-client/.
    """
    srv = tmp_path / "srv_al_adv"
    mods_d = srv / "mods"
    dis_d = srv / "mods-disabled-client"
    mods_d.mkdir(parents=True)
    dis_d.mkdir(parents=True)

    mod_in_mods = make_dummy_jar(mods_d / "client-hud-1.0.jar", mod_id="clienthud")
    mod_in_dis = make_dummy_jar(dis_d / "client-minimap-1.0.jar", mod_id="clientminimap")

    add_to_allowlist(srv, pattern="*client-hud*", mod_name="HUD")
    add_to_allowlist(srv, pattern="*client-minimap*", mod_name="Minimap")

    # Staging has none of these
    staging = tmp_path / "staging_al_adv"
    staging.mkdir()

    # Previous meta marks both as dropped installed files
    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={
            "installed_files": [
                "mods/client-hud-1.0.jar",
                "mods/client-minimap-1.0.jar",
            ]
        },
    )

    # NEITHER file should be in mods_cleaned, BOTH must remain on disk
    assert "client-hud-1.0.jar" not in res["mods_cleaned"]
    assert "client-minimap-1.0.jar" not in res["mods_cleaned"]
    assert mod_in_mods.exists()
    assert mod_in_dis.exists()


def test_adv_protected_paths_never_pruned_by_cleanup(tmp_path: Path):
    """
    Malicious or corrupted previous_meta specifies protected files (server.properties,
    user_jvm_args.txt, world/level.dat). reconcile_and_cleanup_modpack MUST NOT delete them.
    """
    srv = tmp_path / "srv_prot_adv"
    srv.mkdir(parents=True)
    (srv / "server.properties").write_text("level-name=world\n", encoding="utf-8")
    (srv / "user_jvm_args.txt").write_text("-Xmx4G\n", encoding="utf-8")
    (srv / "world").mkdir()
    (srv / "world" / "level.dat").write_bytes(b"SACRED_DATA")

    staging = tmp_path / "staging_prot_adv"
    staging.mkdir()

    res = reconcile_and_cleanup_modpack(
        server_dir=srv,
        staging_dir=staging,
        previous_meta={
            "installed_files": [
                "server.properties",
                "user_jvm_args.txt",
                "world/level.dat",
            ]
        },
    )

    # NONE of them were removed
    assert len(res["files_removed"]) == 0
    assert (srv / "server.properties").exists()
    assert (srv / "user_jvm_args.txt").exists()
    assert (srv / "world" / "level.dat").exists()


# ============================================================================
# Category 4: Loader Migration & Artifact Cleanup
# ============================================================================

def test_adv_clean_obsolete_artifacts_preserves_multicore_agent_and_user_jvm_args(tmp_path: Path):
    """
    clean_obsolete_loader_artifacts purges old loader run scripts and launcher jars,
    but MUST NEVER delete mc-multicore-agent.jar or user_jvm_args.txt.
    """
    srv = tmp_path / "srv_loader_adv"
    srv.mkdir(parents=True)

    # Old loader artifacts
    (srv / "run.sh").write_text("#!/bin/sh\nrun", encoding="utf-8")
    (srv / "run.bat").write_text("@echo off", encoding="utf-8")
    (srv / "forge-1.20.1-47.2.0.jar").write_bytes(b"FORGE_BIN")

    # Multi-Core artifacts (must be protected!)
    (srv / "mc-multicore-agent.jar").write_bytes(b"AGENT_JAR")
    (srv / "user_jvm_args.txt").write_text("-javaagent:mc-multicore-agent.jar\n", encoding="utf-8")

    cleaned = clean_obsolete_loader_artifacts(
        server_dir=srv,
        current_loader="forge",
        target_loader="neoforge",
        mc_version_changed=True,
    )

    # Assertions
    assert "run.sh" in cleaned
    assert "forge-1.20.1-47.2.0.jar" in cleaned
    assert not (srv / "run.sh").exists()
    assert not (srv / "forge-1.20.1-47.2.0.jar").exists()

    # Sacred MultiCore files MUST survive!
    assert (srv / "mc-multicore-agent.jar").exists()
    assert (srv / "user_jvm_args.txt").exists()
    assert "mc-multicore-agent.jar" not in cleaned
    assert "user_jvm_args.txt" not in cleaned


def test_adv_size_collision_with_mismatched_sha1_must_download(tmp_path: Path):
    """
    CRITICAL EMPIRICAL CHALLENGE:
    Target manifest specifies a new mod version with an explicit SHA1 hash.
    A local file exists with the SAME filename and SAME file size, but a DIFFERENT SHA1
    (e.g., an update that happens to have identical file size).
    _stage_modpack_version MUST NOT falsely reuse the local file! It MUST download the new file!
    """
    srv = tmp_path / "adv_col_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    old_jar_content = b"OLD_VERSION_CONTENT_PADDING_" + (b"A" * 500)
    old_jar = mods_d / "colliding-mod-1.0.jar"
    old_jar.write_bytes(old_jar_content)
    old_sha1 = hashlib.sha1(old_jar_content).hexdigest().lower()

    new_jar_content = b"NEW_VERSION_CONTENT_PADDING_" + (b"B" * 500)
    assert len(new_jar_content) == len(old_jar_content), "Must be identical size"
    new_sha1 = hashlib.sha1(new_jar_content).hexdigest().lower()
    assert new_sha1 != old_sha1, "Must have different hashes"

    staging = tmp_path / "staging_col"
    tmpdir = tmp_path / "tmp_col"
    staging.mkdir()
    tmpdir.mkdir()

    mr_index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "v2.0",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
        "files": [
            {
                "path": "mods/colliding-mod-1.0.jar",
                "hashes": {"sha1": new_sha1},  # Explicit new SHA1!
                "downloads": ["http://remote.cdn/colliding-mod-1.0.jar"],
                "fileSize": len(new_jar_content),
            }
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(mr_index))
    mrpack_bytes = buf.getvalue()

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(new_jar_content)

    with patch("requests.get", return_value=MockHttpResponse(mrpack_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="modrinth",
                provider=MagicMock(),
                pack_id="pack-col",
                target_version_obj={"files": [{"url": "http://remote.cdn/pack.mrpack"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    # STRICT EMPIRICAL ASSERTIONS:
    # Because SHA1 did not match, the local file must NOT be reused!
    assert len(remote_download_calls) == 1, (
        f"Security/Correctness violation: old file with wrong SHA1 was reused due to size collision! "
        f"Calls: {remote_download_calls}"
    )
    assert result["reused_mods_count"] == 0
    staged_file = staging / "mods" / "colliding-mod-1.0.jar"
    assert staged_file.read_bytes() == new_jar_content


def test_adv_ftb_size_collision_with_mismatched_sha1(tmp_path: Path):
    """
    CRITICAL EMPIRICAL CHALLENGE (FTB):
    FTB manifest specifies a mod with an explicit SHA1.
    Local file exists with same name and same size, but DIFFERENT SHA1.
    _stage_modpack_version MUST NOT falsely reuse the local file! It MUST download the new file!
    """
    srv = tmp_path / "adv_ftb_col_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    old_content = b"OLD_FTB_JAR_DATA_" + (b"X" * 600)
    (mods_d / "ftb-mod-1.0.jar").write_bytes(old_content)
    old_sha1 = hashlib.sha1(old_content).hexdigest().lower()

    new_content = b"NEW_FTB_JAR_DATA_" + (b"Y" * 600)
    new_sha1 = hashlib.sha1(new_content).hexdigest().lower()
    assert new_sha1 != old_sha1
    assert len(new_content) == len(old_content)

    staging = tmp_path / "staging_ftb_col"
    tmpdir = tmp_path / "tmp_ftb_col"
    staging.mkdir()
    tmpdir.mkdir()

    mock_provider = MagicMock()
    mock_provider.get_version_manifest.return_value = {
        "targets": [{"type": "game", "version": "1.20.1"}, {"type": "modloader", "name": "forge", "version": "47.2.0"}],
        "files": [
            {
                "name": "ftb-mod-1.0.jar",
                "path": "mods/",
                "url": "http://ftb.cdn/ftb-mod-1.0.jar",
                "sha1": new_sha1,  # New SHA1!
                "size": len(new_content),
                "clientonly": False,
            }
        ],
    }

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(new_content)

    with patch("modpack_routes._download_to", side_effect=spy_download_to):
        result = _stage_modpack_version(
            provider_id="ftb",
            provider=mock_provider,
            pack_id="ftb-pack",
            target_version_obj={"id": "v1"},
            staging_dir=staging,
            tmpdir=tmpdir,
            server_dir=srv,
        )

    assert len(remote_download_calls) == 1, (
        f"FTB Correctness violation: old file with wrong SHA1 was reused due to size collision! "
        f"Calls: {remote_download_calls}"
    )
    assert result["reused_mods_count"] == 0


def test_adv_curseforge_size_collision_with_mismatched_fingerprint(tmp_path: Path):
    """
    CRITICAL EMPIRICAL CHALLENGE (CurseForge):
    CurseForge manifest specifies a mod with an explicit fingerprint (Murmur2).
    Local file has same name and same size, but DIFFERENT fingerprint.
    _stage_modpack_version MUST NOT falsely reuse the local file! It MUST download the new file!
    """
    from compat.evidence.collectors.remote import _cf_fingerprint

    srv = tmp_path / "adv_cf_col_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    old_content = b"OLD_CF_JAR_DATA_" + (b"M" * 700)
    (mods_d / "cf-colliding-1.0.jar").write_bytes(old_content)
    old_fp = _cf_fingerprint(str(mods_d / "cf-colliding-1.0.jar"))

    new_content = b"NEW_CF_JAR_DATA_" + (b"N" * 700)
    temp_target = tmp_path / "temp_cf_target.jar"
    temp_target.write_bytes(new_content)
    new_fp = _cf_fingerprint(str(temp_target))

    assert new_fp != old_fp, "Fingerprints must differ"
    assert len(new_content) == len(old_content), "Sizes must match for size collision"

    staging = tmp_path / "staging_cf_col"
    tmpdir = tmp_path / "tmp_cf_col"
    staging.mkdir()
    tmpdir.mkdir()

    cf_mani = {
        "minecraft": {"version": "1.20.1", "modLoaders": [{"id": "neoforge-20.4.253"}]},
        "files": [{"projectID": 111, "fileID": 222}],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(cf_mani))
    cf_zip_bytes = buf.getvalue()

    mock_provider = MagicMock()
    mock_provider.expand_manifest_files.return_value = [
        {
            "id": 222,
            "fileName": "cf-colliding-1.0.jar",
            "downloadUrl": "http://cf.cdn/cf-colliding-1.0.jar",
            "fingerprint": new_fp,  # Explicit new fingerprint!
            "fileLength": len(new_content),
            "hashes": [],  # No sha1 provided, relies on fingerprint
        }
    ]

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(new_content)

    with patch("requests.get", return_value=MockHttpResponse(cf_zip_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="curseforge",
                provider=mock_provider,
                pack_id="cf-col-pack",
                target_version_obj={"files": [{"url": "http://cf.cdn/pack.zip"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    assert len(remote_download_calls) == 1, (
        f"CurseForge Correctness violation: old file with wrong fingerprint was reused due to size collision! "
        f"Calls: {remote_download_calls}"
    )
    assert result["reused_mods_count"] == 0


