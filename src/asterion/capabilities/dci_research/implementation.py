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
from asterion.capabilities.dci_research._runtime import (
    RuntimeEventError,
    RuntimeRequest,
    event_mappings,
)


class DciLocalResearchImplementation:
    """Delegate local-corpus research to an explicitly supplied runtime."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        _require_local_corpus(invocation)
        required = invocation.manifest["requires_capabilities"]
        if not isinstance(required, tuple) or not all(
            isinstance(capability, str) for capability in required
        ):
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
            answer_uri = _answer_artifact_uri(events)
        except (RuntimeEventError, TypeError, ValueError, RuntimeError):
            raise CapabilityExecutionError("research runtime execution failed") from None
        return CapabilityExecutionResult(
            events=(
                {"type": "research.completed", "payload": {"status": "completed"}},
            ),
            artifacts=(
                {
                    "artifact_id": "dci-research-result",
                    "media_type": "application/vnd.dci.research+json",
                    "value": {"answer_artifact_uri": answer_uri},
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


def _answer_artifact_uri(events: Sequence[Mapping[str, object]]) -> str:
    for event in events:
        if event.get("type") != "artifact.created":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        artifact = payload.get("artifact")
        if not isinstance(artifact, Mapping) or artifact.get("kind") != "answer":
            continue
        uri = artifact.get("uri")
        if isinstance(uri, str) and uri:
            return uri
    raise CapabilityExecutionError("research runtime answer artifact is unavailable")
