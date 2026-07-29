from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CAPABILITY_PACKAGE_PROTOCOL_VERSION,
    CapabilityPackageManifest,
    CapabilityPackageProtocolError,
    CapabilityPackageRef,
    ResourceIdentity,
    validate_capability_package_manifest,
)
from asterion.capabilities.catalog import CapabilityRef


FIXTURES = Path(__file__).parent / "fixtures" / "capability_packages" / "v1"
SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "capability-packages"
    / "v1"
    / "capability-package.schema.json"
)
CONTROLLED_CODE_DESCRIPTOR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "asterion"
    / "capabilities"
    / "controlled_code"
    / "capability-package.json"
)
DCI_DESCRIPTOR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "asterion"
    / "capabilities"
    / "dci_research"
    / "capability-package.json"
)


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


VALID = fixture("valid-minimal.json")


class CapabilityPackageProtocolTests(unittest.TestCase):
    def test_protocol_identity_is_asterion_owned(self) -> None:
        self.assertEqual(
            CAPABILITY_PACKAGE_PROTOCOL_VERSION,
            "asterion.capability-package/v1",
        )

    def test_validates_a_portable_immutable_package_snapshot(self) -> None:
        value = fixture("valid-minimal.json")
        manifest = validate_capability_package_manifest(value)

        self.assertEqual(
            manifest,
            CapabilityPackageManifest(
                package_ref=CapabilityPackageRef("example.package", "1.0.0"),
                capabilities=(CapabilityRef("example.research", "1.0.0"),),
                benchmark_suites=(),
                resources=(
                    ResourceIdentity(
                        resource_id="example.conformance",
                        media_type="application/json",
                        sha256="a" * 64,
                    ),
                ),
            ),
        )
        with self.assertRaises(AttributeError):
            manifest.capabilities += (CapabilityRef("example.other", "1.0.0"),)
        capabilities = value["capabilities"]
        assert isinstance(capabilities, list)
        capability = capabilities[0]
        assert isinstance(capability, dict)
        capability["capability_id"] = "example.changed"
        self.assertEqual(manifest.capabilities, (CapabilityRef("example.research", "1.0.0"),))

    def test_schema_is_closed_and_has_no_payload_digest(self) -> None:
        schema = json.loads(SCHEMA.read_text())

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["required"],
            [
                "protocol",
                "package_id",
                "version",
                "capabilities",
                "benchmark_suites",
                "resources",
            ],
        )
        self.assertNotIn("payload_sha256", schema["properties"])
        self.assertEqual(
            schema["properties"]["benchmark_suites"]["items"],
            {"$ref": "#/$defs/benchmark_suite_ref"},
        )
        self.assertTrue(schema["properties"]["benchmark_suites"]["uniqueItems"])
        self.assertIn("benchmark_suite_ref", schema["$defs"])

    def test_accepts_sorted_unique_exact_benchmark_suite_refs(self) -> None:
        value = fixture("valid-minimal.json")
        value["benchmark_suites"] = [
            {"suite_id": "example.alpha", "version": "1.0.0"},
            {"suite_id": "example.zebra", "version": "2.0.0"},
        ]
        manifest = validate_capability_package_manifest(value)

        self.assertEqual(
            manifest.benchmark_suites,
            (
                BenchmarkSuiteRef("example.alpha", "1.0.0"),
                BenchmarkSuiteRef("example.zebra", "2.0.0"),
            ),
        )
        suites = value["benchmark_suites"]
        assert isinstance(suites, list)
        first = suites[0]
        assert isinstance(first, dict)
        first["suite_id"] = "changed"
        self.assertEqual(manifest.benchmark_suites[0].suite_id, "example.alpha")

    def test_rejects_noncanonical_benchmark_suite_refs(self) -> None:
        valid = fixture("valid-minimal.json")
        suite = {"suite_id": "example.suite", "version": "1.0.0"}
        for suites in (
            [suite, suite],
            [
                {"suite_id": "example.zebra", "version": "1.0.0"},
                {"suite_id": "example.alpha", "version": "1.0.0"},
            ],
        ):
            with self.subTest(suites=suites), self.assertRaises(
                CapabilityPackageProtocolError
            ):
                validate_capability_package_manifest(
                    {**valid, "benchmark_suites": suites}
                )

    def test_rejects_shared_invalid_fixtures(self) -> None:
        for name in (
            "invalid-duplicate-capability.json",
            "invalid-duplicate-resource.json",
            "invalid-duplicate-resource-id.json",
            "invalid-benchmark-suite.json",
            "invalid-unknown-field.json",
            "invalid-unsorted-capabilities.json",
            "invalid-unsorted-resources.json",
            "invalid-digest-shape.json",
            "invalid-payload-digest.json",
        ):
            with self.subTest(name=name), self.assertRaises(
                CapabilityPackageProtocolError
            ):
                validate_capability_package_manifest(fixture(name))

    def test_rejects_forbidden_authority_fields(self) -> None:
        for forbidden in (
            "command",
            "executable",
            "prompt",
            "credentials",
            "environment",
            "provider",
        ):
            with self.subTest(forbidden=forbidden), self.assertRaises(
                CapabilityPackageProtocolError
            ):
                validate_capability_package_manifest({**VALID, forbidden: "SECRET"})

    def test_rejects_path_fields(self) -> None:
        for forbidden in ("path", "resource_root"):
            with self.subTest(forbidden=forbidden), self.assertRaises(
                CapabilityPackageProtocolError
            ):
                validate_capability_package_manifest({**VALID, forbidden: "/private"})

    def test_errors_do_not_include_manifest_bodies(self) -> None:
        with self.assertRaises(CapabilityPackageProtocolError) as raised:
            validate_capability_package_manifest({**VALID, "command": "SECRET"})

        self.assertNotIn("SECRET", str(raised.exception))

    def test_builtin_descriptors_are_exact_portable_closures(self) -> None:
        controlled_code = validate_capability_package_manifest(
            json.loads(CONTROLLED_CODE_DESCRIPTOR.read_text())
        )
        dci = validate_capability_package_manifest(json.loads(DCI_DESCRIPTOR.read_text()))

        self.assertEqual(
            controlled_code.package_ref,
            CapabilityPackageRef("controlled-code", "1.0.0"),
        )
        self.assertEqual(
            controlled_code.capabilities,
            (
                CapabilityRef("evaluation.code-quality", "1.0.0"),
                CapabilityRef("observability.execution-audit", "1.0.0"),
                CapabilityRef("policy.controlled-code-check", "1.0.0"),
                CapabilityRef("workflow.code-quality", "1.0.0"),
            ),
        )
        self.assertEqual(
            dci.package_ref,
            CapabilityPackageRef("dci", "1.0.0"),
        )
        self.assertEqual(
            dci.capabilities,
            (
                CapabilityRef("dci.analysis", "1.0.0"),
                CapabilityRef("dci.benchmark", "1.0.0"),
                CapabilityRef("dci.evaluation", "1.0.0"),
                CapabilityRef("dci.export", "1.0.0"),
                CapabilityRef("dci.research", "1.0.0"),
                CapabilityRef("policy.local-corpus", "1.0.0"),
                CapabilityRef("protocol.observability", "1.0.0"),
            ),
        )
        self.assertEqual(controlled_code.benchmark_suites, ())
        self.assertEqual(dci.benchmark_suites, ())
        self.assertEqual(controlled_code.resources, ())
        self.assertEqual(dci.resources, ())


if __name__ == "__main__":
    unittest.main()
