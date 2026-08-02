"""Execute resolved capability implementations in deterministic order."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Callable
from uuid import uuid4

from asterion.assembly.protocol import AssemblyPlan
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    EXECUTABLE_CAPABILITY_KINDS,
    CapabilityExecutionError,
    CapabilityImplementation,
    CapabilityInvocation,
    validate_implementation_bindings,
    validate_capability_result,
)
from asterion.runner.application import (
    ApplicationRunError,
    ApplicationRunResult,
)
from asterion.pathlight import PathlightRecorder, TraceEvent
from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunRequest,
)
from asterion.runtime.protocol import ProtocolError


async def run_composed_application(
    plan: AssemblyPlan,
    *,
    implementations: Iterable[tuple[CapabilityRef, CapabilityImplementation]],
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    host_services: Mapping[str, object],
    host_events: tuple[Mapping[str, object], ...] = (),
    host_artifacts: tuple[Mapping[str, object], ...] = (),
    signal: CancellationSignal | None = None,
    pathlight: PathlightRecorder | None = None,
) -> ApplicationRunResult:
    """Run explicitly bound capability implementations sequentially."""

    try:
        host_events_snapshot = tuple(
            _freeze_mapping(event) for event in host_events
        )
        host_artifacts_snapshot = tuple(
            _freeze_mapping(artifact) for artifact in host_artifacts
        )
    except Exception:
        raise ApplicationRunError("application host evidence is invalid") from None

    lifecycle = _PathlightLifecycle(pathlight)
    lifecycle.start_root()
    lifecycle.start_plan()
    active_capability_span: str | None = None
    cancellation_observed = False
    failure_class = "configuration"

    def record_cancellation() -> None:
        nonlocal cancellation_observed
        cancellation_observed = True

    try:
        _preflight(
            plan,
            runtime=runtime,
            run_id=run_id,
            input_text=input_text,
            host_services=host_services,
            host_events=host_events_snapshot,
            host_artifacts=host_artifacts_snapshot,
            signal=signal,
            on_cancelled=record_cancellation,
        )
        try:
            bindings = validate_implementation_bindings(plan, implementations)
        except CapabilityExecutionError:
            raise ApplicationRunError(
                "application capability binding is invalid"
            ) from None

        events: list[Mapping[str, object]] = []
        artifacts: list[Mapping[str, object]] = []
        artifact_ids: set[str] = set()
        for manifest in plan.capability_manifests:
            if manifest["kind"] not in EXECUTABLE_CAPABILITY_KINDS:
                continue
            if signal is not None and signal.cancelled:
                record_cancellation()
                raise ApplicationRunError(
                    "application capability execution was cancelled"
                )
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
            active_capability_span = lifecycle.start_capability()
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
                lifecycle.fail_capability(active_capability_span)
                active_capability_span = None
                failure_class = "capability-execution-failed"
                raise ApplicationRunError(
                    "application capability execution failed"
                ) from None
            lifecycle.complete_capability(active_capability_span)
            active_capability_span = None
            events.extend(result.events)
            artifacts.extend(result.artifacts)

        result = ApplicationRunResult(
            application_id=plan.application_id,
            runtime_id=plan.runtime_id,
            run_id=run_id,
            events=tuple(events),
            artifacts=tuple(artifacts),
        )
    except asyncio.CancelledError:
        if active_capability_span is not None:
            lifecycle.cancel_capability(active_capability_span)
        lifecycle.cancel_plan()
        lifecycle.cancel_root()
        raise
    except ApplicationRunError:
        if active_capability_span is not None:
            lifecycle.fail_capability(active_capability_span)
        if cancellation_observed:
            lifecycle.cancel_plan()
            lifecycle.cancel_root()
        else:
            lifecycle.fail_plan(failure_class)
            lifecycle.fail_root(failure_class)
        raise
    lifecycle.complete_plan()
    lifecycle.complete_root()
    return result


class _PathlightLifecycle:
    """Emit closed, public-safe spans without influencing execution decisions."""

    def __init__(self, recorder: PathlightRecorder | None) -> None:
        self._recorder = recorder
        self._trace_id: str | None = None
        if recorder is not None:
            try:
                self._trace_id = recorder.trace_id
            except Exception:
                self._disable()
        self._sequence = 0
        self._root_span_id: str | None = None
        self._plan_span_id: str | None = None

    def start_root(self) -> None:
        self._root_span_id = self._start("task", None)

    def start_plan(self) -> None:
        self._plan_span_id = self._start("plan", self._root_span_id)

    def start_capability(self) -> str | None:
        return self._start("task", self._plan_span_id)

    def complete_capability(self, span_id: str | None) -> None:
        self._terminal(span_id, "completed", "task")

    def fail_capability(self, span_id: str | None) -> None:
        self._terminal(
            span_id,
            "failed",
            "task",
            attributes={"failure_class": "capability-execution-failed"},
        )

    def cancel_capability(self, span_id: str | None) -> None:
        self._terminal(
            span_id,
            "cancelled",
            "task",
            attributes={"failure_class": "cancelled"},
        )

    def complete_plan(self) -> None:
        self._terminal(self._plan_span_id, "completed", "plan")

    def fail_plan(self, failure_class: str) -> None:
        self._terminal(
            self._plan_span_id,
            "failed",
            "plan",
            attributes={"failure_class": failure_class},
        )

    def cancel_plan(self) -> None:
        self._terminal(
            self._plan_span_id,
            "cancelled",
            "plan",
            attributes={"failure_class": "cancelled"},
        )

    def complete_root(self) -> None:
        self._terminal(self._root_span_id, "completed", "task")

    def fail_root(self, failure_class: str) -> None:
        self._terminal(
            self._root_span_id,
            "failed",
            "task",
            attributes={"failure_class": failure_class},
        )

    def cancel_root(self) -> None:
        self._terminal(
            self._root_span_id,
            "cancelled",
            "task",
            attributes={"failure_class": "cancelled"},
        )

    def _start(self, kind: str, parent_span_id: str | None) -> str | None:
        if self._trace_id is None:
            return None
        span_id = str(uuid4())
        sequence = self._next_sequence()
        try:
            event = TraceEvent.start(
                self._trace_id,
                span_id,
                parent_span_id,
                sequence,
                kind,
            )
        except Exception:
            self._disable()
            return None
        self._sequence = sequence
        self._record(event)
        return span_id

    def _terminal(
        self,
        span_id: str | None,
        status: str,
        kind: str,
        *,
        attributes: Mapping[str, str] | None = None,
    ) -> None:
        if self._trace_id is None or span_id is None:
            return
        sequence = self._next_sequence()
        try:
            event = TraceEvent.terminal(
                self._trace_id,
                span_id,
                sequence,
                status,
                kind=kind,
                attributes=attributes,
            )
        except Exception:
            self._disable()
            return
        self._sequence = sequence
        self._record(event)

    def _record(self, event: TraceEvent) -> None:
        assert self._recorder is not None
        try:
            self._recorder.record(event)
        except Exception:
            # Instrumentation remains observational and cannot replace the
            # runner's result, failure, or cancellation semantics.
            self._disable()

    def _next_sequence(self) -> int:
        if self._recorder is None:
            return self._sequence + 1
        try:
            sequence = self._recorder.next_sequence
        except Exception:
            return self._sequence + 1
        if type(sequence) is not int or sequence < 1:
            self._disable()
            return self._sequence + 1
        return sequence

    def _disable(self) -> None:
        self._recorder = None
        self._trace_id = None


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
    on_cancelled: Callable[[], None] | None = None,
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
        if on_cancelled is not None:
            on_cancelled()
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
