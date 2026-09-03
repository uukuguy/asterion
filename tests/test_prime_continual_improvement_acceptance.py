from __future__ import annotations

import unittest

from asterion.applications.prime_agent.continual_improvement_acceptance import (
    continual_improvement_revision_sha256,
    continual_improvement_snapshot_sha256,
)
from asterion.control.harness import (
    HarnessEntryDescriptor,
    HarnessRevision,
    HarnessScope,
    HarnessSnapshot,
)


def _entry() -> HarnessEntryDescriptor:
    return HarnessEntryDescriptor("memory-1", "memory", "a" * 64, "private:memory-1", "b" * 64, None, "c" * 64, 1)


class TestContinualImprovementAcceptance(unittest.TestCase):
    def test_public_projections_are_deterministic_and_body_free(self) -> None:
        scope = HarnessScope.project("project-1")
        snapshot = HarnessSnapshot("snapshot-1", scope, "revision-1", 1, (_entry(),), None)
        revision = HarnessRevision("revision-1", 1, "proposal-1", "d" * 64, scope, "snapshot-0", "snapshot-1", "e" * 64, "succeeded", None, {"aggregate_tokens": 0, "cost_micros": 0, "model_credential_reads": 0, "provider_operations": 0})

        self.assertRegex(continual_improvement_snapshot_sha256(snapshot), r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(continual_improvement_revision_sha256(revision), r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("private:memory-1", repr(snapshot))

