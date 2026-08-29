from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.control.authority import AdmissionDecision, BudgetRequest
from asterion.control.host import ControlEvent
from asterion.control.state import (
    ControlState,
    ControlStateError,
    apply_action_admission,
    apply_action_resolution,
    apply_authority_revision,
    mark_action_running,
    reconcile_uncertain_action,
    reduce_control_event,
)


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "agent_control"
    / "v1"
    / "valid-event-action-proposed.json"
)


def _event(
    event_type: str,
    sequence: int,
    payload: dict[str, object],
    *,
    session_id: str = "session-1",
    generation: int = 1,
) -> ControlEvent:
    return ControlEvent.from_mapping(
        {
            "protocol": "asterion.agent-control/v1",
            "event_id": f"event-{sequence}",
            "session_id": session_id,
            "generation": generation,
            "sequence": sequence,
            "emitted_at": f"2026-08-09T15:00:{sequence:02d}Z",
            "type": event_type,
            "payload": payload,
        }
    )


def _proposal(sequence: int) -> ControlEvent:
    value = json.loads(PROPOSAL_FIXTURE.read_text())
    value["event_id"] = f"event-{sequence}"
    value["sequence"] = sequence
    return ControlEvent.from_mapping(value)


def _digest(event: ControlEvent) -> str:
    encoded = json.dumps(
        event.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _decision(event: ControlEvent, status: str = "admitted") -> AdmissionDecision:
    reservation = (
        BudgetRequest(
            controller_tokens=0,
            application_tokens=100,
            child_tokens=0,
            aggregate_tokens=100,
            cost_micros=5_000,
            deadline_ms=10_000,
        )
        if status == "admitted"
        else None
    )
    return AdmissionDecision(
        action_id="action-1",
        authority_id="authority-1",
        authority_revision=1,
        proposal_digest=_digest(event),
        status=status,
        reason="authorized" if status == "admitted" else "target-not-authorized",
        reservation=reservation,
    )


def _running_state() -> ControlState:
    state = ControlState.empty("session-1", generation=1)
    state = reduce_control_event(
        state,
        _event(
            "session.created",
            1,
            {
                "goal_id": "goal-1",
                "authority_id": "authority-1",
                "authority_revision": 1,
            },
        ),
    )
    return reduce_control_event(
        state,
        _event("session.running", 2, {"reason_code": "started"}),
    )


class TestControlState(unittest.TestCase):
    def test_paused_session_allows_only_checkpoint_proposals(self) -> None:
        paused = reduce_control_event(
            _running_state(),
            _event("session.paused", 3, {"reason_code": "checkpoint-boundary"}),
        )
        application = _proposal(4)
        with self.assertRaises(ControlStateError):
            reduce_control_event(paused, application)
        checkpoint = _event(
            "action.proposed",
            4,
            {
                "action_id": "checkpoint-action-1",
                "authority_revision": 1,
                "idempotency_key": "checkpoint-boundary-1",
                "kind": "checkpoint.create",
                "target": {
                    "kind": "checkpoint",
                    "checkpoint_id": "checkpoint-1",
                },
                "input_ref": "input-ref-1",
                "expected_artifacts": [],
                "budget": {
                    "controller_tokens": 1,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": 1,
                    "cost_micros": 0,
                    "deadline_ms": 10000,
                },
                "causal_parent_ids": ["goal-1", "task-1"],
            },
        )
        proposed = reduce_control_event(paused, checkpoint)
        self.assertIn("checkpoint-action-1", proposed.actions)
        admitted = apply_action_admission(
            proposed,
            AdmissionDecision(
                action_id="checkpoint-action-1",
                authority_id="authority-1",
                authority_revision=1,
                proposal_digest=_digest(checkpoint),
                status="admitted",
                reason="authorized",
                reservation=BudgetRequest(
                    controller_tokens=1,
                    application_tokens=0,
                    child_tokens=0,
                    aggregate_tokens=1,
                    cost_micros=0,
                    deadline_ms=10000,
                ),
            ),
        )
        self.assertEqual(
            mark_action_running(admitted, "checkpoint-action-1").actions[
                "checkpoint-action-1"
            ].status,
            "running",
        )

    def test_pause_recovery_goal_and_completion_sequence(self) -> None:
        state = _running_state()
        events = (
            _event("session.paused", 3, {"reason_code": "operator-request"}),
            _event("session.running", 4, {"reason_code": "resumed"}),
            _event(
                "session.recovery-required",
                5,
                {"reason_code": "provider-disconnected"},
            ),
            _event("session.running", 6, {"reason_code": "recovered"}),
            _event(
                "goal.updated",
                7,
                {"goal_id": "goal-1", "status": "completed"},
            ),
            _event("session.completed", 8, {"reason_code": "goal-accepted"}),
        )
        for event in events:
            state = reduce_control_event(state, event)

        self.assertEqual(state.session_status, "completed")
        self.assertEqual(state.goal_status, "completed")
        self.assertEqual(state.next_sequence, 9)
        self.assertEqual(state.terminal_event_id, "event-8")

    def test_paused_checkpoint_may_enter_recovery_required(self) -> None:
        state = reduce_control_event(
            _running_state(),
            _event("session.paused", 3, {"reason_code": "checkpoint-boundary"}),
        )

        recovered = reduce_control_event(
            state,
            _event(
                "session.recovery-required", 4,
                {"reason_code": "prime-checkpoint-restart"},
            ),
        )

        self.assertEqual(recovered.session_status, "recovery_required")

    def test_paused_session_accepts_its_checkpoint_receipt(self) -> None:
        """A checkpoint deliberately preserves an operator pause boundary."""

        paused = reduce_control_event(
            _running_state(),
            _event("session.paused", 3, {"reason_code": "checkpoint-boundary"}),
        )
        received = reduce_control_event(
            paused,
            _event(
                "checkpoint.created",
                4,
                {
                    "checkpoint_id": "checkpoint-1",
                    "capsule_id": "capsule-1",
                    "capsule_digest": "a" * 64,
                    "control_plane_id": "prime.gateway",
                    "control_plane_version": "0.1.0",
                    "checkpoint_version": "1.0.0",
                    "covered_sequence": 3,
                    "storage_ref": "checkpoint-store-1",
                },
            ),
        )

        self.assertEqual(received.session_status, "paused")
        self.assertEqual(received.next_sequence, 5)

    def test_paused_checkpoint_recovery_restores_the_pause_boundary(self) -> None:
        """Recovery must not turn an operator pause into an implicit resume."""

        state = reduce_control_event(
            _running_state(),
            _event("session.paused", 3, {"reason_code": "checkpoint-boundary"}),
        )
        state = reduce_control_event(
            state,
            _event(
                "session.recovery-required", 4,
                {"reason_code": "prime-checkpoint-restart"},
            ),
        )
        restored = reduce_control_event(
            state,
            _event("session.paused", 5, {"reason_code": "prime-checkpoint-restored"}),
        )

        self.assertEqual(restored.session_status, "paused")

    def test_paused_session_accepts_cancellation_goal_before_terminal_event(self) -> None:
        """Gateway cancellation records the goal outcome before the terminal."""

        paused = reduce_control_event(
            _running_state(),
            _event("session.paused", 3, {"reason_code": "checkpoint-boundary"}),
        )
        cancelled_goal = reduce_control_event(
            paused,
            _event("goal.updated", 4, {"goal_id": "goal-1", "status": "cancelled"}),
        )
        terminal = reduce_control_event(
            cancelled_goal,
            _event("session.cancelled", 5, {"reason_code": "operator-request"}),
        )

        self.assertEqual(terminal.goal_status, "cancelled")
        self.assertEqual(terminal.session_status, "cancelled")

    def test_recovery_required_session_accepts_recoverable_fault(self) -> None:
        state = reduce_control_event(
            _running_state(),
            _event("session.recovery-required", 3, {"reason_code": "restart"}),
        )
        observed = reduce_control_event(
            state,
            _event("fault.raised", 4, {"code": "prime-checkpoint-failed", "recoverable": True, "evidence_ref": None}),
        )
        self.assertEqual(observed.session_status, "recovery_required")

    def test_recovery_required_session_accepts_provider_terminal_completion(self) -> None:
        state = _running_state()
        state = reduce_control_event(
            state,
            _event(
                "session.recovery-required",
                3,
                {"reason_code": "provider-disconnected"},
            ),
        )
        state = reduce_control_event(
            state,
            _event(
                "goal.updated",
                4,
                {"goal_id": "goal-1", "status": "completed"},
            ),
        )

        completed = reduce_control_event(
            state,
            _event("session.completed", 5, {"reason_code": "provider-recovered"}),
        )

        self.assertEqual(completed.session_status, "completed")
        self.assertEqual(completed.terminal_event_id, "event-5")

    def test_action_admission_running_uncertain_and_reconciliation_are_explicit(self) -> None:
        state = _running_state()
        proposal = _proposal(3)
        state = reduce_control_event(state, proposal)
        state = apply_action_admission(state, _decision(proposal))
        state = mark_action_running(state, "action-1")
        state = apply_action_resolution(state, "action-1", "uncertain")

        with self.assertRaises(ControlStateError):
            mark_action_running(state, "action-1")
        with self.assertRaises(ControlStateError):
            apply_action_resolution(state, "action-1", "succeeded")

        state = reconcile_uncertain_action(
            state,
            "action-1",
            "succeeded",
            receipt_ref="receipt-1",
        )
        self.assertEqual(state.actions["action-1"].status, "succeeded")
        self.assertEqual(state.actions["action-1"].receipt_ref, "receipt-1")

    def test_rejects_gaps_identity_mismatch_and_illegal_session_transitions(self) -> None:
        state = _running_state()
        cases = (
            _event("session.paused", 4, {"reason_code": "operator-request"}),
            _event(
                "session.paused",
                3,
                {"reason_code": "operator-request"},
                session_id="session-2",
            ),
            _event(
                "session.paused",
                3,
                {"reason_code": "operator-request"},
                generation=2,
            ),
            _event("session.created", 3, {
                "goal_id": "goal-1",
                "authority_id": "authority-1",
                "authority_revision": 1,
            }),
        )
        for event in cases:
            with self.subTest(event=event), self.assertRaises(ControlStateError):
                reduce_control_event(state, event)

    def test_duplicate_action_and_admission_decision_fail_closed(self) -> None:
        state = _running_state()
        proposal = _proposal(3)
        state = reduce_control_event(state, proposal)
        with self.assertRaises(ControlStateError):
            reduce_control_event(
                state,
                replace(proposal, event_id="event-4", sequence=4),
            )
        admitted = apply_action_admission(state, _decision(proposal))
        with self.assertRaises(ControlStateError):
            apply_action_admission(admitted, _decision(proposal, "rejected"))

    def test_cancellation_cascades_and_terminal_event_is_unique(self) -> None:
        state = _running_state()
        proposal = _proposal(3)
        state = apply_action_admission(
            reduce_control_event(state, proposal),
            _decision(proposal),
        )
        state = mark_action_running(state, "action-1")
        state = reduce_control_event(
            state,
            _event("session.cancelled", 4, {"reason_code": "operator-request"}),
        )

        self.assertEqual(state.session_status, "cancelled")
        self.assertEqual(state.actions["action-1"].status, "cancelled")
        with self.assertRaises(ControlStateError):
            reduce_control_event(
                state,
                _event("session.failed", 5, {"reason_code": "late-failure"}),
            )

    def test_budget_limited_resume_requires_a_new_authority_revision(self) -> None:
        state = reduce_control_event(
            _running_state(),
            _event("session.budget-limited", 3, {"reason_code": "budget-exhausted"}),
        )
        with self.assertRaises(ControlStateError):
            reduce_control_event(
                state,
                _event("session.running", 4, {"reason_code": "resumed"}),
            )
        with self.assertRaises(ControlStateError):
            apply_authority_revision(state, 1)

        state = apply_authority_revision(state, 2)
        state = reduce_control_event(
            state,
            _event(
                "session.running",
                1,
                {"reason_code": "resumed"},
                generation=2,
            ),
        )
        self.assertEqual((state.session_status, state.authority_revision), ("running", 2))

    def test_reducer_is_pure_and_preserves_input_state(self) -> None:
        state = _running_state()
        before = state
        event = _event("session.paused", 3, {"reason_code": "operator-request"})

        first = reduce_control_event(state, event)
        second = reduce_control_event(state, event)

        self.assertEqual(first, second)
        self.assertIs(state, before)
        self.assertEqual(state.session_status, "running")
        self.assertEqual(first.session_status, "paused")


if __name__ == "__main__":
    unittest.main()
