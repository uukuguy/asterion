"""Generic benchmark planning and execution contracts."""

from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkModelError,
    BenchmarkTaskImplementation,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    ResolvedCapability,
    public_plan_dict,
)
from asterion.benchmarks.resolution import (
    BenchmarkResolutionError,
    resolve_benchmark_suite,
    resolve_benchmark_tasks,
)


__all__ = (
    "ApplicationRef",
    "BenchmarkModelError",
    "BenchmarkTaskImplementation",
    "BenchmarkTaskInvocation",
    "BenchmarkTaskRequest",
    "BenchmarkResolutionError",
    "ResolvedBenchmarkPlan",
    "ResolvedBenchmarkTask",
    "ResolvedCapability",
    "public_plan_dict",
    "resolve_benchmark_suite",
    "resolve_benchmark_tasks",
)
