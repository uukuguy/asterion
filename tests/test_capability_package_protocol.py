from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.protocol import (
    CAPABILITY_PACKAGE_PROTOCOL_VERSION,
    BenchmarkSuiteRef,
    CapabilityPackageManifest,
    CapabilityPackageProtocolError,
    CapabilityPackageRef,
    ResourceIdentity,
    validate_capability_package_manifest,
)


PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures/capability_packages/v1"
SOURCE = PROJECT / "src/asterion"
SCHEMA = (
    PROJECT
    / "schemas/capability-packages/v1/capability-package.schema.json"
)


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


VALID = fixture("valid-minimal.json")


class CapabilityPackageProtocolTests(unittest.TestCase):
    def test_accepts_the_closed_portable_package_fixture(self) -> None:
        manifest = validate_capability_package_manifest(VALID)

        self.assertEqual(
            CAPABILITY_PACKAGE_PROTOCOL_VERSION,
            "asterion.capability-package/v1",
        )
        self.assertEqual(
            manifest,
            CapabilityPackageManifest(
                package_ref=CapabilityPackageRef("example.package", "1.0.0"),
                capabilities=(
                    CapabilityRef("example.alpha", "1.0.0"),
                    CapabilityRef("example.research", "1.0.0"),
                ),
                benchmark_suites=(
                    BenchmarkSuiteRef("example.benchmark", "1.0.0"),
                ),
                resources=(
                    ResourceIdentity(
                        "example.public-config",
                        "application/json",
                        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                    ),
                ),
            ),
        )

    def test_returns_an_immutable_snapshot_detached_from_the_caller(self) -> None:
        value = fixture("valid-minimal.json")

        manifest = validate_capability_package_manifest(value)
        value["package_id"] = "changed.package"
        capabilities = value["capabilities"]
        assert isinstance(capabilities, list)
        capabilities[0]["capability_id"] = "changed.capability"
        resources = value["resources"]
        assert isinstance(resources, list)
        resources[0]["sha256"] = "f" * 64

        self.assertEqual(manifest.package_ref.package_id, "example.package")
        self.assertEqual(manifest.capabilities[0].capability_id, "example.alpha")
        self.assertEqual(
            manifest.resources[0].sha256,
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )
        self.assertFalse(hasattr(manifest, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            manifest.package_ref = CapabilityPackageRef(  # type: ignore[misc]
                "changed.package",
                "1.0.0",
            )

    def test_reference_values_are_ordered_frozen_slotted_and_exact(self) -> None:
        package_ref = CapabilityPackageRef("example.package", "1.0.0")
        suite_ref = BenchmarkSuiteRef("example.suite", "1.0.0")
        resource = ResourceIdentity(
            "example.resource",
            "text/plain",
            "a" * 64,
        )

        self.assertEqual(package_ref.selector, "example.package@1.0.0")
        self.assertEqual(suite_ref.selector, "example.suite@1.0.0")
        self.assertLess(
            CapabilityPackageRef("example.alpha", "1.0.0"),
            package_ref,
        )
        self.assertFalse(hasattr(package_ref, "__dict__"))
        self.assertFalse(hasattr(suite_ref, "__dict__"))
        self.assertFalse(hasattr(resource, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            resource.sha256 = "b" * 64  # type: ignore[misc]

    def test_rejects_shared_invalid_fixtures(self) -> None:
        for name in (
            "invalid-duplicate-refs.json",
            "invalid-unknown-field.json",
            "invalid-unsorted-refs.json",
            "invalid-digest-shape.json",
            "invalid-forbidden-command.json",
            "invalid-forbidden-executable.json",
            "invalid-forbidden-prompt.json",
            "invalid-forbidden-credentials.json",
            "invalid-forbidden-environment.json",
            "invalid-forbidden-provider.json",
        ):
            with (
                self.subTest(name=name),
                self.assertRaises(CapabilityPackageProtocolError),
            ):
                validate_capability_package_manifest(fixture(name))

    def test_rejects_every_forbidden_authority_field_without_echoing_values(
        self,
    ) -> None:
        sentinel = "SECRET-AUTHORITY-VALUE"
        for forbidden in (
            "command",
            "executable",
            "prompt",
            "credentials",
            "environment",
            "provider",
        ):
            with (
                self.subTest(forbidden=forbidden),
                self.assertRaises(CapabilityPackageProtocolError) as caught,
            ):
                validate_capability_package_manifest(
                    {**VALID, forbidden: sentinel}
                )
            self.assertNotIn(sentinel, str(caught.exception))

    def test_rejects_invalid_nested_ref_and_resource_shapes(self) -> None:
        cases = {
            "legacy-protocol": {
                **VALID,
                "protocol": "dci." + "package/v1",
            },
            "invalid-package-id": {
                **VALID,
                "package_id": "Example Package",
            },
            "invalid-version": {
                **VALID,
                "version": "1",
            },
            "unknown-capability-ref-field": {
                **VALID,
                "capabilities": [
                    {
                        "capability_id": "example.alpha",
                        "version": "1.0.0",
                        "provider": "SECRET",
                    }
                ],
            },
            "unknown-suite-ref-field": {
                **VALID,
                "benchmark_suites": [
                    {
                        "suite_id": "example.benchmark",
                        "version": "1.0.0",
                        "command": "SECRET",
                    }
                ],
            },
            "unknown-resource-field": {
                **VALID,
                "resources": [
                    {
                        "resource_id": "example.public-config",
                        "media_type": "application/json",
                        "sha256": "a" * 64,
                        "path": "SECRET",
                    }
                ],
            },
            "invalid-media-type": {
                **VALID,
                "resources": [
                    {
                        "resource_id": "example.public-config",
                        "media_type": "not-a-media-type",
                        "sha256": "a" * 64,
                    }
                ],
            },
            "duplicate-resource": {
                **VALID,
                "resources": [
                    {
                        "resource_id": "example.public-config",
                        "media_type": "application/json",
                        "sha256": "a" * 64,
                    },
                    {
                        "resource_id": "example.public-config",
                        "media_type": "application/json",
                        "sha256": "a" * 64,
                    },
                ],
            },
        }

        for label, value in cases.items():
            with (
                self.subTest(label=label),
                self.assertRaises(CapabilityPackageProtocolError),
            ):
                validate_capability_package_manifest(value)

    def test_canonical_schema_is_closed_and_declares_canonical_arrays(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "protocol",
                "package_id",
                "version",
                "capabilities",
                "benchmark_suites",
                "resources",
            },
        )
        self.assertEqual(
            schema["properties"]["protocol"]["const"],
            CAPABILITY_PACKAGE_PROTOCOL_VERSION,
        )
        for field in ("capabilities", "benchmark_suites", "resources"):
            with self.subTest(field=field):
                self.assertTrue(
                    schema["properties"][field]["x-asterion-sorted-unique"]
                )
                self.assertTrue(schema["properties"][field]["uniqueItems"])
        self.assertEqual(
            schema["$defs"]["resource"]["properties"]["sha256"]["pattern"],
            "^[0-9a-f]{64}$",
        )

    def test_builtin_descriptors_declare_exact_current_closures(self) -> None:
        cases = (
            (
                "controlled_code/capability-package.json",
                CapabilityPackageRef("controlled-code", "1.0.0"),
                (
                    CapabilityRef("evaluation.code-quality", "1.0.0"),
                    CapabilityRef(
                        "observability.execution-audit",
                        "1.0.0",
                    ),
                    CapabilityRef(
                        "policy.controlled-code-check",
                        "1.0.0",
                    ),
                    CapabilityRef("workflow.code-quality", "1.0.0"),
                ),
            ),
            (
                "dci_research/capability-package.json",
                CapabilityPackageRef("dci", "1.0.0"),
                (
                    CapabilityRef("dci.analysis", "1.0.0"),
                    CapabilityRef("dci.benchmark", "1.0.0"),
                    CapabilityRef("dci.evaluation", "1.0.0"),
                    CapabilityRef("dci.export", "1.0.0"),
                    CapabilityRef("dci.research", "1.0.0"),
                    CapabilityRef("policy.local-corpus", "1.0.0"),
                    CapabilityRef("protocol.observability", "1.0.0"),
                ),
            ),
        )

        for relative_path, package_ref, capabilities in cases:
            with self.subTest(package=package_ref.selector):
                value = json.loads(
                    (SOURCE / "capabilities" / relative_path).read_text(
                        encoding="utf-8"
                    )
                )
                manifest = validate_capability_package_manifest(value)
                self.assertEqual(manifest.package_ref, package_ref)
                self.assertEqual(manifest.capabilities, capabilities)
                self.assertEqual(manifest.benchmark_suites, ())
                self.assertEqual(manifest.resources, ())


if __name__ == "__main__":
    unittest.main()
