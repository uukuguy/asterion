from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

from asterion.control.harness import (
    HarnessCoordinator,
    HarnessEdit,
    HarnessEffectReceipt,
    HarnessEntryDescriptor,
    HarnessError,
    HarnessProposal,
    HarnessRevision,
    HarnessScope,
    HarnessSnapshot,
    HarnessTransportError,
    MemoryHarnessPrivateRevisionStore,
    harness_effect_digest,
)
from asterion.control.journal import (
    FileCanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
    MemoryCanonicalJournal,
)


def _entry(
    entry_id: str = "memory-1",
    *,
    kind: str = "memory",
    version: int = 1,
    body_ref: str = "private:memory-1",
) -> HarnessEntryDescriptor:
    return HarnessEntryDescriptor(
        entry_id=entry_id,
        kind=kind,
        title_digest="a" * 64,
        body_ref=body_ref,
        body_digest="b" * 64,
        grouping_path_digest=None,
        metadata_digest="c" * 64,
        version=version,
    )


def _proposal(
    *,
    proposal_id: str = "proposal-1",
    scope: HarnessScope | None = None,
    evidence_ids: tuple[str, ...] | list[str] = ("evidence-1", "evidence-2"),
    edits: tuple[HarnessEdit, ...] | list[HarnessEdit] | None = None,
    rationale_ref: str = "private:rationale-1",
) -> HarnessProposal:
    if edits is None:
        edits = (HarnessEdit.create(_entry()),)
    return HarnessProposal(
        proposal_id=proposal_id,
        authority_id="authority-1",
        authority_revision=1,
        scope=scope or HarnessScope.session("session-1"),
        baseline_snapshot_id="snapshot-0",
        edits=edits,
        evidence_ids=evidence_ids,
        rationale_ref=rationale_ref,
        rationale_digest="d" * 64,
        expected_outcome_digest="e" * 64,
    )


def _usage() -> dict[str, int]:
    return {
        "aggregate_tokens": 0,
        "cost_micros": 0,
        "model_credential_reads": 0,
        "provider_operations": 0,
    }


def _journal(session_id: str = "harness-session") -> MemoryCanonicalJournal:
    journal = MemoryCanonicalJournal(session_id)
    journal.append(
        0,
        JournalRecord.system_bound(
            system_id="research.system",
            system_version="1.0.0",
        ),
    )
    journal.append(
        1,
        JournalRecord.authority_bound(
            authority_id="authority-1",
            authority_revision=1,
        ),
    )
    return journal


class _Cancellation:
    cancelled = False


class _FailRecordOnce:
    def __init__(self, journal: MemoryCanonicalJournal, kind: str) -> None:
        self.journal = journal
        self.kind = kind
        self.failed = False

    @property
    def position(self) -> int:
        return self.journal.position

    def replay(self, cursor: JournalCursor):
        return self.journal.replay(cursor)

    def append(self, expected_position: int, record: JournalRecord):
        if record.kind == self.kind and not self.failed:
            self.failed = True
            raise JournalConflictError("simulated harness persistence loss")
        return self.journal.append(expected_position, record)


class TestHarnessScope(unittest.TestCase):
    def test_scopes_are_exact_disjoint_and_digestible(self) -> None:
        session = HarnessScope.session("session-1")
        project = HarnessScope.project("project-1")
        global_scope = HarnessScope.global_scope()

        self.assertEqual(session.key, "session:session-1")
        self.assertEqual(project.key, "project:project-1")
        self.assertEqual(global_scope.key, "global")
        self.assertEqual(
            session.to_mapping(), {"kind": "session", "scope_id": "session-1"}
        )
        self.assertRegex(session.digest, r"^[0-9a-f]{64}$")
        self.assertEqual(session.digest, HarnessScope.session("session-1").digest)
        self.assertEqual(len({session.digest, project.digest, global_scope.digest}), 3)

    def test_scope_rejects_implicit_or_malformed_identity(self) -> None:
        invalid = (
            ("session", None),
            ("project", "bad scope"),
            ("global", "project-1"),
            ("workspace", "project-1"),
        )
        for kind, scope_id in invalid:
            with self.subTest(kind=kind, scope_id=scope_id), self.assertRaisesRegex(
                HarnessError, "scope is invalid"
            ):
                HarnessScope(kind, scope_id)  # type: ignore[arg-type]


class TestHarnessValues(unittest.TestCase):
    def test_provider_neutral_values_are_exported_from_control_package(self) -> None:
        import asterion.control as control

        expected = (
            "HarnessCoordinator",
            "HarnessEdit",
            "HarnessEffectSender",
            "HarnessEffectReceipt",
            "HarnessEntryDescriptor",
            "HarnessError",
            "HarnessProposal",
            "HarnessPrivateRevisionStore",
            "HarnessRevision",
            "HarnessScope",
            "HarnessSnapshot",
            "HarnessTransportError",
            "MemoryHarnessPrivateRevisionStore",
            "harness_effect_digest",
        )
        self.assertTrue(all(getattr(control, name) for name in expected))
        self.assertTrue(set(expected).issubset(control.__all__))

    def test_entry_descriptor_is_closed_immutable_and_body_free(self) -> None:
        entry = _entry()

        self.assertNotIn("private:memory-1", repr(entry))
        self.assertEqual(entry.to_public_mapping()["body_digest"], "b" * 64)
        self.assertNotIn("body_ref", entry.to_public_mapping())
        with self.assertRaises(FrozenInstanceError):
            entry.version = 2  # type: ignore[misc]

    def test_all_entry_kinds_validate_and_malformed_values_fail_closed(self) -> None:
        self.assertEqual(
            tuple(_entry(kind=kind).kind for kind in ("prompt", "memory", "skill", "subagent")),
            ("prompt", "memory", "skill", "subagent"),
        )
        invalid_overrides = (
            {"kind": "tool"},
            {"version": True},
            {"version": 0},
            {"body_ref": "private body"},
        )
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(
                HarnessError, "entry descriptor is invalid"
            ):
                _entry(**overrides)  # type: ignore[arg-type]

    def test_edit_actions_enforce_exact_version_semantics(self) -> None:
        created = HarnessEdit.create(_entry())
        updated = HarnessEdit.update(_entry(version=2), expected_version=1)
        deleted = HarnessEdit.delete("memory-1", expected_version=2)

        self.assertEqual(created.action, "create")
        self.assertEqual(updated.expected_version, 1)
        self.assertIsNone(deleted.replacement)
        invalid = (
            lambda: HarnessEdit("create", "memory-1", 1, _entry()),
            lambda: HarnessEdit("update", "memory-1", 1, _entry(version=3)),
            lambda: HarnessEdit("delete", "memory-1", 2, _entry(version=3)),
        )
        for build in invalid:
            with self.subTest(build=build), self.assertRaisesRegex(
                HarnessError, "edit is invalid"
            ):
                build()

    def test_proposal_digest_binds_scope_baseline_edits_and_evidence(self) -> None:
        proposal = _proposal()

        self.assertRegex(proposal.digest, r"^[0-9a-f]{64}$")
        self.assertEqual(proposal.digest, _proposal().digest)
        self.assertNotEqual(
            proposal.digest,
            _proposal(scope=HarnessScope.project("project-1")).digest,
        )
        with self.assertRaisesRegex(HarnessError, "proposal is invalid"):
            _proposal(evidence_ids=("evidence-2", "evidence-1"))

    def test_proposal_copies_containers_and_redacts_private_references(self) -> None:
        edits = [HarnessEdit.create(_entry())]
        evidence_ids = ["evidence-1", "evidence-2"]
        proposal = _proposal(edits=edits, evidence_ids=evidence_ids)
        edits.clear()
        evidence_ids.clear()

        self.assertEqual(len(proposal.edits), 1)
        self.assertEqual(proposal.evidence_ids, ("evidence-1", "evidence-2"))
        self.assertNotIn("private:rationale-1", repr(proposal))
        with self.assertRaises(FrozenInstanceError):
            proposal.authority_revision = 2  # type: ignore[misc]

    def test_snapshot_sorts_entries_and_copies_safe_usage(self) -> None:
        snapshot = HarnessSnapshot(
            snapshot_id="snapshot-1",
            scope=HarnessScope.session("session-1"),
            revision_id="revision-1",
            sequence=1,
            entries=[_entry("skill-1", kind="skill"), _entry("memory-1")],
            pending_status=None,
        )
        usage = _usage()
        revision = HarnessRevision(
            revision_id="revision-1",
            sequence=1,
            proposal_id="proposal-1",
            proposal_digest="f" * 64,
            scope=HarnessScope.session("session-1"),
            baseline_snapshot_id="snapshot-0",
            result_snapshot_id="snapshot-1",
            effect_digest="0" * 64,
            status="succeeded",
            rollback_revision_id=None,
            usage=usage,
        )
        usage["provider_operations"] = 9

        self.assertEqual(tuple(item.entry_id for item in snapshot.entries), ("memory-1", "skill-1"))
        self.assertEqual(revision.usage["provider_operations"], 0)
        with self.assertRaises(TypeError):
            revision.usage["provider_operations"] = 1  # type: ignore[index]

    def test_receipt_named_constructors_bind_proposal_and_safe_result(self) -> None:
        proposal = _proposal()
        receipt = HarnessEffectReceipt.succeeded(
            proposal,
            effect_digest="f" * 64,
            result_entries=(_entry(),),
            usage=_usage(),
        )

        self.assertEqual(receipt.proposal_id, proposal.proposal_id)
        self.assertEqual(receipt.proposal_digest, proposal.digest)
        self.assertEqual(receipt.status, "succeeded")
        self.assertNotIn("private:memory-1", repr(receipt))
        self.assertEqual(
            HarnessEffectReceipt.uncertain(proposal, effect_digest="f" * 64).status,
            "uncertain",
        )


class TestHarnessCoordinator(unittest.TestCase):
    def test_proposal_and_effect_start_are_durable_before_send(self) -> None:
        journal = _journal()

        def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
            kinds = tuple(item.record.kind for item in journal.replay(JournalCursor(0)))
            self.assertEqual(
                kinds[-2:], ("harness.proposed", "harness.effect-started")
            )
            return HarnessEffectReceipt.succeeded(
                proposal,
                effect_digest=harness_effect_digest(proposal),
                result_entries=(_entry(),),
                usage=_usage(),
            )

        revision = HarnessCoordinator(
            journal,
            HarnessScope.session("session-1"),
            send,
            _Cancellation(),
        ).apply(_proposal())

        self.assertEqual(revision.status, "succeeded")
        self.assertEqual(
            tuple(item.record.kind for item in journal.replay(JournalCursor(2))),
            (
                "harness.proposed",
                "harness.effect-started",
                "harness.effect-terminal",
                "harness.snapshot-activated",
            ),
        )

    def test_transport_loss_fences_replay_as_uncertain(self) -> None:
        journal = _journal()
        calls = 0

        def lose_transport(proposal: HarnessProposal) -> HarnessEffectReceipt:
            nonlocal calls
            calls += 1
            raise HarnessTransportError("SENTINEL_PRIVATE_TRANSPORT")

        private_store = MemoryHarnessPrivateRevisionStore()
        first = HarnessCoordinator(
            journal,
            HarnessScope.session("session-1"),
            lose_transport,
            _Cancellation(),
            private_store,
        )
        self.assertEqual(first.apply(_proposal()).status, "uncertain")
        reopened = HarnessCoordinator(
            journal,
            HarnessScope.session("session-1"),
            lambda proposal: self.fail(f"uncertain effect retried: {proposal.digest}"),
            _Cancellation(),
            private_store,
        )

        self.assertEqual(reopened.recover().pending_status, "uncertain")
        self.assertEqual(reopened.history()[-1].status, "uncertain")
        self.assertEqual(calls, 1)
        self.assertNotIn("SENTINEL_PRIVATE_TRANSPORT", repr(reopened.history()))

    def test_scope_and_version_conflicts_reject_before_effect(self) -> None:
        calls = 0

        def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
            nonlocal calls
            calls += 1
            return HarnessEffectReceipt.succeeded(
                proposal,
                effect_digest=harness_effect_digest(proposal),
                result_entries=(_entry(),),
            )

        coordinator = HarnessCoordinator(
            _journal(),
            HarnessScope.session("session-1"),
            send,
            _Cancellation(),
        )
        with self.assertRaisesRegex(HarnessError, "proposal conflicts with snapshot"):
            coordinator.apply(
                _proposal(scope=HarnessScope.project("project-1"))
            )
        with self.assertRaisesRegex(HarnessError, "edit conflicts with snapshot"):
            coordinator.apply(
                _proposal(
                    edits=(HarnessEdit.update(_entry(version=2), expected_version=1),)
                )
            )
        self.assertEqual(calls, 0)

    def test_identical_proposal_replay_returns_original_without_resend(self) -> None:
        calls = 0

        def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
            nonlocal calls
            calls += 1
            return HarnessEffectReceipt.succeeded(
                proposal,
                effect_digest=harness_effect_digest(proposal),
                result_entries=(_entry(),),
            )

        coordinator = HarnessCoordinator(
            _journal(),
            HarnessScope.session("session-1"),
            send,
            _Cancellation(),
        )
        proposal = _proposal()

        self.assertEqual(coordinator.apply(proposal), coordinator.apply(proposal))
        self.assertEqual(calls, 1)

    def test_failed_revision_consumes_sequence_before_later_success(self) -> None:
        calls = 0

        def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
            nonlocal calls
            calls += 1
            if calls == 1:
                return HarnessEffectReceipt.failed(
                    proposal,
                    effect_digest=harness_effect_digest(proposal),
                )
            return HarnessEffectReceipt.succeeded(
                proposal,
                effect_digest=harness_effect_digest(proposal),
                result_entries=(_entry(),),
            )

        coordinator = HarnessCoordinator(
            _journal(),
            HarnessScope.session("session-1"),
            send,
            _Cancellation(),
        )
        failed = coordinator.apply(_proposal())
        succeeded = coordinator.apply(_proposal(proposal_id="proposal-2"))

        self.assertEqual((failed.sequence, succeeded.sequence), (1, 2))
        self.assertEqual(coordinator.snapshot().sequence, 2)

    def test_activation_persistence_failure_recovers_without_second_effect(self) -> None:
        journal = _journal()
        fail_once = _FailRecordOnce(journal, "harness.snapshot-activated")
        private_store = MemoryHarnessPrivateRevisionStore()
        calls = 0

        def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
            nonlocal calls
            calls += 1
            return HarnessEffectReceipt.succeeded(
                proposal,
                effect_digest=harness_effect_digest(proposal),
                result_entries=(_entry(),),
                usage=_usage(),
            )

        first = HarnessCoordinator(
            fail_once,
            HarnessScope.session("session-1"),
            send,
            _Cancellation(),
            private_store,
        )
        with self.assertRaisesRegex(HarnessError, "harness journal conflicts"):
            first.apply(_proposal())

        reopened = HarnessCoordinator(
            journal,
            HarnessScope.session("session-1"),
            lambda proposal: self.fail(f"terminal effect retried: {proposal.digest}"),
            _Cancellation(),
            private_store,
        )
        recovered = reopened.recover()

        self.assertEqual(calls, 1)
        self.assertEqual(recovered.sequence, 1)
        self.assertEqual(recovered.entries, (_entry(),))
        self.assertEqual(
            journal.replay(JournalCursor(journal.position - 1))[0].record.kind,
            "harness.snapshot-activated",
        )

    def test_proposed_without_effect_start_resumes_only_identical_proposal(self) -> None:
        journal = _journal()
        private_store = MemoryHarnessPrivateRevisionStore()
        proposal = _proposal()
        first = HarnessCoordinator(
            _FailRecordOnce(journal, "harness.effect-started"),
            HarnessScope.session("session-1"),
            lambda candidate: self.fail(f"effect started early: {candidate.digest}"),
            _Cancellation(),
            private_store,
        )
        with self.assertRaisesRegex(HarnessError, "harness journal conflicts"):
            first.apply(proposal)

        calls = 0

        def send(candidate: HarnessProposal) -> HarnessEffectReceipt:
            nonlocal calls
            calls += 1
            return HarnessEffectReceipt.succeeded(
                candidate,
                effect_digest=harness_effect_digest(candidate),
                result_entries=(_entry(),),
            )

        reopened = HarnessCoordinator(
            journal,
            HarnessScope.session("session-1"),
            send,
            _Cancellation(),
            private_store,
        )
        with self.assertRaisesRegex(HarnessError, "proposal replay conflicts"):
            reopened.apply(_proposal(evidence_ids=("evidence-1",)))

        self.assertEqual(reopened.apply(proposal).status, "succeeded")
        self.assertEqual(calls, 1)

    def test_rollback_creates_new_revision_and_preserves_history(self) -> None:
        coordinator = HarnessCoordinator(
            _journal(),
            HarnessScope.session("session-1"),
            lambda proposal: HarnessEffectReceipt.succeeded(
                proposal,
                effect_digest=harness_effect_digest(proposal),
                result_entries=() if proposal.edits[0].action == "delete" else (_entry(),),
                usage=_usage(),
            ),
            _Cancellation(),
        )
        original = coordinator.apply(_proposal())
        rollback = coordinator.rollback(
            proposal_id="proposal-rollback",
            authority_id="authority-1",
            authority_revision=1,
            target_revision_id=original.revision_id,
            rationale_ref="private:rollback",
            rationale_digest="1" * 64,
            expected_outcome_digest="2" * 64,
        )

        self.assertGreater(rollback.sequence, original.sequence)
        self.assertEqual(rollback.rollback_revision_id, original.revision_id)
        self.assertEqual(len(coordinator.history()), 2)
        self.assertEqual(coordinator.snapshot().entries, ())

    def test_file_journal_reopen_recovers_activated_snapshot_without_resend(self) -> None:
        private_store = MemoryHarnessPrivateRevisionStore()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-journal"
            journal = FileCanonicalJournal.open(root, "harness-session")
            journal.append(
                0,
                JournalRecord.system_bound(
                    system_id="research.system",
                    system_version="1.0.0",
                ),
            )
            journal.append(
                1,
                JournalRecord.authority_bound(
                    authority_id="authority-1",
                    authority_revision=1,
                ),
            )
            first = HarnessCoordinator(
                journal,
                HarnessScope.session("session-1"),
                lambda proposal: HarnessEffectReceipt.succeeded(
                    proposal,
                    effect_digest=harness_effect_digest(proposal),
                    result_entries=(_entry(),),
                    usage=_usage(),
                ),
                _Cancellation(),
                private_store,
            )
            expected = first.apply(_proposal())
            journal.close()

            reopened_journal = FileCanonicalJournal.open(root, "harness-session")
            reopened = HarnessCoordinator(
                reopened_journal,
                HarnessScope.session("session-1"),
                lambda proposal: self.fail(f"completed effect retried: {proposal.digest}"),
                _Cancellation(),
                private_store,
            )

            self.assertEqual(reopened.snapshot().revision_id, expected.revision_id)
            self.assertEqual(reopened.snapshot().entries, (_entry(),))
            self.assertEqual(reopened.history(), (expected,))
            reopened_journal.close()


if __name__ == "__main__":
    unittest.main()
