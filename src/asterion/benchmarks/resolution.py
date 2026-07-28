"""Exact provider-free benchmark planning and binding attachment."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Never, TypeVar

from asterion.benchmarks.model import (
    BenchmarkPlan,
    PlannedBenchmarkTask,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    ResolvedCapability,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.model import (
    BenchmarkTaskBinding,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.protocol import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    validate_benchmark_suite_manifest,
)


class BenchmarkResolutionError(ValueError):
    """Raised when benchmark metadata or bindings are not one exact closure."""


_Value = TypeVar("_Value")


def resolve_benchmark_suite(
    suite_ref: BenchmarkSuiteRef,
    payloads: Sequence[PortableCapabilityPayload],
) -> BenchmarkSuiteManifest:
    """Select one exact suite from validated portable payload metadata."""

    try:
        return _resolve_benchmark_suite(suite_ref, payloads)
    except BenchmarkResolutionError:
        raise
    except Exception:
        raise BenchmarkResolutionError(
            "benchmark suite resolution failed"
        ) from None


def plan_benchmark_tasks(
    suite: BenchmarkSuiteManifest,
    capabilities: Sequence[ResolvedCapability],
) -> tuple[PlannedBenchmarkTask, ...]:
    """Pair canonical suite tasks with application-selected capabilities."""

    try:
        return _plan_benchmark_tasks(suite, capabilities)
    except BenchmarkResolutionError:
        raise
    except Exception:
        raise BenchmarkResolutionError(
            "benchmark task planning failed"
        ) from None


def resolve_benchmark_execution(
    plan: BenchmarkPlan,
    packages: Sequence[InstalledCapabilityPackage],
) -> ResolvedBenchmarkPlan:
    """Attach one exact selected-provider binding to every planned task."""

    try:
        return _resolve_benchmark_execution(plan, packages)
    except BenchmarkResolutionError:
        raise
    except Exception:
        raise BenchmarkResolutionError(
            "benchmark execution resolution failed"
        ) from None


def _resolve_benchmark_suite(
    suite_ref: BenchmarkSuiteRef,
    payloads: Sequence[PortableCapabilityPayload],
) -> BenchmarkSuiteManifest:
    if not isinstance(suite_ref, BenchmarkSuiteRef):
        _fail_suite()
    values = _sequence_snapshot(payloads)
    if any(
        not isinstance(payload, PortableCapabilityPayload)
        or not _valid_package_manifest(payload.manifest)
        for payload in values
    ):
        _fail_suite()

    packages: dict[CapabilityPackageRef, PortableCapabilityPayload] = {}
    suites: dict[BenchmarkSuiteRef, PortableCapabilityPayload] = {}
    for payload in values:
        package_ref = payload.manifest.package_ref
        if package_ref in packages:
            _fail_suite()
        packages[package_ref] = payload
        for declared_suite_ref in payload.manifest.benchmark_suites:
            if declared_suite_ref in suites:
                _fail_suite()
            suites[declared_suite_ref] = payload

    payload = suites.get(suite_ref)
    if payload is None:
        _fail_suite()
    suite_by_ref = _suite_closure(payload)
    suite = suite_by_ref.get(suite_ref)
    if suite is None:
        _fail_suite()
    return suite


def _plan_benchmark_tasks(
    suite: BenchmarkSuiteManifest,
    capabilities: Sequence[ResolvedCapability],
) -> tuple[PlannedBenchmarkTask, ...]:
    if not _valid_suite_shape(suite):
        _fail_planning()
    values = _sequence_snapshot(capabilities)
    if any(not isinstance(capability, ResolvedCapability) for capability in values):
        _fail_planning()

    capability_by_ref: dict[CapabilityRef, ResolvedCapability] = {}
    for capability in values:
        if capability.ref in capability_by_ref:
            _fail_planning()
        capability_by_ref[capability.ref] = capability

    planned: list[PlannedBenchmarkTask] = []
    for ordinal, task in enumerate(suite.tasks, start=1):
        capability = capability_by_ref.get(task.capability)
        if capability is None:
            _fail_planning()
        planned.append(
            PlannedBenchmarkTask(
                ordinal=ordinal,
                task=task,
                capability=capability,
            )
        )
    return tuple(planned)


def _resolve_benchmark_execution(
    plan: BenchmarkPlan,
    packages: Sequence[InstalledCapabilityPackage],
) -> ResolvedBenchmarkPlan:
    if not isinstance(plan, BenchmarkPlan):
        _fail_execution()
    values = _sequence_snapshot(packages)
    package_by_ref: dict[CapabilityPackageRef, InstalledCapabilityPackage] = {}
    root_owners: dict[Path, CapabilityPackageRef] = {}
    locked_identity_by_ref: dict[CapabilityPackageRef, tuple[str, str]] = {}
    binding_by_key: dict[
        tuple[CapabilityPackageRef, str],
        BenchmarkTaskBinding,
    ] = {}

    for lock in plan.package_locks:
        for entry in lock.entries:
            if entry.package_ref in locked_identity_by_ref:
                _fail_execution()
            locked_identity_by_ref[entry.package_ref] = (
                entry.payload_sha256,
                entry.source_id,
            )

    for package in values:
        if (
            not isinstance(package, InstalledCapabilityPackage)
            or not isinstance(package.package_ref, CapabilityPackageRef)
            or not isinstance(package.catalog_roots, tuple)
            or not package.catalog_roots
            or any(not isinstance(root, Path) for root in package.catalog_roots)
            or not isinstance(package.benchmark_bindings, tuple)
        ):
            _fail_execution()
        if package.package_ref in package_by_ref:
            _fail_execution()
        package_by_ref[package.package_ref] = package
        locked_identity = locked_identity_by_ref.get(package.package_ref)
        if (
            locked_identity is None
            or (package.payload_sha256, package.source_id) != locked_identity
        ):
            _fail_execution()

        for root in package.catalog_roots:
            if root in root_owners:
                _fail_execution()
            root_owners[root] = package.package_ref

    owner_ref = plan.suite.owner_package
    owner = package_by_ref.get(owner_ref)
    owner_lock = locked_identity_by_ref.get(owner_ref)
    if (
        owner is None
        or owner_lock is None
        or (owner.payload_sha256, owner.source_id) != owner_lock
    ):
        _fail_execution()

    for package in values:
        for binding in package.benchmark_bindings:
            if (
                not isinstance(binding, BenchmarkTaskBinding)
                or binding.owner_package != package.package_ref
                or not isinstance(binding.binding_id, str)
                or not binding.binding_id
            ):
                _fail_execution()
            key = (package.package_ref, binding.binding_id)
            if key in binding_by_key:
                _fail_execution()
            binding_by_key[key] = binding

    owner_roots = frozenset(owner.catalog_roots)
    if any(
        not isinstance(planned.capability.source, Path)
        or planned.capability.source.parent not in owner_roots
        for planned in plan.tasks
    ):
        _fail_execution()

    task_keys = tuple(
        (owner_ref, planned.task.binding_id)
        for planned in plan.tasks
    )
    if set(binding_by_key) != set(task_keys):
        _fail_execution()

    resolved = tuple(
        ResolvedBenchmarkTask(
            planned=planned,
            binding=binding_by_key[key],
        )
        for planned, key in zip(plan.tasks, task_keys, strict=True)
    )
    return ResolvedBenchmarkPlan(plan=plan, tasks=resolved)


def _suite_closure(
    payload: PortableCapabilityPayload,
) -> dict[BenchmarkSuiteRef, BenchmarkSuiteManifest]:
    suite_root = payload.resource_root.joinpath("benchmark-suites")
    if not suite_root.is_dir():
        _fail_suite()
    try:
        children = tuple(suite_root.iterdir())
    except Exception:
        _fail_suite()

    suite_by_ref: dict[BenchmarkSuiteRef, BenchmarkSuiteManifest] = {}
    for child in children:
        if not _is_json_file(child):
            _fail_suite()
        try:
            with child.open("r", encoding="utf-8") as stream:
                suite = validate_benchmark_suite_manifest(json.load(stream))
        except Exception:
            _fail_suite()
        if (
            suite.suite_ref in suite_by_ref
            or suite.owner_package != payload.manifest.package_ref
            or any(
                task.capability not in payload.manifest.capabilities
                for task in suite.tasks
            )
        ):
            _fail_suite()
        suite_by_ref[suite.suite_ref] = suite

    observed_refs = tuple(sorted(suite_by_ref))
    if observed_refs != payload.manifest.benchmark_suites:
        _fail_suite()
    return suite_by_ref


def _valid_package_manifest(value: object) -> bool:
    return (
        isinstance(value, CapabilityPackageManifest)
        and isinstance(value.package_ref, CapabilityPackageRef)
        and isinstance(value.capabilities, tuple)
        and bool(value.capabilities)
        and all(isinstance(ref, CapabilityRef) for ref in value.capabilities)
        and tuple(sorted(set(value.capabilities))) == value.capabilities
        and isinstance(value.benchmark_suites, tuple)
        and all(
            isinstance(ref, BenchmarkSuiteRef)
            for ref in value.benchmark_suites
        )
        and tuple(sorted(set(value.benchmark_suites)))
        == value.benchmark_suites
    )


def _valid_suite_shape(value: object) -> bool:
    if (
        not isinstance(value, BenchmarkSuiteManifest)
        or not isinstance(value.suite_ref, BenchmarkSuiteRef)
        or not isinstance(value.owner_package, CapabilityPackageRef)
        or not isinstance(value.tasks, tuple)
        or not value.tasks
    ):
        return False
    task_ids = tuple(task.task_id for task in value.tasks)
    return task_ids == tuple(sorted(set(task_ids)))


def _is_json_file(value: Traversable) -> bool:
    try:
        return value.is_file() and value.name.endswith(".json")
    except Exception:
        return False


def _sequence_snapshot(value: Sequence[_Value]) -> tuple[_Value, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError
    return tuple(value)


def _fail_suite() -> Never:
    raise BenchmarkResolutionError("benchmark suite resolution failed")


def _fail_planning() -> Never:
    raise BenchmarkResolutionError("benchmark task planning failed")


def _fail_execution() -> Never:
    raise BenchmarkResolutionError(
        "benchmark execution resolution failed"
    )
