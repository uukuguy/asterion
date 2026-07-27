from __future__ import annotations

import json
import unittest
from pathlib import Path

import asterion.assembly.protocol as assembly_protocol
from asterion.assembly.protocol import AssemblyError, validate_assembly_manifest
from asterion.capabilities.protocol import (
    CapabilityProtocolError,
    validate_capability_manifest,
)


FIXTURES = Path(__file__).parent / "fixtures"
VALID_APPLICATION_ASSEMBLY = {
    "protocol": "asterion.application-assembly/v1",
    "application_id": "example.application",
    "version": "1.0.0",
    "runtime_id": "example.runtime",
    "capability_packages": [
        {"package_id": "example.alpha", "version": "1.0.0"},
        {"package_id": "example.package", "version": "1.0.0"},
    ],
    "capabilities": [
        {"capability_id": "example.alpha", "version": "1.0.0"},
        {"capability_id": "example.research", "version": "1.0.0"},
    ],
    "host_capabilities": [],
    "host_policies": [],
    "host_events": [],
    "host_artifacts": [],
}


def fixture(protocol: str, name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / protocol / "v1" / name).read_text())
    assert isinstance(value, dict)
    return value


class ProtocolCanonicalOrderingTests(unittest.TestCase):
    def test_uses_the_asterion_application_assembly_identity(self) -> None:
        self.assertEqual(
            getattr(
                assembly_protocol,
                "APPLICATION_ASSEMBLY_PROTOCOL_VERSION",
                None,
            ),
            "asterion.application-assembly/v1",
        )
        try:
            validate_assembly_manifest(VALID_APPLICATION_ASSEMBLY)
        except AssemblyError as error:
            self.fail(f"new application assembly was rejected: {error}")

    def test_rejects_the_legacy_assembly_contract(self) -> None:
        legacy = {
            "protocol": "dci." + "assembly/v1",
            "application_id": "example.application",
            "version": "1.0.0",
            "runtime_id": "example.runtime",
            "packages": [
                {"package_id": "example.research", "version": "1.0.0"},
            ],
            "host_capabilities": [],
            "host_policies": [],
            "host_events": [],
            "host_artifacts": [],
        }

        with self.assertRaises(AssemblyError):
            validate_assembly_manifest(legacy)

    def test_rejects_legacy_assembly_field_and_capability_ref_names(self) -> None:
        cases = {
            "packages-field": {
                key: value
                for key, value in VALID_APPLICATION_ASSEMBLY.items()
                if key != "capabilities"
            }
            | {
                "packages": [
                    {
                        "capability_id": "example.research",
                        "version": "1.0.0",
                    }
                ]
            },
            "package-id-capability-member": {
                **VALID_APPLICATION_ASSEMBLY,
                "capabilities": [
                    {"package_id": "example.research", "version": "1.0.0"}
                ],
            },
        }

        for name, value in cases.items():
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                validate_assembly_manifest(value)

    def test_rejects_each_unsorted_application_assembly_ref_array(self) -> None:
        try:
            validate_assembly_manifest(VALID_APPLICATION_ASSEMBLY)
        except AssemblyError as error:
            self.fail(f"canonical application assembly was rejected: {error}")
        for field in ("capability_packages", "capabilities"):
            with self.subTest(field=field), self.assertRaises(AssemblyError):
                validate_assembly_manifest(
                    {
                        **VALID_APPLICATION_ASSEMBLY,
                        field: list(reversed(VALID_APPLICATION_ASSEMBLY[field])),
                    }
                )

    def test_accepts_shared_valid_capability_ordering_fixture(self) -> None:
        validate_capability_manifest(
            fixture("capabilities", "valid-unicode-scalar-order.json")
        )

    def test_rejects_shared_invalid_capability_ordering_fixtures(self) -> None:
        for name in (
            "invalid-unsorted-edge.json",
            "invalid-unicode-scalar-order.json",
            "invalid-surrogate-edge.json",
            "invalid-line-terminator-surrogate-edge.json",
        ):
            with self.subTest(name=name), self.assertRaises(CapabilityProtocolError):
                validate_capability_manifest(fixture("capabilities", name))

    def test_accepts_shared_valid_assembly_ordering_fixture(self) -> None:
        validate_assembly_manifest(
            fixture("application_assembly", "valid-canonical-order.json")
        )

    def test_rejects_shared_invalid_assembly_ordering_fixtures(self) -> None:
        for name in (
            "invalid-interpolated-capability-package-ref-order.json",
            "invalid-interpolated-capability-ref-order.json",
            "invalid-unicode-scalar-order.json",
            "invalid-surrogate-edge.json",
            "invalid-line-terminator-surrogate-edge.json",
        ):
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                validate_assembly_manifest(fixture("application_assembly", name))


if __name__ == "__main__":
    unittest.main()
