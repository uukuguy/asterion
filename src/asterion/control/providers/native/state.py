"""Pure reduction for the native controller journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.protocol import (
    TERMINAL_CONTROL_EVENT_TYPES,
    validate_control_command,
    validate_control_event,
)
from asterion.control.providers.native.model import (
    NativeActionResultReference,
    NativeCapsuleMetadata,
    NativeControllerState,
    NativeEntry,
    NativeEventDraft,
    NativeInputReference,
    MAX_SAFE_JSON_INTEGER,
    NativeRecord,
    NativeTurnRequest,
    NativeTurnResult,
    _json_value,
)


MAX_USAGE_VALUE = MAX_SAFE_JSON_INTEGER


class NativeStateError(ValueError):
    """Raised when the native journal violates deterministic controller state."""


def session_bound_record(
    provider_id: str,
    provider_version: str,
    system_id: str,
    system_version: str,
    session_id: str,
    generation: int,
    checkpoint_version: str,
    authority_id: str,
    authority_revision: int,
) -> NativeRecord:
    payload = {
        "provider_id": provider_id,
        "provider_version": provider_version,
        "system_id": system_id,
        "system_version": system_version,
        "session_id": session_id,
        "generation": generation,
        "checkpoint_version": checkpoint_version,
        "authority_id": authority_id,
        "authority_revision": authority_revision,
    }
    record = NativeRecord(f"session-bound:{session_id}:{generation}", "session.bound", payload)
    _validate_record(record)
    return record


def authority_synced_record(
    authority_revision: int, budget: RemainingBudget
) -> NativeRecord:
    budget_payload = _remaining_budget_mapping(budget)
    budget_digest = _digest(budget_payload)
    payload = {
        "authority_revision": authority_revision,
        "budget": budget_payload,
    }
    record = NativeRecord(
        f"authority-synced:{authority_revision}:{budget_digest}",
        "authority.synced",
        payload,
    )
    _validate_record(record)
    return record


def command_committed_record(
    command: ControlCommand, events: Iterable[ControlEvent]
) -> NativeRecord:
    command_payload = command.to_mapping()
    payload = {
        "command_digest": _digest(command_payload),
        "command": command_payload,
        "events": tuple(event.to_mapping() for event in events),
    }
    record = NativeRecord(
        f"command:{command.command_id}",
        "command.committed",
        payload,
    )
    _validate_record(record)
    return record


def turn_started_record(request: NativeTurnRequest) -> NativeRecord:
    payload = {"request": _turn_request_mapping(request)}
    record = NativeRecord(f"turn-started:{request.turn_id}", "turn.started", payload)
    _validate_record(record)
    return record


def turn_committed_record(
    result: NativeTurnResult,
    events: Iterable[ControlEvent],
    *,
    adapter_invoked: bool = True,
) -> NativeRecord:
    event_mappings = tuple(event.to_mapping() for event in events)
    _validate_turn_usage(result.usage)
    _validate_event_drafts(result.events, event_mappings)
    payload = {
        "turn_id": result.turn_id,
        "events": event_mappings,
        "usage": _usage_mapping(result.usage),
        "adapter_invoked": adapter_invoked,
    }
    record = NativeRecord(f"turn-committed:{result.turn_id}", "turn.committed", payload)
    _validate_record(record)
    return record


def turn_recovery_required_record(
    turn_id: str, reason_code: str, events: Iterable[ControlEvent]
) -> NativeRecord:
    payload = {
        "turn_id": turn_id,
        "reason_code": reason_code,
        "events": tuple(event.to_mapping() for event in events),
    }
    record = NativeRecord(
        f"turn-recovery-required:{turn_id}",
        "turn.recovery-required",
        payload,
    )
    _validate_record(record)
    return record


def checkpoint_committed_record(
    metadata: NativeCapsuleMetadata, event: ControlEvent
) -> NativeRecord:
    payload = {
        "metadata": _metadata_mapping(metadata),
        "event": event.to_mapping(),
    }
    record = NativeRecord(
        f"checkpoint:{metadata.capsule_id}:{metadata.covered_position}",
        "checkpoint.committed",
        payload,
    )
    _validate_record(record)
    return record


def reduce_native_entries(entries: Iterable[NativeEntry]) -> NativeControllerState:
    """Reduce a contiguous native journal prefix into immutable controller state."""

    if isinstance(entries, (str, bytes, bytearray)) or not isinstance(
        entries, Iterable
    ):
        raise NativeStateError("native entries are invalid")
    state = NativeControllerState.empty()
    previous_digest: str | None = None
    seen_records: dict[str, str] = {}
    for expected_position, entry in enumerate(tuple(entries), start=1):
        if not isinstance(entry, NativeEntry):
            raise NativeStateError("native entry is invalid")
        if entry.position != expected_position:
            raise NativeStateError("native journal position is not contiguous")
        if entry.previous_digest != previous_digest:
            raise NativeStateError("native journal predecessor digest mismatches")
        record_digest = entry.record.digest
        existing_digest = seen_records.get(entry.record.record_id)
        if existing_digest is not None:
            if existing_digest != record_digest:
                raise NativeStateError("native record identity conflicts")
            previous_digest = entry.digest
            continue
        _validate_record(entry.record)
        state = _apply_record(state, entry)
        seen_records[entry.record.record_id] = record_digest
        previous_digest = entry.digest
    return state


def _apply_record(
    state: NativeControllerState, entry: NativeEntry
) -> NativeControllerState:
    record = entry.record
    if record.kind == "session.bound":
        return _apply_session_bound(state, record)
    if record.kind == "authority.synced":
        return _apply_authority_synced(state, record)
    if record.kind == "command.committed":
        return _apply_command_committed(state, record)
    if record.kind == "turn.started":
        return _apply_turn_started(state, record)
    if record.kind == "turn.committed":
        return _apply_turn_committed(state, record)
    if record.kind == "turn.recovery-required":
        return _apply_turn_recovery_required(state, record)
    if record.kind == "checkpoint.committed":
        return _apply_checkpoint_committed(state, entry)
    raise NativeStateError("native record kind is invalid")


def _apply_session_bound(
    state: NativeControllerState, record: NativeRecord
) -> NativeControllerState:
    if state.lifecycle != "empty":
        raise NativeStateError("native session is already bound")
    payload = record.payload
    return replace(
        state,
        provider_id=str(payload["provider_id"]),
        provider_version=str(payload["provider_version"]),
        checkpoint_version=str(payload["checkpoint_version"]),
        system_id=str(payload["system_id"]),
        system_version=str(payload["system_version"]),
        session_id=str(payload["session_id"]),
        generation=_int(payload["generation"]),
        lifecycle="bound",
        authority_id=str(payload["authority_id"]),
        authority_revision=_int(payload["authority_revision"]),
    )


def _apply_authority_synced(
    state: NativeControllerState, record: NativeRecord
) -> NativeControllerState:
    _require_bound(state)
    revision = _int(record.payload["authority_revision"])
    if state.authority_revision is not None and revision < state.authority_revision:
        raise NativeStateError("native authority revision regressed")
    return replace(
        state,
        authority_revision=revision,
        budget_authority_revision=revision,
        remaining_budget=_remaining_budget_from_mapping(record.payload["budget"]),
    )


def _apply_command_committed(
    state: NativeControllerState, record: NativeRecord
) -> NativeControllerState:
    _require_bound(state)
    command = ControlCommand.from_mapping(_mapping(record.payload["command"]))
    command_digest = str(record.payload["command_digest"])
    if command_digest != _digest(command.to_mapping()):
        raise NativeStateError("native command digest mismatches")
    if command.session_id != state.session_id:
        raise NativeStateError("native command session mismatches")
    if (
        state.authority_revision is not None
        and command.authority_revision != state.authority_revision
    ):
        raise NativeStateError("native command authority mismatches")

    command_digests = dict(state.command_digests)
    previous = command_digests.get(command.command_id)
    if previous is not None and previous != command_digest:
        raise NativeStateError("native command identity conflicts")
    command_digests[command.command_id] = command_digest

    pending_inputs = state.pending_inputs
    pending_action_results = state.pending_action_results
    action_statuses = dict(state.action_statuses)
    action_receipts = dict(state.action_receipt_refs)
    if previous is None and command.type == "input.submit":
        pending_inputs = (*pending_inputs, _input_reference(command, command_digest))
    if previous is None and command.type == "action.resolve":
        result = _action_result_reference(command, command_digest)
        pending_action_results = (*pending_action_results, result)
        action_statuses[result.action_id] = result.resolution
        action_receipts[result.action_id] = result.receipt_ref

    state = replace(
        state,
        command_digests=command_digests,
        pending_inputs=pending_inputs,
        pending_action_results=pending_action_results,
        action_statuses=action_statuses,
        action_receipt_refs=action_receipts,
    )
    return _apply_events(state, _events_from_payload(record.payload["events"]))


def _apply_turn_started(
    state: NativeControllerState, record: NativeRecord
) -> NativeControllerState:
    _require_active(state)
    if state.pending_turn is not None:
        raise NativeStateError("native turn is already pending")
    request = _turn_request_from_mapping(record.payload["request"])
    if (
        request.turn_id in state.fenced_turn_ids
        or request.turn_id in state.committed_turn_digests
    ):
        raise NativeStateError("native turn cannot start after fence or commit")
    _validate_turn_request(state, request)
    return replace(state, pending_turn=request)


def _apply_turn_committed(
    state: NativeControllerState, record: NativeRecord
) -> NativeControllerState:
    _require_active(state)
    turn_id = str(record.payload["turn_id"])
    if turn_id in state.fenced_turn_ids:
        raise NativeStateError("native fenced turn cannot commit")
    usage = _usage_from_mapping(record.payload["usage"])
    _validate_turn_usage(usage)
    committed_turns = dict(state.committed_turn_digests)
    previous = committed_turns.get(turn_id)
    if previous is not None and previous != record.digest:
        raise NativeStateError("native turn identity conflicts")
    adapter_invoked = bool(record.payload["adapter_invoked"])
    if state.pending_turn is None and adapter_invoked:
        raise NativeStateError("native adapter turn commit requires pending turn")
    if state.pending_turn is not None and not adapter_invoked:
        raise NativeStateError("native pending turn commit requires adapter invocation")
    if state.pending_turn is not None and state.pending_turn.turn_id != turn_id:
        raise NativeStateError("native pending turn identity mismatches")

    next_state = replace(state, usage=_add_usage(state.usage, usage))
    next_state = _apply_events(
        next_state, _events_from_payload(record.payload["events"])
    )
    committed_turns[turn_id] = record.digest
    pending_inputs = next_state.pending_inputs
    pending_action_results = next_state.pending_action_results
    if state.pending_turn is not None:
        used_input_digests = {item.command_digest for item in state.pending_turn.inputs}
        used_action_digests = {
            item.command_digest for item in state.pending_turn.action_results
        }
        pending_inputs = tuple(
            item
            for item in next_state.pending_inputs
            if item.command_digest not in used_input_digests
        )
        pending_action_results = tuple(
            item
            for item in next_state.pending_action_results
            if item.command_digest not in used_action_digests
        )
    return replace(
        next_state,
        pending_inputs=pending_inputs,
        pending_action_results=pending_action_results,
        pending_turn=None,
        committed_turn_digests=committed_turns,
    )


def _apply_turn_recovery_required(
    state: NativeControllerState, record: NativeRecord
) -> NativeControllerState:
    _require_active(state)
    turn_id = str(record.payload["turn_id"])
    if turn_id in state.fenced_turn_ids or turn_id in state.committed_turn_digests:
        raise NativeStateError("native turn cannot recover after fence or commit")
    if state.pending_turn is not None and state.pending_turn.turn_id != turn_id:
        raise NativeStateError("native recovery turn identity mismatches")
    state = _apply_events(state, _events_from_payload(record.payload["events"]))
    recovery = _append_unique(state.recovery_required_turn_ids, turn_id)
    fenced = _append_unique(state.fenced_turn_ids, turn_id)
    return replace(
        state,
        pending_turn=None,
        recovery_required_turn_ids=recovery,
        fenced_turn_ids=fenced,
    )


def _apply_checkpoint_committed(
    state: NativeControllerState, entry: NativeEntry
) -> NativeControllerState:
    _require_active(state)
    metadata = _metadata_from_mapping(entry.record.payload["metadata"])
    event = ControlEvent.from_mapping(_mapping(entry.record.payload["event"]))
    if metadata.covered_position != entry.position - 1:
        raise NativeStateError("native checkpoint covered position mismatches")
    if metadata.covered_sequence != state.next_sequence - 1:
        raise NativeStateError("native checkpoint covered sequence mismatches")
    if metadata.control_plane_id != state.provider_id:
        raise NativeStateError("native checkpoint control plane mismatches")
    if metadata.control_plane_version != state.provider_version:
        raise NativeStateError("native checkpoint control plane version mismatches")
    if metadata.checkpoint_version != state.checkpoint_version:
        raise NativeStateError("native checkpoint version mismatches")
    payload = event.payload
    if (
        event.type != "checkpoint.created"
        or payload["capsule_id"] != metadata.capsule_id
        or payload["capsule_digest"] != metadata.capsule_digest
        or payload["control_plane_id"] != metadata.control_plane_id
        or payload["control_plane_version"] != metadata.control_plane_version
        or payload["checkpoint_version"] != metadata.checkpoint_version
        or payload["covered_sequence"] != metadata.covered_sequence
        or payload["storage_ref"] != metadata.storage_ref
    ):
        raise NativeStateError("native checkpoint event mismatches metadata")
    return replace(_apply_event(state, event), checkpoint=metadata)


def _apply_events(
    state: NativeControllerState, events: Sequence[ControlEvent]
) -> NativeControllerState:
    result = state
    for event in events:
        result = _apply_event(result, event)
    return result


def _apply_event(
    state: NativeControllerState, event: ControlEvent
) -> NativeControllerState:
    if state.session_id is None or state.generation is None:
        raise NativeStateError("native session is not bound")
    if (
        event.session_id != state.session_id
        or event.generation != state.generation
        or event.sequence != state.next_sequence
    ):
        raise NativeStateError("native event identity or sequence mismatches")
    if state.terminal_event_id is not None:
        raise NativeStateError("native session already has a terminal event")
    if any(existing.event_id == event.event_id for existing in state.events):
        raise NativeStateError("native event identity conflicts")

    lifecycle = state.lifecycle
    goal_id = state.goal_id
    goal_status = state.goal_status
    authority_id = state.authority_id
    authority_revision = state.authority_revision
    terminal_event_id = state.terminal_event_id
    action_statuses = dict(state.action_statuses)
    action_receipts = dict(state.action_receipt_refs)

    if event.type == "session.created":
        if lifecycle != "bound":
            raise NativeStateError("native session.created transition is invalid")
        goal_id = str(event.payload["goal_id"])
        goal_status = "active"
        authority_id = str(event.payload["authority_id"])
        authority_revision = _int(event.payload["authority_revision"])
        lifecycle = "created"
    elif event.type == "session.running":
        if lifecycle not in {"created", "paused", "recovery_required"}:
            raise NativeStateError("native session.running transition is invalid")
        lifecycle = "running"
    elif event.type == "session.paused":
        if lifecycle not in {"running", "recovery_required"}:
            raise NativeStateError("native session.paused transition is invalid")
        lifecycle = "paused"
        if goal_status == "active":
            goal_status = "paused"
    elif event.type == "session.recovery-required":
        if lifecycle not in {"running", "paused"}:
            raise NativeStateError(
                "native session.recovery-required transition is invalid"
            )
        lifecycle = "recovery_required"
    elif event.type in TERMINAL_CONTROL_EVENT_TYPES:
        if lifecycle not in {"created", "running", "paused", "recovery_required"}:
            raise NativeStateError("native terminal transition is invalid")
        lifecycle = event.type.removeprefix("session.").replace("-", "_")
        terminal_event_id = event.event_id
        goal_status = {
            "session.budget-limited": "budget_limited",
            "session.cancelled": "cancelled",
            "session.completed": "completed",
            "session.failed": "failed",
        }[event.type]
    elif event.type == "goal.updated":
        if goal_id is not None and event.payload["goal_id"] != goal_id:
            raise NativeStateError("native goal identity mismatches")
        goal_id = str(event.payload["goal_id"])
        goal_status = str(event.payload["status"])
    elif event.type == "action.proposed":
        if lifecycle != "running":
            raise NativeStateError("native action proposal requires running session")
        action_id = str(event.payload["action_id"])
        action_statuses[action_id] = "proposed"
        action_receipts[action_id] = None
    elif event.type == "budget.reported":
        if _usage_from_mapping(event.payload) != state.usage:
            raise NativeStateError("native budget report is not cumulative")
    elif event.type == "checkpoint.created":
        if lifecycle not in {"running", "paused"}:
            raise NativeStateError("native checkpoint requires active session")
    elif event.type == "fault.raised":
        if lifecycle not in {"running", "paused", "recovery_required"}:
            raise NativeStateError("native fault requires active session")
    else:
        raise NativeStateError("native event type is invalid")

    return replace(
        state,
        lifecycle=lifecycle,
        goal_id=goal_id,
        goal_status=goal_status,
        authority_id=authority_id,
        authority_revision=authority_revision,
        action_statuses=action_statuses,
        action_receipt_refs=action_receipts,
        events=(*state.events, event),
        next_sequence=state.next_sequence + 1,
        terminal_event_id=terminal_event_id,
    )


def _validate_turn_request(
    state: NativeControllerState, request: NativeTurnRequest
) -> None:
    if (
        request.session_id != state.session_id
        or request.generation != state.generation
        or request.authority_revision != state.authority_revision
    ):
        raise NativeStateError("native turn request identity mismatches")
    if any(command_id not in state.command_digests for command_id in request.causal_command_ids):
        raise NativeStateError("native turn references unknown command")
    pending_input_digests = {item.command_digest: item for item in state.pending_inputs}
    pending_action_digests = {
        item.command_digest: item for item in state.pending_action_results
    }
    for item in request.inputs:
        if pending_input_digests.get(item.command_digest) != item:
            raise NativeStateError("native turn input reference mismatches")
    for item in request.action_results:
        if pending_action_digests.get(item.command_digest) != item:
            raise NativeStateError("native turn action result reference mismatches")
    selected = {state.command_digests[item] for item in request.causal_command_ids}
    referenced = {item.command_digest for item in request.inputs} | {
        item.command_digest for item in request.action_results
    }
    if not referenced.issubset(selected):
        raise NativeStateError("native turn causality mismatches references")


def _validate_record(record: NativeRecord) -> None:
    try:
        if record.kind == "session.bound":
            _require_fields(
                record.payload,
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
            validate_control_event(
                {
                    "protocol": "asterion.agent-control/v1",
                    "event_id": "session-bound-validation",
                    "session_id": record.payload["session_id"],
                    "generation": record.payload["generation"],
                    "sequence": 1,
                    "emitted_at": "2026-08-30T00:00:00Z",
                    "type": "session.created",
                    "payload": {
                        "goal_id": "goal-validation",
                        "authority_id": record.payload["authority_id"],
                        "authority_revision": record.payload["authority_revision"],
                    },
                }
            )
            _require_semver(record.payload["provider_version"])
            _require_semver(record.payload["system_version"])
            _require_semver(record.payload["checkpoint_version"])
            _require_identifier(record.payload["provider_id"])
            _require_identifier(record.payload["system_id"])
            _require_record_id(
                record,
                f"session-bound:{record.payload['session_id']}:{record.payload['generation']}",
            )
        elif record.kind == "authority.synced":
            _require_fields(record.payload, {"authority_revision", "budget"})
            _require_positive_int(record.payload["authority_revision"])
            budget = _remaining_budget_from_mapping(record.payload["budget"])
            _require_record_id(
                record,
                "authority-synced:"
                f"{record.payload['authority_revision']}:{_digest(_remaining_budget_mapping(budget))}",
            )
        elif record.kind == "command.committed":
            _require_fields(record.payload, {"command_digest", "command", "events"})
            _require_digest(record.payload["command_digest"])
            command = ControlCommand.from_mapping(_mapping(record.payload["command"]))
            if record.payload["command_digest"] != _digest(command.to_mapping()):
                raise NativeStateError("native command digest mismatches")
            _events_from_payload(record.payload["events"])
            _require_record_id(record, f"command:{command.command_id}")
        elif record.kind == "turn.started":
            _require_fields(record.payload, {"request"})
            request = _turn_request_from_mapping(record.payload["request"])
            _require_record_id(record, f"turn-started:{request.turn_id}")
        elif record.kind == "turn.committed":
            _require_fields(
                record.payload, {"turn_id", "events", "usage", "adapter_invoked"}
            )
            _require_opaque(record.payload["turn_id"])
            if not isinstance(record.payload["adapter_invoked"], bool):
                raise NativeStateError("native adapter flag is invalid")
            _events_from_payload(record.payload["events"])
            _validate_turn_usage(_usage_from_mapping(record.payload["usage"]))
            _require_record_id(record, f"turn-committed:{record.payload['turn_id']}")
        elif record.kind == "turn.recovery-required":
            _require_fields(record.payload, {"turn_id", "reason_code", "events"})
            _require_opaque(record.payload["turn_id"])
            _require_identifier(record.payload["reason_code"])
            _events_from_payload(record.payload["events"])
            _require_record_id(
                record,
                f"turn-recovery-required:{record.payload['turn_id']}",
            )
        elif record.kind == "checkpoint.committed":
            _require_fields(record.payload, {"metadata", "event"})
            metadata = _metadata_from_mapping(record.payload["metadata"])
            event = ControlEvent.from_mapping(_mapping(record.payload["event"]))
            if event.type != "checkpoint.created":
                raise NativeStateError("native checkpoint event type is invalid")
            _require_record_id(
                record,
                f"checkpoint:{metadata.capsule_id}:{metadata.covered_position}",
            )
        else:
            raise NativeStateError("native record kind is invalid")
    except (TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, NativeStateError):
            raise
        raise NativeStateError("native record payload is invalid") from None


def _validate_event_drafts(
    drafts: Sequence[NativeEventDraft], event_mappings: Sequence[Mapping[str, object]]
) -> None:
    if len(drafts) != len(event_mappings):
        raise NativeStateError("native turn events do not match drafts")
    for draft, event_mapping in zip(drafts, event_mappings, strict=True):
        event = ControlEvent.from_mapping(event_mapping)
        if draft.type != event.type or _json_value(draft.payload) != _json_value(
            event.payload
        ):
            raise NativeStateError("native turn event does not match draft")


def _validate_turn_usage(usage: BudgetUsage) -> None:
    if (
        usage.application_tokens != 0
        or usage.child_tokens != 0
        or usage.aggregate_tokens != usage.controller_tokens
        or any(getattr(usage, field) > MAX_USAGE_VALUE for field in _USAGE_FIELDS)
    ):
        raise NativeStateError("native turn usage is invalid")


def _input_reference(
    command: ControlCommand, command_digest: str
) -> NativeInputReference:
    payload = command.payload
    return NativeInputReference(
        input_id=str(payload["input_id"]),
        delivery=str(payload["delivery"]),
        content_ref=str(payload["content_ref"]),
        command_digest=command_digest,
    )


def _action_result_reference(
    command: ControlCommand, command_digest: str
) -> NativeActionResultReference:
    payload = command.payload
    return NativeActionResultReference(
        action_id=str(payload["action_id"]),
        resolution=str(payload["resolution"]),
        reason_code=str(payload["reason_code"]),
        receipt_ref=payload["receipt_ref"] if payload["receipt_ref"] is None else str(payload["receipt_ref"]),
        command_digest=command_digest,
    )


def _turn_request_mapping(request: NativeTurnRequest) -> Mapping[str, object]:
    return {
        "turn_id": request.turn_id,
        "session_id": request.session_id,
        "generation": request.generation,
        "authority_revision": request.authority_revision,
        "causal_command_ids": request.causal_command_ids,
        "inputs": tuple(_input_reference_mapping(item) for item in request.inputs),
        "action_results": tuple(
            _action_result_reference_mapping(item) for item in request.action_results
        ),
        "budget": _remaining_budget_mapping(request.budget),
    }


def _turn_request_from_mapping(value: object) -> NativeTurnRequest:
    mapping = _mapping(value)
    _require_fields(
        mapping,
        {
            "turn_id",
            "session_id",
            "generation",
            "authority_revision",
            "causal_command_ids",
            "inputs",
            "action_results",
            "budget",
        },
    )
    return NativeTurnRequest(
        turn_id=str(mapping["turn_id"]),
        session_id=str(mapping["session_id"]),
        generation=_int(mapping["generation"]),
        authority_revision=_int(mapping["authority_revision"]),
        causal_command_ids=tuple(
            str(item) for item in _sequence(mapping["causal_command_ids"])
        ),
        inputs=tuple(
            _input_reference_from_mapping(item) for item in _sequence(mapping["inputs"])
        ),
        action_results=tuple(
            _action_result_reference_from_mapping(item)
            for item in _sequence(mapping["action_results"])
        ),
        budget=_remaining_budget_from_mapping(mapping["budget"]),
    )


def _input_reference_mapping(value: NativeInputReference) -> Mapping[str, object]:
    return {
        "input_id": value.input_id,
        "delivery": value.delivery,
        "content_ref": value.content_ref,
        "command_digest": value.command_digest,
    }


def _input_reference_from_mapping(value: object) -> NativeInputReference:
    mapping = _mapping(value)
    _require_fields(mapping, {"input_id", "delivery", "content_ref", "command_digest"})
    return NativeInputReference(
        input_id=str(mapping["input_id"]),
        delivery=str(mapping["delivery"]),
        content_ref=str(mapping["content_ref"]),
        command_digest=str(mapping["command_digest"]),
    )


def _action_result_reference_mapping(
    value: NativeActionResultReference,
) -> Mapping[str, object]:
    return {
        "action_id": value.action_id,
        "resolution": value.resolution,
        "reason_code": value.reason_code,
        "receipt_ref": value.receipt_ref,
        "command_digest": value.command_digest,
    }


def _action_result_reference_from_mapping(
    value: object,
) -> NativeActionResultReference:
    mapping = _mapping(value)
    _require_fields(
        mapping,
        {"action_id", "resolution", "reason_code", "receipt_ref", "command_digest"},
    )
    return NativeActionResultReference(
        action_id=str(mapping["action_id"]),
        resolution=str(mapping["resolution"]),
        reason_code=str(mapping["reason_code"]),
        receipt_ref=(
            None if mapping["receipt_ref"] is None else str(mapping["receipt_ref"])
        ),
        command_digest=str(mapping["command_digest"]),
    )


def _metadata_mapping(value: NativeCapsuleMetadata) -> Mapping[str, object]:
    return {
        "capsule_id": value.capsule_id,
        "capsule_digest": value.capsule_digest,
        "control_plane_id": value.control_plane_id,
        "control_plane_version": value.control_plane_version,
        "checkpoint_version": value.checkpoint_version,
        "covered_position": value.covered_position,
        "covered_sequence": value.covered_sequence,
        "storage_ref": value.storage_ref,
    }


def _metadata_from_mapping(value: object) -> NativeCapsuleMetadata:
    mapping = _mapping(value)
    _require_fields(
        mapping,
        {
            "capsule_id",
            "capsule_digest",
            "control_plane_id",
            "control_plane_version",
            "checkpoint_version",
            "covered_position",
            "covered_sequence",
            "storage_ref",
        },
    )
    return NativeCapsuleMetadata(
        capsule_id=str(mapping["capsule_id"]),
        capsule_digest=str(mapping["capsule_digest"]),
        control_plane_id=str(mapping["control_plane_id"]),
        control_plane_version=str(mapping["control_plane_version"]),
        checkpoint_version=str(mapping["checkpoint_version"]),
        covered_position=_int(mapping["covered_position"]),
        covered_sequence=_int(mapping["covered_sequence"]),
        storage_ref=str(mapping["storage_ref"]),
    )


def _events_from_payload(value: object) -> tuple[ControlEvent, ...]:
    return tuple(ControlEvent.from_mapping(_mapping(item)) for item in _sequence(value))


def _remaining_budget_mapping(value: RemainingBudget) -> Mapping[str, object]:
    if not isinstance(value, RemainingBudget):
        raise NativeStateError("native remaining budget is invalid")
    _validate_budget_bounds(value)
    return {
        "controller_tokens": value.controller_tokens,
        "application_tokens": value.application_tokens,
        "child_tokens": value.child_tokens,
        "aggregate_tokens": value.aggregate_tokens,
        "cost_micros": value.cost_micros,
        "deadline_ms": value.deadline_ms,
    }


def _remaining_budget_from_mapping(value: object) -> RemainingBudget:
    mapping = _mapping(value)
    _require_fields(
        mapping,
        {
            "controller_tokens",
            "application_tokens",
            "child_tokens",
            "aggregate_tokens",
            "cost_micros",
            "deadline_ms",
        },
    )
    budget = RemainingBudget(
        controller_tokens=_int(mapping["controller_tokens"]),
        application_tokens=_int(mapping["application_tokens"]),
        child_tokens=_int(mapping["child_tokens"]),
        aggregate_tokens=_int(mapping["aggregate_tokens"]),
        cost_micros=_int(mapping["cost_micros"]),
        deadline_ms=_int(mapping["deadline_ms"]),
    )
    _validate_budget_bounds(budget)
    return budget


def _usage_mapping(value: BudgetUsage) -> Mapping[str, object]:
    if not isinstance(value, BudgetUsage):
        raise NativeStateError("native usage is invalid")
    _validate_usage_bounds(value)
    return {field: getattr(value, field) for field in _USAGE_FIELDS}


def _usage_from_mapping(value: object) -> BudgetUsage:
    mapping = _mapping(value)
    _require_fields(mapping, set(_USAGE_FIELDS))
    usage = BudgetUsage(
        controller_tokens=_int(mapping["controller_tokens"]),
        application_tokens=_int(mapping["application_tokens"]),
        child_tokens=_int(mapping["child_tokens"]),
        aggregate_tokens=_int(mapping["aggregate_tokens"]),
        cost_micros=_int(mapping["cost_micros"]),
    )
    _validate_usage_bounds(usage)
    return usage


def _add_usage(previous: BudgetUsage, delta: BudgetUsage) -> BudgetUsage:
    values = {
        field: getattr(previous, field) + getattr(delta, field)
        for field in _USAGE_FIELDS
    }
    if any(value > MAX_USAGE_VALUE for value in values.values()):
        raise NativeStateError("native usage exceeds bounded maximum")
    return BudgetUsage(**values)


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise NativeStateError("native mapping is invalid")
    return value


def _sequence(value: object) -> Sequence[object]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise NativeStateError("native sequence is invalid")
    return value


def _require_fields(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise NativeStateError("native record fields are invalid")


def _require_bound(state: NativeControllerState) -> None:
    if state.session_id is None or state.generation is None:
        raise NativeStateError("native session is not bound")


def _require_active(state: NativeControllerState) -> None:
    _require_bound(state)
    if state.terminal_event_id is not None:
        raise NativeStateError("native session is terminal")
    if state.lifecycle not in {"created", "running", "paused", "recovery_required"}:
        raise NativeStateError("native session is not active")


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    if value in values:
        return values
    return (*values, value)


def _int(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeStateError("native integer is invalid")
    return value


def _require_positive_int(value: object) -> None:
    if _int(value) < 1:
        raise NativeStateError("native positive integer is invalid")


def _require_opaque(value: object) -> None:
    validate_control_command(
        {
            "protocol": "asterion.agent-control/v1",
            "command_id": value,
            "session_id": "session-validation",
            "authority_revision": 1,
            "type": "session.detach",
            "payload": {"reason_code": "validation"},
        }
    )


def _require_identifier(value: object) -> None:
    if not isinstance(value, str):
        raise NativeStateError("native identifier is invalid")
    validate_control_event(
        {
            "protocol": "asterion.agent-control/v1",
            "event_id": "event-validation",
            "session_id": "session-validation",
            "generation": 1,
            "sequence": 1,
            "emitted_at": "2026-08-30T00:00:00Z",
            "type": "session.running",
            "payload": {"reason_code": value},
        }
    )


def _require_digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NativeStateError("native digest is invalid")


def _require_semver(value: object) -> None:
    if not isinstance(value, str):
        raise NativeStateError("native version is invalid")
    validate_control_event(
        {
            "protocol": "asterion.agent-control/v1",
            "event_id": "event-validation",
            "session_id": "session-validation",
            "generation": 1,
            "sequence": 1,
            "emitted_at": "2026-08-30T00:00:00Z",
            "type": "checkpoint.created",
            "payload": {
                "checkpoint_id": "checkpoint-validation",
                "capsule_id": "capsule-validation",
                "capsule_digest": "0" * 64,
                "control_plane_id": "native",
                "control_plane_version": value,
                "checkpoint_version": value,
                "covered_sequence": 1,
                "storage_ref": "storage-validation",
            },
        }
    )


_USAGE_FIELDS = (
    "controller_tokens",
    "application_tokens",
    "child_tokens",
    "aggregate_tokens",
    "cost_micros",
)


def _validate_usage_bounds(value: BudgetUsage) -> None:
    for field in _USAGE_FIELDS:
        current = getattr(value, field)
        if current < 0 or current > MAX_SAFE_JSON_INTEGER:
            raise NativeStateError("native usage exceeds safe integer range")


def _validate_budget_bounds(value: RemainingBudget) -> None:
    for field in (
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
        "deadline_ms",
    ):
        current = getattr(value, field)
        if current < 0 or current > MAX_SAFE_JSON_INTEGER:
            raise NativeStateError("native budget exceeds safe integer range")


def _require_record_id(record: NativeRecord, expected: str) -> None:
    if record.record_id != expected:
        raise NativeStateError("native record identity is not canonical")
