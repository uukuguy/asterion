"""Provider-owned deterministic runtime for the public-extension reference."""

from __future__ import annotations

from collections.abc import AsyncIterator

from asterion.application_sdk import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeManifest,
)


class _InlineRuntime:
    manifest = RuntimeManifest("acme.inline", ())

    async def run(
        self,
        request: RunRequest,
    *,
    signal: CancellationSignal | None = None,
) -> AsyncIterator[RunEvent]:
        del signal
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(request.run_id, 2, "text.delta", {"text": "acme reference"})
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


def create_runtime(context: RuntimeFactoryContext) -> AgentRuntimeClient:
    if (
        context.provider_id != "acme-sample"
        or context.application_id != "acme.research-application"
        or context.application_version != "1.0.0"
        or context.runtime_id != "acme.inline"
        or context.options
        or context.host_services
    ):
        raise RuntimeFactoryError("acme runtime factory context is invalid")
    return _InlineRuntime()
