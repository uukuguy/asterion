"""Read one Prime runtime receipt. The caller owns the runtime session."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from asterion.runtime.host import CancellationSignal, RunRequest
from asterion.runtime.protocol import ProtocolError


async def consume_prime_receipt(
    runtime: object,
    request: RunRequest,
    signal: CancellationSignal | None = None,
) -> str:
    """Drain one runtime session and return the receipt digest it emitted."""

    digest: str | None = None
    cancelled = False
    async for event in runtime.run(request, signal=signal):  # type: ignore[attr-defined]
        payload = event.payload
        if event.type == "artifact.created" and isinstance(payload, Mapping):
            artifact = payload.get("artifact")
            value = artifact.get("sha256") if isinstance(artifact, Mapping) else None
            if type(value) is str and digest is None:
                digest = value
        elif (
            event.type == "run.completed"
            and isinstance(payload, Mapping)
            and payload.get("status") == "cancelled"
        ):
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError()
    if digest is None:
        raise ProtocolError("Prime runtime receipt is unavailable")
    return digest


__all__ = ("consume_prime_receipt",)
