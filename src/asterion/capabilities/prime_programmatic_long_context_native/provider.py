"""Exact implementation binding for native Prime P2 programmatic long context."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
import re

from asterion.capability_sdk import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)
from asterion.runtime.host import RunRequest, parse_event_stream


PACKAGE_REF = CapabilityPackageRef("prime-programmatic-long-context-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.programmatic-long-context", "1.0.0")
P2_INPUT_PRESET = "fixed-small-verification"
P2_ARTIFACT_ID = "prime.p2-native.receipt"
P2_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p2-native-receipt+json"
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PrimeProgrammaticLongContextNativeImplementation:
    """Run the fixed native preset and expose only its receipt digest."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if (
            invocation.runtime.manifest.runtime_id != "asterion.prime"
            or invocation.runtime.manifest.capabilities != ("prime.tool.ipython",)
            or invocation.input_text != P2_INPUT_PRESET
        ):
            raise CapabilityExecutionError("Prime P2 runtime is unavailable")
        events = tuple(
            [
                event
                async for event in invocation.runtime.run(
                    RunRequest(
                        run_id=invocation.run_id,
                        input_text=invocation.input_text,
                        requested_capabilities=("prime.tool.ipython",),
                        deadline_ms=600_000,
                    ),
                    signal=invocation.signal,
                )
            ]
        )
        try:
            parsed_stream = parse_event_stream(
                event.to_mapping() for event in events
            )
        except Exception:
            raise CapabilityExecutionError(
                "Prime P2 runtime result is invalid"
            ) from None
        if any(event.run_id != invocation.run_id for event in parsed_stream):
            raise CapabilityExecutionError("Prime P2 runtime result is invalid")
        public = tuple(event for event in parsed_stream if event.type != "usage.reported")
        if parsed_stream[-1].type == "run.completed" and parsed_stream[-1].payload == {
            "status": "cancelled"
        }:
            if (
                len(public) != 2
                or tuple(event.type for event in public)
                != ("run.started", "run.completed")
                or public[0].payload != {"capabilities": ["prime.tool.ipython"]}
            ):
                raise CapabilityExecutionError("Prime P2 runtime result is invalid")
            raise asyncio.CancelledError()
        if (
            len(public) != 3
            or tuple(event.type for event in public)
            != ("run.started", "artifact.created", "run.completed")
            or public[0].payload != {"capabilities": ["prime.tool.ipython"]}
            or public[-1].payload != {"status": "completed"}
        ):
            raise CapabilityExecutionError("Prime P2 runtime did not complete")
        artifact = public[1].payload.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact
            != {
                "artifact_id": P2_ARTIFACT_ID,
                "kind": "p2-native",
                "media_type": P2_RECEIPT_MEDIA_TYPE,
                "sha256": artifact.get("sha256"),
            }
            or _DIGEST.fullmatch(str(artifact.get("sha256"))) is None
        ):
            raise CapabilityExecutionError("Prime P2 runtime result is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": P2_ARTIFACT_ID,
                    "media_type": P2_RECEIPT_MEDIA_TYPE,
                    "value": {
                        "scope": "p2-native",
                        "promotion": "unpromoted",
                        "receipt_sha256": artifact["sha256"],
                    },
                },
            ),
        )


def create_prime_programmatic_long_context_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-programmatic-long-context-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF, PrimeProgrammaticLongContextNativeImplementation()
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "P2_ARTIFACT_ID",
    "P2_INPUT_PRESET",
    "P2_RECEIPT_MEDIA_TYPE",
    "PACKAGE_REF",
    "PrimeProgrammaticLongContextNativeImplementation",
    "create_prime_programmatic_long_context_native_package",
)