"""Client endpoint projected from one host-owned control session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Protocol

from asterion.client.private import (
    ClientPrivateValueService,
    OperationPrivateRequestMetadata,
)
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
from asterion.operation.protocol import OperationReceipt, OperationRequestDescriptor, OperationTransaction


class ClientSessionError(RuntimeError):
    """Raised when host-owned client session processing is rejected."""


@dataclass(frozen=True)
class OperationCommandBinding:
    """One closed client command binding; it never names a provider or service."""

    command_name: str
    feature_id: str
    request_kind: str
    request_purpose: str
    accepted_media_type: str
    max_request_bytes: int
    deadline_ms: int

    def __post_init__(self) -> None:
        expected = _OPERATION_BINDING_VALUES.get(self.command_name)
        if (
            expected is None
            or tuple(getattr(self, field) for field in _OPERATION_BINDING_FIELDS)
            != expected
        ):
            raise ClientSessionError("operation command binding is invalid")


class OperationCommandDispatcher(Protocol):
    async def execute_operation(self, transaction: OperationTransaction) -> OperationReceipt:
        ...


class OperationPrivateRequestDescriber(Protocol):
    def describe_operation_request(
        self,
        request_ref: str,
        *,
        client_id: str,
        session_id: str,
        generation: int,
        authority_revision: int,
    ) -> OperationPrivateRequestMetadata:
        ...


_OPERATION_BINDING_FIELDS = (
    "command_name", "feature_id", "request_kind", "request_purpose",
    "accepted_media_type", "max_request_bytes", "deadline_ms",
)
_OPERATION_BINDING_VALUES = MappingProxyType({
    "operation.auth": ("operation.auth", "operation.auth", "operation.auth-request", "operation.auth", "application/json", 4096, 30_000),
    "operation.controlled-update-restart": ("operation.controlled-update-restart", "operation.controlled-update-restart", "operation.controlled-update-restart-request", "operation.controlled-update-restart", "application/json", 4096, 30_000),
    "operation.doctor": ("operation.doctor", "operation.doctor", "operation.doctor-request", "operation.doctor", "application/json", 4096, 30_000),
    "operation.model-selection": ("operation.model-selection", "operation.model-selection", "operation.model-selection-request", "operation.model-selection", "application/json", 4096, 30_000),
    "operation.settings-keybindings": ("operation.settings-keybindings", "operation.settings-keybindings", "operation.settings-keybindings-request", "operation.settings-keybindings", "application/json", 4096, 30_000),
    "operation.telemetry-usage": ("operation.telemetry-usage", "operation.telemetry-usage", "operation.telemetry-usage-request", "operation.telemetry-usage", "application/json", 4096, 30_000),
})


@dataclass(frozen=True)
class OperationCommandRegistry:
    """Immutable exact operation command names at one selected revision."""

    revision: int = 1
    bindings: tuple[OperationCommandBinding, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ClientSessionError("operation command registry is invalid")
        bindings = self.bindings or tuple(
            OperationCommandBinding(*values) for _, values in sorted(_OPERATION_BINDING_VALUES.items())
        )
        if (
            not isinstance(bindings, tuple)
            or any(type(binding) is not OperationCommandBinding for binding in bindings)
            or tuple(binding.command_name for binding in bindings) != tuple(sorted(_OPERATION_BINDING_VALUES))
        ):
            raise ClientSessionError("operation command registry is invalid")
        object.__setattr__(self, "bindings", bindings)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(binding.command_name for binding in self.bindings)

    def resolve(self, command_name: str, *, revision: int) -> OperationCommandBinding:
        if revision != self.revision or not isinstance(command_name, str):
            raise ClientSessionError("operation command is invalid")
        for binding in self.bindings:
            if binding.command_name == command_name:
                return binding
        raise ClientSessionError("operation command is invalid")

    def invoke(self, command_name: str) -> OperationCommandBinding:
        """Compatibility-free exact lookup for UI command validation."""

        return self.resolve(command_name, revision=self.revision)


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
        operation_dispatcher: OperationCommandDispatcher | None = None,
        operation_registry: OperationCommandRegistry | None = None,
        operation_describer: OperationPrivateRequestDescriber | None = None,
        operation_authority_id: str | None = None,
        operation_cancellation_signal: object | None = None,
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
        dispatcher = host if operation_dispatcher is None else operation_dispatcher
        describer = private_values if operation_describer is None else operation_describer
        registry = OperationCommandRegistry() if operation_registry is None else operation_registry
        authority_id = (
            host.operation_authority_id
            if operation_authority_id is None
            else operation_authority_id
        )
        cancelled = _cancellation_value(
            operation_cancellation_signal,
            error_message="client session construction is invalid",
        )
        if (
            not callable(getattr(dispatcher, "execute_operation", None))
            or not callable(getattr(describer, "describe_operation_request", None))
            or type(registry) is not OperationCommandRegistry
            or not isinstance(authority_id, str)
            or not _opaque_id(authority_id)
            or cancelled
        ):
            raise ClientSessionError("client session construction is invalid")
        self._client_id = client_id
        self._host = host
        self._journal = journal
        self._private_values = private_values
        self._observation_source = observation_source
        self._operation_dispatcher = dispatcher
        self._operation_registry = registry
        self._operation_describer = describer
        self._operation_authority_id = authority_id
        self._operation_cancellation_signal = operation_cancellation_signal
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
        self._operation_receipt_keys: set[tuple[str, str, str]] = set()
        self._operation_receipt_statuses: dict[str, str] = {}
        self._operation_receipt_identities: dict[str, tuple[object, ...]] = {}
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

    @property
    def command_registry(self) -> OperationCommandRegistry:
        return self._operation_registry

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
        if intent.type == "command.invoke":
            command_name = intent.payload["command_name"]
            command_revision = intent.payload["command_revision"]
            if not isinstance(command_name, str) or type(command_revision) is not int:
                raise ClientSessionError("operation command is invalid")
            self._operation_registry.resolve(
                command_name, revision=command_revision,
            )
        else:
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
        await self._project_durable_operation_receipts()
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
            pending_operation_receipt: OperationReceipt | None = None
            pending_durable_operation_receipts: list[OperationReceipt] = []
            for entry in entries:
                record = entry.record
                if pending_intent is not None:
                    if pending_intent.type == "command.invoke":
                        if record.kind.startswith("operation."):
                            if record.kind == "operation.receipted":
                                if pending_operation_receipt is not None:
                                    raise ValueError
                                pending_operation_receipt = OperationReceipt.from_mapping(
                                    _mapping(record.payload["receipt"])
                                )
                            continue
                        if (
                            record.kind != "client.event.accepted"
                            or pending_operation_receipt is None
                        ):
                            raise ValueError
                        event = ClientEvent.from_mapping(
                            _mapping(record.payload["event"])
                        )
                        if event != self._operation_event(pending_operation_receipt):
                            raise ValueError
                        self._append_event(event)
                        self._remember_operation_receipt(pending_operation_receipt)
                        self._dispatched_intent_ids.add(pending_intent.intent_id)
                        pending_intent = None
                        pending_operation_receipt = None
                        self._pending_intent_id = None
                        continue
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
                elif record.kind == "operation.receipted":
                    pending_durable_operation_receipts.append(
                        OperationReceipt.from_mapping(_mapping(record.payload["receipt"]))
                    )
                elif record.kind == "client.event.accepted":
                    event = ClientEvent.from_mapping(_mapping(record.payload["event"]))
                    if event.type != "operation.receipted":
                        raise ValueError
                    matches = tuple(
                        receipt for receipt in pending_durable_operation_receipts
                        if self._operation_event(receipt) == event
                    )
                    if len(matches) != 1:
                        raise ValueError
                    self._append_event(event)
                    self._remember_operation_receipt(matches[0])
                    pending_durable_operation_receipts.remove(matches[0])
            if pending_intent is not None and pending_intent.type == "command.invoke":
                if pending_operation_receipt is None:
                    raise ValueError
                self._project_operation_receipt_sync(pending_operation_receipt)
                self._dispatched_intent_ids.add(pending_intent.intent_id)
                self._pending_intent_id = None
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
        if intent.type == "command.invoke":
            await self._dispatch_operation_intent(intent)
            self._dispatched_intent_ids.add(intent.intent_id)
            self._pending_intent_id = None
            return
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

    async def _dispatch_operation_intent(self, intent: ClientIntent) -> None:
        transaction = self._operation_transaction(intent)
        try:
            receipt = await self._operation_dispatcher.execute_operation(transaction)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ClientSessionError("client operation dispatch failed") from None
        if type(receipt) is not OperationReceipt:
            raise ClientSessionError("client operation receipt is invalid")
        await self._project_operation_receipt(receipt)

    def _operation_transaction(self, intent: ClientIntent) -> OperationTransaction:
        payload = intent.payload
        try:
            command_name = payload["command_name"]
            command_revision = payload["command_revision"]
            request_ref = payload["arguments_ref"]
            if (
                not isinstance(command_name, str)
                or type(command_revision) is not int
                or not isinstance(request_ref, str)
            ):
                raise ValueError
            binding = self._operation_registry.resolve(
                command_name, revision=command_revision
            )
            if _cancellation_value(
                self._operation_cancellation_signal,
                error_message="client operation is cancelled",
            ):
                raise ValueError
            metadata = self._operation_describer.describe_operation_request(
                request_ref, client_id=self._client_id,
                session_id=self._host.session_id, generation=self._host.generation,
                authority_revision=self._host.authority_revision,
            )
            if type(metadata) is not OperationPrivateRequestMetadata:
                raise ValueError
            if (
                metadata.request_ref != request_ref
                or metadata.client_id != self._client_id
                or metadata.session_id != self._host.session_id
                or metadata.generation != self._host.generation
                or metadata.authority_revision != self._host.authority_revision
                or metadata.media_type != binding.accepted_media_type
                or metadata.byte_count > binding.max_request_bytes
                or _cancellation_value(
                    self._operation_cancellation_signal,
                    error_message="client operation is cancelled",
                )
            ):
                raise ValueError
            request = OperationRequestDescriptor(
                request_kind=binding.request_kind, request_ref=metadata.request_ref,
                request_sha256=metadata.request_sha256, media_type=metadata.media_type,
                byte_count=metadata.byte_count, purpose=binding.request_purpose,
                client_id=metadata.client_id, session_id=metadata.session_id,
                generation=metadata.generation,
                authority_revision=metadata.authority_revision,
            )
            digest = _digest(intent.to_mapping())
            return OperationTransaction(
                operation_id=f"operation-{digest}", request=request,
                session_id=self._host.session_id, client_id=self._client_id,
                generation=self._host.generation,
                authority_revision=self._host.authority_revision,
                authority_id=self._operation_authority_id, idempotency_key=digest,
                feature_id=binding.feature_id, requested_at=_operation_timestamp(digest),
            )
        except asyncio.CancelledError:
            raise ClientSessionError("client operation is invalid") from None
        except ClientSessionError:
            raise
        except Exception:
            raise ClientSessionError("client operation is invalid") from None

    async def _project_operation_receipt(self, receipt: OperationReceipt) -> None:
        try:
            if (
                receipt.client_id != self._client_id
                or receipt.session_id != self._host.session_id
                or receipt.generation != self._host.generation
                or receipt.authority_revision != self._host.authority_revision
                or receipt.authority_id != self._operation_authority_id
            ):
                raise ValueError
            key = (receipt.operation_id, receipt.status, receipt.receipt_ref)
            prior = self._operation_receipt_statuses.get(receipt.operation_id)
            if key in self._operation_receipt_keys:
                return
            if (
                (prior is not None and (prior != "uncertain" or receipt.status == "uncertain"))
                or (
                    receipt.operation_id in self._operation_receipt_identities
                    and self._operation_receipt_identities[receipt.operation_id]
                    != _operation_receipt_identity(receipt)
                )
            ):
                raise ValueError
            event = self._operation_event(receipt)
            entry = self._journal.accept_client_event(
                event, expected_position=self._journal.position
            )
            self._host.advance_client_record(entry)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ClientSessionError("client operation receipt is invalid") from None
        self._append_event(event)
        self._remember_operation_receipt(receipt)

    def _project_operation_receipt_sync(self, receipt: OperationReceipt) -> None:
        try:
            event = self._operation_event(receipt)
            entry = self._journal.accept_client_event(
                event, expected_position=self._journal.position
            )
            self._host.advance_client_record(entry)
        except Exception:
            raise ValueError from None
        self._append_event(event)
        self._remember_operation_receipt(receipt)

    def _operation_event(self, receipt: OperationReceipt) -> ClientEvent:
        return ClientEvent(
            protocol="asterion.agent-client/v1",
            event_id="operation-event-" + hashlib.sha256(
                f"{receipt.operation_id}:{receipt.status}:{receipt.receipt_ref}".encode()
            ).hexdigest(),
            session_id=self._host.session_id, generation=self._host.generation,
            sequence=len(self._events) + 1, emitted_at=receipt.completed_at,
            type="operation.receipted",
            payload={
                "effect_counts": dict(receipt.effect_counts),
                "feature_id": receipt.feature_id,
                "operation_id": receipt.operation_id,
                "reason_code": receipt.reason_code,
                "receipt_ref": receipt.receipt_ref,
                "status": receipt.status,
            },
        )

    def _remember_operation_receipt(self, receipt: OperationReceipt) -> None:
        key = (receipt.operation_id, receipt.status, receipt.receipt_ref)
        identity = _operation_receipt_identity(receipt)
        prior = self._operation_receipt_statuses.get(receipt.operation_id)
        if (
            receipt.client_id != self._client_id
            or receipt.session_id != self._host.session_id
            or receipt.generation != self._host.generation
            or receipt.authority_revision != self._host.authority_revision
            or receipt.authority_id != self._operation_authority_id
            or key in self._operation_receipt_keys
            or (
                receipt.operation_id in self._operation_receipt_identities
                and self._operation_receipt_identities[receipt.operation_id] != identity
            )
            or (prior is not None and (prior != "uncertain" or receipt.status == "uncertain"))
        ):
            raise ValueError
        self._operation_receipt_keys.add(key)
        self._operation_receipt_statuses[receipt.operation_id] = receipt.status
        self._operation_receipt_identities[receipt.operation_id] = identity

    async def _project_durable_operation_receipts(self) -> None:
        try:
            entries = self._journal.replay(JournalCursor(0))
            receipts = tuple(
                OperationReceipt.from_mapping(_mapping(entry.record.payload["receipt"]))
                for entry in entries if entry.record.kind == "operation.receipted"
            )
        except Exception:
            raise ClientSessionError("client operation receipt is invalid") from None
        for receipt in receipts:
            key = (receipt.operation_id, receipt.status, receipt.receipt_ref)
            if key not in self._operation_receipt_keys:
                await self._project_operation_receipt(receipt)

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


def _operation_timestamp(intent_digest: str) -> str:
    """Derive a replay-stable protocol timestamp from the full intent digest."""

    seconds = int(intent_digest[:8], 16) % 2_000_000_000
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _operation_receipt_identity(receipt: OperationReceipt) -> tuple[object, ...]:
    return (
        receipt.operation_id, receipt.request_ref, receipt.request_sha256,
        receipt.purpose, receipt.session_id, receipt.client_id,
        receipt.generation, receipt.authority_revision, receipt.authority_id,
        receipt.idempotency_key, receipt.feature_id,
    )


def _opaque_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value))
    )


def _cancellation_value(signal: object | None, *, error_message: str) -> bool:
    if signal is None:
        return False
    try:
        value = getattr(signal, "cancelled")
    except asyncio.CancelledError:
        raise ClientSessionError(error_message) from None
    except Exception:
        raise ClientSessionError(error_message) from None
    if type(value) is not bool:
        raise ClientSessionError(error_message)
    return value
