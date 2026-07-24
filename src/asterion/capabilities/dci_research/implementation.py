"""Runtime-neutral DCI local-corpus research implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from asterion.dci.services import LocalCorpusService
from asterion.packages.execution import (
    PackageExecutionError,
    PackageExecutionResult,
    PackageInvocation,
)
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream


class DciLocalResearchImplementation:
    """Delegate local-corpus research to an explicitly supplied runtime."""

    async def execute(
        self, invocation: PackageInvocation
    ) -> PackageExecutionResult:
        _require_local_corpus(invocation)
        required = invocation.manifest["requires_capabilities"]
        if not isinstance(required, tuple) or not all(
            isinstance(capability, str) for capability in required
        ):
            raise PackageExecutionError("research package declaration is invalid")
        request = RunRequest(
            run_id=invocation.run_id,
            input_text=invocation.input_text,
            requested_capabilities=required,
        )
        try:
            events = [
                event.to_mapping()
                async for event in invocation.runtime.run(
                    request, signal=invocation.signal
                )
            ]
            validate_event_stream(events)
            answer_uri = _answer_artifact_uri(events)
        except (ProtocolError, TypeError, ValueError, RuntimeError):
            raise PackageExecutionError("research runtime execution failed") from None
        return PackageExecutionResult(
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


def _require_local_corpus(invocation: PackageInvocation) -> Path:
    try:
        service = invocation.host_services.get("corpus.local-root")
        if not isinstance(service, LocalCorpusService):
            raise TypeError
        root = service.root
    except Exception:
        raise PackageExecutionError("local corpus service is unavailable") from None
    if not isinstance(root, Path):
        raise PackageExecutionError("local corpus service is unavailable")
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
    raise PackageExecutionError("research runtime answer artifact is unavailable")
