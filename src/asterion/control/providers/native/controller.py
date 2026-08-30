"""Durable native controller state machine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import NoReturn

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.protocol import (
    ACTION_RESOLUTIONS,
    OPAQUE_ID,
    SEMANTIC_VERSION,
    UTC_TIMESTAMP,
    validate_control_command,
)
from asterion.control.providers.native.capsule import NativeCapsuleStore
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeActionResultReference,
    NativeCapsuleMetadata,
    NativeControllerState,
    NativeEntry,
    NativeEventDraft,
    NativeRecord,
    NativeInputReference,
    NativeTurnRequest,
    NativeTurnResult,
    _json_value,
)
from asterion.control.providers.native.state import (
    _command_committed_record_from_mapping,
    _metadata_from_mapping,
    _session_bound_record_from_mapping,
    _turn_request_from_mapping,
    authority_synced_record,
    checkpoint_committed_record,
    reduce_native_entries,
    turn_committed_record,
    turn_recovery_required_record,
    turn_started_record,
)
from asterion.control.providers.native.store import (
    NativeSessionStore,
    NativeStorageOwner,
    NativeStoreError,
)
from asterion.control.providers.native.turn import NativeTurnAdapter


CrashHook = Callable[[str], None]


class NativeControllerError(RuntimeError):
    """Raised when native controller state cannot be safely advanced."""

    def __init__(self, *_: object) -> None:
        super().__init__("native controller is unavailable")
        self.__cause__ = None
        self.__context__ = None


def _raise_controller_error() -> NoReturn:
    try:
        raise NativeControllerError from None
    except NativeControllerError as error:
        error.__context__ = None
        raise


def _no_crash(_point: str) -> None:
    return None


class NativeController:
    def __init__(
        self,
        *,
        owner: NativeStorageOwner,
        session_store: NativeSessionStore,
        capsule_store: NativeCapsuleStore,
        turn_adapter: NativeTurnAdapter,
        provider_id: str,
        provider_version: str,
        system_id: str,
        system_version: str,
        session_id: str,
        generation: int,
        checkpoint_version: str,
        authority_id: str,
        authority_revision: int,
        event_id_factory: Callable[[], str],
        turn_id_factory: Callable[[], str],
        capsule_id_factory: Callable[[], str],
        clock: Callable[[], str],
        crash_hook: CrashHook = _no_crash,
    ) -> None:
        try:
            _require_owner(owner)
            _require_store(session_store)
            _require_capsule_store(capsule_store)
            _require_adapter(turn_adapter)
            _require_identifier(provider_id)
            _require_semver(provider_version)
            _require_identifier(system_id)
            _require_semver(system_version)
            _require_opaque(session_id)
            _require_positive(generation)
            _require_semver(checkpoint_version)
            _require_opaque(authority_id)
            _require_positive(authority_revision)
            for factory in (
                event_id_factory,
                turn_id_factory,
                capsule_id_factory,
                clock,
            ):
                if not callable(factory):
                    raise ValueError
            if not callable(crash_hook):
                raise ValueError
            self._owner = owner
            self._session_store = session_store
            self._capsule_store = capsule_store
            self._turn_adapter = turn_adapter
            self._provider_id = provider_id
            self._provider_version = provider_version
            self._system_id = system_id
            self._system_version = system_version
            self._session_id = session_id
            self._generation = generation
            self._checkpoint_version = checkpoint_version
            self._authority_id = authority_id
            self._authority_revision = authority_revision
            self._event_id_factory = event_id_factory
            self._turn_id_factory = turn_id_factory
            self._capsule_id_factory = capsule_id_factory
            self._clock = clock
            self._crash_hook = crash_hook
            self._state = self._reduce_store()
            self._validate_recovered_identity()
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    @property
    def state(self) -> NativeControllerState:
        return self._state

    async def accept(self, command: ControlCommand) -> None:
        try:
            command_mapping = _control_command_mapping(command)
            command_digest = _digest(command_mapping)
            self._preflight_checkpoint_request(command, command_digest)
            records = self._transition_command(
                self.state,
                command,
                command_mapping,
                command_digest,
            )
            if records:
                self._crash_hook("command-before-publish")
            self._append_many(records)
            if records:
                self._crash_hook("command-after-publish-before-ack")
            if command.type == "checkpoint.request":
                self._ensure_checkpoint(str(command.payload["checkpoint_id"]))
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def sync_authority(self, budget: RemainingBudget) -> None:
        try:
            if type(budget) is not RemainingBudget:
                raise NativeControllerError
            if self.state.session_id is None:
                return
            if self.state.terminal_event_id is not None:
                return
            revision = self._require_bound_authority_revision()
            self._append_equal_or_new(authority_synced_record(revision, budget))
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def begin_ready_turn(self) -> NativeTurnRequest | None:
        try:
            request = self._next_turn_request(self.state)
            if request is None:
                return None
            self._append(turn_started_record(request))
            self._crash_hook("turn-after-start")
            return self.state.pending_turn
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def turn_is_budget_limited(self, request: NativeTurnRequest) -> bool:
        self._require_pending_turn(request)
        return not self._has_admissible_turn_budget(request.budget)

    def commit_budget_limited_turn(self, request: NativeTurnRequest) -> None:
        try:
            self._require_pending_turn(request)
            if self._has_admissible_turn_budget(request.budget):
                raise NativeControllerError
            events = self._budget_limited_events(request)
            result = NativeTurnResult(request.turn_id, events=(), usage=BudgetUsage.zero())
            self._append(
                turn_committed_record(result, events, adapter_invoked=False)
            )
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    async def execute_turn(self, request: NativeTurnRequest) -> NativeTurnResult:
        try:
            self._require_pending_turn(request)
            result = await self._turn_adapter.execute(request)
            self._crash_hook("turn-after-adapter-before-commit")
            return result
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def commit_turn(
        self, request: NativeTurnRequest, result: NativeTurnResult
    ) -> None:
        try:
            events = self._validated_turn_events(request, result)
            committed = _result_for_committed_events(result, events)
            self._append(turn_committed_record(committed, events))
            if any(event.type in _TERMINAL_EVENT_TYPES for event in events):
                self._crash_hook("terminal-after-commit-before-host-receipt")
            else:
                self._crash_hook("turn-after-commit-before-yield")
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def fail_turn(self, request: NativeTurnRequest, reason_code: str) -> None:
        try:
            events = self._recovery_events(request, reason_code)
            self._append(
                turn_recovery_required_record(request.turn_id, reason_code, events)
            )
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def checkpoint(self, checkpoint_id: str) -> ControlEvent:
        try:
            return self._ensure_checkpoint(checkpoint_id)
        except (NativeControllerError, NativeStoreError):
            raise
        except Exception:
            _raise_controller_error()

    def replay_events(self, cursor: EventCursor | None) -> tuple[ControlEvent, ...]:
        if cursor is not None and type(cursor) is not EventCursor:
            raise NativeControllerError
        entries = self._session_store.replay()
        self._state = reduce_native_entries(entries)
        return self._validated_event_suffix(self.state.events, cursor)

    def close(self) -> None:
        try:
            self._capsule_store.close()
        finally:
            try:
                self._session_store.close()
            finally:
                self._owner.close()

    def _transition_command(
        self,
        state: NativeControllerState,
        command: ControlCommand,
        command_mapping: Mapping[str, object],
        command_digest: str,
    ) -> tuple[NativeRecord, ...]:
        self._validate_command_identity(state, command)
        previous = state.command_digests.get(command.command_id)
        if previous is not None:
            if previous != command_digest:
                raise NativeControllerError
            return ()
        if state.terminal_event_id is not None:
            raise NativeControllerError
        if state.lifecycle == "empty":
            if command.type != "session.create":
                raise NativeControllerError
            bound = _session_bound_record_from_mapping(
                provider_id=self._provider_id,
                provider_version=self._provider_version,
                system_id=self._system_id,
                system_version=self._system_version,
                session_id=self._session_id,
                generation=self._generation,
                checkpoint_version=self._checkpoint_version,
                authority_id=self._authority_id,
                authority_revision=self._authority_revision,
                initial_create_command_mapping=command_mapping,
            )
            return (
                bound,
                _command_committed_record_from_mapping(
                    command_mapping, self._command_events(state, command)
                ),
            )
        if state.lifecycle == "bound":
            if (
                command.type != "session.create"
                or not _is_incomplete_create_state(state)
                or state.initial_create_command_digest != command_digest
            ):
                raise NativeControllerError
            return (
                _command_committed_record_from_mapping(
                    command_mapping, self._command_events(state, command)
                ),
            )
        if command.type == "session.create":
            raise NativeControllerError
        return (
            _command_committed_record_from_mapping(
                command_mapping, self._command_events(state, command)
            ),
        )

    def _validate_command_identity(
        self, state: NativeControllerState, command: ControlCommand
    ) -> None:
        if command.session_id != self._session_id:
            raise NativeControllerError
        revision = self._authority_revision if state.lifecycle == "empty" else state.authority_revision
        if revision is not None and command.authority_revision != revision:
            raise NativeControllerError
        if command.type == "session.create":
            if (
                command.payload["system_id"] != self._system_id
                or command.payload["system_version"] != self._system_version
            ):
                raise NativeControllerError
        if command.type == "session.attach":
            cursor = command.payload["cursor"]
            if not isinstance(cursor, Mapping):
                raise NativeControllerError
            if cursor["generation"] != self._generation or cursor["sequence"] > len(state.events):
                raise NativeControllerError

    def _command_events(
        self, state: NativeControllerState, command: ControlCommand
    ) -> tuple[ControlEvent, ...]:
        if command.type == "session.create":
            return (
                self._event(
                    state.next_sequence,
                    "session.created",
                    {
                        "goal_id": command.payload["goal_id"],
                        "authority_id": self._authority_id,
                        "authority_revision": self._authority_revision,
                    },
                ),
                self._event(
                    state.next_sequence + 1,
                    "session.running",
                    {"reason_code": "started"},
                ),
            )
        if command.type == "session.pause":
            if state.lifecycle not in {"running", "recovery_required"}:
                raise NativeControllerError
            return (
                self._event(
                    state.next_sequence,
                    "session.paused",
                    {"reason_code": command.payload["reason_code"]},
                ),
            )
        if command.type == "session.resume":
            if state.lifecycle not in {"paused", "recovery_required"}:
                raise NativeControllerError
            return (
                self._event(
                    state.next_sequence,
                    "session.running",
                    {"reason_code": command.payload["reason_code"]},
                ),
            )
        if command.type == "session.cancel":
            if state.lifecycle not in {"created", "running", "paused", "recovery_required"}:
                raise NativeControllerError
            events = [
                self._event(
                    state.next_sequence,
                    "session.cancelled",
                    {"reason_code": command.payload["reason_code"]},
                )
            ]
            return tuple(events)
        if command.type in {"session.detach", "session.attach", "input.submit", "action.resolve", "checkpoint.request"}:
            if state.lifecycle != "running":
                raise NativeControllerError
            if command.type == "action.resolve":
                self._validate_action_resolution(state, command)
            return ()
        raise NativeControllerError

    def _validate_action_resolution(
        self, state: NativeControllerState, command: ControlCommand
    ) -> None:
        action_id = str(command.payload["action_id"])
        resolution = str(command.payload["resolution"])
        if resolution not in ACTION_RESOLUTIONS:
            raise NativeControllerError
        current = state.action_statuses.get(action_id)
        if current is None:
            raise NativeControllerError
        if resolution == "admitted":
            if current != "proposed":
                raise NativeControllerError
            return
        if resolution in {"rejected", "succeeded", "failed", "cancelled", "uncertain"}:
            if current not in {"proposed", "admitted"}:
                raise NativeControllerError
            return
        raise NativeControllerError

    def _append(self, record: NativeRecord) -> None:
        expected = self._session_store.position
        self._session_store.append(expected, record)
        self._state = self._reduce_store()

    def _append_many(self, records: tuple[NativeRecord, ...]) -> None:
        for record in records:
            self._append(record)

    def _append_equal_or_new(self, record: NativeRecord) -> None:
        entries = self._session_store.replay()
        if entries and entries[-1].record == record:
            self._state = reduce_native_entries(entries)
            return
        self._append(record)

    def _require_bound_authority_revision(self) -> int:
        revision = self.state.authority_revision
        if self.state.session_id is None or revision is None:
            raise NativeControllerError
        return revision

    def _next_turn_request(
        self, state: NativeControllerState
    ) -> NativeTurnRequest | None:
        if state.pending_turn is not None:
            if state.pending_turn.turn_id in state.fenced_turn_ids:
                return None
            return state.pending_turn
        if (
            state.lifecycle != "running"
            or state.terminal_event_id is not None
            or state.remaining_budget is None
            or state.authority_revision is None
            or state.session_id is None
            or state.generation is None
        ):
            return None
        recovered_reference_digests = self._recovered_reference_digests(state)
        pending_inputs = tuple(
            item
            for item in state.pending_inputs
            if item.command_digest not in recovered_reference_digests
        )
        terminal_results = tuple(
            result
            for result in state.pending_action_results
            if result.resolution in {"rejected", "succeeded", "failed", "cancelled", "uncertain"}
            and result.command_digest not in recovered_reference_digests
        )
        if pending_inputs and terminal_results:
            raise NativeControllerError
        if pending_inputs:
            inputs = (pending_inputs[0],)
            command_ids = self._command_ids_for_digests(
                {item.command_digest for item in inputs}
            )
            turn_id = self._stable_turn_id(
                "input",
                command_ids,
                tuple(_input_identity(item) for item in inputs),
            )
            return NativeTurnRequest(
                turn_id=turn_id,
                session_id=state.session_id,
                generation=state.generation,
                authority_revision=state.authority_revision,
                causal_command_ids=command_ids,
                inputs=inputs,
                action_results=(),
                budget=state.remaining_budget,
            )
        if terminal_results:
            action_results = (terminal_results[0],)
            command_ids = self._command_ids_for_digests(
                {item.command_digest for item in action_results}
            )
            turn_id = self._stable_turn_id(
                "action",
                command_ids,
                tuple(_action_result_identity(item) for item in action_results),
            )
            return NativeTurnRequest(
                turn_id=turn_id,
                session_id=state.session_id,
                generation=state.generation,
                authority_revision=state.authority_revision,
                causal_command_ids=command_ids,
                inputs=(),
                action_results=action_results,
                budget=state.remaining_budget,
            )
        return None

    def _recovered_reference_digests(
        self, state: NativeControllerState
    ) -> frozenset[str]:
        if not state.recovery_required_turn_ids:
            return frozenset()
        recovered_turn_ids = frozenset(state.recovery_required_turn_ids)
        digests: set[str] = set()
        for entry in self._session_store.replay():
            if entry.record.kind != "turn.started":
                continue
            request = _turn_request_from_mapping(entry.record.payload["request"])
            if request.turn_id not in recovered_turn_ids:
                continue
            digests.update(item.command_digest for item in request.inputs)
            digests.update(item.command_digest for item in request.action_results)
        return frozenset(digests)

    def _stable_turn_id(
        self,
        kind: str,
        command_ids: tuple[str, ...],
        references: tuple[Mapping[str, object], ...],
    ) -> str:
        command_digests = tuple(self.state.command_digests[item] for item in command_ids)
        return _bounded_hash_id(
            "turn",
            {
                "domain": "asterion.native-turn/v1",
                "kind": kind,
                "session_id": self._session_id,
                "generation": self._generation,
                "authority_revision": self.state.authority_revision,
                "causal_command_ids": command_ids,
                "causal_command_digests": command_digests,
                "references": references,
            },
        )

    def _command_ids_for_digests(self, digests: set[str]) -> tuple[str, ...]:
        command_ids = tuple(
            sorted(
                command_id
                for command_id, digest in self.state.command_digests.items()
                if digest in digests
            )
        )
        if not command_ids or len(command_ids) != len(digests):
            raise NativeControllerError
        return command_ids

    def _require_pending_turn(self, request: NativeTurnRequest) -> None:
        if type(request) is not NativeTurnRequest:
            raise NativeControllerError
        if self.state.pending_turn != request or request.turn_id in self.state.fenced_turn_ids:
            raise NativeControllerError

    def _has_admissible_turn_budget(self, budget: RemainingBudget) -> bool:
        return (
            budget.deadline_ms > 0
            and budget.controller_tokens > 0
            and budget.aggregate_tokens > 0
            and budget.cost_micros >= 0
        )

    def _budget_limited_events(
        self, request: NativeTurnRequest
    ) -> tuple[ControlEvent, ControlEvent]:
        self._require_pending_turn(request)
        return (
            self._event(
                self.state.next_sequence,
                "budget.reported",
                _usage_payload(self.state.usage),
            ),
            self._event(
                self.state.next_sequence + 1,
                "session.budget-limited",
                {"reason_code": "native-budget-limited"},
            ),
        )

    def _validated_turn_events(
        self, request: NativeTurnRequest, result: NativeTurnResult
    ) -> tuple[ControlEvent, ...]:
        self._require_pending_turn(request)
        if type(result) is not NativeTurnResult or result.turn_id != request.turn_id:
            raise NativeControllerError
        usage = result.usage
        _validate_native_usage(usage)
        _require_usage_fits_budget(usage, request.budget)
        current = self.state.remaining_budget
        if current is None:
            raise NativeControllerError
        _require_usage_fits_budget(usage, current)
        cumulative = _add_usage(self.state.usage, usage)
        events: list[ControlEvent] = []
        for offset, draft in enumerate(result.events):
            payload: Mapping[str, object]
            if draft.type == "budget.reported":
                payload = _usage_payload(cumulative)
            else:
                payload = draft.payload
            events.append(
                self._event(self.state.next_sequence + offset, draft.type, payload)
            )
        return tuple(events)

    def _recovery_events(
        self, request: NativeTurnRequest, reason_code: str
    ) -> tuple[ControlEvent, ControlEvent]:
        self._require_pending_turn(request)
        _require_identifier(reason_code)
        return (
            self._event(
                self.state.next_sequence,
                "fault.raised",
                {"code": reason_code, "recoverable": True, "evidence_ref": None},
            ),
            self._event(
                self.state.next_sequence + 1,
                "session.recovery-required",
                {"reason_code": reason_code},
            ),
        )

    def _seal_capsule(self, checkpoint_id: str) -> NativeCapsuleMetadata:
        _require_opaque(checkpoint_id)
        covered_position = self._session_store.position
        covered_sequence = self.state.next_sequence - 1
        prefix = self._session_store.replay()
        if len(prefix) != covered_position or reduce_native_entries(prefix) != self.state:
            raise NativeControllerError
        payload = _canonical_json(
            _checkpoint_capsule_payload(
                checkpoint_id=checkpoint_id,
                control_plane_id=self._provider_id,
                control_plane_version=self._provider_version,
                checkpoint_version=self._checkpoint_version,
                covered_position=covered_position,
                covered_sequence=covered_sequence,
                entries=prefix,
            )
        )
        capsule_id = _bounded_hash_id(
            "capsule",
            {
                "domain": "asterion.native-capsule-id/v1",
                "checkpoint_id": checkpoint_id,
                "payload_digest": hashlib.sha256(payload).hexdigest(),
                "covered_position": covered_position,
                "covered_sequence": covered_sequence,
                "control_plane_id": self._provider_id,
                "control_plane_version": self._provider_version,
                "checkpoint_version": self._checkpoint_version,
            },
        )
        metadata = self._capsule_store.seal(
            capsule_id=capsule_id,
            payload=payload,
            covered_position=covered_position,
            covered_sequence=covered_sequence,
        )
        if type(metadata) is not NativeCapsuleMetadata:
            raise NativeControllerError
        self._capsule_store.verify(metadata)
        return metadata

    def _checkpoint_event(
        self, checkpoint_id: str, metadata: NativeCapsuleMetadata
    ) -> ControlEvent:
        return self._event(
            self.state.next_sequence,
            "checkpoint.created",
            {
                "checkpoint_id": checkpoint_id,
                "capsule_id": metadata.capsule_id,
                "capsule_digest": metadata.capsule_digest,
                "control_plane_id": metadata.control_plane_id,
                "control_plane_version": metadata.control_plane_version,
                "checkpoint_version": metadata.checkpoint_version,
                "covered_sequence": metadata.covered_sequence,
                "storage_ref": metadata.storage_ref,
            },
        )

    def _ensure_checkpoint(self, checkpoint_id: str) -> ControlEvent:
        _require_opaque(checkpoint_id)
        existing = self._checkpoint_record_for(checkpoint_id)
        if existing is not None:
            metadata, event = existing
            self._capsule_store.verify(metadata)
            return event
        request_position = self._checkpoint_request_position(checkpoint_id)
        if request_position is not None and request_position != self._session_store.position:
            raise NativeControllerError
        if self.state.lifecycle not in {"running", "paused"}:
            raise NativeControllerError
        metadata = self._seal_capsule(checkpoint_id)
        self._crash_hook("capsule-after-write-before-checkpoint")
        event = self._checkpoint_event(checkpoint_id, metadata)
        self._append(checkpoint_committed_record(metadata, event))
        self._crash_hook("checkpoint-after-commit-before-yield")
        return event

    def _preflight_checkpoint_request(
        self, command: ControlCommand, command_digest: str
    ) -> None:
        if command.type != "checkpoint.request":
            return
        checkpoint_id = str(command.payload["checkpoint_id"])
        for _, existing, existing_digest in self._checkpoint_request_records(
            checkpoint_id
        ):
            if existing.command_id != command.command_id or existing_digest != command_digest:
                raise NativeControllerError

    def _checkpoint_request_position(self, checkpoint_id: str) -> int | None:
        result: int | None = None
        for position, _, _ in self._checkpoint_request_records(checkpoint_id):
            if result is not None:
                raise NativeControllerError
            result = position
        return result

    def _checkpoint_request_records(
        self, checkpoint_id: str
    ) -> tuple[tuple[int, ControlCommand, str], ...]:
        result: list[tuple[int, ControlCommand, str]] = []
        for entry in self._session_store.replay():
            if entry.record.kind != "command.committed":
                continue
            command = ControlCommand.from_mapping(
                _mapping_from_json(entry.record.payload["command"])
            )
            if (
                command.type == "checkpoint.request"
                and command.payload["checkpoint_id"] == checkpoint_id
            ):
                result.append(
                    (entry.position, command, str(entry.record.payload["command_digest"]))
                )
        return tuple(result)

    def _checkpoint_record_for(
        self, checkpoint_id: str
    ) -> tuple[NativeCapsuleMetadata, ControlEvent] | None:
        result: tuple[NativeCapsuleMetadata, ControlEvent] | None = None
        for event in self.state.events:
            if event.type != "checkpoint.created":
                continue
            if event.payload["checkpoint_id"] != checkpoint_id:
                continue
            for entry in self._session_store.replay():
                if entry.record.kind != "checkpoint.committed":
                    continue
                candidate = ControlEvent.from_mapping(
                    _mapping_from_json(entry.record.payload["event"])
                )
                if candidate != event:
                    continue
                metadata = _metadata_from_mapping(entry.record.payload["metadata"])
                current = (metadata, event)
                if result is not None and result != current:
                    raise NativeControllerError
                result = current
        return result

    def _validated_event_suffix(
        self, events: tuple[ControlEvent, ...], cursor: EventCursor | None
    ) -> tuple[ControlEvent, ...]:
        if cursor is None:
            return events
        if type(cursor) is not EventCursor:
            raise NativeControllerError
        if cursor.generation != self._generation or cursor.sequence > len(events):
            raise NativeControllerError
        return events[cursor.sequence :]

    def _event(
        self,
        sequence: int,
        event_type: str,
        payload: Mapping[str, object],
    ) -> ControlEvent:
        event_id = self._event_id_factory()
        emitted_at = self._clock()
        _require_opaque(event_id)
        if not isinstance(emitted_at, str) or UTC_TIMESTAMP.fullmatch(emitted_at) is None:
            raise NativeControllerError
        return ControlEvent(
            event_id=event_id,
            session_id=self._session_id,
            generation=self._generation,
            sequence=sequence,
            emitted_at=emitted_at,
            type=event_type,
            payload=payload,
        )

    def _reduce_store(self) -> NativeControllerState:
        return reduce_native_entries(self._session_store.replay())

    def _validate_recovered_identity(self) -> None:
        state = self.state
        if state.lifecycle == "empty":
            return
        if (
            state.provider_id != self._provider_id
            or state.provider_version != self._provider_version
            or state.system_id != self._system_id
            or state.system_version != self._system_version
            or state.session_id != self._session_id
            or state.generation != self._generation
            or state.checkpoint_version != self._checkpoint_version
            or state.authority_id != self._authority_id
        ):
            raise NativeControllerError


def _require_owner(value: object) -> None:
    for name in ("require_open", "operation", "close"):
        if not callable(getattr(value, name, None)):
            raise NativeControllerError
    value.require_open()  # type: ignore[attr-defined]


def _require_store(value: object) -> None:
    for name in ("append", "replay", "close"):
        if not callable(getattr(value, name, None)):
            raise NativeControllerError


def _require_capsule_store(value: object) -> None:
    for name in ("seal", "verify", "close"):
        if not callable(getattr(value, name, None)):
            raise NativeControllerError


def _require_adapter(value: object) -> None:
    if not callable(getattr(value, "execute", None)) or not isinstance(
        getattr(value, "adapter_id", None), str
    ):
        raise NativeControllerError


def _require_identifier(value: object) -> None:
    if not isinstance(value, str):
        raise NativeControllerError
    ControlEvent(
        event_id="validation-event",
        session_id="validation-session",
        generation=1,
        sequence=1,
        emitted_at="2026-08-30T00:00:00Z",
        type="session.running",
        payload={"reason_code": value},
    )


def _require_semver(value: object) -> None:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise NativeControllerError


def _require_opaque(value: object) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise NativeControllerError


def _require_positive(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise NativeControllerError


def _is_incomplete_create_state(state: NativeControllerState) -> bool:
    return (
        state.lifecycle == "bound"
        and state.initial_create_command_digest is not None
        and state.goal_id is None
        and state.goal_status is None
        and state.budget_authority_revision is None
        and state.remaining_budget is None
        and not state.command_digests
        and not state.pending_inputs
        and not state.pending_action_results
        and state.pending_turn is None
        and not state.committed_turn_digests
        and not state.recovery_required_turn_ids
        and not state.fenced_turn_ids
        and not state.action_statuses
        and not state.action_receipt_refs
        and state.usage == BudgetUsage.zero()
        and not state.events
        and state.next_sequence == 1
        and state.checkpoint is None
        and state.terminal_event_id is None
    )


def _control_command_mapping(command: ControlCommand) -> Mapping[str, object]:
    if type(command) is not ControlCommand:
        raise NativeControllerError
    mapping = _mapping_from_json(command.to_mapping())
    validate_control_command(mapping)
    return mapping


def _input_identity(value: NativeInputReference) -> Mapping[str, object]:
    return {
        "input_id": value.input_id,
        "delivery": value.delivery,
        "content_ref": value.content_ref,
        "command_digest": value.command_digest,
    }


def _action_result_identity(value: NativeActionResultReference) -> Mapping[str, object]:
    return {
        "action_id": value.action_id,
        "resolution": value.resolution,
        "reason_code": value.reason_code,
        "receipt_ref": value.receipt_ref,
        "command_digest": value.command_digest,
    }


def _bounded_hash_id(prefix: str, value: Mapping[str, object]) -> str:
    digest = hashlib.sha256(_canonical_json(value)).hexdigest()
    candidate = f"{prefix}:{digest}"
    _require_opaque(candidate)
    return candidate


def _mapping_from_json(value: object) -> Mapping[str, object]:
    converted = _json_value(value)
    if not isinstance(converted, Mapping):
        raise NativeControllerError
    return converted


def _validate_native_usage(value: BudgetUsage) -> None:
    if (
        value.application_tokens != 0
        or value.child_tokens != 0
        or value.aggregate_tokens != value.controller_tokens
    ):
        raise NativeControllerError
    for field in _USAGE_FIELDS:
        current = getattr(value, field)
        if current < 0 or current > MAX_SAFE_JSON_INTEGER:
            raise NativeControllerError


def _require_usage_fits_budget(usage: BudgetUsage, budget: RemainingBudget) -> None:
    for field in _USAGE_FIELDS:
        if getattr(usage, field) > getattr(budget, field):
            raise NativeControllerError


def _add_usage(previous: BudgetUsage, delta: BudgetUsage) -> BudgetUsage:
    values = {
        field: getattr(previous, field) + getattr(delta, field)
        for field in _USAGE_FIELDS
    }
    if any(value < 0 or value > MAX_SAFE_JSON_INTEGER for value in values.values()):
        raise NativeControllerError
    return BudgetUsage(**values)


def _usage_payload(value: BudgetUsage) -> Mapping[str, object]:
    return {field: getattr(value, field) for field in _USAGE_FIELDS}


def _result_for_committed_events(
    result: NativeTurnResult, events: tuple[ControlEvent, ...]
) -> NativeTurnResult:
    """Use the canonical public event payloads for persisted draft validation."""

    if type(result) is not NativeTurnResult:
        raise NativeControllerError
    return NativeTurnResult(
        result.turn_id,
        tuple(
            NativeEventDraft(event.type, event.payload)
            for event in events
        ),
        result.usage,
    )


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _checkpoint_capsule_payload(
    *,
    checkpoint_id: str,
    control_plane_id: str,
    control_plane_version: str,
    checkpoint_version: str,
    covered_position: int,
    covered_sequence: int,
    entries: tuple[NativeEntry, ...],
) -> Mapping[str, object]:
    return {
        "format": "asterion.native-controller-capsule/v1",
        "checkpoint_id": checkpoint_id,
        "control_plane_id": control_plane_id,
        "control_plane_version": control_plane_version,
        "checkpoint_version": checkpoint_version,
        "covered_position": covered_position,
        "covered_sequence": covered_sequence,
        "journal_prefix": tuple(_entry_capsule_payload(entry) for entry in entries),
    }


def _entry_capsule_payload(entry: NativeEntry) -> Mapping[str, object]:
    if type(entry) is not NativeEntry:
        raise NativeControllerError
    record = entry.record
    if type(record) is not NativeRecord:
        raise NativeControllerError
    return {
        "position": entry.position,
        "previous_digest": entry.previous_digest,
        "digest": entry.digest,
        "record": {
            "record_id": record.record_id,
            "kind": record.kind,
            "payload": record.payload,
        },
    }


_USAGE_FIELDS = (
    "controller_tokens",
    "application_tokens",
    "child_tokens",
    "aggregate_tokens",
    "cost_micros",
)
_TERMINAL_EVENT_TYPES = frozenset(
    {
        "session.budget-limited",
        "session.cancelled",
        "session.completed",
        "session.failed",
    }
)
