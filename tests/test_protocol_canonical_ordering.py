from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.assembly.protocol import AssemblyError, validate_assembly_manifest
from asterion.packages.protocol import (
    PackageProtocolError,
    validate_package_manifest,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(protocol: str, name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / protocol / "v1" / name).read_text())
    assert isinstance(value, dict)
    return value


class ProtocolCanonicalOrderingTests(unittest.TestCase):
    def test_accepts_shared_valid_package_ordering_fixture(self) -> None:
        validate_package_manifest(
            fixture("packages", "valid-unicode-scalar-order.json")
        )

    def test_rejects_shared_invalid_package_ordering_fixtures(self) -> None:
        for name in (
            "invalid-unicode-scalar-order.json",
            "invalid-surrogate-edge.json",
        ):
            with self.subTest(name=name), self.assertRaises(PackageProtocolError):
                validate_package_manifest(fixture("packages", name))

    def test_accepts_shared_valid_assembly_ordering_fixture(self) -> None:
        validate_assembly_manifest(fixture("assembly", "valid-canonical-order.json"))

    def test_rejects_shared_invalid_assembly_ordering_fixtures(self) -> None:
        for name in (
            "invalid-interpolated-package-ref-order.json",
            "invalid-unicode-scalar-order.json",
            "invalid-surrogate-edge.json",
        ):
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                validate_assembly_manifest(fixture("assembly", name))


if __name__ == "__main__":
    unittest.main()
