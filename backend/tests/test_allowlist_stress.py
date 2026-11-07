"""Adversarial stress and edge-case testing for Milestone 1 (M1) Allowlist Tracking & Filter Preservation.

Covers:
1. Edge-case patterns (empty string, special characters, regex-like symbols, uppercase vs lowercase filenames, wildcards).
2. Concurrency & file sync (rapid multi-threaded operations, external .txt modifications, mtime edge-cases, duplicate lines).
3. Corrupted JSON recovery (truncated JSON, malformed schema, null pattern, non-string pattern).
4. Filter preservation pipeline: mock CLIENT_ONLY mods with various naming patterns (appleskin*, *jei*, sodium-*).
   Ensures allowlisted mods are NEVER disabled.
5. API endpoint edge-cases (URL encoded characters, empty inputs, query vs body DELETE).
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-stress-testing-1234567890")
os.environ.setdefault("RUNTIME_MODE", "local")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(__file__).parent / "_tmp_stress_servers"))
os.environ.setdefault("STATS_DB_PATH", str(Path(__file__).parent / "_tmp_stress_stats.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

from client_mod_filter import (
    ALLOWLIST_JSON_FILENAME,
    ALLOWLIST_TXT_FILENAME,
    ClientModFilter,
    FilterAction,
    add_to_allowlist,
    get_allowlist_entries,
    is_mod_allowlisted,
    remove_from_allowlist,
    sync_allowlist,
)
from mod_side_resolver import ModSideResolver


def create_mock_jar(jar_path: Path, manifest: Dict[str, Any], loader: str = "fabric") -> Path:
    """Creates a mock mod jar with specified metadata."""
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if loader == "fabric":
            zf.writestr("fabric.mod.json", json.dumps(manifest))
        elif loader == "forge":
            zf.writestr("META-INF/mods.toml", manifest.get("mods_toml", ""))
        else:
            zf.writestr("pack.mcmeta", json.dumps(manifest))
    return jar_path


@pytest.fixture
def stress_server(tmp_path: Path) -> Path:
    s_dir = tmp_path / "StressServer"
    s_dir.mkdir(parents=True, exist_ok=True)
    (s_dir / "mods").mkdir(parents=True, exist_ok=True)
    return s_dir


# ============================================================================
# 1. Edge Case Pattern Matching Tests
# ============================================================================

class TestEdgeCasePatternMatching:
    """Stress-test pattern matching logic with strange, hostile, and boundary inputs."""

    def test_empty_and_whitespace_patterns(self, stress_server: Path):
        """Empty and whitespace strings must be rejected."""
        with pytest.raises(ValueError, match="Pattern cannot be empty"):
            add_to_allowlist(stress_server, "")

        with pytest.raises(ValueError, match="Pattern cannot be empty"):
            add_to_allowlist(stress_server, "   ")

        assert remove_from_allowlist(stress_server, "") is False
        assert remove_from_allowlist(stress_server, "   ") is False
        assert is_mod_allowlisted(stress_server, "appleskin.jar") is False

    @pytest.mark.parametrize(
        "pattern,filename,expected",
        [
            ("appleskin*", "appleskin-fabric-mc1.20.1-2.5.1.jar", True),
            ("appleskin*", "APPLESKIN-FABRIC-MC1.20.1-2.5.1.JAR", True),
            ("APPLESKIN*", "appleskin-fabric-mc1.20.1-2.5.1.jar", True),
            ("*jei*", "jei-1.20.1-forge-15.2.0.27.jar", True),
            ("*jei*", "JEI-1.20.1-FORGE-15.2.0.27.JAR", True),
            ("*jei*", "another-jei-addon.jar", True),
            ("*jei*", "not_matching.jar", False),
            ("sodium-*", "sodium-fabric-0.5.8.jar", True),
            ("sodium-*", "sodium_fabric_0.5.8.jar", False),
            ("sodium-*", "rubidium-sodium-0.5.8.jar", False),
            ("*.jar", "test.jar", True),
            ("*", "any_mod_name.jar", True),
            ("?ppleskin.jar", "appleskin.jar", True),
            ("?ppleskin.jar", "xppleskin.jar", True),
            ("?ppleskin.jar", "appleskin-fabric.jar", False),
            ("mod-[0-9].jar", "mod-5.jar", True),
            ("mod-[0-9].jar", "mod-a.jar", False),
            ("mod-(test)+[1].jar", "mod-(test)+[1].jar", True),
            ("mod with spaces*", "mod with spaces-1.0.jar", True),
            ("mod_with_unicode_äöü*", "mod_with_unicode_äöü-1.0.jar", True),
            ("mod.with.dots*", "mod.with.dots.1.0.0.jar", True),
        ],
    )
    def test_pattern_matching_varieties(
        self, stress_server: Path, pattern: str, filename: str, expected: bool
    ):
        """Test various pattern styles against candidate filenames."""
        add_to_allowlist(stress_server, pattern=pattern)
        matched = is_mod_allowlisted(stress_server, filename=filename)
        assert matched == expected, f"Pattern '{pattern}' vs '{filename}' expected {expected}, got {matched}"

    def test_unclosed_glob_characters(self, stress_server: Path):
        """Unclosed brackets or malformed glob characters should not crash the matcher."""
        # Unclosed bracket
        add_to_allowlist(stress_server, pattern="broken[pattern")
        # Should not raise exception
        assert is_mod_allowlisted(stress_server, filename="broken[pattern.jar") is True or False

    def test_mod_id_vs_filename_matching(self, stress_server: Path):
        """Matching should succeed if mod_id matches pattern even if filename differs completely."""
        add_to_allowlist(stress_server, pattern="sodium*")
        # Filename does not match, but mod_id does
        assert is_mod_allowlisted(
            stress_server, filename="custom-optimization-pack.jar", mod_id="sodium"
        ) is True
        # Filename matches, but mod_id does not
        assert is_mod_allowlisted(
            stress_server, filename="sodium-fabric-1.0.jar", mod_id="unknown_id"
        ) is True
        # Neither matches
        assert is_mod_allowlisted(
            stress_server, filename="iris-fabric-1.0.jar", mod_id="iris"
        ) is False


# ============================================================================
# 2. Concurrency & File Synchronization Stress Tests
# ============================================================================

class TestConcurrencyAndFileSync:
    """Stress-test concurrent read/write and external file synchronization."""

    def test_rapid_concurrent_additions(self, stress_server: Path):
        """Rapid additions from multiple concurrent threads should not corrupt JSON."""
        num_threads = 10
        patterns_per_thread = 5

        def worker(thread_idx: int):
            for i in range(patterns_per_thread):
                pat = f"mod_{thread_idx}_{i}*"
                add_to_allowlist(
                    stress_server,
                    pattern=pat,
                    mod_name=f"Mod {thread_idx} {i}",
                    added_by=f"thread_{thread_idx}",
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, idx) for idx in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        # The JSON file must be valid JSON after concurrent writes
        json_file = stress_server / ALLOWLIST_JSON_FILENAME
        assert json_file.exists()
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert "entries" in data
        assert isinstance(data["entries"], list)
        # Verify that get_allowlist_entries parses without error
        entries = get_allowlist_entries(stress_server)
        assert len(entries) > 0

    def test_external_txt_modification_sync(self, stress_server: Path):
        """External edits to client-only-allow.txt should be recognized and synced to JSON."""
        # Initial add
        add_to_allowlist(stress_server, pattern="initial_mod*")

        # Simulate external edit to .txt with future timestamp
        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        json_file = stress_server / ALLOWLIST_JSON_FILENAME
        assert txt_file.exists()

        time.sleep(0.1)
        new_content = "# External comment\ninitial_mod*\nexternal_mod_added*\nanother_external*\n"
        txt_file.write_text(new_content, encoding="utf-8")
        # Ensure mtime is newer by at least 2 seconds
        now = time.time() + 2.0
        os.utime(str(txt_file), (now, now))

        # sync_allowlist should reconcile from .txt
        sync_allowlist(stress_server)

        entries = get_allowlist_entries(stress_server)
        patterns = [e["pattern"] for e in entries]
        assert "external_mod_added*" in patterns
        assert "another_external*" in patterns
        assert "initial_mod*" in patterns

    def test_external_txt_removal_sync(self, stress_server: Path):
        """Removing a pattern from .txt externally should remove it from JSON after sync."""
        add_to_allowlist(stress_server, pattern="mod1*")
        add_to_allowlist(stress_server, pattern="mod2*")

        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        time.sleep(0.1)
        # Remove mod1 from .txt
        txt_file.write_text("mod2*\n", encoding="utf-8")
        now = time.time() + 2.0
        os.utime(str(txt_file), (now, now))

        sync_allowlist(stress_server)

        entries = get_allowlist_entries(stress_server)
        patterns = [e["pattern"] for e in entries]
        assert "mod1*" not in patterns
        assert "mod2*" in patterns

    def test_external_txt_duplicates_handling(self, stress_server: Path):
        """Duplicate lines in .txt should not cause errors, but how does sync reconcile?"""
        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        txt_file.write_text("dup_mod*\ndup_mod*\ndup_mod*\n", encoding="utf-8")

        sync_allowlist(stress_server)
        entries = get_allowlist_entries(stress_server)
        assert len(entries) >= 1
        assert is_mod_allowlisted(stress_server, "dup_mod-1.0.jar") is True


# ============================================================================
# 3. Corrupted JSON Recovery Tests
# ============================================================================

class TestCorruptedRecovery:
    """Stress-test system behavior when JSON or TXT files are corrupted."""

    def test_syntax_corrupted_json_recovery_from_txt(self, stress_server: Path):
        """When client-only-allow.json is corrupt (syntax error), sync recovers from TXT."""
        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        json_file = stress_server / ALLOWLIST_JSON_FILENAME

        # Write valid txt
        txt_file.write_text("appleskin*\njei*\n", encoding="utf-8")
        # Write corrupted JSON
        json_file.write_text("{ this is NOT valid json", encoding="utf-8")

        sync_allowlist(stress_server)

        # JSON should be repaired
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert "entries" in data
        patterns = [e["pattern"] for e in data["entries"]]
        assert "appleskin*" in patterns
        assert "jei*" in patterns

    def test_corrupted_json_without_txt_returns_empty(self, stress_server: Path):
        """When JSON is corrupt and TXT does not exist, get_allowlist_entries returns empty without crashing."""
        json_file = stress_server / ALLOWLIST_JSON_FILENAME
        json_file.write_text("CORRUPTED CONTENT", encoding="utf-8")

        entries = get_allowlist_entries(stress_server)
        assert entries == []
        assert is_mod_allowlisted(stress_server, "any_mod.jar") is False

    def test_malformed_json_schema_recovery(self, stress_server: Path):
        """When JSON has wrong data types (e.g. root is a list, or entries is not a list)."""
        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        json_file = stress_server / ALLOWLIST_JSON_FILENAME

        txt_file.write_text("sodium*\n", encoding="utf-8")
        json_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

        sync_allowlist(stress_server)

        entries = get_allowlist_entries(stress_server)
        patterns = [e["pattern"] for e in entries]
        assert "sodium*" in patterns

    def test_null_pattern_in_json(self, stress_server: Path):
        """Test how the system behaves if an entry in client-only-allow.json has pattern=None."""
        json_file = stress_server / ALLOWLIST_JSON_FILENAME
        malformed = {
            "version": 1,
            "updated_at": "2026-11-07T12:00:00Z",
            "entries": [
                {"pattern": None, "mod_name": "Broken", "status": "active"},
                {"pattern": "valid_mod*", "mod_name": "Valid", "status": "active"},
            ],
        }
        json_file.write_text(json.dumps(malformed), encoding="utf-8")

        # Let's see if is_mod_allowlisted or get_allowlist_entries handles this or raises AttributeError
        try:
            matched = is_mod_allowlisted(stress_server, "valid_mod-1.0.jar")
            # If handled, it should match the valid mod
            assert matched is True
        except AttributeError as exc:
            pytest.fail(f"AttributeError raised on null pattern in JSON: {exc}")


# ============================================================================
# 4. Filter Preservation Pipeline Tests (CLIENT_ONLY Mods)
# ============================================================================

class TestFilterPreservationPipeline:
    """Empirically test that CLIENT_ONLY mods matching allowlist are NEVER disabled."""

    def test_filter_preservation_with_various_glob_patterns(self, stress_server: Path):
        """
        Verify preservation of client-only mods matching requested patterns:
        - 'appleskin-fabric-mc1.20.1-2.5.1.jar' matching 'appleskin*'
        - 'jei-1.20.1-forge-15.2.0.27.jar' matching '*jei*'
        - 'sodium-fabric-0.5.8.jar' matching 'sodium-*'
        Non-allowlisted client-only mods MUST be moved to mods-disabled-client/.
        """
        mods_dir = stress_server / "mods"
        disabled_dir = stress_server / "mods-disabled-client"

        # Create mock client-only mods
        # 1. appleskin
        create_mock_jar(
            mods_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar",
            {
                "schemaVersion": 1,
                "id": "appleskin",
                "version": "2.5.1",
                "environment": "client",
            },
        )

        # 2. jei
        create_mock_jar(
            mods_dir / "jei-1.20.1-forge-15.2.0.27.jar",
            {
                "schemaVersion": 1,
                "id": "jei",
                "version": "15.2.0.27",
                "environment": "client",
            },
        )

        # 3. sodium
        create_mock_jar(
            mods_dir / "sodium-fabric-0.5.8.jar",
            {
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.5.8",
                "environment": "client",
            },
        )

        # 4. iris (CLIENT_ONLY, NOT allowlisted)
        create_mock_jar(
            mods_dir / "iris-fabric-1.7.0.jar",
            {
                "schemaVersion": 1,
                "id": "iris",
                "version": "1.7.0",
                "environment": "client",
            },
        )

        # 5. server_mod (SERVER/BOTH, not client-only)
        create_mock_jar(
            mods_dir / "fabric-api-0.90.0.jar",
            {
                "schemaVersion": 1,
                "id": "fabric-api",
                "version": "0.90.0",
                "environment": "*",
            },
        )

        # Register the 3 allowlist patterns
        add_to_allowlist(stress_server, pattern="appleskin*", mod_name="AppleSkin")
        add_to_allowlist(stress_server, pattern="*jei*", mod_name="JEI")
        add_to_allowlist(stress_server, pattern="sodium-*", mod_name="Sodium")

        # Execute ClientModFilter.scan_and_filter
        filter_sys = ClientModFilter(stress_server)
        result = filter_sys.scan_and_filter(dry_run=False, use_allowlist=True)

        # Assertions on decisions
        decisions_by_name = {d["file_name"]: d for d in result["decisions"]}

        # 1. appleskin: preserved and whitelisted
        assert "appleskin-fabric-mc1.20.1-2.5.1.jar" in decisions_by_name
        d_apple = decisions_by_name["appleskin-fabric-mc1.20.1-2.5.1.jar"]
        assert d_apple["action"] == FilterAction.WHITELISTED.value
        assert d_apple["whitelisted"] is True
        assert (mods_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar").exists()
        assert not (disabled_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar").exists()

        # 2. jei: preserved and whitelisted
        assert "jei-1.20.1-forge-15.2.0.27.jar" in decisions_by_name
        d_jei = decisions_by_name["jei-1.20.1-forge-15.2.0.27.jar"]
        assert d_jei["action"] == FilterAction.WHITELISTED.value
        assert d_jei["whitelisted"] is True
        assert (mods_dir / "jei-1.20.1-forge-15.2.0.27.jar").exists()
        assert not (disabled_dir / "jei-1.20.1-forge-15.2.0.27.jar").exists()

        # 3. sodium: preserved and whitelisted
        assert "sodium-fabric-0.5.8.jar" in decisions_by_name
        d_sod = decisions_by_name["sodium-fabric-0.5.8.jar"]
        assert d_sod["action"] == FilterAction.WHITELISTED.value
        assert d_sod["whitelisted"] is True
        assert (mods_dir / "sodium-fabric-0.5.8.jar").exists()
        assert not (disabled_dir / "sodium-fabric-0.5.8.jar").exists()

        # 4. iris: disabled (moved to disabled_dir)
        assert "iris-fabric-1.7.0.jar" in decisions_by_name
        d_iris = decisions_by_name["iris-fabric-1.7.0.jar"]
        assert d_iris["action"] == FilterAction.DISABLED.value
        assert d_iris["whitelisted"] is False
        assert not (mods_dir / "iris-fabric-1.7.0.jar").exists()
        assert (disabled_dir / "iris-fabric-1.7.0.jar").exists()

        # 5. fabric-api: kept (server compatible)
        assert "fabric-api-0.90.0.jar" in decisions_by_name
        d_fab = decisions_by_name["fabric-api-0.90.0.jar"]
        assert d_fab["action"] == FilterAction.KEPT.value
        assert (mods_dir / "fabric-api-0.90.0.jar").exists()

        # Check summary counts
        assert result["whitelisted_count"] == 3
        assert result["disabled_count"] == 1
        assert result["kept_count"] == 4  # 3 whitelisted + 1 server_mod

    def test_mod_side_resolver_filter_server_mods_preserves_allowlist(self, stress_server: Path):
        """Test ModSideResolver.filter_server_mods with allowlist preservation."""
        mods_dir = stress_server / "mods"
        disabled_dir = stress_server / "mods-disabled-client"

        # Setup client-only mod
        create_mock_jar(
            mods_dir / "sodium-fabric-0.5.8.jar",
            {
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.5.8",
                "environment": "client",
            },
        )
        create_mock_jar(
            mods_dir / "unwhitelisted-client.jar",
            {
                "schemaVersion": 1,
                "id": "unwhitelisted",
                "version": "1.0.0",
                "environment": "client",
            },
        )

        add_to_allowlist(stress_server, pattern="sodium-*")

        resolver = ModSideResolver()
        report = resolver.filter_server_mods(server_dir=stress_server, dry_run=False, use_allowlist=True)

        assert report["whitelisted_count"] == 1
        assert len(report["whitelisted_mods"]) == 1
        assert report["whitelisted_mods"][0]["file_name"] == "sodium-fabric-0.5.8.jar"

        # sodium must remain in mods/
        assert (mods_dir / "sodium-fabric-0.5.8.jar").exists()
        assert not (disabled_dir / "sodium-fabric-0.5.8.jar").exists()

        # unwhitelisted must be in disabled_dir
        assert not (mods_dir / "unwhitelisted-client.jar").exists()
        assert (disabled_dir / "unwhitelisted-client.jar").exists()

    def test_mod_side_resolver_explicit_patterns_list(self, stress_server: Path):
        """Test ModSideResolver.filter_server_mods with explicit allowlist_patterns argument."""
        mods_dir = stress_server / "mods"

        create_mock_jar(
            mods_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar",
            {
                "schemaVersion": 1,
                "id": "appleskin",
                "version": "2.5.1",
                "environment": "client",
            },
        )

        resolver = ModSideResolver()
        report = resolver.filter_server_mods(
            server_dir=stress_server,
            dry_run=False,
            use_allowlist=True,
            allowlist_patterns=["appleskin*"],
        )

        assert report["whitelisted_count"] == 1
        assert (mods_dir / "appleskin-fabric-mc1.20.1-2.5.1.jar").exists()

    def test_filter_server_mods_disabled_allowlist_does_not_preserve(self, stress_server: Path):
        """Allowlist entries with status='disabled' must NOT protect the mod."""
        mods_dir = stress_server / "mods"
        disabled_dir = stress_server / "mods-disabled-client"

        create_mock_jar(
            mods_dir / "sodium-fabric-0.5.8.jar",
            {
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.5.8",
                "environment": "client",
            },
        )

        add_to_allowlist(stress_server, pattern="sodium*", status="disabled")

        filter_sys = ClientModFilter(stress_server)
        result = filter_sys.scan_and_filter(dry_run=False, use_allowlist=True)

        assert result["whitelisted_count"] == 0
        assert result["disabled_count"] == 1
        assert not (mods_dir / "sodium-fabric-0.5.8.jar").exists()
        assert (disabled_dir / "sodium-fabric-0.5.8.jar").exists()


    def test_disabled_entries_deleted_on_external_txt_sync(self, stress_server: Path):
        """
        Critical bug hypothesis:
        When an entry has status='disabled' in client-only-allow.json, it is not in client-only-allow.txt.
        When client-only-allow.txt is externally modified (e.g. adding a new pattern),
        sync_allowlist reconciles from txt_lines only, destroying the disabled entry in JSON!
        """
        # Add active entry
        add_to_allowlist(stress_server, pattern="active_mod*")
        # Add disabled entry with audit notes
        add_to_allowlist(
            stress_server,
            pattern="temporarily_disabled*",
            status="disabled",
            notes="Audit note: disabled for debugging",
            mod_name="TempDisabledMod",
        )

        entries_before = get_allowlist_entries(stress_server)
        assert len(entries_before) == 2

        # Now external admin adds a 3rd mod via client-only-allow.txt
        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        time.sleep(0.1)
        txt_file.write_text("active_mod*\nnewly_added_mod*\n", encoding="utf-8")
        future_time = time.time() + 2.0
        os.utime(str(txt_file), (future_time, future_time))

        # Re-sync
        sync_allowlist(stress_server)

        entries_after = get_allowlist_entries(stress_server)
        pats_after = [e["pattern"] for e in entries_after]

        # The disabled entry should still exist in JSON with status='disabled',
        # not be permanently deleted!
        assert "temporarily_disabled*" in pats_after, (
            "BUG: status='disabled' entry in JSON was permanently deleted when client-only-allow.txt was synced!"
        )


    def test_filter_server_mods_allowlist_patterns_with_none_element(self, stress_server: Path):
        """
        Test hypothesis:
        If allowlist_patterns contains None, e.g. from an API request or legacy config,
        [p.strip().lower() for p in allowlist_patterns if p.strip()] raises AttributeError: 'NoneType' object has no attribute 'strip'.
        """
        mods_dir = stress_server / "mods"
        create_mock_jar(
            mods_dir / "sodium-fabric-0.5.8.jar",
            {
                "schemaVersion": 1,
                "id": "sodium",
                "version": "0.5.8",
                "environment": "client",
            },
        )

        resolver = ModSideResolver()
        try:
            report = resolver.filter_server_mods(
                server_dir=stress_server,
                dry_run=False,
                use_allowlist=True,
                allowlist_patterns=["sodium*", None],
            )
            assert report["whitelisted_count"] == 1
        except AttributeError as exc:
            pytest.fail(f"AttributeError raised on None element in allowlist_patterns: {exc}")


    def test_txt_overwritten_if_modified_within_one_second(self, stress_server: Path):
        """
        Test hypothesis:
        If client-only-allow.txt is externally edited within 1 second of JSON creation,
        mtime_txt > mtime_json + 1.0 evaluates to False,
        and the else branch OVERWRITES client-only-allow.txt, reverting user changes!
        """
        add_to_allowlist(stress_server, pattern="initial_mod*")

        txt_file = stress_server / ALLOWLIST_TXT_FILENAME
        json_file = stress_server / ALLOWLIST_JSON_FILENAME

        # Externally modify .txt with mtime = mtime_json + 0.5s (within 1s threshold)
        mtime_json = json_file.stat().st_mtime
        txt_file.write_text("initial_mod*\nuser_external_mod*\n", encoding="utf-8")
        os.utime(str(txt_file), (mtime_json + 0.5, mtime_json + 0.5))

        sync_allowlist(stress_server)

        # What happened to .txt?
        txt_content = txt_file.read_text(encoding="utf-8")
        assert "user_external_mod*" in txt_content, (
            "BUG: User external modification to .txt within 1s was wiped out by JSON sync!"
        )


# ============================================================================
# 5. API Endpoint Adversarial & Security Tests
# ============================================================================

from tests.test_auth_users_api import engine, db_session, client, _login  # noqa: F401


class TestApiAdversarial:
    """Adversarial testing against FastAPI allowlist routes."""

    @pytest.fixture(autouse=True)
    def setup_api_server(self, tmp_path: Path, monkeypatch):
        servers_root = tmp_path / "api_servers"
        servers_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("client_mod_routes.SERVERS_ROOT", servers_root)
        self.server_name = "ApiStressServer"
        self.server_dir = servers_root / self.server_name
        self.server_dir.mkdir(parents=True, exist_ok=True)
        (self.server_dir / "mods").mkdir(parents=True, exist_ok=True)

    def test_api_add_empty_and_whitespace_pattern(self, client, db_session):
        """API should reject empty pattern and whitespace-only pattern with 400 Bad Request."""
        headers = _login(client, "admin", "AdminPass123")

        resp = client.post(
            f"/api/client-mods/whitelist/{self.server_name}",
            json={"pattern": ""},
            headers=headers,
        )
        assert resp.status_code == 400

        resp2 = client.post(
            f"/api/client-mods/whitelist/{self.server_name}",
            json={"pattern": "   "},
            headers=headers,
        )
        assert resp2.status_code == 400

    def test_api_add_pattern_with_newlines_rejected(self, client, db_session):
        """Pattern containing newlines must be rejected with HTTP 400 Bad Request."""
        headers = _login(client, "admin", "AdminPass123")

        resp = client.post(
            f"/api/client-mods/whitelist/{self.server_name}",
            json={"pattern": "mod_a*\nmod_b*", "mod_name": "Injected"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "newline" in resp.json()["detail"].lower()

    def test_api_delete_query_param_with_plus_sign(self, client, db_session):
        """
        URL query parameter 'mod+plus*' is decoded as 'mod plus*'.
        Deleting via JSON body should succeed where query param might fail due to URL decoding.
        """
        headers = _login(client, "admin", "AdminPass123")

        # Add pattern with literal plus
        client.post(
            f"/api/client-mods/whitelist/{self.server_name}",
            json={"pattern": "mod+plus*"},
            headers=headers,
        )

        # Deleting via body payload
        resp = client.request(
            "DELETE",
            f"/api/client-mods/whitelist/{self.server_name}",
            json={"pattern": "mod+plus*"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["pattern"] == "mod+plus*"

        # Verify it was removed
        entries = get_allowlist_entries(self.server_dir)
        assert not any(e["pattern"] == "mod+plus*" for e in entries)

    def test_api_delete_missing_pattern_everywhere(self, client, db_session):
        """DELETE without query param and without body should return 400 Bad Request."""
        headers = _login(client, "admin", "AdminPass123")

        resp = client.delete(
            f"/api/client-mods/whitelist/{self.server_name}",
            headers=headers,
        )
        assert resp.status_code == 400
