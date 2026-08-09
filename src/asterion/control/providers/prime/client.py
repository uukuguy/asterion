"""Host-side client for the exact Prime control-plane provider."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Protocol

from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.protocol import ControlProtocolError
from asterion.control.providers.prime.process import PRIME_GATEWAY_IPC_PROTOCOL


MAX_PRIVATE_TEXT_BYTES = 1024 * 1024


class PrimeControlError(RuntimeError):
    """Raised when Prime cannot safely accept or replay a control operation."""

    def __init__(self, message: str = "Prime control operation failed") -> None:
        super().__init__(message)


class PrivateContentResolver(Protocol):
    """Host-owned resolver for private prompt/input references."""

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        """Resolve a private text reference without exposing it publicly."""


class PrimeSidecarTransport(Protocol):
    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        """Send one request and return one validated sidecar response."""

    def events(
        self, envelope: Mapping[str, object]
    ) -> AsyncIterator[Mapping[str, object]]:
        """Yield public event mappings from the sidecar."""

    async def close(self) -> None:
        """Release the sidecar resources."""


class PrimeControlPlaneClient:
    """ControlPlaneClient implementation backed by the private Prime sidecar."""

    def __init__(
        self,
        *,
        process: PrimeSidecarTransport,
        private_content: PrivateContentResolver,
        manifest: ControlPlaneManifest | None = None,
    ) -> None:
        if not hasattr(private_content, "resolve_text"):
            raise PrimeControlError()
        self._process = process
        self._private_content = private_content
        self._manifest = manifest or _load_manifest()
        self._closed = False

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

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
            or response.get("type") != "command.accepted"
            or set(response) != {"protocol", "id", "type"}
        ):
            raise PrimeControlError()

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
        if self._closed:
            return
        self._closed = True
        try:
            await self._process.close()
        except RuntimeError:
            raise PrimeControlError() from None

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
        return {}


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
