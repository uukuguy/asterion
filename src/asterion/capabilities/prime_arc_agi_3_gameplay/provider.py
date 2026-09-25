"""Exact implementation binding for the independent P7 gameplay-run package."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from hashlib import sha256
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
    PrimeArcAgi3GameplayEvidenceAccessor,
    validate_prime_arc_agi_3_gameplay_evidence,
)


PACKAGE_REF = CapabilityPackageRef("prime-arc-agi-3-gameplay", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.arc-agi-3-gameplay", "1.0.0")
_ARTIFACT_ID = "prime.p7-gameplay-run.evidence"
_MEDIA_TYPE = "application/vnd.asterion.prime.p7-gameplay-run+json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PROMPT_DOMAIN = b"asterion.prime-p7-solve-prompt/v1\0"
P7_SOLVE_PROMPT_SHA256 = (
    "4aac8a4883ee7a9855a2694672f0ceaf0da994295ea2b4c839498658317a7a8c"
)


def _matches_p7_prompt(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        digest = sha256(_PROMPT_DOMAIN + value.encode("utf-8", "strict")).hexdigest()
    except UnicodeError:
        return False
    return digest == P7_SOLVE_PROMPT_SHA256


class PrimeArcAgi3GameplayImplementation:
    """Run the fixed preset and project only its sealed evidence fields."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        if (
            invocation.runtime.manifest.runtime_id != "asterion.prime"
            or invocation.runtime.manifest.capabilities != ("prime.tool.ipython",)
            or not _matches_p7_prompt(invocation.input_text)
        ):
            raise CapabilityExecutionError("Prime gameplay runtime is unavailable")
        accessor = invocation.host_services.get("prime.arc-run-evidence")
        if not isinstance(accessor, PrimeArcAgi3GameplayEvidenceAccessor):
            raise CapabilityExecutionError(
                "Prime gameplay evidence accessor is unavailable"
            )
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
        except Exception:
            raise CapabilityExecutionError(
                "Prime gameplay runtime result is invalid"
            ) from None
        if any(event.run_id != invocation.run_id for event in parsed):
            raise CapabilityExecutionError("Prime gameplay runtime result is invalid")
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
            raise CapabilityExecutionError("Prime gameplay runtime did not complete")
        artifact = parsed[1].payload.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact
            != {
                "artifact_id": _ARTIFACT_ID,
                "kind": "p7-gameplay-run",
                "media_type": _MEDIA_TYPE,
                "sha256": artifact.get("sha256"),
            }
            or _DIGEST.fullmatch(str(artifact.get("sha256"))) is None
        ):
            raise CapabilityExecutionError("Prime gameplay runtime result is invalid")
        digest = "sha256:" + artifact["sha256"]
        try:
            evidence = accessor.get_evidence(
                run_id=invocation.run_id, evidence_sha256=digest
            )
            validate_prime_arc_agi_3_gameplay_evidence(evidence)
        except Exception:
            raise CapabilityExecutionError(
                "Prime gameplay evidence is invalid"
            ) from None
        if evidence.run_id != invocation.run_id or evidence.evidence_sha256 != digest:
            raise CapabilityExecutionError("Prime gameplay evidence is invalid")
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": _ARTIFACT_ID,
                    "media_type": _MEDIA_TYPE,
                    "value": {
                        "scope": "p7-gameplay-run",
                        "promotion": "unpromoted",
                        "game_id": evidence.game_id,
                        "evidence_sha256": evidence.evidence_sha256.removeprefix(
                            "sha256:"
                        ),
                        "win_levels": evidence.win_levels,
                        "action_cap": evidence.action_cap,
                        "completed_level_count": evidence.completed_level_count,
                        "primitive_action_count": evidence.primitive_action_count,
                        "sdk_state": evidence.sdk_state,
                        "terminal_reason": evidence.terminal_reason,
                        "outcome": evidence.outcome,
                    },
                },
            ),
        )


def create_prime_arc_agi_3_gameplay_package() -> InstalledCapabilityPackage:
    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-arc-agi-3-gameplay.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF, PrimeArcAgi3GameplayImplementation()
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "P7_SOLVE_PROMPT_SHA256",
    "PrimeArcAgi3GameplayImplementation",
    "create_prime_arc_agi_3_gameplay_package",
)
