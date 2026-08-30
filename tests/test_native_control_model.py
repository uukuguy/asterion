from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import Iterable, Mapping
from dataclasses import FrozenInstanceError, replace
from typing import cast

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.providers.native.model import (
    NATIVE_RECORD_KINDS,
    NativeActionResultReference,
    NativeCapsuleMetadata,
    NativeEntry,
    NativeEventDraft,
    NativeInputReference,
    NativeRecord,
    NativeTurnRequest,
    NativeTurnResult,
)
from asterion.control.providers.native.state import (
    NativeStateError,
    authority_synced_record,
    checkpoint_committed_record,
    command_committed_record,
    reduce_native_entries,
    session_bound_record,
    turn_committed_record,
    turn_recovery_required_record,
    turn_started_record,
)


SESSION_ID = "session-1"
GENERATION = 1
AUTHORITY_ID = "authority-1"
AUTHORITY_REVISION = 1
EMITTED_AT = "2026-08-30T00:00:00Z"


def _budget(**overrides: int) -> RemainingBudget:
    values = {
        "controller_tokens": 100,
        "application_tokens": 0,
        "child_tokens": 0,
        "aggregate_tokens": 100,
        "cost_micros": 10_000,
        "deadline_ms": 60_000,
    }
    values.update(overrides)
    return RemainingBudget(**values)


def _usage(**overrides: int) -> BudgetUsage:
    values = {
        "controller_tokens": 0,
        "application_tokens": 0,
        "child_tokens": 0,
        "aggregate_tokens": 0,
        "cost_micros": 0,
    }
    values.update(overrides)
    return BudgetUsage(**values)


def _command(
    command_id: str,
    command_type: str,
    payload: dict[str, object],
    *,
    session_id: str = SESSION_ID,
    authority_revision: int = AUTHORITY_REVISION,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id=session_id,
        authority_revision=authority_revision,
        type=command_type,
        payload=payload,
    )


def _event(
    event_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, object],
    *,
    session_id: str = SESSION_ID,
    generation: int = GENERATION,
) -> ControlEvent:
    return ControlEvent(
        event_id=event_id,
        session_id=session_id,
        generation=generation,
        sequence=sequence,
        emitted_at=EMITTED_AT,
        type=event_type,
        payload=payload,
    )


def _chain(records: Iterable[NativeRecord]) -> tuple[NativeEntry, ...]:
    entries: list[NativeEntry] = []
    previous_digest: str | None = None
    for position, record in enumerate(records, start=1):
        entry = NativeEntry(position, previous_digest, record)
        entries.append(entry)
        previous_digest = entry.digest
    return tuple(entries)


def _session_bound() -> NativeRecord:
    return session_bound_record(
        provider_id="native",
        provider_version="0.1.0",
        system_id="research.system",
        system_version="1.0.0",
        session_id=SESSION_ID,
        generation=GENERATION,
        checkpoint_version="1.0.0",
        authority_id=AUTHORITY_ID,
        authority_revision=AUTHORITY_REVISION,
    )


def _session_created() -> ControlEvent:
    return _event(
        "event-created",
        1,
        "session.created",
        {
            "goal_id": "goal-1",
            "authority_id": AUTHORITY_ID,
            "authority_revision": AUTHORITY_REVISION,
        },
    )


def _session_running(sequence: int = 2) -> ControlEvent:
    return _event(
        f"event-running-{sequence}",
        sequence,
        "session.running",
        {"reason_code": "started"},
    )


def _session_create_command() -> ControlCommand:
    return _command(
        "command-create",
        "session.create",
        {
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def _input_command(command_id: str = "command-input") -> ControlCommand:
    return _command(
        command_id,
        "input.submit",
        {
            "input_id": "input-1",
            "delivery": "direct",
            "content_ref": "input-ref-1",
        },
    )


def _action_resolution_command(
    command_id: str = "command-action-result",
) -> ControlCommand:
    return _command(
        command_id,
        "action.resolve",
        {
            "action_id": "action-1",
            "resolution": "succeeded",
            "reason_code": "ok",
            "receipt_ref": "receipt-1",
        },
    )


def _command_digest(command: ControlCommand) -> str:
    encoded = json.dumps(
        command.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _turn_request(
    *,
    input_command: ControlCommand | None = None,
    action_command: ControlCommand | None = None,
) -> NativeTurnRequest:
    inputs: tuple[NativeInputReference, ...] = ()
    if input_command is not None:
        payload = input_command.payload
        inputs = (
            NativeInputReference(
                input_id=str(payload["input_id"]),
                delivery=str(payload["delivery"]),
                content_ref=str(payload["content_ref"]),
                command_digest=_command_digest(input_command),
            ),
        )
    action_results: tuple[NativeActionResultReference, ...] = ()
    if action_command is not None:
        payload = action_command.payload
        action_results = (
            NativeActionResultReference(
                action_id=str(payload["action_id"]),
                resolution=str(payload["resolution"]),
                reason_code=str(payload["reason_code"]),
                receipt_ref=str(payload["receipt_ref"]),
                command_digest=_command_digest(action_command),
            ),
        )
    return NativeTurnRequest(
        turn_id="turn-1",
        session_id=SESSION_ID,
        generation=GENERATION,
        authority_revision=AUTHORITY_REVISION,
        causal_command_ids=tuple(
            sorted(
                command.command_id
                for command in (input_command, action_command)
                if command is not None
            )
        ),
        inputs=inputs,
        action_results=action_results,
        budget=_budget(),
    )


def _budget_report(
    event_id: str,
    sequence: int,
    usage: BudgetUsage,
) -> ControlEvent:
    return _event(
        event_id,
        sequence,
        "budget.reported",
        {
            "controller_tokens": usage.controller_tokens,
            "application_tokens": usage.application_tokens,
            "child_tokens": usage.child_tokens,
            "aggregate_tokens": usage.aggregate_tokens,
            "cost_micros": usage.cost_micros,
        },
    )


def _valid_records() -> tuple[NativeRecord, ...]:
    return (
        _session_bound(),
        authority_synced_record(AUTHORITY_REVISION, _budget()),
        command_committed_record(_session_create_command(), (_session_created(),)),
        turn_committed_record(
            NativeTurnResult(
                turn_id="turn-bootstrap",
                events=(NativeEventDraft("session.running", {"reason_code": "started"}),),
                usage=_usage(),
            ),
            (_session_running(),),
        ),
    )


def invalid_prefixes() -> tuple[tuple[str, tuple[NativeEntry, ...]], ...]:
    valid = _chain(_valid_records())
    fork = (
        valid[0],
        NativeEntry(2, "0" * 64, valid[1].record),
    )
    gap = (
        valid[0],
        NativeEntry(3, valid[0].digest, valid[1].record),
    )
    terminal = _event(
        "event-terminal",
        3,
        "session.completed",
        {"reason_code": "done"},
    )
    second_terminal = _event(
        "event-terminal-2",
        4,
        "session.failed",
        {"reason_code": "failed"},
    )
    duplicate_terminal = _chain(
        (
            *_valid_records(),
            turn_committed_record(
                NativeTurnResult(
                    turn_id="turn-terminal",
                    events=(NativeEventDraft("session.completed", {"reason_code": "done"}),),
                    usage=_usage(),
                ),
                (terminal,),
            ),
            turn_committed_record(
                NativeTurnResult(
                    turn_id="turn-terminal-2",
                    events=(
                        NativeEventDraft("session.failed", {"reason_code": "failed"}),
                    ),
                    usage=_usage(),
                ),
                (second_terminal,),
            ),
        )
    )
    return (
        ("fork", fork),
        ("gap", gap),
        ("second-terminal", duplicate_terminal),
    )


class TestNativeControlModel(unittest.TestCase):
    def test_record_digest_is_canonical_and_payload_is_frozen(self) -> None:
        payload: dict[str, object] = {
            "system_id": "research.system",
            "generation": 1,
            "nested": {"items": ["b", "a"]},
        }
        record = NativeRecord("session-bound", "session.bound", payload)
        same = NativeRecord(
            "session-bound",
            "session.bound",
            {"nested": {"items": ("b", "a")}, "generation": 1, "system_id": "research.system"},
        )

        payload["generation"] = 2

        self.assertEqual(record.payload["generation"], 1)
        self.assertEqual(record.digest, same.digest)
        self.assertRegex(record.digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("payload", repr(record))
        with self.assertRaises(TypeError):
            record.payload["generation"] = 3  # type: ignore[index]
        nested = record.payload["nested"]
        self.assertNotEqual(type(nested).__name__, "dict")
        nested_mapping = cast(Mapping[str, object], nested)
        with self.assertRaises(TypeError):
            nested_mapping["items"] = ()  # type: ignore[index]
        self.assertIsInstance(nested_mapping["items"], tuple)

    def test_entry_digest_covers_position_previous_digest_and_record(self) -> None:
        record = NativeRecord("record-1", "authority.synced", {"revision": 1})
        entry = NativeEntry(1, None, record)
        moved = NativeEntry(2, None, record)
        chained = NativeEntry(1, "a" * 64, record)

        self.assertRegex(entry.digest, r"^[0-9a-f]{64}$")
        self.assertNotEqual(entry.digest, moved.digest)
        self.assertNotEqual(entry.digest, chained.digest)

    def test_closed_record_constructors_emit_exact_payloads(self) -> None:
        budget = _budget()
        command = _input_command()
        action = _action_resolution_command()
        request = _turn_request(input_command=command, action_command=action)
        result = NativeTurnResult("turn-1", (), _usage(controller_tokens=3, aggregate_tokens=3))
        metadata = NativeCapsuleMetadata(
            capsule_id="capsule-1",
            capsule_digest="a" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=4,
            covered_sequence=2,
            storage_ref="storage-1",
        )
        checkpoint_event = _event(
            "event-checkpoint",
            3,
            "checkpoint.created",
            {
                "checkpoint_id": "checkpoint-1",
                "capsule_id": "capsule-1",
                "capsule_digest": "a" * 64,
                "control_plane_id": "native",
                "control_plane_version": "0.1.0",
                "checkpoint_version": "1.0.0",
                "covered_sequence": 2,
                "storage_ref": "storage-1",
            },
        )

        records = (
            _session_bound(),
            authority_synced_record(2, budget),
            command_committed_record(command, ()),
            turn_started_record(request),
            turn_committed_record(result, (), adapter_invoked=False),
            turn_recovery_required_record("turn-2", "adapter-failed", ()),
            checkpoint_committed_record(metadata, checkpoint_event),
        )

        self.assertEqual({record.kind for record in records}, NATIVE_RECORD_KINDS)
        self.assertEqual(
            set(records[0].payload),
            {
                "provider_id",
                "provider_version",
                "system_id",
                "system_version",
                "session_id",
                "generation",
                "checkpoint_version",
                "authority_id",
                "authority_revision",
            },
        )
        self.assertEqual(set(records[1].payload), {"authority_revision", "budget"})
        self.assertEqual(set(records[2].payload), {"command_digest", "command", "events"})
        self.assertEqual(set(records[3].payload), {"request"})
        self.assertEqual(
            set(records[4].payload),
            {"turn_id", "events", "usage", "adapter_invoked"},
        )
        self.assertEqual(set(records[5].payload), {"turn_id", "reason_code", "events"})
        self.assertEqual(set(records[6].payload), {"metadata", "event"})

    def test_reducer_rejects_extra_fields_in_closed_record_payloads(self) -> None:
        record = _session_bound()
        tampered = NativeRecord(
            record.record_id,
            record.kind,
            {**record.payload, "private_path": "/tmp/secret"},
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain((tampered,)))

    def test_reducer_accepts_contiguous_chain_and_activates_goal_on_session_created(
        self,
    ) -> None:
        state = reduce_native_entries(_chain(_valid_records()))

        self.assertEqual(state.provider_id, "native")
        self.assertEqual(state.session_id, SESSION_ID)
        self.assertEqual(state.lifecycle, "running")
        self.assertEqual(state.goal_id, "goal-1")
        self.assertEqual(state.goal_status, "active")
        self.assertEqual(tuple(event.type for event in state.events), ("session.created", "session.running"))
        self.assertEqual(state.next_sequence, 3)

    def test_reducer_rejects_gap_fork_and_second_terminal(self) -> None:
        for label, entries in invalid_prefixes():
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(entries)

    def test_equal_record_id_retry_is_ignored_but_conflict_is_rejected(self) -> None:
        input_command = _input_command()
        command_record = command_committed_record(input_command, ())
        retry = NativeRecord(
            command_record.record_id,
            command_record.kind,
            command_record.payload,
        )
        valid_with_retry = _chain((*_valid_records(), command_record, retry))

        state = reduce_native_entries(valid_with_retry)

        self.assertEqual(tuple(ref.input_id for ref in state.pending_inputs), ("input-1",))

        changed_command = _input_command("command-input")
        changed_payload = dict(changed_command.payload)
        changed_payload["content_ref"] = "input-ref-2"
        conflict_record = command_committed_record(
            replace(changed_command, payload=changed_payload),
            (),
        )
        conflict = _chain((*_valid_records(), command_record, conflict_record))
        with self.assertRaises(NativeStateError):
            reduce_native_entries(conflict)

    def test_authority_sync_record_id_includes_revision_and_budget_digest(self) -> None:
        first = authority_synced_record(1, _budget(controller_tokens=10, aggregate_tokens=10))
        retry = authority_synced_record(1, _budget(controller_tokens=10, aggregate_tokens=10))
        later_same_capacity = authority_synced_record(
            2,
            _budget(controller_tokens=10, aggregate_tokens=10),
        )

        self.assertEqual(first.record_id, retry.record_id)
        self.assertEqual(first.digest, retry.digest)
        self.assertNotEqual(first.record_id, later_same_capacity.record_id)

    def test_turn_usage_is_delta_and_budget_report_publishes_cumulative_usage(
        self,
    ) -> None:
        first_usage = _usage(controller_tokens=4, aggregate_tokens=4, cost_micros=10)
        second_usage = _usage(controller_tokens=6, aggregate_tokens=6, cost_micros=15)
        entries = _chain(
            (
                *_valid_records(),
                turn_committed_record(
                    NativeTurnResult(
                        "turn-1",
                        (
                            NativeEventDraft(
                                "budget.reported",
                                {
                                    "controller_tokens": 4,
                                    "application_tokens": 0,
                                    "child_tokens": 0,
                                    "aggregate_tokens": 4,
                                    "cost_micros": 10,
                                },
                            ),
                        ),
                        first_usage,
                    ),
                    (_budget_report("event-budget-1", 3, first_usage),),
                ),
                turn_committed_record(
                    NativeTurnResult(
                        "turn-2",
                        (
                            NativeEventDraft(
                                "budget.reported",
                                {
                                    "controller_tokens": 10,
                                    "application_tokens": 0,
                                    "child_tokens": 0,
                                    "aggregate_tokens": 10,
                                    "cost_micros": 25,
                                },
                            ),
                        ),
                        second_usage,
                    ),
                    (
                        _budget_report(
                            "event-budget-2",
                            4,
                            _usage(
                                controller_tokens=10,
                                aggregate_tokens=10,
                                cost_micros=25,
                            ),
                        ),
                    ),
                ),
            )
        )

        state = reduce_native_entries(entries)

        self.assertEqual(state.usage.controller_tokens, 10)
        self.assertEqual(state.usage.aggregate_tokens, 10)
        self.assertEqual(state.usage.cost_micros, 25)

    def test_reducer_rejects_usage_impersonating_application_or_child_work(self) -> None:
        for usage in (
            _usage(controller_tokens=1, application_tokens=1, aggregate_tokens=2),
            _usage(controller_tokens=1, child_tokens=1, aggregate_tokens=2),
            _usage(controller_tokens=1, aggregate_tokens=2),
        ):
            with self.subTest(usage=usage), self.assertRaises(NativeStateError):
                reduce_native_entries(
                    _chain(
                        (
                            *_valid_records(),
                            turn_committed_record(
                                NativeTurnResult("turn-bad", (), usage),
                                (),
                            ),
                        )
                    )
                )

    def test_pending_inputs_and_action_results_are_consumed_by_matching_turn(
        self,
    ) -> None:
        input_command = _input_command()
        action_command = _action_resolution_command()
        request = _turn_request(
            input_command=input_command,
            action_command=action_command,
        )
        entries = _chain(
            (
                *_valid_records(),
                command_committed_record(input_command, ()),
                command_committed_record(action_command, ()),
                turn_started_record(request),
                turn_committed_record(
                    NativeTurnResult("turn-1", (), _usage()),
                    (),
                ),
            )
        )

        state = reduce_native_entries(entries)

        self.assertEqual(state.pending_inputs, ())
        self.assertEqual(state.pending_action_results, ())
        self.assertEqual(state.pending_turn, None)

    def test_turn_started_rejects_mutated_or_unknown_command_inputs(self) -> None:
        input_command = _input_command()
        bad_request = replace(
            _turn_request(input_command=input_command),
            inputs=(
                NativeInputReference(
                    input_id="input-1",
                    delivery="direct",
                    content_ref="input-ref-2",
                    command_digest=_command_digest(input_command),
                ),
            ),
        )
        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain(
                    (
                        *_valid_records(),
                        command_committed_record(input_command, ()),
                        turn_started_record(bad_request),
                    )
                )
            )

    def test_events_are_generated_from_drafts_and_sequences_are_checked(self) -> None:
        result = NativeTurnResult(
            "turn-1",
            (NativeEventDraft("budget.reported", {"controller_tokens": 1}),),
            _usage(controller_tokens=1, aggregate_tokens=1),
        )
        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain(
                    (
                        *_valid_records(),
                        turn_committed_record(
                            result,
                            (
                                _budget_report(
                                    "event-budget-wrong",
                                    4,
                                    _usage(controller_tokens=1, aggregate_tokens=1),
                                ),
                            ),
                        ),
                    )
                )
            )

    def test_checkpoint_metadata_must_match_event_and_covered_state(self) -> None:
        base = _valid_records()
        metadata = NativeCapsuleMetadata(
            capsule_id="capsule-1",
            capsule_digest="b" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=4,
            covered_sequence=2,
            storage_ref="storage-1",
        )
        event = _event(
            "event-checkpoint",
            3,
            "checkpoint.created",
            {
                "checkpoint_id": "checkpoint-1",
                "capsule_id": "capsule-1",
                "capsule_digest": "b" * 64,
                "control_plane_id": "native",
                "control_plane_version": "0.1.0",
                "checkpoint_version": "1.0.0",
                "covered_sequence": 2,
                "storage_ref": "storage-1",
            },
        )
        state = reduce_native_entries(_chain((*base, checkpoint_committed_record(metadata, event))))
        self.assertEqual(state.checkpoint, metadata)

        stale = replace(metadata, covered_sequence=1)
        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain((*base, checkpoint_committed_record(stale, event))))

    def test_native_values_are_immutable(self) -> None:
        request = _turn_request()
        metadata = NativeCapsuleMetadata(
            capsule_id="capsule-1",
            capsule_digest="c" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=4,
            covered_sequence=2,
            storage_ref="storage-1",
        )

        with self.assertRaises(FrozenInstanceError):
            request.turn_id = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            metadata.storage_ref = "changed"  # type: ignore[misc]
        self.assertNotIn("storage_ref", repr(metadata))


if __name__ == "__main__":
    unittest.main()
