from __future__ import annotations

import unittest
from collections.abc import Iterator, Sequence
from typing import Any, overload, cast

from asterion.capability_packages.model import CapabilityPackageCandidate
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)
from asterion.capability_packages.resolution import (
    CapabilitySourceResolutionError,
    resolve_capability_source,
)


PACKAGE = CapabilityPackageRef("example.package", "1.0.0")
OTHER_PACKAGE = CapabilityPackageRef("other.package", "1.0.0")
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def candidate(
    *,
    package_ref: CapabilityPackageRef = PACKAGE,
    source_id: str = "example.source",
    digest: str | None = DIGEST,
) -> CapabilityPackageCandidate:
    return CapabilityPackageCandidate(
        package_ref=package_ref,
        source_id=source_id,
        source_kind="local-directory",
        payload_sha256=digest,
        metadata={"distribution_name": "SECRET-DIST"},
    )


def lock_entry(
    *,
    package_ref: CapabilityPackageRef = PACKAGE,
    source_id: str = "example.source",
    digest: str = DIGEST,
) -> CapabilitySourceLockEntry:
    return CapabilitySourceLockEntry(
        package_ref=package_ref,
        payload_sha256=digest,
        source_id=source_id,
    )


def lock(*entries: CapabilitySourceLockEntry) -> CapabilitySourceLock:
    return CapabilitySourceLock(entries=entries)


def assert_stable_error(
    test_case: unittest.TestCase,
    error: BaseException,
    expected: str,
    sentinels: tuple[str, ...] = (),
) -> None:
    test_case.assertEqual(str(error), expected)
    cursor: BaseException | None = error
    seen: set[int] = set()
    while cursor is not None:
        if id(cursor) in seen:
            test_case.fail("exception chain contains a cycle")
        seen.add(id(cursor))
        rendered = repr(cursor)
        for sentinel in sentinels:
            test_case.assertNotIn(sentinel, rendered)
        cursor = cursor.__cause__ or cursor.__context__
    test_case.assertIsNone(error.__cause__)
    test_case.assertIsNone(error.__context__)


class HostileCandidates(Sequence[CapabilityPackageCandidate]):
    def __len__(self) -> int:
        raise RuntimeError("SECRET-CANDIDATE-LENGTH")

    @overload
    def __getitem__(self, index: int) -> CapabilityPackageCandidate: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[CapabilityPackageCandidate]: ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> CapabilityPackageCandidate | Sequence[CapabilityPackageCandidate]:
        del index
        raise RuntimeError("SECRET-CANDIDATE-ACCESS")


class InterruptingCandidates(Sequence[CapabilityPackageCandidate]):
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def __len__(self) -> int:
        raise self._error

    @overload
    def __getitem__(self, index: int) -> CapabilityPackageCandidate: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[CapabilityPackageCandidate]: ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> CapabilityPackageCandidate | Sequence[CapabilityPackageCandidate]:
        del index
        raise self._error


class HostileLockEntries:
    def __iter__(self) -> Iterator[CapabilitySourceLockEntry]:
        raise RuntimeError("SECRET-LOCK-ITERATION")


class HostileRef(CapabilityPackageRef):
    def __eq__(self, other: object) -> bool:
        del other
        raise RuntimeError("SECRET-REF-COMPARISON")


class CapabilitySourceResolutionTests(unittest.TestCase):
    def test_zero_exact_candidates_without_lock_is_unavailable(self) -> None:
        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(PACKAGE, (), None)

        assert_stable_error(
            self,
            raised.exception,
            "capability source is unavailable",
        )

    def test_one_exact_candidate_without_lock_is_selected(self) -> None:
        selected = candidate()

        resolved = resolve_capability_source(
            PACKAGE,
            (candidate(package_ref=OTHER_PACKAGE), selected),
            None,
        )

        self.assertIs(resolved, selected)

    def test_multiple_exact_candidates_without_lock_are_ambiguous(self) -> None:
        cases = (
            (
                candidate(source_id="example.source"),
                candidate(source_id="alternate.source", digest=OTHER_DIGEST),
            ),
            (
                candidate(source_id="example.source"),
                candidate(source_id="alternate.source"),
            ),
        )
        for candidates in cases:
            with self.subTest(candidates=candidates):
                with self.assertRaises(CapabilitySourceResolutionError) as raised:
                    resolve_capability_source(PACKAGE, candidates, None)

                assert_stable_error(
                    self,
                    raised.exception,
                    "capability source is ambiguous",
                )

    def test_lock_selects_exact_package_source_and_digest(self) -> None:
        selected = candidate(source_id="selected.source", digest=OTHER_DIGEST)

        resolved = resolve_capability_source(
            PACKAGE,
            (
                candidate(source_id="example.source", digest=DIGEST),
                candidate(package_ref=OTHER_PACKAGE),
                selected,
            ),
            lock(lock_entry(source_id="selected.source", digest=OTHER_DIGEST)),
        )

        self.assertIs(resolved, selected)

    def test_lock_source_missing_is_unavailable(self) -> None:
        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(
                PACKAGE,
                (candidate(source_id="example.source"),),
                lock(lock_entry(source_id="missing.source")),
            )

        assert_stable_error(
            self,
            raised.exception,
            "capability source is unavailable",
        )

    def test_lock_digest_mismatch_is_rejected(self) -> None:
        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(
                PACKAGE,
                (candidate(source_id="example.source", digest=OTHER_DIGEST),),
                lock(lock_entry(digest=DIGEST)),
            )

        assert_stable_error(
            self,
            raised.exception,
            "capability source digest is rejected",
        )

    def test_missing_candidate_digest_under_digest_lock_is_rejected(self) -> None:
        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(
                PACKAGE,
                (candidate(source_id="example.source", digest=None),),
                lock(lock_entry(digest=DIGEST)),
            )

        assert_stable_error(
            self,
            raised.exception,
            "capability source digest is rejected",
        )

    def test_unrelated_candidates_and_lock_entries_are_ignored(self) -> None:
        selected = candidate()
        source_lock = lock(
            lock_entry(),
            lock_entry(
                package_ref=OTHER_PACKAGE,
                source_id="other.source",
                digest=OTHER_DIGEST,
            ),
        )

        resolved = resolve_capability_source(
            PACKAGE,
            (
                candidate(
                    package_ref=OTHER_PACKAGE,
                    source_id="other.source",
                    digest=OTHER_DIGEST,
                ),
                selected,
            ),
            source_lock,
        )

        self.assertIs(resolved, selected)

    def test_rejects_invalid_boundary_types_with_body_free_errors(self) -> None:
        cases = (
            (
                "package",
                cast(Any, CapabilityPackageRef("Bad ID", "1.0.0")),
                (),
                None,
                "capability source request is invalid",
                ("Bad ID",),
            ),
            (
                "candidate sequence",
                PACKAGE,
                cast(Any, object()),
                None,
                "capability source candidates are invalid",
                (),
            ),
            (
                "candidate element",
                PACKAGE,
                cast(Any, [object()]),
                None,
                "capability source candidates are invalid",
                (),
            ),
            (
                "lock",
                PACKAGE,
                (),
                cast(Any, object()),
                "capability source lock is invalid",
                (),
            ),
        )
        for label, package_ref, candidates, source_lock, expected, sentinels in cases:
            with self.subTest(label=label):
                with self.assertRaises(CapabilitySourceResolutionError) as raised:
                    resolve_capability_source(package_ref, candidates, source_lock)

                assert_stable_error(self, raised.exception, expected, sentinels)

    def test_hostile_candidate_sequence_failures_are_body_free(self) -> None:
        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(PACKAGE, HostileCandidates(), None)

        assert_stable_error(
            self,
            raised.exception,
            "capability source candidates are invalid",
            ("SECRET-CANDIDATE-LENGTH", "SECRET-CANDIDATE-ACCESS"),
        )

    def test_hostile_lock_entry_iteration_failures_are_body_free(self) -> None:
        source_lock = lock(lock_entry())
        object.__setattr__(source_lock, "entries", HostileLockEntries())

        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(PACKAGE, (candidate(),), source_lock)

        assert_stable_error(
            self,
            raised.exception,
            "capability source lock is invalid",
            ("SECRET-LOCK-ITERATION",),
        )

    def test_hostile_package_comparisons_are_body_free(self) -> None:
        hostile = candidate()
        object.__setattr__(
            hostile,
            "package_ref",
            HostileRef("example.package", "1.0.0"),
        )

        with self.assertRaises(CapabilitySourceResolutionError) as raised:
            resolve_capability_source(PACKAGE, (hostile,), None)

        assert_stable_error(
            self,
            raised.exception,
            "capability source candidates are invalid",
            ("SECRET-REF-COMPARISON",),
        )

    def test_base_exceptions_from_sequences_are_preserved(self) -> None:
        for error in (KeyboardInterrupt("SECRET-INTERRUPT"), SystemExit("SECRET-EXIT")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    resolve_capability_source(
                        PACKAGE,
                        InterruptingCandidates(error),
                        None,
                    )


if __name__ == "__main__":
    unittest.main()
