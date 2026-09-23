"""Validate a selected Prime runtime round before exposing its receipt."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.runtime.host import RunRequest, parse_event_stream


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PrimeNativeReceiptImplementation:
    capability_ref: CapabilityRef
    input_preset: str
    artifact_id: str
    media_type: str
    kind: str
    deadline_ms: int

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if (
            invocation.capability_ref != self.capability_ref
            or invocation.runtime.manifest.runtime_id != "asterion.prime"
            or invocation.input_text != self.input_preset
        ):
            raise CapabilityExecutionError("Prime native runtime is unavailable")
        events = tuple(
            [
                event
                async for event in invocation.runtime.run(
                    RunRequest(
                        run_id=invocation.run_id,
                        input_text=invocation.input_text,
                        requested_capabilities=(),
                        deadline_ms=self.deadline_ms,
                    ),
                    signal=invocation.signal,
                )
            ]
        )
        try:
            stream = parse_event_stream(event.to_mapping() for event in events)
        except Exception:
            raise CapabilityExecutionError("Prime native runtime result is invalid") from None
        if any(event.run_id != invocation.run_id for event in stream):
            raise CapabilityExecutionError("Prime native runtime result is invalid")
        if (
            len(stream) == 2
            and tuple(event.type for event in stream) == ("run.started", "run.completed")
            and stream[0].payload == {"capabilities": []}
            and stream[1].payload == {"status": "cancelled"}
        ):
            raise asyncio.CancelledError()
        if (
            len(stream) != 3
            or tuple(event.type for event in stream)
            != ("run.started", "artifact.created", "run.completed")
            or stream[0].payload != {"capabilities": []}
            or stream[2].payload != {"status": "completed"}
        ):
            raise CapabilityExecutionError("Prime native runtime did not complete")
        artifact = stream[1].payload.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact
            != {
                "artifact_id": self.artifact_id,
                "kind": self.kind,
                "media_type": self.media_type,
                "sha256": artifact.get("sha256"),
            }
            or _DIGEST.fullmatch(str(artifact.get("sha256"))) is None
        ):
            raise CapabilityExecutionError("Prime native runtime result is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": self.artifact_id,
                    "media_type": self.media_type,
                    "value": {
                        "scope": self.kind,
                        "promotion": "unpromoted",
                        "receipt_sha256": artifact["sha256"],
                    },
                },
            ),
        )


__all__ = ("PrimeNativeReceiptImplementation",)
