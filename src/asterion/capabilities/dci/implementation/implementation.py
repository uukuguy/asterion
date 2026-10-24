"""Runtime-neutral DCI local-corpus research implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from asterion.capability_sdk import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.capabilities.dci.implementation._runtime import (
    RuntimeEventError,
    RuntimeRequest,
    event_mappings,
)


ANSWER_MEDIA_TYPE = "application/vnd.dci.research.answer+json"
LOCATIONS_MEDIA_TYPE = "application/vnd.dci.research.locations+json"
TRAJECTORY_MEDIA_TYPE = "application/vnd.dci.research.trajectory+json"
CORE_ARTIFACT_MEDIA_TYPES = (
    ANSWER_MEDIA_TYPE,
    LOCATIONS_MEDIA_TYPE,
    TRAJECTORY_MEDIA_TYPE,
)
_REQUIRED_CAPABILITIES = ("filesystem.read", "shell")
_REQUIRED_POLICIES = ("policy.context-management", "policy.local-corpus")


class DciLocalResearchImplementation:
    """Delegate local-corpus research to an explicitly supplied runtime."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        _require_local_corpus(invocation)
        required = invocation.manifest["requires_capabilities"]
        policies = invocation.manifest["requires_policies"]
        if required != _REQUIRED_CAPABILITIES or policies != _REQUIRED_POLICIES:
            raise CapabilityExecutionError("research capability declaration is invalid")
        request = RuntimeRequest(
            run_id=invocation.run_id,
            input_text=invocation.input_text,
            requested_capabilities=required,
        )
        try:
            events = event_mappings([
                event
                async for event in cast(Any, invocation.runtime).run(
                    request, signal=invocation.signal
                )
            ])
            answer_uri, locations, trajectory = _core_evidence(events)
        except (RuntimeEventError, TypeError, ValueError, RuntimeError):
            raise CapabilityExecutionError("research runtime execution failed") from None
        return CapabilityExecutionResult(
            events=(
                {"type": "research.completed", "payload": {"status": "completed"}},
            ),
            artifacts=(
                {
                    "artifact_id": "dci-research-answer",
                    "media_type": ANSWER_MEDIA_TYPE,
                    "value": {"answer_artifact_uri": answer_uri},
                },
                {
                    "artifact_id": "dci-research-locations",
                    "media_type": LOCATIONS_MEDIA_TYPE,
                    "value": locations,
                },
                {
                    "artifact_id": "dci-research-trajectory",
                    "media_type": TRAJECTORY_MEDIA_TYPE,
                    "value": trajectory,
                },
            ),
        )


def _require_local_corpus(invocation: CapabilityInvocation) -> Path:
    try:
        service = invocation.host_services.get("corpus.local-root")
        root = cast(Any, service).root
    except Exception:
        raise CapabilityExecutionError("local corpus service is unavailable") from None
    if not isinstance(root, Path):
        raise CapabilityExecutionError("local corpus service is unavailable")
    return root


def _core_evidence(
    events: Sequence[Mapping[str, object]],
) -> tuple[str, Mapping[str, object], Mapping[str, object]]:
    answer_uri: str | None = None
    paths: list[str] = []
    calls: list[str] = []
    for event in events:
        if event.get("type") != "artifact.created":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        artifact = payload.get("artifact")
        if not isinstance(artifact, Mapping):
            continue
        uri = artifact.get("uri")
        if not isinstance(uri, str) or not uri:
            continue
        kind = artifact.get("kind")
        if kind == "answer":
            if answer_uri is None:
                answer_uri = uri
        elif kind == "locations":
            paths.append(uri)
        elif kind == "trajectory":
            calls.append(uri)
    if answer_uri is None or not paths or not calls:
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    return answer_uri, {"paths": tuple(paths)}, {"calls": tuple(calls)}
