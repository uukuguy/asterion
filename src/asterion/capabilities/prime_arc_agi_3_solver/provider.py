"""Exact implementation binding for the independent P7 solving package."""

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

from .host import (
    PrimeArcAgi3SolveReceiptAccessor,
    validate_prime_arc_agi_3_solve_receipt,
)


PACKAGE_REF = CapabilityPackageRef("prime-arc-agi-3-solver", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.arc-agi-3-solving", "1.0.0")
_ARTIFACT_ID = "prime.p7-solving.receipt"
_MEDIA_TYPE = "application/vnd.asterion.prime.p7-solving-receipt+json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PrimeArcAgi3SolvingImplementation:
    """Run the fixed preset and project only its sealed receipt fields."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if (
            invocation.runtime.manifest.runtime_id != "asterion.prime"
            or invocation.runtime.manifest.capabilities != ("prime.tool.ipython",)
            or type(invocation.input_text) is not str
            or not invocation.input_text.strip()
            or invocation.input_text == "solve-first-public-level"
        ):
            raise CapabilityExecutionError("Prime solver runtime is unavailable")
        events = tuple(
            [
                event
                async for event in invocation.runtime.run(
                    RunRequest(
                        run_id=invocation.run_id,
                        input_text=invocation.input_text,
                        requested_capabilities=("prime.tool.ipython",),
                    ),
                    signal=invocation.signal,
                )
            ]
        )
        try:
            parsed = parse_event_stream(event.to_mapping() for event in events)
        except Exception as error:
            raise CapabilityExecutionError(
                "Prime solver runtime result is invalid"
            ) from error
        if any(event.run_id != invocation.run_id for event in parsed):
            raise CapabilityExecutionError("Prime solver runtime result is invalid")
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
            or parsed[-1].payload != {"status": "completed"}
        ):
            raise CapabilityExecutionError("Prime solver runtime did not complete")
        artifact = parsed[1].payload.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact
            != {
                "artifact_id": _ARTIFACT_ID,
                "kind": "p7-solving",
                "media_type": _MEDIA_TYPE,
                "sha256": artifact.get("sha256"),
            }
            or _DIGEST.fullmatch(str(artifact.get("sha256"))) is None
        ):
            raise CapabilityExecutionError("Prime solver runtime result is invalid")
        digest = "sha256:" + artifact["sha256"]
        accessor = invocation.host_services.get("prime.private-trace")
        if not isinstance(accessor, PrimeArcAgi3SolveReceiptAccessor):
            raise CapabilityExecutionError(
                "Prime solver receipt accessor is unavailable"
            )
        try:
            receipt = accessor.get_receipt(
                run_id=invocation.run_id, receipt_sha256=digest
            )
            validate_prime_arc_agi_3_solve_receipt(receipt)
        except Exception as error:
            raise CapabilityExecutionError("Prime solver receipt is invalid") from error
        if receipt.run_id != invocation.run_id or receipt.receipt_sha256 != digest:
            raise CapabilityExecutionError("Prime solver receipt is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": _ARTIFACT_ID,
                    "media_type": _MEDIA_TYPE,
                    "value": {
                        "scope": receipt.scope,
                        "promotion": receipt.promotion,
                        "receipt_sha256": receipt.receipt_sha256.removeprefix(
                            "sha256:"
                        ),
                        "completed_level_count": receipt.completed_level_count,
                        "primitive_action_count": receipt.primitive_action_count,
                        "partial_game_score": receipt.partial_game_score,
                    },
                },
            ),
        )


def create_prime_arc_agi_3_solver_package() -> InstalledCapabilityPackage:
    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-arc-agi-3-solver.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF, PrimeArcAgi3SolvingImplementation()
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = ("PrimeArcAgi3SolvingImplementation", "create_prime_arc_agi_3_solver_package")
