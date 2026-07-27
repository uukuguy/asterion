"""Versioned immutable contract for installed application providers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from asterion.assembly.protocol import (
    AssemblyError,
    AssemblyPlan,
    resolve_assembly,
    validate_assembly_manifest,
)
from asterion.capabilities.catalog import (
    CapabilityCatalogError,
    discover_capabilities,
)
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityImplementationBinding,
    validate_implementation_bindings,
)
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.applications.product import (
    InstalledCapabilityProduct,
    validate_capability_product,
)
from asterion.runtime.factory import RuntimeFactoryError, RuntimeFactoryRegistry


APPLICATION_PROVIDER_PROTOCOL = "asterion.application-provider/v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)


class ApplicationProviderError(ValueError):
    """Raised when installed application metadata is unsafe or inconsistent."""


@dataclass(frozen=True)
class InstalledAssembly:
    runtime_id: str
    path: Path
    plan: AssemblyPlan
    implementations: tuple[CapabilityImplementationBinding, ...]


@dataclass(frozen=True)
class InstalledApplication:
    application_id: str
    version: str
    assembly_paths: tuple[Path, ...]
    capability_packages: tuple[CapabilityPackageRef, ...]
    runtime_ids: tuple[str, ...]
    assemblies: tuple[InstalledAssembly, ...] = ()


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
    """Backward-compatible name for metadata-only provider validation."""

    return validate_installed_provider_metadata(value, selected_id=selected_id)


def validate_installed_provider_metadata(
    value: InstalledApplicationProvider, *, selected_id: str
) -> InstalledApplicationProvider:
    """Validate selected provider metadata without selecting runtime factories."""

    if not isinstance(value, InstalledApplicationProvider):
        raise ApplicationProviderError("installed application provider is invalid")
    if value.protocol != APPLICATION_PROVIDER_PROTOCOL:
        raise ApplicationProviderError(
            "installed application provider protocol is invalid"
        )
    if not _identifier(selected_id) or value.provider_id != selected_id:
        raise ApplicationProviderError(
            "installed application provider identity is invalid"
        )
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
        applications.append(_validate_application_metadata(application, root=root))
    product = None
    if value.product is not None:
        try:
            product = validate_capability_product(value.product)
        except ValueError:
            raise ApplicationProviderError(
                "installed capability product is invalid"
            ) from None
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id=selected_id,
        resource_root=root,
        applications=tuple(applications),
        product=product,
    )


def resolve_installed_provider(
    provider: InstalledApplicationProvider,
    *,
    installed_packages: tuple[InstalledCapabilityPackage, ...],
    runtime_factories: RuntimeFactoryRegistry,
) -> InstalledApplicationProvider:
    """Resolve every installed application into an exact executable closure."""

    composed = compose_installed_provider(
        provider,
        installed_packages=installed_packages,
        runtime_factories=runtime_factories,
    )
    try:
        for application in composed.applications:
            for assembly in application.assemblies:
                validate_implementation_bindings(
                    assembly.plan, assembly.implementations
                )
    except (CapabilityExecutionError, TypeError, ValueError):
        raise ApplicationProviderError(
            "installed application executable closure is invalid"
        ) from None
    return composed


def compose_installed_provider(
    provider: InstalledApplicationProvider,
    *,
    installed_packages: tuple[InstalledCapabilityPackage, ...],
    runtime_factories: RuntimeFactoryRegistry,
) -> InstalledApplicationProvider:
    """Compose exact installed plans without asserting executable bindings."""

    if (
        not isinstance(provider, InstalledApplicationProvider)
        or not isinstance(installed_packages, tuple)
        or any(
            not isinstance(package, InstalledCapabilityPackage)
            for package in installed_packages
        )
        or len({package.package_ref for package in installed_packages})
        != len(installed_packages)
        or not isinstance(runtime_factories, RuntimeFactoryRegistry)
    ):
        raise ApplicationProviderError("installed application provider is invalid")
    metadata = validate_installed_provider_metadata(
        provider, selected_id=provider.provider_id
    )
    applications = tuple(
        _compose_application(
            application,
            installed_packages=installed_packages,
            runtime_factories=runtime_factories,
        )
        for application in metadata.applications
    )
    return InstalledApplicationProvider(
        protocol=metadata.protocol,
        provider_id=metadata.provider_id,
        resource_root=metadata.resource_root,
        applications=applications,
        product=metadata.product,
    )


def _validate_application_metadata(
    application: InstalledApplication, *, root: Path
) -> InstalledApplication:
    if (
        not isinstance(application.assembly_paths, tuple)
        or not application.assembly_paths
    ):
        raise ApplicationProviderError("installed application assemblies are invalid")
    if (
        not isinstance(application.capability_packages, tuple)
        or not application.capability_packages
        or any(
            not isinstance(package_ref, CapabilityPackageRef)
            for package_ref in application.capability_packages
        )
        or tuple(sorted(set(application.capability_packages)))
        != application.capability_packages
    ):
        raise ApplicationProviderError(
            "installed application capability packages are invalid"
        )
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

    assembly_runtime_ids: list[str] = []
    for assembly_path in assemblies:
        assembly = _read_assembly_snapshot(assembly_path, application=application)
        runtime_id = assembly["runtime_id"]
        assert isinstance(runtime_id, str)
        assembly_runtime_ids.append(runtime_id)
        raw_packages = assembly["capability_packages"]
        assert isinstance(raw_packages, list)
        package_refs = tuple(
            CapabilityPackageRef(item["package_id"], item["version"])
            for item in raw_packages
            if isinstance(item, dict)
            and isinstance(item["package_id"], str)
            and isinstance(item["version"], str)
        )
        if package_refs != application.capability_packages:
            raise ApplicationProviderError(
                "installed application capability packages are unavailable"
            )
    if tuple(sorted(assembly_runtime_ids)) != application.runtime_ids:
        raise ApplicationProviderError(
            "installed application runtime assemblies are invalid"
        )

    return InstalledApplication(
        application_id=application.application_id,
        version=application.version,
        assembly_paths=assemblies,
        capability_packages=application.capability_packages,
        runtime_ids=application.runtime_ids,
        assemblies=(),
    )


def _compose_application(
    application: InstalledApplication,
    *,
    installed_packages: tuple[InstalledCapabilityPackage, ...],
    runtime_factories: RuntimeFactoryRegistry,
) -> InstalledApplication:
    try:
        selected_packages = _select_installed_packages(
            application.capability_packages,
            installed_packages,
        )
        catalog = discover_capabilities(
            tuple(
                root for package in selected_packages for root in package.catalog_roots
            )
        )
        implementations = tuple(
            binding
            for package in selected_packages
            for binding in package.implementations
        )
        assemblies: list[InstalledAssembly] = []
        for assembly_path in application.assembly_paths:
            assembly = _read_assembly_snapshot(assembly_path, application=application)
            runtime_id = assembly["runtime_id"]
            assert isinstance(runtime_id, str)
            runtime_binding = runtime_factories.select(runtime_id)
            plan = resolve_assembly(
                assembly,
                catalog=catalog,
                runtime_manifest=runtime_binding.manifest.to_mapping(),
            )
            assemblies.append(
                InstalledAssembly(
                    runtime_id=runtime_id,
                    path=assembly_path,
                    plan=plan,
                    implementations=implementations,
                )
            )
    except (
        OSError,
        UnicodeError,
        KeyError,
        TypeError,
        ValueError,
        CapabilityCatalogError,
        AssemblyError,
        RuntimeFactoryError,
    ):
        raise ApplicationProviderError(
            "installed application composition closure is invalid"
        ) from None
    values = tuple(sorted(assemblies, key=lambda value: value.runtime_id))
    if tuple(value.runtime_id for value in values) != application.runtime_ids:
        raise ApplicationProviderError(
            "installed application runtime assemblies are invalid"
        )
    return InstalledApplication(
        application_id=application.application_id,
        version=application.version,
        assembly_paths=application.assembly_paths,
        capability_packages=application.capability_packages,
        runtime_ids=application.runtime_ids,
        assemblies=values,
    )


def _select_installed_packages(
    package_refs: tuple[CapabilityPackageRef, ...],
    installed_packages: tuple[InstalledCapabilityPackage, ...],
) -> tuple[InstalledCapabilityPackage, ...]:
    selected: list[InstalledCapabilityPackage] = []
    for package_ref in package_refs:
        matches = tuple(
            package
            for package in installed_packages
            if package.package_ref == package_ref
        )
        if len(matches) != 1:
            raise ApplicationProviderError(
                "installed application capability package is unavailable"
            )
        selected.append(matches[0])
    return tuple(selected)


def _read_assembly_snapshot(
    assembly_path: Path,
    *,
    application: InstalledApplication,
) -> dict[str, object]:
    try:
        assembly = json.loads(assembly_path.read_text())
        validate_assembly_manifest(assembly)
    except (OSError, UnicodeError, TypeError, ValueError):
        raise ApplicationProviderError(
            "installed application assembly is invalid"
        ) from None
    assert isinstance(assembly, dict)
    if (
        assembly["application_id"] != application.application_id
        or assembly["version"] != application.version
        or assembly["runtime_id"] not in application.runtime_ids
    ):
        raise ApplicationProviderError(
            "installed application assembly identity is invalid"
        )
    return assembly


def _canonical_resource(value: Path, *, kind: str) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ApplicationProviderError("installed application resource is unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ApplicationProviderError(
            "installed application resource is unavailable"
        ) from None
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
        raise ApplicationProviderError(
            "installed application resource escapes its root"
        )
    return resolved


def _identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None
