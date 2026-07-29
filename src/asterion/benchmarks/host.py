"""Host-owned metadata planning for installed benchmark suites."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NoReturn

from asterion.applications import (
    InstalledApplication,
    compose_installed_provider,
    load_application_provider,
    select_application_provider_id,
)
from asterion.applications.selection import (
    ApplicationSelector,
    select_installed_application,
)
from asterion.benchmarks.model import ApplicationRef, ResolvedBenchmarkPlan
from asterion.benchmarks.planning import (
    BenchmarkPlanRequest,
    create_benchmark_plan,
)
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    CapabilityPackageCandidate,
    CapabilitySourceLock,
    InstalledCapabilityPackage,
    resolve_capability_source,
    validate_capability_source_lock,
)
from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryRegistry


_SOURCE_LOCK_MAX_BYTES = 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class BenchmarkHostError(ValueError):
    """Raised when host-owned benchmark metadata cannot be resolved safely."""


def create_installed_benchmark_plan(
    *,
    application_ref: ApplicationRef,
    suite_ref: BenchmarkSuiteRef,
    case_limit: int | None,
    source_lock_path: Path | None = None,
    application_index_entry_points: Iterable[object] | None = None,
    application_entry_points: Iterable[object] | None = None,
    runtime_factories: RuntimeFactoryRegistry | None = None,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
) -> ResolvedBenchmarkPlan:
    """Create a typed plan without loading capability implementation providers."""

    try:
        if not isinstance(application_ref, ApplicationRef) or not isinstance(
            suite_ref, BenchmarkSuiteRef
        ):
            _fail()
        provider_id = select_application_provider_id(
            application_ref,
            application_entry_points=application_index_entry_points,
            provider_entry_points=application_entry_points,
        )
        metadata_provider = load_application_provider(
            provider_id,
            entry_points=application_entry_points,
        )
        metadata_application = select_installed_application(
            metadata_provider,
            ApplicationSelector(
                application_id=application_ref.application_id,
                version=application_ref.version,
            ),
        )
        source_lock = _read_source_lock(source_lock_path)
        sources = _package_sources(package_sources)
        with tempfile.TemporaryDirectory(prefix="asterion-benchmark-plan-") as temp:
            packages = _metadata_packages(
                metadata_application,
                sources=sources,
                source_lock=source_lock,
                materialization_root=Path(temp),
            )
            provider = compose_installed_provider(
                metadata_provider,
                runtime_factories=(
                    default_runtime_factory_registry()
                    if runtime_factories is None
                    else runtime_factories
                ),
                installed_packages=packages,
            )
            application = select_installed_application(
                provider,
                ApplicationSelector(
                    application_id=application_ref.application_id,
                    version=application_ref.version,
                ),
            )
            return create_benchmark_plan(
                BenchmarkPlanRequest(
                    application_ref=application_ref,
                    suite_ref=suite_ref,
                    case_limit=case_limit,
                    execute=False,
                ),
                application,
                packages,
            )
    except BenchmarkHostError:
        raise
    except Exception:
        _fail()


def _package_sources(
    values: Sequence[CapabilityPackageSource] | None,
) -> tuple[CapabilityPackageSource, ...]:
    if values is None:
        return (
            BuiltinCapabilitySource(),
            DistributionCapabilityPackageSource(),
        )
    try:
        sources = tuple(values)
    except Exception:
        _fail()
    if not sources:
        _fail()
    for source in sources:
        if not all(
            callable(getattr(source, method, None))
            for method in (
                "discover_metadata",
                "open_payload",
                "validate_source_identity",
                "load_provider",
            )
        ):
            _fail()
    return sources


def _metadata_packages(
    application: InstalledApplication,
    *,
    sources: tuple[CapabilityPackageSource, ...],
    source_lock: CapabilitySourceLock | None,
    materialization_root: Path,
) -> tuple[InstalledCapabilityPackage, ...]:
    if source_lock is not None and {
        entry.package_ref for entry in source_lock.entries
    } != set(application.capability_packages):
        _fail()
    records: list[
        tuple[CapabilityPackageSource, CapabilityPackageCandidate, PortableCapabilityPayload]
    ] = []
    for source in sources:
        candidates = source.discover_metadata()
        for candidate in candidates:
            if candidate.package_ref not in application.capability_packages:
                continue
            payload = source.open_payload(candidate)
            source.validate_source_identity(candidate, payload)
            records.append(
                (
                    source,
                    CapabilityPackageCandidate(
                        package_ref=candidate.package_ref,
                        source_id=candidate.source_id,
                        source_kind=candidate.source_kind,
                        payload_sha256=payload.payload_sha256,
                        metadata=candidate.metadata,
                    ),
                    payload,
                )
            )
    packages: list[InstalledCapabilityPackage] = []
    for package_ref in application.capability_packages:
        candidates = tuple(
            candidate for _, candidate, _ in records if candidate.package_ref == package_ref
        )
        selected = resolve_capability_source(package_ref, candidates, source_lock)
        matches = tuple(
            (source, payload)
            for source, candidate, payload in records
            if candidate == selected
        )
        if len(matches) != 1:
            _fail()
        _, payload = matches[0]
        root = _materialize_payload(
            payload,
            materialization_root / f"package-{len(packages) + 1}",
        )
        packages.append(
            InstalledCapabilityPackage(
                package_ref=package_ref,
                payload_sha256=payload.payload_sha256,
                source_id=selected.source_id,
                source_kind=selected.source_kind,
                catalog_roots=(root / "capabilities",),
                benchmark_suite_paths=(
                    (root / "benchmark-suites",)
                    if payload.manifest.benchmark_suites
                    else ()
                ),
                implementations=(),
                benchmark_bindings=(),
            )
        )
    return tuple(packages)


def _materialize_payload(payload: PortableCapabilityPayload, root: Path) -> Path:
    try:
        root.mkdir(mode=0o700)
        for directory_name in ("capabilities", "benchmark-suites"):
            source = payload.resource_root.joinpath(directory_name)
            if not source.is_dir():
                continue
            target = root / directory_name
            target.mkdir(mode=0o700)
            children = tuple(source.iterdir())
            for child in children:
                if (
                    not child.is_file()
                    or child.name in {".", ".."}
                    or "/" in child.name
                    or "\\" in child.name
                ):
                    _fail()
                (target / child.name).write_bytes(child.read_bytes())
        resolved = root.resolve(strict=True)
    except BenchmarkHostError:
        raise
    except Exception:
        _fail()
    if not (resolved / "capabilities").is_dir():
        _fail()
    return resolved


def _read_source_lock(path: Path | None) -> CapabilitySourceLock | None:
    if path is None:
        return None
    if not isinstance(path, Path) or path.is_symlink():
        _fail()
    fd: int | None = None
    try:
        fd = os.open(
            path,
            os.O_RDONLY | int(_O_NOFOLLOW) | int(_O_CLOEXEC),
        )
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _SOURCE_LOCK_MAX_BYTES:
            _fail()
        content = os.read(fd, _SOURCE_LOCK_MAX_BYTES + 1)
        if len(content) > _SOURCE_LOCK_MAX_BYTES:
            _fail()
        return validate_capability_source_lock(json.loads(content.decode("utf-8")))
    except BenchmarkHostError:
        raise
    except Exception:
        _fail()
    finally:
        if fd is not None:
            os.close(fd)


def _fail() -> NoReturn:
    raise BenchmarkHostError("benchmark host planning is invalid") from None


__all__ = (
    "BenchmarkHostError",
    "create_installed_benchmark_plan",
)
