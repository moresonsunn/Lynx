"""Lynx Multi-Core Engine (LMCE) - Adversarial Stress & Property-Based Test Harness.

Empirically challenges the multicore module against:
1. 5,292-combination full-factorial property matrix (cores x ram x java_version x server_type).
2. Fuzzing with boundary, negative, and extreme integer values.
3. String type resilience and input sanitization bug demonstration.
4. Deep directory nesting and non-ASCII path idempotence.
5. Existing user_jvm_args.txt preservation over multiple re-writes.
6. Live Java agent bytecode verification and JVM execution under adversarial agent arguments.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, List, Optional

import pytest

import backend.multicore as mc
from backend.multicore.agent_manager import (
    AGENT_JAR_NAME,
    AGENT_PREMAIN_CLASS,
    BUNDLED_AGENT_JAR,
    build_agent_jar,
    ensure_agent_binary,
    validate_agent_jar,
)
from backend.multicore.concurrency_profile import (
    ConcurrencyProfile,
    MultiCoreConfig,
    detect_available_cores,
    get_concurrency_profile,
)
from backend.multicore.jvm_args_builder import (
    LMCE_HEADER_END,
    LMCE_HEADER_START,
    build_env_vars,
    build_multicore_jvm_args,
    format_user_jvm_args,
    prepare_server_multicore_env,
    write_user_jvm_args,
)


# ==============================================================================
# 1. Full Combinatorial Property Matrix Test (5,292 combinations)
# ==============================================================================

CORES_MATRIX = [-5, 0, 1, 2, 3, 4, 7, 8, 15, 16, 32, 64, 128, None]
RAM_MATRIX = [0, 256, 1024, 2048, 4096, 8192, 16384, 32768, None]
JAVA_VERSIONS_MATRIX = [7, 8, 11, 16, 17, 21, 25]
SERVER_TYPES_MATRIX = ["vanilla", "paper", "forge", "neoforge", "fabric", "purpur"]


class TestCombinatorialPropertyMatrix:
    """Evaluates invariant properties across the full 5,292-case matrix specified in M1 Challenger prompt."""

    def test_full_property_matrix_invariants(self):
        tested_count = 0

        for cores in CORES_MATRIX:
            for ram in RAM_MATRIX:
                for java_ver in JAVA_VERSIONS_MATRIX:
                    for server_type in SERVER_TYPES_MATRIX:
                        tested_count += 1
                        # 1. Must never raise unhandled exceptions
                        profile = get_concurrency_profile(
                            cores=cores,
                            ram_mb=ram,
                            java_version=java_ver,
                        )
                        flags = build_multicore_jvm_args(profile, server_type=server_type)

                        # 2. Invariant: Java 8/7/11/16 must NEVER emit ZGC flags
                        if java_ver <= 16:
                            assert "-XX:+UseZGC" not in flags, (
                                f"Java {java_ver} emitted -XX:+UseZGC with cores={cores}, ram={ram}"
                            )
                            assert "-XX:+ZGenerational" not in flags, (
                                f"Java {java_ver} emitted -XX:+ZGenerational with cores={cores}, ram={ram}"
                            )
                            # Legacy Java 8 should include legacy G1GC flags
                            if java_ver == 8:
                                assert "-XX:+UseG1GC" in flags
                                assert "-XX:+UseStringDeduplication" in flags

                        # 3. Invariant: Java 17 must NEVER emit -XX:+ZGenerational
                        if java_ver == 17:
                            assert "-XX:+ZGenerational" not in flags, (
                                f"Java 17 emitted -XX:+ZGenerational with cores={cores}, ram={ram}"
                            )
                            assert "-XX:+UseG1GC" in flags

                        # 4. Invariant: Java 21+ with RAM >= 4096 must emit Generational ZGC
                        effective_ram = ram if (ram is not None and ram > 0) else 2048
                        if java_ver >= 21 and effective_ram >= 4096:
                            assert "-XX:+UseZGC" in flags, (
                                f"Java {java_ver} RAM {ram} missing -XX:+UseZGC"
                            )
                            assert "-XX:+ZGenerational" in flags, (
                                f"Java {java_ver} RAM {ram} missing -XX:+ZGenerational"
                            )
                        elif java_ver >= 21 and effective_ram < 4096:
                            # Low-RAM fallback to G1GC
                            assert "-XX:+UseG1GC" in flags
                            assert "-XX:+ZGenerational" not in flags

                        # 5. Invariant: In all multi-core cases (cores is None or cores >= 2 or cores <= 1 clamped to 2),
                        # worker_threads >= 2 and fork_join_parallelism >= 2
                        assert profile.worker_threads >= 2, (
                            f"worker_threads={profile.worker_threads} < 2 for cores={cores}"
                        )
                        assert profile.fork_join_parallelism >= 2, (
                            f"fork_join_parallelism={profile.fork_join_parallelism} < 2 for cores={cores}"
                        )
                        assert profile.ci_compiler_count >= 2, (
                            f"ci_compiler_count={profile.ci_compiler_count} < 2"
                        )
                        assert 1 <= profile.netty_threads <= 16, (
                            f"netty_threads={profile.netty_threads} out of range [1, 16]"
                        )

                        # 6. Invariant: Server-type specific optimizations
                        if server_type in ("forge", "neoforge"):
                            assert "-Dterminal.jline=false" in flags
                            assert "-Dterminal.ansi=true" in flags
                        elif server_type in ("paper", "purpur"):
                            assert "-Dpaper.playerconnection.keepalive=60" in flags

        assert tested_count == len(CORES_MATRIX) * len(RAM_MATRIX) * len(JAVA_VERSIONS_MATRIX) * len(SERVER_TYPES_MATRIX)
        assert tested_count == 5292


# ==============================================================================
# 2. Input Type Resilience & Ordering Bug Findings (Adversarial Stress)
# ==============================================================================

class TestAdversarialTypeHandlingAndBugs:
    """Verifies input sanitization edge cases where string inputs resolve cleanly to target types."""

    def test_ram_mb_string_coercion_bug(self):
        """Passing string '4096' to ram_mb should safely resolve to 4096 MB without raising TypeError."""
        profile = get_concurrency_profile(cpu_cores=4, ram_mb="4096", java_version=21)
        assert profile.ram_mb == 4096
        assert "-XX:+UseZGC" in profile.jvm_flags
        assert "-XX:+ZGenerational" in profile.jvm_flags

    def test_java_version_string_coercion_bug(self):
        """Passing string '8' to java_version should resolve to Java 8, not fall back to 21."""
        profile = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version="8")
        assert profile.java_version == 8
        assert "-XX:+UseZGC" not in profile.jvm_flags
        assert "-XX:+ZGenerational" not in profile.jvm_flags
        assert "-XX:+UseG1GC" in profile.jvm_flags

    def test_java_version_string_coercion_17(self):
        """Passing string '17' to java_version should resolve to Java 17 and strictly forbid ZGenerational."""
        profile = get_concurrency_profile(cpu_cores=4, ram_mb=8192, java_version="17")
        assert profile.java_version == 17
        assert "-XX:+ZGenerational" not in profile.jvm_flags
        assert "-XX:+UseG1GC" in profile.jvm_flags


# ==============================================================================
# 3. Randomized Fuzzing Harness (1,000 iterations over valid/coerced types)
# ==============================================================================

class TestFuzzingHarness:
    """Fuzzes numeric boundaries, negative values, and mode combinations."""

    def test_random_numeric_fuzzing_inputs_no_crash(self):
        fuzz_cores = [-10000, -1, 0, 1, 2, 5, 17, 63, 128, 512, 100000, None]
        fuzz_ram = [-2048, 0, 1, 512, 1024, 4096, 8192, 65536, 1000000, None]
        fuzz_jv = [0, 6, 7, 8, 11, 15, 16, 17, 18, 20, 21, 22, 25, 99]
        fuzz_modes = ["auto", "single_core", "high_throughput", "parallel_dimensions", "parallel_entities", "UNKNOWN_MODE", "", None]
        fuzz_server_types = ["vanilla", "paper", "forge", "neoforge", "fabric", "purpur", "custom_engine", "", None]

        random.seed(42)  # Deterministic seed for reproducible challenger tests

        for _ in range(1000):
            c = random.choice(fuzz_cores)
            r = random.choice(fuzz_ram)
            j = random.choice(fuzz_jv)
            m = random.choice(fuzz_modes)
            st = random.choice(fuzz_server_types)

            prof = get_concurrency_profile(
                cpu_cores=c,
                ram_mb=r,
                java_version=j,
                mode=str(m) if m is not None else "auto",
            )

            # Invariant checks
            assert prof.allocated_cores >= 1
            assert prof.worker_threads >= 1
            assert prof.fork_join_parallelism >= 1
            assert prof.gc_threads >= 1
            assert prof.conc_gc_threads >= 1
            assert prof.ci_compiler_count >= 2

            flags = build_multicore_jvm_args(prof, server_type=str(st) if st else "")
            assert isinstance(flags, list)
            assert len(flags) > 5

            # Must serialize cleanly to JSON
            as_dict = prof.as_dict()
            json_str = json.dumps(as_dict)
            assert len(json_str) > 0


# ==============================================================================
# 4. Deep Directory Nesting, Missing Folders & Non-ASCII Paths
# ==============================================================================

class TestFileSystemEdgeCases:
    """Stress tests file system paths: deep nesting, missing directories, non-ASCII."""

    def test_deep_directory_nesting_write_user_jvm_args(self, tmp_path):
        deep_dir = tmp_path
        for level in range(15):
            deep_dir = deep_dir / f"nested_level_{level}"

        assert not deep_dir.exists()

        flags = ["-Xmx8G", "-XX:+UseZGC", "-XX:+ZGenerational"]
        result_path = write_user_jvm_args(deep_dir, flags)

        assert result_path.is_file()
        assert result_path.name == "user_jvm_args.txt"
        content = result_path.read_text(encoding="utf-8")
        assert "-XX:+UseZGC" in content
        assert LMCE_HEADER_START in content
        assert LMCE_HEADER_END in content

    def test_non_ascii_unicode_directory_path(self, tmp_path):
        unicode_dir = tmp_path / "server_äöü_日本語_🚀_srv"
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)

        env = prepare_server_multicore_env(unicode_dir, prof, server_type="forge")

        assert unicode_dir.is_dir()
        target_file = unicode_dir / "user_jvm_args.txt"
        assert target_file.is_file()
        agent_file = unicode_dir / AGENT_JAR_NAME
        assert agent_file.is_file()
        assert validate_agent_jar(agent_file)
        assert env["MULTICORE_ENABLED"] == "1"

    def test_write_user_jvm_args_on_existing_file_raises_not_a_directory(self, tmp_path):
        file_path = tmp_path / "fake_dir_is_file.txt"
        file_path.write_text("i am a file", encoding="utf-8")

        with pytest.raises(NotADirectoryError):
            write_user_jvm_args(file_path, ["-XX:+UseG1GC"])

    def test_server_dir_with_spaces_argfile_jvm_execution(self, tmp_path):
        """Server directory with spaces correctly quotes -javaagent in user_jvm_args.txt and executes cleanly."""
        spaced_dir = tmp_path / "Adversarial Spaced Server Directory"
        prof = get_concurrency_profile(cpu_cores=2, ram_mb=2048, java_version=21)
        env = prepare_server_multicore_env(spaced_dir, prof, server_type="forge")

        argfile = spaced_dir / "user_jvm_args.txt"
        assert argfile.is_file()
        content = argfile.read_text(encoding="utf-8")

        for line in content.splitlines():
            if "-javaagent:" in line:
                assert line.startswith('"') and line.endswith('"')

        if shutil.which("java"):
            cmd = ["java", "@user_jvm_args.txt", "-version"]
            res = subprocess.run(cmd, cwd=spaced_dir, capture_output=True, text=True, check=False)
            assert res.returncode == 0, f"JVM failed to launch on spaced path: {res.stderr}"


# ==============================================================================
# 5. Idempotence & Existing Flags Preservation
# ==============================================================================

class TestIdempotenceAndPreservation:
    """Verifies that existing user flags are preserved and multiple writes do not duplicate blocks."""

    def test_repeated_writes_preserve_custom_flags_idempotently(self, tmp_path):
        server_dir = tmp_path / "forge_server"
        server_dir.mkdir(parents=True)
        target_file = server_dir / "user_jvm_args.txt"

        # Pre-seed user_jvm_args.txt with custom user configurations
        initial_user_config = (
            "# Custom Server Startup Options\n"
            "-Xms4096M\n"
            "-Xmx8192M\n"
            "-Dcustom.user.prop=special_value\n"
            "-XX:+UnlockDiagnosticVMOptions\n"
        )
        target_file.write_text(initial_user_config, encoding="utf-8")

        prof1 = get_concurrency_profile(cpu_cores=4, ram_mb=8192, java_version=21)
        flags1 = build_multicore_jvm_args(prof1, server_type="forge")

        # Write 1
        write_user_jvm_args(server_dir, flags1)
        content1 = target_file.read_text(encoding="utf-8")

        # Assert custom flags preserved
        assert "-Xms4096M" in content1
        assert "-Xmx8192M" in content1
        assert "-Dcustom.user.prop=special_value" in content1
        assert content1.count(LMCE_HEADER_START) == 1
        assert content1.count(LMCE_HEADER_END) == 1

        # Write 2 (same flags - must be completely idempotent)
        write_user_jvm_args(server_dir, flags1)
        content2 = target_file.read_text(encoding="utf-8")
        assert content2 == content1

        # Write 3 (updated profile: scaled to 8 cores)
        prof2 = get_concurrency_profile(cpu_cores=8, ram_mb=16384, java_version=21)
        flags2 = build_multicore_jvm_args(prof2, server_type="forge")
        write_user_jvm_args(server_dir, flags2)
        content3 = target_file.read_text(encoding="utf-8")

        # Custom flags STILL preserved
        assert "-Xms4096M" in content3
        assert "-Xmx8192M" in content3
        assert "-Dcustom.user.prop=special_value" in content3
        assert content3.count(LMCE_HEADER_START) == 1
        assert content3.count(LMCE_HEADER_END) == 1
        # Updated core flags
        assert "-Dmulticore.threads=8" in content3
        assert "-Dio.netty.eventLoopThreads=8" in content3

    def test_prepare_server_multicore_env_idempotence(self, tmp_path):
        server_dir = tmp_path / "paper_server"
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)

        # Call prepare 3 times consecutively
        env1 = prepare_server_multicore_env(server_dir, prof, server_type="paper")
        env2 = prepare_server_multicore_env(server_dir, prof, server_type="paper")
        env3 = prepare_server_multicore_env(server_dir, prof, server_type="paper")

        assert env1 == env2 == env3
        # Paper server does NOT generate user_jvm_args.txt
        assert not (server_dir / "user_jvm_args.txt").exists()
        # But agent JAR must exist and be valid
        agent_jar = server_dir / AGENT_JAR_NAME
        assert agent_jar.is_file()
        assert validate_agent_jar(agent_jar)


# ==============================================================================
# 6. Java Agent Bytecode Integrity & Subprocess Execution
# ==============================================================================

class TestJavaAgentBytecodeAndRuntime:
    """Verifies Java agent bytecode compliance (Java 8 / major 52) and real JVM execution."""

    def test_agent_jar_bytecode_major_version(self):
        """All class files in mc-multicore-agent.jar must have major version 52 (Java 8)."""
        agent_path = BUNDLED_AGENT_JAR
        assert agent_path.is_file(), f"Agent JAR not found at {agent_path}"

        with zipfile.ZipFile(agent_path, "r") as zf:
            class_names = [n for n in zf.namelist() if n.endswith(".class")]
            assert len(class_names) >= 6, f"Expected at least 6 class files, found {len(class_names)}"

            for class_name in class_names:
                data = zf.read(class_name)
                magic, minor, major = struct.unpack(">IHH", data[:8])
                assert magic == 0xCAFEBABE, f"Class {class_name} has invalid magic: {hex(magic)}"
                assert major == 52, f"Class {class_name} has major version {major} (expected 52 for Java 8 compatibility)"
                assert minor == 0, f"Class {class_name} has non-zero minor version {minor}"

    def test_agent_manifest_headers(self):
        """Manifest must contain all required Java agent headers."""
        with zipfile.ZipFile(BUNDLED_AGENT_JAR, "r") as zf:
            manifest_bytes = zf.read("META-INF/MANIFEST.MF")
            manifest_text = manifest_bytes.decode("utf-8")

            assert f"Premain-Class: {AGENT_PREMAIN_CLASS}" in manifest_text
            assert "Can-Redefine-Classes: true" in manifest_text
            assert "Can-Retransform-Classes: true" in manifest_text

    def test_live_java_execution_default_agent(self):
        """Execute `java -javaagent:... -version` and verify clean initialization and exit code 0."""
        cmd = ["java", f"-javaagent:{BUNDLED_AGENT_JAR}", "-version"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        combined_output = proc.stdout + "\n" + proc.stderr
        assert proc.returncode == 0, f"Java agent execution failed with returncode {proc.returncode}: {combined_output}"
        assert "Lynx Multi-Core Engine (LMCE) - Universal Java Agent" in combined_output
        assert "Universal Multi-Core Agent successfully initialized and armed." in combined_output

    def test_live_java_execution_custom_agent_parameters(self):
        """Execute with explicit agent arguments: cores=6, mode=high_throughput, asyncsave=false."""
        agent_arg = f"-javaagent:{BUNDLED_AGENT_JAR}=cores=6,mode=high_throughput,asyncsave=false"
        cmd = ["java", agent_arg, "-version"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        combined_output = proc.stdout + "\n" + proc.stderr
        assert proc.returncode == 0, f"Execution failed: {combined_output}"
        assert "Active Configuration: cores=6, mode=high_throughput, asyncSave=false" in combined_output
        assert "Scaled background worker pool to 6 threads (Multicore-Worker-N)." in combined_output
        assert "Initialized DimensionDispatcher with 6 worker threads (mode=high_throughput)." in combined_output

    def test_live_java_execution_adversarial_malformed_args(self):
        """Pass malformed and negative agent parameters; must handle gracefully without crashing JVM."""
        agent_arg = f"-javaagent:{BUNDLED_AGENT_JAR}=cores=-999,mode=invalid_crazy_mode,threads=not_an_int"
        cmd = ["java", agent_arg, "-version"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        combined_output = proc.stdout + "\n" + proc.stderr
        assert proc.returncode == 0, f"Malformed args caused crash: {combined_output}"
        assert "Universal Multi-Core Agent successfully initialized and armed." in combined_output

    def test_live_java_execution_system_properties_injection(self):
        """Inject -Dmulticore.threads and -Dmulticore.mode via JVM command line."""
        cmd = [
            "java",
            "-Dmulticore.threads=12",
            "-Dmulticore.mode=parallel_entities",
            f"-javaagent:{BUNDLED_AGENT_JAR}",
            "-version",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        combined_output = proc.stdout + "\n" + proc.stderr
        assert proc.returncode == 0, f"Failed property injection: {combined_output}"
        assert "Active Configuration: cores=12, mode=parallel_entities" in combined_output
        assert "Scaled background worker pool to 12 threads (Multicore-Worker-N)." in combined_output


# ==============================================================================
# 7. Corrupted Agent JAR Auto-Healing
# ==============================================================================

class TestAgentAutoHealing:
    """Verifies that ensure_agent_binary detects corrupted agent JARs and restores them."""

    def test_ensure_agent_binary_heals_truncated_jar(self, tmp_path):
        target_jar = tmp_path / AGENT_JAR_NAME
        target_jar.write_bytes(b"PK\x03\x04corrupted_truncated_junk_bytes")

        assert not validate_agent_jar(target_jar)

        restored_jar = ensure_agent_binary(tmp_path)
        assert restored_jar == target_jar
        assert validate_agent_jar(restored_jar)
        assert target_jar.stat().st_size > 1000
