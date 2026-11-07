"""Adversarial stress-testing suite for Client-Only-Allowlist tracking and filtering.

Tests edge cases, boundary conditions, malicious payloads, concurrency,
file corruption resilience, and backward compatibility.
"""

from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, Union

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production-0123456789")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(__file__).parent / "_tmp_servers_adv"))
os.environ.setdefault("STATS_DB_PATH", str(Path(__file__).parent / "_tmp_stats_adv.db"))
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


def create_mod_jar(jar_path: Path, files: Dict[str, Union[bytes, str]]) -> Path:
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(arcname, data)
    return jar_path


@pytest.fixture
def adv_server(tmp_path: Path) -> Path:
    server_dir = tmp_path / "AdversarialServer"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "mods").mkdir(parents=True, exist_ok=True)
    return server_dir


# ============================================================================
# 1. Adversarial Patterns & Encodings (Unicode, Emojis, Long Strings, Special Chars)
# ============================================================================

def test_unicode_and_emojis_in_metadata(adv_server: Path):
    """Stress-test non-ASCII characters, German umlauts, Chinese characters, and emojis."""
    entry = add_to_allowlist(
        adv_server,
        pattern="äpfel-skin-*.jar",
        mod_name="ÄpfelSkin 🍎 Mod (日本語 / 中文)",
        notes="Erlaubt für Performance-Boost & Flüssigkeit 🚀🔥 — 测试备注",
        status="active",
        added_by="админ_user",
    )

    assert entry["pattern"] == "äpfel-skin-*.jar"
    assert "🍎" in entry["mod_name"]
    assert "🚀🔥" in entry["notes"]
    assert entry["added_by"] == "админ_user"

    # Verify retrieval
    entries = get_allowlist_entries(adv_server)
    assert len(entries) == 1
    loaded = entries[0]
    assert loaded["pattern"] == "äpfel-skin-*.jar"
    assert "🍎" in loaded["mod_name"]
    assert "🚀🔥" in loaded["notes"]

    # Verify JSON file has proper utf-8 encoding without mangled escape chars
    json_path = adv_server / "client-only-allow.json"
    raw_json = json_path.read_text(encoding="utf-8")
    assert "🍎" in raw_json
    assert "ÄpfelSkin" in raw_json

    # Matching test
    assert is_mod_allowlisted(adv_server, "äpfel-skin-1.0.jar") is True
    assert is_mod_allowlisted(adv_server, "ÄPFEL-SKIN-1.0.JAR") is True


def test_extreme_long_strings_stress(adv_server: Path):
    """Test resilience against very long strings in notes, pattern, and mod_name."""
    long_note = "A" * 10000
    long_mod_name = "SuperModName" + ("X" * 1000)
    long_pattern = "long_mod_pattern_" + ("y" * 200) + "*.jar"

    entry = add_to_allowlist(
        adv_server,
        pattern=long_pattern,
        mod_name=long_mod_name,
        notes=long_note,
    )

    assert entry["pattern"] == long_pattern
    assert len(entry["notes"]) == 10000

    entries = get_allowlist_entries(adv_server)
    assert len(entries) == 1
    assert len(entries[0]["notes"]) == 10000

    # Matching with long pattern
    target_file = f"long_mod_pattern_{'y'*200}_v1.jar"
    assert is_mod_allowlisted(adv_server, target_file) is True


def test_special_characters_and_wildcard_variations(adv_server: Path):
    """Test glob characters (*, ?, []), regex-like chars (+, ^, $, (, ), .), and spaces."""
    patterns = [
        "mod-with.dots.v[1-9].jar",
        "mod+plus+test-*.jar",
        "mod(parentheses)-*.jar",
        "mod with spaces *.jar",
        "?single_char_prefix_*.jar",
    ]

    for p in patterns:
        add_to_allowlist(adv_server, pattern=p)

    assert len(get_allowlist_entries(adv_server)) == len(patterns)

    # Test matching
    assert is_mod_allowlisted(adv_server, "mod-with.dots.v2.jar") is True
    assert is_mod_allowlisted(adv_server, "mod-with.dots.v0.jar") is False  # [1-9] doesn't match 0
    assert is_mod_allowlisted(adv_server, "mod+plus+test-1.0.jar") is True
    assert is_mod_allowlisted(adv_server, "mod(parentheses)-2.5.jar") is True
    assert is_mod_allowlisted(adv_server, "mod with spaces 1.0.jar") is True
    assert is_mod_allowlisted(adv_server, "xsingle_char_prefix_foo.jar") is True
    assert is_mod_allowlisted(adv_server, "xxsingle_char_prefix_foo.jar") is False


def test_prefix_overmatching_bug_investigation(adv_server: Path):
    """Investigate whether non-glob exact filename allowlist allows unrelated extensions."""
    add_to_allowlist(adv_server, pattern="exact_mod.jar")
    # Exact file should match
    assert is_mod_allowlisted(adv_server, "exact_mod.jar") is True

    # CHALLENGE CHECK: Does 'exact_mod.jar.bak' or 'exact_mod.jar.disabled' match?
    # Suffix overmatch must NOT allow bak or disabled files to pass through
    overmatches_bak = is_mod_allowlisted(adv_server, "exact_mod.jar.bak")
    overmatches_dis = is_mod_allowlisted(adv_server, "exact_mod.jar.disabled")
    
    assert overmatches_bak is False
    assert overmatches_dis is False


def test_newline_injection_investigation(adv_server: Path):
    """Verify that pattern containing newlines is rejected and cannot inject entries."""
    with pytest.raises(ValueError, match="newline"):
        add_to_allowlist(adv_server, pattern="modA\nmodB", mod_name="Injected")


# ============================================================================
# 2. Idempotency vs Update vs Case Sensitivity
# ============================================================================

def test_idempotent_add_and_update_preserves_added_at(adv_server: Path):
    """Adding same pattern repeatedly updates metadata without creating duplicates and keeps original added_at."""
    entry1 = add_to_allowlist(adv_server, pattern="jei*", mod_name="JEI v1", notes="First note", status="active")
    orig_added_at = entry1["added_at"]

    time.sleep(0.01)

    entry2 = add_to_allowlist(adv_server, pattern="JEI*", mod_name="JEI v2", notes="Second note", status="active")
    assert entry2["added_at"] == orig_added_at
    assert entry2["mod_name"] == "JEI v2"
    assert entry2["notes"] == "Second note"

    entries = get_allowlist_entries(adv_server)
    assert len(entries) == 1
    assert entries[0]["pattern"] == "JEI*"


def test_toggling_status_active_to_disabled_and_back(adv_server: Path):
    """Toggling status to 'disabled' stops matching and excludes pattern from TXT mirror."""
    add_to_allowlist(adv_server, pattern="sodium*", mod_name="Sodium", status="active")
    assert is_mod_allowlisted(adv_server, "sodium-0.5.jar") is True

    txt_lines = [l.strip() for l in (adv_server / "client-only-allow.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert "sodium*" in txt_lines

    # Toggle to disabled
    add_to_allowlist(adv_server, pattern="sodium*", status="disabled")
    assert is_mod_allowlisted(adv_server, "sodium-0.5.jar") is False

    txt_lines = [l.strip() for l in (adv_server / "client-only-allow.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert "sodium*" not in txt_lines

    # Reactivate
    add_to_allowlist(adv_server, pattern="sodium*", status="active")
    assert is_mod_allowlisted(adv_server, "sodium-0.5.jar") is True


# ============================================================================
# 3. Deletion Edge Cases (Case insensitivity, Non-existent, Empty)
# ============================================================================

def test_delete_case_insensitive_and_whitespace(adv_server: Path):
    """Deleting pattern should match case-insensitively and strip whitespace."""
    add_to_allowlist(adv_server, pattern="AppleSkin*")
    assert len(get_allowlist_entries(adv_server)) == 1

    # Delete with lower case and surrounding whitespace
    assert remove_from_allowlist(adv_server, "  appleskin*  ") is True
    assert len(get_allowlist_entries(adv_server)) == 0

    # Repeat delete returns False
    assert remove_from_allowlist(adv_server, "appleskin*") is False
    assert remove_from_allowlist(adv_server, "") is False
    assert remove_from_allowlist(adv_server, "   ") is False


# ============================================================================
# 4. Resilience to File Corruption and Out-of-Sync States
# ============================================================================

def test_corrupted_json_syntax_recovers_gracefully(adv_server: Path):
    """If JSON is corrupted (invalid syntax, truncated, wrong structure), system doesn't crash."""
    json_path = adv_server / "client-only-allow.json"
    txt_path = adv_server / "client-only-allow.txt"

    # Write broken JSON
    json_path.write_text("{ this is not valid json! truncated...", encoding="utf-8")
    txt_path.write_text("fallback-mod*\n", encoding="utf-8")

    entries = get_allowlist_entries(adv_server)
    # Should fall back to TXT without crashing
    assert len(entries) == 1
    assert entries[0]["pattern"] == "fallback-mod*"


def test_json_with_null_or_invalid_entries_array(adv_server: Path):
    """If JSON exists but entries is null, integer, or invalid type, handle gracefully."""
    json_path = adv_server / "client-only-allow.json"
    json_path.write_text(json.dumps({"version": 1, "entries": None}), encoding="utf-8")

    entries = get_allowlist_entries(adv_server)
    assert entries == []

    # Can still add without crash
    add_to_allowlist(adv_server, pattern="new-mod*")
    assert len(get_allowlist_entries(adv_server)) == 1


def test_txt_with_comments_and_empty_lines(adv_server: Path):
    """client-only-allow.txt with diverse comment styles and blank lines."""
    txt_path = adv_server / "client-only-allow.txt"
    txt_path.write_text(
        "# Server Allowlist\n"
        "\n"
        "   \n"
        "# Another comment\n"
        "valid-mod-1*\n"
        "\n"
        "valid-mod-2*\n"
        "# trailing comment\n",
        encoding="utf-8",
    )

    entries = get_allowlist_entries(adv_server)
    pats = [e["pattern"] for e in entries]
    assert pats == ["valid-mod-1*", "valid-mod-2*"]


# ============================================================================
# 5. REST API Adversarial Scenarios
# ============================================================================

def test_api_post_validation_and_edge_payloads(client, db_session, monkeypatch, tmp_path):
    """Test API behavior under boundary and invalid payloads."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "AdvApiServer"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "mods").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)
    admin_h = _login(client, "admin", "AdminPass123")

    # 1. Empty pattern rejected with 400
    r = client.post("/api/client-mods/whitelist/AdvApiServer", json={"pattern": ""}, headers=admin_h)
    assert r.status_code == 400

    r = client.post("/api/client-mods/whitelist/AdvApiServer", json={"pattern": "   "}, headers=admin_h)
    assert r.status_code == 400

    # 2. Missing pattern key rejected with 422
    r = client.post("/api/client-mods/whitelist/AdvApiServer", json={"notes": "no pattern"}, headers=admin_h)
    assert r.status_code == 422

    # 3. Non-existent server returns 404
    r = client.post("/api/client-mods/whitelist/NonExistentServer", json={"pattern": "test*"}, headers=admin_h)
    assert r.status_code == 404

    r = client.get("/api/client-mods/whitelist/NonExistentServer", headers=admin_h)
    assert r.status_code == 404

    r = client.delete("/api/client-mods/whitelist/NonExistentServer?pattern=test*", headers=admin_h)
    assert r.status_code == 404


def test_api_delete_query_vs_body_priority_and_errors(client, db_session, monkeypatch, tmp_path):
    """Test DELETE with various combinations of query params, bodies, and missing targets."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "DeleteTestServer"
    server_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)
    admin_h = _login(client, "admin", "AdminPass123")

    # Add two patterns
    client.post("/api/client-mods/whitelist/DeleteTestServer", json={"pattern": "patA*"}, headers=admin_h)
    client.post("/api/client-mods/whitelist/DeleteTestServer", json={"pattern": "patB*"}, headers=admin_h)

    # DELETE without query param and without body -> 400
    r = client.delete("/api/client-mods/whitelist/DeleteTestServer", headers=admin_h)
    assert r.status_code == 400

    # DELETE with empty query param and empty body -> 400
    r = client.request("DELETE", "/api/client-mods/whitelist/DeleteTestServer?pattern=", json={"pattern": ""}, headers=admin_h)
    assert r.status_code == 400

    # DELETE non-existent pattern -> 404
    r = client.delete("/api/client-mods/whitelist/DeleteTestServer?pattern=does_not_exist*", headers=admin_h)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()

    # Query param takes precedence over body if both provided
    r = client.request("DELETE", "/api/client-mods/whitelist/DeleteTestServer?pattern=patA*", json={"pattern": "patB*"}, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["pattern"] == "patA*"

    # Verify patA* is deleted, patB* still remains
    get_r = client.get("/api/client-mods/whitelist/DeleteTestServer", headers=admin_h)
    assert "patA*" not in get_r.json()["patterns"]
    assert "patB*" in get_r.json()["patterns"]

    # DELETE patB* via body
    r = client.request("DELETE", "/api/client-mods/whitelist/DeleteTestServer", json={"pattern": "patB*"}, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["pattern"] == "patB*"


def test_api_backward_compatibility_schema(client, db_session, monkeypatch, tmp_path):
    """Verify that GET returns both 'patterns' array of strings and 'entries' array of objects."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "CompatServer"
    server_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)
    admin_h = _login(client, "admin", "AdminPass123")

    client.post(
        "/api/client-mods/whitelist/CompatServer",
        json={"pattern": "appleskin*", "mod_name": "AppleSkin", "notes": "HUD", "status": "active"},
        headers=admin_h,
    )

    r = client.get("/api/client-mods/whitelist/CompatServer", headers=admin_h)
    assert r.status_code == 200
    data = r.json()

    # Strict check on contract
    assert "patterns" in data
    assert isinstance(data["patterns"], list)
    assert data["patterns"] == ["appleskin*"]

    assert "entries" in data
    assert isinstance(data["entries"], list)
    assert len(data["entries"]) == 1

    entry = data["entries"][0]
    expected_keys = {"pattern", "mod_name", "added_at", "added_by", "status", "notes"}
    assert expected_keys.issubset(set(entry.keys()))
    assert entry["pattern"] == "appleskin*"
    assert entry["mod_name"] == "AppleSkin"
    assert entry["status"] == "active"
    assert entry["notes"] == "HUD"
    assert entry["added_by"] == "admin"


# ============================================================================
# 6. Mass Ingestion and Concurrency Stress Test
# ============================================================================

def test_mass_ingestion_stress(adv_server: Path):
    """Add 50 distinct patterns in rapid succession and verify full data integrity."""
    count = 50
    for i in range(count):
        add_to_allowlist(
            adv_server,
            pattern=f"mod_pack_entry_{i:03d}*.jar",
            mod_name=f"Mod Entry #{i}",
            notes=f"Automated test note {i}",
            status="active" if i % 2 == 0 else "disabled",
        )

    entries = get_allowlist_entries(adv_server)
    assert len(entries) == count

    # Active count should be exactly half (25)
    active_entries = [e for e in entries if e["status"] == "active"]
    assert len(active_entries) == 25

    # Check TXT mirror has only active patterns
    txt_lines = [l.strip() for l in (adv_server / "client-only-allow.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert len(txt_lines) == 25
    for l in txt_lines:
        assert l in [e["pattern"] for e in active_entries]


def test_url_encoded_delete_via_api(client, db_session, monkeypatch, tmp_path):
    """Verify that URL-encoded patterns like spaces and asterisks delete properly via query param."""
    import client_mod_routes

    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    server_dir = servers_dir / "UrlServer"
    server_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(client_mod_routes, "SERVERS_ROOT", servers_dir)
    admin_h = _login(client, "admin", "AdminPass123")

    pattern_with_space = "my mod with spaces *.jar"
    client.post("/api/client-mods/whitelist/UrlServer", json={"pattern": pattern_with_space}, headers=admin_h)

    # Verify present
    r = client.get("/api/client-mods/whitelist/UrlServer", headers=admin_h)
    assert pattern_with_space in r.json()["patterns"]

    # Delete with query param URL encoded: "my%20mod%20with%20spaces%20%2A.jar"
    import urllib.parse
    encoded = urllib.parse.quote(pattern_with_space)
    r = client.delete(f"/api/client-mods/whitelist/UrlServer?pattern={encoded}", headers=admin_h)
    assert r.status_code == 200

    # Verify gone
    r = client.get("/api/client-mods/whitelist/UrlServer", headers=admin_h)
    assert pattern_with_space not in r.json()["patterns"]
