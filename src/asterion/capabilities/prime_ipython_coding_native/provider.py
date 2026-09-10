"""Exact implementation binding for native Prime P1 coding."""

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


PACKAGE_REF = CapabilityPackageRef("prime-ipython-coding-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.ipython-coding", "1.0.0")
P1_INPUT_PRESET = "fixed-small-verification"
P1_ARTIFACT_ID = "prime.p1-native.receipt"
P1_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p1-native-receipt+json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PrimeIpythonCodingNativeImplementation:
    """Run the fixed native preset and expose only its receipt digest."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if (
            invocation.runtime.manifest.runtime_id != "asterion.prime"
            or invocation.runtime.manifest.capabilities != ("prime.tool.ipython",)
            or invocation.input_text != P1_INPUT_PRESET
        ):
            raise CapabilityExecutionError("Prime P1 runtime is unavailable")
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
            parsed = parse_event_stream(event.to_mapping() for event in events)
        except Exception:
            raise CapabilityExecutionError(
                "Prime P1 runtime result is invalid"
            ) from None
        if any(event.run_id != invocation.run_id for event in parsed):
            raise CapabilityExecutionError("Prime P1 runtime result is invalid")
        public = tuple(event for event in parsed if event.type != "usage.reported")
        if parsed[-1].type == "run.completed" and parsed[-1].payload == {
            "status": "cancelled"
        }:
            if (
                len(public) != 2
                or tuple(event.type for event in public)
                != ("run.started", "run.completed")
                or public[0].payload != {"capabilities": ["prime.tool.ipython"]}
            ):
                raise CapabilityExecutionError("Prime P1 runtime result is invalid")
            raise asyncio.CancelledError()
        if (
            len(public) != 3
            or tuple(event.type for event in public)
            != ("run.started", "artifact.created", "run.completed")
            or public[0].payload != {"capabilities": ["prime.tool.ipython"]}
            or public[-1].payload != {"status": "completed"}
        ):
            raise CapabilityExecutionError("Prime P1 runtime did not complete")
        artifact = public[1].payload.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact
            != {
                "artifact_id": P1_ARTIFACT_ID,
                "kind": "p1-native",
                "media_type": P1_RECEIPT_MEDIA_TYPE,
                "sha256": artifact.get("sha256"),
            }
            or _DIGEST.fullmatch(str(artifact.get("sha256"))) is None
        ):
            raise CapabilityExecutionError("Prime P1 runtime result is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": P1_ARTIFACT_ID,
                    "media_type": P1_RECEIPT_MEDIA_TYPE,
                    "value": {
                        "scope": "p1-native",
                        "promotion": "unpromoted",
                        "receipt_sha256": artifact["sha256"],
                    },
                },
            ),
        )


def create_prime_ipython_coding_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-ipython-coding-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF, PrimeIpythonCodingNativeImplementation()
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "P1_ARTIFACT_ID",
    "P1_INPUT_PRESET",
    "P1_RECEIPT_MEDIA_TYPE",
    "PrimeIpythonCodingNativeImplementation",
    "create_prime_ipython_coding_native_package",
)
