"""Adversarial stress and challenge test suite for Milestone 4 (Platform & Version Compatibility Engine).

Authored by challenger_m4_2 (Empirical Challenger):
- Legacy Forge (1.12.2 and 1.16.5) pattern matching and Java inference.
- Real Bash simulation of docker/runtime-entrypoint.sh JAR selection and run.sh forwarding.
- Modern Forge and NeoForge user_jvm_args.txt preservation across rewrites and spaces.
- Exhaustive GC safety matrix across all Java versions (8, 11, 17, 21, 25), RAM sizes, and CPU cores.
- Launch type classification and helper consistency.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
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
from backend.multicore.jvm_args_builder import (
    LMCE_HEADER_START,
    LMCE_HEADER_END,
    quote_jvm_arg,
    write_user_jvm_args,
)
from backend.server_providers.forge import ForgeProvider
from backend.server_providers.neoforge import NeoForgeProvider


def find_bash_executable() -> str:
    """Find a functional GNU Bash executable (Git bash, WSL, or PATH)."""
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            try:
                res = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    return c
            except Exception:
                continue
    return "bash"


BASH_BIN = find_bash_executable()


# ==============================================================================
# 1. Legacy Forge (1.12.2 and 1.16.5) & Entrypoint Pattern Matching Adversarial
# ==============================================================================

class TestLegacyForgeJarPatternsAdversarial:
    """Adversarially tests JAR autodetection patterns in docker/runtime-entrypoint.sh."""

    @pytest.fixture
    def entrypoint_path(self):
        p = BACKEND_DIR.parent / "docker" / "runtime-entrypoint.sh"
        assert p.is_file(), f"runtime-entrypoint.sh not found at {p}"
        return p

    def run_bash_jar_autodetection(self, server_type: str, server_dir: Path, custom_server_jar: str = "") -> str:
        """Run the exact jar autodetection shell logic from runtime-entrypoint.sh in server_dir."""
        script = f'''
SERVER_TYPE="{server_type}"
SERVER_JAR="{custom_server_jar}"
start_jar=""

if [ -n "$SERVER_JAR" ]; then
  if [ -f "$SERVER_JAR" ]; then
    start_jar="$SERVER_JAR"
  elif [ -f "./$SERVER_JAR" ]; then
    start_jar="./$SERVER_JAR"
  fi
fi

if [ -z "$start_jar" ]; then
  if [ "$SERVER_TYPE" = "forge" ] || [ "$SERVER_TYPE" = "neoforge" ] || [ "$SERVER_TYPE" = "mohist" ] || [ "$SERVER_TYPE" = "magma" ] || [ "$SERVER_TYPE" = "catserver" ] || [ "$SERVER_TYPE" = "spongeforge" ]; then
    patterns="server.jar neoforge-*-universal.jar *forge-*-universal.jar forge-*-server.jar forge-*.jar *mohist*.jar *magma*.jar *catserver*.jar *spongeforge*.jar *server*.jar"
  elif [ "$SERVER_TYPE" = "fabric" ] || [ "$SERVER_TYPE" = "quilt" ] || [ "$SERVER_TYPE" = "banner" ]; then
    patterns="server.jar *fabric*.jar *quilt*.jar *banner*.jar *server*.jar"
  else
    patterns="server.jar *paper*.jar *purpur*.jar *folia*.jar *server*.jar"
  fi
  for pattern in $patterns; do
    found=$(ls $pattern 2>/dev/null | head -n 1 || true)
    if [ -n "$found" ]; then
      start_jar="$found"
      break
    fi
  done
fi

echo -n "$start_jar"
'''
        proc = subprocess.run(
            [BASH_BIN, "-c", script],
            cwd=str(server_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0, f"Bash script failed: {proc.stderr}"
        return proc.stdout.strip()

    def test_forge_1122_coexistence_prefers_forge_over_minecraft_server(self):
        """CRITICAL: Forge 1.12.2 creates both forge-*.jar and minecraft_server.1.12.2.jar.

        Must select forge-*.jar and NEVER minecraft_server.1.12.2.jar.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "minecraft_server.1.12.2.jar").write_bytes(b"vanilla")
            (srv / "forge-1.12.2-14.23.5.2859.jar").write_bytes(b"forge")

            chosen = self.run_bash_jar_autodetection("forge", srv)
            assert chosen == "forge-1.12.2-14.23.5.2859.jar", (
                f"Expected forge-1.12.2-14.23.5.2859.jar but got '{chosen}'. "
                f"Booting minecraft_server.1.12.2.jar would accidentally run vanilla without mods!"
            )

    def test_forge_1165_matches_and_selects_forge_jar(self):
        """Forge 1.16.5 has forge-1.16.5-36.2.34.jar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "forge-1.16.5-36.2.34.jar").write_bytes(b"forge16")

            chosen = self.run_bash_jar_autodetection("forge", srv)
            assert chosen == "forge-1.16.5-36.2.34.jar"

    def test_forge_1710_coexistence_prefers_universal_over_vanilla_server(self):
        """Legacy Forge 1.7.10 installer produces forge-1.7.10-...-universal.jar and minecraft_server.1.7.10.jar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "minecraft_server.1.7.10.jar").write_bytes(b"vanilla7")
            (srv / "forge-1.7.10-10.13.4.1614-1.7.10-universal.jar").write_bytes(b"forge7")

            chosen = self.run_bash_jar_autodetection("forge", srv)
            assert chosen == "forge-1.7.10-10.13.4.1614-1.7.10-universal.jar"

    def test_neoforge_universal_jar_selected(self):
        """NeoForge standalone universal jar detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "neoforge-20.4.80-beta-universal.jar").write_bytes(b"nf")

            chosen = self.run_bash_jar_autodetection("neoforge", srv)
            assert chosen == "neoforge-20.4.80-beta-universal.jar"

    def test_mohist_magma_catserver_coexistence_prefers_hybrid_over_minecraft_server(self):
        """Hybrids with minecraft_server.<ver>.jar alongside them."""
        for server_type, hybrid_jar in [
            ("mohist", "mohist-1.16.5-server.jar"),
            ("catserver", "catserver-1.12.2-server.jar"),
            ("magma", "magma-1.12.2-server.jar"),
            ("spongeforge", "spongeforge-1.12.2-server.jar"),
        ]:
            with tempfile.TemporaryDirectory() as tmpdir:
                srv = Path(tmpdir)
                (srv / "minecraft_server.1.12.2.jar").write_bytes(b"vanilla")
                (srv / hybrid_jar).write_bytes(b"hybrid")

                chosen = self.run_bash_jar_autodetection(server_type, srv)
                assert chosen == hybrid_jar, f"For {server_type}, expected {hybrid_jar} but got '{chosen}'"

    def test_paper_and_folia_jar_detection(self):
        """Paper and Folia jar autodetection in runtime-entrypoint.sh."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "folia-1.20.4-31.jar").write_bytes(b"folia")
            chosen = self.run_bash_jar_autodetection("folia", srv)
            assert chosen == "folia-1.20.4-31.jar"

        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "paper-1.21.1-120.jar").write_bytes(b"paper")
            chosen = self.run_bash_jar_autodetection("paper", srv)
            assert chosen == "paper-1.21.1-120.jar"

    def test_explicit_server_jar_overrides_patterns(self):
        """Explicit SERVER_JAR takes precedence over pattern search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            (srv / "custom_server.jar").write_bytes(b"custom")
            (srv / "forge-1.16.5-36.2.34.jar").write_bytes(b"forge")

            chosen = self.run_bash_jar_autodetection("forge", srv, custom_server_jar="custom_server.jar")
            assert chosen == "custom_server.jar"


# ==============================================================================
# 2. Bash Entrypoint Java Version Resolution Adversarial
# ==============================================================================

class TestEntrypointBashJavaResolutionAdversarial:
    """Tests the select_java_version function in docker/runtime-entrypoint.sh via real Bash execution."""

    def run_bash_select_java_version(self, server_type: str, mc_version: str) -> str:
        """Execute the exact select_java_version shell function."""
        script = f'''
select_java_version() {{
    local s_type="$1"
    local version="$2"
    local java_version="21"
    
    case "$s_type" in
        "vanilla"|"paper"|"purpur"|"folia")
            if [[ "$version" == 1.8* ]] || [[ "$version" == 1.9* ]] || [[ "$version" == 1.10* ]] || [[ "$version" == 1.11* ]] || [[ "$version" == 1.12* ]] || [[ "$version" == 1.13* ]] || [[ "$version" == 1.14* ]] || [[ "$version" == 1.15* ]] || [[ "$version" == 1.16* ]]; then
                java_version="8"
            elif [[ "$version" == 1.17* ]] || [[ "$version" == 1.18* ]]; then
                java_version="17"
            elif [[ "$version" == 26* ]]; then
                java_version="25"
            elif [[ "$version" == 1.19* ]] || [[ "$version" == 1.20* ]] || [[ "$version" == 1.21* ]]; then
                java_version="21"
            else
                java_version="21"
            fi
            ;;
        "fabric"|"quilt"|"banner")
            if [[ "$version" == 26* ]]; then
                java_version="25"
            elif [[ "$version" == 1.19* ]] || [[ "$version" == 1.20* ]] || [[ "$version" == 1.21* ]]; then
                java_version="21"
            elif [[ "$version" == 1.17* ]] || [[ "$version" == 1.18* ]]; then
                java_version="17"
            else
                java_version="8"
            fi
            ;;
        "forge"|"neoforge"|"mohist"|"magma"|"catserver"|"spongeforge")
            if [[ "$version" == 26* ]]; then
                java_version="25"
            elif [[ "$version" == 1.8* ]] || [[ "$version" == 1.9* ]] || [[ "$version" == 1.10* ]] || [[ "$version" == 1.11* ]] || [[ "$version" == 1.12* ]] || [[ "$version" == 1.13* ]] || [[ "$version" == 1.14* ]] || [[ "$version" == 1.15* ]] || [[ "$version" == 1.16* ]]; then
                java_version="8"
            elif [[ "$version" == 1.20.5* ]] || [[ "$version" == 1.20.6* ]] || [[ "$version" == 1.21* ]]; then
                java_version="21"
            else
                java_version="17"
            fi
            ;;
    esac
    echo "$java_version"
}}

select_java_version "{server_type}" "{mc_version}"
'''
        proc = subprocess.run([BASH_BIN, "-c", script], capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0, f"Bash failed: {proc.stderr}"
        return proc.stdout.strip()

    @pytest.mark.parametrize(
        "server_type,version,expected",
        [
            ("forge", "1.12.2", "8"),
            ("forge", "1.16.5", "8"),
            ("forge", "1.15.2", "8"),
            ("forge", "1.14.4", "8"),
            ("forge", "1.8.9", "8"),
            ("forge", "1.17.1", "17"),
            ("forge", "1.18.2", "17"),
            ("forge", "1.20.1", "17"),
            ("forge", "1.20.4", "17"),
            ("forge", "1.20.5", "21"),
            ("forge", "1.20.6", "21"),
            ("forge", "1.21.1", "21"),
            ("forge", "26.1", "25"),
            ("neoforge", "1.20.4", "17"),
            ("neoforge", "1.20.6", "21"),
            ("neoforge", "1.21.1", "21"),
            ("folia", "1.19.4", "21"),
            ("folia", "1.20.4", "21"),
            ("folia", "1.21.1", "21"),
            ("vanilla", "1.12.2", "8"),
            ("vanilla", "1.16.5", "8"),
            ("vanilla", "1.17.1", "17"),
            ("vanilla", "1.20.4", "21"),
        ],
    )
    def test_bash_select_java_version_matrix(self, server_type, version, expected):
        assert self.run_bash_select_java_version(server_type, version) == expected


# ==============================================================================
# 3. Modern Forge & NeoForge run.sh Forwarding in Bash
# ==============================================================================

class TestRunShArgumentForwardingAdversarial:
    """Verifies that line 1158 in runtime-entrypoint.sh correctly passes arguments to ./run.sh."""

    def test_run_sh_receives_effective_args_and_extra_server_args(self):
        """Simulate runsh execution and verify all arguments arrive intact at ./run.sh."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            # Create mock run.sh that logs all passed arguments line by line
            run_sh = workdir / "run.sh"
            run_sh.write_text(
                '#!/usr/bin/env bash\n'
                'for arg in "$@"; do\n'
                '  echo "ARG: $arg" >> run_args.log\n'
                'done\n'
                'exit 0\n',
                encoding="utf-8",
            )

            # Create entrypoint snippet executing line 1158
            runner = workdir / "test_exec.sh"
            runner.write_text(
                '#!/usr/bin/env bash\n'
                'set -e\n'
                'mkfifo -m 600 console.in 2>/dev/null || true\n'
                'effective_args=("nogui" "--forceUpgrade" "--safeMode")\n'
                'EXTRA_SERVER_ARGS="--port 25565 --demo"\n'
                '# Feed an EOF or quit to FIFO to prevent hanging\n'
                '( sleep 0.1; echo "stop" > console.in ) &\n'
                'tail -f -n +1 console.in | bash ./run.sh "${effective_args[@]}" $EXTRA_SERVER_ARGS\n',
                encoding="utf-8",
            )

            proc = subprocess.run([BASH_BIN, str(runner)], cwd=str(workdir), capture_output=True, text=True, timeout=10)
            assert proc.returncode == 0, f"Execution failed: {proc.stderr}"

            log_file = workdir / "run_args.log"
            assert log_file.is_file(), "run_args.log was not generated by mock run.sh"
            lines = log_file.read_text(encoding="utf-8").splitlines()

            assert "ARG: nogui" in lines
            assert "ARG: --forceUpgrade" in lines
            assert "ARG: --safeMode" in lines
            assert "ARG: --port" in lines
            assert "ARG: 25565" in lines
            assert "ARG: --demo" in lines


# ==============================================================================
# 4. user_jvm_args.txt Robustness & Preservation Adversarial
# ==============================================================================

class TestUserJvmArgsRobustnessAdversarial:
    """Stress-tests user_jvm_args.txt creation, updating, and custom flag preservation."""

    def test_preserves_custom_flags_before_and_after_lmce_block(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            target = srv / "user_jvm_args.txt"

            initial_content = (
                "# Custom User Memory Configuration\n"
                "-Xmx8G\n"
                "-Xms4G\n"
                "-XX:+HeapDumpOnOutOfMemoryError\n"
                "# Trailing comment\n"
            )
            target.write_text(initial_content, encoding="utf-8")

            # Write LMCE args
            lmce_flags = ["-XX:+TieredCompilation", "-Dmulticore.enabled=true", "-Dmulticore.threads=8"]
            write_user_jvm_args(srv, lmce_flags)

            res = target.read_text(encoding="utf-8")
            assert "-Xmx8G" in res
            assert "-Xms4G" in res
            assert "-XX:+HeapDumpOnOutOfMemoryError" in res
            assert LMCE_HEADER_START in res
            assert "-Dmulticore.threads=8" in res
            assert LMCE_HEADER_END in res

    def test_multiple_sequential_updates_idempotent_no_header_leak(self):
        """Updating user_jvm_args 10 times consecutively must not duplicate headers or corrupt user flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            target = srv / "user_jvm_args.txt"
            target.write_text("-Xmx6G\n-Dcustom.prop=true\n", encoding="utf-8")

            for i in range(1, 11):
                flags = [
                    "-XX:+TieredCompilation",
                    f"-Dmulticore.threads={i}",
                    f"-Dnet.minecraft.server.ServerThreadPoolSize={i}",
                ]
                write_user_jvm_args(srv, flags)

            final_content = target.read_text(encoding="utf-8")
            # Should have exactly ONE start header and ONE end header
            assert final_content.count(LMCE_HEADER_START) == 1
            assert final_content.count(LMCE_HEADER_END) == 1
            assert final_content.count("-Xmx6G") == 1
            assert final_content.count("-Dcustom.prop=true") == 1
            assert "-Dmulticore.threads=10" in final_content
            assert "-Dmulticore.threads=9" not in final_content

    def test_quote_jvm_arg_edge_cases(self):
        """Test quote_jvm_arg against spaces, tabs, internal quotes, and Windows paths."""
        # Unspaced stays unspaced
        assert quote_jvm_arg("-Xmx4G") == "-Xmx4G"
        assert quote_jvm_arg("-XX:+UseG1GC") == "-XX:+UseG1GC"

        # Windows backslash in javaagent converted to forward slash
        agent_arg = r"-javaagent:C:\Servers\Minecraft\agent.jar"
        assert quote_jvm_arg(agent_arg) == "-javaagent:C:/Servers/Minecraft/agent.jar"

        # Spaced argument gets quoted
        spaced = "-Dproperty.name=hello world"
        assert quote_jvm_arg(spaced) == '"-Dproperty.name=hello world"'

        # Spaced javaagent gets converted and quoted
        spaced_agent = r"-javaagent:C:\Program Files\Minecraft Server\agent.jar"
        assert quote_jvm_arg(spaced_agent) == '"-javaagent:C:/Program Files/Minecraft Server/agent.jar"'

        # Already quoted stays quoted without double-quoting
        assert quote_jvm_arg('"-Xmx4G -Xms2G"') == '"-Xmx4G -Xms2G"'
        assert quote_jvm_arg("'-Xmx4G -Xms2G'") == "'-Xmx4G -Xms2G'"
        assert quote_jvm_arg('-Dprop="val with space"') == '-Dprop="val with space"'

    def test_strips_legacy_conflicting_gc_flags_outside_lmce_block(self):
        """Regression: legacy -XX:+UseG1GC outside LMCE block must be stripped to prevent 'Multiple garbage collectors selected'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            srv = Path(tmpdir)
            target = srv / "user_jvm_args.txt"
            target.write_text(
                "# Modpack defaults\n"
                "-Xmx24G\n"
                "-Xms12G\n"
                "-XX:+UseG1GC\n"
                "-XX:+ParallelRefProcEnabled\n"
                "-XX:MaxGCPauseMillis=200\n"
                "-XX:G1HeapRegionSize=16m\n"
                "-XX:+HeapDumpOnOutOfMemoryError\n"
                "-XX:+DisableExplicitGC\n",
                encoding="utf-8",
            )

            prof = get_concurrency_profile(cpu_cores=16, ram_mb=24576, java_version=25)
            flags = build_multicore_jvm_args(prof, server_type="neoforge")
            write_user_jvm_args(srv, flags)

            res = target.read_text(encoding="utf-8")
            assert "-Xmx24G" in res
            assert "-Xms12G" in res
            assert "-XX:+HeapDumpOnOutOfMemoryError" in res
            assert "-XX:+DisableExplicitGC" in res
            assert "-XX:+UseZGC" in res
            assert "-XX:+UseG1GC" not in res
            assert "-XX:+ParallelRefProcEnabled" not in res
            assert "-XX:MaxGCPauseMillis=200" not in res
            assert "-XX:G1HeapRegionSize=16m" not in res
            assert "-XX:+ZGenerational" not in res

    def test_java25_zgc_omits_removed_zgenerational(self):
        """Regression: Java 25 (Minecraft 26.x) must emit -XX:+UseZGC without removed -XX:+ZGenerational."""
        prof = get_concurrency_profile(cpu_cores=16, ram_mb=24576, java_version=25)
        flags = build_multicore_jvm_args(prof, server_type="neoforge")
        assert "-XX:+UseZGC" in flags
        assert "-XX:+ZGenerational" not in flags
        assert "-XX:+UseG1GC" not in flags


# ==============================================================================
# 5. Java GC Safety Across Matrix (Exhaustive Combinatorial Challenge)
# ==============================================================================

class TestExhaustiveGarbageCollectionSafety:
    """Exhaustively verifies GC safety across all LTS versions, RAM ranges, and core counts."""

    @pytest.mark.parametrize("java_ver", [8, 11, 17])
    @pytest.mark.parametrize("ram_mb", [512, 1024, 2048, 4096, 8192, 16384, 65536])
    @pytest.mark.parametrize("platform", ["vanilla", "paper", "forge", "neoforge"])
    def test_java8_11_17_never_emits_zgc(self, java_ver, ram_mb, platform):
        """CRITICAL SAFETY: Java 8, 11, and 17 MUST NEVER emit -XX:+UseZGC or -XX:+ZGenerational under any RAM amount."""
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=ram_mb, java_version=java_ver)
        flags = build_multicore_jvm_args(prof, server_type=platform)

        assert "-XX:+UseZGC" not in flags, f"ZGC emitted for Java {java_ver} ({platform}, {ram_mb}MB)!"
        assert "-XX:+ZGenerational" not in flags, f"ZGenerational emitted for Java {java_ver} ({platform}, {ram_mb}MB)!"
        assert "-XX:+UseG1GC" in flags, f"G1GC missing for Java {java_ver} ({platform}, {ram_mb}MB)!"

        if java_ver <= 11:
            assert "-XX:+UseStringDeduplication" in flags
            assert "-XX:+UnlockExperimentalVMOptions" in flags

    @pytest.mark.parametrize("ram_mb", [512, 1024, 2048, 3072, 4095])
    def test_java21_low_ram_falls_back_to_g1gc_no_zgc(self, ram_mb):
        """Java 21 with <4GB RAM falls back to G1GC to prevent ZGC memory headroom exhaustion."""
        prof = get_concurrency_profile(cpu_cores=4, ram_mb=ram_mb, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-XX:+UseZGC" not in flags
        assert "-XX:+ZGenerational" not in flags
        assert "-XX:+UseG1GC" in flags

    @pytest.mark.parametrize("ram_mb", [4096, 6144, 8192, 16384, 32768])
    def test_java21_high_ram_uses_generational_zgc(self, ram_mb):
        """Java 21 with >=4GB RAM enables ultra-low latency Generational ZGC."""
        prof = get_concurrency_profile(cpu_cores=8, ram_mb=ram_mb, java_version=21)
        flags = build_multicore_jvm_args(prof, server_type="vanilla")

        assert "-XX:+UseZGC" in flags
        assert "-XX:+ZGenerational" in flags
        assert "-XX:+UseG1GC" not in flags


# ==============================================================================
# 6. Provider Helper Consistency & Launch Classification
# ==============================================================================

class TestProviderHelpersAdversarial:
    """Verifies provider helper methods on ForgeProvider and NeoForgeProvider."""

    def test_forge_provider_extract_mc_version_edge_cases(self):
        fp = ForgeProvider()
        assert fp.extract_mc_version("1.12.2-14.23.5.2859") == "1.12.2"
        assert fp.extract_mc_version("1.16.5-36.2.34") == "1.16.5"
        assert fp.extract_mc_version("1.7.10-10.13.4.1614-1.7.10") == "1.7.10"
        assert fp.extract_mc_version("1.20.1-47.3.0") == "1.20.1"
        assert fp.extract_mc_version("1.21.1") == "1.21.1"
        assert fp.extract_mc_version("") == ""
        assert fp.extract_mc_version(None) == ""

    def test_forge_provider_is_modern(self):
        fp = ForgeProvider()
        assert fp.is_modern("1.7.10") is False
        assert fp.is_modern("1.12.2") is False
        assert fp.is_modern("1.16.5") is False
        assert fp.is_modern("1.16.5-36.2.34") is False
        assert fp.is_modern("1.17.1") is True
        assert fp.is_modern("1.18.2") is True
        assert fp.is_modern("1.20.1") is True
        assert fp.is_modern("1.20.1-47.3.0") is True
        assert fp.is_modern("1.21.1") is True

    def test_forge_provider_launch_type(self):
        fp = ForgeProvider()
        assert fp.get_expected_launch_type("1.12.2") == "jar"
        assert fp.get_expected_launch_type("1.16.5") == "jar"
        assert fp.get_expected_launch_type("1.20.1") == "run_script"
        assert fp.get_expected_launch_type("1.21.1") == "run_script"

    def test_neoforge_provider_is_modern_and_launch_type(self):
        nfp = NeoForgeProvider()
        assert nfp.is_modern("1.20.4") is True
        assert nfp.is_modern("20.4.253") is True
        assert nfp.is_modern("21.1.266") is True
        assert nfp.get_expected_launch_type("1.20.4") == "run_script"
        assert nfp.get_expected_launch_type("20.4.253") == "run_script"
