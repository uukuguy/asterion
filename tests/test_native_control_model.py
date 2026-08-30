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
MAX_PROTOCOL_ID = "a" * 128
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
        initial_create_command=_session_create_command(),
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


class HostileControlCommand(ControlCommand):
    mapping_calls: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping_calls", 0)

    def to_mapping(self) -> Mapping[str, object]:
        object.__setattr__(self, "mapping_calls", self.mapping_calls + 1)
        raise AssertionError("SENTINEL_SECRET")


class HostileControlEvent(ControlEvent):
    mapping_calls: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping_calls", 0)

    def to_mapping(self) -> Mapping[str, object]:
        object.__setattr__(self, "mapping_calls", self.mapping_calls + 1)
        raise AssertionError("SENTINEL_SECRET")


class HostileNativeCapsuleMetadata(NativeCapsuleMetadata):
    attribute_reads: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "attribute_reads", 0)

    def __getattribute__(self, name: str) -> object:
        if name in {
            "capsule_id",
            "capsule_digest",
            "control_plane_id",
            "control_plane_version",
            "checkpoint_version",
            "covered_position",
            "covered_sequence",
            "storage_ref",
        }:
            object.__setattr__(
                self,
                "attribute_reads",
                object.__getattribute__(self, "attribute_reads") + 1,
            )
            raise AssertionError("SENTINEL_SECRET")
        return super().__getattribute__(name)


def _valid_records() -> tuple[NativeRecord, ...]:
    return (
        _session_bound(),
        authority_synced_record(AUTHORITY_REVISION, _budget()),
        command_committed_record(
            _session_create_command(),
            (_session_created(), _session_running()),
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
    terminal_request = NativeTurnRequest(
        turn_id="turn-terminal",
        session_id=SESSION_ID,
        generation=GENERATION,
        authority_revision=AUTHORITY_REVISION,
        causal_command_ids=(),
        inputs=(),
        action_results=(),
        budget=_budget(),
    )
    duplicate_terminal = _chain(
        (
            *_valid_records(),
            turn_started_record(terminal_request),
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


def _terminal_records() -> tuple[NativeRecord, ...]:
    request = NativeTurnRequest(
        turn_id="turn-terminal",
        session_id=SESSION_ID,
        generation=GENERATION,
        authority_revision=AUTHORITY_REVISION,
        causal_command_ids=(),
        inputs=(),
        action_results=(),
        budget=_budget(),
    )
    return (
        *_valid_records(),
        turn_started_record(request),
        turn_committed_record(
            NativeTurnResult(
                turn_id="turn-terminal",
                events=(
                    NativeEventDraft(
                        "session.completed",
                        {"reason_code": "done"},
                    ),
                ),
                usage=_usage(),
            ),
            (
                _event(
                    "event-terminal",
                    3,
                    "session.completed",
                    {"reason_code": "done"},
                ),
            ),
        ),
    )


class TestNativeControlModel(unittest.TestCase):
    def test_record_constructors_exact_type_check_public_values_before_effects(
        self,
    ) -> None:
        hostile_command = HostileControlCommand(
            command_id="command-hostile",
            session_id=SESSION_ID,
            authority_revision=AUTHORITY_REVISION,
            type="session.create",
            payload=_session_create_command().payload,
        )
        with self.assertRaises(NativeStateError):
            session_bound_record(
                provider_id="native",
                provider_version="0.1.0",
                system_id="research.system",
                system_version="1.0.0",
                session_id=SESSION_ID,
                generation=GENERATION,
                checkpoint_version="1.0.0",
                authority_id=AUTHORITY_ID,
                authority_revision=AUTHORITY_REVISION,
                initial_create_command=hostile_command,
            )
        with self.assertRaises(NativeStateError):
            command_committed_record(hostile_command, ())
        self.assertEqual(hostile_command.mapping_calls, 0)

        hostile_event = HostileControlEvent(
            event_id="event-hostile",
            session_id=SESSION_ID,
            generation=GENERATION,
            sequence=1,
            emitted_at=EMITTED_AT,
            type="session.created",
            payload=_session_created().payload,
        )
        with self.assertRaises(NativeStateError):
            command_committed_record(_session_create_command(), (hostile_event,))
        self.assertEqual(hostile_event.mapping_calls, 0)

        hostile_metadata = HostileNativeCapsuleMetadata(
            capsule_id="capsule-hostile",
            capsule_digest="a" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=3,
            covered_sequence=2,
            storage_ref="storage-hostile",
        )
        with self.assertRaises(NativeStateError):
            checkpoint_committed_record(
                hostile_metadata,
                _event(
                    "event-checkpoint",
                    3,
                    "checkpoint.created",
                    {
                        "checkpoint_id": "checkpoint-hostile",
                        "capsule_id": "capsule-hostile",
                        "capsule_digest": "a" * 64,
                        "control_plane_id": "native",
                        "control_plane_version": "0.1.0",
                        "checkpoint_version": "1.0.0",
                        "covered_sequence": 2,
                        "storage_ref": "storage-hostile",
                    },
                ),
            )
        self.assertEqual(hostile_metadata.attribute_reads, 0)

    def test_session_bound_persists_initial_create_digest_without_committing_command(
        self,
    ) -> None:
        command = _session_create_command()
        record = session_bound_record(
            provider_id="native",
            provider_version="0.1.0",
            system_id="research.system",
            system_version="1.0.0",
            session_id=SESSION_ID,
            generation=GENERATION,
            checkpoint_version="1.0.0",
            authority_id=AUTHORITY_ID,
            authority_revision=AUTHORITY_REVISION,
            initial_create_command=command,
        )

        self.assertEqual(
            record.payload["initial_create_command_digest"],
            _command_digest(command),
        )
        state = reduce_native_entries(_chain((record,)))
        self.assertEqual(state.initial_create_command_digest, _command_digest(command))
        self.assertEqual(state.command_digests, {})
        self.assertEqual(state.events, ())

        for label, payload in (
            (
                "missing",
                {
                    key: value
                    for key, value in record.payload.items()
                    if key != "initial_create_command_digest"
                },
            ),
            (
                "drift",
                {**record.payload, "initial_create_command_digest": "0" * 64},
            ),
        ):
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(
                    _chain((NativeRecord(record.record_id, record.kind, payload),))
                )

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
            covered_position=3,
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
                "initial_create_command_digest",
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

    def test_reducer_enforces_canonical_record_ids_for_every_kind(self) -> None:
        input_command = _input_command()
        request = _turn_request(input_command=input_command)
        checkpoint_event = _event(
            "event-checkpoint",
            3,
            "checkpoint.created",
            {
                "checkpoint_id": "checkpoint-1",
                "capsule_id": "capsule-1",
                "capsule_digest": "d" * 64,
                "control_plane_id": "native",
                "control_plane_version": "0.1.0",
                "checkpoint_version": "1.0.0",
                "covered_sequence": 2,
                "storage_ref": "storage-1",
            },
        )
        metadata = NativeCapsuleMetadata(
            capsule_id="capsule-1",
            capsule_digest="d" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=3,
            covered_sequence=2,
            storage_ref="storage-1",
        )
        cases = (
            ("session.bound", (NativeRecord("wrong-session-bound", "session.bound", _session_bound().payload),)),
            (
                "authority.synced",
                (
                    _session_bound(),
                    NativeRecord(
                        "wrong-authority",
                        "authority.synced",
                        authority_synced_record(AUTHORITY_REVISION, _budget()).payload,
                    ),
                ),
            ),
            (
                "command.committed",
                (
                    *_valid_records(),
                    NativeRecord(
                        "wrong-command",
                        "command.committed",
                        command_committed_record(input_command, ()).payload,
                    ),
                ),
            ),
            (
                "turn.started",
                (
                    *_valid_records(),
                    command_committed_record(input_command, ()),
                    NativeRecord(
                        "wrong-turn-start",
                        "turn.started",
                        turn_started_record(request).payload,
                    ),
                ),
            ),
            (
                "turn.committed",
                (
                    *_valid_records(),
                    NativeRecord(
                        "wrong-turn-commit",
                        "turn.committed",
                        turn_committed_record(
                            NativeTurnResult("turn-2", (), _usage()),
                            (),
                            adapter_invoked=False,
                        ).payload,
                    ),
                ),
            ),
            (
                "turn.recovery-required",
                (
                    *_valid_records(),
                    NativeRecord(
                        "wrong-turn-recovery",
                        "turn.recovery-required",
                        turn_recovery_required_record("turn-2", "adapter-failed", ()).payload,
                    ),
                ),
            ),
            (
                "checkpoint.committed",
                (
                    *_valid_records(),
                    NativeRecord(
                        "wrong-checkpoint",
                        "checkpoint.committed",
                        checkpoint_committed_record(metadata, checkpoint_event).payload,
                    ),
                ),
            ),
        )

        for label, records in cases:
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(_chain(records))

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

    def test_reducer_rejects_every_nonduplicate_record_after_terminal(self) -> None:
        command = _input_command("command-after-terminal")
        request = NativeTurnRequest(
            turn_id="turn-after-terminal",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        checkpoint_event = _event(
            "event-checkpoint-after-terminal",
            4,
            "checkpoint.created",
            {
                "checkpoint_id": "checkpoint-after-terminal",
                "capsule_id": "capsule-after-terminal",
                "capsule_digest": "e" * 64,
                "control_plane_id": "native",
                "control_plane_version": "0.1.0",
                "checkpoint_version": "1.0.0",
                "covered_sequence": 3,
                "storage_ref": "storage-after-terminal",
            },
        )
        metadata = NativeCapsuleMetadata(
            capsule_id="capsule-after-terminal",
            capsule_digest="e" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=5,
            covered_sequence=3,
            storage_ref="storage-after-terminal",
        )
        cases = (
            ("authority", authority_synced_record(2, _budget())),
            ("command-without-events", command_committed_record(command, ())),
            ("turn-started", turn_started_record(request)),
            (
                "turn-committed",
                turn_committed_record(
                    NativeTurnResult("turn-after-terminal", (), _usage()),
                    (),
                    adapter_invoked=False,
                ),
            ),
            (
                "turn-recovery",
                turn_recovery_required_record(
                    "turn-after-terminal",
                    "adapter-failed",
                    (),
                ),
            ),
            ("checkpoint", checkpoint_committed_record(metadata, checkpoint_event)),
        )

        for label, record in cases:
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(_chain((*_terminal_records(), record)))

    def test_reducer_allows_exact_duplicate_record_replay_after_terminal(self) -> None:
        records = _terminal_records()
        state = reduce_native_entries(_chain((*records, records[-1])))

        self.assertEqual(state.terminal_event_id, "event-terminal")
        self.assertEqual(tuple(event.event_id for event in state.events).count("event-terminal"), 1)

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

    def test_reducer_rejects_same_command_id_with_noncanonical_fresh_events(self) -> None:
        input_command = _input_command()
        command_record = command_committed_record(input_command, ())
        replay_with_fresh_event = NativeRecord(
            "command-replay:command-input",
            "command.committed",
            {
                "command_digest": command_record.payload["command_digest"],
                "command": command_record.payload["command"],
                "events": (
                    _budget_report(
                        "event-command-replay",
                        3,
                        _usage(),
                    ).to_mapping(),
                ),
            },
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain((*_valid_records(), command_record, replay_with_fresh_event))
            )

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
        first_request = NativeTurnRequest(
            turn_id="turn-1",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        second_request = NativeTurnRequest(
            turn_id="turn-2",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(controller_tokens=96, aggregate_tokens=96, cost_micros=9_990),
        )
        entries = _chain(
            (
                *_valid_records(),
                turn_started_record(first_request),
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
                turn_started_record(second_request),
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

    def test_turn_start_requires_synced_authority_budget_and_exact_request_budget(
        self,
    ) -> None:
        request = NativeTurnRequest(
            turn_id="turn-budget",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        missing_sync_prefix = (
            _session_bound(),
            command_committed_record(
                _session_create_command(),
                (_session_created(), _session_running()),
            ),
        )
        mismatch_budget = replace(
            request,
            budget=_budget(controller_tokens=99, aggregate_tokens=99),
        )

        cases = (
            ("missing-sync", (*missing_sync_prefix, turn_started_record(request))),
            ("budget-mismatch", (*_valid_records(), turn_started_record(mismatch_budget))),
        )
        for label, records in cases:
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(_chain(records))

    def test_turn_commit_usage_must_not_exceed_pending_budget_by_field(self) -> None:
        fields = ("controller_tokens", "aggregate_tokens", "cost_micros")
        for field in fields:
            budget_values = {
                "controller_tokens": 5,
                "aggregate_tokens": 5,
                "cost_micros": 5,
            }
            budget = _budget(**budget_values)
            usage_values = {
                "controller_tokens": 1,
                "aggregate_tokens": 1,
                "cost_micros": 1,
            }
            if field in {"controller_tokens", "aggregate_tokens"}:
                usage_values["controller_tokens"] = 6
                usage_values["aggregate_tokens"] = 6
            else:
                usage_values[field] = 6
            request = NativeTurnRequest(
                turn_id=f"turn-overrun-{field}",
                session_id=SESSION_ID,
                generation=GENERATION,
                authority_revision=AUTHORITY_REVISION,
                causal_command_ids=(),
                inputs=(),
                action_results=(),
                budget=budget,
            )
            records = (
                _session_bound(),
                authority_synced_record(AUTHORITY_REVISION, budget),
                command_committed_record(
                    _session_create_command(),
                    (_session_created(), _session_running()),
                ),
                turn_started_record(request),
                turn_committed_record(
                    NativeTurnResult(
                        f"turn-overrun-{field}",
                        (),
                        _usage(**usage_values),
                    ),
                    (),
                ),
            )
            with self.subTest(field=field), self.assertRaises(NativeStateError):
                reduce_native_entries(_chain(records))

    def test_turn_commit_usage_must_not_exceed_current_remaining_budget(self) -> None:
        synced_budget = _budget(controller_tokens=10, aggregate_tokens=10, cost_micros=10)
        reduced_budget = _budget(controller_tokens=2, aggregate_tokens=2, cost_micros=2)
        request = NativeTurnRequest(
            turn_id="turn-current-budget",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=synced_budget,
        )
        records = (
            _session_bound(),
            authority_synced_record(AUTHORITY_REVISION, synced_budget),
            command_committed_record(
                _session_create_command(),
                (_session_created(), _session_running()),
            ),
            turn_started_record(request),
            authority_synced_record(2, reduced_budget),
            turn_committed_record(
                NativeTurnResult(
                    "turn-current-budget",
                    (),
                    _usage(controller_tokens=3, aggregate_tokens=3, cost_micros=3),
                ),
                (),
            ),
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain(records))

    def test_multi_turn_usage_consumes_remaining_budget_before_next_commit(self) -> None:
        first_request = NativeTurnRequest(
            turn_id="turn-sixty-a",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        second_request = NativeTurnRequest(
            turn_id="turn-sixty-b",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        records = (
            *_valid_records(),
            turn_started_record(first_request),
            turn_committed_record(
                NativeTurnResult(
                    "turn-sixty-a",
                    (),
                    _usage(controller_tokens=60, aggregate_tokens=60),
                ),
                (),
            ),
            turn_started_record(second_request),
            turn_committed_record(
                NativeTurnResult(
                    "turn-sixty-b",
                    (),
                    _usage(controller_tokens=60, aggregate_tokens=60),
                ),
                (),
            ),
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain(records))

    def test_exact_budget_exhaustion_updates_remaining_budget_to_zero(self) -> None:
        request = NativeTurnRequest(
            turn_id="turn-exhaust",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )

        state = reduce_native_entries(
            _chain(
                (
                    *_valid_records(),
                    turn_started_record(request),
                    turn_committed_record(
                        NativeTurnResult(
                            "turn-exhaust",
                            (),
                            _usage(
                                controller_tokens=100,
                                aggregate_tokens=100,
                                cost_micros=10_000,
                            ),
                        ),
                        (),
                    ),
                )
            )
        )

        self.assertEqual(
            state.remaining_budget,
            _budget(controller_tokens=0, aggregate_tokens=0, cost_micros=0),
        )
        self.assertEqual(state.usage.controller_tokens, 100)
        self.assertEqual(state.usage.aggregate_tokens, 100)

    def test_pending_non_invoked_turn_commit_accepts_only_budget_limited_shape(
        self,
    ) -> None:
        input_command = _input_command()
        request = _turn_request(input_command=input_command)
        budget_limited = _event(
            "event-budget-limited",
            4,
            "session.budget-limited",
            {"reason_code": "native-budget-limited"},
        )
        records = (
            *_valid_records(),
            command_committed_record(input_command, ()),
            turn_started_record(request),
            turn_committed_record(
                NativeTurnResult("turn-1", (), _usage()),
                (
                    _budget_report("event-budget-before-limit", 3, _usage()),
                    budget_limited,
                ),
                adapter_invoked=False,
            ),
        )

        state = reduce_native_entries(_chain(records))

        self.assertEqual(state.lifecycle, "budget_limited")
        self.assertEqual(state.pending_turn, None)
        self.assertEqual(state.pending_inputs, ())
        self.assertEqual(state.remaining_budget, _budget())
        self.assertFalse(
            records[-1].payload["adapter_invoked"],
        )

    def test_pending_non_invoked_turn_commit_rejects_non_budget_limited_shapes(
        self,
    ) -> None:
        input_command = _input_command()
        request = _turn_request(input_command=input_command)
        valid_budget = _budget_report("event-budget-before-limit", 3, _usage())
        terminal = _event(
            "event-budget-limited",
            4,
            "session.budget-limited",
            {"reason_code": "native-budget-limited"},
        )
        cases = (
            (
                "nonzero-usage",
                NativeTurnResult(
                    "turn-1",
                    (),
                    _usage(controller_tokens=1, aggregate_tokens=1),
                ),
                (valid_budget, terminal),
            ),
            (
                "normal-result",
                NativeTurnResult(
                    "turn-1",
                    (NativeEventDraft("session.completed", {"reason_code": "done"}),),
                    _usage(),
                ),
                (_event("event-completed", 3, "session.completed", {"reason_code": "done"}),),
            ),
            (
                "budget-only",
                NativeTurnResult("turn-1", (), _usage()),
                (valid_budget,),
            ),
            (
                "wrong-terminal",
                NativeTurnResult("turn-1", (), _usage()),
                (
                    valid_budget,
                    _event(
                        "event-cancelled",
                        4,
                        "session.cancelled",
                        {"reason_code": "cancelled"},
                    ),
                ),
            ),
            (
                "absent-pending-turn",
                NativeTurnResult("turn-1", (), _usage()),
                (valid_budget, terminal),
            ),
        )
        for label, result, events in cases:
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                prefix = (
                    (*_valid_records(), command_committed_record(input_command, ()))
                    if label == "absent-pending-turn"
                    else (
                        *_valid_records(),
                        command_committed_record(input_command, ()),
                        turn_started_record(request),
                    )
                )
                reduce_native_entries(
                    _chain(
                        (
                            *prefix,
                            turn_committed_record(
                                result,
                                events,
                                adapter_invoked=False,
                            ),
                        )
                    )
                )

    def test_nonzero_turn_after_zero_budget_rejects_before_state_update(self) -> None:
        exhausted_prefix = (
            *_valid_records(),
            turn_started_record(
                NativeTurnRequest(
                    turn_id="turn-exhaust",
                    session_id=SESSION_ID,
                    generation=GENERATION,
                    authority_revision=AUTHORITY_REVISION,
                    causal_command_ids=(),
                    inputs=(),
                    action_results=(),
                    budget=_budget(),
                )
            ),
            turn_committed_record(
                NativeTurnResult(
                    "turn-exhaust",
                    (),
                    _usage(
                        controller_tokens=100,
                        aggregate_tokens=100,
                        cost_micros=10_000,
                    ),
                ),
                (),
            ),
        )
        full = (
            *exhausted_prefix,
            turn_started_record(
                NativeTurnRequest(
                    turn_id="turn-after-zero",
                    session_id=SESSION_ID,
                    generation=GENERATION,
                    authority_revision=AUTHORITY_REVISION,
                    causal_command_ids=(),
                    inputs=(),
                    action_results=(),
                    budget=_budget(),
                )
            ),
            turn_committed_record(
                NativeTurnResult(
                    "turn-after-zero",
                    (),
                    _usage(controller_tokens=1, aggregate_tokens=1),
                ),
                (),
            ),
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain(full))

        prefix_state = reduce_native_entries(_chain(exhausted_prefix))
        self.assertEqual(prefix_state.usage.controller_tokens, 100)
        self.assertEqual(
            prefix_state.remaining_budget,
            _budget(controller_tokens=0, aggregate_tokens=0, cost_micros=0),
        )

    def test_next_turn_request_must_carry_updated_remaining_budget(self) -> None:
        stale_second_request = NativeTurnRequest(
            turn_id="turn-stale-budget",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        records = (
            *_valid_records(),
            turn_started_record(
                NativeTurnRequest(
                    turn_id="turn-sixty",
                    session_id=SESSION_ID,
                    generation=GENERATION,
                    authority_revision=AUTHORITY_REVISION,
                    causal_command_ids=(),
                    inputs=(),
                    action_results=(),
                    budget=_budget(),
                )
            ),
            turn_committed_record(
                NativeTurnResult(
                    "turn-sixty",
                    (),
                    _usage(controller_tokens=60, aggregate_tokens=60),
                ),
                (),
            ),
            turn_started_record(stale_second_request),
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain(records))

    def test_authority_resync_replaces_capacity_without_resetting_cumulative_usage(
        self,
    ) -> None:
        first_usage = _usage(controller_tokens=60, aggregate_tokens=60, cost_micros=1)
        second_usage = _usage(controller_tokens=50, aggregate_tokens=50, cost_micros=2)
        records = (
            *_valid_records(),
            turn_started_record(
                NativeTurnRequest(
                    turn_id="turn-before-resync",
                    session_id=SESSION_ID,
                    generation=GENERATION,
                    authority_revision=AUTHORITY_REVISION,
                    causal_command_ids=(),
                    inputs=(),
                    action_results=(),
                    budget=_budget(),
                )
            ),
            turn_committed_record(
                NativeTurnResult(
                    "turn-before-resync",
                    (
                        NativeEventDraft(
                            "budget.reported",
                            {
                                "controller_tokens": 60,
                                "application_tokens": 0,
                                "child_tokens": 0,
                                "aggregate_tokens": 60,
                                "cost_micros": 1,
                            },
                        ),
                    ),
                    first_usage,
                ),
                (_budget_report("event-budget-before-resync", 3, first_usage),),
            ),
            authority_synced_record(2, _budget()),
            turn_started_record(
                NativeTurnRequest(
                    turn_id="turn-after-resync",
                    session_id=SESSION_ID,
                    generation=GENERATION,
                    authority_revision=2,
                    causal_command_ids=(),
                    inputs=(),
                    action_results=(),
                    budget=_budget(),
                )
            ),
            turn_committed_record(
                NativeTurnResult(
                    "turn-after-resync",
                    (
                        NativeEventDraft(
                            "budget.reported",
                            {
                                "controller_tokens": 110,
                                "application_tokens": 0,
                                "child_tokens": 0,
                                "aggregate_tokens": 110,
                                "cost_micros": 3,
                            },
                        ),
                    ),
                    second_usage,
                ),
                (
                    _budget_report(
                        "event-budget-after-resync",
                        4,
                        _usage(
                            controller_tokens=110,
                            aggregate_tokens=110,
                            cost_micros=3,
                        ),
                    ),
                ),
            ),
        )

        state = reduce_native_entries(_chain(records))

        self.assertEqual(state.usage.controller_tokens, 110)
        self.assertEqual(state.usage.cost_micros, 3)
        self.assertEqual(
            state.remaining_budget,
            _budget(controller_tokens=50, aggregate_tokens=50, cost_micros=9_998),
        )

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
                                adapter_invoked=False,
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

    def test_reducer_rejects_orphan_and_non_invoked_pending_turn_commits(self) -> None:
        request = NativeTurnRequest(
            turn_id="turn-pending",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        pending_commit = turn_committed_record(
            NativeTurnResult("turn-pending", (), _usage()),
            (),
            adapter_invoked=False,
        )
        orphan_commit = turn_committed_record(
            NativeTurnResult("turn-orphan", (), _usage()),
            (),
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain((*_valid_records(), orphan_commit)))
        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain((*_valid_records(), turn_started_record(request), pending_commit))
            )

    def test_reducer_rejects_every_non_invoked_turn_commit_without_pending_turn(
        self,
    ) -> None:
        cases = (
            (
                "empty",
                NativeTurnResult("turn-empty", (), _usage()),
                (),
            ),
            (
                "budget",
                NativeTurnResult(
                    "turn-budget",
                    (
                        NativeEventDraft(
                            "budget.reported",
                            {
                                "controller_tokens": 0,
                                "application_tokens": 0,
                                "child_tokens": 0,
                                "aggregate_tokens": 0,
                                "cost_micros": 0,
                            },
                        ),
                    ),
                    _usage(),
                ),
                (_budget_report("event-budget-orphan", 3, _usage()),),
            ),
            (
                "terminal",
                NativeTurnResult(
                    "turn-terminal",
                    (NativeEventDraft("session.completed", {"reason_code": "done"}),),
                    _usage(),
                ),
                (_event("event-terminal-orphan", 3, "session.completed", {"reason_code": "done"}),),
            ),
        )
        for label, result, events in cases:
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(
                    _chain(
                        (
                            *_valid_records(),
                            turn_committed_record(
                                result,
                                events,
                                adapter_invoked=False,
                            ),
                        )
                    )
                )

    def test_reducer_rejects_start_or_commit_after_turn_is_fenced(self) -> None:
        request = NativeTurnRequest(
            turn_id="turn-fenced",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        recovery = turn_recovery_required_record(
            "turn-fenced",
            "adapter-failed",
            (),
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain((*_valid_records(), recovery, turn_started_record(request)))
            )
        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain(
                    (
                        *_valid_records(),
                        recovery,
                        turn_committed_record(
                            NativeTurnResult("turn-fenced", (), _usage()),
                            (),
                            adapter_invoked=False,
                        ),
                    )
                )
            )

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

    def test_reducer_rejects_duplicate_event_ids_before_append(self) -> None:
        duplicate = _budget_report("event-running-2", 3, _usage())

        with self.assertRaises(NativeStateError):
            reduce_native_entries(
                _chain(
                    (
                        *_valid_records(),
                        turn_committed_record(
                            NativeTurnResult(
                                "turn-duplicate-event",
                                (
                                    NativeEventDraft(
                                        "budget.reported",
                                        {
                                            "controller_tokens": 0,
                                            "application_tokens": 0,
                                            "child_tokens": 0,
                                            "aggregate_tokens": 0,
                                            "cost_micros": 0,
                                        },
                                    ),
                                ),
                                _usage(),
                            ),
                            (duplicate,),
                            adapter_invoked=False,
                        ),
                    )
                )
            )

    def test_native_model_rejects_non_canonical_json_numbers(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf"), 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                NativeRecord("record-1", "authority.synced", {"revision": value})

    def test_native_usage_and_budget_reject_js_unsafe_values(self) -> None:
        unsafe = 2**53

        with self.assertRaises(ValueError):
            NativeTurnResult(
                "turn-unsafe",
                (),
                _usage(controller_tokens=unsafe, aggregate_tokens=unsafe),
            )
        with self.assertRaises(ValueError):
            NativeTurnRequest(
                turn_id="turn-unsafe",
                session_id=SESSION_ID,
                generation=GENERATION,
                authority_revision=AUTHORITY_REVISION,
                causal_command_ids=(),
                inputs=(),
                action_results=(),
                budget=_budget(controller_tokens=unsafe, aggregate_tokens=unsafe),
            )
        with self.assertRaises(NativeStateError):
            authority_synced_record(
                AUTHORITY_REVISION,
                _budget(controller_tokens=unsafe, aggregate_tokens=unsafe),
            )

    def test_reducer_rejects_js_unsafe_cumulative_usage(self) -> None:
        maximum = 2**53 - 1
        entries = _chain(
            (
                *_valid_records(),
                turn_committed_record(
                    NativeTurnResult(
                        "turn-max-minus-one",
                        (),
                        _usage(
                            controller_tokens=maximum - 1,
                            aggregate_tokens=maximum - 1,
                        ),
                    ),
                    (),
                    adapter_invoked=False,
                ),
                turn_committed_record(
                    NativeTurnResult(
                        "turn-overflow",
                        (),
                        _usage(controller_tokens=2, aggregate_tokens=2),
                    ),
                    (),
                    adapter_invoked=False,
                ),
            )
        )

        with self.assertRaises(NativeStateError):
            reduce_native_entries(entries)

    def test_record_ids_are_bounded_for_max_length_public_ids(self) -> None:
        action_command_id = "b" * 128
        command = _command(
            MAX_PROTOCOL_ID,
            "input.submit",
            {
                "input_id": MAX_PROTOCOL_ID,
                "delivery": "direct",
                "content_ref": MAX_PROTOCOL_ID,
            },
            session_id=MAX_PROTOCOL_ID,
        )
        action_command = _command(
            action_command_id,
            "action.resolve",
            {
                "action_id": MAX_PROTOCOL_ID,
                "resolution": "succeeded",
                "reason_code": "ok",
                "receipt_ref": MAX_PROTOCOL_ID,
            },
            session_id=MAX_PROTOCOL_ID,
        )
        request = NativeTurnRequest(
            turn_id=MAX_PROTOCOL_ID,
            session_id=MAX_PROTOCOL_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(MAX_PROTOCOL_ID, action_command_id),
            inputs=(
                NativeInputReference(
                    input_id=MAX_PROTOCOL_ID,
                    delivery="direct",
                    content_ref=MAX_PROTOCOL_ID,
                    command_digest=_command_digest(command),
                ),
            ),
            action_results=(
                NativeActionResultReference(
                    action_id=MAX_PROTOCOL_ID,
                    resolution="succeeded",
                    reason_code="ok",
                    receipt_ref=MAX_PROTOCOL_ID,
                    command_digest=_command_digest(action_command),
                ),
            ),
            budget=_budget(),
        )
        records = (
            session_bound_record(
                provider_id="native",
                provider_version="0.1.0",
                system_id="research.system",
                system_version="1.0.0",
                session_id=MAX_PROTOCOL_ID,
                generation=GENERATION,
                checkpoint_version="1.0.0",
                authority_id=MAX_PROTOCOL_ID,
                authority_revision=AUTHORITY_REVISION,
                initial_create_command=_command(
                    "command-create",
                    "session.create",
                    {
                        "system_id": "research.system",
                        "system_version": "1.0.0",
                        "goal_id": MAX_PROTOCOL_ID,
                        "goal_ref": MAX_PROTOCOL_ID,
                    },
                    session_id=MAX_PROTOCOL_ID,
                ),
            ),
            authority_synced_record(AUTHORITY_REVISION, _budget()),
            command_committed_record(
                _command(
                    "command-create",
                    "session.create",
                    {
                        "system_id": "research.system",
                        "system_version": "1.0.0",
                        "goal_id": MAX_PROTOCOL_ID,
                        "goal_ref": MAX_PROTOCOL_ID,
                    },
                    session_id=MAX_PROTOCOL_ID,
                ),
                (
                    _event(
                        "event-created",
                        1,
                        "session.created",
                        {
                            "goal_id": MAX_PROTOCOL_ID,
                            "authority_id": MAX_PROTOCOL_ID,
                            "authority_revision": AUTHORITY_REVISION,
                        },
                        session_id=MAX_PROTOCOL_ID,
                    ),
                    _event(
                        "event-running-2",
                        2,
                        "session.running",
                        {"reason_code": "started"},
                        session_id=MAX_PROTOCOL_ID,
                    ),
                ),
            ),
            command_committed_record(command, ()),
            command_committed_record(action_command, ()),
            turn_started_record(request),
            turn_committed_record(
                NativeTurnResult(MAX_PROTOCOL_ID, (), _usage()),
                (),
            ),
        )

        for record in records:
            with self.subTest(kind=record.kind):
                self.assertLessEqual(len(record.record_id), 128)
                self.assertRegex(record.record_id, r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

        state = reduce_native_entries(_chain(records))

        self.assertEqual(state.session_id, MAX_PROTOCOL_ID)
        self.assertEqual(tuple(ref.input_id for ref in state.pending_inputs), ())

    def test_record_id_derivation_changes_when_identity_payload_drifts(self) -> None:
        command = _input_command()
        first = command_committed_record(command, ())
        changed_payload = dict(command.payload)
        changed_payload["content_ref"] = "input-ref-2"
        changed = command_committed_record(replace(command, payload=changed_payload), ())
        tampered = NativeRecord(first.record_id, changed.kind, changed.payload)

        self.assertNotEqual(first.record_id, changed.record_id)
        with self.assertRaises(NativeStateError):
            reduce_native_entries(_chain((*_valid_records(), tampered)))

    def test_checkpoint_metadata_must_match_event_and_covered_state(self) -> None:
        base = _valid_records()
        metadata = NativeCapsuleMetadata(
            capsule_id="capsule-1",
            capsule_digest="b" * 64,
            control_plane_id="native",
            control_plane_version="0.1.0",
            checkpoint_version="1.0.0",
            covered_position=len(base),
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
