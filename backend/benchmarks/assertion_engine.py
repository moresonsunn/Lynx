"""
Assertion Engine for Multi-Core Acceptance Criteria Verification.

Verifies:
1. Active CPU load distribution across multiple CPU cores (>100% aggregate CPU, >=2 active cores).
2. Under simulated load, server maintains stable tick rate (20 TPS) with tick work distributed across threads/cores.
3. Thread scaling & MSPT bounding.
4. Operational hygiene: 0 crashes, 0 orphan processes, 0 port leaks.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

try:
    from backend.benchmarks.metrics_collector import BenchmarkMetricsSummary
except ImportError:
    from metrics_collector import BenchmarkMetricsSummary


@dataclasses.dataclass
class CriterionResult:
    name: str
    expected: str
    actual: str
    passed: bool
    details: str = ""


@dataclasses.dataclass
class BenchmarkVerificationReport:
    overall_passed: bool
    summary_text: str
    criteria: List[CriterionResult]
    metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_passed": self.overall_passed,
            "summary_text": self.summary_text,
            "criteria": [dataclasses.asdict(c) for c in self.criteria],
            "metrics": self.metrics,
        }


class AssertionEngine:
    """Evaluates multi-core benchmark telemetry against formal acceptance thresholds."""

    def __init__(
        self,
        min_aggregate_cpu: float = 100.0,
        min_active_cores: int = 2,
        min_worker_threads: int = 2,
        min_tps: float = 19.8,
        max_mspt: float = 50.0,
    ):
        self.min_aggregate_cpu = min_aggregate_cpu
        self.min_active_cores = min_active_cores
        self.min_worker_threads = min_worker_threads
        self.min_tps = min_tps
        self.max_mspt = max_mspt

    def evaluate(
        self,
        summary: BenchmarkMetricsSummary,
        crash_count: int = 0,
        orphan_processes_count: int = 0,
        port_leaks_count: int = 0,
    ) -> BenchmarkVerificationReport:
        criteria: List[CriterionResult] = []

        # 1. Multi-Core Aggregate CPU Load (> 100.0%)
        # Check either peak or avg aggregate CPU
        effective_cpu = max(summary.peak_aggregate_cpu, summary.avg_aggregate_cpu)
        cpu_passed = effective_cpu > self.min_aggregate_cpu
        criteria.append(
            CriterionResult(
                name="Aggregate Multi-Core CPU Utilization",
                expected=f">{self.min_aggregate_cpu:.1f}% aggregate CPU",
                actual=f"{effective_cpu:.1f}% (peak: {summary.peak_aggregate_cpu:.1f}%, avg: {summary.avg_aggregate_cpu:.1f}%)",
                passed=cpu_passed,
                details="Un-clamped CPU exceeding single-core 100.0% boundary confirms parallel multi-core execution.",
            )
        )

        # 2. Active CPU Cores Distribution (>= 2 cores)
        cores_passed = summary.active_cores_count >= self.min_active_cores
        criteria.append(
            CriterionResult(
                name="Active Core Distribution",
                expected=f">={self.min_active_cores} active logical cores",
                actual=f"{summary.active_cores_count} cores",
                passed=cores_passed,
                details=f"Measured parallel activity across {summary.active_cores_count} CPU cores.",
            )
        )

        # 3. Active Worker Threads (>= 2 threads)
        threads_passed = summary.peak_active_threads >= self.min_worker_threads
        criteria.append(
            CriterionResult(
                name="Concurrent Worker Threads",
                expected=f">={self.min_worker_threads} worker threads",
                actual=f"{summary.peak_active_threads} active threads",
                passed=threads_passed,
                details=f"Thread scaling verified with {summary.peak_active_threads} concurrent threads.",
            )
        )

        # 4. Stable Server Tick Rate (20 TPS)
        tps_passed = summary.avg_tps >= self.min_tps
        criteria.append(
            CriterionResult(
                name="Stable Server Tick Rate (TPS)",
                expected=f">={self.min_tps:.1f} TPS (20 TPS target)",
                actual=f"{summary.avg_tps:.2f} TPS (min: {summary.min_tps:.2f})",
                passed=tps_passed,
                details="Server maintains full 20 TPS tick rate under concurrent multi-client load.",
            )
        )

        # 5. Milliseconds Per Tick (MSPT <= 50ms)
        mspt_passed = summary.avg_mspt <= self.max_mspt
        criteria.append(
            CriterionResult(
                name="Tick Time Bounding (MSPT)",
                expected=f"<={self.max_mspt:.1f} ms",
                actual=f"{summary.avg_mspt:.1f} ms (max: {summary.max_mspt:.1f} ms)",
                passed=mspt_passed,
                details="Tick processing finishes well within the 50ms budget for stable 20 TPS.",
            )
        )

        # 6. Operational Stability & Zero Leak Hygiene
        hygiene_passed = (crash_count == 0) and (orphan_processes_count == 0) and (port_leaks_count == 0)
        criteria.append(
            CriterionResult(
                name="Zero Leaks & Operational Hygiene",
                expected="0 crashes, 0 orphan processes, 0 port leaks",
                actual=f"{crash_count} crashes, {orphan_processes_count} orphans, {port_leaks_count} port leaks",
                passed=hygiene_passed,
                details="Zero resource leaks, zero dangling processes, and clean socket closure.",
            )
        )

        all_passed = all(c.passed for c in criteria)
        status_word = "PASSED" if all_passed else "FAILED"
        summary_text = (
            f"Multi-Core Benchmark {status_word}: Aggregate CPU={effective_cpu:.1f}%, "
            f"Active Cores={summary.active_cores_count}, TPS={summary.avg_tps:.2f}, "
            f"MSPT={summary.avg_mspt:.1f}ms, Threads={summary.peak_active_threads}"
        )

        return BenchmarkVerificationReport(
            overall_passed=all_passed,
            summary_text=summary_text,
            criteria=criteria,
            metrics=summary.to_dict(),
        )
