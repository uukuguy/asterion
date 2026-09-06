"""Versioned immutable contract for installed application providers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from asterion.assembly.protocol import (
    AssemblyError,
    AssemblyPlan,
    resolve_assembly,
    validate_assembly_manifest,
)
from asterion.capability_packages import (
    CapabilityPackageRef,
    InstalledCapabilityPackage,
)
from asterion.capabilities.catalog import (
    CapabilityCatalogError,
    CapabilityRef,
    discover_capabilities,
)
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityImplementation,
    EXECUTABLE_CAPABILITY_KINDS,
    validate_implementation_bindings,
)
from asterion.applications.product import (
    InstalledCapabilityProduct,
    validate_capability_product,
)
from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryError,
    RuntimeFactoryRegistry,
)


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
    runtime_binding: RuntimeFactoryBinding | None = field(default=None, repr=False)


@dataclass(frozen=True)
class InstalledApplication:
    application_id: str
    version: str
    assembly_paths: tuple[Path, ...]
    capability_packages: tuple[CapabilityPackageRef, ...]
    runtime_ids: tuple[str, ...]
    installed_packages: tuple[InstalledCapabilityPackage, ...] = ()
    assemblies: tuple[InstalledAssembly, ...] = ()

    @property
    def catalog_roots(self) -> tuple[Path, ...]:
        return tuple(
            root
            for package in self.installed_packages
            for root in package.catalog_roots
        )

    @property
    def implementations(
        self,
    ) -> tuple[tuple[CapabilityRef, CapabilityImplementation], ...]:
        bindings = tuple(
            (binding.capability_ref, binding.implementation)
            for package in self.installed_packages
            for binding in package.implementations
        )
        if not self.assemblies:
            return bindings
        expected_refs = {
            CapabilityRef(str(manifest["capability_id"]), str(manifest["version"]))
            for assembly in self.assemblies
            for manifest in assembly.plan.capability_manifests
            if manifest["kind"] in EXECUTABLE_CAPABILITY_KINDS
        }
        return tuple(binding for binding in bindings if binding[0] in expected_refs)


@dataclass(frozen=True)
class InstalledApplicationProvider:
    protocol: str
    provider_id: str
    resource_root: Path
    applications: tuple[InstalledApplication, ...]
    product: InstalledCapabilityProduct | None = None
    runtime_factory_bindings: tuple[RuntimeFactoryBinding, ...] = field(
        default=(), repr=False
    )


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
    bindings = _runtime_factory_bindings(value.runtime_factory_bindings, applications)
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
        runtime_factory_bindings=bindings,
    )


def resolve_installed_provider(
    provider: InstalledApplicationProvider,
    *,
    runtime_factories: RuntimeFactoryRegistry,
    installed_packages: tuple[InstalledCapabilityPackage, ...] = (),
) -> InstalledApplicationProvider:
    """Resolve every installed application into an exact executable closure."""

    composed = compose_installed_provider(
        provider,
        runtime_factories=runtime_factories,
        installed_packages=installed_packages,
    )
    try:
        for application in composed.applications:
            for assembly in application.assemblies:
                validate_implementation_bindings(
                    assembly.plan, application.implementations
                )
    except (CapabilityExecutionError, TypeError, ValueError):
        raise ApplicationProviderError(
            "installed application executable closure is invalid"
        ) from None
    return composed


def compose_installed_provider(
    provider: InstalledApplicationProvider,
    *,
    runtime_factories: RuntimeFactoryRegistry,
    installed_packages: tuple[InstalledCapabilityPackage, ...] = (),
) -> InstalledApplicationProvider:
    """Compose exact installed plans without asserting executable bindings."""

    if not isinstance(provider, InstalledApplicationProvider) or not isinstance(
        runtime_factories, RuntimeFactoryRegistry
    ):
        raise ApplicationProviderError("installed application provider is invalid")
    metadata = validate_installed_provider_metadata(
        provider, selected_id=provider.provider_id
    )
    try:
        effective_factories = runtime_factories.extend(
            metadata.runtime_factory_bindings
        )
    except RuntimeFactoryError:
        raise ApplicationProviderError(
            "installed application runtime bindings are invalid"
        ) from None
    package_map = _installed_package_map(installed_packages)
    applications = tuple(
        _compose_application(
            application,
            runtime_factories=effective_factories,
            installed_packages=package_map,
        )
        for application in metadata.applications
    )
    return InstalledApplicationProvider(
        protocol=metadata.protocol,
        provider_id=metadata.provider_id,
        resource_root=metadata.resource_root,
        applications=applications,
        product=metadata.product,
        runtime_factory_bindings=metadata.runtime_factory_bindings,
    )


def _validate_application_metadata(
    application: InstalledApplication, *, root: Path
) -> InstalledApplication:
    if (
        not isinstance(application.assembly_paths, tuple)
        or not application.assembly_paths
    ):
        raise ApplicationProviderError("installed application assemblies are invalid")
    if not isinstance(application.capability_packages, tuple):
        raise ApplicationProviderError(
            "installed application capability packages are invalid"
        )
    application_package_refs = _package_ref_tuple(application.capability_packages)
    if not application_package_refs:
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
        if not isinstance(raw_packages, list):
            raise ApplicationProviderError(
                "installed application package closure is invalid"
            )
        assembly_package_refs = tuple(
            _assembly_package_ref(item) for item in raw_packages
        )
        if assembly_package_refs != application_package_refs:
            raise ApplicationProviderError(
                "installed application package closure is invalid"
            )
    if tuple(sorted(assembly_runtime_ids)) != application.runtime_ids:
        raise ApplicationProviderError(
            "installed application runtime assemblies are invalid"
        )

    return InstalledApplication(
        application_id=application.application_id,
        version=application.version,
        assembly_paths=assemblies,
        capability_packages=application_package_refs,
        runtime_ids=application.runtime_ids,
        installed_packages=(),
        assemblies=(),
    )


def _compose_application(
    application: InstalledApplication,
    *,
    runtime_factories: RuntimeFactoryRegistry,
    installed_packages: Mapping[CapabilityPackageRef, InstalledCapabilityPackage],
) -> InstalledApplication:
    try:
        packages = _packages_for_application(application, installed_packages)
        if len(packages) > 1 and any(
            package._owned_capability_refs is None for package in packages
        ):
            raise ApplicationProviderError(
                "installed application package authority is invalid"
            )
        package_catalog_roots = tuple(
            tuple(
                _canonical_resource(root, kind="directory")
                for root in package.catalog_roots
            )
            for package in packages
        )
        catalog_roots = tuple(root for roots in package_catalog_roots for root in roots)
        catalog = discover_capabilities(catalog_roots)
        package_capability_refs = tuple(
            _catalog_capability_refs(catalog, roots) for roots in package_catalog_roots
        )
        for package, owned_refs in zip(packages, package_capability_refs, strict=True):
            if (
                package._owned_capability_refs is not None
                and package._owned_capability_refs != owned_refs
            ):
                raise ApplicationProviderError(
                    "installed application package authority is invalid"
                )
            if any(
                binding.capability_ref not in owned_refs
                for binding in package.implementations
            ):
                raise ApplicationProviderError(
                    "installed application binding is unavailable"
                )
        available_capability_refs = set().union(*package_capability_refs)
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
            if not set(plan.capability_refs).issubset(available_capability_refs):
                raise ApplicationProviderError(
                    "installed application package closure is invalid"
                )
            assemblies.append(
                InstalledAssembly(
                    runtime_id=runtime_id,
                    path=assembly_path,
                    plan=plan,
                    runtime_binding=runtime_binding,
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
        installed_packages=packages,
        assemblies=values,
    )


def _read_assembly_snapshot(
    assembly_path: Path,
    *,
    application: InstalledApplication,
) -> Mapping[str, object]:
    try:
        assembly = json.loads(assembly_path.read_text())
        validate_assembly_manifest(assembly)
    except (OSError, UnicodeError, TypeError, ValueError):
        raise ApplicationProviderError(
            "installed application assembly is invalid"
        ) from None
    if (
        assembly["application_id"] != application.application_id
        or assembly["version"] != application.version
        or assembly["runtime_id"] not in application.runtime_ids
    ):
        raise ApplicationProviderError(
            "installed application assembly identity is invalid"
        )
    return assembly


def _package_ref_tuple(
    values: tuple[CapabilityPackageRef, ...],
) -> tuple[CapabilityPackageRef, ...]:
    try:
        package_refs = tuple(values)
    except Exception:
        raise ApplicationProviderError(
            "installed application capability packages are invalid"
        ) from None
    if (
        not all(
            type(package_ref) is CapabilityPackageRef for package_ref in package_refs
        )
        or tuple(sorted(package_refs)) != package_refs
        or len(set(package_refs)) != len(package_refs)
    ):
        raise ApplicationProviderError(
            "installed application capability packages are invalid"
        )
    return package_refs


def _assembly_package_ref(value: object) -> CapabilityPackageRef:
    if not isinstance(value, Mapping):
        raise ApplicationProviderError(
            "installed application package closure is invalid"
        )
    package_id = value.get("package_id")
    version = value.get("version")
    if not isinstance(package_id, str) or not isinstance(version, str):
        raise ApplicationProviderError(
            "installed application package closure is invalid"
        )
    return CapabilityPackageRef(package_id, version)


def _installed_package_map(
    values: tuple[InstalledCapabilityPackage, ...],
) -> Mapping[CapabilityPackageRef, InstalledCapabilityPackage]:
    if not isinstance(values, tuple):
        raise ApplicationProviderError(
            "installed application capability packages are invalid"
        )
    packages: dict[CapabilityPackageRef, InstalledCapabilityPackage] = {}
    for package in values:
        if type(package) is not InstalledCapabilityPackage:
            raise ApplicationProviderError(
                "installed application capability packages are invalid"
            )
        if package.package_ref in packages:
            raise ApplicationProviderError(
                "installed application capability packages are invalid"
            )
        packages[package.package_ref] = package
    return packages


def _packages_for_application(
    application: InstalledApplication,
    installed_packages: Mapping[CapabilityPackageRef, InstalledCapabilityPackage],
) -> tuple[InstalledCapabilityPackage, ...]:
    packages = tuple(
        installed_packages[package_ref]
        for package_ref in application.capability_packages
        if package_ref in installed_packages
    )
    if len(packages) != len(application.capability_packages):
        raise ApplicationProviderError(
            "installed application capability packages are unavailable"
        )
    return packages


def _catalog_capability_refs(
    catalog,
    roots: tuple[Path, ...],
) -> frozenset[CapabilityRef]:
    return frozenset(
        entry.ref
        for entry in catalog.entries
        if any(entry.source.is_relative_to(root) for root in roots)
    )


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


def _runtime_factory_bindings(
    values: object,
    applications: list[InstalledApplication],
) -> tuple[RuntimeFactoryBinding, ...]:
    if not isinstance(values, tuple):
        raise ApplicationProviderError(
            "installed application runtime bindings are invalid"
        )
    try:
        bindings = tuple(values)
        RuntimeFactoryRegistry(bindings)
    except (TypeError, ValueError):
        raise ApplicationProviderError(
            "installed application runtime bindings are invalid"
        ) from None
    declared = {
        runtime_id
        for application in applications
        for runtime_id in application.runtime_ids
    }
    if any(binding.runtime_id not in declared for binding in bindings):
        raise ApplicationProviderError(
            "installed application runtime bindings are invalid"
        )
    return bindings
