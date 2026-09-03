from __future__ import annotations

import unittest

from asterion.applications.prime_agent.continual_improvement_acceptance import (
    accept_continual_improvement,
    continual_improvement_revision_sha256,
    continual_improvement_snapshot_sha256,
)
from asterion.applications.prime_agent.continual_improvement_receipt import ContinualImprovementTrace
from asterion.applications.prime_agent.operator.continual_improvement_workload import P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256, P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256, P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256, P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256
from asterion.control.harness import (
    HarnessEntryDescriptor,
    HarnessRevision,
    HarnessScope,
    HarnessSnapshot,
)


def _entry() -> HarnessEntryDescriptor:
    return HarnessEntryDescriptor("memory-1", "memory", "a" * 64, "private:memory-1", "b" * 64, None, "c" * 64, 1)


class TestContinualImprovementAcceptance(unittest.IsolatedAsyncioTestCase):
    def test_public_projections_are_deterministic_and_body_free(self) -> None:
        scope = HarnessScope.project("project-1")
        snapshot = HarnessSnapshot("snapshot-1", scope, "revision-1", 1, (_entry(),), None)
        revision = HarnessRevision("revision-1", 1, "proposal-1", "d" * 64, scope, "snapshot-0", "snapshot-1", "e" * 64, "succeeded", None, {"aggregate_tokens": 0, "cost_micros": 0, "model_credential_reads": 0, "provider_operations": 0})

        self.assertRegex(continual_improvement_snapshot_sha256(snapshot), r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(continual_improvement_revision_sha256(revision), r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("private:memory-1", repr(snapshot))

    async def test_accepts_one_matching_nonregressing_holdout_as_provider_free(self) -> None:
        scope = HarnessScope.project("project-1")
        baseline = HarnessSnapshot("snapshot-0", scope, None, 0, (), None)
        candidate = HarnessSnapshot("snapshot-1", scope, "revision-1", 1, (_entry(),), None)
        revision = HarnessRevision("revision-1", 1, "proposal-1", "d" * 64, scope, "snapshot-0", "snapshot-1", "e" * 64, "succeeded", None, {"aggregate_tokens": 0, "cost_micros": 0, "model_credential_reads": 0, "provider_operations": 0})
        trace = ContinualImprovementTrace(P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST, continual_improvement_snapshot_sha256(baseline), continual_improvement_snapshot_sha256(candidate), continual_improvement_revision_sha256(revision), "sha256:" + "a" * 64, "sha256:" + "b" * 64, P6_CONTINUAL_IMPROVEMENT_ORACLE_SHA256, P6_CONTINUAL_IMPROVEMENT_MODEL_SHA256, P6_CONTINUAL_IMPROVEMENT_SCHEMA_SHA256, ("ipython",), 3, 10, 1, 1, 0, "preserved", P6_CONTINUAL_IMPROVEMENT_ROLLBACK_AUTHORITY_ID, 1, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_PROPOSAL_ID, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_RATIONALE_SHA256, P6_CONTINUAL_IMPROVEMENT_ROLLBACK_OUTCOME_SHA256, True, True, True)

        class Gate:
            async def evaluate(self, candidate_sha256: str) -> tuple[bool, str]:
                self.seen = candidate_sha256
                return True, trace.task_b_result_sha256

        gate = Gate()
        receipt = await accept_continual_improvement(gate=gate, trace=trace, baseline_snapshot=baseline, candidate_snapshot=candidate, candidate_revision=revision, disposed=True, reaped=True)
        self.assertEqual(receipt.level.value, "provider-free")
        self.assertEqual(gate.seen, trace.candidate_snapshot_sha256)
