from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.applications.product import InstalledCapabilityProduct
from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    compose_installed_provider,
    resolve_installed_provider,
    validate_installed_provider,
)
from asterion.capabilities.catalog import CapabilityRef, discover_capabilities
from asterion.capabilities.execution import (
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityInvocation,
)
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry


PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")


class FixtureImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(events=(), artifacts=())


class NonCallableImplementation:
    execute = "SECRET-NON-CALLABLE-IMPLEMENTATION"


def write_assembly(
    root: Path,
    *,
    application_id: str = "example.research",
    filename: str = "research.json",
    runtime_id: str = "pi.reference",
) -> Path:
    assembly_dir = root / "assemblies"
    assembly_dir.mkdir(exist_ok=True)
    path = assembly_dir / filename
    path.write_text(
        json.dumps(
            {
                "protocol": "asterion.application-assembly/v1",
                "application_id": application_id,
                "version": "1.0.0",
                "runtime_id": runtime_id,
                "capability_packages": [
                    {"package_id": "example.package", "version": "1.0.0"}
                ],
                "capabilities": [
                    {
                        "capability_id": "example.research",
                        "version": "1.0.0",
                    }
                ],
                "host_capabilities": [],
                "host_policies": [],
                "host_events": ["run.started"],
                "host_artifacts": ["text/plain"],
            }
        )
    )
    return path


def write_catalog(
    root: Path,
    *,
    directory: str = "manifests",
    requires_capabilities: tuple[str, ...] = (),
) -> Path:
    catalog = root / directory
    catalog.mkdir(exist_ok=True)
    (catalog / "research.json").write_text(
        json.dumps(
            {
                "protocol": "asterion.capability/v1",
                "capability_id": "example.research",
                "version": "1.0.0",
                "kind": "capability",
                "provides_capabilities": [],
                "requires_capabilities": list(requires_capabilities),
                "requires_policies": [],
                "emits_events": [],
                "consumes_events": [],
                "produces_artifacts": [],
                "consumes_artifacts": [],
            }
        )
    )
    return catalog.resolve()


def runtime_factories(*runtime_ids: str) -> RuntimeFactoryRegistry:
    def fail_if_called(context):
        del context
        raise AssertionError("provider validation called a runtime factory")

    return RuntimeFactoryRegistry(
        RuntimeFactoryBinding(
            runtime_id=runtime_id,
            capabilities=(),
            factory=fail_if_called,
        )
        for runtime_id in runtime_ids
    )


def provider(root: Path) -> InstalledApplicationProvider:
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="example-app",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="example.research",
                version="1.0.0",
                assembly_paths=(write_assembly(root),),
                capability_packages=(PACKAGE_REF,),
                runtime_ids=("pi.reference",),
            ),
        ),
    )


def installed_package(
    root: Path,
    *,
    catalog_root: Path | None = None,
    implementations: tuple[CapabilityImplementationBinding, ...] | None = None,
) -> InstalledCapabilityPackage:
    if catalog_root is None:
        catalog_root = write_catalog(root)
    if implementations is None:
        implementations = (
            CapabilityImplementationBinding(
                capability_ref=CapabilityRef("example.research", "1.0.0"),
                implementation=FixtureImplementation(),
            ),
        )
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256="a" * 64,
        source_id="builtin:example.package@1.0.0",
        source_kind="builtin",
        catalog_roots=(catalog_root,),
        benchmark_suite_paths=(),
        implementations=implementations,
        benchmark_bindings=(),
    )


class InstalledApplicationProviderTests(unittest.TestCase):
    def test_application_metadata_owns_exact_package_refs_not_package_bodies(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata = validate_installed_provider(
                provider(Path(temp_dir)), selected_id="example-app"
            )

        application = metadata.applications[0]
        self.assertEqual(application.capability_packages, (PACKAGE_REF,))
        self.assertFalse(hasattr(application, "catalog_roots"))
        self.assertFalse(hasattr(application, "implementations"))

    def test_composition_resolves_catalogs_and_bindings_from_selected_packages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = installed_package(root)

            resolved = resolve_installed_provider(
                provider(root),
                installed_packages=(package,),
                runtime_factories=runtime_factories("pi.reference"),
            )

        application = resolved.applications[0]
        self.assertFalse(hasattr(application, "implementations"))
        self.assertEqual(
            {
                binding.capability_ref
                for binding in application.assemblies[0].implementations
            },
            {CapabilityRef("example.research", "1.0.0")},
        )

    def test_composition_is_independent_from_executable_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = provider(root)
            package = installed_package(root, implementations=())
            registry = runtime_factories("pi.reference")

            composed = compose_installed_provider(
                valid,
                installed_packages=(package,),
                runtime_factories=registry,
            )

            self.assertEqual(
                tuple(
                    assembly.runtime_id
                    for assembly in composed.applications[0].assemblies
                ),
                ("pi.reference",),
            )
            with self.assertRaises(ApplicationProviderError):
                resolve_installed_provider(
                    valid,
                    installed_packages=(package,),
                    runtime_factories=registry,
                )

    def test_executable_resolution_composes_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = provider(root)
            packages = (installed_package(root),)
            registry = runtime_factories("pi.reference")
            with patch(
                "asterion.applications.provider.compose_installed_provider",
                wraps=compose_installed_provider,
            ) as composition:
                resolved = resolve_installed_provider(
                    valid,
                    installed_packages=packages,
                    runtime_factories=registry,
                )

        self.assertEqual(composition.call_count, 1)
        self.assertEqual(len(resolved.applications[0].assemblies), 1)

    def test_malformed_executable_closures_fail_before_runtime_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = provider(root)
            application = valid.applications[0]
            package = installed_package(root)
            duplicate_path = write_assembly(root, filename="research-copy.json")
            unlisted_path = write_assembly(
                root,
                filename="other-runtime.json",
                runtime_id="other.runtime",
            )
            uncomposable_catalog = write_catalog(
                root,
                directory="uncomposable-manifests",
                requires_capabilities=("missing.capability",),
            )

            def with_application(
                value: InstalledApplication,
            ) -> InstalledApplicationProvider:
                return replace(valid, applications=(value,))

            unknown_binding = CapabilityImplementationBinding(
                capability_ref=CapabilityRef("example.unknown", "1.0.0"),
                implementation=FixtureImplementation(),
            )
            non_callable_binding = CapabilityImplementationBinding(
                capability_ref=CapabilityRef("example.research", "1.0.0"),
                implementation=NonCallableImplementation(),  # type: ignore[arg-type]
            )
            cases = {
                "runtime-without-assembly": (
                    with_application(
                        replace(
                            application,
                            runtime_ids=("other.runtime", "pi.reference"),
                        )
                    ),
                    (package,),
                ),
                "two-assemblies-for-one-runtime": (
                    with_application(
                        replace(
                            application,
                            assembly_paths=(
                                *application.assembly_paths,
                                duplicate_path,
                            ),
                        )
                    ),
                    (package,),
                ),
                "assembly-runtime-not-listed": (
                    with_application(
                        replace(application, assembly_paths=(unlisted_path,))
                    ),
                    (package,),
                ),
                "missing-installed-package": (valid, ()),
                "missing-package-implementation": (
                    valid,
                    (replace(package, implementations=()),),
                ),
                "unknown-package-implementation": (
                    valid,
                    (
                        replace(
                            package,
                            implementations=(
                                *package.implementations,
                                unknown_binding,
                            ),
                        ),
                    ),
                ),
                "non-callable-package-implementation": (
                    valid,
                    (
                        replace(
                            package,
                            implementations=(non_callable_binding,),
                        ),
                    ),
                ),
                "uncomposable-bound-assembly": (
                    valid,
                    (
                        replace(
                            package,
                            catalog_roots=(uncomposable_catalog,),
                        ),
                    ),
                ),
            }
            registry = runtime_factories("other.runtime", "pi.reference")
            for case, (value, packages) in cases.items():
                with (
                    self.subTest(case=case),
                    self.assertRaises(ApplicationProviderError),
                ):
                    resolve_installed_provider(
                        validate_installed_provider(
                            value, selected_id=value.provider_id
                        ),
                        installed_packages=packages,
                        runtime_factories=registry,
                    )

    def test_resolution_revalidates_the_exact_assembly_snapshot(self) -> None:
        sentinel = "other.secret"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = validate_installed_provider(
                provider(root), selected_id="example-app"
            )
            package = installed_package(root)
            assembly_path = metadata.applications[0].assembly_paths[0]

            def mutate_during_discovery(roots):
                catalog = discover_capabilities(roots)
                assembly = json.loads(assembly_path.read_text())
                assembly["application_id"] = sentinel
                assembly_path.write_text(json.dumps(assembly))
                return catalog

            with (
                patch(
                    "asterion.applications.provider.discover_capabilities",
                    side_effect=mutate_during_discovery,
                ),
                self.assertRaises(ApplicationProviderError) as raised,
            ):
                resolve_installed_provider(
                    metadata,
                    installed_packages=(package,),
                    runtime_factories=runtime_factories("pi.reference"),
                )

        self.assertIs(type(raised.exception), ApplicationProviderError)
        self.assertNotIn(sentinel, str(raised.exception))

    def test_hostile_numeric_json_is_normalized_and_redacted(self) -> None:
        sentinel = "SECRET-HOSTILE-NUMERIC"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = provider(root)
            application = valid.applications[0]
            hostile_path = application.assembly_paths[0].with_name(f"{sentinel}.json")
            hostile_path.write_text('{"value":' + ("9" * 10000) + "}")
            invalid = replace(
                valid,
                applications=(replace(application, assembly_paths=(hostile_path,)),),
            )

            with self.assertRaises(ApplicationProviderError) as raised:
                validate_installed_provider(invalid, selected_id="example-app")

        self.assertIs(type(raised.exception), ApplicationProviderError)
        self.assertNotIn(sentinel, str(raised.exception))

    def test_optional_capability_product_survives_provider_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            product = InstalledCapabilityProduct(
                description=None,  # type: ignore[arg-type]
                verifier=lambda request: None,  # type: ignore[arg-type, return-value]
            )
            invalid = replace(valid, product=product)

            with self.assertRaises(ApplicationProviderError):
                validate_installed_provider(invalid, selected_id="example-app")

    def test_valid_provider_is_deeply_immutable_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = validate_installed_provider(
                provider(root), selected_id="example-app"
            )
            package = installed_package(root)
            with patch(
                "asterion.applications.provider.discover_capabilities",
                wraps=discover_capabilities,
            ) as discovery:
                value = resolve_installed_provider(
                    metadata,
                    installed_packages=(package,),
                    runtime_factories=runtime_factories("pi.reference"),
                )

        self.assertEqual(metadata.applications[0].assemblies, ())
        self.assertEqual(discovery.call_count, 1)
        self.assertEqual(value.protocol, "asterion.application-provider/v1")
        self.assertEqual(value.applications[0].application_id, "example.research")
        self.assertEqual(
            tuple(assembly.runtime_id for assembly in value.applications[0].assemblies),
            ("pi.reference",),
        )
        self.assertEqual(
            value.applications[0].assemblies[0].plan.application_id,
            "example.research",
        )
        with self.assertRaises((AttributeError, TypeError)):
            value.applications[0].runtime_ids += (  # type: ignore[misc]
                "other.runtime",
            )
        with self.assertRaises((AttributeError, TypeError)):
            value.applications[0].assemblies += ()  # type: ignore[misc]

    def test_provider_identity_and_duplicate_applications_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            cases = (
                (valid, "other-app"),
                (
                    replace(
                        valid,
                        applications=(
                            valid.applications[0],
                            valid.applications[0],
                        ),
                    ),
                    valid.provider_id,
                ),
            )
            for value, selected in cases:
                with (
                    self.subTest(selected=selected),
                    self.assertRaises(ApplicationProviderError),
                ):
                    validate_installed_provider(value, selected_id=selected)

    def test_symlink_and_resource_escape_are_rejected_without_content(
        self,
    ) -> None:
        sentinel = "SECRET-RESOURCE"
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            root.mkdir()
            outside = base / sentinel
            outside.mkdir()
            outside_assembly = write_assembly(outside)
            valid = provider(root)
            link = root / "escaped.json"
            link.symlink_to(outside_assembly)
            invalid = replace(
                valid,
                applications=(
                    replace(
                        valid.applications[0],
                        assembly_paths=(link,),
                    ),
                ),
            )

            with self.assertRaises(ApplicationProviderError) as raised:
                validate_installed_provider(invalid, selected_id="example-app")

        self.assertNotIn(sentinel, str(raised.exception))

    def test_protocol_runtime_and_package_ref_invariants_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            application = valid.applications[0]
            duplicate_package_ref = replace(
                application,
                capability_packages=(PACKAGE_REF, PACKAGE_REF),
            )
            no_runtime = replace(application, runtime_ids=())
            cases = (
                replace(valid, protocol="other/v1"),
                replace(valid, applications=(duplicate_package_ref,)),
                replace(valid, applications=(no_runtime,)),
            )
            for value in cases:
                with (
                    self.subTest(value=value),
                    self.assertRaises(ApplicationProviderError),
                ):
                    validate_installed_provider(value, selected_id="example-app")


if __name__ == "__main__":
    unittest.main()
