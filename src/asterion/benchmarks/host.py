"""Host-owned metadata planning for installed benchmark suites."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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
    CapabilitySourceLock,
    InstalledCapabilityPackage,
    PreparedCapabilityPackage,
    prepare_capability_source,
    validate_capability_source_lock,
)
from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.sources.base import CapabilityPackageSource
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


class _MaterializedBenchmarkRoot:
    __slots__ = ("path",)

    def __init__(self) -> None:
        self.path: Path | None = Path(
            tempfile.mkdtemp(prefix="asterion-benchmark-resolution-")
        ).resolve(strict=True)

    def cleanup(self) -> None:
        path = self.path
        self.path = None
        if path is not None:
            shutil.rmtree(path, ignore_errors=True)

    def __del__(self) -> None:
        self.cleanup()


@dataclass(frozen=True, slots=True)
class InstalledBenchmarkResolution:
    """Selected application and metadata-only package snapshots."""

    application: InstalledApplication
    packages: tuple[InstalledCapabilityPackage, ...]
    _prepared_packages: tuple[PreparedCapabilityPackage, ...] = field(
        repr=False, compare=False
    )
    _materialization: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        packages = tuple(self.packages)
        try:
            prepared_packages = tuple(self._prepared_packages)
        except Exception:
            _fail()
        if (
            not isinstance(self.application, InstalledApplication)
            or not packages
            or not all(
                isinstance(package, InstalledCapabilityPackage)
                and not package.implementations
                and not package.benchmark_bindings
                for package in packages
            )
            or len(prepared_packages) != len(packages)
            or not all(
                type(prepared) is PreparedCapabilityPackage
                and prepared.candidate.package_ref == package.package_ref
                and prepared.candidate.source_id == package.source_id
                and prepared.candidate.source_kind == package.source_kind
                and prepared.candidate.payload_sha256 == package.payload_sha256
                for package, prepared in zip(packages, prepared_packages, strict=True)
            )
        ):
            _fail()
        object.__setattr__(self, "packages", packages)
        object.__setattr__(self, "_prepared_packages", prepared_packages)


def resolve_installed_benchmark(
    *,
    application_ref: ApplicationRef,
    source_lock_path: Path | None = None,
    application_index_entry_points: Iterable[object] | None = None,
    application_entry_points: Iterable[object] | None = None,
    runtime_factories: RuntimeFactoryRegistry | None = None,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
) -> InstalledBenchmarkResolution:
    """Resolve one installed application over retained metadata snapshots."""

    materialization: _MaterializedBenchmarkRoot | None = None
    try:
        if not isinstance(application_ref, ApplicationRef):
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
        materialization = _MaterializedBenchmarkRoot()
        assert materialization.path is not None
        packages, prepared_packages = _metadata_packages(
            metadata_application,
            sources=sources,
            source_lock=source_lock,
            materialization_root=materialization.path,
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
        resolution = InstalledBenchmarkResolution(
            application=application,
            packages=packages,
            _prepared_packages=prepared_packages,
            _materialization=materialization,
        )
        materialization = None
        return resolution
    except BenchmarkHostError:
        raise
    except Exception:
        _fail()
    finally:
        if materialization is not None:
            materialization.cleanup()


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
        resolution = resolve_installed_benchmark(
            application_ref=application_ref,
            source_lock_path=source_lock_path,
            application_index_entry_points=application_index_entry_points,
            application_entry_points=application_entry_points,
            runtime_factories=runtime_factories,
            package_sources=package_sources,
        )
        return create_benchmark_plan(
            BenchmarkPlanRequest(
                application_ref=application_ref,
                suite_ref=suite_ref,
                case_limit=case_limit,
                execute=False,
            ),
            resolution.application,
            resolution.packages,
        )
    except BenchmarkHostError:
        raise
    except Exception:
        _fail()


def _package_sources(
    values: Sequence[CapabilityPackageSource] | None,
) -> tuple[CapabilityPackageSource, ...]:
    if values is None:
        return (DistributionCapabilityPackageSource(),)
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
) -> tuple[
    tuple[InstalledCapabilityPackage, ...], tuple[PreparedCapabilityPackage, ...]
]:
    if source_lock is not None and {
        entry.package_ref for entry in source_lock.entries
    } != set(application.capability_packages):
        _fail()
    packages: list[InstalledCapabilityPackage] = []
    prepared_packages: list[PreparedCapabilityPackage] = []
    for package_ref in application.capability_packages:
        prepared = prepare_capability_source(package_ref, sources, source_lock)
        selected, payload = prepared.candidate, prepared.payload
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
        prepared_packages.append(prepared)
    return tuple(packages), tuple(prepared_packages)


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
    "InstalledBenchmarkResolution",
    "create_installed_benchmark_plan",
    "resolve_installed_benchmark",
)
