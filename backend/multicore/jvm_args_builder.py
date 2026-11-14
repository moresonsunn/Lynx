"""Lynx Multi-Core Engine (LMCE) - JVM Arguments Builder & Forge/NeoForge Bridge.

Generates core-scaled JVM flags, Generational ZGC and G1GC configurations,
system properties for thread pools, and formats/writes user_jvm_args.txt
for modern Forge and NeoForge run.sh pipelines.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Union

if TYPE_CHECKING:
    from .concurrency_profile import ConcurrencyProfile

logger = logging.getLogger(__name__)

LMCE_HEADER_START = "# --- Lynx Multi-Core Engine (LMCE) Configuration ---"
LMCE_HEADER_END = "# --- End Lynx Multi-Core Engine Configuration ---"


def build_multicore_jvm_args(
    profile: "ConcurrencyProfile",
    server_type: str = "vanilla",
    include_agent: bool = True,
) -> List[str]:
    """Generate ordered list of JVM argument strings tailored to the concurrency profile and server type."""
    flags: List[str] = []

    # 1. Thread Pool & Concurrency System Properties
    flags.append(
        f"-Djava.util.concurrent.ForkJoinPool.common.parallelism={profile.fork_join_parallelism}"
    )
    flags.append(f"-Dio.netty.eventLoopThreads={profile.netty_threads}")

    # 2. Tiered Compilation & JIT Compiler Threads
    flags.append("-XX:+TieredCompilation")
    flags.append(f"-XX:CICompilerCount={profile.ci_compiler_count}")

    # 3. Garbage Collection Flags Matrix
    jv = profile.java_version
    ram = profile.ram_mb or 2048

    if jv >= 21 and ram >= 4096:
        # Generational ZGC: Ultra-low latency concurrent collection for Java 21+ with >=4GB RAM
        flags.append("-XX:+UseZGC")
        if jv < 24:
            # -XX:+ZGenerational was removed in Java 24+ where ZGC is unconditionally generational
            flags.append("-XX:+ZGenerational")
        flags.append(f"-XX:ConcGCThreads={profile.conc_gc_threads}")
        flags.append(f"-XX:ParallelGCThreads={profile.gc_threads}")
    elif jv >= 17:
        # Modern G1GC for Java 17 or Java 21+ with low RAM (<4GB)
        flags.append("-XX:+UseG1GC")
        flags.append(f"-XX:ParallelGCThreads={profile.gc_threads}")
        flags.append(f"-XX:ConcGCThreads={profile.conc_gc_threads}")
        region_size = "16m" if ram >= 2048 else "8m"
        flags.append(f"-XX:G1HeapRegionSize={region_size}")
        flags.append("-XX:G1ReservePercent=15")
        flags.append("-XX:InitiatingHeapOccupancyPercent=45")
    else:
        # Legacy G1GC for Java 8 / 11 (Minecraft 1.8 - 1.16.5)
        # CRITICAL: Must NEVER emit -XX:+UseZGC or -XX:+ZGenerational
        flags.append("-XX:+UseG1GC")
        flags.append(f"-XX:ParallelGCThreads={profile.gc_threads}")
        flags.append(f"-XX:ConcGCThreads={profile.conc_gc_threads}")
        flags.append("-XX:G1ReservePercent=15")
        flags.append("-XX:InitiatingHeapOccupancyPercent=45")
        flags.append("-XX:+UseStringDeduplication")
        flags.append("-XX:+UnlockExperimentalVMOptions")

    # 4. Engine Telemetry & Control Properties
    flags.append("-Dmulticore.enabled=true")
    flags.append(f"-Dmulticore.threads={profile.worker_threads}")
    flags.append(f"-Dmulticore.mode={profile.mode}")
    flags.append(f"-Dnet.minecraft.server.ServerThreadPoolSize={profile.worker_threads}")

    # 5. Universal Agent Attachment
    if include_agent and profile.agent_path:
        agent_path_str = str(profile.agent_path).replace("\\", "/")
        flags.append(f"-javaagent:{agent_path_str}")

    # 6. Platform-Specific JVM Optimizations
    st = server_type.strip().lower() if server_type else ""
    if st in ("forge", "neoforge"):
        flags.append("-Dterminal.jline=false")
        flags.append("-Dterminal.ansi=true")
    elif st in ("paper", "purpur", "folia"):
        flags.append("-Dpaper.playerconnection.keepalive=60")
        flags.append(f"-Dpaper.player-connection-limit={profile.worker_threads}")

    return flags


def quote_jvm_arg(arg: str) -> str:
    """Ensure a JVM argument containing whitespace is properly quoted for @argfile and environment variables.

    - Normalizes backslashes in -javaagent paths to forward slashes to prevent escape corruption in HotSpot @argfile.
    - Leaves unspaced arguments untouched.
    - Idempotent: avoids double-quoting arguments that are already quoted (outer or internal quotes).
    """
    cleaned = arg.strip()
    if not cleaned:
        return ""

    # Normalize backslashes in -javaagent paths for @argfile escape-sequence safety
    if cleaned.startswith("-javaagent:") or cleaned.startswith('"-javaagent:') or cleaned.startswith("'-javaagent:"):
        cleaned = cleaned.replace("\\", "/")

    # Check for whitespace (spaces or tabs)
    if " " in cleaned or "\t" in cleaned:
        # If already enclosed in matching double or single quotes, keep as is
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (
            cleaned.startswith("'") and cleaned.endswith("'")
        ):
            return cleaned
        # If already internally quoted (e.g. -Dprop="a b" or -javaagent:"path/agent.jar")
        if '"' in cleaned or "'" in cleaned:
            return cleaned
        # Quote entire argument
        return f'"{cleaned}"'

    return cleaned


_CONFLICTING_GC_TOKEN_RE = re.compile(
    r"^(?:"
    r"-XX:[+-]Use[A-Za-z0-9]+GC"
    r"|-XX:[+-]ZGenerational"
    r"|-XX:G1.*"
    r"|-XX:InitiatingHeapOccupancyPercent(?:=.*)?"
    r"|-XX:MaxGCPauseMillis(?:=.*)?"
    r"|-XX:SurvivorRatio(?:=.*)?"
    r"|-XX:[+-]ParallelRefProcEnabled"
    r"|-XX:ConcGCThreads=.*"
    r"|-XX:ParallelGCThreads=.*"
    r"|-XX:CICompilerCount=.*"
    r"|-XX:[+-]TieredCompilation"
    r"|-XX:[+-]UseStringDeduplication"
    r"|-XX:[+-]UnlockExperimentalVMOptions"
    r")$"
)


def _strip_conflicting_gc_tokens_from_line(line: str) -> str:
    """Strip GC selector and LMCE-managed tuning tokens from a preserved user_jvm_args line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line
    tokens = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', stripped)
    kept = [t for t in tokens if not _CONFLICTING_GC_TOKEN_RE.match(t.strip("\"'"))]
    if len(kept) == len(tokens):
        return line
    return " ".join(kept)


def format_user_jvm_args(jvm_args: List[str]) -> str:
    """Format JVM arguments according to official user_jvm_args.txt specification."""
    lines: List[str] = [
        "# Generated by Minecraft-Controller Lynx Multi-Core Engine (LMCE)",
        "# DO NOT REMOVE: Enables parallel CPU execution across multiple cores",
        LMCE_HEADER_START,
    ]
    for arg in jvm_args:
        quoted = quote_jvm_arg(arg)
        if quoted:
            lines.append(quoted)
    lines.append(LMCE_HEADER_END)
    lines.append("")  # Trailing newline
    return "\n".join(lines)


def write_user_jvm_args(server_dir: Union[Path, str], jvm_args: List[str]) -> Path:
    """Write multi-core JVM flags to user_jvm_args.txt in server root.

    Preserves custom user flags (e.g. -Xmx, -Xms) while atomically updating LMCE flags.
    Raises NotADirectoryError if server_dir is a file.
    Raises PermissionError if server_dir is read-only.
    """
    path = Path(server_dir)
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")

    path.mkdir(parents=True, exist_ok=True)
    target_file = path / "user_jvm_args.txt"

    preserved_lines: List[str] = []
    if target_file.is_file():
        try:
            content = target_file.read_text(encoding="utf-8")
            in_lmce_block = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped == LMCE_HEADER_START:
                    in_lmce_block = True
                    continue
                elif stripped == LMCE_HEADER_END:
                    in_lmce_block = False
                    continue

                if not in_lmce_block:
                    # Ignore old generated header lines to avoid duplicates
                    if stripped.startswith("# Generated by Minecraft-Controller") or stripped.startswith(
                        "# DO NOT REMOVE: Enables parallel"
                    ):
                        continue
                    cleaned_line = _strip_conflicting_gc_tokens_from_line(line)
                    if cleaned_line == "" and stripped:
                        continue
                    preserved_lines.append(cleaned_line)
        except Exception as e:
            logger.debug("Failed reading existing user_jvm_args.txt: %s", e)

    # Build full content
    new_content_parts: List[str] = []
    if preserved_lines:
        preserved_text = "\n".join(preserved_lines).strip()
        if preserved_text:
            new_content_parts.append(preserved_text)
            new_content_parts.append("")

    new_content_parts.append(format_user_jvm_args(jvm_args))
    final_content = "\n".join(new_content_parts).strip() + "\n"

    # Atomic write via temporary file
    temp_file = path / f"user_jvm_args.txt.{uuid.uuid4().hex}.tmp"
    try:
        temp_file.write_text(final_content, encoding="utf-8")
        temp_file.replace(target_file)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass

    return target_file


def build_env_vars(profile: "ConcurrencyProfile") -> Dict[str, str]:
    """Build environment variables dictionary for server process execution."""
    agent_path = str(profile.agent_path) if profile.agent_path else ""

    all_args_str = " ".join(quote_jvm_arg(f) for f in profile.jvm_flags if f.strip())

    # Filter tool options: HotSpot JVM parses JAVA_TOOL_OPTIONS automatically
    tool_options_list = [
        f for f in profile.jvm_flags
        if not f.startswith("-Dpaper.") and not f.startswith("-Dterminal.")
    ]
    java_tool_options_str = " ".join(quote_jvm_arg(f) for f in tool_options_list if f.strip())

    return {
        "MULTICORE_ENABLED": "1",
        "MULTICORE_THREADS": str(profile.worker_threads),
        "MULTICORE_MODE": str(profile.mode),
        "MULTICORE_ALLOCATED_CORES": str(profile.allocated_cores),
        "FORK_JOIN_PARALLELISM": str(profile.fork_join_parallelism),
        "NETTY_THREADS": str(profile.netty_threads),
        "GC_THREADS": str(profile.gc_threads),
        "ALL_JAVA_ARGS": all_args_str,
        "JAVA_TOOL_OPTIONS": java_tool_options_str,
        "MC_MULTICORE_AGENT_PATH": agent_path,
    }


def prepare_server_multicore_env(
    server_dir: Union[Path, str],
    profile: "ConcurrencyProfile",
    server_type: str = "vanilla",
) -> Dict[str, str]:
    """Prepare server directory, ensure agent binary, write user_jvm_args.txt if Forge/NeoForge, and return env vars."""
    from .agent_manager import ensure_agent_binary

    target_dir = Path(server_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ensure Agent Binary is present in server directory
    agent_binary_path = ensure_agent_binary(target_dir)
    profile.agent_path = str(agent_binary_path)

    # 2. Synthesize complete JVM arguments
    profile.jvm_flags = build_multicore_jvm_args(profile, server_type=server_type)

    # 3. If Forge/NeoForge or run.sh/user_jvm_args.txt already present, write & sanitize user_jvm_args.txt
    st = server_type.strip().lower() if server_type else ""
    if st in ("forge", "neoforge") or (target_dir / "run.sh").is_file() or (target_dir / "user_jvm_args.txt").is_file():
        try:
            write_user_jvm_args(target_dir, profile.jvm_flags)
        except (PermissionError, OSError) as e:
            logger.warning(
                "Cannot write user_jvm_args.txt to %s: %s. Falling back to environment variables.",
                target_dir,
                e,
            )

    # 4. Return environment variables dictionary
    return build_env_vars(profile)
