from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from asterion.capabilities.builtin import (
    BuiltinCapabilityRegistration,
    builtin_capability_sources,
)
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.resolution import resolve_capability_source
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilitySource,
    BuiltinCapabilitySourceError,
)
from asterion.capability_sdk import run_capability_conformance


CONTROLLED_CODE = CapabilityPackageRef("controlled-code", "1.0.0")
DCI = CapabilityPackageRef("dci", "1.0.0")
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "extensions" / "minimal" / "payload"


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _rewrite_package_ref(payload_root: Path, package_ref: CapabilityPackageRef) -> None:
    descriptor = json.loads((payload_root / "capability-package.json").read_text())
    descriptor["package_id"] = package_ref.package_id
    descriptor["version"] = package_ref.version
    for suite_path in (payload_root / "benchmark-suites").glob("*.json"):
        suite = json.loads(suite_path.read_text())
        suite["owner_package"] = {
            "package_id": package_ref.package_id,
            "version": package_ref.version,
        }
        suite_path.write_bytes(_canonical_json(suite))
    (payload_root / "capability-package.json").write_bytes(_canonical_json(descriptor))


def _installed_package(
    package_ref: CapabilityPackageRef,
    *,
    payload_sha256: str,
    source_id: str,
    source_kind: str = "builtin",
) -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256=payload_sha256,
        source_id=source_id,
        source_kind=source_kind,
        catalog_roots=(Path("/private/catalog"),),
        benchmark_suite_paths=(),
        implementations=(),
        benchmark_bindings=(),
    )


class BuiltinCapabilitySourceTests(unittest.TestCase):
    def test_builtin_registration_table_is_explicit(self) -> None:
        registrations = builtin_capability_sources()

        self.assertEqual(
            tuple(item.package_ref for item in registrations),
            (CONTROLLED_CODE, DCI),
        )
        self.assertNotIn(
            CapabilityPackageRef("dci-agent-lite", "1.0.0"),
            tuple(item.package_ref for item in registrations),
        )
        with self.assertRaises((AttributeError, TypeError)):
            setattr(registrations[0], "payload_root", Path("/private"))

    def test_discovery_is_metadata_only_and_never_calls_provider_factory(self) -> None:
        called = Mock(side_effect=AssertionError("SECRET-FACTORY-CALLED"))
        registration = BuiltinCapabilityRegistration(
            package_ref=CONTROLLED_CODE,
            payload_root=builtin_capability_sources()[0].payload_root,
            provider_factory=called,
        )

        candidates = BuiltinCapabilitySource((registration,)).discover_metadata()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].package_ref, CONTROLLED_CODE)
        self.assertEqual(candidates[0].source_id, "controlled-code.builtin")
        self.assertEqual(candidates[0].source_kind, "builtin")
        self.assertIsNone(candidates[0].payload_sha256)
        called.assert_not_called()

    def test_corrupted_payload_fails_only_when_opened(self) -> None:
        sentinel = "SECRET-CORRUPTED-MEMBER"
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = Path(temp_dir).resolve() / "payload"
            shutil.copytree(FIXTURE_ROOT, payload_root)
            package_ref = CapabilityPackageRef("example.builtin", "1.0.0")
            _rewrite_package_ref(payload_root, package_ref)
            (payload_root / "resources" / "example.conformance").write_text(sentinel)
            source = BuiltinCapabilitySource(
                (
                    BuiltinCapabilityRegistration(
                        package_ref=package_ref,
                        payload_root=payload_root,
                        provider_factory=lambda: _installed_package(
                            package_ref,
                            payload_sha256="0" * 64,
                            source_id="example.builtin.builtin",
                        ),
                    ),
                )
            )

            candidate = source.discover_metadata()[0]
            with self.assertRaises(BuiltinCapabilitySourceError) as raised:
                source.open_payload(candidate)

        self.assertEqual(str(raised.exception), "built-in capability source is invalid")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(sentinel, repr(raised.exception))

    def test_selected_provider_load_requires_payload_and_installed_identity_agreement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = Path(temp_dir).resolve() / "payload"
            shutil.copytree(FIXTURE_ROOT, payload_root)
            package_ref = CapabilityPackageRef("example.builtin", "1.0.0")
            _rewrite_package_ref(payload_root, package_ref)
            source = BuiltinCapabilitySource(
                (
                    BuiltinCapabilityRegistration(
                        package_ref=package_ref,
                        payload_root=payload_root,
                        provider_factory=lambda: _installed_package(
                            package_ref,
                            payload_sha256="f" * 64,
                            source_id="example.builtin.builtin",
                        ),
                    ),
                )
            )
            candidate = resolve_capability_source(
                package_ref, source.discover_metadata(), None
            )
            payload = source.open_payload(candidate)

            with self.assertRaises(BuiltinCapabilitySourceError):
                source.load_provider(candidate)

            good_factory = Mock(
                return_value=_installed_package(
                    package_ref,
                    payload_sha256=payload.payload_sha256,
                    source_id="example.builtin.builtin",
                )
            )
            good_source = BuiltinCapabilitySource(
                (
                    BuiltinCapabilityRegistration(
                        package_ref=package_ref,
                        payload_root=payload_root,
                        provider_factory=good_factory,
                    ),
                )
            )

            installed = good_source.load_provider(
                resolve_capability_source(
                    package_ref, good_source.discover_metadata(), None
                )
            )

        self.assertEqual(installed.package_ref, package_ref)
        good_factory.assert_called_once_with()

    def test_duplicate_builtin_registrations_fail_closed_without_private_context(self) -> None:
        registration = builtin_capability_sources()[0]
        with self.assertRaises(BuiltinCapabilitySourceError) as raised:
            BuiltinCapabilitySource((registration, registration)).discover_metadata()

        self.assertEqual(str(raised.exception), "built-in capability source is invalid")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(str(registration.payload_root), repr(raised.exception))

    def test_candidate_digest_mismatch_is_rejected_after_payload_identity(self) -> None:
        registration = builtin_capability_sources()[0]
        source = BuiltinCapabilitySource((registration,))
        candidate = source.discover_metadata()[0]
        payload = source.open_payload(candidate)
        mismatched = type(candidate)(
            package_ref=candidate.package_ref,
            source_id=candidate.source_id,
            source_kind=candidate.source_kind,
            payload_sha256=hashlib.sha256(payload.payload_sha256.encode()).hexdigest(),
            metadata=candidate.metadata,
        )

        with self.assertRaises(BuiltinCapabilitySourceError):
            source.validate_source_identity(mismatched, payload)

    def test_every_builtin_has_portable_externalization_and_conformance(self) -> None:
        source = BuiltinCapabilitySource()

        for candidate in source.discover_metadata():
            with self.subTest(package=candidate.package_ref.package_id):
                payload = source.open_payload(candidate)
                self.assertEqual(
                    tuple(item.resource_id for item in payload.manifest.conformance),
                    ("externalization.json",),
                )
                installed = source.load_provider(candidate)
                result = run_capability_conformance(installed)
                self.assertTrue(result.passed, result.errors)


if __name__ == "__main__":
    unittest.main()
