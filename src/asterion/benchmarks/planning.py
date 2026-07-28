"""Pure construction and public rendering of bounded benchmark plans."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar
from uuid import uuid4

from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkPlan,
    ResolvedCapability,
    public_plan_dict,
)
from asterion.benchmarks.resolution import (
    BenchmarkResolutionError,
    plan_benchmark_tasks,
    resolve_benchmark_suite,
)
from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_Value = TypeVar("_Value")


class BenchmarkPlanningError(ValueError):
    """Raised when provider-free benchmark planning is not exact and bounded."""


@dataclass(frozen=True, slots=True)
class BenchmarkPlanRequest:
    """Public exact identities and optional finite operator case bound."""

    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    case_limit: int | None

    def __post_init__(self) -> None:
        if (
            not _valid_application_ref(self.application_ref)
            or not isinstance(self.suite_ref, BenchmarkSuiteRef)
        ):
            raise BenchmarkPlanningError("benchmark plan request is invalid")
        if self.case_limit is not None and (
            type(self.case_limit) is not int or self.case_limit <= 0
        ):
            raise BenchmarkPlanningError("benchmark case limit is invalid")


@dataclass(frozen=True, slots=True, init=False)
class ResolvedApplicationMetadata:
    """Provider-free application closure selected by the host."""

    application_ref: ApplicationRef
    capabilities: tuple[ResolvedCapability, ...] = field(repr=False)
    package_locks: tuple[CapabilitySourceLock, ...] = field(repr=False)

    def __init__(
        self,
        application_ref: ApplicationRef,
        capabilities: Iterable[ResolvedCapability],
        package_locks: Iterable[CapabilitySourceLock],
    ) -> None:
        object.__setattr__(self, "application_ref", application_ref)
        object.__setattr__(
            self,
            "capabilities",
            _snapshot(capabilities, "benchmark application metadata is invalid"),
        )
        object.__setattr__(
            self,
            "package_locks",
            _snapshot(
                package_locks,
                "benchmark application metadata is invalid",
            ),
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        capabilities = _snapshot(
            self.capabilities,
            "benchmark application metadata is invalid",
        )
        locks = _snapshot(
            self.package_locks,
            "benchmark application metadata is invalid",
        )
        if (
            not _valid_application_ref(self.application_ref)
            or not capabilities
            or any(
                not isinstance(capability, ResolvedCapability)
                for capability in capabilities
            )
            or not locks
            or any(not isinstance(lock, CapabilitySourceLock) for lock in locks)
        ):
            raise BenchmarkPlanningError(
                "benchmark application metadata is invalid"
            )

        capabilities = tuple(
            sorted(capabilities, key=lambda item: item.ref.selector)
        )
        if len({capability.ref for capability in capabilities}) != len(
            capabilities
        ):
            raise BenchmarkPlanningError(
                "benchmark application metadata is invalid"
            )
        _lock_entries(locks)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "package_locks", locks)


def create_benchmark_plan(
    request: BenchmarkPlanRequest,
    application: ResolvedApplicationMetadata,
    payloads: Sequence[PortableCapabilityPayload],
) -> BenchmarkPlan:
    """Resolve one exact immutable plan without loading executable authority."""

    if not isinstance(request, BenchmarkPlanRequest) or not isinstance(
        application, ResolvedApplicationMetadata
    ):
        raise BenchmarkPlanningError("benchmark planning input is invalid")
    if request.application_ref != application.application_ref:
        raise BenchmarkPlanningError("benchmark application is invalid")

    payload_values = _payload_snapshot(payloads)
    _validate_locked_payloads(application.package_locks, payload_values)
    try:
        suite = resolve_benchmark_suite(request.suite_ref, payload_values)
        case_limit = (
            suite.default_case_limit
            if request.case_limit is None
            else request.case_limit
        )
        if case_limit > suite.default_case_limit:
            raise BenchmarkPlanningError("benchmark case limit is invalid")
        tasks = plan_benchmark_tasks(suite, application.capabilities)
        return BenchmarkPlan(
            run_id=f"benchmark-{uuid4().hex}",
            application_ref=application.application_ref,
            suite=suite,
            tasks=tasks,
            case_limit=case_limit,
            package_locks=application.package_locks,
        )
    except BenchmarkPlanningError:
        raise
    except (BenchmarkResolutionError, TypeError, ValueError):
        raise BenchmarkPlanningError("benchmark planning failed") from None


def render_benchmark_plan(plan: BenchmarkPlan) -> str:
    """Render only the allowlisted public plan fields as canonical JSON."""

    try:
        public = public_plan_dict(plan)
    except (TypeError, ValueError):
        raise BenchmarkPlanningError("benchmark plan is invalid") from None
    return (
        json.dumps(
            public,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _payload_snapshot(
    values: Sequence[PortableCapabilityPayload],
) -> tuple[PortableCapabilityPayload, ...]:
    if isinstance(values, (str, bytes)):
        raise BenchmarkPlanningError("benchmark package payloads are invalid")
    try:
        payloads = tuple(values)
    except TypeError:
        raise BenchmarkPlanningError(
            "benchmark package payloads are invalid"
        ) from None
    if not payloads or any(
        not isinstance(payload, PortableCapabilityPayload)
        for payload in payloads
    ):
        raise BenchmarkPlanningError("benchmark package payloads are invalid")
    package_refs = tuple(payload.manifest.package_ref for payload in payloads)
    if len(set(package_refs)) != len(package_refs):
        raise BenchmarkPlanningError("benchmark package payloads are invalid")
    return tuple(
        sorted(
            payloads,
            key=lambda payload: (
                payload.manifest.package_ref.package_id,
                payload.manifest.package_ref.version,
            ),
        )
    )


def _validate_locked_payloads(
    locks: tuple[CapabilitySourceLock, ...],
    payloads: tuple[PortableCapabilityPayload, ...],
) -> None:
    locked = {
        entry.package_ref: entry.payload_sha256
        for entry in _lock_entries(locks)
    }
    actual = {
        payload.manifest.package_ref: payload.payload_sha256
        for payload in payloads
    }
    if locked != actual:
        raise BenchmarkPlanningError("benchmark package locks are invalid")


def _lock_entries(
    locks: tuple[CapabilitySourceLock, ...],
) -> tuple[CapabilitySourceLockEntry, ...]:
    entries: list[CapabilitySourceLockEntry] = []
    package_refs: set[CapabilityPackageRef] = set()
    for lock in locks:
        if not isinstance(lock.entries, tuple) or not lock.entries:
            raise BenchmarkPlanningError(
                "benchmark application metadata is invalid"
            )
        for entry in lock.entries:
            if (
                not isinstance(entry, CapabilitySourceLockEntry)
                or not isinstance(entry.package_ref, CapabilityPackageRef)
                or entry.package_ref in package_refs
                or not isinstance(entry.payload_sha256, str)
                or _SHA256.fullmatch(entry.payload_sha256) is None
                or not isinstance(entry.source_id, str)
                or _IDENTIFIER.fullmatch(entry.source_id) is None
            ):
                raise BenchmarkPlanningError(
                    "benchmark application metadata is invalid"
                )
            entries.append(entry)
            package_refs.add(entry.package_ref)
    return tuple(entries)


def _snapshot(
    values: Iterable[_Value],
    error: str,
) -> tuple[_Value, ...]:
    if isinstance(values, (str, bytes)):
        raise BenchmarkPlanningError(error)
    try:
        return tuple(values)
    except TypeError:
        raise BenchmarkPlanningError(error) from None


def _valid_application_ref(value: object) -> bool:
    return (
        isinstance(value, ApplicationRef)
        and isinstance(value.application_id, str)
        and _IDENTIFIER.fullmatch(value.application_id) is not None
        and isinstance(value.version, str)
        and _VERSION.fullmatch(value.version) is not None
    )
