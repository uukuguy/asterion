from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import Mock

from asterion.capabilities.builtin import builtin_capability_sources
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import CapabilityPackagePayloadError
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilityPackageSource,
    BuiltinCapabilitySourceError,
)


class BuiltinCapabilitySourceTests(unittest.TestCase):
    def test_registration_table_is_explicit_immutable_and_includes_dci(
        self,
    ) -> None:
        registrations = builtin_capability_sources()

        self.assertIs(type(registrations), tuple)
        self.assertEqual(
            tuple(registration.package_ref for registration in registrations),
            (
                CapabilityPackageRef("controlled-code", "1.0.0"),
                CapabilityPackageRef("dci", "1.0.0"),
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            registrations[0].payload_root = Path("other")  # type: ignore[misc]

    def test_discovery_does_not_validate_payload_or_call_provider_factory(
        self,
    ) -> None:
        registration = builtin_capability_sources()[0]
        provider_factory = Mock(
            side_effect=AssertionError("provider factory called during discovery")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = Path(temp_dir) / "payload"
            shutil.copytree(registration.payload_root, payload_root)
            descriptor_path = payload_root / "capability-package.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["capabilities"].append(
                {"capability_id": "missing.member", "version": "1.0.0"}
            )
            descriptor["capabilities"].sort(
                key=lambda item: (item["capability_id"], item["version"])
            )
            descriptor_path.write_text(
                json.dumps(descriptor, sort_keys=True, separators=(",", ":")) + "\n"
            )
            source = BuiltinCapabilityPackageSource(
                (
                    replace(
                        registration,
                        payload_root=payload_root,
                        provider_factory=provider_factory,
                    ),
                )
            )

            candidates = source.discover_metadata()

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].package_ref, registration.package_ref)
            self.assertEqual(candidates[0].source_kind, "builtin")
            self.assertIsNone(candidates[0].payload_sha256)
            self.assertEqual(dict(candidates[0].metadata), {})
            provider_factory.assert_not_called()
            with self.assertRaises(CapabilityPackagePayloadError):
                source.open_payload(candidates[0])
            with self.assertRaises(CapabilityPackagePayloadError):
                source.load_provider(candidates[0])
            provider_factory.assert_not_called()

    def test_valid_payload_and_provider_are_bound_to_the_same_exact_identity(
        self,
    ) -> None:
        source = BuiltinCapabilityPackageSource()
        candidate = source.discover_metadata()[0]

        payload = source.open_payload(candidate)
        source.validate_source_identity(candidate, payload)
        installed = source.load_provider(candidate)

        self.assertEqual(installed.package_ref, candidate.package_ref)
        self.assertEqual(installed.payload_sha256, payload.payload_sha256)
        self.assertEqual(installed.source_id, candidate.source_id)
        self.assertEqual(installed.source_kind, "builtin")
        self.assertTrue(installed.catalog_roots)
        self.assertTrue(installed.implementations)

    def test_provider_identity_mismatch_fails_closed(self) -> None:
        registration = builtin_capability_sources()[0]
        valid = registration.provider_factory()
        mismatches = (
            replace(
                valid,
                package_ref=CapabilityPackageRef("other.package", "1.0.0"),
            ),
            replace(valid, payload_sha256="0" * 64),
            replace(valid, source_id="builtin.other.package.1.0.0"),
            replace(valid, source_kind="local-directory"),
        )
        for installed in mismatches:
            with self.subTest(installed=installed):
                source = BuiltinCapabilityPackageSource(
                    (
                        replace(
                            registration,
                            provider_factory=_factory(installed),
                        ),
                    )
                )
                candidate = source.discover_metadata()[0]
                with self.assertRaises(BuiltinCapabilitySourceError):
                    source.load_provider(candidate)

    def test_provider_resources_cannot_escape_the_validated_payload(
        self,
    ) -> None:
        registration = builtin_capability_sources()[0]
        valid = registration.provider_factory()
        with tempfile.TemporaryDirectory() as temp_dir:
            escaped = replace(
                valid,
                catalog_roots=(Path(temp_dir).resolve(),),
            )
            source = BuiltinCapabilityPackageSource(
                (
                    replace(
                        registration,
                        provider_factory=_factory(escaped),
                    ),
                )
            )

            with self.assertRaises(BuiltinCapabilitySourceError):
                source.load_provider(source.discover_metadata()[0])

    def test_unknown_or_forged_candidate_is_rejected_without_provider_load(
        self,
    ) -> None:
        registration = builtin_capability_sources()[0]
        provider_factory = Mock(
            side_effect=AssertionError("unselected provider factory called")
        )
        source = BuiltinCapabilityPackageSource(
            (replace(registration, provider_factory=provider_factory),)
        )
        candidate = source.discover_metadata()[0]

        forged = replace(candidate, source_id="builtin.forged.1.0.0")
        for operation in (
            source.open_payload,
            lambda value: source.validate_source_identity(
                value, source.open_payload(candidate)
            ),
            source.load_provider,
        ):
            with (
                self.subTest(operation=operation),
                self.assertRaises(BuiltinCapabilitySourceError),
            ):
                operation(forged)
        provider_factory.assert_not_called()


def _factory(
    installed: InstalledCapabilityPackage,
):
    def create() -> InstalledCapabilityPackage:
        return installed

    return create


if __name__ == "__main__":
    unittest.main()
