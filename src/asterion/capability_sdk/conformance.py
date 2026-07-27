"""Provider-free conformance checks for installed capability packages."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    EXECUTABLE_CAPABILITY_KINDS,
    CapabilityImplementationBinding,
)
from asterion.capabilities.protocol import validate_capability_manifest
from asterion.capability_packages.model import (
    SOURCE_KINDS,
    BenchmarkTaskBinding,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteManifest,
    CapabilityPackageRef,
    validate_benchmark_suite_manifest,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFORMANCE_CASES = frozenset(
    {
        "explicit-local-source",
        "manifest-closure",
        "metadata-only-discovery",
        "portable-identity",
    }
)
_FAILURE = "capability package conformance failed"


def run_capability_conformance(
    installed: InstalledCapabilityPackage,
) -> None:
    """Validate one installed package without invoking providers or runtimes."""

    try:
        _run_capability_conformance(installed)
    except Exception:
        raise ValueError(_FAILURE) from None


def _run_capability_conformance(
    installed: InstalledCapabilityPackage,
) -> None:
    if (
        type(installed) is not InstalledCapabilityPackage
        or type(installed.package_ref) is not CapabilityPackageRef
        or type(installed.payload_sha256) is not str
        or _SHA256.fullmatch(installed.payload_sha256) is None
        or type(installed.source_id) is not str
        or not installed.source_id
        or type(installed.source_kind) is not str
        or installed.source_kind not in SOURCE_KINDS
        or type(installed.catalog_roots) is not tuple
        or len(installed.catalog_roots) != 1
        or type(installed.benchmark_suite_paths) is not tuple
        or type(installed.implementations) is not tuple
        or type(installed.benchmark_bindings) is not tuple
    ):
        raise TypeError

    catalog_root = _canonical_path(installed.catalog_roots[0], directory=True)
    if catalog_root.name != "capabilities":
        raise ValueError
    payload_root = catalog_root.parent
    if catalog_root != payload_root / "capabilities":
        raise ValueError

    payload = open_portable_payload(payload_root)
    if (
        payload.manifest.package_ref != installed.package_ref
        or payload.payload_sha256 != installed.payload_sha256
    ):
        raise ValueError

    snapshot = Path(str(payload.resource_root))
    capability_manifests = tuple(
        sorted(
            (
                validate_capability_manifest(_load_json(path))
                for path in (snapshot / "capabilities").glob("*.json")
            ),
            key=lambda manifest: (
                str(manifest["capability_id"]),
                str(manifest["version"]),
            ),
        )
    )
    capability_refs = tuple(
        CapabilityRef(
            str(manifest["capability_id"]),
            str(manifest["version"]),
        )
        for manifest in capability_manifests
    )
    if capability_refs != payload.manifest.capabilities:
        raise ValueError

    suite_manifests = tuple(
        sorted(
            (
                validate_benchmark_suite_manifest(_load_json(path))
                for path in (snapshot / "benchmark-suites").glob("*.json")
            ),
            key=lambda suite: suite.suite_ref,
        )
    )
    if tuple(suite.suite_ref for suite in suite_manifests) != (
        payload.manifest.benchmark_suites
    ) or any(
        task.capability not in payload.manifest.capabilities
        for suite in suite_manifests
        for task in suite.tasks
    ):
        raise ValueError
    _validate_suite_paths(
        installed.benchmark_suite_paths,
        payload_root=payload_root,
        suite_count=len(suite_manifests),
    )
    _validate_capability_bindings(
        installed.implementations,
        capability_manifests,
    )
    _validate_benchmark_bindings(
        installed.benchmark_bindings,
        suite_manifests,
        package_ref=installed.package_ref,
    )
    _validate_conformance_profile(
        snapshot / "conformance/profile.json",
        source_kind=installed.source_kind,
    )


def _validate_suite_paths(
    values: tuple[Path, ...],
    *,
    payload_root: Path,
    suite_count: int,
) -> None:
    if len(values) != suite_count:
        raise ValueError
    suite_root = payload_root / "benchmark-suites"
    canonical = tuple(_canonical_path(path, directory=False) for path in values)
    if (
        len(set(canonical)) != len(canonical)
        or tuple(sorted(canonical)) != canonical
        or any(path.parent != suite_root or path.suffix != ".json" for path in canonical)
    ):
        raise ValueError


def _validate_capability_bindings(
    bindings: tuple[CapabilityImplementationBinding, ...],
    manifests: tuple[Mapping[str, object], ...],
) -> None:
    expected = tuple(
        CapabilityRef(
            str(manifest["capability_id"]),
            str(manifest["version"]),
        )
        for manifest in manifests
        if manifest["kind"] in EXECUTABLE_CAPABILITY_KINDS
    )
    observed: list[CapabilityRef] = []
    for binding in bindings:
        if (
            type(binding) is not CapabilityImplementationBinding
            or type(binding.capability_ref) is not CapabilityRef
            or not callable(getattr(binding.implementation, "execute", None))
        ):
            raise TypeError
        observed.append(binding.capability_ref)
    if tuple(sorted(observed)) != expected or len(set(observed)) != len(observed):
        raise ValueError


def _validate_benchmark_bindings(
    bindings: tuple[BenchmarkTaskBinding, ...],
    suites: tuple[BenchmarkSuiteManifest, ...],
    *,
    package_ref: CapabilityPackageRef,
) -> None:
    expected = {
        task.binding_id
        for suite in suites
        for task in suite.tasks
    }
    observed: list[str] = []
    for binding in bindings:
        if (
            type(binding) is not BenchmarkTaskBinding
            or binding.owner_package != package_ref
            or type(binding.binding_id) is not str
            or not binding.binding_id
            or binding.implementation is None
        ):
            raise TypeError
        observed.append(binding.binding_id)
    if set(observed) != expected or len(set(observed)) != len(observed):
        raise ValueError


def _validate_conformance_profile(path: Path, *, source_kind: str) -> None:
    profile = _load_json(path)
    if (
        not isinstance(profile, Mapping)
        or profile.keys() != {"case_ids", "profile"}
        or type(profile["profile"]) is not str
        or not profile["profile"]
        or type(profile["case_ids"]) is not list
        or not profile["case_ids"]
        or any(type(case_id) is not str for case_id in profile["case_ids"])
    ):
        raise ValueError
    case_ids = tuple(profile["case_ids"])
    if (
        case_ids != tuple(sorted(set(case_ids)))
        or not set(case_ids) <= _CONFORMANCE_CASES
        or (
            "explicit-local-source" in case_ids
            and source_kind != "local-directory"
        )
        or (
            "metadata-only-discovery" in case_ids
            and source_kind != "python-distribution"
        )
    ):
        raise ValueError


def _canonical_path(value: object, *, directory: bool) -> Path:
    if not isinstance(value, Path):
        raise TypeError
    resolved = value.resolve(strict=True)
    if value != resolved or value.is_symlink():
        raise ValueError
    if directory and not resolved.is_dir():
        raise ValueError
    if not directory and (not resolved.is_file() or resolved.is_symlink()):
        raise ValueError
    return resolved


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)
