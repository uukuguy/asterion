"""Exact installed package binding for Prime's P1 coding capability."""

from __future__ import annotations

import asyncio
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
from asterion.runtime.host import RunRequest
from asterion.runtime.host import parse_event_stream


PACKAGE_REF = CapabilityPackageRef("prime-agent", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.ipython-coding", "1.0.0")


_TRACE_ARTIFACT_ID = "prime.p1-b-development.trace"
_TRACE_MEDIA_TYPE = "application/vnd.asterion.prime.p1-development-trace+json"
_TRACE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PrimeIpythonCodingImplementation:
    """Project only the public-safe trace from Prime's fixed verification."""

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityExecutionResult:
        if invocation.runtime.manifest.runtime_id != "prime.agent" or (
            invocation.runtime.manifest.capabilities != ("prime.tool.ipython",)
        ):
            raise CapabilityExecutionError("Prime runtime is unavailable")
        if invocation.input_text != "fixed-small-verification":
            raise CapabilityExecutionError("Prime capability input is invalid")
        events = tuple([
            event
            async for event in invocation.runtime.run(
                RunRequest(
                    run_id=invocation.run_id,
                    input_text=invocation.input_text,
                    requested_capabilities=("prime.tool.ipython",),
                ),
                signal=invocation.signal,
            )
        ])
        try:
            parsed = parse_event_stream(event.to_mapping() for event in events)
        except Exception as error:
            raise CapabilityExecutionError("Prime runtime result is invalid") from error
        if any(event.run_id != invocation.run_id for event in parsed):
            raise CapabilityExecutionError("Prime runtime result is invalid")
        if (
            len(parsed) == 2
            and tuple(event.type for event in parsed)
            == ("run.started", "run.completed")
            and parsed[0].payload == {"capabilities": ["prime.tool.ipython"]}
            and parsed[-1].payload == {"status": "cancelled"}
        ):
            raise asyncio.CancelledError
        if (
            len(parsed) != 3
            or tuple(event.type for event in parsed)
            != ("run.started", "artifact.created", "run.completed")
            or parsed[0].payload != {"capabilities": ["prime.tool.ipython"]}
        ):
            raise CapabilityExecutionError("Prime runtime did not complete")
        if parsed[-1].payload != {"status": "completed"}:
            raise CapabilityExecutionError("Prime runtime did not complete")
        artifact = parsed[1].payload.get("artifact")
        if not isinstance(artifact, dict) or artifact != {
            "artifact_id": _TRACE_ARTIFACT_ID,
            "kind": "p1-b-development",
            "media_type": _TRACE_MEDIA_TYPE,
            "sha256": artifact.get("sha256"),
        } or _TRACE_SHA256.fullmatch(str(artifact.get("sha256"))) is None:
            raise CapabilityExecutionError("Prime runtime result is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": _TRACE_ARTIFACT_ID,
                    "media_type": _TRACE_MEDIA_TYPE,
                    "value": {
                        "scope": "p1-b-development",
                        "promotion": "unpromoted",
                        "trace_sha256": artifact["sha256"],
                    },
                },
            ),
        )


def create_prime_agent_package() -> InstalledCapabilityPackage:
    """Load the exact local Prime package payload and its one implementation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-agent.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(CAPABILITY_REF, PrimeIpythonCodingImplementation()),
        ),
        benchmark_bindings=(),
    )


__all__ = ("create_prime_agent_package",)
