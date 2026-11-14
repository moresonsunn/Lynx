"""Empirical challenger test suite for Milestone 1: Multi-Core Engine Core & Universal Agent.

Verifies:
1. mc-multicore-agent.jar archive integrity, class file bytecode version (Java 8 / v52), and manifest.
2. Direct JVM execution with -javaagent flag, banner printing, and graceful shutdown hook.
3. Configuration argument parsing and resilience against malformed inputs.
4. Concurrency stress harness verifying mutual exclusion between dimension ticks and atomic world save locks.
5. prepare_server_multicore_env environment variable and user_jvm_args.txt contract verification.
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path
import pytest

from backend.multicore import (
    get_concurrency_profile,
    prepare_server_multicore_env,
    build_multicore_jvm_args,
    build_env_vars,
    ensure_agent_binary,
    validate_agent_jar,
    AGENT_JAR_NAME,
)
from backend.multicore.agent_manager import (
    AGENT_PREMAIN_CLASS,
    AGENT_CLASS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLED_JAR = REPO_ROOT / "backend" / "multicore" / "agent" / AGENT_JAR_NAME


class TestJarArchiveIntegrity:
    """Empirical verification of the mc-multicore-agent.jar archive."""

    def test_jar_exists_and_valid_zip(self):
        assert BUNDLED_JAR.is_file(), f"JAR not found at {BUNDLED_JAR}"
        assert BUNDLED_JAR.stat().st_size > 0
        assert zipfile.is_zipfile(BUNDLED_JAR)

    def test_manifest_entries_and_headers(self):
        with zipfile.ZipFile(BUNDLED_JAR, "r") as zf:
            namelist = zf.namelist()
            assert "META-INF/MANIFEST.MF" in namelist

            manifest_content = zf.read("META-INF/MANIFEST.MF").decode("utf-8")
            assert f"Premain-Class: {AGENT_PREMAIN_CLASS}" in manifest_content
            assert f"Agent-Class: {AGENT_CLASS}" in manifest_content
            assert "Can-Redefine-Classes: true" in manifest_content
            assert "Can-Retransform-Classes: true" in manifest_content

    def test_all_class_files_present_and_java8_bytecode(self):
        """Verify bytecode version is 52.0 (Java 8) for universal compatibility."""
        expected_classes = [
            "com/lynx/multicore/agent/MultiCoreAgent.class",
            "com/lynx/multicore/agent/DimensionDispatcher.class",
            "com/lynx/multicore/agent/DimensionDispatcher$1.class",
            "com/lynx/multicore/agent/DimensionDispatcher$2.class",
            "com/lynx/multicore/agent/WorldSaveBarrier.class",
            "com/lynx/multicore/agent/WorldSaveBarrier$1.class",
            "com/lynx/multicore/agent/DimensionTransferQueue.class",
            "com/lynx/multicore/agent/DimensionTransferQueue$EntityTransfer.class",
            "com/lynx/multicore/agent/MulticoreConfig.class",
            "com/lynx/multicore/agent/WorkerPoolScaler.class",
            "com/lynx/multicore/agent/WorkerPoolScaler$1.class",
        ]

        with zipfile.ZipFile(BUNDLED_JAR, "r") as zf:
            names = set(zf.namelist())
            for cls_name in expected_classes:
                assert cls_name in names, f"Missing class in JAR: {cls_name}"
                data = zf.read(cls_name)
                # Verify CAFEBABE magic
                assert data[:4] == b"\xca\xfe\xba\xbe", f"Invalid class magic in {cls_name}"
                # Verify major version 52 (Java 8)
                major_version = int.from_bytes(data[6:8], "big")
                assert major_version == 52, f"Class {cls_name} has major version {major_version}, expected 52 (Java 8)"


class TestJvmAgentExecution:
    """Empirical verification of JVM startup with -javaagent attached."""

    def test_jvm_starts_with_agent_and_prints_banner(self):
        jar_path = str(BUNDLED_JAR).replace("\\", "/")
        cmd = ["java", f"-javaagent:{jar_path}", "-version"]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = result.stdout + result.stderr

        if "Server shutdown detected. Coordinating graceful multi-core world flush..." not in output:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = result.stdout + result.stderr

        assert result.returncode == 0, f"JVM failed with code {result.returncode}: {output}"
        assert "Lynx Multi-Core Engine (LMCE) - Universal Java Agent" in output
        assert "[LMCE] Active Configuration:" in output
        assert "[LMCE] Scaled background worker pool to" in output
        assert "[LMCE] Initialized DimensionDispatcher with" in output
        assert "[LMCE] Universal Multi-Core Agent successfully initialized and armed." in output
        assert "Server shutdown detected. Coordinating graceful multi-core world flush..." in output

    def test_jvm_agent_arguments_configuration(self):
        jar_path = str(BUNDLED_JAR).replace("\\", "/")
        cmd = [
            "java",
            f"-javaagent:{jar_path}=cores=4,mode=parallel_dimensions,asyncsave=false",
            "-version",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = result.stdout + result.stderr

        assert result.returncode == 0, f"JVM failed: {output}"
        assert "cores=4" in output
        assert "mode=parallel_dimensions" in output
        assert "asyncSave=false" in output
        # With asyncsave=false, shutdown hook should NOT be registered
        assert "Server shutdown detected. Coordinating graceful multi-core world flush..." not in output

    def test_jvm_agent_resilience_malformed_arguments(self):
        jar_path = str(BUNDLED_JAR).replace("\\", "/")
        cmd = [
            "java",
            f"-javaagent:{jar_path}=invalid,,threads=nan,cores=-10",
            "-version",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = result.stdout + result.stderr

        assert result.returncode == 0, f"JVM crashed on malformed agent args: {output}"
        assert "Universal Multi-Core Agent successfully initialized and armed." in output


class TestConcurrentStressHarness:
    """Empirical verification of concurrency, mutual exclusion, and deadlock freedom."""

    def test_agent_stress_harness_execution(self):
        classes_dir = REPO_ROOT / "backend" / "tests" / "classes"
        harness_src = REPO_ROOT / "backend" / "tests" / "AgentStressHarness.java"

        # Ensure classes compiled
        classes_dir.mkdir(parents=True, exist_ok=True)
        compile_cmd = [
            "javac",
            "-cp",
            str(BUNDLED_JAR),
            "-d",
            str(classes_dir),
            str(harness_src),
        ]
        compile_res = subprocess.run(compile_cmd, capture_output=True, text=True, check=False)
        assert compile_res.returncode == 0, f"Compilation failed: {compile_res.stderr}"

        # Run harness with -javaagent attached
        jar_path = str(BUNDLED_JAR).replace("\\", "/")
        cp = f"{jar_path};{str(classes_dir).replace('\\', '/')}"
        run_cmd = [
            "java",
            f"-javaagent:{jar_path}",
            "-cp",
            cp,
            "com.lynx.multicore.tests.AgentStressHarness",
            "16",
        ]

        run_res = subprocess.run(run_cmd, capture_output=True, text=True, check=False, timeout=90)
        output = run_res.stdout + run_res.stderr

        assert run_res.returncode == 0, f"Stress harness failed with code {run_res.returncode}: {output}"
        assert "Concurrency Violations: 0" in output
        assert "SUCCESS: Zero deadlocks, zero race conditions, full mutual exclusion verified." in output


class TestPrepareServerMulticoreEnvRigorous:
    """Empirical tests for environment variable synthesis and file contracts."""

    @pytest.mark.parametrize("server_type", ["vanilla", "paper", "forge", "neoforge"])
    def test_required_env_keys_across_all_platforms(self, tmp_path: Path, server_type: str):
        profile = get_concurrency_profile(cpu_cores=8, ram_mb=8192, java_version=21)
        env = prepare_server_multicore_env(tmp_path, profile, server_type=server_type)

        required_keys = [
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
        ]
        for key in required_keys:
            assert key in env, f"Missing key {key} in environment"
            assert len(env[key]) > 0, f"Empty value for {key}"

        assert env["MULTICORE_ENABLED"] == "1"
        assert env["MULTICORE_THREADS"] == "8"
        assert env["MULTICORE_ALLOCATED_CORES"] == "8"
        assert env["FORK_JOIN_PARALLELISM"] == "8"

        # Check agent binary was placed in server directory
        server_jar = tmp_path / AGENT_JAR_NAME
        assert server_jar.is_file()
        assert validate_agent_jar(server_jar)
        assert Path(env["MC_MULTICORE_AGENT_PATH"]).resolve() == server_jar.resolve()

    def test_user_jvm_args_only_created_for_forge_and_neoforge(self, tmp_path: Path):
        profile = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)

        vanilla_dir = tmp_path / "vanilla"
        prepare_server_multicore_env(vanilla_dir, profile, server_type="vanilla")
        assert not (vanilla_dir / "user_jvm_args.txt").exists()

        paper_dir = tmp_path / "paper"
        prepare_server_multicore_env(paper_dir, profile, server_type="paper")
        assert not (paper_dir / "user_jvm_args.txt").exists()

        forge_dir = tmp_path / "forge"
        prepare_server_multicore_env(forge_dir, profile, server_type="forge")
        assert (forge_dir / "user_jvm_args.txt").is_file()
        forge_content = (forge_dir / "user_jvm_args.txt").read_text(encoding="utf-8")
        assert "-Dterminal.jline=false" in forge_content
        assert "-XX:+UseZGC" in forge_content

        neoforge_dir = tmp_path / "neoforge"
        prepare_server_multicore_env(neoforge_dir, profile, server_type="neoforge")
        assert (neoforge_dir / "user_jvm_args.txt").is_file()
        neoforge_content = (neoforge_dir / "user_jvm_args.txt").read_text(encoding="utf-8")
        assert "-Dterminal.jline=false" in neoforge_content
        assert "-XX:+UseZGC" in neoforge_content

    def test_env_java_tool_options_omits_unsupported_flags(self, tmp_path: Path):
        profile = get_concurrency_profile(cpu_cores=4, ram_mb=4096, java_version=21)
        env = prepare_server_multicore_env(tmp_path, profile, server_type="forge")

        java_tool_options = env["JAVA_TOOL_OPTIONS"]
        assert "-Dterminal.jline=false" not in java_tool_options
        assert "-Dterminal.ansi=true" not in java_tool_options
        assert "-XX:+UseZGC" in java_tool_options
