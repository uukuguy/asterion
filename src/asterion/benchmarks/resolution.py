"""Exact closed-world benchmark suite and task resolution."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from asterion.benchmarks.model import (
    ResolvedBenchmarkTask,
    ResolvedCapability,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteProtocolError,
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    InstalledCapabilityPackage,
    validate_benchmark_suite_manifest,
)


class BenchmarkResolutionError(ValueError):
    """Raised when generic benchmark resolution is ambiguous or incomplete."""


def resolve_benchmark_suite(
    suite_ref: BenchmarkSuiteRef,
    packages: Sequence[InstalledCapabilityPackage],
) -> BenchmarkSuiteManifest:
    """Resolve one exact suite ref from already installed capability packages."""

    if not isinstance(suite_ref, BenchmarkSuiteRef):
        raise BenchmarkResolutionError("benchmark suite resolution is invalid")
    matches: list[BenchmarkSuiteManifest] = []
    for package in _package_tuple(packages):
        for suite in _package_suites(package):
            if suite.owner_package != package.package_ref:
                raise BenchmarkResolutionError(
                    "benchmark suite resolution is invalid"
                )
            if suite.suite_ref == suite_ref:
                matches.append(suite)
    if len(matches) != 1:
        raise BenchmarkResolutionError("benchmark suite resolution is invalid")
    return matches[0]


def resolve_benchmark_tasks(
    suite: BenchmarkSuiteManifest,
    capabilities: Sequence[ResolvedCapability],
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[ResolvedBenchmarkTask, ...]:
    """Resolve benchmark task bindings for one selected suite."""

    if not isinstance(suite, BenchmarkSuiteManifest):
        raise BenchmarkResolutionError("benchmark task resolution is invalid")
    package_values = _package_tuple(packages)
    capability_map = _capability_map(capabilities)
    binding_map: dict[tuple[CapabilityPackageRef, str], BenchmarkTaskBinding] = {}
    known_bindings: dict[CapabilityPackageRef, set[str]] = {
        suite.owner_package: {task.binding_id for task in suite.tasks}
    }
    seen_packages: set[CapabilityPackageRef] = set()
    for package in package_values:
        if package.package_ref in seen_packages:
            raise BenchmarkResolutionError("benchmark task resolution is invalid")
        seen_packages.add(package.package_ref)
        for package_suite in _package_suites(package):
            if package_suite.owner_package != package.package_ref:
                raise BenchmarkResolutionError(
                    "benchmark task resolution is invalid"
                )
            known_bindings.setdefault(package.package_ref, set()).update(
                task.binding_id for task in package_suite.tasks
            )
        for binding in package.benchmark_bindings:
            if (
                not isinstance(binding, BenchmarkTaskBinding)
                or binding.owner_package != package.package_ref
            ):
                raise BenchmarkResolutionError(
                    "benchmark task resolution is invalid"
                )
            key = (binding.owner_package, binding.binding_id)
            if key in binding_map:
                raise BenchmarkResolutionError(
                    "benchmark task resolution is invalid"
                )
            binding_map[key] = binding
    for binding in binding_map.values():
        if binding.binding_id not in known_bindings.get(binding.owner_package, set()):
            raise BenchmarkResolutionError("benchmark task resolution is invalid")
    resolved: list[ResolvedBenchmarkTask] = []
    for ordinal, task in enumerate(suite.tasks, start=1):
        capability = capability_map.get(task.capability)
        binding = binding_map.get((suite.owner_package, task.binding_id))
        if capability is None or binding is None:
            raise BenchmarkResolutionError("benchmark task resolution is invalid")
        try:
            resolved.append(
                ResolvedBenchmarkTask(
                    ordinal=ordinal,
                    task=task,
                    capability=capability,
                    binding=binding,
                )
            )
        except ValueError:
            raise BenchmarkResolutionError(
                "benchmark task resolution is invalid"
            ) from None
    return tuple(resolved)


def _package_tuple(
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[InstalledCapabilityPackage, ...]:
    try:
        package_values = tuple(packages)
    except TypeError:
        raise BenchmarkResolutionError("benchmark package set is invalid") from None
    if not all(isinstance(package, InstalledCapabilityPackage) for package in package_values):
        raise BenchmarkResolutionError("benchmark package set is invalid")
    return package_values


def _capability_map(
    capabilities: Sequence[ResolvedCapability],
) -> dict[CapabilityRef, ResolvedCapability]:
    try:
        capability_values = tuple(capabilities)
    except TypeError:
        raise BenchmarkResolutionError("benchmark capability set is invalid") from None
    result: dict[CapabilityRef, ResolvedCapability] = {}
    for capability in capability_values:
        if not isinstance(capability, ResolvedCapability) or capability.ref in result:
            raise BenchmarkResolutionError("benchmark capability set is invalid")
        result[capability.ref] = capability
    return result


def _package_suites(
    package: InstalledCapabilityPackage,
) -> tuple[BenchmarkSuiteManifest, ...]:
    suites: list[BenchmarkSuiteManifest] = []
    for suite_root in package.benchmark_suite_paths:
        if not isinstance(suite_root, Path):
            raise BenchmarkResolutionError("benchmark suite resolution is invalid")
        try:
            suite_paths = tuple(
                path
                for path in sorted(suite_root.iterdir(), key=lambda child: child.name)
                if path.suffix == ".json"
            )
        except OSError:
            raise BenchmarkResolutionError(
                "benchmark suite resolution is invalid"
            ) from None
        for suite_path in suite_paths:
            try:
                if not suite_path.is_file():
                    raise BenchmarkResolutionError(
                        "benchmark suite resolution is invalid"
                    )
                suites.append(
                    validate_benchmark_suite_manifest(
                        json.loads(suite_path.read_text(encoding="utf-8"))
                    )
                )
            except BenchmarkResolutionError:
                raise
            except (OSError, json.JSONDecodeError, BenchmarkSuiteProtocolError):
                raise BenchmarkResolutionError(
                    "benchmark suite resolution is invalid"
                ) from None
    return tuple(suites)


__all__ = (
    "BenchmarkResolutionError",
    "resolve_benchmark_suite",
    "resolve_benchmark_tasks",
)
