from __future__ import annotations

import unittest

from asterion.capability_packages import (
    CapabilityPackageCandidate,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
    load_prepared_capability_source,
    prepare_capability_source,
)
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource


PACKAGE = CapabilityPackageRef("dci", "1.0.0")
OTHER_DIGEST = "b" * 64


class RecordingSource:
    def __init__(
        self,
        source_id: str,
        payload: PortableCapabilityPayload,
        *,
        source_kind: str = "builtin",
    ) -> None:
        self.candidate = CapabilityPackageCandidate(
            package_ref=PACKAGE,
            source_id=source_id,
            source_kind=source_kind,
            payload_sha256=None,
            metadata={},
        )
        self.payload = payload
        self.discoveries = self.opens = self.loads = 0
        self.installed_digest = payload.payload_sha256

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        self.discoveries += 1
        return (self.candidate,)

    def open_payload(
        self, candidate: CapabilityPackageCandidate
    ) -> PortableCapabilityPayload:
        self.opens += 1
        if candidate is not self.candidate:
            raise RuntimeError("SECRET-CANDIDATE")
        return self.payload

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        if candidate != self.candidate or payload.manifest.package_ref != PACKAGE:
            raise RuntimeError("SECRET-IDENTITY")

    def load_provider(
        self, candidate: CapabilityPackageCandidate
    ) -> InstalledCapabilityPackage:
        self.loads += 1
        if candidate is not self.candidate:
            raise RuntimeError("SECRET-CANDIDATE")
        return InstalledCapabilityPackage(
            package_ref=PACKAGE,
            payload_sha256=self.installed_digest,
            source_id=candidate.source_id,
            source_kind=candidate.source_kind,
            catalog_roots=(),
            benchmark_suite_paths=(),
            implementations=(),
            benchmark_bindings=(),
        )


def payload() -> PortableCapabilityPayload:
    source = BuiltinCapabilitySource()
    candidate = next(
        value for value in source.discover_metadata() if value.package_ref == PACKAGE
    )
    return source.open_payload(candidate)


class CapabilitySourcePreparationTests(unittest.TestCase):
    def test_invalid_request_boundaries_fail_before_discovery(self) -> None:
        malformed_lock = object.__new__(CapabilitySourceLock)
        object.__setattr__(malformed_lock, "entries", (object(),))
        cases = (
            ("package", object(), ()),
            ("sources", PACKAGE, (object(),)),
            ("lock", PACKAGE, (), malformed_lock),
        )
        for case in cases:
            with self.subTest(case=case[0]):
                source = RecordingSource("selected", payload())
                package_ref = case[1]
                sources = case[2] if len(case) == 3 else (source,)
                lock = None if len(case) == 3 else case[3]
                with self.assertRaises(ValueError):
                    prepare_capability_source(package_ref, sources, lock)  # type: ignore[arg-type]
                self.assertEqual(source.discoveries, 0)

    def test_builtin_source_prepares_none_digest_as_payload_digest_without_loading(
        self,
    ) -> None:
        source = BuiltinCapabilitySource()

        prepared = prepare_capability_source(PACKAGE, (source,), None)

        self.assertIsNotNone(prepared.candidate.payload_sha256)
        self.assertEqual(
            prepared.candidate.payload_sha256, prepared.payload.payload_sha256
        )

    def test_without_lock_rejects_ambiguity_before_open_or_load(self) -> None:
        first, second = (
            RecordingSource("first", payload()),
            RecordingSource("second", payload()),
        )

        with self.assertRaises(ValueError) as raised:
            prepare_capability_source(PACKAGE, (first, second), None)

        self.assertEqual(str(raised.exception), "capability source preparation failed")
        self.assertEqual(
            (first.opens, second.opens, first.loads, second.loads), (0, 0, 0, 0)
        )

    def test_lock_opens_only_selected_identity_and_builtin_digest_is_normalized(
        self,
    ) -> None:
        first, second = (
            RecordingSource("first", payload()),
            RecordingSource("second", payload()),
        )
        lock = CapabilitySourceLock(
            entries=(
                CapabilitySourceLockEntry(
                    PACKAGE, second.payload.payload_sha256, "second"
                ),
            )
        )

        prepared = prepare_capability_source(PACKAGE, (first, second), lock)

        self.assertEqual(prepared.candidate.source_id, "second")
        self.assertEqual(
            prepared.candidate.payload_sha256, second.payload.payload_sha256
        )
        self.assertEqual(
            (first.opens, second.opens, first.loads, second.loads), (0, 1, 0, 0)
        )

    def test_load_rejects_payload_drift_before_provider_load(self) -> None:
        source = RecordingSource("selected", payload())
        prepared = prepare_capability_source(PACKAGE, (source,), None)
        source.payload = payload()
        source.payload = PortableCapabilityPayload(
            source.payload.manifest, OTHER_DIGEST, source.payload.resource_root
        )

        with self.assertRaises(ValueError) as raised:
            load_prepared_capability_source(prepared)

        self.assertEqual(str(raised.exception), "capability source preparation failed")
        self.assertEqual(source.loads, 0)

    def test_load_rejects_installed_identity_mismatch(self) -> None:
        source = RecordingSource("selected", payload())
        prepared = prepare_capability_source(PACKAGE, (source,), None)
        source.installed_digest = OTHER_DIGEST

        with self.assertRaises(ValueError) as raised:
            load_prepared_capability_source(prepared)

        self.assertEqual(str(raised.exception), "capability source preparation failed")

    def test_adapter_errors_are_redacted(self) -> None:
        source = RecordingSource("selected", payload())
        source.discover_metadata = lambda: (_ for _ in ()).throw(
            RuntimeError("SECRET-PATH")
        )  # type: ignore[method-assign]

        with self.assertRaises(ValueError) as raised:
            prepare_capability_source(PACKAGE, (source,), None)

        self.assertEqual(str(raised.exception), "capability source preparation failed")
        self.assertNotIn("SECRET-PATH", repr(raised.exception))
        self.assertIsNone(raised.exception.__context__)
