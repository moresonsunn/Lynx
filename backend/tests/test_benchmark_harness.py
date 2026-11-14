"""
Tests for Multi-Core Benchmark Harness (backend/benchmarks).

Validates:
1. SyntheticClientPool lifecycle and load test execution.
2. MetricsCollector telemetry sampling and summary calculations.
3. AssertionEngine criteria verification against thresholds.
4. run_benchmark full execution cycle.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
_BENCHMARK_DIR = _BACKEND_DIR / "benchmarks"
for p in [str(_REPO_ROOT), str(_BACKEND_DIR), str(_BENCHMARK_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.benchmarks.load_gen import SyntheticClientPool, LoadTestResult
from backend.benchmarks.metrics_collector import MetricsCollector, BenchmarkMetricsSummary, TelemetrySnapshot
from backend.benchmarks.assertion_engine import AssertionEngine, BenchmarkVerificationReport
from backend.benchmarks.run_multicore_benchmark import run_benchmark, GenuineMultiCoreServerProcess


class TestBenchmarkHarness:

    def test_synthetic_client_pool_lifecycle(self):
        pool = SyntheticClientPool(host="127.0.0.1", port=25565, bot_count=3, spread_radius=100)
        result = pool.run_load_test(duration_sec=1)
        assert isinstance(result, LoadTestResult)
        assert result.bot_count == 3
        assert result.duration_sec >= 0.8
        assert result.total_actions > 0
        assert result.actions_per_sec > 0
        assert result.success_rate == 100.0

    def test_metrics_collector_summary(self):
        collector = MetricsCollector(sample_interval=0.1)
        collector.start()
        time.sleep(0.3)
        collector.stop()
        summary = collector.get_summary()

        assert isinstance(summary, BenchmarkMetricsSummary)
        assert summary.samples_count >= 1
        assert summary.active_cores_count >= 1
        assert len(summary.per_core_avg_cpu) > 0
        assert summary.peak_active_threads > 0

    def test_assertion_engine_evaluates_pass_and_fail(self):
        engine = AssertionEngine(
            min_aggregate_cpu=100.0,
            min_active_cores=2,
            min_worker_threads=2,
            min_tps=19.8,
            max_mspt=50.0,
        )

        # Passing summary
        pass_summary = BenchmarkMetricsSummary(
            duration_sec=5.0,
            samples_count=10,
            peak_aggregate_cpu=185.0,
            avg_aggregate_cpu=150.0,
            active_cores_count=8,
            per_core_avg_cpu=[25.0] * 8,
            peak_active_threads=16,
            avg_active_threads=14.0,
            min_tps=20.0,
            avg_tps=20.0,
            max_mspt=18.0,
            avg_mspt=12.0,
            thread_distribution=[],
        )
        report = engine.evaluate(pass_summary, crash_count=0, orphan_processes_count=0, port_leaks_count=0)
        assert report.overall_passed is True
        assert all(c.passed for c in report.criteria)

        # Failing summary (low CPU, low TPS)
        fail_summary = BenchmarkMetricsSummary(
            duration_sec=5.0,
            samples_count=10,
            peak_aggregate_cpu=45.0,
            avg_aggregate_cpu=30.0,
            active_cores_count=1,
            per_core_avg_cpu=[30.0],
            peak_active_threads=1,
            avg_active_threads=1.0,
            min_tps=12.0,
            avg_tps=14.0,
            max_mspt=80.0,
            avg_mspt=70.0,
            thread_distribution=[],
        )
        fail_report = engine.evaluate(fail_summary, crash_count=1, orphan_processes_count=1, port_leaks_count=1)
        assert fail_report.overall_passed is False
        assert not all(c.passed for c in fail_report.criteria)

    def test_run_benchmark_integration(self, tmp_path):
        out_json = tmp_path / "bench_test_results.json"
        report = run_benchmark(
            duration_sec=3,
            bot_count=4,
            worker_threads=2,
            output_file=str(out_json),
            verbose=False,
        )
        assert isinstance(report, BenchmarkVerificationReport)
        assert report.overall_passed is True
        assert out_json.is_file()
