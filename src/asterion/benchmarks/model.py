"""Immutable public values for generic benchmark planning."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.model import BenchmarkTaskBinding
from asterion.capability_packages.protocol import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    BenchmarkTaskManifest,
    CapabilitySourceLock,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)


class BenchmarkModelError(ValueError):
    """Raised when generic benchmark runtime values are malformed."""


@dataclass(frozen=True, order=True, slots=True)
class ApplicationRef:
    application_id: str
    version: str

    def __post_init__(self) -> None:
        _validate_identifier(self.application_id, "benchmark application is invalid")
        _validate_version(self.version, "benchmark application is invalid")

    @property
    def selector(self) -> str:
        return f"{self.application_id}@{self.version}"

    def __str__(self) -> str:
        return self.selector


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    ref: CapabilityRef
    manifest: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.ref, CapabilityRef) or not isinstance(
            self.manifest, Mapping
        ):
            raise BenchmarkModelError("resolved benchmark capability is invalid")
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))


@dataclass(frozen=True, slots=True)
class BenchmarkTaskRequest:
    run_id: str
    suite_ref: BenchmarkSuiteRef
    task_id: str
    case_limit: int
    output_directory: Path = field(repr=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.run_id, "benchmark task request is invalid")
        if not isinstance(self.suite_ref, BenchmarkSuiteRef):
            raise BenchmarkModelError("benchmark task request is invalid")
        _validate_identifier(self.task_id, "benchmark task request is invalid")
        _validate_positive_int(self.case_limit, "benchmark task request is invalid")
        if not isinstance(self.output_directory, Path):
            raise BenchmarkModelError("benchmark task request is invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkTaskInvocation:
    task_id: str
    binding_id: str
    public_arguments: tuple[str, ...]
    private_payload: object = field(repr=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.task_id, "benchmark task invocation is invalid")
        _validate_identifier(self.binding_id, "benchmark task invocation is invalid")
        public_arguments = tuple(self.public_arguments)
        if not all(type(argument) is str for argument in public_arguments):
            raise BenchmarkModelError("benchmark task invocation is invalid")
        object.__setattr__(self, "public_arguments", public_arguments)


@runtime_checkable
class BenchmarkTaskImplementation(Protocol):
    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation: ...


@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkTask:
    ordinal: int
    task: BenchmarkTaskManifest
    capability: ResolvedCapability
    binding: BenchmarkTaskBinding

    def __post_init__(self) -> None:
        _validate_positive_int(self.ordinal, "resolved benchmark task is invalid")
        if (
            not isinstance(self.task, BenchmarkTaskManifest)
            or not isinstance(self.capability, ResolvedCapability)
            or not isinstance(self.binding, BenchmarkTaskBinding)
            or self.task.capability != self.capability.ref
            or self.task.binding_id != self.binding.binding_id
        ):
            raise BenchmarkModelError("resolved benchmark task is invalid")


@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkPlan:
    run_id: str
    application_ref: ApplicationRef
    suite: BenchmarkSuiteManifest
    tasks: tuple[ResolvedBenchmarkTask, ...]
    case_limit: int
    package_locks: tuple[CapabilitySourceLock, ...]

    def __post_init__(self) -> None:
        _validate_identifier(self.run_id, "resolved benchmark plan is invalid")
        if (
            not isinstance(self.application_ref, ApplicationRef)
            or not isinstance(self.suite, BenchmarkSuiteManifest)
        ):
            raise BenchmarkModelError("resolved benchmark plan is invalid")
        _validate_positive_int(self.case_limit, "resolved benchmark plan is invalid")
        tasks = tuple(self.tasks)
        package_locks = tuple(self.package_locks)
        if not all(isinstance(task, ResolvedBenchmarkTask) for task in tasks):
            raise BenchmarkModelError("resolved benchmark plan is invalid")
        if not all(isinstance(lock, CapabilitySourceLock) for lock in package_locks):
            raise BenchmarkModelError("resolved benchmark plan is invalid")
        expected_ordinals = tuple(range(1, len(tasks) + 1))
        if tuple(task.ordinal for task in tasks) != expected_ordinals:
            raise BenchmarkModelError("resolved benchmark plan task order is invalid")
        task_ids = tuple(task.task.task_id for task in tasks)
        if len(set(task_ids)) != len(task_ids):
            raise BenchmarkModelError("resolved benchmark plan task set is invalid")
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "package_locks", package_locks)


def public_plan_dict(plan: ResolvedBenchmarkPlan) -> dict[str, object]:
    """Return a body-free public projection of a resolved benchmark plan."""

    if not isinstance(plan, ResolvedBenchmarkPlan):
        raise BenchmarkModelError("resolved benchmark plan is invalid")
    return {
        "run_id": plan.run_id,
        "application": plan.application_ref.selector,
        "suite": _suite_selector(plan.suite.suite_ref),
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


def _suite_selector(ref: BenchmarkSuiteRef) -> str:
    return f"{ref.suite_id}@{ref.version}"


def _validate_identifier(value: object, message: str) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise BenchmarkModelError(message)


def _validate_version(value: object, message: str) -> None:
    if type(value) is not str or _SEMANTIC_VERSION.fullmatch(value) is None:
        raise BenchmarkModelError(message)


def _validate_positive_int(value: object, message: str) -> None:
    if type(value) is not int or value < 1:
        raise BenchmarkModelError(message)


__all__ = (
    "ApplicationRef",
    "BenchmarkModelError",
    "BenchmarkTaskImplementation",
    "BenchmarkTaskInvocation",
    "BenchmarkTaskRequest",
    "ResolvedBenchmarkPlan",
    "ResolvedBenchmarkTask",
    "ResolvedCapability",
    "public_plan_dict",
)
