from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from collections.abc import Iterable, Mapping

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlCommand
from asterion.control.providers.native.verified import (
    NativeVerifiedFeatureError,
    NativeVerifiedFeatureRecord,
    native_verified_record_id,
    reduce_verified_feature_records,
)
from asterion.control.providers.native.capsule import MemoryNativeCapsuleStore
from asterion.control.providers.native.controller import NativeController
from asterion.control.providers.native.store import (
    MemoryNativeSessionStore,
    MemoryNativeStorageOwner,
)
from asterion.control.providers.native.model import NativeEventDraft, NativeTurnResult
from asterion.control.providers.native.turn import DeterministicNativeTurnAdapter


SESSION_ID = "session-1"
GENERATION = 1


def _record(
    feature_id: str,
    payload: Mapping[str, object],
    *,
    record_id: str | None = None,
) -> NativeVerifiedFeatureRecord:
    return NativeVerifiedFeatureRecord(
        feature_id=feature_id,
        record_id=record_id or native_verified_record_id(feature_id, payload),
        payload=payload,
    )


def _session_records() -> tuple[NativeVerifiedFeatureRecord, ...]:
    return (
        _record(
            "session.persistence-naming",
            {
                "session_id": SESSION_ID,
                "generation": GENERATION,
                "name_digest": "1" * 64,
                "active_continuation_id": "continuation-active",
                "transcript_id": "transcript-1",
            },
        ),
        _record(
            "session.delivery",
            {
                "session_id": SESSION_ID,
                "generation": GENERATION,
                "input_id": "input-1",
                "delivery": "direct",
                "ordinal": 1,
            },
        ),
        _record(
            "session.usage-status",
            {
                "session_id": SESSION_ID,
                "generation": GENERATION,
                "status": "running",
                "total_tokens": 5,
                "controller_tokens": 5,
                "cost_micros": 7,
            },
        ),
    )


def _records(
    items: Iterable[tuple[str, Mapping[str, object]]],
) -> tuple[NativeVerifiedFeatureRecord, ...]:
    return tuple(_record(feature_id, payload) for feature_id, payload in items)


def _selector_digest(continuation_id: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.native-verified-selector/v1",
                "session_id": SESSION_ID,
                "generation": GENERATION,
                "continuation_id": continuation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _rlm_snapshot_digest(
    environment_id: str,
    environment_digest: str,
    child_tokens: int,
    cost_micros: int,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.native-verified-rlm-snapshot/v1",
                "environment_id": environment_id,
                "environment_digest": environment_digest,
                "child_tokens": child_tokens,
                "cost_micros": cost_micros,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _rlm_restart_records() -> tuple[NativeVerifiedFeatureRecord, ...]:
    environment_id = "environment-1"
    environment_digest = "3" * 64
    return _records(
        (
            (
                "rlm.environment",
                {
                    "environment_id": environment_id,
                    "environment_digest": environment_digest,
                },
            ),
            (
                "rlm.usage-cost",
                {
                    "environment_id": environment_id,
                    "child_tokens": 7,
                    "cost_micros": 11,
                },
            ),
            (
                "rlm.recovery",
                {
                    "environment_id": environment_id,
                    "snapshot_digest": _rlm_snapshot_digest(
                        environment_id,
                        environment_digest,
                        7,
                        11,
                    ),
                },
            ),
            (
                "rlm.usage-cost",
                {
                    "environment_id": environment_id,
                    "child_tokens": 2,
                    "cost_micros": 3,
                },
            ),
        )
    )


def _goal_history() -> tuple[NativeVerifiedFeatureRecord, ...]:
    return _records(
        (
            ("operation.goals", {"operation_id": "operation-1", "goal_status": "active"}),
            (
                "operation.detach-attach-replay",
                {"operation_id": "operation-1", "cursor": 1, "event_digest": "5" * 64},
            ),
            (
                "operation.detach-attach-replay",
                {"operation_id": "operation-1", "cursor": 2, "event_digest": "6" * 64},
            ),
            (
                "operation.detach-attach-replay",
                {"operation_id": "operation-1", "cursor": 3, "event_digest": "7" * 64},
            ),
            (
                "operation.goals",
                {"operation_id": "operation-1", "goal_status": "succeeded"},
            ),
        )
    )


def _budget() -> RemainingBudget:
    return RemainingBudget(
        controller_tokens=100,
        application_tokens=0,
        child_tokens=0,
        aggregate_tokens=100,
        cost_micros=10_000,
        deadline_ms=60_000,
    )


def _create_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-create",
        session_id=SESSION_ID,
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def _input_command(
    command_id: str,
    input_id: str,
    delivery: str,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id=SESSION_ID,
        authority_revision=1,
        type="input.submit",
        payload={
            "input_id": input_id,
            "delivery": delivery,
            "content_ref": f"content-{input_id}",
        },
    )


class TestNativeVerifiedSessions(unittest.TestCase):
    def test_session_delivery_and_usage_are_immutable_and_ordered(self) -> None:
        state = reduce_verified_feature_records(_session_records())

        projection = state.session_projection(SESSION_ID)

        self.assertEqual(projection["deliveries"], ("input-1",))
        self.assertEqual(projection["delivery_modes"], ("direct",))
        self.assertEqual(projection["total_tokens"], 5)
        with self.assertRaises(TypeError):
            projection["session_id"] = "mutated"  # type: ignore[index]

    def test_session_records_reject_malformed_and_secret_bearing_payloads(
        self,
    ) -> None:
        with self.assertRaises(NativeVerifiedFeatureError) as feature_context:
            _record("session.tree-navigation", {})
        self.assertNotIn("session.tree-navigation", str(feature_context.exception))

        with self.assertRaises(NativeVerifiedFeatureError):
            _record(
                "session.delivery",
                {
                    "session_id": SESSION_ID,
                    "generation": GENERATION,
                    "input_id": "input-1",
                    "delivery": "direct",
                    "ordinal": 1,
                    "prompt": "SENTINEL_SECRET",
                },
            )

        with self.assertRaises(NativeVerifiedFeatureError) as sentinel_context:
            _record(
                "session.persistence-naming",
                {
                    "session_id": SESSION_ID,
                    "generation": GENERATION,
                    "name": "SENTINEL_SECRET",
                    "active_continuation_id": "continuation-active",
                    "transcript_id": "transcript-1",
                },
            )
        self.assertNotIn("SENTINEL_SECRET", str(sentinel_context.exception))

    def test_duplicate_replay_is_idempotent_and_conflicts_fail_closed(self) -> None:
        records = _session_records()
        state = reduce_verified_feature_records((*records, records[1]))
        self.assertEqual(state.session_projection(SESSION_ID)["deliveries"], ("input-1",))

        with self.assertRaises(NativeVerifiedFeatureError):
            _record(
                "session.delivery",
                {
                    "session_id": SESSION_ID,
                    "generation": GENERATION,
                    "input_id": "input-2",
                    "delivery": "direct",
                    "ordinal": 2,
                },
                record_id=records[1].record_id,
            )

    def test_persistence_naming_requires_digest_only_stable_public_values(
        self,
    ) -> None:
        base = _session_records()
        duplicate_name = _record("session.persistence-naming", base[0].payload)
        state = reduce_verified_feature_records((*base, duplicate_name))
        projection = state.session_projection(SESSION_ID)
        self.assertEqual(projection["name_digest"], "1" * 64)
        self.assertNotIn("name", projection)
        self.assertNotIn("path", projection)

        renamed = _record(
            "session.persistence-naming",
            {
                "session_id": SESSION_ID,
                "generation": GENERATION,
                "name_digest": "2" * 64,
                "active_continuation_id": "continuation-active",
                "transcript_id": "transcript-1",
            },
        )
        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records((*base, renamed))

    def test_resume_delete_uses_exact_selectors_and_rejects_active_delete(
        self,
    ) -> None:
        records = _records(
            (
                (
                    "session.persistence-naming",
                    {
                        "session_id": SESSION_ID,
                        "generation": GENERATION,
                        "name_digest": "1" * 64,
                        "active_continuation_id": "continuation-active",
                        "transcript_id": "transcript-1",
                    },
                ),
                (
                    "session.resume-delete",
                    {
                        "session_id": SESSION_ID,
                        "generation": GENERATION,
                        "operation": "resume",
                        "selector_digest": _selector_digest("continuation-active"),
                        "continuation_id": "continuation-active",
                    },
                ),
                (
                    "session.resume-delete",
                    {
                        "session_id": SESSION_ID,
                        "generation": GENERATION,
                        "operation": "delete",
                        "selector_digest": _selector_digest("continuation-old"),
                        "continuation_id": "continuation-old",
                    },
                ),
            )
        )
        projection = reduce_verified_feature_records(records).session_projection(SESSION_ID)
        self.assertEqual(projection["resumed_continuations"], ("continuation-active",))
        self.assertEqual(projection["deleted_continuations"], ("continuation-old",))
        self.assertNotIn("path", projection)

        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                (
                    records[0],
                    _record(
                        "session.resume-delete",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "operation": "delete",
                            "selector_digest": _selector_digest("continuation-active"),
                            "continuation_id": "continuation-active",
                        },
                    ),
                )
            )

        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                (
                    records[1],
                    _record(
                        "session.resume-delete",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "operation": "resume",
                            "selector_digest": _selector_digest("continuation-active"),
                            "continuation_id": "continuation-other",
                        },
                    ),
                )
            )

    def test_delivery_order_requires_direct_then_steer_then_follow_up(self) -> None:
        state = reduce_verified_feature_records(
            _records(
                (
                    (
                        "session.delivery",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "input_id": "input-1",
                            "delivery": "direct",
                            "ordinal": 1,
                        },
                    ),
                    (
                        "session.delivery",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "input_id": "input-2",
                            "delivery": "steer",
                            "ordinal": 2,
                        },
                    ),
                    (
                        "session.delivery",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "input_id": "input-3",
                            "delivery": "follow_up",
                            "ordinal": 3,
                        },
                    ),
                )
            )
        )
        self.assertEqual(
            state.session_projection(SESSION_ID)["deliveries"],
            ("input-1", "input-2", "input-3"),
        )

        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                _records(
                    (
                        (
                            "session.delivery",
                            {
                                "session_id": SESSION_ID,
                                "generation": GENERATION,
                                "input_id": "input-2",
                                "delivery": "follow_up",
                                "ordinal": 2,
                            },
                        ),
                        (
                            "session.delivery",
                            {
                                "session_id": SESSION_ID,
                                "generation": GENERATION,
                                "input_id": "input-1",
                                "delivery": "direct",
                                "ordinal": 1,
                            },
                        ),
                    )
                )
            )

    def test_usage_status_is_monotonic_body_free_and_current_generation(self) -> None:
        state = reduce_verified_feature_records(
            _records(
                (
                    (
                        "session.usage-status",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "status": "running",
                            "total_tokens": 2,
                            "controller_tokens": 2,
                            "cost_micros": 0,
                        },
                    ),
                    (
                        "session.usage-status",
                        {
                            "session_id": SESSION_ID,
                            "generation": GENERATION,
                            "status": "paused",
                            "total_tokens": 3,
                            "controller_tokens": 3,
                            "cost_micros": 1,
                        },
                    ),
                )
            )
        )
        projection = state.session_projection(SESSION_ID)
        self.assertEqual(projection["status"], "paused")
        self.assertEqual(projection["generation"], GENERATION)
        self.assertNotIn("provider_payload", projection)
        self.assertNotIn("raw_output", projection)

        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                _records(
                    (
                        (
                            "session.usage-status",
                            {
                                "session_id": SESSION_ID,
                                "generation": GENERATION,
                                "status": "running",
                                "total_tokens": 3,
                                "controller_tokens": 3,
                                "cost_micros": 1,
                            },
                        ),
                        (
                            "session.usage-status",
                            {
                                "session_id": SESSION_ID,
                                "generation": GENERATION,
                                "status": "running",
                                "total_tokens": 2,
                                "controller_tokens": 2,
                                "cost_micros": 1,
                            },
                        ),
                    )
                )
            )

    def test_controller_projects_verified_records_from_existing_journal(self) -> None:
        owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        session_store = MemoryNativeSessionStore(owner, max_record_bytes=65_536)
        capsule_store = MemoryNativeCapsuleStore(owner, max_capsule_bytes=65_536)
        controller = NativeController(
            owner=owner,
            session_store=session_store,
            capsule_store=capsule_store,
            turn_adapter=DeterministicNativeTurnAdapter(
                {}
            ),
            provider_id="asterion.native",
            provider_version="0.1.0",
            system_id="research.system",
            system_version="1.0.0",
            session_id=SESSION_ID,
            generation=GENERATION,
            checkpoint_version="1.0.0",
            authority_id="authority-1",
            authority_revision=1,
            event_id_factory=iter(("event-1", "event-2", "event-3")).__next__,
            turn_id_factory=iter(("turn-unused",)).__next__,
            capsule_id_factory=iter(("capsule-unused",)).__next__,
            clock=lambda: "2026-08-30T00:00:00Z",
        )
        try:
            asyncio.run(controller.accept(_create_command()))
            controller.sync_authority(_budget())
            asyncio.run(controller.accept(_input_command("command-input", "input-1", "direct")))
            request = controller.begin_ready_turn()
            self.assertIsNotNone(request)
            assert request is not None
            controller.commit_turn(
                request,
                NativeTurnResult(
                    request.turn_id,
                    (
                        NativeEventDraft(
                            "budget.reported",
                            {
                                "controller_tokens": 5,
                                "application_tokens": 0,
                                "child_tokens": 0,
                                "aggregate_tokens": 5,
                                "cost_micros": 1,
                            },
                        ),
                    ),
                    BudgetUsage(
                        controller_tokens=5,
                        application_tokens=0,
                        child_tokens=0,
                        aggregate_tokens=5,
                        cost_micros=1,
                    ),
                ),
            )

            state = reduce_verified_feature_records(controller.verified_feature_records())
            projection = state.session_projection(SESSION_ID)
            self.assertEqual(projection["deliveries"], ("input-1",))
            self.assertEqual(projection["total_tokens"], 5)
            self.assertEqual(len(state.operation_ids), 1)
            operation_id = state.operation_ids[0]
            self.assertEqual(state.operation_projection(operation_id)["goal_status"], "active")
            self.assertEqual(
                tuple(cursor for cursor, _ in state.replay(operation_id, after_cursor=0)),
                tuple(range(1, len(controller.state.events) + 1)),
            )
        finally:
            controller.close()


class TestNativeVerifiedRlm(unittest.TestCase):
    def test_snapshot_recovery_preserves_environment_and_usage(self) -> None:
        state = reduce_verified_feature_records(_rlm_restart_records())

        projection = state.rlm_projection("environment-1")

        self.assertEqual(projection["environment_digest"], "3" * 64)
        self.assertEqual(projection["child_tokens"], 9)
        self.assertEqual(projection["cost_micros"], 14)
        self.assertNotIn("snapshot", projection)
        with self.assertRaises(TypeError):
            projection["cost_micros"] = 0  # type: ignore[index]

    def test_recovery_rejects_missing_or_conflicting_snapshot_prefix(self) -> None:
        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                _records(
                    (
                        (
                            "rlm.recovery",
                            {
                                "environment_id": "environment-1",
                                "snapshot_digest": "4" * 64,
                            },
                        ),
                    )
                )
            )

        records = _rlm_restart_records()
        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                (
                    *records[:2],
                    _record(
                        "rlm.recovery",
                        {
                            "environment_id": "environment-1",
                            "snapshot_digest": _rlm_snapshot_digest(
                                "environment-1",
                                "3" * 64,
                                6,
                                11,
                            ),
                        },
                    ),
                )
            )

    def test_usage_rejects_unknown_environment_and_counter_overflow(self) -> None:
        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                _records(
                    (
                        (
                            "rlm.usage-cost",
                            {
                                "environment_id": "environment-missing",
                                "child_tokens": 1,
                                "cost_micros": 1,
                            },
                        ),
                    )
                )
            )

        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                _records(
                    (
                        (
                            "rlm.environment",
                            {
                                "environment_id": "environment-1",
                                "environment_digest": "3" * 64,
                            },
                        ),
                        (
                            "rlm.usage-cost",
                            {
                                "environment_id": "environment-1",
                                "child_tokens": 9_007_199_254_740_991,
                                "cost_micros": 0,
                            },
                        ),
                        (
                            "rlm.usage-cost",
                            {
                                "environment_id": "environment-1",
                                "child_tokens": 1,
                                "cost_micros": 0,
                            },
                        ),
                    )
                )
            )


class TestNativeVerifiedOperations(unittest.TestCase):
    def test_goal_detach_attach_replay_has_one_terminal_history(self) -> None:
        state = reduce_verified_feature_records(_goal_history())

        projection = state.operation_projection("operation-1")

        self.assertEqual(projection["goal_status"], "succeeded")
        self.assertEqual(
            state.replay("operation-1", after_cursor=2),
            ((3, "7" * 64),),
        )
        with self.assertRaises(TypeError):
            projection["goal_status"] = "mutated"  # type: ignore[index]

    def test_operation_rejects_second_terminal_and_cursor_gap(self) -> None:
        history = _goal_history()
        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                (
                    *history,
                    _record(
                        "operation.goals",
                        {"operation_id": "operation-1", "goal_status": "cancelled"},
                    ),
                )
            )

        with self.assertRaises(NativeVerifiedFeatureError):
            reduce_verified_feature_records(
                _records(
                    (
                        (
                            "operation.detach-attach-replay",
                            {
                                "operation_id": "operation-1",
                                "cursor": 2,
                                "event_digest": "5" * 64,
                            },
                        ),
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
