"""Tests for deterministic capability-package source selection."""

from __future__ import annotations

import unittest
from pathlib import Path

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.protocol import (
    CapabilityPackageManifest,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)
from asterion.capability_packages.resolution import (
    CapabilitySourceResolutionError,
    load_installed_capability_packages,
    resolve_capability_source,
)


class FixtureSource:
    def __init__(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
        installed: InstalledCapabilityPackage,
    ) -> None:
        self.candidate = candidate
        self.payload = payload
        self.installed = installed
        self.calls: list[str] = []

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        self.calls.append("discover")
        return (self.candidate,)

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        self.calls.append("open")
        self.assert_candidate(candidate)
        return self.payload

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        self.calls.append("validate")
        self.assert_candidate(candidate)
        if payload is not self.payload:
            raise AssertionError("unexpected payload")

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        self.calls.append("load")
        self.assert_candidate(candidate)
        return self.installed

    def assert_candidate(self, candidate: CapabilityPackageCandidate) -> None:
        if candidate is not self.candidate:
            raise AssertionError("unexpected candidate")


class CapabilitySourceResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package_ref = CapabilityPackageRef("example.package", "1.0.0")
        self.other_package_ref = CapabilityPackageRef("other.package", "1.0.0")
        self.digest = "a" * 64

    def _candidate(
        self,
        source_id: str,
        *,
        package_ref: CapabilityPackageRef | None = None,
        payload_sha256: str | None = None,
    ) -> CapabilityPackageCandidate:
        return CapabilityPackageCandidate(
            package_ref=package_ref or self.package_ref,
            source_id=source_id,
            source_kind="builtin",
            payload_sha256=payload_sha256 or self.digest,
            metadata={},
        )

    def _lock(
        self,
        source_id: str,
        payload_sha256: str | None = None,
    ) -> CapabilitySourceLock:
        return CapabilitySourceLock(
            entries=(
                CapabilitySourceLockEntry(
                    package_ref=self.package_ref,
                    payload_sha256=payload_sha256 or self.digest,
                    source_id=source_id,
                ),
            )
        )

    def test_rejects_when_no_candidate_matches_requested_package(self) -> None:
        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability source is unavailable or ambiguous$",
        ):
            resolve_capability_source(self.package_ref, (), None)

    def test_selects_one_exact_candidate_without_lock(self) -> None:
        candidate = self._candidate("example.source")

        self.assertIs(
            resolve_capability_source(self.package_ref, (candidate,), None),
            candidate,
        )

    def test_rejects_two_exact_candidates_without_lock(self) -> None:
        candidates = (
            self._candidate("first.source"),
            self._candidate("second.source"),
        )

        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability source is unavailable or ambiguous$",
        ):
            resolve_capability_source(self.package_ref, candidates, None)

    def test_rejects_same_digest_candidates_without_lock(self) -> None:
        candidates = (
            self._candidate("first.source"),
            self._candidate("second.source"),
        )

        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability source is unavailable or ambiguous$",
        ):
            resolve_capability_source(self.package_ref, candidates, None)

    def test_lock_selects_candidate_with_exact_source_and_digest(self) -> None:
        selected = self._candidate("selected.source")
        candidates = (self._candidate("other.source"), selected)

        self.assertIs(
            resolve_capability_source(
                self.package_ref,
                candidates,
                self._lock("selected.source"),
            ),
            selected,
        )

    def test_rejects_lock_for_missing_source(self) -> None:
        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability source is unavailable or rejected$",
        ):
            resolve_capability_source(
                self.package_ref,
                (self._candidate("available.source"),),
                self._lock("missing.source"),
            )

    def test_rejects_lock_when_candidate_digest_differs(self) -> None:
        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability source is unavailable or rejected$",
        ):
            resolve_capability_source(
                self.package_ref,
                (self._candidate("selected.source"),),
                self._lock("selected.source", "b" * 64),
            )

    def test_rejects_lock_without_exact_requested_package_ref(self) -> None:
        lock = CapabilitySourceLock(
            entries=(
                CapabilitySourceLockEntry(
                    package_ref=self.other_package_ref,
                    payload_sha256=self.digest,
                    source_id="selected.source",
                ),
            )
        )

        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability source is unavailable or rejected$",
        ):
            resolve_capability_source(
                self.package_ref,
                (self._candidate("selected.source"),),
                lock,
            )

    def test_rejection_does_not_disclose_source_or_digest_values(self) -> None:
        source_id = "SENTINEL-PRIVATE-SOURCE"
        digest = "b" * 64

        with self.assertRaises(CapabilitySourceResolutionError) as caught:
            resolve_capability_source(
                self.package_ref,
                (self._candidate(source_id),),
                self._lock(source_id, digest),
            )

        self.assertNotIn(source_id, str(caught.exception))
        self.assertNotIn(digest, str(caught.exception))

    def test_ignores_candidates_for_unrelated_package(self) -> None:
        selected = self._candidate("selected.source")
        unrelated = self._candidate(
            "unrelated.source",
            package_ref=self.other_package_ref,
        )

        self.assertIs(
            resolve_capability_source(
                self.package_ref,
                (unrelated, selected),
                None,
            ),
            selected,
        )

    def test_host_loads_exact_selected_package_through_source_phases(
        self,
    ) -> None:
        candidate = self._candidate("selected.source")
        manifest = CapabilityPackageManifest(
            package_ref=self.package_ref,
            capabilities=(),
            benchmark_suites=(),
            resources=(),
        )
        payload = PortableCapabilityPayload(
            manifest=manifest,
            payload_sha256=self.digest,
            resource_root=Path("."),
        )
        installed = InstalledCapabilityPackage(
            package_ref=self.package_ref,
            payload_sha256=self.digest,
            source_id=candidate.source_id,
            source_kind=candidate.source_kind,
            catalog_roots=(),
            benchmark_suite_paths=(),
            implementations=(),
            benchmark_bindings=(),
        )
        selected = FixtureSource(candidate, payload, installed)
        unrelated_ref = CapabilityPackageRef("unrelated.package", "1.0.0")
        unrelated_candidate = self._candidate(
            "unrelated.source",
            package_ref=unrelated_ref,
        )
        unrelated = FixtureSource(unrelated_candidate, payload, installed)

        loaded = load_installed_capability_packages(
            (self.package_ref,),
            (unrelated, selected),
        )

        self.assertEqual(loaded, (installed,))
        self.assertEqual(unrelated.calls, ["discover"])
        self.assertEqual(
            selected.calls,
            ["discover", "open", "validate", "load"],
        )

    def test_host_rejects_provider_identity_mismatch(self) -> None:
        candidate = self._candidate("selected.source")
        payload = PortableCapabilityPayload(
            manifest=CapabilityPackageManifest(
                package_ref=self.package_ref,
                capabilities=(),
                benchmark_suites=(),
                resources=(),
            ),
            payload_sha256=self.digest,
            resource_root=Path("."),
        )
        installed = InstalledCapabilityPackage(
            package_ref=self.other_package_ref,
            payload_sha256=self.digest,
            source_id=candidate.source_id,
            source_kind=candidate.source_kind,
            catalog_roots=(),
            benchmark_suite_paths=(),
            implementations=(),
            benchmark_bindings=(),
        )

        with self.assertRaisesRegex(
            CapabilitySourceResolutionError,
            "^capability package provider identity is invalid$",
        ):
            load_installed_capability_packages(
                (self.package_ref,),
                (FixtureSource(candidate, payload, installed),),
            )
