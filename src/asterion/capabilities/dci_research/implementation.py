"""Runtime-neutral DCI local-corpus research implementation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from asterion.packages.execution import (
    PackageExecutionError,
    PackageExecutionResult,
    PackageInvocation,
)
from asterion.dci.bridge import DciRunExecutor, project_dci_run
from asterion.dci.run import DciRunRequest, DciRunResult
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream


class DciLocalResearchImplementation:
    """Delegate local-corpus research to an explicitly supplied runtime."""

    def __init__(self, *, native_executor: DciRunExecutor | None = None) -> None:
        self._native_executor = native_executor

    async def execute(
        self, invocation: PackageInvocation
    ) -> PackageExecutionResult:
        if (
            invocation.runtime.manifest.runtime_id == "pi.reference"
            and self._native_executor is not None
        ):
            try:
                return self.execute_completed_native_run(
                    self._native_executor.run(
                        DciRunRequest(
                            run_id=invocation.run_id,
                            question=invocation.input_text,
                            cwd=Path.cwd(),
                        )
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                raise PackageExecutionError("research native execution failed") from None
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
            events = tuple([
                event.to_mapping()
                async for event in invocation.runtime.run(
                    request, signal=invocation.signal
                )
            ])
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

    def execute_completed_native_run(self, result: DciRunResult) -> PackageExecutionResult:
        """Project an explicitly supplied native run; generic ownership remains unchanged."""

        return project_dci_run(result)


def _answer_artifact_uri(events: tuple[Mapping[str, object], ...]) -> str:
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
