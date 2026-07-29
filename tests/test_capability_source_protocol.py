from __future__ import annotations

import json
import operator
import unittest
from pathlib import Path
from typing import cast

from asterion.capability_packages.protocol import (
    CAPABILITY_LOCK_PROTOCOL_VERSION,
    CAPABILITY_SOURCE_PROTOCOL_VERSION,
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    CapabilitySourceProtocolError,
    validate_capability_source_declaration,
    validate_capability_source_lock,
)


FIXTURES = Path(__file__).parent / "fixtures" / "capability_source" / "v1"
SCHEMAS = (
    Path(__file__).resolve().parents[1] / "schemas" / "capability-source" / "v1"
)


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


class CapabilitySourceProtocolTests(unittest.TestCase):
    def test_validates_a_public_source_declaration(self) -> None:
        source = validate_capability_source_declaration(fixture("valid-source.json"))

        self.assertEqual(CAPABILITY_SOURCE_PROTOCOL_VERSION, "asterion.capability-source/v1")
        self.assertEqual(
            source.public_projection,
            {
                "source_id": "example.source",
                "kind": "local-directory",
                "package_ref": {
                    "package_id": "example.package",
                    "version": "1.0.0",
                },
                "payload_sha256": "a" * 64,
            },
        )
        with self.assertRaises(TypeError):
            operator.setitem(
                cast(dict[str, object], source.public_projection),
                "source_id",
                "changed",
            )

    def test_private_locator_is_deeply_immutable_and_never_public(self) -> None:
        private = {
            "root": "/private/operator/package",
            "provider_factory": "private.module:create",
            "options": ["SECRET"],
        }
        source = CapabilitySourceDeclaration(
            source_id="example.source",
            kind="local-directory",
            package_ref=CapabilityPackageRef("example.package", "1.0.0"),
            payload_sha256="a" * 64,
            private_locator=private,
        )
        private["root"] = "/changed"
        options = private["options"]
        assert isinstance(options, list)
        options.append("changed")

        rendered = repr(source)
        public = source.public_projection
        private_locator = cast(dict[str, object], source.private_locator)
        self.assertNotIn("/private/operator/package", rendered)
        self.assertNotIn("private.module:create", rendered)
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("private_locator", public)
        self.assertNotIn("/private/operator/package", repr(public))
        self.assertEqual(private_locator["root"], "/private/operator/package")
        self.assertEqual(private_locator["options"], ("SECRET",))
        with self.assertRaises(TypeError):
            operator.setitem(private_locator, "root", "/changed")

    def test_rejects_private_or_authority_fields_in_public_document(self) -> None:
        with self.assertRaises(CapabilitySourceProtocolError):
            validate_capability_source_declaration(
                fixture("invalid-private-public-field.json")
            )
        valid = fixture("valid-source.json")
        for forbidden in (
            "locator",
            "path",
            "provider_factory",
            "registry",
            "version_range",
            "latest",
            "precedence",
            "command",
            "environment",
        ):
            with self.subTest(forbidden=forbidden), self.assertRaises(
                CapabilitySourceProtocolError
            ):
                validate_capability_source_declaration(
                    {**valid, forbidden: "SECRET"}
                )

    def test_rejects_registry_as_a_public_source_kind(self) -> None:
        with self.assertRaises(CapabilitySourceProtocolError):
            validate_capability_source_declaration(
                fixture("invalid-registry-kind.json")
            )

    def test_validates_an_exact_immutable_source_lock(self) -> None:
        value = fixture("valid-lock.json")
        lock = validate_capability_source_lock(value)

        self.assertEqual(CAPABILITY_LOCK_PROTOCOL_VERSION, "asterion.capability-lock/v1")
        self.assertEqual(
            lock,
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=CapabilityPackageRef(
                            "example.package",
                            "1.0.0",
                        ),
                        payload_sha256="a" * 64,
                        source_id="example.source",
                    ),
                )
            ),
        )
        entries = value["entries"]
        assert isinstance(entries, list)
        entry = entries[0]
        assert isinstance(entry, dict)
        entry["source_id"] = "changed"
        self.assertEqual(lock.entries[0].source_id, "example.source")
        with self.assertRaises(AttributeError):
            setattr(lock, "entries", lock.entries + lock.entries)

    def test_rejects_duplicate_unsorted_and_malformed_lock_entries(self) -> None:
        with self.assertRaises(CapabilitySourceProtocolError):
            validate_capability_source_lock(fixture("invalid-duplicate-lock.json"))
        valid_entry = fixture("valid-lock.json")["entries"]
        assert isinstance(valid_entry, list)
        first = valid_entry[0]
        assert isinstance(first, dict)
        other = {
            **first,
            "package_ref": {
                "package_id": "another.package",
                "version": "1.0.0",
            },
        }
        for entries in (
            [first, other],
            [{**first, "payload_sha256": "not-a-digest"}],
            [
                first,
                {
                    **first,
                    "payload_sha256": "b" * 64,
                    "source_id": "other.source",
                },
            ],
        ):
            with self.subTest(entries=entries), self.assertRaises(
                CapabilitySourceProtocolError
            ):
                validate_capability_source_lock(
                    {
                        "protocol": "asterion.capability-lock/v1",
                        "entries": entries,
                    }
                )

    def test_errors_are_body_free(self) -> None:
        with self.assertRaises(CapabilitySourceProtocolError) as raised:
            validate_capability_source_declaration(
                {**fixture("valid-source.json"), "locator": "SECRET"}
            )

        self.assertNotIn("SECRET", str(raised.exception))

    def test_schemas_are_closed_and_declare_semantic_ordering(self) -> None:
        source_schema = json.loads((SCHEMAS / "source.schema.json").read_text())
        lock_schema = json.loads((SCHEMAS / "lock.schema.json").read_text())

        self.assertFalse(source_schema["additionalProperties"])
        self.assertFalse(lock_schema["additionalProperties"])
        self.assertIn("Unicode scalar", lock_schema["$comment"])
        self.assertNotIn("locator", source_schema["properties"])
        self.assertNotIn("path", source_schema["properties"])
        self.assertNotIn("provider_factory", source_schema["properties"])
        self.assertNotIn("registry", source_schema["properties"]["kind"]["enum"])


if __name__ == "__main__":
    unittest.main()
