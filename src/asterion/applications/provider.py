"""Versioned immutable contract for installed application providers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from asterion.assembly.protocol import validate_assembly_manifest
from asterion.packages.catalog import PackageRef
from asterion.packages.execution import PackageImplementation
from asterion.applications.product import (
    InstalledCapabilityProduct,
    validate_capability_product,
)


APPLICATION_PROVIDER_PROTOCOL = "asterion.application-provider/v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)


class ApplicationProviderError(ValueError):
    """Raised when installed application metadata is unsafe or inconsistent."""


@dataclass(frozen=True)
class InstalledApplication:
    application_id: str
    version: str
    assembly_paths: tuple[Path, ...]
    catalog_roots: tuple[Path, ...]
    implementations: tuple[tuple[PackageRef, PackageImplementation], ...]
    runtime_ids: tuple[str, ...]


@dataclass(frozen=True)
class InstalledApplicationProvider:
    protocol: str
    provider_id: str
    resource_root: Path
    applications: tuple[InstalledApplication, ...]
    product: InstalledCapabilityProduct | None = None


def validate_installed_provider(
    value: InstalledApplicationProvider, *, selected_id: str
) -> InstalledApplicationProvider:
    """Validate and canonicalize one explicitly selected installed provider."""

    if not isinstance(value, InstalledApplicationProvider):
        raise ApplicationProviderError("installed application provider is invalid")
    if value.protocol != APPLICATION_PROVIDER_PROTOCOL:
        raise ApplicationProviderError("installed application provider protocol is invalid")
    if not _identifier(selected_id) or value.provider_id != selected_id:
        raise ApplicationProviderError("installed application provider identity is invalid")
    root = _canonical_resource(value.resource_root, kind="directory")
    if not value.applications or not isinstance(value.applications, tuple):
        raise ApplicationProviderError("installed application set is invalid")

    identities: set[tuple[str, str]] = set()
    applications: list[InstalledApplication] = []
    for application in value.applications:
        if not isinstance(application, InstalledApplication):
            raise ApplicationProviderError("installed application is invalid")
        identity = (application.application_id, application.version)
        if (
            not _identifier(application.application_id)
            or SEMANTIC_VERSION.fullmatch(application.version) is None
            or identity in identities
        ):
            raise ApplicationProviderError("installed application identity is invalid")
        identities.add(identity)
        applications.append(_validate_application(application, root=root))
    product = None
    if value.product is not None:
        try:
            product = validate_capability_product(value.product)
        except ValueError:
            raise ApplicationProviderError("installed capability product is invalid") from None
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id=selected_id,
        resource_root=root,
        applications=tuple(applications),
        product=product,
    )


def _validate_application(
    application: InstalledApplication, *, root: Path
) -> InstalledApplication:
    if not isinstance(application.assembly_paths, tuple) or not application.assembly_paths:
        raise ApplicationProviderError("installed application assemblies are invalid")
    if not isinstance(application.catalog_roots, tuple) or not application.catalog_roots:
        raise ApplicationProviderError("installed application catalogs are invalid")
    if not isinstance(application.implementations, tuple):
        raise ApplicationProviderError("installed application implementations are invalid")
    if (
        not isinstance(application.runtime_ids, tuple)
        or not application.runtime_ids
        or tuple(sorted(set(application.runtime_ids))) != application.runtime_ids
        or any(not _identifier(runtime_id) for runtime_id in application.runtime_ids)
    ):
        raise ApplicationProviderError("installed application runtimes are invalid")

    assemblies = tuple(
        _resource_beneath(path, root=root, kind="file")
        for path in application.assembly_paths
    )
    catalogs = tuple(
        _resource_beneath(path, root=root, kind="directory")
        for path in application.catalog_roots
    )
    refs: set[PackageRef] = set()
    implementations: list[tuple[PackageRef, PackageImplementation]] = []
    for binding in application.implementations:
        if (
            not isinstance(binding, tuple)
            or len(binding) != 2
            or not isinstance(binding[0], PackageRef)
            or binding[0] in refs
        ):
            raise ApplicationProviderError("installed application binding is invalid")
        refs.add(binding[0])
        implementations.append(binding)

    for assembly_path in assemblies:
        try:
            assembly = json.loads(assembly_path.read_text())
            validate_assembly_manifest(assembly)
        except Exception:
            raise ApplicationProviderError("installed application assembly is invalid") from None
        if (
            assembly["application_id"] != application.application_id
            or assembly["version"] != application.version
            or assembly["runtime_id"] not in application.runtime_ids
        ):
            raise ApplicationProviderError("installed application assembly identity is invalid")
        package_refs = {
            PackageRef(item["package_id"], item["version"])
            for item in assembly["packages"]
        }
        if not refs.issubset(package_refs):
            raise ApplicationProviderError("installed application binding is unavailable")

    return InstalledApplication(
        application_id=application.application_id,
        version=application.version,
        assembly_paths=assemblies,
        catalog_roots=catalogs,
        implementations=tuple(implementations),
        runtime_ids=application.runtime_ids,
    )


def _canonical_resource(value: Path, *, kind: str) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ApplicationProviderError("installed application resource is unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ApplicationProviderError("installed application resource is unavailable") from None
    if kind == "file" and not resolved.is_file():
        raise ApplicationProviderError("installed application resource is invalid")
    if kind == "directory" and not resolved.is_dir():
        raise ApplicationProviderError("installed application resource is invalid")
    return resolved


def _resource_beneath(value: Path, *, root: Path, kind: str) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ApplicationProviderError("installed application resource is unsafe")
    resolved = _canonical_resource(path, kind=kind)
    if not resolved.is_relative_to(root):
        raise ApplicationProviderError("installed application resource escapes its root")
    return resolved


def _identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None
