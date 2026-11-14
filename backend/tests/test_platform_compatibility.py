"""Integration tests for Minecraft-Controller Platform & Version Compatibility Engine (Milestone 4).

Verifies multi-core execution support across all 4 platforms (Vanilla, Paper/Folia,
Forge, NeoForge) and versions (legacy 1.12.2, 1.16.5; modern 1.20+, 1.21+):
- Java version inference matrix (including Forge 1.16.5 Java 8 resolution)
- JVM multicore arguments synthesis & GC safety across Java 8, 17, 21+
- System property injection: ServerThreadPoolSize and Paper connection limits
- Argfile user_jvm_args.txt generation for modern Forge/NeoForge
- Dual-path argument delivery (CLI / JAVA_TOOL_OPTIONS vs user_jvm_args.txt)
- Server files provisioning and metadata tracking for all platforms
- Entrypoint pattern matching and argument forwarding verification
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.local_runtime import _infer_java_version
from backend.multicore import (
    ConcurrencyProfile,
    build_multicore_jvm_args,
    get_concurrency_profile,
    prepare_server_multicore_env,
)
from backend.multicore.jvm_args_builder import LMCE_HEADER_START, LMCE_HEADER_END
from backend.server_providers.forge import ForgeProvider
from backend.server_providers.neoforge import NeoForgeProvider
from backend.download_manager import prepare_server_files


# ==============================================================================
# 1. Java Version Inference Matrix Tests across All Platforms
# ==============================================================================

class TestJavaVersionInferenceMatrix:
    """Verifies that each server platform and version maps to the exact required Java runtime."""

    @pytest.mark.parametrize(
        "server_type,version,expected_java",
        [
            # Legacy Vanilla (1.12.2, 1.16.5) -> Java 8
            ("vanilla", "1.12.2", 8),
            ("vanilla", "1.16.5", 8),
            # Intermediate Vanilla (1.17 - 1.18) -> Java 17
            ("vanilla", "1.17.1", 17),
            ("vanilla", "1.18.2", 17),
            # Modern Vanilla (1.19+, 1.20+, 1.21+) -> Java 21
            ("vanilla", "1.19.4", 21),
            ("vanilla", "1.20.1", 21),
            ("vanilla", "1.20.4", 21),
            ("vanilla", "1.20.6", 21),
            ("vanilla", "1.21", 21),
            ("vanilla", "1.21.1", 21),
            ("vanilla", "1.21.4", 21),
            # Future Snapshots -> Java 25
            ("vanilla", "26.1", 25),

            # Paper Matrix
            ("paper", "1.12.2", 8),
            ("paper", "1.16.5", 8),
            ("paper", "1.18.2", 17),
            ("paper", "1.20.4", 21),
            ("paper", "1.20.6", 21),
            ("paper", "1.21.1", 21),

            # Folia Matrix (Modern only: 1.19.4+)
            ("folia", "1.19.4", 21),
            ("folia", "1.20.1", 21),
            ("folia", "1.20.4", 21),
            ("folia", "1.20.6", 21),
            ("folia", "1.21.1", 21),

            # Forge Matrix: CRITICAL - 1.12.2 and 1.16.5 MUST be Java 8
            ("forge", "1.12.2", 8),
            ("forge", "1.16.5", 8),
            ("forge", "1.20.1", 17),
            ("forge", "1.20.4", 17),
            ("forge", "1.20.6", 21),
            ("forge", "1.21.1", 21),

            # NeoForge Matrix (1.20.2+ only)
            ("neoforge", "1.20.2", 17),
            ("neoforge", "1.20.4", 17),
            ("neoforge", "20.4.253", 17),
            ("neoforge", "1.20.6", 21),
            ("neoforge", "1.21.1", 21),
            ("neoforge", "21.1.266", 21),
        ],
    )
    def test_infer_java_version_platform_matrix(self, server_type, version, expected_java):
        assert _infer_java_version(None, server_type, version) == expected_java

    def test_forge_provider_get_java_version_helper_consistency(self):
        fp = ForgeProvider()
        assert fp.get_java_version("1.12.2") == 8
        assert fp.get_java_version("1.16.5") == 8
        assert fp.get_java_version("1.16.5-36.2.34") == 8
        assert fp.get_java_version("1.20.1") == 17
        assert fp.get_java_version("1.20.4") == 17
        assert fp.get_java_version("1.21.1") == 21

    def test_neoforge_provider_get_java_version_helper_consistency(self):
        nfp = NeoForgeProvider()
        assert nfp.get_java_version("1.20.4") == 17
        assert nfp.get_java_version("20.4.253") == 17
        assert nfp.get_java_version("1.21.1") == 21
        assert nfp.get_java_version("21.1.266") == 21

    def test_fallback_unparseable_version_defaults_to_java21(self):
        assert _infer_java_version(None, "custom", "unknown_release") == 21


# ==============================================================================
# 2. Multi-Core System Properties & Platform Flag Synthesis
# ==============================================================================

class TestMulticoreJvmArgsSynthesis:
    """Verifies JVM flags and system properties across platforms and versions."""

    def test_common_multicore_system_properties_present(self):
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        # Minecraft background worker pool property
        assert f"-Dnet.minecraft.server.ServerThreadPoolSize={prof.worker_threads}" in flags
        # Lynx engine flags
        assert "-Dmulticore.enabled=true" in flags
        assert f"-Dmulticore.threads={prof.worker_threads}" in flags
        assert f"-Djava.util.concurrent.ForkJoinPool.common.parallelism={prof.fork_join_parallelism}" in flags
        assert f"-Dio.netty.eventLoopThreads={prof.netty_threads}" in flags

    def test_paper_and_folia_connection_properties(self):
        for st in ("paper", "folia", "purpur"):
            prof = get_concurrency_profile(cpu_cores=6, ram_mb=6144, java_version=21)
            flags = build_multicore_jvm_args(prof, server_type=st)

            assert "-Dpaper.playerconnection.keepalive=60" in flags
            assert f"-Dpaper.player-connection-limit={prof.worker_threads}" in flags
            assert "-Dterminal.jline=false" not in flags

    def test_forge_and_neoforge_terminal_properties(self):
        for st in ("forge", "neoforge"):
            prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=17)
            flags = build_multicore_jvm_args(prof, server_type=st)

            assert "-Dterminal.jline=false" in flags
            assert "-Dterminal.ansi=true" in flags
            assert "-Dpaper.playerconnection.keepalive=60" not in flags
            assert not any(f.startswith("-Dpaper.player-connection-limit") for f in flags)

    def test_vanilla_omits_platform_specific_flags(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-Dterminal.jline=false" not in flags
        assert "-Dpaper.playerconnection.keepalive=60" not in flags
        assert not any(f.startswith("-Dpaper.") for f in flags)


# ==============================================================================
# 3. Garbage Collection Safety Matrix across Java Versions
# ==============================================================================

class TestGarbageCollectionSafetyMatrix:
    """Verifies that Java 8 / 11 NEVER receive ZGC flags and Java 21+ uses Generational ZGC."""

    @pytest.mark.parametrize(
        "platform,version",
        [
            ("vanilla", "1.12.2"),
            ("vanilla", "1.16.5"),
            ("forge", "1.12.2"),
            ("forge", "1.16.5"),
            ("paper", "1.12.2"),
            ("paper", "1.16.5"),
        ],
    )
    def test_legacy_java8_g1gc_strictly_no_zgc(self, platform, version):
        jv = _infer_java_version(None, platform, version)
        assert jv == 8

        prof = get_concurrency_profile(cpu_cores=4, ram_mb=8192, java_version=jv)
        flags = build_multicore_jvm_args(prof, server_type=platform)

        # Must use Java 8 tuned G1GC
        assert "-XX:+UseG1GC" in flags
        assert "-XX:+UseStringDeduplication" in flags
        assert "-XX:+UnlockExperimentalVMOptions" in flags
        # Must strictly NEVER emit ZGC flags (causes instant JVM crash on Java 8)
        assert "-XX:+UseZGC" not in flags
        assert "-XX:+ZGenerational" not in flags

    @pytest.mark.parametrize(
        "platform,version",
        [
            ("vanilla", "1.18.2"),
            ("paper", "1.18.2"),
            ("forge", "1.20.1"),
            ("forge", "1.20.4"),
            ("neoforge", "1.20.4"),
        ],
    )
    def test_java17_modern_g1gc_strictly_no_zgc(self, platform, version):
        jv = _infer_java_version(None, platform, version)
        assert jv == 17

        prof = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=jv)
        flags = build_multicore_jvm_args(prof, server_type=platform)

        assert "-XX:+UseG1GC" in flags
        assert "-XX:G1HeapRegionSize=16m" in flags
        assert "-XX:+UseZGC" not in flags
        assert "-XX:+ZGenerational" not in flags

    @pytest.mark.parametrize(
        "platform,version",
        [
            ("vanilla", "1.21.1"),
            ("paper", "1.21.1"),
            ("folia", "1.21.1"),
            ("forge", "1.21.1"),
            ("neoforge", "1.21.1"),
        ],
    )
    def test_java21_high_ram_generational_zgc(self, platform, version):
        jv = _infer_java_version(None, platform, version)
        assert jv == 21

        prof = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=jv)
        flags = build_multicore_jvm_args(prof, server_type=platform)

        assert "-XX:+UseZGC" in flags
        assert "-XX:+ZGenerational" in flags
        assert "-XX:+UseG1GC" not in flags


# ==============================================================================
# 4. user_jvm_args.txt vs Direct CLI Multi-Core Environment Delivery
# ==============================================================================

class TestMulticoreEnvironmentPreparation:
    """Verifies prepare_server_multicore_env across all 4 platforms."""

    def test_modern_forge_writes_user_jvm_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv_dir = Path(tmpdir)
            prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=17)
            env_vars = prepare_server_multicore_env(srv_dir, prof, server_type="forge")

            argfile = srv_dir / "user_jvm_args.txt"
            assert argfile.is_file()
            content = argfile.read_text(encoding="utf-8")

            # Check header, flags, and footer
            assert LMCE_HEADER_START in content
            assert LMCE_HEADER_END in content
            assert "-Dterminal.jline=false" in content
            assert f"-Dnet.minecraft.server.ServerThreadPoolSize={prof.worker_threads}" in content
            assert f"-Dmulticore.threads={prof.worker_threads}" in content

            # Environment variables dictionary returned
            assert env_vars["MULTICORE_ENABLED"] == "1"
            assert env_vars["MULTICORE_THREADS"] == str(prof.worker_threads)
            assert "ALL_JAVA_ARGS" in env_vars

    def test_modern_neoforge_writes_user_jvm_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv_dir = Path(tmpdir)
            prof = get_concurrency_profile(cpu_cores=6, ram_mb=8192, java_version=21)
            env_vars = prepare_server_multicore_env(srv_dir, prof, server_type="neoforge")

            argfile = srv_dir / "user_jvm_args.txt"
            assert argfile.is_file()
            content = argfile.read_text(encoding="utf-8")

            assert "-XX:+UseZGC" in content
            assert "-XX:+ZGenerational" in content
            assert "-Dterminal.jline=false" in content

    def test_vanilla_paper_folia_do_not_write_user_jvm_args(self):
        for st in ("vanilla", "paper", "folia"):
            with tempfile.TemporaryDirectory() as tmpdir:
                srv_dir = Path(tmpdir)
                prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
                env_vars = prepare_server_multicore_env(srv_dir, prof, server_type=st)

                argfile = srv_dir / "user_jvm_args.txt"
                # user_jvm_args.txt is Forge/NeoForge specific
                assert not argfile.exists()

                # Multi-core flags are delivered via ALL_JAVA_ARGS and JAVA_TOOL_OPTIONS
                assert env_vars["MULTICORE_ENABLED"] == "1"
                assert "-Dnet.minecraft.server.ServerThreadPoolSize=" in env_vars["ALL_JAVA_ARGS"]

    def test_tool_options_strips_incompatible_flags(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        with tempfile.TemporaryDirectory() as tmpdir:
            env_vars = prepare_server_multicore_env(tmpdir, prof, server_type="paper")
            tool_opts = env_vars["JAVA_TOOL_OPTIONS"]

            # Paper flags filtered from JAVA_TOOL_OPTIONS to prevent JVM unrecognized property warnings
            assert "-Dpaper." not in tool_opts
            # Core GC and thread pool flags preserved
            assert "-Djava.util.concurrent.ForkJoinPool" in tool_opts
            assert "-Dnet.minecraft.server.ServerThreadPoolSize" in tool_opts


# ==============================================================================
# 5. Launch Classification & Server Provisioning Integration
# ==============================================================================

class TestLaunchClassificationAndProvisioning:
    """Verifies launch type classification and download manager provisioning."""

    def test_forge_and_neoforge_launch_type_helpers(self):
        fp = ForgeProvider()
        nfp = NeoForgeProvider()

        # Legacy Forge uses direct jar
        assert fp.get_expected_launch_type("1.12.2") == "jar"
        assert fp.get_expected_launch_type("1.16.5") == "jar"
        # Modern Forge uses run.sh
        assert fp.get_expected_launch_type("1.20.1") == "run_script"
        assert fp.get_expected_launch_type("1.21.1") == "run_script"
        # NeoForge always uses run.sh
        assert nfp.get_expected_launch_type("1.20.4") == "run_script"
        assert nfp.get_expected_launch_type("1.21.1") == "run_script"

    def test_prepare_server_files_folia(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv_dir = Path(tmpdir)
            mock_url = "https://fill-data.papermc.io/folia-1.20.4-31.jar"
            mock_builds = [{"id": 31, "channel": "ALPHA", "downloads": {"server:default": {"url": mock_url}}}]

            with patch("requests.get") as mock_get, patch("backend.download_manager.stream_download") as mock_stream:
                # Mock builds response
                mock_resp = MagicMock()
                mock_resp.json.return_value = mock_builds
                mock_resp.raise_for_status.return_value = None
                mock_get.return_value = mock_resp

                # Mock streaming download creating a real server.jar
                def fake_download(url, dest):
                    Path(dest).write_bytes(b"PK\x03\x04" + b"A" * 1024)

                mock_stream.side_effect = fake_download

                jar_path = prepare_server_files("folia", "1.20.4", srv_dir)
                assert jar_path.is_file()
                assert jar_path.name == "server.jar"

                # Check eula
                assert (srv_dir / "eula.txt").read_text(encoding="utf-8").strip() == "eula=true"

                # Check meta
                meta = json.loads((srv_dir / "server_meta.json").read_text(encoding="utf-8"))
                assert meta["server_type"] == "folia"
                assert meta["version"] == "1.20.4"
                assert meta["folia_build"] == 31


# ==============================================================================
# 6. Docker Entrypoint Shell Logic Assertions
# ==============================================================================

class TestDockerEntrypointLogic:
    """Verifies that docker/runtime-entrypoint.sh contains the correct fixes."""

    @pytest.fixture
    def entrypoint_content(self):
        entrypoint_path = BACKEND_DIR.parent / "docker" / "runtime-entrypoint.sh"
        assert entrypoint_path.is_file(), f"Entrypoint not found at {entrypoint_path}"
        return entrypoint_path.read_text(encoding="utf-8")

    def test_entrypoint_forge_legacy_jar_pattern(self, entrypoint_content):
        # Must contain forge-*.jar before *server*.jar
        match = re.search(r'patterns="([^"]*forge-\*\.jar[^"]*\*server\*\.jar[^"]*)"', entrypoint_content)
        assert match is not None, "forge-*.jar must appear before *server*.jar in patterns"

    def test_entrypoint_folia_in_java_inference(self, entrypoint_content):
        # Case statement must include "folia"
        assert '"vanilla"|"paper"|"purpur"|"folia")' in entrypoint_content

    def test_entrypoint_forge_1165_java8_inference(self, entrypoint_content):
        # Must match 1.8 through 1.16 for Java 8
        assert '[[ "$version" == 1.16* ]]' in entrypoint_content

    def test_entrypoint_runsh_arg_forwarding(self, entrypoint_content):
        # run.sh execution must forward effective args and extra server args
        assert 'tail -f -n +1 console.in | bash ./run.sh "${effective_args[@]}" $EXTRA_SERVER_ARGS' in entrypoint_content
