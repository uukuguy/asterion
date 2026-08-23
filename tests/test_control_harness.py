from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from asterion.control.harness import (
    HarnessEdit,
    HarnessEffectReceipt,
    HarnessEntryDescriptor,
    HarnessError,
    HarnessProposal,
    HarnessRevision,
    HarnessScope,
    HarnessSnapshot,
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
    scope: HarnessScope | None = None,
    evidence_ids: tuple[str, ...] | list[str] = ("evidence-1", "evidence-2"),
    edits: tuple[HarnessEdit, ...] | list[HarnessEdit] | None = None,
    rationale_ref: str = "private:rationale-1",
) -> HarnessProposal:
    if edits is None:
        edits = (HarnessEdit.create(_entry()),)
    return HarnessProposal(
        proposal_id="proposal-1",
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
            "HarnessEdit",
            "HarnessEffectReceipt",
            "HarnessEntryDescriptor",
            "HarnessError",
            "HarnessProposal",
            "HarnessRevision",
            "HarnessScope",
            "HarnessSnapshot",
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


if __name__ == "__main__":
    unittest.main()
