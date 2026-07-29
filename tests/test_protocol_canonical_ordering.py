from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.assembly.protocol import (
    APPLICATION_ASSEMBLY_PROTOCOL_VERSION,
    AssemblyError,
    validate_assembly_manifest,
)
from asterion.capabilities.protocol import (
    CapabilityProtocolError,
    validate_capability_manifest,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(protocol: str, name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / protocol / "v1" / name).read_text())
    assert isinstance(value, dict)
    return value


class ProtocolCanonicalOrderingTests(unittest.TestCase):
    def application_assembly(self) -> dict[str, object]:
        return {
            "protocol": "asterion.application-assembly/v1",
            "application_id": "example.research",
            "version": "1.0.0",
            "runtime_id": "example.runtime",
            "capability_packages": [
                {"package_id": "example", "version": "1.0.0"},
                {"package_id": "example.extension", "version": "1.0.0"},
            ],
            "capabilities": [
                {"capability_id": "example.policy", "version": "1.0.0"},
                {"capability_id": "example.research", "version": "1.0.0"},
            ],
            "host_capabilities": [],
            "host_policies": [],
            "host_events": [],
            "host_artifacts": [],
        }

    def test_uses_asterion_application_assembly_protocol_identity(self) -> None:
        self.assertEqual(
            APPLICATION_ASSEMBLY_PROTOCOL_VERSION,
            "asterion.application-assembly/v1",
        )
        validate_assembly_manifest(self.application_assembly())

    def test_rejects_removed_assembly_protocol_and_fields(self) -> None:
        valid = self.application_assembly()
        cases = {
            "old-protocol": {**valid, "protocol": "dci.assembly/v1"},
            "old-packages-field": {
                key: value
                for key, value in {
                    **valid,
                    "packages": valid["capabilities"],
                }.items()
                if key != "capabilities"
            },
            "package-id-capability-member": {
                **valid,
                "capabilities": [
                    {"package_id": "example.policy", "version": "1.0.0"}
                ],
            },
        }
        for name, manifest in cases.items():
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                validate_assembly_manifest(manifest)

    def test_rejects_each_noncanonical_assembly_ref_array_independently(self) -> None:
        valid = self.application_assembly()
        cases = {
            "capability-packages": {
                **valid,
                "capability_packages": list(reversed(valid["capability_packages"])),
            },
            "capabilities": {
                **valid,
                "capabilities": list(reversed(valid["capabilities"])),
            },
        }
        for name, manifest in cases.items():
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                validate_assembly_manifest(manifest)

    def test_returns_a_deep_immutable_assembly_snapshot(self) -> None:
        source = self.application_assembly()
        try:
            validated = validate_assembly_manifest(source)
        except AssemblyError:
            self.fail("new application assembly wire contract was rejected")

        source["capabilities"].append(
            {"capability_id": "z.changed", "version": "1.0.0"}
        )
        self.assertEqual(len(validated["capabilities"]), 2)
        with self.assertRaises(TypeError):
            validated["capabilities"][0]["capability_id"] = "z.changed"

    def test_accepts_shared_valid_capability_ordering_fixture(self) -> None:
        validate_capability_manifest(
            fixture("capabilities", "valid-unicode-scalar-order.json")
        )

    def test_rejects_shared_invalid_capability_ordering_fixtures(self) -> None:
        for name in (
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
            "invalid-interpolated-package-ref-order.json",
            "invalid-unicode-scalar-order.json",
            "invalid-surrogate-edge.json",
            "invalid-line-terminator-surrogate-edge.json",
        ):
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                validate_assembly_manifest(fixture("application_assembly", name))


if __name__ == "__main__":
    unittest.main()
