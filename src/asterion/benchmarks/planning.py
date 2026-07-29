"""Pure benchmark plan construction from composed application state."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NoReturn, Protocol, runtime_checkable

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


@runtime_checkable
class BenchmarkExecutionAuthorization(Protocol):
    """Opaque host-owned benchmark execution authorization claim."""


@runtime_checkable
class BenchmarkExecutionAuthorizer(Protocol):
    """Host-owned service that validates opaque execution authorization claims."""

    def authorize_benchmark_execution(
        self,
        authorization: BenchmarkExecutionAuthorization,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int,
    ) -> str: ...


def create_benchmark_plan(
    request: BenchmarkPlanRequest,
    application: InstalledApplication,
    packages: Sequence[InstalledCapabilityPackage],
    *,
    authorizer: BenchmarkExecutionAuthorizer | None = None,
) -> ResolvedBenchmarkPlan:
    """Resolve a benchmark plan without building invocations or self-authorizing."""

    try:
        return _create_benchmark_plan(
            request,
            application,
            packages,
            authorizer=authorizer,
        )
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


def _create_benchmark_plan(
    request: BenchmarkPlanRequest,
    application: InstalledApplication,
    packages: Sequence[InstalledCapabilityPackage],
    *,
    authorizer: BenchmarkExecutionAuthorizer | None,
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
        run_id = (
            _authorized_run_id(request, case_limit, authorizer=authorizer)
            if request.execute
            else _new_run_id()
        )
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


def _authorized_run_id(
    request: BenchmarkPlanRequest,
    case_limit: int,
    *,
    authorizer: BenchmarkExecutionAuthorizer | None,
) -> str:
    authorization = request.authorization
    if authorizer is None or authorization is None:
        _fail("benchmark execution authorization is invalid")
    try:
        run_id = authorizer.authorize_benchmark_execution(
            authorization,
            application_ref=request.application_ref,
            suite_ref=request.suite_ref,
            case_limit=case_limit,
        )
    except Exception:
        _fail("benchmark execution authorization is invalid")
    if not _is_run_id(run_id):
        _fail("benchmark execution authorization is invalid")
    return run_id


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
    try:
        composed_values = _package_tuple(application.installed_packages)
    except Exception:
        _fail("benchmark planning is invalid")
    explicit_values = _package_tuple(packages)
    composed_map = _package_map(composed_values)
    explicit_map = _package_map(explicit_values)
    if set(composed_map) != set(package_refs) or set(explicit_map) != set(package_refs):
        _fail("benchmark planning is invalid")
    for package_ref in package_refs:
        composed = composed_map[package_ref]
        explicit = explicit_map[package_ref]
        if explicit is not composed and not _same_installed_package_snapshot(
            explicit,
            composed,
        ):
            _fail("benchmark planning is invalid")
    return tuple(composed_map[package_ref] for package_ref in package_refs)


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


def _package_map(
    packages: Sequence[InstalledCapabilityPackage],
) -> dict[CapabilityPackageRef, InstalledCapabilityPackage]:
    result: dict[CapabilityPackageRef, InstalledCapabilityPackage] = {}
    for package in packages:
        if package.package_ref in result:
            _fail("benchmark planning is invalid")
        result[package.package_ref] = package
    return result


def _same_installed_package_snapshot(
    left: InstalledCapabilityPackage,
    right: InstalledCapabilityPackage,
) -> bool:
    try:
        return (
            left.package_ref == right.package_ref
            and left.payload_sha256 == right.payload_sha256
            and left.source_id == right.source_id
            and left.source_kind == right.source_kind
            and left.catalog_roots == right.catalog_roots
            and left.benchmark_suite_paths == right.benchmark_suite_paths
            and _implementation_binding_refs(left) == _implementation_binding_refs(right)
            and _benchmark_binding_refs(left) == _benchmark_binding_refs(right)
        )
    except Exception:
        _fail("benchmark planning is invalid")


def _implementation_binding_refs(
    package: InstalledCapabilityPackage,
) -> tuple[CapabilityRef, ...]:
    return tuple(binding.capability_ref for binding in package.implementations)


def _benchmark_binding_refs(
    package: InstalledCapabilityPackage,
) -> tuple[tuple[CapabilityPackageRef, str], ...]:
    return tuple(
        (binding.owner_package, binding.binding_id)
        for binding in package.benchmark_bindings
    )


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


def _is_run_id(value: object) -> bool:
    return type(value) is str and _RUN_ID.fullmatch(value) is not None


def _package_selector(ref: CapabilityPackageRef) -> str:
    return f"{ref.package_id}@{ref.version}"


def _fail(message: str) -> NoReturn:
    raise BenchmarkPlanningError(message) from None
