from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from asterion.control.authority import AuthorityEnvelope, BudgetLimit, PortfolioGrant
from asterion.control.rlm import (
    RlmChildBinding,
    RlmChildService,
    RlmError,
    RlmMessageBinding,
)


def _authority(*, max_concurrent_children: int = 1) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        authority_id="authority-1",
        revision=1,
        allowed_portfolio=(PortfolioGrant("example.provider", "alpha", "1.0.0", "fake.runtime"),),
        allowed_operations=("rlm.child.delete", "rlm.child.message", "rlm.child.spawn"),
        budget_limit=BudgetLimit(10, 10, 10, 30, 10),
        expires_at_ms=10_000,
        max_action_deadline_ms=1_000,
        max_recursion_depth=2,
        max_concurrent_children=max_concurrent_children,
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


def _message(**changes: object) -> RlmMessageBinding:
    values = {
        "message_id": "message-1",
        "sender_id": "session-1",
        "recipient_id": "child-1",
        "body_digest": "c" * 64,
        "authority_revision": 1,
    }
    values.update(changes)
    return RlmMessageBinding(**values)  # type: ignore[arg-type]


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

    def test_message_admission_accepts_parent_child_and_sibling_family_edges(self) -> None:
        service = RlmChildService(_authority(max_concurrent_children=2))
        binding = _binding()
        sibling = _binding(action_id="action-2", child_id="child-2")
        service.admit(binding)
        service.admit(sibling)
        service.record_started(binding, native_identity="private-native-session")
        service.record_started(sibling, native_identity="private-native-session-2")

        admitted = service.admit_message(_message())
        delivered = service.record_message_delivered(_message())
        sibling_message = service.admit_message(
            _message(
                message_id="message-2",
                sender_id="child-1",
                recipient_id="child-2",
            )
        )

        self.assertEqual(admitted.status, "admitted")
        self.assertEqual(delivered.status, "delivered")
        self.assertEqual(sibling_message.status, "admitted")
        self.assertEqual(service.public_messages()[0].to_mapping(), {
            "message_id": "message-1",
            "sender_id": "session-1",
            "recipient_id": "child-1",
            "body_digest": "c" * 64,
            "authority_revision": 1,
            "status": "delivered",
        })

    def test_message_rejects_nonfamily_or_terminal_parties_without_body(self) -> None:
        service = RlmChildService(_authority())
        binding = _binding()
        service.admit(binding)
        service.record_started(binding, native_identity="private-native-session")

        with self.assertRaisesRegex(RlmError, "RLM message target is unavailable"):
            service.admit_message(_message(recipient_id="outside-agent"))
        service.record_terminal(binding, status="completed")
        with self.assertRaisesRegex(RlmError, "RLM message target is unavailable"):
            service.admit_message(_message(sender_id="child-1", recipient_id="session-1"))
        with self.assertRaisesRegex(RlmError, "RLM message target is unavailable"):
            service.admit_message(
                _message(
                    message_id="message-2",
                    sender_id="child-1",
                    recipient_id="child-2",
                )
            )
        self.assertNotIn("outside-agent", repr(service.public_messages()))

    def test_reopen_fences_admitted_message_without_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = _binding()
            service = RlmChildService(_authority(), private_root=root)
            service.admit(binding)
            service.record_started(binding, native_identity="private-native-session")
            service.admit_message(_message())

            reopened = RlmChildService(_authority(), private_root=root)

        self.assertEqual(reopened.public_messages()[0].status, "uncertain")
        with self.assertRaisesRegex(RlmError, "RLM message is fenced"):
            reopened.admit_message(_message())

    def test_reopen_upgrades_pre_message_ledger_without_widening_children(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = _binding()
            service = RlmChildService(_authority(), private_root=root)
            service.admit(binding)
            service.record_started(binding, native_identity="private-native-session")
            stored = (root / "rlm-ledger.json").read_text()
            (root / "rlm-ledger.json").write_text(
                stored.replace(',"messages":[]', "")
            )

            reopened = RlmChildService(_authority(), private_root=root)

        self.assertEqual(reopened.status("child-1").status, "uncertain")
        self.assertEqual(reopened.public_messages(), ())
