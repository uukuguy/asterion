"""Client endpoint projected from one host-owned control session."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.client.private import ClientPrivateValueService
from asterion.client.export import (
    ClientArtifactReceipt,
    ClientArtifactStore,
    ClientExportAuthority,
)
from asterion.client.protocol import (
    ClientCursor,
    ClientEvent,
    ClientIntent,
    validate_client_event_stream,
)
from asterion.control.journal import CanonicalJournal, JournalCursor
from asterion.control.host import ControlCommand
from asterion.control.manager import ControlHost


class ClientSessionError(RuntimeError):
    """Raised when host-owned client session processing is rejected."""


@dataclass(frozen=True, repr=False)
class ClientObservation:
    observation_id: str
    session_id: str
    generation: int
    source_sequence: int
    emitted_at: str
    kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        event = ClientEvent(
            protocol="asterion.agent-client/v1",
            event_id=self.observation_id,
            session_id=self.session_id,
            generation=self.generation,
            sequence=self.source_sequence,
            emitted_at=self.emitted_at,
            type=self.kind,
            payload=self.payload,
        )
        object.__setattr__(self, "payload", event.payload)

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "observation_id": self.observation_id,
                "session_id": self.session_id,
                "generation": self.generation,
                "source_sequence": self.source_sequence,
                "emitted_at": self.emitted_at,
                "kind": self.kind,
                "payload": self.payload,
            }
        )


class ClientObservationSource(Protocol):
    def client_observations(
        self, cursor: ClientCursor | None = None
    ) -> AsyncIterator[ClientObservation]:
        ...


class ClientSessionEndpoint(Protocol):
    @property
    def private_values(self) -> ClientPrivateValueService:
        ...

    @property
    def client_id(self) -> str:
        ...

    @property
    def session_id(self) -> str:
        ...

    @property
    def generation(self) -> int:
        ...

    async def submit(self, intent: ClientIntent) -> str:
        ...

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        ...

    async def pump(self, *, until_terminal: bool = False) -> None:
        ...

    async def close(self) -> None:
        ...


_CONTROL_TYPES = frozenset(
    {"input.submit", "session.attach", "session.cancel", "session.create", "session.pause", "session.resume"}
)


class HostClientSessionEndpoint:
    """The only client-facing adapter over one already-selected ``ControlHost``."""

    def __init__(
        self,
        *,
        client_id: str,
        host: ControlHost,
        journal: CanonicalJournal,
        private_values: ClientPrivateValueService,
        observation_source: ClientObservationSource | None = None,
    ) -> None:
        if (
            not isinstance(client_id, str)
            or not isinstance(host, ControlHost)
            or not callable(getattr(journal, "append", None))
            or not callable(getattr(journal, "replay", None))
            or not isinstance(private_values, ClientPrivateValueService)
            or private_values.access.client_id != client_id
            or private_values.access.session_id != host.session_id
            or private_values.access.authority_revision != host.authority_revision
            or (
                observation_source is not None
                and not callable(getattr(observation_source, "client_observations", None))
            )
        ):
            raise ClientSessionError("client session construction is invalid")
        self._client_id = client_id
        self._host = host
        self._journal = journal
        self._private_values = private_values
        self._observation_source = observation_source
        self._intent_digests: dict[str, str] = {}
        self._dispatched_intent_ids: set[str] = set()
        self._pending_intent_id: str | None = None
        self._submit_lock = asyncio.Lock()
        self._inflight_dispatches: dict[str, tuple[str, asyncio.Task[None]]] = {}
        self._closed = False
        self._events: list[ClientEvent] = []
        self._event_ids: set[str] = set()
        self._active_call_ids: set[str] = set()
        self._seen_call_ids: set[str] = set()
        self._terminal_seen = False
        self._last_observation_source_sequence: int | None = None
        self._rebuild()

    @property
    def private_values(self) -> ClientPrivateValueService:
        return self._private_values

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def session_id(self) -> str:
        return self._host.session_id

    @property
    def generation(self) -> int:
        return self._host.generation

    def export(
        self,
        *,
        visibility: str,
        artifacts: ClientArtifactStore,
        authority: ClientExportAuthority | None = None,
    ) -> ClientArtifactReceipt:
        """Export the admitted complete stream through injected host services."""

        from asterion.client.export import export_client_session

        return export_client_session(
            tuple(self._events), visibility=visibility, artifacts=artifacts,
            authority=authority, private_values=self._private_values,
            journal=self._journal, client_id=self._client_id,
        )

    async def submit(self, intent: ClientIntent) -> str:
        if (
            not isinstance(intent, ClientIntent)
            or intent.client_id != self._client_id
            or intent.session_id != self._host.session_id
            or intent.authority_revision != self._host.authority_revision
        ):
            raise ClientSessionError("client intent identity is invalid")
        digest = _digest(intent.to_mapping())
        _control_mapping(intent)
        async with self._submit_lock:
            if self._closed:
                raise ClientSessionError("client session is closed")
            previous = self._intent_digests.get(intent.intent_id)
            in_flight = self._inflight_dispatches.get(intent.intent_id)
            if in_flight is not None:
                if in_flight[0] != digest:
                    raise ClientSessionError("client intent retry conflicts")
                dispatch = in_flight[1]
            else:
                if previous is not None:
                    if previous != digest:
                        raise ClientSessionError("client intent retry conflicts")
                    if intent.intent_id in self._dispatched_intent_ids:
                        return f"client:{intent.intent_id}"
                    if self._pending_intent_id != intent.intent_id:
                        raise ClientSessionError("client intent recovery is incomplete")
                else:
                    if self._pending_intent_id is not None:
                        raise ClientSessionError("client intent recovery is incomplete")
                    try:
                        entry = self._journal.accept_client_intent(
                            intent, expected_position=self._journal.position
                        )
                        self._host.advance_client_record(entry)
                    except Exception:
                        raise ClientSessionError(
                            "client intent journal admission failed"
                        ) from None
                    self._intent_digests[intent.intent_id] = digest
                    self._pending_intent_id = intent.intent_id
                dispatch = asyncio.create_task(self._dispatch_intent(intent))
                self._inflight_dispatches[intent.intent_id] = (digest, dispatch)
                dispatch.add_done_callback(
                    lambda completed: self._complete_dispatch(
                        intent.intent_id, digest, completed
                    )
                )
        await asyncio.shield(dispatch)
        return f"client:{intent.intent_id}"

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        if cursor is not None and (
            not isinstance(cursor, ClientCursor)
            or cursor.generation != self._host.generation
            or cursor.sequence > len(self._events)
        ):
            raise ClientSessionError("client event cursor is invalid")
        start = 0 if cursor is None else cursor.sequence

        async def iterate() -> AsyncIterator[ClientEvent]:
            for event in tuple(self._events[start:]):
                yield event

        return iterate()

    async def pump(self, *, until_terminal: bool = False) -> None:
        await self._host.pump(until_terminal=until_terminal)
        source = self._observation_source
        if source is None:
            return
        cursor = (
            None
            if self._last_observation_source_sequence is None
            else ClientCursor(
                self._host.generation, self._last_observation_source_sequence
            )
        )
        async for observation in source.client_observations(cursor):
            if (
                observation.session_id != self._host.session_id
                or observation.generation != self._host.generation
                or (
                    self._last_observation_source_sequence is not None
                    and observation.source_sequence
                    <= self._last_observation_source_sequence
                )
            ):
                raise ClientSessionError("client observation identity is invalid")
            event = self._project_observation(observation)
            self._validate_next_event(event)
            try:
                observation_entry = self._journal.accept_client_observation(
                    observation.to_mapping(), expected_position=self._journal.position
                )
                self._host.advance_client_record(observation_entry)
                event_entry = self._journal.accept_client_event(
                    event, expected_position=self._journal.position
                )
                self._host.advance_client_record(event_entry)
            except Exception:
                raise ClientSessionError("client observation journal admission failed") from None
            self._append_event(event)
            self._last_observation_source_sequence = observation.source_sequence

    async def close(self) -> None:
        async with self._submit_lock:
            self._closed = True
            dispatches = tuple(entry[1] for entry in self._inflight_dispatches.values())
        for dispatch in dispatches:
            dispatch.cancel()
        if dispatches:
            await asyncio.gather(*dispatches, return_exceptions=True)
        await self._host.close()

    def _complete_dispatch(
        self, intent_id: str, digest: str, dispatch: asyncio.Task[None]
    ) -> None:
        if not dispatch.cancelled():
            dispatch.exception()
        if self._inflight_dispatches.get(intent_id) == (digest, dispatch):
            del self._inflight_dispatches[intent_id]

    def _rebuild(self) -> None:
        try:
            entries = self._journal.replay(JournalCursor(0))
            pending_intent: ClientIntent | None = None
            pending_observation: ClientObservation | None = None
            for entry in entries:
                record = entry.record
                if pending_intent is not None:
                    if record.kind != "command.accepted":
                        raise ValueError
                    command = ControlCommand.from_mapping(
                        _mapping(record.payload["command"])
                    )
                    if command != self._client_command(pending_intent):
                        raise ValueError
                    self._dispatched_intent_ids.add(pending_intent.intent_id)
                    pending_intent = None
                    self._pending_intent_id = None
                    continue
                if pending_observation is not None:
                    if record.kind != "client.event.accepted":
                        raise ValueError
                    event = ClientEvent.from_mapping(_mapping(record.payload["event"]))
                    if not _matches_observation(event, pending_observation):
                        raise ValueError
                    self._append_event(event)
                    self._last_observation_source_sequence = (
                        pending_observation.source_sequence
                    )
                    pending_observation = None
                    continue
                if record.kind == "client.intent.accepted":
                    intent = ClientIntent.from_mapping(_mapping(record.payload["intent"]))
                    if (
                        intent.client_id != self._client_id
                        or intent.session_id != self._host.session_id
                        or intent.authority_revision != self._host.authority_revision
                    ):
                        raise ValueError
                    digest = _digest(intent.to_mapping())
                    prior = self._intent_digests.get(intent.intent_id)
                    if prior is not None:
                        raise ValueError
                    self._intent_digests[intent.intent_id] = digest
                    pending_intent = intent
                    self._pending_intent_id = intent.intent_id
                elif record.kind == "client.observation.accepted":
                    observation = _observation_from_mapping(record.payload["observation"])
                    if (
                        observation.session_id != self._host.session_id
                        or observation.generation != self._host.generation
                        or (
                            self._last_observation_source_sequence is not None
                            and observation.source_sequence
                            <= self._last_observation_source_sequence
                        )
                    ):
                        raise ValueError
                    pending_observation = observation
                elif record.kind == "client.event.accepted":
                    raise ValueError
            if pending_observation is not None:
                event = self._project_observation(pending_observation)
                self._validate_next_event(event)
                event_entry = self._journal.accept_client_event(
                    event, expected_position=self._journal.position
                )
                self._host.advance_client_record(event_entry)
                self._append_event(event)
                self._last_observation_source_sequence = (
                    pending_observation.source_sequence
                )
        except Exception:
            raise ClientSessionError("client session recovery failed") from None

    async def _dispatch_intent(self, intent: ClientIntent) -> None:
        if self._pending_intent_id != intent.intent_id:
            raise ClientSessionError("client intent recovery is invalid")
        command = self._client_command(intent)
        try:
            await self._host.dispatch(command)
        except Exception:
            if self._journal_has_command(command):
                self._dispatched_intent_ids.add(intent.intent_id)
                self._pending_intent_id = None
            raise ClientSessionError("client intent dispatch failed") from None
        self._dispatched_intent_ids.add(intent.intent_id)
        self._pending_intent_id = None

    def _client_command(self, intent: ClientIntent) -> ControlCommand:
        command_type, payload = _control_mapping(intent)
        return self._host.client_command(
            command_id=f"client:{intent.intent_id}",
            command_type=command_type,
            payload=payload,
        )

    def _journal_has_command(self, command: ControlCommand) -> bool:
        try:
            return any(
                entry.record.kind == "command.accepted"
                and ControlCommand.from_mapping(
                    _mapping(entry.record.payload["command"])
                )
                == command
                for entry in self._journal.replay(JournalCursor(0))
            )
        except Exception:
            raise ClientSessionError("client intent recovery failed") from None

    def _project_observation(self, observation: ClientObservation) -> ClientEvent:
        return ClientEvent(
            protocol="asterion.agent-client/v1",
            event_id=observation.observation_id,
            session_id=observation.session_id,
            generation=observation.generation,
            sequence=len(self._events) + 1,
            emitted_at=observation.emitted_at,
            type=observation.kind,
            payload=observation.payload,
        )

    def _validate_next_event(self, event: ClientEvent) -> None:
        if (
            event.session_id != self._host.session_id
            or event.generation != self._host.generation
            or event.sequence != len(self._events) + 1
            or event.event_id in self._event_ids
            or self._terminal_seen
        ):
            raise ClientSessionError("client event prefix is invalid")
        if event.type == "tool.started":
            call_id = event.payload["call_id"]
            if not isinstance(call_id, str) or call_id in self._seen_call_ids:
                raise ClientSessionError("client event prefix is invalid")
        elif event.type == "tool.completed":
            call_id = event.payload["call_id"]
            if not isinstance(call_id, str) or call_id not in self._active_call_ids:
                raise ClientSessionError("client event prefix is invalid")
        elif event.type == "session.terminal":
            try:
                validate_client_event_stream((*self._events, event))
            except ValueError:
                raise ClientSessionError("client event prefix is invalid") from None

    def _append_event(self, event: ClientEvent) -> None:
        self._validate_next_event(event)
        if event.type == "tool.started":
            call_id = event.payload["call_id"]
            assert isinstance(call_id, str)
            self._active_call_ids.add(call_id)
            self._seen_call_ids.add(call_id)
        elif event.type == "tool.completed":
            call_id = event.payload["call_id"]
            assert isinstance(call_id, str)
            self._active_call_ids.remove(call_id)
        elif event.type == "session.terminal":
            self._terminal_seen = True
        self._event_ids.add(event.event_id)
        self._events.append(event)


def _control_mapping(intent: ClientIntent) -> tuple[str, Mapping[str, object]]:
    if intent.type not in _CONTROL_TYPES:
        raise ClientSessionError("client intent is unsupported")
    payload: Mapping[str, object] = intent.payload
    if intent.type == "session.create":
        payload = {"goal_id": payload["goal_id"], "goal_ref": payload["goal_ref"]}
    return intent.type, payload


def _observation_from_mapping(value: object) -> ClientObservation:
    value = _mapping(value)
    return ClientObservation(
        observation_id=value["observation_id"],  # type: ignore[arg-type]
        session_id=value["session_id"],  # type: ignore[arg-type]
        generation=value["generation"],  # type: ignore[arg-type]
        source_sequence=value["source_sequence"],  # type: ignore[arg-type]
        emitted_at=value["emitted_at"],  # type: ignore[arg-type]
        kind=value["kind"],  # type: ignore[arg-type]
        payload=value["payload"],  # type: ignore[arg-type]
    )


def _matches_observation(event: ClientEvent, observation: ClientObservation) -> bool:
    return (
        event.event_id == observation.observation_id
        and event.session_id == observation.session_id
        and event.generation == observation.generation
        and event.sequence > 0
        and event.emitted_at == observation.emitted_at
        and event.type == observation.kind
        and event.payload == observation.payload
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    return value


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
