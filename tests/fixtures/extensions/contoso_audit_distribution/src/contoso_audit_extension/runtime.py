import os
from collections.abc import AsyncIterator
from pathlib import Path
from asterion.application_sdk import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeManifest,
)


class Runtime:
    manifest = RuntimeManifest("contoso.inline", ())

    def __init__(self) -> None:
        _count("client")

    async def run(
        self, request: RunRequest, *, signal: CancellationSignal | None = None
    ) -> AsyncIterator[RunEvent]:
        _count("run")
        del signal
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(request.run_id, 2, "text.delta", {"text": "contoso"})
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


def create_runtime(context: RuntimeFactoryContext) -> AgentRuntimeClient:
    _count("factory")
    if (
        context.provider_id != "contoso-audit"
        or context.application_id != "contoso.audited-research"
        or context.application_version != "1.0.0"
        or context.runtime_id != "contoso.inline"
        or context.options
        or context.host_services
    ):
        raise RuntimeFactoryError("contoso runtime factory context is invalid")
    return Runtime()


def _count(name: str) -> None:
    path = os.environ.get("CONTOSO_COUNT_FILE")
    if path:
        Path(path).write_text(name, encoding="utf-8")
