"""Programmatic adapter over one injected client-session endpoint."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from asterion.client.protocol import ClientCursor, ClientEvent, ClientIntent
from asterion.client.session import ClientSessionEndpoint


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AgentClientError(ValueError):
    """Raised when the SDK request is not owned by this client."""


class AgentClient:
    """A provider-neutral SDK over an already-created client session."""

    def __init__(self, endpoint: ClientSessionEndpoint, *, client_id: str) -> None:
        _require_client_id(client_id)
        self._endpoint = endpoint
        self._client_id = client_id

    async def submit(self, intent: ClientIntent) -> str:
        if not isinstance(intent, ClientIntent) or intent.client_id != self._client_id:
            raise AgentClientError("client intent identity mismatches")
        return await self._endpoint.submit(intent)

    async def submit_input(
        self,
        *,
        session_id: str,
        authority_revision: int,
        input_id: str,
        content_ref: str,
        delivery: str,
    ) -> str:
        """Submit one body-free input request using its stable input identity."""

        return await self.submit(
            ClientIntent(
                protocol="asterion.agent-client/v1",
                intent_id=input_id,
                client_id=self._client_id,
                session_id=session_id,
                authority_revision=authority_revision,
                type="input.submit",
                payload={
                    "content_ref": content_ref,
                    "delivery": delivery,
                    "input_id": input_id,
                },
            )
        )

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        return self._endpoint.events(cursor)

    def resolve_text(
        self, reference: str, *, purpose: str, max_bytes: int, deadline_ms: int
    ) -> str:
        return self._endpoint.private_values.resolve_text(
            reference, purpose=purpose, max_bytes=max_bytes, deadline_ms=deadline_ms
        )

    async def close(self) -> None:
        await self._endpoint.close()


def _require_client_id(value: object) -> None:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise AgentClientError("client identity is invalid")
