from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from asterion.control.authority import AuthorityEnvelope, BudgetLimit, PortfolioGrant
from asterion.control.rlm import RlmChildBinding, RlmChildService, RlmError


def _authority() -> AuthorityEnvelope:
    return AuthorityEnvelope(
        authority_id="authority-1",
        revision=1,
        allowed_portfolio=(PortfolioGrant("example.provider", "alpha", "1.0.0", "fake.runtime"),),
        allowed_operations=("rlm.child.delete", "rlm.child.message", "rlm.child.spawn"),
        budget_limit=BudgetLimit(10, 10, 10, 30, 10),
        expires_at_ms=10_000,
        max_action_deadline_ms=1_000,
        max_recursion_depth=2,
        max_concurrent_children=1,
        execution_domain="trusted-local",
        host_service_grants=("storage.private",),
    )


def _binding(**changes: object) -> RlmChildBinding:
    values = {
        "action_id": "action-1",
        "child_id": "child-1",
        "parent_session_id": "session-1",
        "authority_revision": 1,
        "proposal_digest": "a" * 64,
        "depth": 1,
        "model_selector_digest": "b" * 64,
    }
    values.update(changes)
    return RlmChildBinding(**values)  # type: ignore[arg-type]


class TestRlmChildService(unittest.TestCase):
    def test_binding_exposes_no_private_native_identity(self) -> None:
        with self.assertRaisesRegex(RlmError, "RLM child binding is invalid"):
            _binding(proposal_digest="private-session-path")

        self.assertEqual(
            _binding().to_mapping(),
            {
                "action_id": "action-1",
                "child_id": "child-1",
                "parent_session_id": "session-1",
                "authority_revision": 1,
                "proposal_digest": "a" * 64,
                "depth": 1,
                "model_selector_digest": "b" * 64,
            },
        )

    def test_uncertain_started_child_is_fenced_from_replay(self) -> None:
        service = RlmChildService(_authority())
        binding = _binding()

        service.admit(binding)
        service.record_started(binding, native_identity="private-native-session")
        service.record_uncertain(binding)

        self.assertEqual(service.status("child-1").status, "uncertain")
        with self.assertRaisesRegex(RlmError, "RLM child is fenced"):
            service.admit(binding)
        self.assertNotIn("private-native-session", repr(service.public_registry()))

    def test_terminal_cannot_regress_or_change_private_identity(self) -> None:
        service = RlmChildService(_authority())
        binding = _binding()
        service.admit(binding)
        service.record_started(binding, native_identity="private-native-session")
        service.record_terminal(binding, status="completed")

        with self.assertRaisesRegex(RlmError, "RLM child is terminal"):
            service.record_started(binding, native_identity="private-native-session")
        with self.assertRaisesRegex(RlmError, "RLM child identity conflicts"):
            service.record_terminal(
                binding,
                status="completed",
                native_identity="other-private-session",
            )

    def test_reopen_fences_started_native_child_without_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = _binding()
            service = RlmChildService(_authority(), private_root=root)
            service.admit(binding)
            service.record_started(binding, native_identity="private-native-session")

            reopened = RlmChildService(_authority(), private_root=root)

        self.assertEqual(reopened.status("child-1").status, "uncertain")
        with self.assertRaisesRegex(RlmError, "RLM child is fenced"):
            reopened.admit(binding)
