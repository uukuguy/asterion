"""Record a Prime receipt citation without executing Prime."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CITATION_KEYS = frozenset({"media_type", "run_id", "sha256"})


@dataclass(frozen=True, slots=True)
class PrimeNativeReceiptImplementation:
    capability_ref: CapabilityRef
    artifact_id: str
    media_type: str

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if invocation.signal is not None and invocation.signal.cancelled:
            raise asyncio.CancelledError()
        if invocation.capability_ref != self.capability_ref:
            raise CapabilityExecutionError("Prime receipt citation is invalid")
        citation = _citation(invocation.input_text, invocation.run_id, self.media_type)
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": self.artifact_id,
                    "media_type": self.media_type,
                    "value": citation,
                },
            ),
        )


def _citation(text: str, run_id: str, media_type: str) -> dict[str, str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise CapabilityExecutionError("Prime receipt citation is invalid") from None
    if (
        type(payload) is not dict
        or set(payload) != _CITATION_KEYS
        or any(type(payload[key]) is not str for key in _CITATION_KEYS)
    ):
        raise CapabilityExecutionError("Prime receipt citation is invalid")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if (
        canonical != text
        or payload["media_type"] != media_type
        or payload["run_id"] != run_id
        or payload["run_id"] == ""
        or _DIGEST.fullmatch(payload["sha256"]) is None
    ):
        raise CapabilityExecutionError("Prime receipt citation is invalid")
    return {
        "media_type": payload["media_type"],
        "run_id": payload["run_id"],
        "sha256": payload["sha256"],
    }


__all__ = ("PrimeNativeReceiptImplementation",)
