"""Exact closed-world benchmark suite and task resolution."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

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


_SUITE_FILE_MAX_BYTES = 1024 * 1024
_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", None)
_SUPPORTS_DIR_FD = getattr(os, "supports_dir_fd", frozenset())
_SUPPORTS_FD = getattr(os, "supports_fd", frozenset())
_SECURE_FD_AVAILABLE = (
    isinstance(_O_DIRECTORY, int)
    and isinstance(_O_NOFOLLOW, int)
    and isinstance(_O_CLOEXEC, int)
    and os.open in _SUPPORTS_DIR_FD
    and os.listdir in _SUPPORTS_FD
)


def _secure_fd_flags(
    o_directory: object,
    o_nofollow: object,
    o_cloexec: object,
) -> tuple[int | None, int | None]:
    if (
        not _SECURE_FD_AVAILABLE
        or not isinstance(o_directory, int)
        or not isinstance(o_nofollow, int)
        or not isinstance(o_cloexec, int)
    ):
        return None, None
    return (
        os.O_RDONLY | o_directory | o_nofollow | o_cloexec,
        os.O_RDONLY | o_nofollow | o_cloexec,
    )


_DIRECTORY_FLAGS, _FILE_FLAGS = _secure_fd_flags(
    _O_DIRECTORY,
    _O_NOFOLLOW,
    _O_CLOEXEC,
)


class BenchmarkResolutionError(ValueError):
    """Raised when generic benchmark resolution is ambiguous or incomplete."""


def resolve_benchmark_suite(
    suite_ref: BenchmarkSuiteRef,
    packages: Sequence[InstalledCapabilityPackage],
) -> BenchmarkSuiteManifest:
    """Resolve one exact suite ref from already installed capability packages."""

    if not isinstance(suite_ref, BenchmarkSuiteRef):
        _fail("benchmark suite resolution is invalid")
    index = _build_package_suite_index(packages, "benchmark suite resolution is invalid")
    suite = index.suites.get(suite_ref)
    if suite is None:
        _fail("benchmark suite resolution is invalid")
    return suite


def resolve_benchmark_tasks(
    suite: BenchmarkSuiteManifest,
    capabilities: Sequence[ResolvedCapability],
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[ResolvedBenchmarkTask, ...]:
    """Resolve benchmark task bindings for one selected suite."""

    if not isinstance(suite, BenchmarkSuiteManifest):
        _fail("benchmark task resolution is invalid")
    index = _build_package_suite_index(packages, "benchmark task resolution is invalid")
    declared_suite = index.suites.get(suite.suite_ref)
    if declared_suite != suite:
        _fail("benchmark task resolution is invalid")
    capability_map = _capability_map(capabilities)
    binding_map: dict[tuple[CapabilityPackageRef, str], BenchmarkTaskBinding] = {}
    for package in index.packages:
        for binding in package.benchmark_bindings:
            if (
                not isinstance(binding, BenchmarkTaskBinding)
                or binding.owner_package != package.package_ref
            ):
                _fail("benchmark task resolution is invalid")
            key = (binding.owner_package, binding.binding_id)
            if key in binding_map:
                _fail("benchmark task resolution is invalid")
            binding_map[key] = binding
    for binding in binding_map.values():
        if binding.binding_id not in index.known_bindings.get(
            binding.owner_package,
            frozenset(),
        ):
            _fail("benchmark task resolution is invalid")
    resolved: list[ResolvedBenchmarkTask] = []
    for ordinal, task in enumerate(suite.tasks, start=1):
        capability = capability_map.get(task.capability)
        binding = binding_map.get((suite.owner_package, task.binding_id))
        if capability is None or binding is None:
            _fail("benchmark task resolution is invalid")
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
            _fail("benchmark task resolution is invalid")
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class _PackageSuiteIndex:
    packages: tuple[InstalledCapabilityPackage, ...]
    suites: Mapping[BenchmarkSuiteRef, BenchmarkSuiteManifest]
    known_bindings: Mapping[CapabilityPackageRef, frozenset[str]]


def _build_package_suite_index(
    packages: Sequence[InstalledCapabilityPackage],
    message: str,
) -> _PackageSuiteIndex:
    package_values = _package_tuple(packages, message)
    seen_packages: set[CapabilityPackageRef] = set()
    suites: dict[BenchmarkSuiteRef, BenchmarkSuiteManifest] = {}
    known_bindings: dict[CapabilityPackageRef, set[str]] = {}
    for package in package_values:
        if package.package_ref in seen_packages:
            _fail(message)
        seen_packages.add(package.package_ref)
        for suite in _package_suites(package, message):
            if suite.owner_package != package.package_ref or suite.suite_ref in suites:
                _fail(message)
            suites[suite.suite_ref] = suite
            known_bindings.setdefault(package.package_ref, set()).update(
                task.binding_id for task in suite.tasks
            )
    return _PackageSuiteIndex(
        packages=package_values,
        suites=suites,
        known_bindings={
            package_ref: frozenset(binding_ids)
            for package_ref, binding_ids in known_bindings.items()
        },
    )


def _package_tuple(
    packages: Sequence[InstalledCapabilityPackage],
    message: str,
) -> tuple[InstalledCapabilityPackage, ...]:
    try:
        package_values = tuple(packages)
    except Exception:
        _fail(message)
    if not all(isinstance(package, InstalledCapabilityPackage) for package in package_values):
        _fail(message)
    return package_values


def _capability_map(
    capabilities: Sequence[ResolvedCapability],
) -> dict[CapabilityRef, ResolvedCapability]:
    try:
        capability_values = tuple(capabilities)
    except Exception:
        _fail("benchmark capability set is invalid")
    result: dict[CapabilityRef, ResolvedCapability] = {}
    for capability in capability_values:
        if not isinstance(capability, ResolvedCapability) or capability.ref in result:
            _fail("benchmark capability set is invalid")
        result[capability.ref] = capability
    return result


def _package_suites(
    package: InstalledCapabilityPackage,
    message: str,
) -> tuple[BenchmarkSuiteManifest, ...]:
    suites: list[BenchmarkSuiteManifest] = []
    for suite_root in package.benchmark_suite_paths:
        if not isinstance(suite_root, Path):
            _fail(message)
        try:
            suites.extend(_read_suite_root(suite_root, message))
        except BenchmarkResolutionError:
            raise
        except Exception:
            _fail(message)
    return tuple(suites)


def _read_suite_root(root: Path, message: str) -> tuple[BenchmarkSuiteManifest, ...]:
    if not _SECURE_FD_AVAILABLE:
        _fail(message)
    suites: list[BenchmarkSuiteManifest] = []
    root_fd = _open_directory_fd(root, message)
    try:
        try:
            children = sorted(os.listdir(root_fd))
        except Exception:
            _fail(message)
        for name in children:
            if not isinstance(name, str) or Path(name).suffix != ".json":
                continue
            if "/" in name or "\\" in name or name in {".", ".."}:
                _fail(message)
            fd: int | None = None
            try:
                if _FILE_FLAGS is None:
                    _fail(message)
                fd = os.open(name, _FILE_FLAGS, dir_fd=root_fd)
                suites.append(_read_suite_file(fd, message))
            except BenchmarkResolutionError:
                raise
            except Exception:
                _fail(message)
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
    finally:
        os.close(root_fd)
    return tuple(suites)


def _open_directory_fd(root: Path, message: str) -> int:
    if not _SECURE_FD_AVAILABLE or _DIRECTORY_FLAGS is None:
        _fail(message)
    try:
        raw_path = os.fspath(root)
    except Exception:
        _fail(message)
    path = Path(raw_path)
    parts = path.parts
    if not path.is_absolute() or not parts:
        _fail(message)
    try:
        fd = os.open(parts[0], _DIRECTORY_FLAGS)
    except Exception:
        _fail(message)
    try:
        for part in parts[1:]:
            if part in {"", ".", ".."} or "/" in part or "\\" in part:
                _fail(message)
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BenchmarkResolutionError:
        os.close(fd)
        raise
    except Exception:
        os.close(fd)
        _fail(message)


def _read_suite_file(fd: int, message: str) -> BenchmarkSuiteManifest:
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > _SUITE_FILE_MAX_BYTES:
            _fail(message)
        data = _read_bounded(fd, message)
        text = data.decode("utf-8", errors="strict")
        value = json.loads(text)
        return validate_benchmark_suite_manifest(value)
    except BenchmarkResolutionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, BenchmarkSuiteProtocolError):
        _fail(message)


def _read_bounded(fd: int, message: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(fd, min(65536, _SUITE_FILE_MAX_BYTES + 1 - total))
        except OSError:
            _fail(message)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > _SUITE_FILE_MAX_BYTES:
            _fail(message)
        chunks.append(chunk)


def _fail(message: str) -> NoReturn:
    raise BenchmarkResolutionError(message) from None


__all__ = (
    "BenchmarkResolutionError",
    "resolve_benchmark_suite",
    "resolve_benchmark_tasks",
)
