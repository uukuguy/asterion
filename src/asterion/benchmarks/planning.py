"""Pure benchmark plan construction from composed application state."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from asterion.applications import InstalledApplication, InstalledAssembly
from asterion.assembly.protocol import AssemblyPlan
from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkModelError,
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


_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_MAX_AUTHORIZATION_VALIDITY = timedelta(minutes=15)
_BENCHMARK_AUTHORIZATION_ISSUER = object()


class BenchmarkPlanningError(ValueError):
    """Raised when benchmark planning or authorization claims are invalid."""


@dataclass(frozen=True, slots=True)
class BenchmarkPlanRequest:
    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    case_limit: int | None
    execute: bool
    authorization: BenchmarkExecutionAuthorization | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.application_ref, ApplicationRef)
            or not isinstance(self.suite_ref, BenchmarkSuiteRef)
            or type(self.execute) is not bool
            or (
                self.case_limit is not None
                and type(self.case_limit) is not int
            )
        ):
            _fail("benchmark plan request is invalid")
        if self.authorization is not None and not isinstance(
            self.authorization,
            BenchmarkExecutionAuthorization,
        ):
            _fail("benchmark plan request is invalid")


@dataclass(frozen=True, init=False, slots=True)
class BenchmarkExecutionAuthorization:
    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    run_id: str
    case_limit: int
    issued_at: datetime
    expires_at: datetime
    _issuance_capability: object = field(repr=False, compare=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError(
            "benchmark execution authorization must be host-issued"
        )


def create_benchmark_plan(
    request: BenchmarkPlanRequest,
    application: InstalledApplication,
    packages: Sequence[InstalledCapabilityPackage],
) -> ResolvedBenchmarkPlan:
    """Resolve a benchmark plan without building invocations or self-authorizing."""

    try:
        return _create_benchmark_plan(request, application, packages)
    except BenchmarkPlanningError:
        raise
    except Exception:
        _fail("benchmark planning is invalid")


def render_benchmark_plan(plan: ResolvedBenchmarkPlan) -> str:
    """Render a deterministic body-free public projection of a benchmark plan."""

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
        )
    except BenchmarkPlanningError:
        raise
    except Exception:
        _fail("benchmark planning is invalid")


def _issue_benchmark_execution_authorization(
    *,
    application_ref: ApplicationRef,
    suite_ref: BenchmarkSuiteRef,
    run_id: str,
    case_limit: int,
    issued_at: datetime,
    expires_at: datetime,
    issuance_capability: object,
) -> BenchmarkExecutionAuthorization:
    if issuance_capability is not _BENCHMARK_AUTHORIZATION_ISSUER:
        _fail("benchmark execution authorization is invalid")
    if (
        not isinstance(application_ref, ApplicationRef)
        or not isinstance(suite_ref, BenchmarkSuiteRef)
        or not _is_run_id(run_id)
        or type(case_limit) is not int
        or case_limit < 1
        or not isinstance(issued_at, datetime)
        or not isinstance(expires_at, datetime)
    ):
        _fail("benchmark execution authorization is invalid")
    authorization = object.__new__(BenchmarkExecutionAuthorization)
    object.__setattr__(authorization, "application_ref", application_ref)
    object.__setattr__(authorization, "suite_ref", suite_ref)
    object.__setattr__(authorization, "run_id", run_id)
    object.__setattr__(authorization, "case_limit", case_limit)
    object.__setattr__(authorization, "issued_at", issued_at)
    object.__setattr__(authorization, "expires_at", expires_at)
    object.__setattr__(
        authorization,
        "_issuance_capability",
        _BENCHMARK_AUTHORIZATION_ISSUER,
    )
    return authorization


def _create_benchmark_plan(
    request: BenchmarkPlanRequest,
    application: InstalledApplication,
    packages: Sequence[InstalledCapabilityPackage],
) -> ResolvedBenchmarkPlan:
    if not isinstance(request, BenchmarkPlanRequest) or not isinstance(
        application,
        InstalledApplication,
    ):
        _fail("benchmark planning is invalid")
    application_ref = _application_ref(application)
    if request.application_ref != application_ref:
        _fail("benchmark planning is invalid")
    package_values = _application_packages(application, packages)
    assemblies = _application_assemblies(application, application_ref, package_values)
    capabilities = _resolved_capabilities(assemblies)
    try:
        suite = resolve_benchmark_suite(request.suite_ref, package_values)
        case_limit = _case_limit(request.case_limit, suite.default_case_limit)
        run_id = _authorized_run_id(request, case_limit) if request.execute else _new_run_id()
        tasks = resolve_benchmark_tasks(suite, capabilities, package_values)
        locks = _source_locks(package_values)
        return ResolvedBenchmarkPlan(
            run_id=run_id,
            application_ref=application_ref,
            suite=suite,
            tasks=tasks,
            case_limit=case_limit,
            package_locks=locks,
        )
    except (
        BenchmarkModelError,
        BenchmarkResolutionError,
        CapabilitySourceProtocolError,
        ValueError,
    ):
        _fail("benchmark planning is invalid")


def _authorized_run_id(request: BenchmarkPlanRequest, case_limit: int) -> str:
    authorization = request.authorization
    if (
        type(authorization) is not BenchmarkExecutionAuthorization
        or getattr(authorization, "_issuance_capability", None)
        is not _BENCHMARK_AUTHORIZATION_ISSUER
    ):
        _fail("benchmark execution authorization is invalid")
    now = _utc_now()
    if (
        authorization.application_ref != request.application_ref
        or authorization.suite_ref != request.suite_ref
        or authorization.case_limit != case_limit
        or not _is_run_id(authorization.run_id)
        or not _is_utc(authorization.issued_at)
        or not _is_utc(authorization.expires_at)
        or not _is_utc(now)
        or authorization.issued_at > now
        or authorization.expires_at <= now
        or authorization.expires_at - authorization.issued_at
        > _MAX_AUTHORIZATION_VALIDITY
    ):
        _fail("benchmark execution authorization is invalid")
    return authorization.run_id


def _application_ref(application: InstalledApplication) -> ApplicationRef:
    try:
        return ApplicationRef(application.application_id, application.version)
    except Exception:
        _fail("benchmark planning is invalid")


def _application_packages(
    application: InstalledApplication,
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[InstalledCapabilityPackage, ...]:
    package_refs = _package_ref_tuple(application.capability_packages)
    package_values = _package_tuple(packages)
    package_map: dict[CapabilityPackageRef, InstalledCapabilityPackage] = {}
    for package in package_values:
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


def _package_ref_tuple(values: object) -> tuple[CapabilityPackageRef, ...]:
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


def _package_tuple(
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[InstalledCapabilityPackage, ...]:
    if not isinstance(packages, Sequence):
        _fail("benchmark planning is invalid")
    try:
        package_values = tuple(packages)
    except Exception:
        _fail("benchmark planning is invalid")
    if not all(type(package) is InstalledCapabilityPackage for package in package_values):
        _fail("benchmark planning is invalid")
    return package_values


def _case_limit(value: int | None, maximum: int) -> int:
    selected = maximum if value is None else value
    if type(selected) is not int or selected < 1 or selected > maximum:
        _fail("benchmark planning case limit is invalid")
    return selected


def _manifest_ref(manifest: Mapping[str, object]) -> CapabilityRef:
    if not isinstance(manifest, Mapping):
        _fail("benchmark planning is invalid")
    capability_id = manifest.get("capability_id")
    version = manifest.get("version")
    if not isinstance(capability_id, str) or not isinstance(version, str):
        _fail("benchmark planning is invalid")
    return CapabilityRef(capability_id, version)


def _new_run_id() -> str:
    return f"run-{uuid.uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_run_id(value: object) -> bool:
    return type(value) is str and _RUN_ID.fullmatch(value) is not None


def _is_utc(value: datetime) -> bool:
    return isinstance(value, datetime) and value.utcoffset() == timedelta(0)


def _package_selector(ref: CapabilityPackageRef) -> str:
    return f"{ref.package_id}@{ref.version}"


def _fail(message: str) -> NoReturn:
    raise BenchmarkPlanningError(message) from None
