"""Adversarial Challenge & Stress Test Suite for Folia & Modern Platform Integration.

Milestone 4: Platform & Version Compatibility Engine
Focus:
1. Folia Provider Empirical Stress (PaperMC Fill v3 API, channel fallbacks, malformed responses).
2. Folia Server Download & Provisioning (prepare_server_files, server_meta.json, build_number).
3. Folia Multi-Core JVM Parameters (Java 17 vs 21+, ServerThreadPoolSize, connection limits, keepalive).
4. LocalRuntime Java version inference and concurrency bounds.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.download_manager import prepare_server_files
from backend.local_runtime import _infer_java_version
from backend.multicore.concurrency_profile import (
    ConcurrencyProfile,
    get_concurrency_profile,
)
from backend.multicore.jvm_args_builder import (
    build_multicore_jvm_args,
    prepare_server_multicore_env,
)
from backend.server_providers.folia import FoliaProvider
from backend.server_providers.providers import get_provider


# -----------------------------------------------------------------------------
# Fixtures & Sample API Payloads
# -----------------------------------------------------------------------------

SAMPLE_FILL_V3_FOLIA_PROJECT = {
    "project": "folia",
    "versions": {
        "26.3": ["26.3"],
        "26.2": ["26.2"],
        "26.1": ["26.1.2"],
        "1.21": ["1.21.11", "1.21.8", "1.21.6", "1.21.5", "1.21.4"],
        "1.20": ["1.20.6", "1.20.4", "1.20.2", "1.20.1"],
        "1.19": ["1.19.4"],
    },
}

SAMPLE_FOLIA_BUILDS_ONLY_ALPHA = [
    {
        "id": 31,
        "time": "2024-05-10T22:34:23.862Z",
        "channel": "ALPHA",
        "downloads": {
            "server:default": {
                "name": "folia-1.20.4-31.jar",
                "checksums": {"sha256": "b0d55be3ba19cb6e040f0e7fba400e5224a271fbc7db73a9683aef7468425af9"},
                "size": 43050096,
                "url": "https://fill-data.papermc.io/v1/objects/b0d55be3ba19cb6e040f0e7fba400e5224a271fbc7db73a9683aef7468425af9/folia-1.20.4-31.jar",
            }
        },
    },
    {
        "id": 30,
        "time": "2024-05-09T18:00:00.000Z",
        "channel": "ALPHA",
        "downloads": {
            "server:default": {
                "name": "folia-1.20.4-30.jar",
                "checksums": {"sha256": "abcdef"},
                "size": 43000000,
                "url": "https://fill-data.papermc.io/v1/objects/abcdef/folia-1.20.4-30.jar",
            }
        },
    },
]

SAMPLE_FOLIA_BUILDS_ONLY_EXPERIMENTAL = [
    {
        "id": 15,
        "time": "2024-03-01T12:00:00.000Z",
        "channel": "EXPERIMENTAL",
        "downloads": {
            "server:default": {
                "name": "folia-1.20.4-15.jar",
                "checksums": {"sha256": "exp15sha"},
                "size": 42000000,
                "url": "https://fill-data.papermc.io/v1/objects/exp15sha/folia-1.20.4-15.jar",
            }
        },
    }
]

SAMPLE_FOLIA_BUILDS_MIXED_CHANNELS = [
    {
        "id": 50,
        "time": "2024-06-01T00:00:00.000Z",
        "channel": "ALPHA",
        "downloads": {
            "server:default": {
                "name": "folia-1.20.4-50.jar",
                "url": "https://fill-data.papermc.io/v1/objects/alpha50/folia-1.20.4-50.jar",
            }
        },
    },
    {
        "id": 49,
        "time": "2024-05-30T00:00:00.000Z",
        "channel": "STABLE",
        "downloads": {
            "server:default": {
                "name": "folia-1.20.4-49.jar",
                "url": "https://fill-data.papermc.io/v1/objects/stable49/folia-1.20.4-49.jar",
            }
        },
    },
]

SAMPLE_FOLIA_BUILDS_UNTAGGED_CHANNEL = [
    {
        "id": 7,
        "time": "2024-01-01T00:00:00.000Z",
        "channel": "NIGHTLY",
        "downloads": {
            "server:default": {
                "name": "folia-1.20.4-7.jar",
                "url": "https://fill-data.papermc.io/v1/objects/nightly7/folia-1.20.4-7.jar",
            }
        },
    }
]


# =============================================================================
# Battery 1: Folia Provider Empirical Stress & PaperMC Fill v3 API
# =============================================================================

class TestFoliaProviderFillV3Stress:
    """Stress-test FoliaProvider's interaction with PaperMC Fill v3 API."""

    def test_provider_registration(self):
        """Verify 'folia' is registered in provider registry and implements expected interface."""
        provider = get_provider("folia")
        assert provider is not None
        assert isinstance(provider, FoliaProvider)
        assert provider.name == "folia"
        assert hasattr(provider, "list_versions")
        assert hasattr(provider, "get_download_url")

    def test_list_versions_parses_grouped_versions_dict(self):
        """Verify list_versions flattens dict grouping into simple version list."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = SAMPLE_FILL_V3_FOLIA_PROJECT

        with patch("requests.get", return_value=mock_resp):
            versions = provider.list_versions()

        assert "1.19.4" in versions
        assert "1.20.4" in versions
        assert "1.21.4" in versions
        assert "26.3" in versions
        assert len(versions) == 13

    def test_list_versions_handles_flat_list_format(self):
        """Verify list_versions handles API returning flat list if API changes format."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"versions": ["1.20.4", "1.20.6", "1.21.1"]}

        with patch("requests.get", return_value=mock_resp):
            versions = provider.list_versions()

        assert versions == ["1.20.4", "1.20.6", "1.21.1"]

    def test_list_versions_handles_network_timeout(self):
        """Verify network timeout returns empty list without crashing."""
        provider = FoliaProvider()
        with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
            versions = provider.list_versions()
        assert versions == []

    def test_list_versions_handles_http_error(self):
        """Verify HTTP 500 error returns empty list without crashing."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        with patch("requests.get", return_value=mock_resp):
            versions = provider.list_versions()
        assert versions == []

    def test_channel_fallback_alpha_only(self):
        """Real-world Folia condition: Folia only has ALPHA builds on PaperMC.

        Verify fallback to ALPHA builds when STABLE channel has 0 builds.
        """
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = SAMPLE_FOLIA_BUILDS_ONLY_ALPHA

        with patch("requests.get", return_value=mock_resp):
            url = provider.get_download_url("1.20.4")

        assert "folia-1.20.4-31.jar" in url
        assert url.startswith("https://fill-data.papermc.io/")

    def test_channel_fallback_experimental_only(self):
        """Verify fallback to EXPERIMENTAL channel when STABLE and ALPHA are absent."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = SAMPLE_FOLIA_BUILDS_ONLY_EXPERIMENTAL

        with patch("requests.get", return_value=mock_resp):
            url = provider.get_download_url("1.20.4")

        assert "folia-1.20.4-15.jar" in url

    def test_stable_preferred_over_alpha(self):
        """Verify STABLE build is chosen even if an ALPHA build has a higher build id."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = SAMPLE_FOLIA_BUILDS_MIXED_CHANNELS

        with patch("requests.get", return_value=mock_resp):
            url = provider.get_download_url("1.20.4")

        assert "folia-1.20.4-49.jar" in url

    def test_channel_fallback_untagged_channel(self):
        """Verify fallback to any channel with server:default if STABLE/ALPHA/EXP are missing."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = SAMPLE_FOLIA_BUILDS_UNTAGGED_CHANNEL

        with patch("requests.get", return_value=mock_resp):
            url = provider.get_download_url("1.20.4")

        assert "folia-1.20.4-7.jar" in url

    def test_empty_builds_list_raises_value_error(self):
        """Verify empty builds list raises descriptive ValueError."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = []

        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="No builds found for Folia version"):
                provider.get_download_url("1.20.4")

    def test_builds_missing_server_default_download_raises_value_error(self):
        """Verify builds with only server:mojang or empty downloads dict raises ValueError."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [
            {
                "id": 1,
                "channel": "ALPHA",
                "downloads": {
                    "server:mojang": {"url": "https://example.com/mojang.jar"}
                },
            }
        ]

        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="No downloadable build found for Folia version"):
                provider.get_download_url("1.20.4")

    def test_http_404_not_found_raises_value_error(self):
        """Verify HTTP 404 on builds endpoint raises descriptive ValueError."""
        provider = FoliaProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error: Not Found")

        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="Failed to get Folia download URL for version"):
                provider.get_download_url("99.99.99")

    def test_live_fill_v3_folia_api_probing(self):
        """Probe real live PaperMC Fill v3 API if network is available.

        Verifies that actual Folia versions and build URLs resolve as expected.
        """
        provider = FoliaProvider()
        try:
            versions = provider.list_versions()
            if not versions:
                pytest.skip("Network unavailable or PaperMC API offline")
            assert "1.20.4" in versions
            assert "1.19.4" in versions

            url_1204 = provider.get_download_url("1.20.4")
            assert "folia-1.20.4-" in url_1204
            assert url_1204.endswith(".jar")

            url_1194 = provider.get_download_url("1.19.4")
            assert "folia-1.19.4-" in url_1194
        except requests.exceptions.RequestException:
            pytest.skip("PaperMC Fill v3 unreachable in test runner")


# =============================================================================
# Battery 2: Folia Server Download & Provisioning (`prepare_server_files`)
# =============================================================================

class TestFoliaServerProvisioning:
    """Stress-test Folia server download, provisioning, and metadata generation."""

    def test_prepare_server_files_folia_creates_jar_eula_and_meta(self, tmp_path):
        """Verify prepare_server_files for Folia provisions server.jar, eula.txt, and server_meta.json."""
        dest_dir = tmp_path / "folia_server_test"
        dest_dir.mkdir(parents=True, exist_ok=True)

        fake_jar_bytes = b"PK\x03\x04" + b"\x00" * 2048  # Realistic mock JAR header + padding

        def mock_stream_download(url, dest_path):
            Path(dest_path).write_bytes(fake_jar_bytes)

        # Mock Fill v3 builds response
        mock_builds_resp = MagicMock()
        mock_builds_resp.raise_for_status.return_value = None
        mock_builds_resp.json.return_value = SAMPLE_FOLIA_BUILDS_ONLY_ALPHA

        with patch("requests.get", return_value=mock_builds_resp), \
             patch("backend.download_manager.stream_download", side_effect=mock_stream_download):

            jar_result = prepare_server_files(server_type="folia", version="1.20.4", dest_dir=dest_dir)

        # 1. Verify server.jar
        assert jar_result == dest_dir / "server.jar"
        assert jar_result.is_file()
        assert jar_result.stat().st_size == len(fake_jar_bytes)

        # 2. Verify eula.txt
        eula_path = dest_dir / "eula.txt"
        assert eula_path.is_file()
        assert "eula=true" in eula_path.read_text(encoding="utf-8")

        # 3. Verify server_meta.json
        meta_path = dest_dir / "server_meta.json"
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        assert meta.get("server_type") == "folia"
        assert meta.get("version") == "1.20.4"
        assert meta.get("folia_build") == 31
        assert meta.get("build_number") == "31"
        assert "folia-1.20.4-31.jar" in meta.get("download_url")
        assert meta.get("jar_size_bytes") == len(fake_jar_bytes)
        assert "jar_sha256" in meta

    def test_prepare_server_files_folia_regex_fallback_when_builds_api_fails(self, tmp_path):
        """Verify that if Fill v3 builds endpoint fails, build_number is extracted via regex from URL."""
        dest_dir = tmp_path / "folia_regex_test"
        dest_dir.mkdir(parents=True, exist_ok=True)

        fake_jar_bytes = b"PK\x03\x04" + b"\x00" * 1024

        def mock_stream_download(url, dest_path):
            Path(dest_path).write_bytes(fake_jar_bytes)

        # Build endpoint fails with warning, but provider.get_download_url succeeds
        mock_get = MagicMock(side_effect=requests.exceptions.RequestException("Fill v3 builds API down"))

        mock_provider = FoliaProvider()
        mock_provider.get_download_url = MagicMock(
            return_value="https://fill-data.papermc.io/v1/objects/xyz/folia-1.20.4-42.jar"
        )

        with patch("requests.get", mock_get), \
             patch("backend.download_manager.get_provider", return_value=mock_provider), \
             patch("backend.download_manager.stream_download", side_effect=mock_stream_download):

            prepare_server_files(server_type="folia", version="1.20.4", dest_dir=dest_dir)

        meta_path = dest_dir / "server_meta.json"
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # build_number extracted via regex: -42.jar -> "42"
        assert meta.get("build_number") == "42"

    def test_prepare_server_files_folia_empty_download_raises_value_error(self, tmp_path):
        """Verify 0-byte downloaded JAR causes prepare_server_files to raise ValueError."""
        dest_dir = tmp_path / "folia_empty_test"
        dest_dir.mkdir(parents=True, exist_ok=True)

        def mock_empty_download(url, dest_path):
            Path(dest_path).write_bytes(b"")

        mock_builds_resp = MagicMock()
        mock_builds_resp.raise_for_status.return_value = None
        mock_builds_resp.json.return_value = SAMPLE_FOLIA_BUILDS_ONLY_ALPHA

        with patch("requests.get", return_value=mock_builds_resp), \
             patch("backend.download_manager.stream_download", side_effect=mock_empty_download):

            with pytest.raises(ValueError, match="Downloaded JAR is empty"):
                prepare_server_files(server_type="folia", version="1.20.4", dest_dir=dest_dir)


# =============================================================================
# Battery 3: Folia Multi-Core JVM Parameters Across Java Versions & Memory Limits
# =============================================================================

class TestFoliaMulticoreJvmParameters:
    """Stress-test Folia JVM flag synthesis, system properties, and runtime environments."""

    @pytest.mark.parametrize("cores", [1, 2, 4, 8, 16, 32])
    def test_folia_core_scaled_properties(self, cores):
        """Verify ServerThreadPoolSize and player-connection-limit scale with profile.worker_threads."""
        profile = get_concurrency_profile(cores=cores, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(profile, server_type="folia")

        expected_threads = profile.worker_threads

        # 1. Mojang ServerThreadPoolSize
        pool_flag = f"-Dnet.minecraft.server.ServerThreadPoolSize={expected_threads}"
        assert pool_flag in flags

        # 2. Paper player-connection-limit
        conn_flag = f"-Dpaper.player-connection-limit={expected_threads}"
        assert conn_flag in flags

        # 3. Paper playerconnection.keepalive=60
        assert "-Dpaper.playerconnection.keepalive=60" in flags

    def test_folia_java17_strict_g1gc_no_zgc(self):
        """Java 17 Folia server MUST use G1GC and NEVER emit ZGC flags."""
        profile = ConcurrencyProfile(
            allocated_cores=8,
            worker_threads=8,
            fork_join_parallelism=8,
            gc_threads=8,
            conc_gc_threads=4,
            ci_compiler_count=4,
            netty_threads=8,
            java_version=17,
            ram_mb=8192,  # Even with high RAM, Java 17 lacks Generational ZGC
        )
        flags = build_multicore_jvm_args(profile, server_type="folia")

        assert "-XX:+UseG1GC" in flags
        assert "-XX:ParallelGCThreads=8" in flags
        assert "-XX:ConcGCThreads=4" in flags

        # Strictly no ZGC on Java 17
        assert not any("ZGC" in f for f in flags)
        assert not any("ZGenerational" in f for f in flags)

        # Folia flags present
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=8" in flags
        assert "-Dpaper.player-connection-limit=8" in flags
        assert "-Dpaper.playerconnection.keepalive=60" in flags

    def test_folia_java21_high_ram_generational_zgc(self):
        """Java 21 Folia server with >=4GB RAM MUST use Generational ZGC."""
        profile = ConcurrencyProfile(
            allocated_cores=8,
            worker_threads=8,
            fork_join_parallelism=8,
            gc_threads=8,
            conc_gc_threads=4,
            ci_compiler_count=4,
            netty_threads=8,
            java_version=21,
            ram_mb=8192,
        )
        flags = build_multicore_jvm_args(profile, server_type="folia")

        assert "-XX:+UseZGC" in flags
        assert "-XX:+ZGenerational" in flags
        assert "-XX:ConcGCThreads=4" in flags
        assert "-XX:ParallelGCThreads=8" in flags

        # Folia flags present
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=8" in flags
        assert "-Dpaper.player-connection-limit=8" in flags
        assert "-Dpaper.playerconnection.keepalive=60" in flags

    def test_folia_java21_low_ram_fallback_to_g1gc(self):
        """Java 21 Folia server with <4GB RAM (<4096MB) MUST fall back to G1GC to prevent OOM."""
        profile = ConcurrencyProfile(
            allocated_cores=4,
            worker_threads=4,
            fork_join_parallelism=4,
            gc_threads=4,
            conc_gc_threads=2,
            ci_compiler_count=2,
            netty_threads=4,
            java_version=21,
            ram_mb=2048,  # Under 4GB threshold
        )
        flags = build_multicore_jvm_args(profile, server_type="folia")

        assert "-XX:+UseG1GC" in flags
        assert not any("ZGC" in f for f in flags)

        # Folia flags present
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=4" in flags
        assert "-Dpaper.player-connection-limit=4" in flags
        assert "-Dpaper.playerconnection.keepalive=60" in flags

    def test_folia_prepare_server_multicore_env(self, tmp_path):
        """Verify prepare_server_multicore_env provisions agent, skips user_jvm_args.txt, and sets env vars."""
        server_dir = tmp_path / "folia_env_test"
        server_dir.mkdir(parents=True, exist_ok=True)

        profile = get_concurrency_profile(cores=4, ram_mb=4096, java_version=21)

        env = prepare_server_multicore_env(server_dir, profile, server_type="folia")

        # 1. Folia does NOT use user_jvm_args.txt (only Forge/NeoForge run.sh uses it)
        user_jvm_args_path = server_dir / "user_jvm_args.txt"
        assert not user_jvm_args_path.exists()

        # 2. Agent jar deployed
        agent_path = server_dir / "mc-multicore-agent.jar"
        assert agent_path.is_file()

        # 3. Environment variables verification
        assert env["MULTICORE_ENABLED"] == "1"
        assert env["MULTICORE_THREADS"] == str(profile.worker_threads)

        all_args = env["ALL_JAVA_ARGS"]
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=" in all_args
        assert "-Dpaper.player-connection-limit=" in all_args
        assert "-Dpaper.playerconnection.keepalive=60" in all_args
        assert "-javaagent:" in all_args

        # 4. JAVA_TOOL_OPTIONS should omit -Dpaper.* flags to avoid JVM launch rejection
        tool_options = env["JAVA_TOOL_OPTIONS"]
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=" in tool_options
        assert "-Dpaper.player-connection-limit=" not in tool_options
        assert "-Dpaper.playerconnection.keepalive=" not in tool_options


# =============================================================================
# Battery 4: LocalRuntime Java Version Inference for Folia
# =============================================================================

class TestFoliaJavaVersionInference:
    """Verify _infer_java_version properly resolves Java versions for Folia."""

    @pytest.mark.parametrize(
        "mc_version,expected_java",
        [
            ("1.19.4", 21),  # Modern default >= 1.19
            ("1.20.1", 21),
            ("1.20.2", 21),
            ("1.20.4", 21),
            ("1.20.6", 21),
            ("1.21.1", 21),
            ("1.21.4", 21),
            ("26.1.2", 25),  # 26+ snapshots map to Java 25
            ("26.3", 25),
        ],
    )
    def test_infer_java_version_folia(self, mc_version, expected_java):
        """Verify Java version inference for Folia Minecraft versions."""
        assert _infer_java_version(None, "folia", mc_version) == expected_java


# =============================================================================
# Battery 5: Folia Concurrency Modes & Advanced Adversarial Stress
# =============================================================================

class TestFoliaConcurrencyModesAndEdgeCases:
    """Stress-test Folia concurrency modes, single-core fallback, and platform flag boundaries."""

    def test_folia_single_core_mode_bounds(self):
        """Verify single_core mode cleanly bounds threads and pool sizes to 1."""
        profile = get_concurrency_profile(
            cores=8,
            ram_mb=4096,
            java_version=21,
            mode="single_core",
        )
        assert profile.worker_threads == 1
        flags = build_multicore_jvm_args(profile, server_type="folia")

        assert "-Dmulticore.mode=single_core" in flags
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=1" in flags
        assert "-Dpaper.player-connection-limit=1" in flags
        assert "-Dpaper.playerconnection.keepalive=60" in flags

    def test_folia_high_throughput_mode(self):
        """Verify high_throughput mode scales worker threads to effective_cores + 2."""
        profile = get_concurrency_profile(
            cores=4,
            ram_mb=4096,
            java_version=21,
            mode="high_throughput",
        )
        assert profile.worker_threads == 6  # 4 + 2
        flags = build_multicore_jvm_args(profile, server_type="folia")

        assert "-Dmulticore.mode=high_throughput" in flags
        assert "-Dnet.minecraft.server.ServerThreadPoolSize=6" in flags
        assert "-Dpaper.player-connection-limit=6" in flags

    def test_folia_never_receives_terminal_jline_flags(self):
        """Verify Forge/NeoForge-specific terminal flags (-Dterminal.*) are never attached to Folia."""
        profile = get_concurrency_profile(cores=4, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(profile, server_type="folia")

        assert not any("terminal.jline" in f for f in flags)
        assert not any("terminal.ansi" in f for f in flags)

    def test_prepare_server_files_overwrites_prior_server_meta(self, tmp_path):
        """Verify provisioning Folia over an existing server cleanly updates server_meta.json."""
        dest_dir = tmp_path / "folia_overwrite_test"
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Pre-seed existing server_meta.json from Paper 1.18.2
        prior_meta = {
            "server_type": "paper",
            "version": "1.18.2",
            "paper_build": 388,
            "build_number": "388",
            "download_url": "https://api.papermc.io/old_paper.jar",
        }
        (dest_dir / "server_meta.json").write_text(json.dumps(prior_meta), encoding="utf-8")

        fake_jar_bytes = b"PK\x03\x04" + b"\x00" * 2048

        def mock_stream_download(url, dest_path):
            Path(dest_path).write_bytes(fake_jar_bytes)

        mock_builds_resp = MagicMock()
        mock_builds_resp.raise_for_status.return_value = None
        mock_builds_resp.json.return_value = SAMPLE_FOLIA_BUILDS_ONLY_ALPHA

        with patch("requests.get", return_value=mock_builds_resp), \
             patch("backend.download_manager.stream_download", side_effect=mock_stream_download):

            prepare_server_files(server_type="folia", version="1.20.4", dest_dir=dest_dir)

        meta_path = dest_dir / "server_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        assert meta.get("server_type") == "folia"
        assert meta.get("version") == "1.20.4"
        assert meta.get("folia_build") == 31
        assert meta.get("build_number") == "31"

    def test_malformed_builds_payload_handling(self):
        """Verify FoliaProvider gracefully raises ValueError on malformed builds responses."""
        provider = FoliaProvider()

        # Case 1: builds is a dict instead of list
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "Internal Error"}

        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="No builds found for Folia version"):
                provider.get_download_url("1.20.4")

        # Case 2: build item is missing 'downloads'
        mock_resp.json.return_value = [{"id": 1, "channel": "ALPHA"}]
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="No downloadable build found for Folia version"):
                provider.get_download_url("1.20.4")

        # Case 3: server:default is None or not a dict
        mock_resp.json.return_value = [
            {"id": 1, "channel": "ALPHA", "downloads": {"server:default": None}}
        ]
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError):
                provider.get_download_url("1.20.4")
