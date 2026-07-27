"""Immutable domain-neutral values for benchmark planning and execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from asterion.applications.selection import ApplicationSelector
from asterion.capabilities.catalog import CatalogEntry
from asterion.capability_packages.model import BenchmarkTaskBinding
from asterion.capability_packages.protocol import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    BenchmarkTaskManifest,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_PUBLIC_ARGUMENT = re.compile(
    r"^(?:--)?[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Plans 1 and 2 already provide these exact provider-neutral values. Benchmark
# code gives them intent-specific names without creating parallel identities.
ApplicationRef = ApplicationSelector
ResolvedCapability = CatalogEntry


@dataclass(frozen=True, slots=True)
class BenchmarkTaskRequest:
    """Private host request passed to one selected task implementation."""

    run_id: str
    suite_ref: BenchmarkSuiteRef
    task_id: str
    case_limit: int
    output_directory: Path = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not _safe_run_id(self.run_id)
            or not isinstance(self.suite_ref, BenchmarkSuiteRef)
            or not _identifier(self.task_id)
            or type(self.case_limit) is not int
            or self.case_limit <= 0
            or not isinstance(self.output_directory, Path)
        ):
            raise ValueError("benchmark task request is invalid")
        object.__setattr__(
            self,
            "output_directory",
            Path(self.output_directory),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkTaskInvocation:
    """One immutable invocation with an explicitly private provider payload."""

    task_id: str
    binding_id: str
    public_arguments: tuple[str, ...]
    private_payload: object = field(repr=False)

    def __post_init__(self) -> None:
        arguments = _tuple_snapshot(
            self.public_arguments,
            error="benchmark public arguments are invalid",
        )
        if (
            not _identifier(self.task_id)
            or not _identifier(self.binding_id)
            or any(
                not isinstance(argument, str)
                or _PUBLIC_ARGUMENT.fullmatch(argument) is None
                for argument in arguments
            )
        ):
            raise ValueError("benchmark public arguments are invalid")
        object.__setattr__(self, "public_arguments", arguments)


@runtime_checkable
class BenchmarkTaskImplementation(Protocol):
    """Selected-provider protocol for building one private invocation."""

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation: ...


@dataclass(frozen=True, slots=True)
class PlannedBenchmarkTask:
    """One provider-free task selected from suite metadata."""

    ordinal: int
    task: BenchmarkTaskManifest
    capability: ResolvedCapability = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or self.ordinal <= 0
            or not isinstance(self.task, BenchmarkTaskManifest)
            or not isinstance(self.capability, ResolvedCapability)
            or self.capability.ref != self.task.capability
        ):
            raise ValueError("planned benchmark task is invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkPlan:
    """Provider-free exact benchmark plan safe for public rendering."""

    run_id: str
    application_ref: ApplicationRef
    suite: BenchmarkSuiteManifest
    tasks: tuple[PlannedBenchmarkTask, ...]
    case_limit: int
    package_locks: tuple[CapabilitySourceLock, ...]

    def __post_init__(self) -> None:
        tasks = _tuple_snapshot(
            self.tasks,
            error="benchmark plan tasks are invalid",
        )
        if any(not isinstance(task, PlannedBenchmarkTask) for task in tasks):
            raise ValueError("benchmark plan tasks are invalid")
        tasks = tuple(sorted(tasks, key=lambda task: task.ordinal))
        locks = _canonical_locks(self.package_locks)

        if (
            not _safe_run_id(self.run_id)
            or not isinstance(self.application_ref, ApplicationRef)
            or not isinstance(self.suite, BenchmarkSuiteManifest)
            or type(self.case_limit) is not int
            or self.case_limit <= 0
            or self.case_limit > self.suite.default_case_limit
        ):
            raise ValueError("benchmark plan is invalid")

        ordinals = tuple(task.ordinal for task in tasks)
        task_ids = tuple(task.task.task_id for task in tasks)
        if (
            ordinals != tuple(range(1, len(tasks) + 1))
            or len(set(task_ids)) != len(task_ids)
            or tuple(task.task for task in tasks) != self.suite.tasks
        ):
            raise ValueError("benchmark plan tasks are invalid")

        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "package_locks", locks)


@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkTask:
    """One planned task paired with its selected opaque binding."""

    planned: PlannedBenchmarkTask
    binding: BenchmarkTaskBinding

    def __post_init__(self) -> None:
        if not isinstance(
            self.planned, PlannedBenchmarkTask
        ) or not isinstance(self.binding, BenchmarkTaskBinding):
            raise ValueError("resolved benchmark task is invalid")


@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkPlan:
    """Private execution preparation with complete exact implementations."""

    plan: BenchmarkPlan
    tasks: tuple[ResolvedBenchmarkTask, ...]

    def __post_init__(self) -> None:
        tasks = _tuple_snapshot(
            self.tasks,
            error="resolved benchmark plan is invalid",
        )
        if any(not isinstance(task, ResolvedBenchmarkTask) for task in tasks):
            raise ValueError("resolved benchmark plan is invalid")
        tasks = tuple(sorted(tasks, key=lambda task: task.planned.ordinal))
        if (
            not isinstance(self.plan, BenchmarkPlan)
            or tuple(task.planned for task in tasks) != self.plan.tasks
            or any(
                task.binding.binding_id != task.planned.task.binding_id
                or task.binding.owner_package != self.plan.suite.owner_package
                or not _is_task_implementation(
                    task.binding.implementation,
                )
                for task in tasks
            )
        ):
            raise ValueError("resolved benchmark plan is invalid")
        object.__setattr__(self, "tasks", tasks)


def public_plan_dict(plan: BenchmarkPlan) -> dict[str, object]:
    """Return the allowlisted path- and provider-free plan projection."""

    if not isinstance(plan, BenchmarkPlan):
        raise ValueError("benchmark plan is invalid")
    return {
        "run_id": plan.run_id,
        "application": (
            f"{plan.application_ref.application_id}@"
            f"{plan.application_ref.version}"
        ),
        "suite": plan.suite.suite_ref.selector,
        "case_limit": plan.case_limit,
        "tasks": [
            {
                "ordinal": task.ordinal,
                "task_id": task.task.task_id,
                "capability": task.capability.ref.selector,
                "binding_id": task.task.binding_id,
            }
            for task in plan.tasks
        ],
    }


def _canonical_locks(
    values: object,
) -> tuple[CapabilitySourceLock, ...]:
    locks = _tuple_snapshot(
        values,
        error="benchmark plan package locks are invalid",
    )
    normalized: list[CapabilitySourceLock] = []
    package_refs: set[object] = set()
    for lock in locks:
        if not isinstance(lock, CapabilitySourceLock):
            raise ValueError("benchmark plan package locks are invalid")
        entries = _tuple_snapshot(
            lock.entries,
            error="benchmark plan package locks are invalid",
        )
        if not entries or any(
            not isinstance(entry, CapabilitySourceLockEntry)
            for entry in entries
        ):
            raise ValueError("benchmark plan package locks are invalid")
        entries = tuple(
            sorted(
                entries,
                key=lambda entry: (
                    entry.package_ref.package_id,
                    entry.package_ref.version,
                    entry.payload_sha256,
                    entry.source_id,
                ),
            )
        )
        for entry in entries:
            if (
                entry.package_ref in package_refs
                or _SHA256.fullmatch(entry.payload_sha256) is None
                or not _identifier(entry.source_id)
            ):
                raise ValueError("benchmark plan package locks are invalid")
            package_refs.add(entry.package_ref)
        normalized.append(CapabilitySourceLock(entries=entries))
    return tuple(
        sorted(
            normalized,
            key=lambda lock: tuple(
                (
                    entry.package_ref.package_id,
                    entry.package_ref.version,
                    entry.payload_sha256,
                    entry.source_id,
                )
                for entry in lock.entries
            ),
        )
    )


def _tuple_snapshot(value: object, *, error: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(error)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(error) from None


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _safe_run_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and "\x00" not in value
        and "\n" not in value
        and "\r" not in value
    )


def _is_task_implementation(value: object) -> bool:
    try:
        build_invocation = getattr(value, "build_invocation")
    except Exception:
        return False
    return isinstance(
        value, BenchmarkTaskImplementation
    ) and callable(build_invocation)
