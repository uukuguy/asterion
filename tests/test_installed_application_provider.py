from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    compose_installed_provider,
    resolve_installed_provider,
    validate_installed_provider,
)
from asterion.applications.product import InstalledCapabilityProduct
from asterion.capability_packages import CapabilityPackageRef
from asterion.capabilities.catalog import CapabilityRef, discover_capabilities
from asterion.capabilities.execution import CapabilityExecutionResult, CapabilityInvocation
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry


class FixtureImplementation:
    async def execute(self, invocation: CapabilityInvocation) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(events=(), artifacts=())


class NonCallableImplementation:
    execute = "SECRET-NON-CALLABLE-IMPLEMENTATION"


def write_capability_package(
    root: Path,
    *,
    package_id: str = "example",
    version: str = "1.0.0",
    capabilities: tuple[dict[str, str], ...] = (
        {"capability_id": "example.research", "version": "1.0.0"},
    ),
) -> Path:
    path = root / "capability-package.json"
    path.write_text(
        json.dumps(
            {
                "protocol": "asterion.capability-package/v1",
                "package_id": package_id,
                "version": version,
                "capabilities": list(capabilities),
                "benchmark_suites": [],
                "resources": [],
            }
        )
    )
    return path


def write_assembly(
    root: Path,
    *,
    application_id: str = "example.research",
    filename: str = "research.json",
    runtime_id: str = "pi.reference",
    capability_packages: tuple[dict[str, str], ...] = (
        {"package_id": "example", "version": "1.0.0"},
    ),
    capabilities: tuple[dict[str, str], ...] = (
        {"capability_id": "example.research", "version": "1.0.0"},
    ),
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
                "capability_packages": list(capability_packages),
                "capabilities": list(capabilities),
                "host_capabilities": [],
                "host_policies": [],
                "host_events": ["run.started"],
                "host_artifacts": ["text/plain"],
            }
        )
    )
    return path


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
    write_capability_package(root)
    catalog = root / "manifests"
    catalog.mkdir(exist_ok=True)
    (catalog / "research.json").write_text(
        json.dumps(
            {
                "protocol": "asterion.capability/v1",
                "capability_id": "example.research",
                "version": "1.0.0",
                "kind": "capability",
                "provides_capabilities": [],
                "requires_capabilities": [],
                "requires_policies": [],
                "emits_events": [],
                "consumes_events": [],
                "produces_artifacts": [],
                "consumes_artifacts": [],
            }
        )
    )
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="example-app",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="example.research",
                version="1.0.0",
                assembly_paths=(write_assembly(root),),
                catalog_roots=(catalog,),
                implementations=(
                    (
                        CapabilityRef("example.research", "1.0.0"),
                        FixtureImplementation(),
                    ),
                ),
                runtime_ids=("pi.reference",),
            ),
        ),
    )


class InstalledApplicationProviderTests(unittest.TestCase):
    def test_composition_is_independent_from_executable_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            application = valid.applications[0]
            missing_binding = InstalledApplicationProvider(
                protocol=valid.protocol,
                provider_id=valid.provider_id,
                resource_root=valid.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=application.catalog_roots,
                        implementations=(),
                        runtime_ids=application.runtime_ids,
                    ),
                ),
            )
            registry = runtime_factories("pi.reference")

            composed = compose_installed_provider(
                missing_binding, runtime_factories=registry
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
                    missing_binding, runtime_factories=registry
                )

    def test_executable_resolution_composes_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            registry = runtime_factories("pi.reference")
            with patch(
                "asterion.applications.provider.compose_installed_provider",
                wraps=compose_installed_provider,
            ) as composition:
                resolved = resolve_installed_provider(
                    valid, runtime_factories=registry
                )

        self.assertEqual(composition.call_count, 1)
        self.assertEqual(len(resolved.applications[0].assemblies), 1)

    def test_malformed_executable_closures_fail_before_runtime_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = provider(root)
            application = valid.applications[0]
            duplicate_path = write_assembly(root, filename="research-copy.json")
            unlisted_path = write_assembly(
                root,
                filename="other-runtime.json",
                runtime_id="other.runtime",
            )
            catalog = application.catalog_roots[0]
            uncomposable_catalog = root / "uncomposable-manifests"
            uncomposable_catalog.mkdir()
            (uncomposable_catalog / "research.json").write_text(
                json.dumps(
                    {
                        "protocol": "asterion.capability/v1",
                        "capability_id": "example.research",
                        "version": "1.0.0",
                        "kind": "capability",
                        "provides_capabilities": [],
                        "requires_capabilities": ["missing.capability"],
                        "requires_policies": [],
                        "emits_events": [],
                        "consumes_events": [],
                        "produces_artifacts": [],
                        "consumes_artifacts": [],
                    }
                )
            )

            def with_application(
                value: InstalledApplication,
            ) -> InstalledApplicationProvider:
                return InstalledApplicationProvider(
                    protocol=valid.protocol,
                    provider_id=valid.provider_id,
                    resource_root=valid.resource_root,
                    applications=(value,),
                )

            cases = {
                "runtime-without-assembly": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=(catalog,),
                        implementations=application.implementations,
                        runtime_ids=("other.runtime", "pi.reference"),
                    )
                ),
                "two-assemblies-for-one-runtime": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(*application.assembly_paths, duplicate_path),
                        catalog_roots=(catalog,),
                        implementations=application.implementations,
                        runtime_ids=("pi.reference",),
                    )
                ),
                "assembly-runtime-not-listed": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(unlisted_path,),
                        catalog_roots=(catalog,),
                        implementations=application.implementations,
                        runtime_ids=("pi.reference",),
                    )
                ),
                "missing-package-implementation": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=(catalog,),
                        implementations=(),
                        runtime_ids=application.runtime_ids,
                    )
                ),
                "unknown-package-implementation": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=(catalog,),
                        implementations=(
                            *application.implementations,
                            (
                                CapabilityRef("example.unknown", "1.0.0"),
                                FixtureImplementation(),
                            ),
                        ),
                        runtime_ids=application.runtime_ids,
                    )
                ),
                "non-callable-package-implementation": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=(catalog,),
                        implementations=(
                            (
                                CapabilityRef("example.research", "1.0.0"),
                                NonCallableImplementation(),
                            ),
                        ),
                        runtime_ids=application.runtime_ids,
                    )
                ),
                "uncomposable-bound-assembly": with_application(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=(uncomposable_catalog,),
                        implementations=application.implementations,
                        runtime_ids=application.runtime_ids,
                    )
                ),
            }
            registry = runtime_factories("other.runtime", "pi.reference")
            for case, value in cases.items():
                with (
                    self.subTest(case=case),
                    self.assertRaises(ApplicationProviderError),
                ):
                    resolve_installed_provider(
                        validate_installed_provider(
                            value, selected_id=value.provider_id
                        ),
                        runtime_factories=registry,
                    )

    def test_unknown_or_mismatched_assembly_package_ref_fails_before_resolution(
        self,
    ) -> None:
        sentinel = "secret.missing-package"
        cases = (
            (
                "unknown-package",
                ({"package_id": sentinel, "version": "1.0.0"},),
                sentinel,
            ),
            (
                "mismatched-version",
                ({"package_id": "example", "version": "9.9.9"},),
                "9.9.9",
            ),
        )
        for case, package_refs, secret in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                valid = provider(root)
                application = valid.applications[0]
                assembly_path = write_assembly(
                    root,
                    filename="missing-package-ref.json",
                    capability_packages=package_refs,
                )
                invalid = InstalledApplicationProvider(
                    protocol=valid.protocol,
                    provider_id=valid.provider_id,
                    resource_root=valid.resource_root,
                    applications=(
                        InstalledApplication(
                            application_id=application.application_id,
                            version=application.version,
                            assembly_paths=(assembly_path,),
                            catalog_roots=application.catalog_roots,
                            implementations=application.implementations,
                            runtime_ids=application.runtime_ids,
                        ),
                    ),
                )

                with self.assertRaises(ApplicationProviderError) as raised:
                    validate_installed_provider(invalid, selected_id="example-app")
                self.assertNotIn(secret, str(raised.exception))

    def test_assembly_capability_must_belong_to_referenced_package(self) -> None:
        sentinel = "secret.extra-capability"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = provider(root)
            application = valid.applications[0]
            assembly_path = write_assembly(
                root,
                filename="extra-capability.json",
                capabilities=(
                    {"capability_id": "example.research", "version": "1.0.0"},
                    {"capability_id": sentinel, "version": "1.0.0"},
                ),
            )
            invalid = InstalledApplicationProvider(
                protocol=valid.protocol,
                provider_id=valid.provider_id,
                resource_root=valid.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(assembly_path,),
                        catalog_roots=application.catalog_roots,
                        implementations=application.implementations,
                        runtime_ids=application.runtime_ids,
                    ),
                ),
            )

            with self.assertRaises(ApplicationProviderError) as raised:
                validate_installed_provider(invalid, selected_id="example-app")

        self.assertNotIn(sentinel, str(raised.exception))

    def test_resolution_revalidates_the_exact_assembly_snapshot(self) -> None:
        sentinel = "other.secret"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = validate_installed_provider(
                provider(root), selected_id="example-app"
            )
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
            hostile_path = application.assembly_paths[0].with_name(
                f"{sentinel}.json"
            )
            hostile_path.write_text('{"value":' + ("9" * 10000) + "}")
            invalid = InstalledApplicationProvider(
                protocol=valid.protocol,
                provider_id=valid.provider_id,
                resource_root=valid.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=(hostile_path,),
                        catalog_roots=application.catalog_roots,
                        implementations=application.implementations,
                        runtime_ids=application.runtime_ids,
                    ),
                ),
            )

            with self.assertRaises(ApplicationProviderError) as raised:
                validate_installed_provider(invalid, selected_id="example-app")

        self.assertIs(type(raised.exception), ApplicationProviderError)
        self.assertNotIn(sentinel, str(raised.exception))

    def test_optional_capability_product_survives_provider_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            product = InstalledCapabilityProduct(
                description=None,  # type: ignore[arg-type]
                verifier=lambda request: None,
            )
            invalid = InstalledApplicationProvider(
                protocol=valid.protocol,
                provider_id=valid.provider_id,
                resource_root=valid.resource_root,
                applications=valid.applications,
                product=product,
            )

            with self.assertRaises(ApplicationProviderError):
                validate_installed_provider(invalid, selected_id="example-app")

    def test_valid_provider_is_deeply_immutable_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata = validate_installed_provider(
                provider(Path(temp_dir)), selected_id="example-app"
            )
            with patch(
                "asterion.applications.provider.discover_capabilities",
                wraps=discover_capabilities,
            ) as discovery:
                value = resolve_installed_provider(
                    metadata,
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
        self.assertEqual(
            value.applications[0].assemblies[0].plan.capability_package_refs,
            (CapabilityPackageRef("example", "1.0.0"),),
        )
        with self.assertRaises((AttributeError, TypeError)):
            value.applications[0].runtime_ids += ("other.runtime",)
        with self.assertRaises((AttributeError, TypeError)):
            value.applications[0].assemblies += ()

    def test_provider_identity_and_duplicate_applications_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            cases = (
                (valid, "other-app"),
                (
                    InstalledApplicationProvider(
                        protocol=valid.protocol,
                        provider_id=valid.provider_id,
                        resource_root=valid.resource_root,
                        applications=(valid.applications[0], valid.applications[0]),
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

    def test_symlink_and_resource_escape_are_rejected_without_content(self) -> None:
        sentinel = "SECRET-RESOURCE"
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            root.mkdir()
            outside = base / sentinel
            outside.mkdir()
            valid = provider(root)
            link = root / "escaped"
            link.symlink_to(outside, target_is_directory=True)
            application = valid.applications[0]
            invalid = InstalledApplicationProvider(
                protocol=valid.protocol,
                provider_id=valid.provider_id,
                resource_root=valid.resource_root,
                applications=(
                    InstalledApplication(
                        application_id=application.application_id,
                        version=application.version,
                        assembly_paths=application.assembly_paths,
                        catalog_roots=(link,),
                        implementations=application.implementations,
                        runtime_ids=application.runtime_ids,
                    ),
                ),
            )

            with self.assertRaises(ApplicationProviderError) as raised:
                validate_installed_provider(invalid, selected_id="example-app")

        self.assertNotIn(sentinel, str(raised.exception))

    def test_protocol_runtime_and_duplicate_binding_invariants_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = provider(Path(temp_dir))
            application = valid.applications[0]
            duplicate_binding = InstalledApplication(
                application_id=application.application_id,
                version=application.version,
                assembly_paths=application.assembly_paths,
                catalog_roots=application.catalog_roots,
                implementations=(
                    application.implementations[0],
                    application.implementations[0],
                ),
                runtime_ids=application.runtime_ids,
            )
            no_runtime = InstalledApplication(
                application_id=application.application_id,
                version=application.version,
                assembly_paths=application.assembly_paths,
                catalog_roots=application.catalog_roots,
                implementations=application.implementations,
                runtime_ids=(),
            )
            cases = (
                InstalledApplicationProvider(
                    protocol="other/v1",
                    provider_id=valid.provider_id,
                    resource_root=valid.resource_root,
                    applications=valid.applications,
                ),
                InstalledApplicationProvider(
                    protocol=valid.protocol,
                    provider_id=valid.provider_id,
                    resource_root=valid.resource_root,
                    applications=(duplicate_binding,),
                ),
                InstalledApplicationProvider(
                    protocol=valid.protocol,
                    provider_id=valid.provider_id,
                    resource_root=valid.resource_root,
                    applications=(no_runtime,),
                ),
            )
            for value in cases:
                with (
                    self.subTest(value=value),
                    self.assertRaises(ApplicationProviderError),
                ):
                    validate_installed_provider(value, selected_id="example-app")


if __name__ == "__main__":
    unittest.main()
