"""Tests for the P6 host Protocol + frozen dataclasses (Phase 9, Task 4)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
import typing
import unittest

from asterion.applications.prime.p6.host import (
    P6AdmittedProposal,
    P6BaselineSnapshot,
    P6CandidateRevision,
    P6HoldoutResult,
    P6PromotionAction,
    P6RuntimeHost,
    P6TerminalOutcome,
)
from asterion.control.harness import HarnessEntryDescriptor


def _make_entry(entry_id: str = "entry-1") -> HarnessEntryDescriptor:
    """Build one valid ``HarnessEntryDescriptor`` for tests.

    Mirrors the fixture shape used by P3 / P4 / P5 host protocol
    tests: real 64-hex digests, a valid kind, version >= 1. Keeps
    each test self-contained without reaching into a fixture file.
    """

    return HarnessEntryDescriptor(
        entry_id=entry_id,
        kind="memory",
        title_digest="a" * 64,
        body_ref="memory.test",
        body_digest="b" * 64,
        grouping_path_digest=None,
        metadata_digest="c" * 64,
        version=1,
    )


class TestP6HostProtocol(unittest.TestCase):
    def test_p6_runtime_host_owns_one_candidate_workflow(self) -> None:
        members = {name for name in dir(P6RuntimeHost) if not name.startswith("_")}
        self.assertEqual(members, {"validate_runtime_services", "run_candidate"})

    def test_p6_admitted_proposal_is_frozen(self) -> None:
        field_names = {f.name for f in fields(P6AdmittedProposal)}
        self.assertEqual(
            field_names,
            {
                "proposal_id",
                "proposal_digest",
                "revision_id",
                "admission_timestamp",
            },
        )
        self.assertEqual(len(field_names), 4)

        instance = P6AdmittedProposal(
            proposal_id="prop-1",
            proposal_digest="a" * 64,
            revision_id="rev-1",
            admission_timestamp=datetime(2026, 9, 19, tzinfo=timezone.utc),
        )
        with self.assertRaises(FrozenInstanceError):
            instance.proposal_id = "prop-2"  # type: ignore[misc]

    def test_p6_baseline_snapshot_carries_tuple_of_entries(self) -> None:
        field_names = {f.name for f in fields(P6BaselineSnapshot)}
        self.assertEqual(field_names, {"snapshot_id", "entries"})
        self.assertEqual(len(field_names), 2)

        entry = _make_entry()
        instance = P6BaselineSnapshot(
            snapshot_id="snap-1", entries=(entry,)
        )
        # entries is a tuple, not a list — list values cannot be
        # promoted to tuple implicitly because the field type is
        # closed. Mutation on the field raises FrozenInstanceError
        # (the dataclass is frozen).
        self.assertIsInstance(instance.entries, tuple)
        self.assertEqual(len(instance.entries), 1)
        self.assertIs(instance.entries[0], entry)

        with self.assertRaises(FrozenInstanceError):
            instance.snapshot_id = "snap-2"  # type: ignore[misc]

    def test_p6_candidate_revision_carries_parent_revision_id_optional(
        self,
    ) -> None:
        field_names = {f.name for f in fields(P6CandidateRevision)}
        self.assertEqual(
            field_names,
            {
                "revision_id",
                "revision_digest",
                "parent_revision_id",
            },
        )
        self.assertEqual(len(field_names), 3)

        # First revision: parent_revision_id is None — the oracle
        # keys on this distinction to prove the candidate differs
        # from the empty baseline on iteration 1.
        first = P6CandidateRevision(
            revision_id="rev-1",
            revision_digest="a" * 64,
            parent_revision_id=None,
        )
        self.assertIsNone(first.parent_revision_id)

        # Subsequent revision: parent_revision_id is a non-empty
        # string identifying the prior revision.
        next_rev = P6CandidateRevision(
            revision_id="rev-2",
            revision_digest="b" * 64,
            parent_revision_id="rev-1",
        )
        self.assertEqual(next_rev.parent_revision_id, "rev-1")

        # Frozen: any field mutation raises FrozenInstanceError.
        with self.assertRaises(FrozenInstanceError):
            first.revision_id = "rev-x"  # type: ignore[misc]

    def test_p6_promotion_action_references_target_revision_id(self) -> None:
        field_names = {f.name for f in fields(P6PromotionAction)}
        self.assertEqual(
            field_names,
            {
                "promotion_id",
                "promotion_digest",
                "target_revision_id",
                "promotion_timestamp",
            },
        )
        self.assertEqual(len(field_names), 4)

        instance = P6PromotionAction(
            promotion_id="promo-1",
            promotion_digest="a" * 64,
            target_revision_id="rev-1",
            promotion_timestamp=datetime(2026, 9, 19, tzinfo=timezone.utc),
        )
        # target_revision_id is a required ``str`` field; the
        # witness's third clause ("an improving candidate requires an
        # explicit admitted promotion action before becoming
        # current") is enforced by the oracle refusing a ``preserved``
        # receipt whose promotion does not name a specific revision.
        self.assertEqual(instance.target_revision_id, "rev-1")
        self.assertIsInstance(instance.target_revision_id, str)

        with self.assertRaises(FrozenInstanceError):
            instance.target_revision_id = "rev-2"  # type: ignore[misc]

    def test_p6_terminal_outcome_is_closed_two_element_literal(self) -> None:
        # P6TerminalOutcome is a Literal[...] type alias; resolve its
        # __args__ at runtime to enumerate the closed set. The
        # public surface is 2 elements (``preserved`` | ``rolled-back``)
        # — the oracle's internal ``global-rejected`` verdict, plus
        # cancellation / candidate-admission / holdout-evaluation /
        # promotion-action errors, all fold into ``rolled-back`` so the
        # public enum stays at 2. ``global-rejected`` is NOT a public
        # terminal outcome; it is an internal oracle verdict that the
        # public surface expresses through
        # ``terminal_outcome="rolled-back"`` +
        # ``global_activation_approved=False`` on the sealed
        # ``P6NativeReceipt``.
        args = set(typing.get_args(P6TerminalOutcome))
        self.assertEqual(args, {"preserved", "rolled-back"})
        self.assertEqual(len(args), 2)
        # Defensive: explicitly reject the oracle's internal verdict
        # in the public surface. ``global-rejected`` would silently
        # widen the public contract if it ever leaked in here.
        self.assertNotIn("global-rejected", args)
        # Defensive: explicitly reject P5's 5-element enum values
        # from leaking into P6's smaller 2-element public surface.
        for p5_terminal in {
            "success",
            "iteration-cap-exceeded",
            "duration-cap-exceeded",
            "no-progress",
            "cancelled",
        }:
            self.assertNotIn(p5_terminal, args)


class TestP6HoldoutResult(unittest.TestCase):
    """Cover ``P6HoldoutResult`` alongside the protocol-shape tests.

    ``P6HoldoutResult`` is one of the five P6 dataclasses; it is
    referenced by ``evaluate_holdout`` in the Protocol and by the
    sealed ``P6NativeReceipt`` (``task_b_result_digest`` derives from
    ``task_b_result_sha256``). The dataclass is frozen, the
    ``task_b_result_sha256`` is a 64-hex SHA-256 by oracle invariant,
    and ``non_regressing`` is the boolean the oracle keys on to choose
    between ``preserved`` and ``rolled-back``.
    """

    def test_p6_holdout_result_is_frozen(self) -> None:
        field_names = {f.name for f in fields(P6HoldoutResult)}
        self.assertEqual(
            field_names,
            {
                "task_b_result_sha256",
                "non_regressing",
                "evaluation_timestamp",
            },
        )
        self.assertEqual(len(field_names), 3)

        instance = P6HoldoutResult(
            task_b_result_sha256="d" * 64,
            non_regressing=True,
            evaluation_timestamp=datetime(2026, 9, 19, tzinfo=timezone.utc),
        )
        self.assertTrue(instance.non_regressing)
        self.assertEqual(len(instance.task_b_result_sha256), 64)

        with self.assertRaises(FrozenInstanceError):
            instance.non_regressing = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
