from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.capability_packages.protocol import (
    CAPABILITY_LOCK_PROTOCOL_VERSION,
    CAPABILITY_SOURCE_PROTOCOL_VERSION,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    CapabilitySourceProtocolError,
    validate_capability_source_declaration,
    validate_capability_source_lock,
)


PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures/capability_source/v1"
SOURCE_SCHEMA = PROJECT / "schemas/capability-source/v1/source.schema.json"
LOCK_SCHEMA = PROJECT / "schemas/capability-source/v1/lock.schema.json"


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


VALID_SOURCE = fixture("valid-source.json")
VALID_LOCK = fixture("valid-lock.json")


class CapabilitySourceProtocolTests(unittest.TestCase):
    def test_accepts_operator_source_and_projects_only_safe_identity(self) -> None:
        declaration = validate_capability_source_declaration(VALID_SOURCE)

        self.assertEqual(
            CAPABILITY_SOURCE_PROTOCOL_VERSION,
            "asterion.capability-source/v1",
        )
        self.assertEqual(declaration.source_id, "example.local")
        self.assertEqual(declaration.kind, "local-directory")
        self.assertEqual(
            declaration.package_ref,
            CapabilityPackageRef("example.package", "1.0.0"),
        )
        self.assertEqual(
            dict(declaration.locator),
            {"root": "/operator/private/example-package"},
        )
        self.assertEqual(
            dict(declaration.provider_factory),
            {"module": "example.provider", "name": "create_provider"},
        )
        self.assertEqual(
            dict(declaration.public_projection),
            {
                "source_id": "example.local",
                "kind": "local-directory",
                "package": {
                    "package_id": "example.package",
                    "version": "1.0.0",
                },
                "payload_sha256": (
                    "0123456789abcdef0123456789abcdef"
                    "0123456789abcdef0123456789abcdef"
                ),
            },
        )

    def test_private_operator_values_are_immutable_and_repr_redacted(self) -> None:
        sentinel = "/operator/private/example-package"
        value = fixture("valid-source.json")
        declaration = validate_capability_source_declaration(value)

        locator = value["locator"]
        assert isinstance(locator, dict)
        locator["root"] = "/changed"
        factory = value["provider_factory"]
        assert isinstance(factory, dict)
        factory["module"] = "changed.module"

        self.assertEqual(declaration.locator["root"], sentinel)
        self.assertEqual(
            declaration.provider_factory["module"],
            "example.provider",
        )
        self.assertNotIn(sentinel, repr(declaration))
        self.assertNotIn("example.provider", repr(declaration))
        self.assertNotIn("locator", declaration.public_projection)
        self.assertNotIn("provider_factory", declaration.public_projection)
        self.assertFalse(hasattr(declaration, "__dict__"))
        with self.assertRaises(TypeError):
            declaration.locator["root"] = "/changed"  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            declaration.kind = "builtin"  # type: ignore[misc]

    def test_accepts_an_exact_canonical_source_lock(self) -> None:
        lock = validate_capability_source_lock(VALID_LOCK)

        self.assertEqual(
            CAPABILITY_LOCK_PROTOCOL_VERSION,
            "asterion.capability-lock/v1",
        )
        self.assertEqual(
            lock,
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=CapabilityPackageRef(
                            "example.alpha",
                            "1.0.0",
                        ),
                        payload_sha256="a" * 64,
                        source_id="example.alpha-source",
                    ),
                    CapabilitySourceLockEntry(
                        package_ref=CapabilityPackageRef(
                            "example.package",
                            "1.0.0",
                        ),
                        payload_sha256=(
                            "0123456789abcdef0123456789abcdef"
                            "0123456789abcdef0123456789abcdef"
                        ),
                        source_id="example.local",
                    ),
                )
            ),
        )
        self.assertFalse(hasattr(lock, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            lock.entries = ()  # type: ignore[misc]

    def test_rejects_shared_invalid_source_and_lock_fixtures(self) -> None:
        cases = (
            (
                validate_capability_source_declaration,
                "invalid-private-public-field.json",
            ),
            (
                validate_capability_source_lock,
                "invalid-duplicate-lock.json",
            ),
        )
        for validator, name in cases:
            with (
                self.subTest(name=name),
                self.assertRaises(CapabilitySourceProtocolError),
            ):
                validator(fixture(name))

    def test_rejects_private_or_malformed_values_without_echoing_them(
        self,
    ) -> None:
        sentinel = "SECRET-PRIVATE-LOCATOR"
        cases = {
            "unknown-kind": {**VALID_SOURCE, "kind": sentinel},
            "invalid-digest": {
                **VALID_SOURCE,
                "payload_sha256": sentinel,
            },
            "invalid-locator": {
                **VALID_SOURCE,
                "locator": {"root": sentinel, "nested": {"secret": sentinel}},
            },
            "unknown-source-field": {**VALID_SOURCE, "credentials": sentinel},
            "unknown-lock-field": {**VALID_LOCK, "locator": sentinel},
            "unsorted-lock": {
                **VALID_LOCK,
                "entries": list(reversed(VALID_LOCK["entries"])),
            },
        }
        for label, value in cases.items():
            validator = (
                validate_capability_source_lock
                if "lock" in label
                else validate_capability_source_declaration
            )
            with (
                self.subTest(label=label),
                self.assertRaises(CapabilitySourceProtocolError) as caught,
            ):
                validator(value)
            self.assertNotIn(sentinel, str(caught.exception))

    def test_all_reserved_source_kinds_and_unknown_digest_are_supported(
        self,
    ) -> None:
        for kind in (
            "archive",
            "builtin",
            "local-directory",
            "python-distribution",
            "registry",
        ):
            with self.subTest(kind=kind):
                declaration = validate_capability_source_declaration(
                    {
                        **VALID_SOURCE,
                        "kind": kind,
                        "payload_sha256": None,
                    }
                )
                self.assertEqual(declaration.kind, kind)
                self.assertIsNone(declaration.payload_sha256)

    def test_source_and_lock_schemas_are_closed_operator_contracts(self) -> None:
        source = json.loads(SOURCE_SCHEMA.read_text(encoding="utf-8"))
        lock = json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(source["additionalProperties"])
        self.assertEqual(
            source["properties"]["protocol"]["const"],
            CAPABILITY_SOURCE_PROTOCOL_VERSION,
        )
        self.assertEqual(
            set(source["required"]),
            {
                "protocol",
                "source_id",
                "kind",
                "package",
                "payload_sha256",
                "locator",
                "provider_factory",
            },
        )
        self.assertFalse(lock["additionalProperties"])
        self.assertEqual(
            lock["properties"]["protocol"]["const"],
            CAPABILITY_LOCK_PROTOCOL_VERSION,
        )
        self.assertEqual(
            lock["properties"]["entries"]["x-asterion-sorted-unique"],
            [
                "package.package_id",
                "package.version",
                "payload_sha256",
                "source_id",
            ],
        )
        self.assertTrue(lock["properties"]["entries"]["uniqueItems"])


if __name__ == "__main__":
    unittest.main()
