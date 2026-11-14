"""Lynx Multi-Core Engine (LMCE) - Concurrency Profile & Hardware Topology Detection.

Calculates host and container CPU topology, worker thread sizing, and memory profile
to power multi-core execution across Vanilla, Paper, Forge, and NeoForge Minecraft servers.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import psutil

logger = logging.getLogger(__name__)

# Valid concurrency modes supported by LMCE
VALID_CONCURRENCY_MODES = {
    "auto",
    "parallel_dimensions",
    "parallel_entities",
    "high_throughput",
    "single_core",
}

# Valid GC types
VALID_GC_TYPES = {"auto", "zgc", "g1gc", "parallel"}


def _safe_coerce_int(
    val: Any,
    default: Optional[int] = None,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None,
) -> Optional[int]:
    """Safely coerce any numeric or string input to an integer with bounds checking.

    Handles:
    - int, float, and strings representing integers or floats ('4', '4.0', ' 4096 ')
    - None, empty strings, whitespace, non-numeric strings ('abc') -> returns default
    - Boolean values (True/False) -> returns default (not treated as 1/0)
    - Non-finite floats (NaN, Inf, -Inf) -> returns default
    - Min and max bounds clamping/filtering
    """
    if val is None or isinstance(val, bool):
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        num = int(f)
        if min_val is not None and num < min_val:
            return default
        if max_val is not None and num > max_val:
            return default
        return num
    except (ValueError, TypeError, OverflowError):
        return default


@dataclass
class ConcurrencyProfile:
    """Calculated CPU topology, worker thread sizing, and JVM parameters."""

    allocated_cores: int
    worker_threads: int
    fork_join_parallelism: int
    gc_threads: int
    conc_gc_threads: int
    ci_compiler_count: int
    netty_threads: int
    effective_cores: Optional[int] = None
    jvm_flags: List[str] = field(default_factory=list)
    agent_path: str = ""
    mode: str = "auto"
    ram_mb: int = 2048
    java_version: int = 21
    use_zgc: bool = False

    def __post_init__(self) -> None:
        if self.effective_cores is None:
            self.effective_cores = max(2, self.allocated_cores)

    def as_dict(self) -> Dict[str, Any]:
        """Serialize profile to JSON-compatible dictionary."""
        return {
            "allocated_cores": self.allocated_cores,
            "effective_cores": self.effective_cores,
            "worker_threads": self.worker_threads,
            "fork_join_parallelism": self.fork_join_parallelism,
            "gc_threads": self.gc_threads,
            "conc_gc_threads": self.conc_gc_threads,
            "ci_compiler_count": self.ci_compiler_count,
            "netty_threads": self.netty_threads,
            "jvm_flags": list(self.jvm_flags),
            "agent_path": self.agent_path,
            "mode": self.mode,
            "ram_mb": self.ram_mb,
            "java_version": self.java_version,
            "use_zgc": self.use_zgc,
        }


@dataclass
class MultiCoreConfig:
    """Configuration schema for server multi-core settings."""

    enabled: bool = True
    mode: str = "auto"
    cpu_cores: Optional[int] = None
    worker_threads: Optional[int] = None
    agent_enabled: bool = True
    gc_type: str = "auto"
    custom_jvm_flags: List[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate configuration parameters against allowed options."""
        if self.mode not in VALID_CONCURRENCY_MODES:
            raise ValueError(
                f"Invalid mode '{self.mode}'. Must be one of {sorted(VALID_CONCURRENCY_MODES)}"
            )
        if self.gc_type not in VALID_GC_TYPES:
            raise ValueError(
                f"Invalid gc_type '{self.gc_type}'. Must be one of {sorted(VALID_GC_TYPES)}"
            )
        if self.cpu_cores is not None and self.cpu_cores < 1:
            raise ValueError("cpu_cores must be >= 1 or None")
        if self.worker_threads is not None and self.worker_threads < 1:
            raise ValueError("worker_threads must be >= 1 or None")


@dataclass
class JvmProfile:
    """Encapsulates JVM version capability detection and GC support rules."""

    java_version: int
    is_generational_zgc_supported: bool
    is_zgc_supported: bool
    is_g1gc_supported: bool
    default_gc: str
    tier_compilation: bool = True
    flags: List[str] = field(default_factory=list)

    @classmethod
    def for_version(cls, java_version: Any, ram_mb: Any = 2048) -> "JvmProfile":
        """Factory creating JvmProfile based on Java specification rules."""
        jv = _safe_coerce_int(java_version, default=21, min_val=1)
        ram = _safe_coerce_int(ram_mb, default=2048, min_val=1)
        is_gen_zgc = jv >= 21
        is_zgc = jv >= 17
        is_g1 = jv >= 8

        if jv >= 21 and ram >= 4096:
            default_gc = "ZGC"
        else:
            default_gc = "G1GC"

        return cls(
            java_version=jv,
            is_generational_zgc_supported=is_gen_zgc,
            is_zgc_supported=is_zgc,
            is_g1gc_supported=is_g1,
            default_gc=default_gc,
            tier_compilation=True,
        )


def detect_hardware_cores() -> int:
    """Detect raw host logical CPU cores using psutil with os.cpu_count fallback."""
    try:
        cnt = psutil.cpu_count(logical=True)
        if cnt and cnt > 0:
            return int(cnt)
    except Exception as e:
        logger.debug("psutil.cpu_count failed: %s", e)

    try:
        cnt = os.cpu_count()
        if cnt and cnt > 0:
            return int(cnt)
    except Exception as e:
        logger.debug("os.cpu_count failed: %s", e)

    return 1


def detect_cgroup_quota() -> Optional[float]:
    """Detect CPU quota limits from Linux cgroups (v2 cpu.max or v1 cpu.cfs_quota_us)."""
    # 1. cgroup v2: /sys/fs/cgroup/cpu.max
    # Format: "max 100000" or "200000 100000" (quota period)
    cgroup_v2 = Path("/sys/fs/cgroup/cpu.max")
    if cgroup_v2.is_file():
        try:
            content = cgroup_v2.read_text(encoding="utf-8").strip()
            parts = content.split()
            if len(parts) >= 2 and parts[0] != "max":
                quota, period = float(parts[0]), float(parts[1])
                if quota > 0 and period > 0:
                    return quota / period
        except Exception as e:
            logger.debug("cgroup v2 cpu.max read error: %s", e)

    # 2. cgroup v1: /sys/fs/cgroup/cpu/cpu.cfs_quota_us and cpu.cfs_period_us
    v1_bases = [
        Path("/sys/fs/cgroup/cpu"),
        Path("/sys/fs/cgroup/cpu,cpuacct"),
    ]
    for base in v1_bases:
        quota_file = base / "cpu.cfs_quota_us"
        period_file = base / "cpu.cfs_period_us"
        if quota_file.is_file() and period_file.is_file():
            try:
                quota = float(quota_file.read_text(encoding="utf-8").strip())
                period = float(period_file.read_text(encoding="utf-8").strip())
                if quota > 0 and period > 0:
                    return quota / period
            except Exception as e:
                logger.debug("cgroup v1 quota read error: %s", e)

    return None


def detect_cpuset_cores() -> Optional[int]:
    """Detect core count constrained by cpuset files."""
    cpuset_paths = [
        Path("/sys/fs/cgroup/cpuset.cpus.effective"),
        Path("/sys/fs/cgroup/cpuset.cpus"),
        Path("/sys/fs/cgroup/cpuset/cpuset.cpus"),
    ]
    for p in cpuset_paths:
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    count = 0
                    for token in text.split(","):
                        token = token.strip()
                        if "-" in token:
                            parts = token.split("-", 1)
                            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                count += int(parts[1]) - int(parts[0]) + 1
                        elif token.isdigit():
                            count += 1
                    if count > 0:
                        return count
            except Exception as e:
                logger.debug("cpuset read error: %s", e)
    return None


def detect_affinity_cores() -> Optional[int]:
    """Detect core count constrained by process affinity (sched_getaffinity)."""
    sched_getaffinity = getattr(os, "sched_getaffinity", None)
    if callable(sched_getaffinity):
        try:
            aff = sched_getaffinity(0)
            if aff:
                return len(aff)
        except Exception as e:
            logger.debug("sched_getaffinity error: %s", e)
    return None


def detect_available_cores() -> int:
    """Detect available logical cores considering host, cgroups, cpuset, and affinity."""
    host_cores = detect_hardware_cores()
    limits = [host_cores]

    cgroup_quota = detect_cgroup_quota()
    if cgroup_quota is not None and cgroup_quota > 0:
        limits.append(math.ceil(cgroup_quota))

    cpuset_cnt = detect_cpuset_cores()
    if cpuset_cnt is not None and cpuset_cnt > 0:
        limits.append(cpuset_cnt)

    aff_cnt = detect_affinity_cores()
    if aff_cnt is not None and aff_cnt > 0:
        limits.append(aff_cnt)

    return max(1, min(limits))


def get_concurrency_profile(
    cpu_cores: Optional[Union[int, str, float]] = None,
    ram_mb: Optional[Union[int, str, float]] = None,
    java_version: Union[int, str, float] = 21,
    mode: str = "auto",
    agent_path: str = "",
    enforce_multicore: bool = True,
    cores: Optional[Union[int, str, float]] = None,
) -> ConcurrencyProfile:
    """Calculates dynamic CPU core topology, worker thread sizing, and JVM flags.

    Enforces cores = max(2, allocated) when allocating multi-core profiles.
    Single-core fallback is preserved if mode='single_core' or enforce_multicore=False.
    Supports both `cpu_cores` and `cores` parameters for API compatibility.
    """
    if cores is not None and cpu_cores is None:
        cpu_cores = cores
    # 1. Core Resolution
    raw_cores = _safe_coerce_int(cpu_cores, min_val=1)
    if raw_cores is None:
        raw_cores = _safe_coerce_int(os.environ.get("CPU_CORES"), min_val=1)
    if raw_cores is None:
        raw_cores = detect_available_cores()

    # Clamp raw allocated cores between 1 and safety limit (1024)
    raw_allocated = min(max(1, raw_cores), 1024)

    # 2. RAM Resolution
    ram = _safe_coerce_int(ram_mb, default=2048, min_val=1)

    # 3. Java Version Resolution
    jv = _safe_coerce_int(java_version, default=21, min_val=1)

    # 4. Mode Resolution
    cleaned_mode = mode.strip().lower() if mode else "auto"
    if cleaned_mode not in VALID_CONCURRENCY_MODES:
        cleaned_mode = "auto"

    # 5. Worker Thread & Core Allocation
    is_single_core = (cleaned_mode == "single_core") or (not enforce_multicore and raw_allocated == 1)

    if is_single_core:
        # Graceful single-core fallback: no thread explosion
        allocated = 1
        effective = 1
        worker_threads = 1
        fork_join = 1
        gc_threads = 1
        conc_gc_threads = 1
        ci_compiler_count = 2  # HotSpot JVM requires minimum 2 for TieredCompilation
        netty_threads = 1
    else:
        # Multi-core profile: Enforce cores = max(2, allocated)
        effective = max(2, raw_allocated)
        allocated = effective

        if cleaned_mode == "high_throughput":
            worker_threads = effective + 2
        else:
            worker_threads = max(2, effective)

        fork_join = effective
        gc_threads = effective
        conc_gc_threads = max(1, effective // 2)
        ci_compiler_count = max(2, effective // 2)
        netty_threads = max(2, min(effective, 16))

    # 6. GC Selection
    use_zgc = (jv >= 21) and (ram >= 4096)

    profile = ConcurrencyProfile(
        allocated_cores=allocated,
        effective_cores=effective,
        worker_threads=worker_threads,
        fork_join_parallelism=fork_join,
        gc_threads=gc_threads,
        conc_gc_threads=conc_gc_threads,
        ci_compiler_count=ci_compiler_count,
        netty_threads=netty_threads,
        agent_path=agent_path,
        mode=cleaned_mode,
        ram_mb=ram,
        java_version=jv,
        use_zgc=use_zgc,
    )

    # 7. Synthesize JVM flags if jvm_args_builder is available
    try:
        from .jvm_args_builder import build_multicore_jvm_args

        profile.jvm_flags = build_multicore_jvm_args(profile)
    except ImportError:
        pass

    return profile
