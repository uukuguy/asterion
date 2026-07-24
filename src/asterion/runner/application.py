"""Execute one resolved application plan through an explicit runtime client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from asterion.assembly.protocol import AssemblyPlan
from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunRequest,
)
from asterion.runtime.protocol import ProtocolError, validate_event_stream


class ApplicationRunError(RuntimeError):
    """Raised when an application cannot produce one valid normalized result."""


@dataclass(frozen=True)
class ApplicationRunResult:
    application_id: str
    runtime_id: str
    run_id: str
    events: tuple[Mapping[str, object], ...]
    artifacts: tuple[Mapping[str, object], ...]


async def run_application(
    plan: AssemblyPlan,
    *,
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    host_services: Mapping[str, object],
    signal: CancellationSignal | None = None,
) -> ApplicationRunResult:
    """Run a resolved plan once without discovering packages or services."""

    if runtime.manifest.runtime_id != plan.runtime_id:
        raise ApplicationRunError("application runtime identity does not match")
    if any(
        capability not in runtime.manifest.capabilities
        for capability in plan.runtime_capabilities
    ):
        raise ApplicationRunError("application runtime capability is unavailable")
    if any(capability not in host_services for capability in plan.host_capabilities):
        raise ApplicationRunError("application host service is unavailable")
    if signal is not None and signal.cancelled:
        raise ApplicationRunError("application run was cancelled before invocation")

    request = RunRequest(
        run_id=run_id,
        input_text=input_text,
        requested_capabilities=plan.runtime_capabilities,
    )
    try:
        request.to_mapping()
    except (ProtocolError, TypeError, ValueError):
        raise ApplicationRunError("application request is invalid") from None

    runtime_failed = False
    events = []
    try:
        events = [
            event.to_mapping()
            async for event in runtime.run(request, signal=signal)
        ]
    except Exception:
        runtime_failed = True
    if runtime_failed:
        raise ApplicationRunError("application runtime failed")

    try:
        validate_event_stream(events)
    except (ProtocolError, TypeError, ValueError):
        raise ApplicationRunError("application event stream is invalid") from None
    if any(event["run_id"] != run_id for event in events):
        raise ApplicationRunError("application event stream run identity does not match")

    frozen_events = tuple(_freeze_mapping(event) for event in events)
    frozen_artifacts = tuple(
        _freeze_mapping(event["payload"]["artifact"])
        for event in events
        if event["type"] == "artifact.created"
    )
    return ApplicationRunResult(
        application_id=plan.application_id,
        runtime_id=plan.runtime_id,
        run_id=run_id,
        events=frozen_events,
        artifacts=frozen_artifacts,
    )


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value
