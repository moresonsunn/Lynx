"""Unit tests for Lynx Multi-Core Engine (LMCE) - Milestone 1.

Covers:
- ConcurrencyProfile, MultiCoreConfig, JvmProfile dataclasses and validation
- Hardware detection (psutil, cgroups v1/v2, cpuset, affinity, fallbacks)
- Multi-core profile scaling (enforcing cores = max(2, allocated), single-core fallback)
- Concurrency modes (auto, parallel_dimensions, parallel_entities, high_throughput)
- JVM argument builder across Java 8, 17, and 21+ (Generational ZGC vs G1GC)
- Server platform adaptations (Vanilla, Paper, Forge, NeoForge)
- user_jvm_args.txt writing, custom flag preservation, atomic writes, error handling
- Universal Java Agent binary packaging, manifest verification, corruption recovery
- prepare_server_multicore_env integration and environment variables dictionary
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.multicore import (
    AGENT_JAR_NAME,
    ConcurrencyProfile,
    JvmProfile,
    MultiCoreConfig,
    build_agent_jar,
    build_env_vars,
    build_multicore_jvm_args,
    detect_available_cores,
    detect_hardware_cores,
    ensure_agent_binary,
    format_user_jvm_args,
    get_concurrency_profile,
    prepare_server_multicore_env,
    validate_agent_jar,
    write_user_jvm_args,
)
from backend.multicore.agent_manager import BUNDLED_AGENT_JAR
from backend.multicore.concurrency_profile import (
    detect_affinity_cores,
    detect_cgroup_quota,
    detect_cpuset_cores,
)


# ==============================================================================
# 1. Dataclasses & Schema Tests
# ==============================================================================


class TestMultiCoreDataclasses:
    """Tests for ConcurrencyProfile, MultiCoreConfig, and JvmProfile dataclasses."""

    def test_concurrency_profile_instantiation_and_serialization(self):
        profile = ConcurrencyProfile(
            allocated_cores=4,
            worker_threads=4,
            fork_join_parallelism=4,
            gc_threads=4,
            conc_gc_threads=2,
            ci_compiler_count=2,
            netty_threads=4,
            jvm_flags=["-XX:+UseG1GC"],
            agent_path="/path/to/mc-multicore-agent.jar",
            mode="auto",
            ram_mb=4096,
            java_version=17,
            use_zgc=False,
        )

        assert profile.allocated_cores == 4
        assert profile.effective_cores == 4
        assert profile.worker_threads == 4
        assert profile.fork_join_parallelism == 4
        assert profile.gc_threads == 4
        assert profile.conc_gc_threads == 2
        assert profile.ci_compiler_count == 2
        assert profile.netty_threads == 4

        d = profile.as_dict()
        assert isinstance(d, dict)
        assert d["allocated_cores"] == 4
        assert d["effective_cores"] == 4
        assert d["worker_threads"] == 4
        assert d["jvm_flags"] == ["-XX:+UseG1GC"]
        assert d["agent_path"] == "/path/to/mc-multicore-agent.jar"
        assert d["mode"] == "auto"
        assert d["ram_mb"] == 4096
        assert d["java_version"] == 17
        assert d["use_zgc"] is False

    def test_multicore_config_defaults_and_validation(self):
        cfg = MultiCoreConfig()
        assert cfg.enabled is True
        assert cfg.mode == "auto"
        assert cfg.cpu_cores is None
        assert cfg.worker_threads is None
        assert cfg.gc_type == "auto"
        assert cfg.custom_jvm_flags == []

        # Valid validation
        cfg.validate()

        # Valid custom
        cfg2 = MultiCoreConfig(
            mode="parallel_dimensions",
            cpu_cores=8,
            worker_threads=8,
            gc_type="zgc",
        )
        cfg2.validate()

        # Invalid mode
        with pytest.raises(ValueError, match="Invalid mode"):
            MultiCoreConfig(mode="hyper_warp").validate()

        # Invalid gc_type
        with pytest.raises(ValueError, match="Invalid gc_type"):
            MultiCoreConfig(gc_type="shenandoah_unsupported").validate()

        # Invalid cpu_cores
        with pytest.raises(ValueError, match="cpu_cores must be >= 1"):
            MultiCoreConfig(cpu_cores=0).validate()

        with pytest.raises(ValueError, match="cpu_cores must be >= 1"):
            MultiCoreConfig(cpu_cores=-2).validate()

        # Invalid worker_threads
        with pytest.raises(ValueError, match="worker_threads must be >= 1"):
            MultiCoreConfig(worker_threads=0).validate()

    def test_jvm_profile_support_matrix(self):
        prof8 = JvmProfile.for_version(8, ram_mb=4096)
        assert prof8.java_version == 8
        assert prof8.is_generational_zgc_supported is False
        assert prof8.is_zgc_supported is False
        assert prof8.is_g1gc_supported is True
        assert prof8.default_gc == "G1GC"

        prof17 = JvmProfile.for_version(17, ram_mb=8192)
        assert prof17.java_version == 17
        assert prof17.is_generational_zgc_supported is False
        assert prof17.is_zgc_supported is True
        assert prof17.is_g1gc_supported is True
        assert prof17.default_gc == "G1GC"

        prof21_low_ram = JvmProfile.for_version(21, ram_mb=2048)
        assert prof21_low_ram.java_version == 21
        assert prof21_low_ram.is_generational_zgc_supported is True
        assert prof21_low_ram.default_gc == "G1GC"

        prof21_high_ram = JvmProfile.for_version(21, ram_mb=8192)
        assert prof21_high_ram.java_version == 21
        assert prof21_high_ram.is_generational_zgc_supported is True
        assert prof21_high_ram.default_gc == "ZGC"


# ==============================================================================
# 2. Concurrency Profile & Hardware Core Detection Tests
# ==============================================================================


class TestConcurrencyProfile:
    """Tests for core detection, multi-core profile calculations, and fallback policies."""

    def test_auto_detect_cores_with_psutil(self):
        with patch("psutil.cpu_count", return_value=8):
            cores = detect_hardware_cores()
            assert cores == 8

        with patch("psutil.cpu_count", return_value=16):
            cores = detect_hardware_cores()
            assert cores == 16

    def test_auto_detect_cores_psutil_none_fallback_os(self):
        with patch("psutil.cpu_count", return_value=None), patch(
            "os.cpu_count", return_value=6
        ):
            cores = detect_hardware_cores()
            assert cores == 6

    def test_auto_detect_cores_both_fail_fallback_one(self):
        with patch("psutil.cpu_count", return_value=None), patch(
            "os.cpu_count", return_value=None
        ):
            cores = detect_hardware_cores()
            assert cores == 1

        with patch("psutil.cpu_count", side_effect=Exception("psutil error")), patch(
            "os.cpu_count", side_effect=Exception("os error")
        ):
            cores = detect_hardware_cores()
            assert cores == 1

    def test_cgroup_quota_detection_v2(self, tmp_path):
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("400000 100000\n", encoding="utf-8")
        with patch("backend.multicore.concurrency_profile.Path") as mock_path:
            mock_path.side_effect = lambda *args: (
                cgroup_file if args == ("/sys/fs/cgroup/cpu.max",) else Path(*args)
            )
            quota = detect_cgroup_quota()
            assert quota == 4.0

    def test_cgroup_quota_detection_v2_unlimited(self, tmp_path):
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("max 100000\n", encoding="utf-8")
        with patch("backend.multicore.concurrency_profile.Path") as mock_path:
            mock_path.side_effect = lambda *args: (
                cgroup_file if args == ("/sys/fs/cgroup/cpu.max",) else Path(*args)
            )
            quota = detect_cgroup_quota()
            assert quota is None

    def test_cgroup_quota_detection_v1(self, tmp_path):
        cpu_dir = tmp_path / "cpu"
        cpu_dir.mkdir(parents=True)
        quota_f = cpu_dir / "cpu.cfs_quota_us"
        period_f = cpu_dir / "cpu.cfs_period_us"
        quota_f.write_text("200000\n", encoding="utf-8")
        period_f.write_text("100000\n", encoding="utf-8")

        with patch("backend.multicore.concurrency_profile.Path") as mock_path:
            def side_effect(*args):
                if args == ("/sys/fs/cgroup/cpu.max",):
                    return tmp_path / "nonexistent"
                elif args == ("/sys/fs/cgroup/cpu",):
                    return cpu_dir
                return Path(*args)

            mock_path.side_effect = side_effect
            quota = detect_cgroup_quota()
            assert quota == 2.0

    def test_cpuset_cores_detection(self, tmp_path):
        cpuset_f = tmp_path / "cpuset.cpus.effective"
        cpuset_f.write_text("0-3,6,8-9\n", encoding="utf-8")  # 4 + 1 + 2 = 7 cores

        with patch("backend.multicore.concurrency_profile.Path") as mock_path:
            mock_path.side_effect = lambda *args: (
                cpuset_f
                if args == ("/sys/fs/cgroup/cpuset.cpus.effective",)
                else Path(*args)
            )
            cnt = detect_cpuset_cores()
            assert cnt == 7

    def test_affinity_cores_detection(self):
        with patch("os.sched_getaffinity", create=True, return_value={0, 1, 2, 3}):
            cnt = detect_affinity_cores()
            assert cnt == 4

        with patch("os.sched_getaffinity", create=True, side_effect=Exception("error")):
            cnt = detect_affinity_cores()
            assert cnt is None

    def test_detect_available_cores_hierarchy(self):
        with patch(
            "backend.multicore.concurrency_profile.detect_hardware_cores", return_value=16
        ), patch(
            "backend.multicore.concurrency_profile.detect_cgroup_quota", return_value=6.0
        ), patch(
            "backend.multicore.concurrency_profile.detect_cpuset_cores", return_value=8
        ), patch(
            "backend.multicore.concurrency_profile.detect_affinity_cores", return_value=12
        ):
            cores = detect_available_cores()
            # min(16, ceil(6.0), 8, 12) = 6
            assert cores == 6

    def test_explicit_cores_valid(self):
        prof = get_concurrency_profile(cpu_cores=6, ram_mb=4096, java_version=21)
        assert prof.allocated_cores == 6
        assert prof.effective_cores == 6
        assert prof.worker_threads == 6
        assert prof.fork_join_parallelism == 6
        assert prof.gc_threads == 6
        assert prof.conc_gc_threads == 3
        assert prof.ci_compiler_count == 3
        assert prof.netty_threads == 6

    def test_enforce_multicore_min_two_cores(self):
        """Requirement: enforce cores = max(2, allocated) when allocating multi-core profiles."""
        prof = get_concurrency_profile(cpu_cores=1, ram_mb=2048, java_version=21, mode="auto")
        assert prof.allocated_cores == 2
        assert prof.effective_cores == 2
        assert prof.worker_threads >= 2
        assert prof.fork_join_parallelism >= 2

    def test_single_core_graceful_fallback(self):
        """Single-core fallback when mode='single_core' or enforce_multicore=False."""
        prof = get_concurrency_profile(
            cpu_cores=1, ram_mb=2048, java_version=21, mode="single_core"
        )
        assert prof.allocated_cores == 1
        assert prof.effective_cores == 1
        assert prof.worker_threads == 1
        assert prof.fork_join_parallelism == 1
        assert prof.gc_threads == 1
        assert prof.conc_gc_threads == 1
        assert prof.ci_compiler_count == 2  # JVM minimum
        assert prof.netty_threads == 1

        prof_no_enforce = get_concurrency_profile(
            cpu_cores=1, ram_mb=2048, java_version=21, enforce_multicore=False
        )
        assert prof_no_enforce.allocated_cores == 1
        assert prof_no_enforce.worker_threads == 1

    def test_negative_or_zero_cores_handling(self):
        with patch(
            "backend.multicore.concurrency_profile.detect_available_cores", return_value=4
        ):
            prof_zero = get_concurrency_profile(cpu_cores=0)
            assert prof_zero.allocated_cores == 4

            prof_neg = get_concurrency_profile(cpu_cores=-8)
            assert prof_neg.allocated_cores == 4

    def test_large_cores_clamping(self):
        prof = get_concurrency_profile(cpu_cores=65536)
        assert prof.allocated_cores == 1024
        assert prof.effective_cores == 1024

    def test_ram_mb_none_default(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=None)
        assert prof.ram_mb == 2048

        prof_zero = get_concurrency_profile(cpu_cores=4, ram_mb=0)
        assert prof_zero.ram_mb == 2048

    def test_modes_worker_thread_allocations(self):
        # Auto mode
        prof_auto = get_concurrency_profile(cpu_cores=8, mode="auto")
        assert prof_auto.mode == "auto"
        assert prof_auto.worker_threads == 8

        # Parallel dimensions
        prof_dims = get_concurrency_profile(cpu_cores=8, mode="parallel_dimensions")
        assert prof_dims.mode == "parallel_dimensions"
        assert prof_dims.worker_threads == 8

        # Parallel entities
        prof_ents = get_concurrency_profile(cpu_cores=8, mode="parallel_entities")
        assert prof_ents.mode == "parallel_entities"
        assert prof_ents.worker_threads == 8

        # High throughput mode allocates cores + 2
        prof_ht = get_concurrency_profile(cpu_cores=8, mode="high_throughput")
        assert prof_ht.mode == "high_throughput"
        assert prof_ht.worker_threads == 10  # 8 + 2

    def test_invalid_mode_fallback_auto(self):
        prof = get_concurrency_profile(cpu_cores=4, mode="warp_speed_turbo")
        assert prof.mode == "auto"

    def test_string_coercion_ram_mb(self):
        """String ram_mb='4096' should coerce to int 4096 and trigger ZGC on Java 21."""
        prof = get_concurrency_profile(cpu_cores=4, ram_mb="4096", java_version=21)
        assert prof.ram_mb == 4096
        assert "-XX:+UseZGC" in prof.jvm_flags
        assert "-XX:+ZGenerational" in prof.jvm_flags

    def test_string_coercion_java_version_8(self):
        """String java_version='8' should coerce to int 8 and strictly forbid ZGC flags."""
        prof = get_concurrency_profile(cpu_cores=4, ram_mb="4096", java_version="8")
        assert prof.java_version == 8
        assert "-XX:+UseZGC" not in prof.jvm_flags
        assert "-XX:+ZGenerational" not in prof.jvm_flags
        assert "-XX:+UseG1GC" in prof.jvm_flags

    def test_string_coercion_java_version_17(self):
        """String java_version='17' should coerce to int 17 and strictly forbid ZGenerational."""
        prof = get_concurrency_profile(cpu_cores=4, ram_mb="8192", java_version="17")
        assert prof.java_version == 17
        assert "-XX:+ZGenerational" not in prof.jvm_flags
        assert "-XX:+UseG1GC" in prof.jvm_flags

    def test_string_coercion_invalid_fallbacks(self):
        """Non-numeric or negative string inputs safely fall back to defaults without exception."""
        prof_bad_ram = get_concurrency_profile(cpu_cores=4, ram_mb="not_a_number", java_version=21)
        assert prof_bad_ram.ram_mb == 2048

        prof_neg_ram = get_concurrency_profile(cpu_cores=4, ram_mb="-1024", java_version=21)
        assert prof_neg_ram.ram_mb == 2048

        prof_bad_jv = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version="invalid")
        assert prof_bad_jv.java_version == 21

        prof_neg_jv = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version="-8")
        assert prof_neg_jv.java_version == 21

    def test_string_coercion_all_parameters_combined(self):
        """All parameters passed as strings simultaneously."""
        prof = get_concurrency_profile(cpu_cores="4", ram_mb="4096", java_version="8")
        assert prof.allocated_cores == 4
        assert prof.ram_mb == 4096
        assert prof.java_version == 8
        assert "-XX:+UseZGC" not in prof.jvm_flags
        assert "-XX:+ZGenerational" not in prof.jvm_flags
        assert "-XX:+UseG1GC" in prof.jvm_flags


# ==============================================================================
# 3. JVM Arguments Builder Tests
# ==============================================================================


class TestJvmArgsBuilder:
    """Tests for version-specific GC flag generation and JVM system properties."""

    def test_jvm_args_java21_high_ram_generational_zgc(self):
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-XX:+UseZGC" in flags
        assert "-XX:+ZGenerational" in flags
        assert "-XX:ConcGCThreads=4" in flags
        assert "-XX:ParallelGCThreads=8" in flags
        assert "-XX:+UseG1GC" not in flags

    def test_jvm_args_java21_low_ram_fallback_g1gc(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=2048, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-XX:+UseG1GC" in flags
        assert "-XX:ParallelGCThreads=4" in flags
        assert "-XX:ConcGCThreads=2" in flags
        assert "-XX:+UseZGC" not in flags
        assert "-XX:+ZGenerational" not in flags

    def test_jvm_args_java17_g1gc(self):
        prof = get_concurrency_profile(cpu_cores=6, ram_mb=8192, java_version=17)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-XX:+UseG1GC" in flags
        assert "-XX:ParallelGCThreads=6" in flags
        assert "-XX:ConcGCThreads=3" in flags
        assert "-XX:G1HeapRegionSize=16m" in flags
        assert "-XX:G1ReservePercent=15" in flags
        assert "-XX:InitiatingHeapOccupancyPercent=45" in flags
        assert "-XX:+UseZGC" not in flags
        assert "-XX:+ZGenerational" not in flags

    def test_jvm_args_java8_g1gc_no_zgc(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=2048, java_version=8)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-XX:+UseG1GC" in flags
        assert "-XX:ParallelGCThreads=4" in flags
        assert "-XX:ConcGCThreads=2" in flags
        assert "-XX:+UseStringDeduplication" in flags
        assert "-XX:+UnlockExperimentalVMOptions" in flags
        # CRITICAL: Must NEVER emit ZGC flags on Java 8
        assert "-XX:+UseZGC" not in flags
        assert "-XX:+ZGenerational" not in flags

    def test_concurrency_properties_present(self):
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof)

        assert "-Djava.util.concurrent.ForkJoinPool.common.parallelism=8" in flags
        assert "-Dio.netty.eventLoopThreads=8" in flags
        assert "-Dmulticore.enabled=true" in flags
        assert "-Dmulticore.threads=8" in flags
        assert "-Dmulticore.mode=auto" in flags

    def test_tiered_compilation_flags_present(self):
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof)

        assert "-XX:+TieredCompilation" in flags
        assert "-XX:CICompilerCount=4" in flags

    def test_platform_forge_flags(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="forge")

        assert "-Dterminal.jline=false" in flags
        assert "-Dterminal.ansi=true" in flags

    def test_platform_neoforge_flags(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="neoforge")

        assert "-Dterminal.jline=false" in flags
        assert "-Dterminal.ansi=true" in flags

    def test_platform_paper_flags(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="paper")

        assert "-Dpaper.playerconnection.keepalive=60" in flags

    def test_platform_vanilla_flags(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-Dterminal.jline=false" not in flags
        assert "-Dpaper.playerconnection.keepalive=60" not in flags

    def test_server_type_case_insensitivity(self):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        flags_upper = build_multicore_jvm_args(prof, server_type="FORGE")
        flags_mixed = build_multicore_jvm_args(prof, server_type="NeoForge")

        assert "-Dterminal.jline=false" in flags_upper
        assert "-Dterminal.jline=false" in flags_mixed

    def test_agent_flag_included_when_path_set(self):
        prof = get_concurrency_profile(
            cpu_cores=4,
            ram_mb=4096,
            java_version=21,
            agent_path="/opt/agent/mc-multicore-agent.jar",
        )
        flags = build_multicore_jvm_args(prof, include_agent=True)

        assert "-javaagent:/opt/agent/mc-multicore-agent.jar" in flags

        flags_no_agent = build_multicore_jvm_args(prof, include_agent=False)
        assert not any(f.startswith("-javaagent:") for f in flags_no_agent)


# ==============================================================================
# 4. user_jvm_args.txt Writing & Formatting Tests
# ==============================================================================


class TestWriteUserJvmArgs:
    """Tests for user_jvm_args.txt creation, atomic writes, and custom flag preservation."""

    def test_format_user_jvm_args(self):
        flags = ["-XX:+UseG1GC", "-XX:ParallelGCThreads=4"]
        formatted = format_user_jvm_args(flags)

        assert "# Generated by Minecraft-Controller Lynx Multi-Core Engine (LMCE)" in formatted
        assert "-XX:+UseG1GC" in formatted
        assert "-XX:ParallelGCThreads=4" in formatted
        assert formatted.endswith("\n")

    def test_write_valid_server_dir(self, tmp_path):
        flags = ["-XX:+UseG1GC", "-XX:ParallelGCThreads=4"]
        target = write_user_jvm_args(tmp_path, flags)

        assert target.is_file()
        assert target.name == "user_jvm_args.txt"
        content = target.read_text(encoding="utf-8")
        assert "-XX:+UseG1GC" in content
        assert "-XX:ParallelGCThreads=4" in content

    def test_creates_server_dir_if_missing(self, tmp_path):
        nested_dir = tmp_path / "servers" / "forge_test"
        assert not nested_dir.exists()

        target = write_user_jvm_args(nested_dir, ["-XX:+UseG1GC"])
        assert nested_dir.is_dir()
        assert target.is_file()

    def test_atomic_overwrite_preserves_custom_flags(self, tmp_path):
        target = tmp_path / "user_jvm_args.txt"
        existing_content = (
            "# User memory settings\n"
            "-Xmx6G\n"
            "-Xms2G\n"
            "-Dcustom.property=true\n"
            "# Old LMCE block\n"
            "# --- Lynx Multi-Core Engine (LMCE) Configuration ---\n"
            "-XX:ParallelGCThreads=2\n"
            "# --- End Lynx Multi-Core Engine Configuration ---\n"
        )
        target.write_text(existing_content, encoding="utf-8")

        new_flags = ["-XX:ParallelGCThreads=8", "-Dio.netty.eventLoopThreads=8"]
        write_user_jvm_args(tmp_path, new_flags)

        updated_content = target.read_text(encoding="utf-8")
        # Preserved user lines
        assert "-Xmx6G" in updated_content
        assert "-Xms2G" in updated_content
        assert "-Dcustom.property=true" in updated_content
        # Updated LMCE flags
        assert "-XX:ParallelGCThreads=8" in updated_content
        assert "-Dio.netty.eventLoopThreads=8" in updated_content
        # Old LMCE line removed
        assert "-XX:ParallelGCThreads=2" not in updated_content

    def test_not_a_directory_error(self, tmp_path):
        regular_file = tmp_path / "not_a_dir.txt"
        regular_file.write_text("hello", encoding="utf-8")

        with pytest.raises(NotADirectoryError):
            write_user_jvm_args(regular_file, ["-XX:+UseG1GC"])

    def test_permission_error_handling(self, tmp_path):
        with patch.object(Path, "replace", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                write_user_jvm_args(tmp_path, ["-XX:+UseG1GC"])

    def test_quote_jvm_arg_edge_cases(self):
        from backend.multicore.jvm_args_builder import quote_jvm_arg

        assert quote_jvm_arg("-XX:+UseG1GC") == "-XX:+UseG1GC"
        assert quote_jvm_arg("-javaagent:C:/Program Files/agent.jar") == '"-javaagent:C:/Program Files/agent.jar"'
        assert quote_jvm_arg('"-javaagent:C:/Program Files/agent.jar"') == '"-javaagent:C:/Program Files/agent.jar"'
        assert quote_jvm_arg("'-javaagent:C:/Program Files/agent.jar'") == "'-javaagent:C:/Program Files/agent.jar'"
        assert quote_jvm_arg('-Dcustom.msg="Hello World"') == '-Dcustom.msg="Hello World"'
        assert quote_jvm_arg(r"-javaagent:C:\Program Files\agent.jar") == '"-javaagent:C:/Program Files/agent.jar"'

    def test_format_user_jvm_args_quotes_arguments_with_spaces(self):
        flags = [
            "-XX:+UseG1GC",
            "-javaagent:C:/Program Files/Minecraft/agent.jar",
            "-Dcustom.title=My Great Server",
        ]
        formatted = format_user_jvm_args(flags)
        lines = formatted.splitlines()

        assert "-XX:+UseG1GC" in lines
        assert '"-javaagent:C:/Program Files/Minecraft/agent.jar"' in lines
        assert '"-Dcustom.title=My Great Server"' in lines

    def test_write_user_jvm_args_in_directory_with_spaces(self, tmp_path):
        from backend.multicore.jvm_args_builder import quote_jvm_arg

        spaced_dir = tmp_path / "My Spaced Minecraft Server"
        flags = ["-XX:+UseG1GC", f"-javaagent:{spaced_dir / 'agent.jar'}"]
        target = write_user_jvm_args(spaced_dir, flags)

        assert target.is_file()
        assert target.parent == spaced_dir
        content = target.read_text(encoding="utf-8")
        expected_arg = quote_jvm_arg(f"-javaagent:{spaced_dir / 'agent.jar'}")
        assert expected_arg in content


# ==============================================================================
# 5. Agent Manager & JAR Packaging Tests
# ==============================================================================


class TestAgentManager:
    """Tests for agent JAR discovery, compilation, packaging, and validation."""

    def test_validate_agent_jar_bundled(self):
        assert BUNDLED_AGENT_JAR.is_file(), "Bundled agent jar should exist"
        assert validate_agent_jar(BUNDLED_AGENT_JAR) is True

    def test_validate_agent_jar_invalid_cases(self, tmp_path):
        # Non-existent
        assert validate_agent_jar(tmp_path / "missing.jar") is False

        # Zero bytes
        empty_jar = tmp_path / "empty.jar"
        empty_jar.touch()
        assert validate_agent_jar(empty_jar) is False

        # Bad zip
        bad_zip = tmp_path / "bad.jar"
        bad_zip.write_bytes(b"not a valid zip file content")
        assert validate_agent_jar(bad_zip) is False

        # Zip without manifest
        no_manifest = tmp_path / "no_manifest.jar"
        with zipfile.ZipFile(no_manifest, "w") as zf:
            zf.writestr("test.txt", "hello")
        assert validate_agent_jar(no_manifest) is False

        # Zip with manifest missing Premain-Class
        wrong_manifest = tmp_path / "wrong_manifest.jar"
        with zipfile.ZipFile(wrong_manifest, "w") as zf:
            zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nMain-Class: Main\r\n\r\n")
        assert validate_agent_jar(wrong_manifest) is False

    def test_ensure_agent_binary_already_exists_valid(self, tmp_path):
        jar_path = tmp_path / AGENT_JAR_NAME
        jar_path.write_bytes(BUNDLED_AGENT_JAR.read_bytes())

        res = ensure_agent_binary(tmp_path)
        assert res == jar_path
        assert validate_agent_jar(res) is True

    def test_ensure_agent_binary_creates_jar_with_manifest(self, tmp_path):
        target_dir = tmp_path / "server_test"
        res = ensure_agent_binary(target_dir)

        assert res.is_file()
        assert res.name == AGENT_JAR_NAME
        assert validate_agent_jar(res) is True

        # Verify manifest contents
        with zipfile.ZipFile(res, "r") as zf:
            manifest_text = zf.read("META-INF/MANIFEST.MF").decode("utf-8")
            assert "Premain-Class: com.lynx.multicore.agent.MultiCoreAgent" in manifest_text
            assert "Agent-Class: com.lynx.multicore.agent.MultiCoreAgent" in manifest_text
            assert "Can-Redefine-Classes: true" in manifest_text
            assert "Can-Retransform-Classes: true" in manifest_text

    def test_ensure_agent_binary_replaces_corrupted_jar(self, tmp_path):
        corrupted_jar = tmp_path / AGENT_JAR_NAME
        corrupted_jar.write_bytes(b"corrupt 010101")
        assert validate_agent_jar(corrupted_jar) is False

        res = ensure_agent_binary(tmp_path)
        assert res == corrupted_jar
        assert validate_agent_jar(res) is True

    def test_build_agent_jar_custom_output(self, tmp_path):
        custom_out = tmp_path / "custom" / "my-agent.jar"
        built = build_agent_jar(custom_out)

        assert built == custom_out
        assert custom_out.is_file()
        assert validate_agent_jar(custom_out) is True


# ==============================================================================
# 6. prepare_server_multicore_env Integration Tests
# ==============================================================================


class TestPrepareServerMulticoreEnv:
    """Tests for environment preparation across Vanilla, Paper, Forge, and NeoForge."""

    def test_prepare_env_vanilla_no_user_jvm_args(self, tmp_path):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        env = prepare_server_multicore_env(tmp_path, prof, server_type="vanilla")

        assert not (tmp_path / "user_jvm_args.txt").exists()
        assert (tmp_path / AGENT_JAR_NAME).is_file()

        assert env["MULTICORE_ENABLED"] == "1"
        assert env["MULTICORE_THREADS"] == "4"
        assert env["MULTICORE_MODE"] == "auto"
        assert env["MULTICORE_ALLOCATED_CORES"] == "4"
        assert env["FORK_JOIN_PARALLELISM"] == "4"
        assert env["NETTY_THREADS"] == "4"
        assert env["GC_THREADS"] == "4"
        assert "-XX:+UseZGC" in env["ALL_JAVA_ARGS"]
        assert "-javaagent:" in env["ALL_JAVA_ARGS"]
        assert env["MC_MULTICORE_AGENT_PATH"] == str(tmp_path / AGENT_JAR_NAME)

    def test_prepare_env_paper_no_user_jvm_args(self, tmp_path):
        prof = get_concurrency_profile(cpu_cores=6, ram_mb=2048, java_version=17)
        env = prepare_server_multicore_env(tmp_path, prof, server_type="paper")

        assert not (tmp_path / "user_jvm_args.txt").exists()
        assert (tmp_path / AGENT_JAR_NAME).is_file()
        assert "-Dpaper.playerconnection.keepalive=60" in env["ALL_JAVA_ARGS"]

    def test_prepare_env_forge_writes_user_jvm_args(self, tmp_path):
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=21)
        env = prepare_server_multicore_env(tmp_path, prof, server_type="forge")

        user_jvm_args = tmp_path / "user_jvm_args.txt"
        assert user_jvm_args.is_file()

        content = user_jvm_args.read_text(encoding="utf-8")
        assert "-XX:+UseZGC" in content
        assert "-XX:+ZGenerational" in content
        assert "-Dterminal.jline=false" in content
        assert "-Dterminal.ansi=true" in content
        assert "-javaagent:" in content

        assert env["MULTICORE_ENABLED"] == "1"
        assert env["MULTICORE_THREADS"] == "8"

    def test_prepare_env_neoforge_writes_user_jvm_args(self, tmp_path):
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=21)
        env = prepare_server_multicore_env(tmp_path, prof, server_type="neoforge")

        user_jvm_args = tmp_path / "user_jvm_args.txt"
        assert user_jvm_args.is_file()

        content = user_jvm_args.read_text(encoding="utf-8")
        assert "-XX:+UseZGC" in content
        assert "-Dterminal.jline=false" in content

    def test_prepare_env_forge_readonly_fallback(self, tmp_path):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)

        with patch(
            "backend.multicore.jvm_args_builder.write_user_jvm_args",
            side_effect=PermissionError("Read-only file system"),
        ):
            # Should NOT crash; logs warning and returns complete env dictionary
            env = prepare_server_multicore_env(tmp_path, prof, server_type="forge")
            assert env["MULTICORE_ENABLED"] == "1"
            assert env["ALL_JAVA_ARGS"] != ""
            assert "-javaagent:" in env["ALL_JAVA_ARGS"]

    def test_prepare_env_all_required_keys_present(self, tmp_path):
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=2048, java_version=17)
        env = prepare_server_multicore_env(tmp_path, prof, server_type="vanilla")

        required_keys = {
            "MULTICORE_ENABLED",
            "MULTICORE_THREADS",
            "MULTICORE_MODE",
            "MULTICORE_ALLOCATED_CORES",
            "FORK_JOIN_PARALLELISM",
            "NETTY_THREADS",
            "GC_THREADS",
            "ALL_JAVA_ARGS",
            "JAVA_TOOL_OPTIONS",
            "MC_MULTICORE_AGENT_PATH",
        }
        assert required_keys.issubset(set(env.keys()))

    def test_prepare_server_multicore_env_spaced_path_execution(self, tmp_path):
        import shutil
        import subprocess

        spaced_dir = tmp_path / "My Minecraft Server (Forge)"
        prof = get_concurrency_profile(cpu_cores=2, ram_mb=2048, java_version=21)
        env = prepare_server_multicore_env(spaced_dir, prof, server_type="forge")

        user_jvm_args = spaced_dir / "user_jvm_args.txt"
        assert user_jvm_args.is_file()
        content = user_jvm_args.read_text(encoding="utf-8")

        # Quoted javaagent in file
        expected_quoted = f'"{ "-javaagent:" + (spaced_dir / AGENT_JAR_NAME).as_posix() }"'
        assert expected_quoted in content

        # Live JVM argfile boot test with java @user_jvm_args.txt -version
        if shutil.which("java"):
            res = subprocess.run(
                ["java", "@user_jvm_args.txt", "-version"],
                cwd=spaced_dir,
                capture_output=True,
                text=True,
            )
            assert res.returncode == 0, f"JVM @argfile boot failed: {res.stdout}\n{res.stderr}"
            assert "Lynx Multi-Core Engine (LMCE) - Universal Java Agent" in (res.stdout + res.stderr)

            # Live JVM JAVA_TOOL_OPTIONS boot test
            test_env = os.environ.copy()
            test_env["JAVA_TOOL_OPTIONS"] = env["JAVA_TOOL_OPTIONS"]
            res_env = subprocess.run(["java", "-version"], env=test_env, capture_output=True, text=True)
            assert res_env.returncode == 0, f"JVM JAVA_TOOL_OPTIONS boot failed: {res_env.stdout}\n{res_env.stderr}"
