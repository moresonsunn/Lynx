"""Comprehensive tests for Client-Only-Allowlist tracking, sync, and filter preservation.

Tests cover:
1. Adding allowlist entries with timestamp, mod_name, and status.
2. Querying allowlist entries via GET (both patterns and entries).
3. Deleting allowlist entries via DELETE (query param & request body).
4. Ensuring files matching allowlist patterns are NOT moved by scan_and_filter() and filter_server_mods().
5. Fallback & bidirectional sync between client-only-allow.json and client-only-allow.txt.
6. Role-based access control and permissions on whitelist API endpoints.
"""

from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Union

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(__file__).parent / "_tmp_servers"))
os.environ.setdefault("STATS_DB_PATH", str(Path(__file__).parent / "_tmp_stats.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

from client_mod_filter import (
    ClientModFilter,
    FilterAction,
    add_to_allowlist,
    get_allowlist_entries,
    is_mod_allowlisted,
    remove_from_allowlist,
    sync_allowlist,
)
from mod_side_resolver import ModSideResolver
from tests.test_auth_users_api import engine, db_session, client, _login  # noqa: F401


# ============================================================================
# Helpers & Fixtures
# ============================================================================

def create_mod_jar(jar_path: Path, files: Dict[str, Union[bytes, str]]) -> Path:
    """Creates a real zip/jar file containing the specified manifest files."""
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(arcname, data)
    return jar_path


@pytest.fixture
def mock_server(tmp_path: Path) -> Path:
    """Initializes a clean server directory structure."""
    server_dir = tmp_path / "TestServer"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "mods").mkdir(parents=True, exist_ok=True)
    return server_dir


# ============================================================================
# 1. Allowlist CRUD & Metadata Tests
# ============================================================================

def test_add_allowlist_entry_with_metadata(mock_server: Path):
    """Test adding an allowlist entry stores pattern, timestamp, mod_name, and status."""
    entry = add_to_allowlist(
        server_dir=mock_server,
        pattern="appleskin*",
        mod_name="AppleSkin",
        added_by="admin",
        notes="HUD mod allowed for convenience",
    )

    assert entry["pattern"] == "appleskin*"
    assert entry["mod_name"] == "AppleSkin"
    assert entry["added_by"] == "admin"
    assert entry["status"] == "active"
    assert entry["notes"] == "HUD mod allowed for convenience"
    # Ensure added_at is a valid ISO-8601 UTC timestamp
    assert datetime.fromisoformat(entry["added_at"].replace("Z", "+00:00")) is not None

    # Verify client-only-allow.json contents
    json_file = mock_server / "client-only-allow.json"
    assert json_file.exists()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["entries"]) == 1
    assert data["entries"][0]["pattern"] == "appleskin*"

    # Verify client-only-allow.txt mirror
    txt_file = mock_server / "client-only-allow.txt"
    assert txt_file.exists()
    lines = [l.strip() for l in txt_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert "appleskin*" in lines


def test_get_allowlist_entries_structure(mock_server: Path):
    """Test querying allowlist entries returns structured metadata."""
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin", added_by="admin")
    add_to_allowlist(mock_server, pattern="jei*", mod_name="Just Enough Items", added_by="mod1")

    entries = get_allowlist_entries(mock_server)
    assert len(entries) == 2
    patterns = [e["pattern"] for e in entries]
    assert "appleskin*" in patterns
    assert "jei*" in patterns
    for e in entries:
        assert "added_at" in e
        assert e["status"] == "active"


def test_delete_allowlist_entry(mock_server: Path):
    """Test deleting allowlist entries removes from both JSON and TXT."""
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin")
    add_to_allowlist(mock_server, pattern="jei*", mod_name="JEI")

    removed = remove_from_allowlist(mock_server, pattern="appleskin*")
    assert removed is True

    entries = get_allowlist_entries(mock_server)
    assert len(entries) == 1
    assert entries[0]["pattern"] == "jei*"

    txt_lines = [l.strip() for l in (mock_server / "client-only-allow.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert "appleskin*" not in txt_lines
    assert "jei*" in txt_lines

    # Removing non-existent pattern returns False
    assert remove_from_allowlist(mock_server, pattern="nonexistent*") is False


def test_add_duplicate_pattern_is_idempotent(mock_server: Path):
    """Test adding an existing pattern updates notes/status rather than duplicating."""
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin", notes="v1")
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin Updated", notes="v2")

    entries = get_allowlist_entries(mock_server)
    assert len(entries) == 1
    assert entries[0]["notes"] == "v2"
    assert entries[0]["mod_name"] == "AppleSkin Updated"


# ============================================================================
# 2. Fallback & Bidirectional Sync Tests
# ============================================================================

def test_sync_from_legacy_txt_only(mock_server: Path):
    """Test that if only client-only-allow.txt exists, it is migrated to JSON with metadata."""
    txt_file = mock_server / "client-only-allow.txt"
    txt_file.write_text("# Legacy allowlist\nappleskin*\n\njei*\n# end comment\n", encoding="utf-8")

    entries = get_allowlist_entries(mock_server)
    assert len(entries) == 2
    patterns = {e["pattern"] for e in entries}
    assert patterns == {"appleskin*", "jei*"}

    # JSON should now exist
    json_file = mock_server / "client-only-allow.json"
    assert json_file.exists()
    for e in entries:
        assert e["status"] == "active"
        assert e["added_by"] in ("legacy_txt", "legacy_sync", "file_sync")


def test_sync_from_json_to_txt_mirror(mock_server: Path):
    """Test that client-only-allow.txt is recreated from JSON if missing."""
    add_to_allowlist(mock_server, pattern="sodium*", mod_name="Sodium")
    txt_file = mock_server / "client-only-allow.txt"
    if txt_file.exists():
        txt_file.unlink()

    sync_allowlist(mock_server)
    assert txt_file.exists()
    assert "sodium*" in txt_file.read_text(encoding="utf-8")


def test_sync_when_txt_modified_externally(mock_server: Path):
    """Test external manual edit of TXT is synced into JSON without losing existing metadata."""
    add_to_allowlist(mock_server, pattern="appleskin*", mod_name="AppleSkin", notes="original note")

    txt_file = mock_server / "client-only-allow.txt"
    with open(txt_file, "a", encoding="utf-8") as f:
        f.write("\niris*\n")

    # Touch txt file mtime to 5 seconds in future relative to json
    future_time = time.time() + 5
    os.utime(txt_file, (future_time, future_time))

    entries = get_allowlist_entries(mock_server)
    patterns = {e["pattern"]: e for e in entries}
    assert "appleskin*" in patterns
    assert "iris*" in patterns
    # Original notes must not be lost
    assert patterns["appleskin*"]["notes"] == "original note"
    assert patterns["iris*"]["status"] == "active"


def test_sync_handles_corrupt_json_gracefully(mock_server: Path):
    """Test corrupt JSON falls back to TXT without crashing."""
    txt_file = mock_server / "client-only-allow.txt"
    txt_file.write_text("appleskin*\n", encoding="utf-8")

    json_file = mock_server / "client-only-allow.json"
    json_file.write_text("{corrupt: true, invalid", encoding="utf-8")

    entries = get_allowlist_entries(mock_server)
    assert len(entries) >= 1
    assert any(e["pattern"] == "appleskin*" for e in entries)


# ============================================================================
# 3. Glob & Mod ID Matching Tests
# ============================================================================

def test_is_mod_allowlisted_glob_matching(mock_server: Path):
    """Test wildcard filename matching."""
    add_to_allowlist(mock_server, pattern="appleskin*")
    add_to_allowlist(mock_server, pattern="jei-*.jar")

    assert is_mod_allowlisted(mock_server, filename="appleskin-1.20.1-fabric.jar") is True
    assert is_mod_allowlisted(mock_server, filename="jei-1.20.1-forge-15.0.0.jar") is True
    assert is_mod_allowlisted(mock_server, filename="sodium-fabric-0.6.0.jar") is False


def test_is_mod_allowlisted_mod_id_matching(mock_server: Path):
    """Test matching against mod_id."""
    add_to_allowlist(mock_server, pattern="sodium")

    assert is_mod_allowlisted(mock_server, filename="rubidium-mc1.20.jar", mod_id="sodium") is True
    assert is_mod_allowlisted(mock_server, filename="other-mod.jar", mod_id="other") is False


def test_is_mod_allowlisted_case_insensitive(mock_server: Path):
    """Test pattern matching is case-insensitive."""
    add_to_allowlist(mock_server, pattern="AppleSkin*")

    assert is_mod_allowlisted(mock_server, filename="appleskin-fabric.jar") is True
    assert is_mod_allowlisted(mock_server, filename="APPLESKIN-FORGE.JAR") is True


def test_is_mod_allowlisted_disabled_status(mock_server: Path):
    """Test that disabled allowlist entries are ignored."""
    add_to_allowlist(mock_server, pattern="sodium*", status="disabled")

    assert is_mod_allowlisted(mock_server, filename="sodium-fabric-0.6.0.jar") is False


# ============================================================================
# 4. Filter Preservation Tests
# ============================================================================

def test_scan_and_filter_preserves_allowlisted_mod(mock_server: Path):
    """Test that a CLIENT_ONLY mod is preserved in mods/ if allowlisted."""
    mods_dir = mock_server / "mods"
    disabled_dir = mock_server / "mods-disabled-client"

    # 1. sodium: client-only
    create_mod_jar(
        mods_dir / "sodium-fabric-0.6.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.6.0",
                "environment": "client",
            })
        },
    )

    # 2. iris: client-only (not whitelisted)
    create_mod_jar(
        mods_dir / "iris-fabric-1.7.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "iris",
                "version": "1.7.0",
                "environment": "client",
            })
        },
    )

    # 3. fabric-api: both sides required
    create_mod_jar(
        mods_dir / "fabric-api-0.90.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "fabric-api",
                "version": "0.90.0",
                "environment": "*",
            })
        },
    )

    # Allowlist sodium
    add_to_allowlist(mock_server, pattern="sodium*", mod_name="Sodium")

    filter_sys = ClientModFilter(mock_server)
    result = filter_sys.scan_and_filter(dry_run=False, use_allowlist=True)

    # Sodium must STILL be in mods/
    assert (mods_dir / "sodium-fabric-0.6.0.jar").exists()
    # Iris must be moved to mods-disabled-client/
    assert not (mods_dir / "iris-fabric-1.7.0.jar").exists()
    assert (disabled_dir / "iris-fabric-1.7.0.jar").exists()
    # Fabric-api must still be in mods/
    assert (mods_dir / "fabric-api-0.90.0.jar").exists()

    # Decisions check
    decisions = {d["file_name"]: d for d in result["decisions"]}
    assert decisions["sodium-fabric-0.6.0.jar"]["action"] == FilterAction.WHITELISTED.value
    assert decisions["sodium-fabric-0.6.0.jar"]["whitelisted"] is True
    assert decisions["iris-fabric-1.7.0.jar"]["action"] == FilterAction.DISABLED.value
    assert result["disabled_count"] == 1
    assert result["whitelisted_count"] == 1


def test_scan_and_filter_dry_run_preserves_files(mock_server: Path):
    """Test dry run moves no files but correctly flags actions."""
    mods_dir = mock_server / "mods"
    disabled_dir = mock_server / "mods-disabled-client"

    create_mod_jar(
        mods_dir / "iris-fabric-1.7.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "iris",
                "version": "1.7.0",
                "environment": "client",
            })
        },
    )

    filter_sys = ClientModFilter(mock_server)
    res = filter_sys.scan_and_filter(dry_run=True, use_allowlist=True)

    # No files should have moved
    assert (mods_dir / "iris-fabric-1.7.0.jar").exists()
    assert not disabled_dir.exists() or len(list(disabled_dir.glob("*.jar"))) == 0
    assert res["disabled_count"] == 1


def test_scan_and_filter_respects_use_allowlist_false(mock_server: Path):
    """Test that disabling use_allowlist moves even allowlisted mods."""
    mods_dir = mock_server / "mods"
    disabled_dir = mock_server / "mods-disabled-client"

    create_mod_jar(
        mods_dir / "sodium-fabric-0.6.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.6.0",
                "environment": "client",
            })
        },
    )

    add_to_allowlist(mock_server, pattern="sodium*")

    filter_sys = ClientModFilter(mock_server)
    res = filter_sys.scan_and_filter(dry_run=False, use_allowlist=False)

    assert not (mods_dir / "sodium-fabric-0.6.0.jar").exists()
    assert (disabled_dir / "sodium-fabric-0.6.0.jar").exists()
    assert res["disabled_count"] == 1


def test_mod_side_resolver_filter_server_mods_preserves_allowlist(mock_server: Path):
    """Test that ModSideResolver.filter_server_mods also respects allowlist."""
    mods_dir = mock_server / "mods"

    create_mod_jar(
        mods_dir / "sodium-fabric-0.6.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.6.0",
                "environment": "client",
            })
        },
    )
    add_to_allowlist(mock_server, pattern="sodium*")

    resolver = ModSideResolver(enable_network=False)
    report = resolver.filter_server_mods(server_dir=mock_server, dry_run=False, use_allowlist=True)

    assert (mods_dir / "sodium-fabric-0.6.0.jar").exists()
    assert report["moved_count"] == 0
    assert report["whitelisted_count"] == 1


def test_mod_side_resolver_filter_server_mods_allowlist_patterns_param(mock_server: Path):
    """Test passing explicit allowlist_patterns list to filter_server_mods."""
    mods_dir = mock_server / "mods"

    create_mod_jar(
        mods_dir / "sodium-fabric-0.6.0.jar",
        {
            "fabric.mod.json": json.dumps({
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.6.0",
                "environment": "client",
            })
        },
    )

    resolver = ModSideResolver(enable_network=False)
    report = resolver.filter_server_mods(
        server_dir=mock_server,
        dry_run=False,
        use_allowlist=False,
        allowlist_patterns=["sodium*"],
    )

    assert (mods_dir / "sodium-fabric-0.6.0.jar").exists()
    assert report["moved_count"] == 0
    assert report["whitelisted_count"] == 1


# ============================================================================
# 5. REST API Integration Tests
# ============================================================================

def test_api_whitelist_lifecycle(client, db_session, monkeypatch, tmp_path):
    """Test full API lifecycle: GET, POST with metadata, and DELETE via HTTP."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "TestApiServer"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "mods").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)

    admin_h = _login(client, "admin", "AdminPass123")

    # 1. Initially empty
    r = client.get("/api/client-mods/whitelist/TestApiServer", headers=admin_h)
    assert r.status_code == 200
    data = r.json()
    assert data["patterns"] == []
    assert data["entries"] == []

    # 2. Add entry with metadata
    r = client.post(
        "/api/client-mods/whitelist/TestApiServer",
        json={"pattern": "appleskin*", "mod_name": "AppleSkin", "notes": "HUD convenience"},
        headers=admin_h,
    )
    assert r.status_code == 200
    res_data = r.json()
    assert res_data["pattern"] == "appleskin*"
    assert res_data["entry"]["pattern"] == "appleskin*"
    assert res_data["entry"]["mod_name"] == "AppleSkin"
    assert res_data["entry"]["added_by"] == "admin"

    # 3. Query entries
    r = client.get("/api/client-mods/whitelist/TestApiServer", headers=admin_h)
    assert r.status_code == 200
    data = r.json()
    assert "appleskin*" in data["patterns"]
    assert len(data["entries"]) == 1
    assert data["entries"][0]["pattern"] == "appleskin*"
    assert data["entries"][0]["mod_name"] == "AppleSkin"
    assert data["entries"][0]["status"] == "active"
    assert data["entries"][0]["added_by"] == "admin"

    # 4. Add second entry
    r = client.post(
        "/api/client-mods/whitelist/TestApiServer",
        json={"pattern": "jei*", "mod_name": "JEI"},
        headers=admin_h,
    )
    assert r.status_code == 200

    # 5. Delete entry via query parameter
    r = client.delete("/api/client-mods/whitelist/TestApiServer?pattern=appleskin*", headers=admin_h)
    assert r.status_code == 200

    # 6. Delete entry via JSON body
    r = client.request("DELETE", "/api/client-mods/whitelist/TestApiServer", json={"pattern": "jei*"}, headers=admin_h)
    assert r.status_code == 200

    # 7. Verify deleted
    r = client.get("/api/client-mods/whitelist/TestApiServer", headers=admin_h)
    assert r.status_code == 200
    data = r.json()
    assert data["patterns"] == []
    assert data["entries"] == []


def test_api_whitelist_permissions(client, db_session, monkeypatch, tmp_path):
    """Test role requirements: anonymous blocked (401), non-moderator blocked (403)."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "TestPermServer"
    server_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)

    # Anonymous access blocked
    r = client.get("/api/client-mods/whitelist/TestPermServer")
    assert r.status_code == 401

    r = client.post("/api/client-mods/whitelist/TestPermServer", json={"pattern": "test*"})
    assert r.status_code == 401

    # Plain user cannot add or delete
    admin_h = _login(client, "admin", "AdminPass123")
    client.post(
        "/api/users",
        json={"username": "plain_user_allowlist", "email": "pua@localhost", "password": "UserPass123", "role": "user"},
        headers=admin_h,
    )
    user_h = _login(client, "plain_user_allowlist", "UserPass123")

    r = client.post("/api/client-mods/whitelist/TestPermServer", json={"pattern": "test*"}, headers=user_h)
    assert r.status_code == 403

    r = client.delete("/api/client-mods/whitelist/TestPermServer?pattern=test*", headers=user_h)
    assert r.status_code == 403


# ============================================================================
# 7. Milestone 1 Iteration 2 Enhancements
# ============================================================================

def test_bracket_filename_and_stem_allowlisting(mock_server: Path):
    """Test bracket filename matching, bracket globbing, and suffix guard."""
    from client_mod_filter import match_allowlist_pattern

    # Direct filename with brackets
    add_to_allowlist(mock_server, pattern="mod-(test)+[1].jar")
    assert is_mod_allowlisted(mock_server, "mod-(test)+[1].jar") is True
    assert is_mod_allowlisted(mock_server, "MOD-(TEST)+[1].JAR") is True
    assert is_mod_allowlisted(mock_server, "mod-(test)+[2].jar") is False

    # Bracket with wildcard
    assert match_allowlist_pattern("[1.20.1]appleskin*", "[1.20.1]appleskin-fabric-2.5.1.jar") is True

    # Suffix guard: exact_mod.jar must NOT match exact_mod.jar.bak
    add_to_allowlist(mock_server, pattern="exact_mod.jar")
    assert is_mod_allowlisted(mock_server, "exact_mod.jar") is True
    assert is_mod_allowlisted(mock_server, "exact_mod.jar.bak") is False
    assert is_mod_allowlisted(mock_server, "exact_mod.jar.disabled") is False


def test_sync_preserves_disabled_entries_and_bom(mock_server: Path):
    """Test sync_allowlist preserves disabled entries and strips UTF-8 BOM."""
    add_to_allowlist(mock_server, pattern="active_rule*", status="active")
    add_to_allowlist(mock_server, pattern="disabled_rule*", status="disabled", notes="Audit reason")

    txt_file = mock_server / "client-only-allow.txt"
    # Write external update with BOM
    bom_content = "\ufeff# Comments\nactive_rule*\nexternally_added*\n"
    txt_file.write_text(bom_content, encoding="utf-8")
    future_time = time.time() + 2.0
    os.utime(str(txt_file), (future_time, future_time))

    sync_allowlist(mock_server)

    entries = get_allowlist_entries(mock_server)
    patterns = {e["pattern"]: e.get("status") for e in entries}

    assert patterns.get("active_rule*") == "active"
    assert patterns.get("disabled_rule*") == "disabled"
    assert patterns.get("externally_added*") == "active"


def test_api_newline_rejection_and_added_at_fallback(client, db_session, monkeypatch, tmp_path):
    """Test API rejects newlines and handles missing added_at gracefully."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "TestRobustServer"
    server_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)
    admin_h = _login(client, "admin", "AdminPass123")

    # 1. Newline rejected in POST
    r = client.post(
        "/api/client-mods/whitelist/TestRobustServer",
        json={"pattern": "mod1*\nmod2*"},
        headers=admin_h,
    )
    assert r.status_code == 400
    assert "newline" in r.json()["detail"].lower()

    # 2. JSON with missing/null added_at is handled by response model
    json_path = server_dir / "client-only-allow.json"
    json_path.write_text(
        json.dumps({
            "version": 1,
            "entries": [
                {"pattern": "legacy_mod*", "added_at": None, "status": "active"},
            ],
        }),
        encoding="utf-8",
    )

    r = client.get("/api/client-mods/whitelist/TestRobustServer", headers=admin_h)
    assert r.status_code == 200
    data = r.json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["pattern"] == "legacy_mod*"
    assert data["entries"][0]["added_at"] is not None
