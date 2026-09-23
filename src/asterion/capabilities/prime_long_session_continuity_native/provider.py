"""Exact implementation binding for native Prime P4 long-session-continuity."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from dataclasses import dataclass
import re

from asterion.capability_sdk import (
    CapabilityImplementationBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.runtime.host import RunRequest, parse_event_stream


PACKAGE_REF = CapabilityPackageRef("prime-long-session-continuity-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.long-session-continuity", "1.0.0")
P4_INPUT_PRESET = "fixed-cross-generation-continuity"
P4_ARTIFACT_ID = "prime.p4-native.receipt"
P4_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p4-native-receipt+json"


@dataclass(frozen=True, slots=True)
class _P4ReceiptImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if (
            invocation.capability_ref != CAPABILITY_REF
            or invocation.input_text != P4_INPUT_PRESET
        ):
            raise CapabilityExecutionError("P4 native runtime is unavailable")
        events = tuple(
            [
                event
                async for event in invocation.runtime.run(
                    RunRequest(
                        invocation.run_id,
                        invocation.input_text,
                        requested_capabilities=("prime.tool.ipython",),
                        deadline_ms=120_000,
                    ),
                    signal=invocation.signal,
                )
            ]
        )
        stream = parse_event_stream(event.to_mapping() for event in events)
        if (
            len(stream) != 4
            or tuple(event.type for event in stream)
            != ("run.started", "usage.reported", "artifact.created", "run.completed")
            or stream[0].payload.get("capabilities") != ["prime.tool.ipython"]
            or stream[3].payload != {"status": "completed"}
        ):
            raise CapabilityExecutionError("P4 native runtime did not complete")
        artifact = stream[2].payload.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("artifact_id") != P4_ARTIFACT_ID
            or artifact.get("kind") != "p4-native"
            or artifact.get("media_type") != P4_RECEIPT_MEDIA_TYPE
            or re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256"))) is None
        ):
            raise CapabilityExecutionError("P4 native runtime result is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": P4_ARTIFACT_ID,
                    "media_type": P4_RECEIPT_MEDIA_TYPE,
                    "value": {
                        "scope": "p4-native",
                        "promotion": "unpromoted",
                        "receipt_sha256": artifact["sha256"],
                    },
                },
            ),
        )


def create_prime_long_session_continuity_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-long-session-continuity-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF,
                _P4ReceiptImplementation(),
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "PACKAGE_REF",
    "P4_ARTIFACT_ID",
    "P4_INPUT_PRESET",
    "P4_RECEIPT_MEDIA_TYPE",
    "create_prime_long_session_continuity_native_package",
)
