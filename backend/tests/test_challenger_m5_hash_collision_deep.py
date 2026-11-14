"""Deep Adversarial Challenge Test Suite for Milestone 5 Iteration 2:
Empirical Verification of Hash Fallback and Size-Collision Closure across FTB, Modrinth, and CurseForge.
Authored by challenger_m5_iter2_1.
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

os.environ.setdefault("SECRET_KEY", "test-secret-key-challenger-m5-deep-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(tempfile.gettempdir()) / "_tmp_servers_challenger_m5_deep"))
os.environ.setdefault("STATS_DB_PATH", str(Path(tempfile.gettempdir()) / "_tmp_stats_challenger_m5_deep.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

import modpack_routes
from modpack_routes import (
    _index_local_server_mods,
    _stage_modpack_version,
)
from compat.evidence.collectors.remote import _cf_fingerprint


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


def make_dummy_jar(
    jar_path: Path,
    mod_id: str,
    version: str = "1.0.0",
    payload: bytes = b"",
) -> Path:
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        f_mod = {
            "schemaVersion": 1,
            "id": mod_id,
            "version": version,
            "name": mod_id.capitalize(),
        }
        zf.writestr("fabric.mod.json", json.dumps(f_mod))
        if payload:
            zf.writestr("data/payload.bin", payload)
    return jar_path


# ============================================================================
# Deep Challenge 1: Modrinth SHA-512 Fallback & Collision Resistance
# ============================================================================

def test_deep_modrinth_sha512_collision_triggers_download(tmp_path: Path):
    """
    When Modrinth manifest has NO sha1, but DOES have sha512:
    A local file with identical filename and identical size but differing SHA512
    MUST NOT be reused! Must trigger remote download.
    """
    srv = tmp_path / "deep_mr_col_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    old_content = b"LOCAL_OLD_SHA512_FILE_" + (b"A" * 512)
    local_jar = mods_d / "sha512-mod-1.0.jar"
    local_jar.write_bytes(old_content)
    old_sha512 = hashlib.sha512(old_content).hexdigest().lower()

    new_content = b"REMOTE_NEW_SHA512_FILE" + (b"B" * 512)
    assert len(new_content) == len(old_content), "Sizes must collide"
    new_sha512 = hashlib.sha512(new_content).hexdigest().lower()
    assert new_sha512 != old_sha512

    staging = tmp_path / "staging_mr_512"
    tmpdir = tmp_path / "tmp_mr_512"
    staging.mkdir()
    tmpdir.mkdir()

    mr_index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "v1.0",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
        "files": [
            {
                "path": "mods/sha512-mod-1.0.jar",
                "hashes": {"sha512": new_sha512},  # Only sha512, NO sha1!
                "downloads": ["http://remote.cdn/sha512-mod-1.0.jar"],
                "fileSize": len(new_content),
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
        dest_file.write_bytes(new_content)

    with patch("requests.get", return_value=MockHttpResponse(mrpack_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="modrinth",
                provider=MagicMock(),
                pack_id="pack-512",
                target_version_obj={"files": [{"url": "http://remote.cdn/pack.mrpack"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    assert len(remote_download_calls) == 1, (
        f"Modrinth SHA512 collision violation: local file with mismatched SHA512 was reused! Calls: {remote_download_calls}"
    )
    assert result["reused_mods_count"] == 0
    assert (staging / "mods" / "sha512-mod-1.0.jar").read_bytes() == new_content


def test_deep_modrinth_sha512_match_reuses_locally(tmp_path: Path):
    """
    When Modrinth manifest has NO sha1, but DOES have sha512:
    A local file with matching SHA512 MUST be reused locally with 0 downloads.
    """
    srv = tmp_path / "deep_mr_reuse_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    content = b"LOCAL_MATCHING_SHA512_FILE_" + (b"Z" * 512)
    local_jar = mods_d / "sha512-match-1.0.jar"
    local_jar.write_bytes(content)
    sha512_val = hashlib.sha512(content).hexdigest().lower()

    staging = tmp_path / "staging_mr_reuse"
    tmpdir = tmp_path / "tmp_mr_reuse"
    staging.mkdir()
    tmpdir.mkdir()

    mr_index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "v1.0",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
        "files": [
            {
                "path": "mods/sha512-match-1.0.jar",
                "hashes": {"sha512": sha512_val},
                "downloads": ["http://remote.cdn/sha512-match-1.0.jar"],
                "fileSize": len(content),
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
        dest_file.write_bytes(content)

    with patch("requests.get", return_value=MockHttpResponse(mrpack_bytes)):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="modrinth",
                provider=MagicMock(),
                pack_id="pack-reuse-512",
                target_version_obj={"files": [{"url": "http://remote.cdn/pack.mrpack"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    assert len(remote_download_calls) == 0, f"Expected 0 downloads, got: {remote_download_calls}"
    assert result["reused_mods_count"] == 1
    assert (staging / "mods" / "sha512-match-1.0.jar").read_bytes() == content


# ============================================================================
# Deep Challenge 2: CurseForge Unexpanded Manifest Size-Collision
# ============================================================================

def test_deep_curseforge_unexpanded_fingerprint_collision_triggers_download(tmp_path: Path):
    """
    CurseForge unexpanded manifest fallback (where provider does NOT have expand_manifest_files):
    When the CurseForge API returns file data with fingerprint/sha1:
    A local file with identical filename and size but mismatched fingerprint
    MUST NOT be reused! Must trigger remote download.
    """
    srv = tmp_path / "deep_cf_unexp_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    old_content = b"OLD_CF_UNEXP_CONTENT_" + (b"X" * 650)
    (mods_d / "unexp-mod-1.0.jar").write_bytes(old_content)
    old_fp = _cf_fingerprint(str(mods_d / "unexp-mod-1.0.jar"))

    new_content = b"NEW_CF_UNEXP_CONTENT_" + (b"Y" * 650)
    assert len(new_content) == len(old_content)
    target_tmp = tmp_path / "target_tmp.jar"
    target_tmp.write_bytes(new_content)
    new_fp = _cf_fingerprint(str(target_tmp))
    assert new_fp != old_fp

    staging = tmp_path / "staging_cf_unexp"
    tmpdir = tmp_path / "tmp_cf_unexp"
    staging.mkdir()
    tmpdir.mkdir()

    # Manifest has files list
    cf_mani = {
        "minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.2.0"}]},
        "files": [{"projectID": 8888, "fileID": 9999}],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(cf_mani))
    cf_zip_bytes = buf.getvalue()

    # Provider WITHOUT expand_manifest_files
    mock_provider = MagicMock(spec=["_headers"])
    mock_provider._headers.return_value = {"x-api-key": "fake"}

    # Mock response for /mods/8888/files/9999
    api_response_data = {
        "data": {
            "id": 9999,
            "fileName": "unexp-mod-1.0.jar",
            "downloadUrl": "http://cf.cdn/unexp-mod-1.0.jar",
            "fileLength": len(new_content),
            "fingerprint": new_fp,
            "hashes": [],
        }
    }

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(new_content)

    def mock_get(url, *args, **kwargs):
        if "pack.zip" in url:
            return MockHttpResponse(cf_zip_bytes)
        elif "/mods/8888/files/9999" in url:
            return MockHttpResponse(json.dumps(api_response_data).encode("utf-8"))
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=mock_get):
        with patch("modpack_routes._download_to", side_effect=spy_download_to):
            result = _stage_modpack_version(
                provider_id="curseforge",
                provider=mock_provider,
                pack_id="cf-unexp-pack",
                target_version_obj={"files": [{"url": "http://cf.cdn/pack.zip"}]},
                staging_dir=staging,
                tmpdir=tmpdir,
                server_dir=srv,
            )

    assert len(remote_download_calls) == 1, (
        f"CurseForge unexpanded violation: old file with wrong fingerprint was reused! Calls: {remote_download_calls}"
    )
    assert result["reused_mods_count"] == 0
    assert (staging / "mods" / "unexp-mod-1.0.jar").read_bytes() == new_content


# ============================================================================
# Deep Challenge 3: Case-Insensitivity of Hex Hashes in Manifests
# ============================================================================

def test_deep_ftb_uppercase_sha1_matches_lowercase_local_index(tmp_path: Path):
    """
    Manifest provides UPPERCASE SHA1 (e.g. from an API response).
    Local index produces lowercase hex.
    Must successfully match and reuse locally with 0 downloads!
    """
    srv = tmp_path / "deep_ftb_case_srv"
    mods_d = srv / "mods"
    mods_d.mkdir(parents=True)

    content = b"FTB_UPPERCASE_SHA1_TEST_CONTENT_" + (b"K" * 300)
    (mods_d / "ftb-upper-1.0.jar").write_bytes(content)
    raw_sha1 = hashlib.sha1(content).hexdigest()
    upper_sha1 = raw_sha1.upper()

    staging = tmp_path / "staging_ftb_upper"
    tmpdir = tmp_path / "tmp_ftb_upper"
    staging.mkdir()
    tmpdir.mkdir()

    mock_provider = MagicMock()
    mock_provider.get_version_manifest.return_value = {
        "targets": [{"type": "game", "version": "1.20.1"}],
        "files": [
            {
                "name": "ftb-upper-1.0.jar",
                "path": "mods/",
                "url": "http://ftb.cdn/ftb-upper-1.0.jar",
                "sha1": upper_sha1,  # UPPERCASE!
                "size": len(content),
                "clientonly": False,
            }
        ],
    }

    remote_download_calls = []
    def spy_download_to(dest_file, url, timeout=120):
        remote_download_calls.append(url)
        dest_file.write_bytes(content)

    with patch("modpack_routes._download_to", side_effect=spy_download_to):
        result = _stage_modpack_version(
            provider_id="ftb",
            provider=mock_provider,
            pack_id="ftb-upper-pack",
            target_version_obj={"id": "v1"},
            staging_dir=staging,
            tmpdir=tmpdir,
            server_dir=srv,
        )

    assert len(remote_download_calls) == 0, f"Expected 0 downloads for matching uppercase SHA1, got: {remote_download_calls}"
    assert result["reused_mods_count"] == 1
    assert (staging / "mods" / "ftb-upper-1.0.jar").read_bytes() == content
