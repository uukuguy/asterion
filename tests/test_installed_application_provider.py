from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    validate_installed_provider,
)
from asterion.applications.product import InstalledCapabilityProduct
from asterion.packages.catalog import PackageRef
from asterion.packages.execution import PackageExecutionResult, PackageInvocation


class FixtureImplementation:
    async def execute(
        self, invocation: PackageInvocation
    ) -> PackageExecutionResult:
        del invocation
        return PackageExecutionResult(events=(), artifacts=())


def write_assembly(root: Path, *, application_id: str = "example.research") -> Path:
    assembly_dir = root / "assemblies"
    assembly_dir.mkdir(exist_ok=True)
    path = assembly_dir / "research.json"
    path.write_text(
        json.dumps(
            {
                "protocol": "dci.assembly/v1",
                "application_id": application_id,
                "version": "1.0.0",
                "runtime_id": "pi.reference",
                "packages": [
                    {"package_id": "example.research", "version": "1.0.0"}
                ],
                "host_capabilities": [],
                "host_policies": [],
                "host_events": ["run.started"],
                "host_artifacts": ["text/plain"],
            }
        )
    )
    return path


def provider(root: Path) -> InstalledApplicationProvider:
    catalog = root / "manifests"
    catalog.mkdir(exist_ok=True)
    (catalog / "research.json").write_text(
        json.dumps(
            {
                "protocol": "dci.package/v1",
                "package_id": "example.research",
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
                        PackageRef("example.research", "1.0.0"),
                        FixtureImplementation(),
                    ),
                ),
                runtime_ids=("pi.reference",),
            ),
        ),
    )


class InstalledApplicationProviderTests(unittest.TestCase):
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
            value = validate_installed_provider(
                provider(Path(temp_dir)), selected_id="example-app"
            )

        self.assertEqual(value.protocol, "asterion.application-provider/v1")
        self.assertEqual(value.applications[0].application_id, "example.research")
        with self.assertRaises((AttributeError, TypeError)):
            value.applications[0].runtime_ids += ("other.runtime",)

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
                with self.subTest(selected=selected), self.assertRaises(
                    ApplicationProviderError
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

    def test_protocol_runtime_and_duplicate_binding_invariants_fail_closed(self) -> None:
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
                with self.subTest(value=value), self.assertRaises(
                    ApplicationProviderError
                ):
                    validate_installed_provider(value, selected_id="example-app")


if __name__ == "__main__":
    unittest.main()
