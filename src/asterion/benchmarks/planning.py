"""Benchmark plan construction and authorization-gated invocation building."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from asterion.applications import InstalledApplication, InstalledAssembly
from asterion.assembly.protocol import AssemblyPlan
from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkModelError,
    BenchmarkTaskImplementation,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedCapability,
    public_plan_dict,
)
from asterion.benchmarks.resolution import (
    BenchmarkResolutionError,
    resolve_benchmark_suite,
    resolve_benchmark_tasks,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.protocol import CapabilitySourceProtocolError


_NONCE = re.compile(r"^[a-z0-9](?:[a-z0-9]|[._-](?=[a-z0-9])){5,127}$")
_CONSUMED_AUTHORIZATIONS: set[tuple[str, str]] = set()


class BenchmarkPlanningError(ValueError):
    """Raised when benchmark planning or authorized invocation building fails."""


@dataclass(frozen=True, slots=True)
class BenchmarkExecutionAuthorization:
    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    run_id: str
    case_limit: int
    nonce: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.application_ref, ApplicationRef)
            or not isinstance(self.suite_ref, BenchmarkSuiteRef)
        ):
            _fail("benchmark execution authorization is invalid")
        try:
            BenchmarkTaskRequest(
                run_id=self.run_id,
                suite_ref=self.suite_ref,
                task_id="authorization.probe",
                case_limit=self.case_limit,
                output_directory=Path("."),
            )
        except BenchmarkModelError:
            _fail("benchmark execution authorization is invalid")
        if (
            type(self.nonce) is not str
            or _NONCE.fullmatch(self.nonce) is None
            or not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
        ):
            _fail("benchmark execution authorization is invalid")


def create_benchmark_plan(
    application: InstalledApplication,
    suite_ref: BenchmarkSuiteRef,
    *,
    run_id: str,
    case_limit: int | None = None,
) -> ResolvedBenchmarkPlan:
    """Resolve a benchmark plan from an already composed installed application."""

    try:
        return _create_benchmark_plan(
            application,
            suite_ref,
            run_id=run_id,
            case_limit=case_limit,
        )
    except BenchmarkPlanningError:
        raise
    except Exception:
        _fail("benchmark planning is invalid")


def render_public_benchmark_plan(plan: ResolvedBenchmarkPlan) -> bytes:
    """Render the body-free public projection of a benchmark plan."""

    try:
        if not isinstance(plan, ResolvedBenchmarkPlan):
            _fail("benchmark planning is invalid")
        value = public_plan_dict(plan)
        value["package_locks"] = [
            {
                "package": _package_selector(entry.package_ref),
                "payload_sha256": entry.payload_sha256,
                "source_id": entry.source_id,
            }
            for lock in plan.package_locks
            for entry in lock.entries
        ]
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except BenchmarkPlanningError:
        raise
    except Exception:
        _fail("benchmark planning is invalid")


def execute_benchmark_plan(
    plan: ResolvedBenchmarkPlan,
    authorization: BenchmarkExecutionAuthorization,
    *,
    output_directory: Path,
    now: datetime | None = None,
) -> tuple[BenchmarkTaskInvocation, ...]:
    """Build benchmark task invocations only with exact fresh host authorization."""

    try:
        if not isinstance(plan, ResolvedBenchmarkPlan) or not isinstance(
            authorization,
            BenchmarkExecutionAuthorization,
        ):
            _fail("benchmark execution is unauthorized")
        if not isinstance(output_directory, Path):
            _fail("benchmark execution is unauthorized")
        effective_now = now if now is not None else datetime.now(UTC)
        _validate_authorization(plan, authorization, effective_now)
        invocations: list[BenchmarkTaskInvocation] = []
        for task in plan.tasks:
            request = BenchmarkTaskRequest(
                run_id=plan.run_id,
                suite_ref=plan.suite.suite_ref,
                task_id=task.task.task_id,
                case_limit=plan.case_limit,
                output_directory=output_directory,
            )
            implementation = task.binding.implementation
            if not isinstance(implementation, BenchmarkTaskImplementation):
                _fail("benchmark execution is invalid")
            invocation = implementation.build_invocation(request)
            if (
                not isinstance(invocation, BenchmarkTaskInvocation)
                or invocation.task_id != task.task.task_id
                or invocation.binding_id != task.binding.binding_id
            ):
                _fail("benchmark execution is invalid")
            invocations.append(invocation)
        return tuple(invocations)
    except BenchmarkPlanningError:
        raise
    except Exception:
        _fail("benchmark execution is invalid")


def _create_benchmark_plan(
    application: InstalledApplication,
    suite_ref: BenchmarkSuiteRef,
    *,
    run_id: str,
    case_limit: int | None,
) -> ResolvedBenchmarkPlan:
    if not isinstance(application, InstalledApplication) or not isinstance(
        suite_ref,
        BenchmarkSuiteRef,
    ):
        _fail("benchmark planning is invalid")
    application_ref = ApplicationRef(application.application_id, application.version)
    packages = _application_packages(application)
    assemblies = _application_assemblies(application, application_ref, packages)
    capabilities = _resolved_capabilities(assemblies)
    try:
        suite = resolve_benchmark_suite(suite_ref, packages)
        selected_case_limit = (
            suite.default_case_limit if case_limit is None else case_limit
        )
        if (
            type(selected_case_limit) is not int
            or selected_case_limit < 1
            or selected_case_limit > suite.default_case_limit
        ):
            _fail("benchmark planning case limit is invalid")
        tasks = resolve_benchmark_tasks(suite, capabilities, packages)
        locks = _source_locks(packages)
        return ResolvedBenchmarkPlan(
            run_id=run_id,
            application_ref=application_ref,
            suite=suite,
            tasks=tasks,
            case_limit=selected_case_limit,
            package_locks=locks,
        )
    except (
        BenchmarkModelError,
        BenchmarkResolutionError,
        CapabilitySourceProtocolError,
        ValueError,
    ):
        _fail("benchmark planning is invalid")


def _application_packages(
    application: InstalledApplication,
) -> tuple[InstalledCapabilityPackage, ...]:
    package_refs = _package_ref_tuple(application.capability_packages)
    try:
        installed_packages = tuple(application.installed_packages)
    except Exception:
        _fail("benchmark planning is invalid")
    if not all(
        type(package) is InstalledCapabilityPackage for package in installed_packages
    ):
        _fail("benchmark planning is invalid")
    package_map: dict[CapabilityPackageRef, InstalledCapabilityPackage] = {}
    for package in installed_packages:
        if package.package_ref in package_map:
            _fail("benchmark planning is invalid")
        package_map[package.package_ref] = package
    if set(package_map) != set(package_refs):
        _fail("benchmark planning is invalid")
    return tuple(package_map[package_ref] for package_ref in package_refs)


def _application_assemblies(
    application: InstalledApplication,
    application_ref: ApplicationRef,
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[InstalledAssembly, ...]:
    try:
        assemblies = tuple(application.assemblies)
        runtime_ids = tuple(application.runtime_ids)
    except Exception:
        _fail("benchmark planning is invalid")
    if (
        not assemblies
        or not all(type(assembly) is InstalledAssembly for assembly in assemblies)
        or not all(type(runtime_id) is str for runtime_id in runtime_ids)
        or tuple(sorted(set(runtime_ids))) != runtime_ids
    ):
        _fail("benchmark planning is invalid")
    expected_packages = tuple(package.package_ref for package in packages)
    for assembly in assemblies:
        plan = assembly.plan
        if (
            not isinstance(plan, AssemblyPlan)
            or assembly.runtime_id != plan.runtime_id
            or assembly.runtime_id not in runtime_ids
            or plan.application_id != application_ref.application_id
            or plan.version != application_ref.version
            or tuple(plan.capability_package_refs) != expected_packages
        ):
            _fail("benchmark planning is invalid")
    if tuple(sorted(assembly.runtime_id for assembly in assemblies)) != runtime_ids:
        _fail("benchmark planning is invalid")
    return tuple(sorted(assemblies, key=lambda assembly: assembly.runtime_id))


def _resolved_capabilities(
    assemblies: Sequence[InstalledAssembly],
) -> tuple[ResolvedCapability, ...]:
    capabilities: dict[CapabilityRef, ResolvedCapability] = {}
    for assembly in assemblies:
        plan = assembly.plan
        selected_refs = set(plan.capability_refs)
        manifest_refs: set[CapabilityRef] = set()
        for manifest in plan.capability_manifests:
            ref = _manifest_ref(manifest)
            manifest_refs.add(ref)
            if ref not in selected_refs:
                _fail("benchmark planning is invalid")
            resolved = ResolvedCapability(ref=ref, manifest=manifest)
            existing = capabilities.get(ref)
            if existing is not None and existing.manifest != resolved.manifest:
                _fail("benchmark planning is invalid")
            capabilities[ref] = resolved
        if manifest_refs != selected_refs:
            _fail("benchmark planning is invalid")
    return tuple(capabilities[ref] for ref in sorted(capabilities))


def _source_locks(
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[CapabilitySourceLock, ...]:
    return (
        CapabilitySourceLock(
            entries=tuple(
                CapabilitySourceLockEntry(
                    package_ref=package.package_ref,
                    payload_sha256=package.payload_sha256,
                    source_id=package.source_id,
                )
                for package in packages
            )
        ),
    )


def _validate_authorization(
    plan: ResolvedBenchmarkPlan,
    authorization: BenchmarkExecutionAuthorization,
    now: datetime,
) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        _fail("benchmark execution is unauthorized")
    key = (authorization.run_id, authorization.nonce)
    if (
        authorization.application_ref != plan.application_ref
        or authorization.suite_ref != plan.suite.suite_ref
        or authorization.run_id != plan.run_id
        or authorization.case_limit != plan.case_limit
        or authorization.expires_at <= now
        or key in _CONSUMED_AUTHORIZATIONS
    ):
        _fail("benchmark execution is unauthorized")
    _CONSUMED_AUTHORIZATIONS.add(key)


def _package_ref_tuple(
    values: object,
) -> tuple[CapabilityPackageRef, ...]:
    if not isinstance(values, Sequence):
        _fail("benchmark planning is invalid")
    try:
        package_refs = tuple(values)
    except Exception:
        _fail("benchmark planning is invalid")
    if (
        not package_refs
        or not all(type(package_ref) is CapabilityPackageRef for package_ref in package_refs)
        or tuple(sorted(package_refs)) != package_refs
        or len(set(package_refs)) != len(package_refs)
    ):
        _fail("benchmark planning is invalid")
    return package_refs


def _manifest_ref(manifest: Mapping[str, object]) -> CapabilityRef:
    if not isinstance(manifest, Mapping):
        _fail("benchmark planning is invalid")
    capability_id = manifest.get("capability_id")
    version = manifest.get("version")
    if not isinstance(capability_id, str) or not isinstance(version, str):
        _fail("benchmark planning is invalid")
    return CapabilityRef(capability_id, version)


def _package_selector(ref: CapabilityPackageRef) -> str:
    return f"{ref.package_id}@{ref.version}"


def _fail(message: str) -> NoReturn:
    raise BenchmarkPlanningError(message) from None
