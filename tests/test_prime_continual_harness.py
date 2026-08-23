from __future__ import annotations

import unittest

from asterion.control.harness import (
    HarnessEdit,
    HarnessEntryDescriptor,
    HarnessProposal,
    HarnessScope,
    harness_effect_digest,
)
from asterion.control.providers.prime.harness import (
    PrimeContinualHarnessService,
    PrimeHarnessError,
    PrimeHarnessIpcReceipt,
)


def _entry(entry_id: str, kind: str) -> HarnessEntryDescriptor:
    return HarnessEntryDescriptor(
        entry_id=entry_id,
        kind=kind,
        title_digest="a" * 64,
        body_ref=f"private:{entry_id}",
        body_digest="b" * 64,
        grouping_path_digest=None,
        metadata_digest="c" * 64,
        version=1,
    )


def _proposal(
    *,
    scope: HarnessScope | None = None,
    entries: tuple[HarnessEntryDescriptor, ...] | None = None,
) -> HarnessProposal:
    values = entries or (_entry("memory-1", "memory"),)
    return HarnessProposal(
        proposal_id="proposal-1",
        authority_id="authority-1",
        authority_revision=1,
        scope=scope or HarnessScope.session("session-1"),
        baseline_snapshot_id="snapshot-0",
        edits=tuple(HarnessEdit.create(item) for item in values),
        evidence_ids=("evidence-1",),
        rationale_ref="private:rationale-1",
        rationale_digest="d" * 64,
        expected_outcome_digest="e" * 64,
    )


class _PrivateBodies:
    def resolve_text(self, private_ref: str) -> str:
        return {
            "private:memory-1": "SENTINEL_PRIVATE_MEMORY_BODY",
            "private:skill-1": "def run(value): return value",
            "private:subagent-1": "Subagent declaration",
        }[private_ref]


class _RecordingClient:
    def __init__(self) -> None:
        self.effects = []
        self.import_count = 0
        self.spawn_count = 0

    def apply_harness_effect(self, effect):
        self.effects.append(effect)
        return PrimeHarnessIpcReceipt(
            proposal_id=effect.proposal_id,
            proposal_digest=effect.proposal_digest,
            effect_digest=effect.effect_digest,
            status="succeeded",
            result_entries=tuple(
                edit.to_public_entry_mapping()
                for edit in effect.edits
                if edit.action != "delete"
            ),
            usage={
                "aggregate_tokens": 0,
                "cost_micros": 0,
                "model_credential_reads": 0,
                "provider_operations": 0,
            },
        )

    def read_harness_snapshot(self, scope):
        raise AssertionError(f"unexpected snapshot read: {scope.digest}")


class _DriftingClient(_RecordingClient):
    def apply_harness_effect(self, effect):
        receipt = super().apply_harness_effect(effect)
        return PrimeHarnessIpcReceipt(
            proposal_id=receipt.proposal_id,
            proposal_digest="f" * 64,
            effect_digest=receipt.effect_digest,
            status=receipt.status,
            result_entries=receipt.result_entries,
            usage=receipt.usage,
        )


class TestPrimeContinualHarnessService(unittest.TestCase):
    def test_selected_provider_exports_closed_harness_adapter(self) -> None:
        import asterion.control.providers.prime as prime

        expected = (
            "PrimeContinualHarnessService",
            "PrimeHarnessEdit",
            "PrimeHarnessEffect",
            "PrimeHarnessError",
            "PrimeHarnessIpcReceipt",
        )
        self.assertTrue(all(getattr(prime, name) for name in expected))
        self.assertTrue(set(expected).issubset(prime.__all__))

    def test_project_scope_uses_dedicated_local_projection(self) -> None:
        client = _RecordingClient()
        proposal = _proposal(scope=HarnessScope.project("project-1"))
        receipt = PrimeContinualHarnessService(client).apply(
            proposal,
            bodies=_PrivateBodies(),
        )

        self.assertEqual(client.effects[0].prime_scope, "local")
        self.assertEqual(client.effects[0].scope_digest, proposal.scope.digest)
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(receipt.effect_digest, harness_effect_digest(proposal))

    def test_global_scope_is_explicit_and_private_body_is_never_represented(self) -> None:
        client = _RecordingClient()
        proposal = _proposal(scope=HarnessScope.global_scope())
        PrimeContinualHarnessService(client).apply(proposal, _PrivateBodies())

        effect = client.effects[0]
        self.assertEqual(effect.prime_scope, "global")
        self.assertNotIn("SENTINEL_PRIVATE_MEMORY_BODY", repr(effect))
        self.assertNotIn("private:memory-1", repr(effect))

    def test_adapter_rejects_receipt_identity_drift(self) -> None:
        with self.assertRaisesRegex(PrimeHarnessError, "receipt is invalid"):
            PrimeContinualHarnessService(_DriftingClient()).apply(
                _proposal(),
                bodies=_PrivateBodies(),
            )

    def test_skill_and_subagent_entries_remain_declarative(self) -> None:
        client = _RecordingClient()
        proposal = _proposal(
            entries=(
                _entry("skill-1", "skill"),
                _entry("subagent-1", "subagent"),
            )
        )
        PrimeContinualHarnessService(client).apply(proposal, _PrivateBodies())

        self.assertEqual(client.import_count, 0)
        self.assertEqual(client.spawn_count, 0)
        self.assertEqual(tuple(edit.kind for edit in client.effects[0].edits), ("skill", "subagent"))

    def test_base_system_prompt_mutation_rejects_before_client(self) -> None:
        client = _RecordingClient()
        proposal = _proposal(entries=(_entry("base-system-prompt", "prompt"),))

        with self.assertRaisesRegex(PrimeHarnessError, "effect is invalid"):
            PrimeContinualHarnessService(client).apply(proposal, _PrivateBodies())
        self.assertEqual(client.effects, [])


if __name__ == "__main__":
    unittest.main()
