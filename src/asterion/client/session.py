"""Client endpoint projected from one host-owned control session."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.client.private import ClientPrivateValueService
from asterion.client.protocol import ClientCursor, ClientEvent, ClientIntent
from asterion.control.journal import CanonicalJournal, JournalCursor
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
        self._events: list[ClientEvent] = []
        self._rebuild()

    @property
    def private_values(self) -> ClientPrivateValueService:
        return self._private_values

    async def submit(self, intent: ClientIntent) -> str:
        if (
            not isinstance(intent, ClientIntent)
            or intent.client_id != self._client_id
            or intent.session_id != self._host.session_id
            or intent.authority_revision != self._host.authority_revision
        ):
            raise ClientSessionError("client intent identity is invalid")
        digest = _digest(intent.to_mapping())
        previous = self._intent_digests.get(intent.intent_id)
        if previous is not None:
            if previous != digest:
                raise ClientSessionError("client intent retry conflicts")
            return f"client:{intent.intent_id}"
        command_type, payload = _control_mapping(intent)
        try:
            self._journal.accept_client_intent(intent, expected_position=self._journal.position)
        except Exception:
            raise ClientSessionError("client intent journal admission failed") from None
        self._intent_digests[intent.intent_id] = digest
        try:
            command = self._host.client_command(
                command_id=f"client:{intent.intent_id}",
                command_type=command_type,
                payload=payload,
            )
            await self._host.dispatch(command)
        except Exception:
            raise ClientSessionError("client intent dispatch failed") from None
        return command.command_id

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
        cursor = None if not self._events else ClientCursor(self._host.generation, len(self._events))
        async for observation in source.client_observations(cursor):
            if (
                observation.session_id != self._host.session_id
                or observation.generation != self._host.generation
            ):
                raise ClientSessionError("client observation identity is invalid")
            event = ClientEvent(
                protocol="asterion.agent-client/v1",
                event_id=observation.observation_id,
                session_id=observation.session_id,
                generation=observation.generation,
                sequence=len(self._events) + 1,
                emitted_at=observation.emitted_at,
                type=observation.kind,
                payload=observation.payload,
            )
            try:
                self._journal.accept_client_observation(
                    observation.to_mapping(), expected_position=self._journal.position
                )
                self._journal.accept_client_event(
                    event, expected_position=self._journal.position
                )
            except Exception:
                raise ClientSessionError("client observation journal admission failed") from None
            self._events.append(event)

    async def close(self) -> None:
        await self._host.close()

    def _rebuild(self) -> None:
        try:
            entries = self._journal.replay(JournalCursor(0))
            for entry in entries:
                record = entry.record
                if record.kind == "client.intent.accepted":
                    intent = ClientIntent.from_mapping(record.payload["intent"])
                    if intent.client_id != self._client_id or intent.session_id != self._host.session_id:
                        raise ValueError
                    digest = _digest(intent.to_mapping())
                    prior = self._intent_digests.get(intent.intent_id)
                    if prior is not None and prior != digest:
                        raise ValueError
                    self._intent_digests[intent.intent_id] = digest
                elif record.kind == "client.event.accepted":
                    event = ClientEvent.from_mapping(record.payload["event"])
                    if event.session_id != self._host.session_id or event.generation != self._host.generation:
                        raise ValueError
                    if event.sequence != len(self._events) + 1:
                        raise ValueError
                    self._events.append(event)
        except Exception:
            raise ClientSessionError("client session recovery failed") from None


def _control_mapping(intent: ClientIntent) -> tuple[str, Mapping[str, object]]:
    if intent.type not in _CONTROL_TYPES:
        raise ClientSessionError("client intent is unsupported")
    payload: Mapping[str, object] = intent.payload
    if intent.type == "session.create":
        payload = {"goal_id": payload["goal_id"], "goal_ref": payload["goal_ref"]}
    return intent.type, payload


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
