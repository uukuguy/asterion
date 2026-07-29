"""Provider-free capability package conformance checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from asterion.capabilities.catalog import CapabilityRef, discover_capabilities
from asterion.capabilities.execution import (
    EXECUTABLE_CAPABILITY_KINDS,
    CapabilityImplementationBinding,
)
from asterion.capability_packages.model import (
    BenchmarkTaskBinding,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteManifest,
    CapabilityPackageRef,
    validate_benchmark_suite_manifest,
)


_CONFORMANCE_EXECUTABLE_KINDS = EXECUTABLE_CAPABILITY_KINDS | frozenset({"research"})


@dataclass(frozen=True, slots=True)
class _CapabilityConformanceResult:
    passed: bool
    errors: tuple[str, ...]


def run_capability_conformance(installed: object) -> _CapabilityConformanceResult:
    """Validate a selected installed package without executing provider code."""

    try:
        errors = _conformance_errors(installed)
    except BaseException as error:
        if not isinstance(error, Exception):
            raise
        errors = ("installed package value is invalid",)
    unique_errors = tuple(dict.fromkeys(errors))
    return _CapabilityConformanceResult(
        passed=not unique_errors,
        errors=unique_errors,
    )


def _conformance_errors(installed: object) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        package_ref = _field(installed, "package_ref")
        payload_sha256 = _field(installed, "payload_sha256")
        source_kind = _field(installed, "source_kind")
        catalog_roots = tuple(cast(Iterable[object], _field(installed, "catalog_roots")))
        suite_paths = tuple(
            cast(Iterable[object], _field(installed, "benchmark_suite_paths"))
        )
        implementations = tuple(
            cast(Iterable[object], _field(installed, "implementations"))
        )
        benchmark_bindings = tuple(
            cast(Iterable[object], _field(installed, "benchmark_bindings"))
        )
    except BaseException as error:
        if not isinstance(error, Exception):
            raise
        return ("installed package value is invalid",)

    if not isinstance(package_ref, CapabilityPackageRef):
        return ("installed package value is invalid",)
    if source_kind not in {
        "archive",
        "builtin",
        "local-directory",
        "python-distribution",
        "registry",
    }:
        return ("installed package value is invalid",)

    payload_root = _payload_root(catalog_roots, suite_paths)
    payload = None
    if payload_root is None:
        errors.append("payload closure is invalid")
    else:
        try:
            payload = open_portable_payload(payload_root)
        except Exception:
            errors.append("payload closure is invalid")

    if payload is not None and payload_root is not None:
        if package_ref != payload.manifest.package_ref:
            errors.append("package identity does not match payload")
        if payload_sha256 != payload.payload_sha256:
            errors.append("payload digest does not match payload")
        if errors:
            return tuple(errors)
        errors.extend(_catalog_errors(catalog_roots, payload.manifest.capabilities))
        errors.extend(_benchmark_errors(suite_paths, package_ref, benchmark_bindings))
        errors.extend(_implementation_errors(payload_root, implementations))
        errors.extend(_conformance_vector_errors(payload))

    return tuple(errors)


def _field(value: object, name: str) -> object:
    return getattr(value, name)


def _payload_root(catalog_roots: tuple[object, ...], suite_paths: tuple[object, ...]) -> Path | None:
    parents: set[Path] = set()
    for root in catalog_roots:
        path = Path(cast(Any, root))
        if path.name != "capabilities":
            return None
        parents.add(path.parent)
    for root in suite_paths:
        path = Path(cast(Any, root))
        if path.name != "benchmark-suites":
            return None
        parents.add(path.parent)
    if len(parents) != 1:
        return None
    return next(iter(parents))


def _catalog_errors(
    catalog_roots: tuple[object, ...],
    expected: tuple[CapabilityRef, ...],
) -> tuple[str, ...]:
    try:
        catalog = discover_capabilities(
            tuple(Path(cast(Any, root)) for root in catalog_roots)
        )
        actual = tuple(entry.ref for entry in catalog.entries)
    except Exception:
        return ("capability catalog closure is invalid",)
    if tuple(sorted(actual)) != expected:
        return ("capability catalog closure is invalid",)
    return ()


def _implementation_errors(
    payload_root: Path,
    implementations: tuple[object, ...],
) -> tuple[str, ...]:
    manifests: list[Mapping[str, object]] = []
    try:
        for path in sorted((payload_root / "capabilities").glob("*.json")):
            manifests.append(json.loads(path.read_text()))
    except Exception:
        return ("capability catalog closure is invalid",)
    expected = {
        CapabilityRef(str(manifest["capability_id"]), str(manifest["version"]))
        for manifest in manifests
        if manifest.get("kind") in _CONFORMANCE_EXECUTABLE_KINDS
    }
    seen: set[CapabilityRef] = set()
    for binding in implementations:
        if not isinstance(binding, CapabilityImplementationBinding):
            return ("implementation binding is invalid",)
        ref = binding.capability_ref
        if ref in seen:
            return ("implementation binding is duplicated",)
        seen.add(ref)
    if missing := expected - seen:
        del missing
        return ("implementation binding is missing",)
    if unknown := seen - expected:
        del unknown
        return ("implementation binding is unknown",)
    return ()


def _benchmark_errors(
    suite_paths: tuple[object, ...],
    package_ref: CapabilityPackageRef,
    benchmark_bindings: tuple[object, ...],
) -> tuple[str, ...]:
    suites = _suite_manifests(suite_paths)
    if suites is None:
        return ("benchmark suite closure is invalid",)
    expected: set[str] = set()
    for suite in suites:
        if suite.owner_package != package_ref:
            return ("benchmark suite owner is invalid",)
        for task in suite.tasks:
            expected.add(task.binding_id)

    seen: set[str] = set()
    for binding in benchmark_bindings:
        if not isinstance(binding, BenchmarkTaskBinding):
            return ("benchmark binding is invalid",)
        if binding.owner_package != package_ref:
            return ("benchmark binding owner is invalid",)
        if binding.binding_id in seen:
            return ("benchmark binding is duplicated",)
        seen.add(binding.binding_id)
    if expected - seen:
        return ("benchmark binding is missing",)
    if seen - expected:
        return ("benchmark binding is unknown",)
    return ()


def _suite_manifests(suite_paths: tuple[object, ...]) -> tuple[BenchmarkSuiteManifest, ...] | None:
    suites: list[BenchmarkSuiteManifest] = []
    try:
        for suite_root in suite_paths:
            for path in sorted(Path(cast(Any, suite_root)).glob("*.json")):
                suites.append(validate_benchmark_suite_manifest(json.loads(path.read_text())))
    except Exception:
        return None
    return tuple(suites)


def _conformance_vector_errors(payload: PortableCapabilityPayload) -> tuple[str, ...]:
    try:
        manifest = payload.manifest
        root = payload.resource_root
        for resource in manifest.conformance:
            node = root.joinpath("conformance", resource.resource_id)
            value = json.loads(node.read_text())
            if set(value) != {"case_ids", "profile_id"}:
                return ("conformance vector is invalid",)
            profile_id = value["profile_id"]
            case_ids = value["case_ids"]
            if not isinstance(profile_id, str) or not profile_id:
                return ("conformance vector is invalid",)
            if (
                not isinstance(case_ids, list)
                or any(not isinstance(case_id, str) for case_id in case_ids)
                or case_ids != sorted(set(case_ids))
            ):
                return ("conformance vector is invalid",)
            if hashlib.sha256(node.read_bytes()).hexdigest() != resource.sha256:
                return ("conformance vector is invalid",)
    except Exception:
        return ("conformance vector is invalid",)
    return ()


__all__ = ("run_capability_conformance",)
