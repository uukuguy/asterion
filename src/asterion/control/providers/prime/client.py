"""Host-side client for the exact Prime control-plane provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from asterion.control.authority import RemainingBudget
from asterion.control.ecosystem import (
    EcosystemActivationReceipt,
    EcosystemPortfolio,
)
from asterion.control.providers.prime.ecosystem import (
    McpCredentialRefresh,
    PrimeEcosystemConsumerNotQuiesced,
    PrimeEcosystemService,
)
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.protocol import ControlProtocolError, OPAQUE_ID
from asterion.control.private_store import (
    PrivateAttachmentResolver,
    PrivateContentResolver,
)
from asterion.control.session_context import (
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.control.providers.prime.process import (
    PRIME_GATEWAY_IPC_PROTOCOL,
    PrimeSidecarProcessError,
)
from asterion.control.providers.prime.long_running import (
    PrimeLongRunningIpcReceipt,
    validate_prime_long_running_mapping,
)
from asterion.control.providers.prime.operation import PrimeOperationClient
from asterion.client.protocol import ClientCursor
from asterion.client.private import PrivateValueDescriptor
from asterion.client.session import ClientObservation


MAX_PRIVATE_TEXT_BYTES = 1024 * 1024
MAX_PRIVATE_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_PREPARED_PRIVATE_INPUTS = 128


@dataclass(frozen=True)
class RlmLifecycleObservation:
    """One public-safe native RLM lifecycle transition from the sidecar."""

    type: Literal["rlm.child.started", "rlm.child.terminal", "rlm.child.deleted"]
    child_id: str
    status: Literal["completed", "failed", "cancelled"] | None = None
    native_identity_digest: str | None = None

    def __post_init__(self) -> None:
        if (
            self.type
            not in {"rlm.child.started", "rlm.child.terminal", "rlm.child.deleted"}
            or not isinstance(self.child_id, str)
            or OPAQUE_ID.fullmatch(self.child_id) is None
            or (
                self.type == "rlm.child.started"
                and (
                    self.status is not None
                    or not isinstance(self.native_identity_digest, str)
                    or len(self.native_identity_digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in self.native_identity_digest
                    )
                )
            )
            or (
                self.type == "rlm.child.terminal"
                and (
                    self.status not in {"completed", "failed", "cancelled"}
                    or self.native_identity_digest is not None
                )
            )
            or (
                self.type == "rlm.child.deleted"
                and (self.status is not None or self.native_identity_digest is not None)
            )
        ):
            raise PrimeControlError()


@dataclass(frozen=True)
class RlmAdmissionBinding:
    """Safe immutable metadata bound by the Gateway before a native child effect."""

    action_id: str
    child_id: str
    authority_revision: int
    depth: int
    model_selector_digest: str

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None
                for value in (self.action_id, self.child_id)
            )
            or isinstance(self.authority_revision, bool)
            or not isinstance(self.authority_revision, int)
            or self.authority_revision < 1
            or isinstance(self.depth, bool)
            or not isinstance(self.depth, int)
            or self.depth < 0
            or not isinstance(self.model_selector_digest, str)
            or len(self.model_selector_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.model_selector_digest)
        ):
            raise PrimeControlError()


@dataclass(frozen=True)
class RlmMessageAdmissionBinding:
    """Safe immutable native family-message binding and delivery observation."""

    action_id: str
    message_id: str
    sender_id: str
    recipient_id: str
    authority_revision: int
    body_digest: str
    delivered: bool

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None
                for value in (
                    self.action_id,
                    self.message_id,
                    self.sender_id,
                    self.recipient_id,
                )
            )
            or self.sender_id == self.recipient_id
            or isinstance(self.authority_revision, bool)
            or not isinstance(self.authority_revision, int)
            or self.authority_revision < 1
            or not isinstance(self.body_digest, str)
            or len(self.body_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.body_digest)
            or type(self.delivered) is not bool
        ):
            raise PrimeControlError()


@dataclass(frozen=True)
class ClientObservationHealth:
    """Closed, body-free health of the private client-observation projection."""

    status: Literal["healthy", "degraded", "resync-required"]
    reason_code: Literal["native-sequence-gap"] | None
    observed_through_native_sequence: int
    first_missing_native_sequence: int | None
    resync_required: bool

    def __post_init__(self) -> None:
        if (
            self.status not in {"healthy", "degraded", "resync-required"}
            or self.reason_code not in {None, "native-sequence-gap"}
            or isinstance(self.observed_through_native_sequence, bool)
            or not isinstance(self.observed_through_native_sequence, int)
            or self.observed_through_native_sequence < 0
            or self.first_missing_native_sequence is not None
            and (
                isinstance(self.first_missing_native_sequence, bool)
                or not isinstance(self.first_missing_native_sequence, int)
                or self.first_missing_native_sequence < 1
            )
            or type(self.resync_required) is not bool
            or self.status == "healthy"
            and (
                self.reason_code is not None
                or self.first_missing_native_sequence is not None
                or self.resync_required
            )
            or self.status != "healthy"
            and (
                self.reason_code != "native-sequence-gap"
                or self.first_missing_native_sequence
                != self.observed_through_native_sequence + 1
                or self.resync_required != (self.status == "resync-required")
            )
        ):
            raise PrimeControlError()


class PrimeControlError(RuntimeError):
    """Raised when Prime cannot safely accept or replay a control operation."""

    def __init__(
        self, message: str = "Prime control operation failed", *, safe_code: str | None = None
    ) -> None:
        if safe_code not in {None, "response-timeout", "sidecar-error", "response-eof", "response-invalid", "event-protocol", "event-runtime"}:
            raise ValueError("Prime control error safe code is invalid")
        self.safe_code = safe_code
        super().__init__(message)


class PrimeSidecarTransport(Protocol):
    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        """Send one request and return one validated sidecar response."""
        ...

    def events(
        self, envelope: Mapping[str, object]
    ) -> AsyncIterator[Mapping[str, object]]:
        """Yield public event mappings from the sidecar."""
        ...

    async def close(self) -> None:
        """Release the sidecar resources."""
        ...


class PrimeControlPlaneClient:
    """ControlPlaneClient implementation backed by the private Prime sidecar."""

    def __init__(
        self,
        *,
        process: PrimeSidecarTransport,
        private_content: PrivateContentResolver,
        private_attachments: PrivateAttachmentResolver | None = None,
        manifest: ControlPlaneManifest | None = None,
        event_observer: Callable[[ControlEvent], None] | None = None,
    ) -> None:
        try:
            valid_private_content = callable(
                getattr(private_content, "resolve_text", None)
            )
        except Exception:
            valid_private_content = False
        if not valid_private_content:
            raise PrimeControlError()
        if event_observer is not None and not callable(event_observer):
            raise PrimeControlError()
        self._process = process
        self._private_content = private_content
        self._private_attachments = private_attachments
        self._manifest = manifest or _load_manifest()
        self._event_observer = event_observer
        self._closed = False
        self._result_projections: dict[
            str, Mapping[str, str | list[str]]
        ] = {}
        self._prepared_inputs: OrderedDict[str, str] = OrderedDict()
        self._client_private_descriptors: dict[str, PrivateValueDescriptor] = {}
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._ecosystem_service: PrimeEcosystemService | None = None
        self._ecosystem_credential_refresh: McpCredentialRefresh | None = None
        self._operation_client: PrimeOperationClient | None = None

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    @property
    def ecosystem_service(self) -> PrimeEcosystemService | None:
        """Return the private selected-provider ecosystem boundary, if bound."""

        return self._ecosystem_service

    @property
    def operation_client(self) -> PrimeOperationClient:
        """Return the generic, body-free operation sidecar bridge."""

        client = self._operation_client
        if client is None:
            client = PrimeOperationClient(self._process)
            self._operation_client = client
        return client

    def bind_operation_client(self, client: PrimeOperationClient) -> None:
        """Bind the factory-validated operations-v1 bridge exactly once."""

        if type(client) is not PrimeOperationClient or self._operation_client is not None:
            raise PrimeControlError()
        self._operation_client = client

    def bind_ecosystem_service(
        self,
        service: PrimeEcosystemService,
        credential_refresh: McpCredentialRefresh,
    ) -> None:
        """Bind the already-preflighted ecosystem capabilities exactly once."""

        try:
            valid = (
                type(service) is PrimeEcosystemService
                and callable(getattr(credential_refresh, "refresh", None))
            )
        except Exception:
            valid = False
        if (
            not valid
            or self._ecosystem_service is not None
            or self._ecosystem_credential_refresh is not None
        ):
            raise PrimeControlError()
        self._ecosystem_service = service
        self._ecosystem_credential_refresh = credential_refresh

    async def activate_ecosystem_portfolio(
        self,
        portfolio: EcosystemPortfolio,
    ) -> EcosystemActivationReceipt:
        """Activate one sealed portfolio through the factory-bound service."""

        service = self._ecosystem_service
        credential_refresh = self._ecosystem_credential_refresh
        if self._closed or service is None or credential_refresh is None:
            raise PrimeControlError()
        try:
            return await service.activate(portfolio, credential_refresh)
        except Exception:
            raise PrimeControlError() from None

    async def activate_ecosystem(
        self, frame: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Send one selected-provider private ecosystem activation frame."""

        if self._closed or not isinstance(frame, Mapping):
            raise PrimeControlError()
        try:
            envelope: dict[str, object] = {
                "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
                "id": _request_id(),
                "type": "ecosystem_activate",
                "frame": _json_value(frame),
            }
        except Exception:
            raise PrimeControlError() from None
        try:
            response = await self._process.request(envelope)
            receipt = response.get("receipt")
            if (
                set(response) != {"protocol", "id", "type", "receipt"}
                or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
                or response.get("id") != envelope["id"]
                or response.get("type") != "ecosystem_receipt"
                or not isinstance(receipt, Mapping)
            ):
                raise PrimeControlError()
            return MappingProxyType(dict(receipt))
        except Exception:
            await self.quiesce_ecosystem()
            raise PrimeControlError() from None

    async def quiesce_ecosystem(self) -> None:
        """Definitively stop the selected consumer of a private projection."""

        try:
            await self.close()
        except Exception:
            raise PrimeEcosystemConsumerNotQuiesced() from None

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        """Resolve operator-owned refs or currently prepared provider refs."""

        if not isinstance(reference, str) or not isinstance(max_bytes, int):
            raise PrimeControlError()
        cached = self._prepared_inputs.get(reference)
        if cached is not None:
            self._prepared_inputs.move_to_end(reference)
            if len(cached.encode("utf-8")) > max_bytes:
                raise PrimeControlError()
            return cached
        return self._private_content.resolve_text(reference, max_bytes=max_bytes)

    def cache_private_input(self, reference: str, text: str) -> None:
        """Seed a private input that was resolved by a parent provider boundary."""

        self._cache_private_input(reference, text)

    async def prepare_private_input(self, reference: str) -> None:
        """Read one provider-generated private input from the sidecar into memory."""

        if self._closed or not isinstance(reference, str):
            raise PrimeControlError()
        if reference in self._prepared_inputs:
            self._prepared_inputs.move_to_end(reference)
            return
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "private.read",
            "reference": reference,
        }
        try:
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        text = response.get("text")
        if (
            set(response) != {"protocol", "id", "type", "text"}
            or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
            or response.get("type") != "private.value"
            or not isinstance(text, str)
        ):
            raise PrimeControlError()
        self._cache_private_input(reference, text)

    def release_private_input(self, reference: str) -> None:
        if isinstance(reference, str):
            self._prepared_inputs.pop(reference, None)

    async def sync_authority_snapshot(self, budget: RemainingBudget) -> None:
        """Push the current host-owned remaining budget to the private bridge."""

        if self._closed or type(budget) is not RemainingBudget:
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "authority.update",
            "budget": {
                "controller_tokens": budget.controller_tokens,
                "application_tokens": budget.application_tokens,
                "child_tokens": budget.child_tokens,
                "aggregate_tokens": budget.aggregate_tokens,
                "cost_micros": budget.cost_micros,
                "deadline_ms": budget.deadline_ms,
            },
        }
        try:
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        if (
            set(response) != {"protocol", "id", "type"}
            or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
            or response.get("type") != "authority.accepted"
        ):
            raise PrimeControlError()

    async def send(self, command: ControlCommand) -> None:
        if self._closed:
            raise PrimeControlError()
        try:
            envelope = {
                "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
                "id": _request_id(),
                "type": "command.accept",
                "command": command.to_mapping(),
                "private": self._private_for_command(command),
            }
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        if (
            response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
        ):
            raise PrimeControlError()
        if response.get("type") == "error":
            if (
                response.get("code") == "prime-gateway-sidecar-failed"
                and set(response) == {"protocol", "id", "type", "code"}
            ):
                raise PrimeControlError()
            raise PrimeControlError()
        if (
            response.get("type") != "command.accepted"
            or set(response) != {"protocol", "id", "type"}
        ):
            raise PrimeControlError()

    async def execute_session_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        """Use the selected sidecar for one admitted session-context command."""

        if self._closed or not isinstance(command, SessionContextCommand):
            raise PrimeControlError()
        try:
            envelope: dict[str, object] = {
                "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
                "id": _request_id(),
                "type": "session-context.execute",
                "command": command.to_mapping(),
                "private": self._private_for_session_context(command),
            }
            response = await self._process.request(envelope)
            receipt_value = response.get("receipt")
            if (
                set(response) != {"protocol", "id", "type", "receipt"}
                or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
                or response.get("id") != envelope["id"]
                or response.get("type") != "session-context.receipt"
                or not isinstance(receipt_value, Mapping)
            ):
                raise PrimeControlError()
            receipt = SessionContextReceipt.from_mapping(receipt_value)
            if (
                receipt.command_id != command.command_id
                or receipt.session_id != command.session_id
                or receipt.generation != command.generation
                or receipt.operation != command.operation
            ):
                raise PrimeControlError()
            return receipt
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None

    async def cancel_session_context(self, command_id: str) -> None:
        """Request cancellation through the same selected sidecar."""

        if (
            self._closed
            or not isinstance(command_id, str)
            or OPAQUE_ID.fullmatch(command_id) is None
        ):
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "session-context.cancel",
            "command_id": command_id,
        }
        try:
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        if (
            set(response) != {"protocol", "id", "type"}
            or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
            or response.get("type") != "session-context.cancel.accepted"
        ):
            raise PrimeControlError()

    async def execute_long_running(
        self,
        command_id: str,
        command: Mapping[str, object],
    ) -> PrimeLongRunningIpcReceipt:
        """Send one host-authorized exact heartbeat command through private IPC."""

        if (
            self._closed
            or not isinstance(command_id, str)
            or OPAQUE_ID.fullmatch(command_id) is None
        ):
            raise PrimeControlError()
        try:
            validated = validate_prime_long_running_mapping(command)
            envelope: dict[str, object] = {
                "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
                "id": _request_id(),
                "type": "long-running.execute",
                "command_id": command_id,
                "command": validated,
            }
            response = await self._process.request(envelope)
            receipt = response.get("receipt")
            if (
                set(response) != {"protocol", "id", "type", "receipt"}
                or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
                or response.get("id") != envelope["id"]
                or response.get("type") != "long-running.receipt"
                or not isinstance(receipt, Mapping)
                or set(receipt) != {"commandId", "commandDigest", "status"}
            ):
                raise PrimeControlError()
            result = PrimeLongRunningIpcReceipt(
                receipt["commandId"],
                receipt["commandDigest"],
                receipt["status"],
            )
            if result.command_id != command_id:
                raise PrimeControlError()
            return result
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None

    async def rlm_lifecycle(self) -> tuple[RlmLifecycleObservation, ...]:
        """Read the closed, body-free native RLM child lifecycle."""

        if self._closed:
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "rlm.lifecycle.read",
        }
        try:
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        lifecycle = response.get("lifecycle")
        if (
            set(response) != {"protocol", "id", "type", "lifecycle"}
            or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
            or response.get("type") != "rlm.lifecycle.batch"
            or not isinstance(lifecycle, list)
            or len(lifecycle) > 1024
        ):
            raise PrimeControlError()
        active: set[str] = set()
        closed: set[str] = set()
        result: list[RlmLifecycleObservation] = []
        try:
            for item in lifecycle:
                if not isinstance(item, Mapping):
                    raise PrimeControlError()
                item_type = item.get("type")
                child_id = item.get("child_id")
                if not isinstance(child_id, str):
                    raise PrimeControlError()
                if item_type == "rlm.child.started" and set(item) == {
                    "type",
                    "child_id",
                    "native_identity_digest",
                }:
                    observation = RlmLifecycleObservation(
                        item_type,
                        child_id,
                        native_identity_digest=item.get("native_identity_digest"),
                    )
                    if child_id in active:
                        raise PrimeControlError()
                    active.add(child_id)
                elif item_type == "rlm.child.terminal" and set(item) == {
                    "type",
                    "child_id",
                    "status",
                }:
                    observation = RlmLifecycleObservation(
                        item_type, child_id, item.get("status")
                    )
                    if child_id not in active:
                        raise PrimeControlError()
                    active.remove(child_id)
                    closed.add(child_id)
                elif item_type == "rlm.child.deleted" and set(item) == {
                    "type",
                    "child_id",
                }:
                    observation = RlmLifecycleObservation(item_type, child_id)
                    if child_id not in closed:
                        raise PrimeControlError()
                    closed.remove(child_id)
                else:
                    raise PrimeControlError()
                result.append(observation)
        except (TypeError, ValueError):
            raise PrimeControlError() from None
        return tuple(result)

    async def rlm_binding(self, action_id: str) -> RlmAdmissionBinding:
        """Read one exact safe RLM binding prepared before action admission."""

        if (
            self._closed
            or not isinstance(action_id, str)
            or OPAQUE_ID.fullmatch(action_id) is None
        ):
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "rlm.binding.read",
            "action_id": action_id,
        }
        try:
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        binding = response.get("binding")
        if (
            set(response) != {"protocol", "id", "type", "binding"}
            or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
            or response.get("type") != "rlm.binding.value"
            or not isinstance(binding, Mapping)
            or set(binding)
            != {
                "action_id",
                "child_id",
                "authority_revision",
                "depth",
                "model_selector_digest",
            }
        ):
            raise PrimeControlError()
        try:
            result = RlmAdmissionBinding(
                binding["action_id"],
                binding["child_id"],
                binding["authority_revision"],
                binding["depth"],
                binding["model_selector_digest"],
            )
        except (KeyError, TypeError, ValueError):
            raise PrimeControlError() from None
        if result.action_id != action_id:
            raise PrimeControlError()
        return result

    async def rlm_message_binding(self, action_id: str) -> RlmMessageAdmissionBinding:
        """Read one exact body-free native RLM message binding."""

        if (
            self._closed
            or not isinstance(action_id, str)
            or OPAQUE_ID.fullmatch(action_id) is None
        ):
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "rlm.message.binding.read",
            "action_id": action_id,
        }
        try:
            response = await self._process.request(envelope)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None
        binding = response.get("binding")
        if (
            set(response) != {"protocol", "id", "type", "binding"}
            or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
            or response.get("id") != envelope["id"]
            or response.get("type") != "rlm.message.binding.value"
            or not isinstance(binding, Mapping)
            or set(binding)
            != {
                "action_id",
                "authority_revision",
                "body_digest",
                "delivered",
                "message_id",
                "recipient_id",
                "sender_id",
            }
        ):
            raise PrimeControlError()
        try:
            result = RlmMessageAdmissionBinding(
                binding["action_id"],
                binding["message_id"],
                binding["sender_id"],
                binding["recipient_id"],
                binding["authority_revision"],
                binding["body_digest"],
                binding["delivered"],
            )
        except (KeyError, TypeError, ValueError):
            raise PrimeControlError() from None
        if result.action_id != action_id:
            raise PrimeControlError()
        return result

    def bind_action_result(self, receipt: ActionExecutionReceipt) -> None:
        """Remember the public-safe private-result projection for a terminal send."""

        if type(receipt) is not ActionExecutionReceipt:
            raise PrimeControlError()
        projection: Mapping[str, str | list[str]] = {
            "receipt_ref": receipt.receipt_ref,
            "artifact_ids": list(receipt.artifact_ids),
            "media_types": list(receipt.media_types),
        }
        existing = self._result_projections.get(receipt.action_id)
        if existing is not None and existing != projection:
            raise PrimeControlError()
        self._result_projections[receipt.action_id] = projection

    async def events(
        self, cursor: EventCursor | None = None
    ) -> AsyncIterator[ControlEvent]:
        if self._closed:
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "events.stream",
            "cursor": None if cursor is None else cursor.to_mapping(),
        }
        try:
            async for event in self._process.events(envelope):
                control_event = ControlEvent.from_mapping(event)
                if self._event_observer is not None:
                    self._event_observer(control_event)
                yield control_event
        except PrimeSidecarProcessError as error:
            if error.safe_code in {"response-timeout", "sidecar-error", "response-eof", "response-invalid"}:
                raise PrimeControlError(safe_code=error.safe_code) from None
            raise PrimeControlError() from None
        except (ControlProtocolError, TypeError, ValueError):
            raise PrimeControlError(safe_code="event-protocol") from None
        except RuntimeError:
            raise PrimeControlError(safe_code="event-runtime") from None

    def client_observations(
        self, cursor: ClientCursor | None = None
    ) -> AsyncIterator[ClientObservation]:
        """Yield closed client observations from the selected private sidecar."""

        if self._closed or (cursor is not None and not isinstance(cursor, ClientCursor)):
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "client_observations",
            "cursor": None if cursor is None else {
                "generation": cursor.generation,
                "sequence": cursor.sequence,
            },
        }

        async def iterate() -> AsyncIterator[ClientObservation]:
            previous = 0 if cursor is None else cursor.sequence
            generation = None if cursor is None else cursor.generation
            try:
                async for value in self._process.events(envelope):
                    observation = _client_observation_from_mapping(value)
                    if generation is None:
                        generation = observation.generation
                    elif observation.generation != generation:
                        raise PrimeControlError()
                    if observation.source_sequence != previous + 1:
                        raise PrimeControlError()
                    previous = observation.source_sequence
                    await self._remember_client_descriptors(observation)
                    yield observation
            except asyncio.CancelledError:
                raise PrimeControlError() from None
            except (PrimeControlError, TypeError, ValueError, RuntimeError):
                raise PrimeControlError() from None

        return iterate()

    async def client_observation_health(
        self, cursor: ClientCursor | None = None
    ) -> ClientObservationHealth:
        """Read one validated, body-free observation-health snapshot."""

        if self._closed or (cursor is not None and not isinstance(cursor, ClientCursor)):
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "client_observations",
            "cursor": None if cursor is None else {
                "generation": cursor.generation, "sequence": cursor.sequence,
            },
        }
        try:
            response = await self._process.request(envelope)
            if response.get("type") != "client_observations.batch":
                raise ValueError
            health = response.get("health")
            if not isinstance(health, Mapping):
                raise ValueError
            return ClientObservationHealth(
                status=health["status"], reason_code=health["reason_code"],
                observed_through_native_sequence=health["observed_through_native_sequence"],
                first_missing_native_sequence=health["first_missing_native_sequence"],
                resync_required=health["resync_required"],
            )
        except PrimeSidecarProcessError as error:
            if error.safe_code in {"response-timeout", "sidecar-error", "response-eof", "response-invalid"}:
                raise PrimeControlError(safe_code=error.safe_code) from None
            raise PrimeControlError() from None
        except (KeyError, TypeError, ValueError):
            raise PrimeControlError() from None

    def describe(self, reference: str) -> PrivateValueDescriptor:
        """Return a previously observed immutable private-value descriptor."""

        try:
            descriptor = self._client_private_descriptors.get(reference)
        except Exception:
            descriptor = None
        if self._closed or not isinstance(reference, str) or descriptor is None:
            raise PrimeControlError()
        return descriptor

    async def read(self, reference: str, *, max_bytes: int) -> bytes:
        """Read one descriptor-bound private value through the sidecar only."""

        descriptor = self.describe(reference)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise PrimeControlError()
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "client_value_read",
            "reference": reference,
            "max_bytes": max_bytes,
        }
        try:
            response = await self._process.request(envelope)
            body_value = response.get("body_base64")
            response_descriptor = response.get("descriptor")
            if (
                set(response) != {"protocol", "id", "type", "descriptor", "body_base64"}
                or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
                or response.get("id") != envelope["id"]
                or response.get("type") != "client_value"
                or not isinstance(body_value, str)
                or not isinstance(response_descriptor, Mapping)
            ):
                raise PrimeControlError()
            returned = _private_descriptor_from_mapping(response_descriptor)
            body = base64.b64decode(body_value.encode("ascii"), validate=True)
            if (
                returned != descriptor
                or len(body) != descriptor.size
                or len(body) > max_bytes
                or hashlib.sha256(body).hexdigest() != descriptor.sha256
            ):
                raise PrimeControlError()
            return bytes(body)
        except asyncio.CancelledError:
            raise PrimeControlError() from None
        except (PrimeControlError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None

    async def _remember_client_descriptors(self, observation: ClientObservation) -> None:
        payload = observation.payload
        reference_fields = {
            "artifact.available": ("artifact_ref", "artifact", "media_type"),
            "message.available": ("content_ref", "message", "media_type"),
            "tool.completed": ("result_ref", "tool-result", "media_type"),
            "tool.started": ("arguments_ref", "tool-arguments", None),
        }
        binding = reference_fields.get(observation.kind)
        if observation.kind == "extension-ui.requested":
            reference = payload.get("payload_ref")
            if not isinstance(reference, str):
                raise PrimeControlError()
            descriptor = await self._read_extension_descriptor(reference)
            existing = self._client_private_descriptors.get(reference)
            if existing is not None and existing != descriptor:
                raise PrimeControlError()
            self._client_private_descriptors[reference] = descriptor
            return
        if binding is None:
            return
        reference = payload.get(binding[0])
        sha256 = payload.get("sha256")
        size = payload.get("size")
        media_type = payload.get(binding[2]) if binding[2] is not None else "application/json"
        if (
            not isinstance(reference, str)
            or not isinstance(sha256, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not isinstance(media_type, str)
        ):
            raise PrimeControlError()
        descriptor = PrivateValueDescriptor(reference, binding[1], media_type, size, sha256)
        existing = self._client_private_descriptors.get(reference)
        if existing is not None and existing != descriptor:
            raise PrimeControlError()
        self._client_private_descriptors[reference] = descriptor

    async def _read_extension_descriptor(
        self, reference: str
    ) -> PrivateValueDescriptor:
        envelope: dict[str, object] = {
            "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
            "id": _request_id(),
            "type": "client_value_read",
            "reference": reference,
            "max_bytes": 700 * 1024,
        }
        try:
            response = await self._process.request(envelope)
            if (
                set(response) != {"protocol", "id", "type", "descriptor", "body_base64"}
                or response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
                or response.get("id") != envelope["id"]
                or response.get("type") != "client_value"
                or not isinstance(response.get("descriptor"), Mapping)
                or not isinstance(response.get("body_base64"), str)
            ):
                raise PrimeControlError()
            response_descriptor = response["descriptor"]
            body_base64 = response["body_base64"]
            if not isinstance(response_descriptor, Mapping) or not isinstance(body_base64, str):
                raise PrimeControlError()
            descriptor = _private_descriptor_from_mapping(response_descriptor)
            body = base64.b64decode(body_base64.encode("ascii"), validate=True)
            if (
                descriptor.reference != reference
                or descriptor.kind != "extension-ui"
                or descriptor.media_type != "application/json"
                or len(body) != descriptor.size
                or hashlib.sha256(body).hexdigest() != descriptor.sha256
            ):
                raise PrimeControlError()
            return descriptor
        except asyncio.CancelledError:
            raise PrimeControlError() from None
        except (PrimeControlError, TypeError, ValueError, RuntimeError):
            raise PrimeControlError() from None

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            if self._close_task is None or self._close_task.done():
                self._close_task = asyncio.create_task(self._process.close())
            close_task = self._close_task
        try:
            await close_task
        except RuntimeError:
            async with self._close_lock:
                if self._close_task is close_task:
                    self._close_task = None
            raise PrimeControlError() from None
        async with self._close_lock:
            if self._close_task is close_task:
                self._closed = True
                self._close_task = None

    def _private_for_command(self, command: ControlCommand) -> Mapping[str, str]:
        if command.type == "session.create":
            reference = command.payload["goal_ref"]
            if not isinstance(reference, str):
                raise PrimeControlError()
            return {
                "goal": self._private_content.resolve_text(
                    reference, max_bytes=MAX_PRIVATE_TEXT_BYTES
                )
            }
        if command.type == "input.submit":
            reference = command.payload["content_ref"]
            if not isinstance(reference, str):
                raise PrimeControlError()
            return {
                "content": self._private_content.resolve_text(
                    reference, max_bytes=MAX_PRIVATE_TEXT_BYTES
                )
            }
        if command.type == "action.resolve":
            if command.payload["resolution"] != "succeeded":
                return {}
            receipt_ref = command.payload["receipt_ref"]
            if receipt_ref is None:
                raise PrimeControlError()
            action_id = command.payload["action_id"]
            if not isinstance(action_id, str) or not isinstance(receipt_ref, str):
                raise PrimeControlError()
            projection = self._result_projections.get(action_id)
            if projection is None or projection.get("receipt_ref") != receipt_ref:
                raise PrimeControlError()
            return {"result": projection}  # type: ignore[return-value]
        return {}

    def _private_for_session_context(
        self,
        command: SessionContextCommand,
    ) -> Mapping[str, object]:
        payload = command.payload
        if command.operation == "session.attachment.bind":
            resolver = getattr(self._private_attachments, "resolve_bytes", None)
            if not callable(resolver):
                raise PrimeControlError()
            reference = payload["body_ref"]
            media_type = payload["media_type"]
            expected_sha256 = payload["sha256"]
            expected_size = payload["size"]
            if (
                not isinstance(reference, str)
                or not isinstance(media_type, str)
                or not isinstance(expected_sha256, str)
                or isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
            ):
                raise PrimeControlError()
            body = resolver(
                reference,
                expected_media_type=media_type,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                max_bytes=MAX_PRIVATE_ATTACHMENT_BYTES,
            )
            if (
                type(body) is not bytes
                or len(body) != expected_size
                or len(body) > MAX_PRIVATE_ATTACHMENT_BYTES
                or hashlib.sha256(body).hexdigest() != expected_sha256
            ):
                raise PrimeControlError()
            return {"body_base64": base64.b64encode(body).decode("ascii")}
        if command.operation == "session.name.set":
            return {"name": self._resolve_context_text(payload["name_ref"])}
        if command.operation == "session.label.set":
            reference = payload["label_ref"]
            return {} if reference is None else {
                "label": self._resolve_context_text(reference)
            }
        if command.operation in {
            "session.branch.summarize",
            "session.compact",
        }:
            reference = payload["instructions_ref"]
            return {} if reference is None else {
                "instructions": self._resolve_context_text(reference)
            }
        return {}

    def _resolve_context_text(self, reference: object) -> str:
        if not isinstance(reference, str):
            raise PrimeControlError()
        value = self._private_content.resolve_text(
            reference,
            max_bytes=MAX_PRIVATE_TEXT_BYTES,
        )
        if (
            not isinstance(value, str)
            or len(value.encode("utf-8")) > MAX_PRIVATE_TEXT_BYTES
        ):
            raise PrimeControlError()
        return value

    def _cache_private_input(self, reference: str, text: str) -> None:
        if (
            not isinstance(reference, str)
            or not isinstance(text, str)
            or len(text.encode("utf-8")) > MAX_PRIVATE_TEXT_BYTES
        ):
            raise PrimeControlError()
        self._prepared_inputs[reference] = text
        self._prepared_inputs.move_to_end(reference)
        while len(self._prepared_inputs) > MAX_PREPARED_PRIVATE_INPUTS:
            self._prepared_inputs.popitem(last=False)


def _client_observation_from_mapping(value: Mapping[str, object]) -> ClientObservation:
    if set(value) != {
        "observation_id",
        "active_session_id",
        "generation",
        "source_sequence",
        "emitted_at",
        "kind",
        "payload",
    }:
        raise PrimeControlError()
    try:
        active_session_id = value["active_session_id"]
        payload = value["payload"]
        observation_id = value["observation_id"]
        generation = value["generation"]
        source_sequence = value["source_sequence"]
        emitted_at = value["emitted_at"]
        kind = value["kind"]
        if (
            not isinstance(active_session_id, str)
            or not isinstance(payload, Mapping)
            or not isinstance(observation_id, str)
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or isinstance(source_sequence, bool)
            or not isinstance(source_sequence, int)
            or not isinstance(emitted_at, str)
            or not isinstance(kind, str)
        ):
            raise PrimeControlError()
        return ClientObservation(
            observation_id=observation_id,
            session_id=active_session_id,
            generation=generation,
            source_sequence=source_sequence,
            emitted_at=emitted_at,
            kind=kind,
            payload=payload,
        )
    except (KeyError, TypeError, ValueError):
        raise PrimeControlError() from None


def _private_descriptor_from_mapping(value: Mapping[str, object]) -> PrivateValueDescriptor:
    if set(value) != {"reference", "kind", "media_type", "size", "sha256"}:
        raise PrimeControlError()
    try:
        reference = value["reference"]
        kind = value["kind"]
        media_type = value["media_type"]
        size = value["size"]
        sha256 = value["sha256"]
        if (
            not isinstance(reference, str)
            or not isinstance(kind, str)
            or not isinstance(media_type, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not isinstance(sha256, str)
        ):
            raise PrimeControlError()
        return PrivateValueDescriptor(
            reference, kind, media_type, size, sha256
        )
    except (KeyError, TypeError, ValueError):
        raise PrimeControlError() from None


def _request_id() -> str:
    return f"request-{uuid.uuid4().hex}"


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _load_manifest() -> ControlPlaneManifest:
    try:
        path = Path(__file__).resolve().parent / "resources" / "control-plane.json"
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        raise PrimeControlError() from None
    if not isinstance(value, Mapping):
        raise PrimeControlError()
    return ControlPlaneManifest.from_mapping(value)
