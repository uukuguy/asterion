"""Host-side client for the exact Prime control-plane provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Protocol

from asterion.control.authority import RemainingBudget
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
from asterion.control.providers.prime.process import PRIME_GATEWAY_IPC_PROTOCOL


MAX_PRIVATE_TEXT_BYTES = 1024 * 1024
MAX_PRIVATE_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_PREPARED_PRIVATE_INPUTS = 128


class PrimeControlError(RuntimeError):
    """Raised when Prime cannot safely accept or replay a control operation."""

    def __init__(self, message: str = "Prime control operation failed") -> None:
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
    ) -> None:
        if not hasattr(private_content, "resolve_text"):
            raise PrimeControlError()
        self._process = process
        self._private_content = private_content
        self._private_attachments = private_attachments
        self._manifest = manifest or _load_manifest()
        self._closed = False
        self._result_projections: dict[
            str, Mapping[str, str | list[str]]
        ] = {}
        self._prepared_inputs: OrderedDict[str, str] = OrderedDict()
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

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
                yield ControlEvent.from_mapping(event)
        except (ControlProtocolError, TypeError, ValueError, RuntimeError):
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


def _request_id() -> str:
    return f"request-{uuid.uuid4().hex}"


def _load_manifest() -> ControlPlaneManifest:
    try:
        path = Path(__file__).resolve().parent / "resources" / "control-plane.json"
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        raise PrimeControlError() from None
    if not isinstance(value, Mapping):
        raise PrimeControlError()
    return ControlPlaneManifest.from_mapping(value)
