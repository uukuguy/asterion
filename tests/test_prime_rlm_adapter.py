from __future__ import annotations

import unittest
from hashlib import sha256

from asterion.control.authority import (
    AuthorityEnvelope,
    BudgetLimit,
    PortfolioGrant,
)
from asterion.control.host import ControlEvent
from asterion.control.providers.prime.client import RlmAdmissionBinding
from asterion.control.providers.prime.client import RlmLifecycleObservation
from asterion.control.providers.prime.client import RlmMessageAdmissionBinding
from asterion.control.providers.prime.rlm import PrimeRlmAdmissionPreparer
from asterion.control.providers.prime.rlm import PrimeRlmActionLifecycle
from asterion.control.providers.prime.rlm import build_prime_rlm_host_components
from asterion.control.rlm import RlmChildService, RlmError
from asterion.control.authority import BudgetUsage


def _authority() -> AuthorityEnvelope:
    return AuthorityEnvelope(
        authority_id="authority-1",
        revision=1,
        allowed_portfolio=(
            PortfolioGrant("example.provider", "alpha", "1.0.0", "fake.runtime"),
        ),
        allowed_operations=("rlm.child.message", "rlm.child.spawn"),
        budget_limit=BudgetLimit(10, 10, 10, 30, 10),
        expires_at_ms=10_000,
        max_action_deadline_ms=1_000,
        max_recursion_depth=2,
        max_concurrent_children=1,
        execution_domain="trusted-local",
        host_service_grants=("storage.private",),
    )


def _proposal(
    *, action_id: str = "action-1", child_id: str = "child-1", event_id: str = "event-1"
) -> ControlEvent:
    return ControlEvent.from_mapping(
        {
            "protocol": "asterion.agent-control/v1",
            "event_id": event_id,
            "session_id": "session-1",
            "generation": 1,
            "sequence": 1,
            "emitted_at": "2026-08-12T10:00:00Z",
            "type": "action.proposed",
            "payload": {
                "action_id": action_id,
                "authority_revision": 1,
                "idempotency_key": "spawn-1",
                "kind": "child.spawn",
                "target": {"kind": "child", "child_id": child_id},
                "input_ref": "input-1",
                "expected_artifacts": [],
                "budget": {
                    "controller_tokens": 0,
                    "application_tokens": 0,
                    "child_tokens": 1,
                    "aggregate_tokens": 1,
                    "cost_micros": 0,
                    "deadline_ms": 1,
                },
                "causal_parent_ids": [],
            },
        }
    )


class _Client:
    def __init__(self, binding: RlmAdmissionBinding) -> None:
        self.binding = binding
        self.calls: list[str] = []
        self.lifecycle: tuple[RlmLifecycleObservation, ...] = ()
        self.message_calls: list[str] = []
        self.message_binding = RlmMessageAdmissionBinding(
            "message-action",
            "message-1",
            "session-1",
            "child-1",
            1,
            "c" * 64,
            False,
        )

    async def rlm_binding(self, action_id: str) -> RlmAdmissionBinding:
        self.calls.append(action_id)
        return self.binding

    async def rlm_lifecycle(self):
        return self.lifecycle

    async def rlm_message_binding(self, action_id: str) -> RlmMessageAdmissionBinding:
        self.message_calls.append(action_id)
        return self.message_binding


class TestPrimeRlmAdmissionPreparer(unittest.IsolatedAsyncioTestCase):
    async def test_prepares_and_settles_native_message_only_after_delivery(self) -> None:
        service = RlmChildService(_authority())
        client = _Client(
            RlmAdmissionBinding("spawn-action", "child-1", 1, 1, "a" * 64)
        )
        client.lifecycle = ()
        client.message_calls = []
        client.message_binding = RlmMessageAdmissionBinding(
            "message-action",
            "message-1",
            "session-1",
            "child-1",
            1,
            "c" * 64,
            False,
        )
        preparer = PrimeRlmAdmissionPreparer(
            client=client, children=service, parent_session_id="session-1"
        )
        await preparer.prepare(_proposal(action_id="spawn-action"))
        message = ControlEvent.from_mapping(
            {
                "protocol": "asterion.agent-control/v1",
                "event_id": "event-message",
                "session_id": "session-1",
                "generation": 1,
                "sequence": 2,
                "emitted_at": "2026-08-12T10:00:01Z",
                "type": "action.proposed",
                "payload": {
                    "action_id": "message-action",
                    "authority_revision": 1,
                    "idempotency_key": "message-1",
                    "kind": "child.message",
                    "target": {"kind": "child", "child_id": "child-1"},
                    "input_ref": "input-2",
                    "expected_artifacts": [],
                    "budget": {
                        "controller_tokens": 0,
                        "application_tokens": 0,
                        "child_tokens": 0,
                        "aggregate_tokens": 0,
                        "cost_micros": 0,
                        "deadline_ms": 1,
                    },
                    "causal_parent_ids": [],
                },
            }
        )

        await preparer.prepare(message)
        lifecycle = PrimeRlmActionLifecycle(preparer)
        self.assertTrue(lifecycle.owns(message))
        self.assertEqual(service.public_messages()[0].status, "admitted")
        self.assertEqual(await lifecycle.reconcile(), ())

        client.message_binding = RlmMessageAdmissionBinding(
            "message-action", "message-1", "session-1", "child-1", 1,
            "c" * 64, True,
        )
        terminals = await lifecycle.reconcile()

        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0].action_id, "message-action")
        self.assertEqual(terminals[0].status, "succeeded")
        self.assertIsNotNone(terminals[0].receipt)
        assert terminals[0].receipt is not None
        self.assertEqual(terminals[0].receipt.usage, BudgetUsage.zero())
        self.assertEqual(
            terminals[0].receipt.receipt_ref,
            "rlm-message-" + sha256(b"message-action").hexdigest(),
        )
        self.assertEqual(service.public_messages()[0].status, "delivered")
    async def test_builds_one_consistent_prime_rlm_host_component_set(self) -> None:
        client = _Client(
            RlmAdmissionBinding("action-1", "child-1", 1, 1, "a" * 64)
        )
        components = build_prime_rlm_host_components(
            client=client,
            authority=_authority(),
            parent_session_id="session-1",
        )

        self.assertIsInstance(components.children, RlmChildService)
        self.assertIsInstance(components.admission_preparer, PrimeRlmAdmissionPreparer)
        self.assertIsInstance(components.action_lifecycle, PrimeRlmActionLifecycle)
        self.assertIs(components.action_lifecycle._preparer, components.admission_preparer)

    async def test_prepares_exact_gateway_binding_before_prime_delivery(self) -> None:
        service = RlmChildService(_authority())
        client = _Client(
            RlmAdmissionBinding("action-1", "child-1", 1, 1, "a" * 64)
        )
        preparer = PrimeRlmAdmissionPreparer(
            client=client, children=service, parent_session_id="session-1"
        )

        await preparer.prepare(_proposal())

        self.assertEqual(client.calls, ["action-1"])
        self.assertEqual(service.status("child-1").status, "admitted")

    async def test_rejects_gateway_binding_identity_drift_before_effect(self) -> None:
        service = RlmChildService(_authority())
        preparer = PrimeRlmAdmissionPreparer(
            client=_Client(
                RlmAdmissionBinding("action-1", "child-other", 1, 1, "a" * 64)
            ),
            children=service,
            parent_session_id="session-1",
        )

        with self.assertRaises(RlmError):
            await preparer.prepare(_proposal())

        with self.assertRaises(RlmError):
            service.status("child-1")

    async def test_reconciles_native_started_and_terminal_without_identity_leak(self) -> None:
        service = RlmChildService(_authority())
        client = _Client(
            RlmAdmissionBinding("action-1", "child-1", 1, 1, "a" * 64)
        )
        client.lifecycle = ()
        preparer = PrimeRlmAdmissionPreparer(
            client=client, children=service, parent_session_id="session-1"
        )
        await preparer.prepare(_proposal())
        client.lifecycle = (
            RlmLifecycleObservation(
                "rlm.child.started", "child-1", native_identity_digest="b" * 64
            ),
            RlmLifecycleObservation("rlm.child.terminal", "child-1", "completed"),
        )

        await preparer.reconcile_lifecycle()
        await preparer.reconcile_lifecycle()

        self.assertEqual(service.status("child-1").status, "completed")

    async def test_completed_native_child_stays_uncertain_without_verified_result(self) -> None:
        service = RlmChildService(_authority())
        client = _Client(
            RlmAdmissionBinding("action-1", "child-1", 1, 1, "a" * 64)
        )
        client.lifecycle = ()
        preparer = PrimeRlmAdmissionPreparer(
            client=client, children=service, parent_session_id="session-1"
        )
        await preparer.prepare(_proposal())
        client.lifecycle = (
            RlmLifecycleObservation(
                "rlm.child.started", "child-1", native_identity_digest="b" * 64
            ),
            RlmLifecycleObservation("rlm.child.terminal", "child-1", "completed"),
        )

        terminals = await PrimeRlmActionLifecycle(preparer).reconcile()

        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0].status, "uncertain")

    async def test_owns_only_bound_prime_action_and_reports_active_child(self) -> None:
        service = RlmChildService(_authority())
        client = _Client(
            RlmAdmissionBinding("action-1", "child-1", 1, 1, "a" * 64)
        )
        preparer = PrimeRlmAdmissionPreparer(
            client=client, children=service, parent_session_id="session-1"
        )
        lifecycle = PrimeRlmActionLifecycle(preparer)
        unrelated = _proposal(
            action_id="action-2", child_id="child-2", event_id="event-2"
        )

        self.assertFalse(lifecycle.owns(_proposal()))
        self.assertFalse(lifecycle.owns(unrelated))
        self.assertEqual(lifecycle.active_child_count, 0)

        await preparer.prepare(_proposal())

        self.assertTrue(lifecycle.owns(_proposal()))
        self.assertFalse(lifecycle.owns(unrelated))
        self.assertEqual(lifecycle.active_child_count, 1)
