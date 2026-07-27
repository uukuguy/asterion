"""Execute resolved package implementations in deterministic order."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from asterion.assembly.protocol import AssemblyPlan
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    EXECUTABLE_CAPABILITY_KINDS,
    CapabilityExecutionError,
    CapabilityImplementationBinding,
    CapabilityInvocation,
    validate_implementation_bindings,
    validate_capability_result,
)
from asterion.runner.application import (
    ApplicationRunError,
    ApplicationRunResult,
)
from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunRequest,
)
from asterion.runtime.protocol import ProtocolError


async def run_composed_application(
    plan: AssemblyPlan,
    *,
    implementations: Iterable[CapabilityImplementationBinding],
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    host_services: Mapping[str, object],
    host_events: tuple[Mapping[str, object], ...] = (),
    host_artifacts: tuple[Mapping[str, object], ...] = (),
    signal: CancellationSignal | None = None,
) -> ApplicationRunResult:
    """Run explicitly bound package implementations sequentially."""

    try:
        host_events_snapshot = tuple(
            _freeze_mapping(event) for event in host_events
        )
        host_artifacts_snapshot = tuple(
            _freeze_mapping(artifact) for artifact in host_artifacts
        )
    except Exception:
        raise ApplicationRunError("application host evidence is invalid") from None

    _preflight(
        plan,
        runtime=runtime,
        run_id=run_id,
        input_text=input_text,
        host_services=host_services,
        host_events=host_events_snapshot,
        host_artifacts=host_artifacts_snapshot,
        signal=signal,
    )
    try:
        bindings = validate_implementation_bindings(plan, implementations)
    except CapabilityExecutionError:
        raise ApplicationRunError("application package binding is invalid") from None

    events: list[Mapping[str, object]] = []
    artifacts: list[Mapping[str, object]] = []
    artifact_ids: set[str] = set()
    for manifest in plan.package_manifests:
        if manifest["kind"] not in EXECUTABLE_CAPABILITY_KINDS:
            continue
        if signal is not None and signal.cancelled:
            raise ApplicationRunError("application package execution was cancelled")
        capability_ref = CapabilityRef(
            str(manifest["capability_id"]), str(manifest["version"])
        )
        consumed_events = manifest["consumes_events"]
        consumed_artifacts = manifest["consumes_artifacts"]
        assert isinstance(consumed_events, tuple)
        assert isinstance(consumed_artifacts, tuple)
        upstream_events = tuple(
            event for event in events if event.get("type") in consumed_events
        )
        upstream_artifacts = tuple(
            artifact
            for artifact in artifacts
            if artifact.get("media_type") in consumed_artifacts
        )
        package_host_events = tuple(
            event
            for event in host_events_snapshot
            if event.get("type") in consumed_events
        )
        package_host_artifacts = tuple(
            artifact
            for artifact in host_artifacts_snapshot
            if artifact.get("media_type") in consumed_artifacts
        )
        invocation = CapabilityInvocation(
            capability_ref=capability_ref,
            manifest=manifest,
            run_id=run_id,
            input_text=input_text,
            upstream_events=upstream_events,
            upstream_artifacts=upstream_artifacts,
            host_events=package_host_events,
            host_artifacts=package_host_artifacts,
            runtime=runtime,
            host_services=host_services,
            signal=signal,
        )
        try:
            result = await bindings[capability_ref].execute(invocation)
            validate_capability_result(manifest, result)
            for artifact in result.artifacts:
                artifact_id = artifact["artifact_id"]
                assert isinstance(artifact_id, str)
                if artifact_id in artifact_ids:
                    raise CapabilityExecutionError(
                        "application artifact identity is duplicated"
                    )
                artifact_ids.add(artifact_id)
        except Exception:
            raise ApplicationRunError("application package execution failed") from None
        events.extend(result.events)
        artifacts.extend(result.artifacts)

    return ApplicationRunResult(
        application_id=plan.application_id,
        runtime_id=plan.runtime_id,
        run_id=run_id,
        events=tuple(events),
        artifacts=tuple(artifacts),
    )


def _preflight(
    plan: AssemblyPlan,
    *,
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    host_services: Mapping[str, object],
    host_events: tuple[Mapping[str, object], ...],
    host_artifacts: tuple[Mapping[str, object], ...],
    signal: CancellationSignal | None,
) -> None:
    if runtime.manifest.runtime_id != plan.runtime_id:
        raise ApplicationRunError("application runtime identity does not match")
    if any(
        capability not in runtime.manifest.capabilities
        for capability in plan.runtime_capabilities
    ):
        raise ApplicationRunError("application runtime capability is unavailable")
    if any(capability not in host_services for capability in plan.host_capabilities):
        raise ApplicationRunError("application host service is unavailable")
    _preflight_host_evidence(
        plan,
        host_events=host_events,
        host_artifacts=host_artifacts,
    )
    if signal is not None and signal.cancelled:
        raise ApplicationRunError("application run was cancelled before invocation")
    try:
        RunRequest(run_id=run_id, input_text=input_text).to_mapping()
    except (ProtocolError, TypeError, ValueError):
        raise ApplicationRunError("application request is invalid") from None


def _preflight_host_evidence(
    plan: AssemblyPlan,
    *,
    host_events: tuple[Mapping[str, object], ...],
    host_artifacts: tuple[Mapping[str, object], ...],
) -> None:
    event_types: set[str] = set()
    for event in host_events:
        if (
            not isinstance(event, Mapping)
            or event.keys() != {"type", "payload"}
            or not isinstance(event["type"], str)
            or not isinstance(event["payload"], Mapping)
        ):
            raise ApplicationRunError("application host event is invalid")
        event_types.add(event["type"])
    if event_types != set(plan.host_events):
        raise ApplicationRunError("application host event declarations do not match")

    media_types: set[str] = set()
    artifact_ids: set[str] = set()
    for artifact in host_artifacts:
        if (
            not isinstance(artifact, Mapping)
            or artifact.keys() != {"artifact_id", "media_type", "value"}
            or not isinstance(artifact["artifact_id"], str)
            or not artifact["artifact_id"]
            or artifact["artifact_id"] in artifact_ids
            or not isinstance(artifact["media_type"], str)
            or not isinstance(artifact["value"], Mapping)
        ):
            raise ApplicationRunError("application host artifact is invalid")
        artifact_ids.add(artifact["artifact_id"])
        media_types.add(artifact["media_type"])
    if media_types != set(plan.host_artifacts):
        raise ApplicationRunError(
            "application host artifact declarations do not match"
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
