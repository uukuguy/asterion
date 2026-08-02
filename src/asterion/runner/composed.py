"""Execute resolved capability implementations in deterministic order."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Callable
from uuid import uuid4

from asterion.assembly.protocol import AssemblyPlan
from asterion.capability_packages import CapabilityPackageRef
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
    implementation_packages: Mapping[CapabilityRef, CapabilityPackageRef] | None = None,
    monotonic_ns: Callable[[], int] | None = None,
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

    lifecycle = _PathlightLifecycle(pathlight, monotonic_ns=monotonic_ns)
    lifecycle.start_root(plan, run_id=run_id)
    lifecycle.start_assembly(plan)
    lifecycle.record_package_boundaries(plan.capability_package_refs)
    lifecycle.record_host_service_boundaries(host_services)
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
            implementation = bindings[capability_ref]
            owner_package: CapabilityPackageRef | None = None
            if implementation_packages is not None:
                try:
                    candidate = implementation_packages.get(capability_ref)
                    if isinstance(candidate, CapabilityPackageRef):
                        owner_package = candidate
                except Exception:
                    owner_package = None
            active_capability_span = lifecycle.start_capability(
                capability_ref,
                implementation,
                run_id=run_id,
                owner_package=owner_package,
            )
            try:
                result = await implementation.execute(invocation)
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
            lifecycle.record_capability_outputs(
                active_capability_span,
                manifest=manifest,
                artifacts=result.artifacts,
            )
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
        lifecycle.cancel_assembly()
        lifecycle.cancel_root()
        raise
    except ApplicationRunError:
        if active_capability_span is not None:
            lifecycle.fail_capability(active_capability_span)
        if cancellation_observed:
            lifecycle.cancel_plan()
            lifecycle.cancel_assembly()
            lifecycle.cancel_root()
        else:
            lifecycle.fail_plan(failure_class)
            lifecycle.fail_assembly(failure_class)
            lifecycle.fail_root(failure_class)
        raise
    lifecycle.complete_plan()
    lifecycle.complete_assembly()
    lifecycle.complete_root()
    return result


class _PathlightLifecycle:
    """Emit closed, public-safe spans without influencing execution decisions."""

    def __init__(
        self,
        recorder: PathlightRecorder | None,
        *,
        monotonic_ns: Callable[[], int] | None,
    ) -> None:
        self._recorder = recorder
        self._trace_id: str | None = None
        if recorder is not None:
            try:
                self._trace_id = recorder.trace_id
            except Exception:
                self._disable()
        self._sequence = 0
        self._clock = monotonic_ns if monotonic_ns is not None else time.monotonic_ns
        self._started_ns: dict[str, int] = {}
        self._root_span_id: str | None = None
        self._assembly_span_id: str | None = None
        self._assembly_digest_value: str | None = None
        self._plan_span_id: str | None = None

    def start_root(self, plan: AssemblyPlan, *, run_id: str) -> None:
        self._root_span_id = self._start(
            "task",
            None,
            attributes={
                "run_sha256": _identity_sha256(run_id),
                "application_sha256": _identity_sha256(
                    {"application_id": plan.application_id, "version": plan.version}
                ),
                "task_sha256": _identity_sha256(
                    {
                        "application_id": plan.application_id,
                        "application_version": plan.version,
                        "run_id": run_id,
                    }
                ),
            },
        )

    def start_assembly(self, plan: AssemblyPlan) -> None:
        self._assembly_digest_value = _assembly_sha256(plan)
        self._assembly_span_id = self._start(
            "assembly",
            self._root_span_id,
            attributes={
                "application_sha256": _identity_sha256(
                    {"application_id": plan.application_id, "version": plan.version}
                ),
                "assembly_sha256": self._assembly_digest_value,
                "runtime_sha256": _identity_sha256(plan.runtime_id),
            },
        )

    def record_package_boundaries(
        self, package_refs: tuple[CapabilityPackageRef, ...]
    ) -> None:
        for package_ref in package_refs:
            span_id = self._start(
                "plan",
                self._assembly_span_id,
                attributes={
                    "capability_package_sha256": _package_ref_sha256(package_ref)
                },
            )
            self._terminal(span_id, "completed", "plan")

    def record_host_service_boundaries(
        self, host_services: Mapping[str, object]
    ) -> None:
        try:
            service_ids = tuple(sorted(host_services))
        except Exception:
            return
        for service_id in service_ids:
            if type(service_id) is not str:
                continue
            span_id = self._start(
                "host-service",
                self._assembly_span_id,
                attributes={"host_service_sha256": _identity_sha256(service_id)},
            )
            self._terminal(span_id, "completed", "host-service")

    def start_plan(self) -> None:
        if self._assembly_span_id is None or self._assembly_digest_value is None:
            return
        self._plan_span_id = self._start(
            "plan",
            self._assembly_span_id,
            attributes={"assembly_sha256": self._assembly_digest_value},
        )

    def start_capability(
        self,
        capability_ref: CapabilityRef,
        implementation: CapabilityImplementation,
        *,
        run_id: str,
        owner_package: CapabilityPackageRef | None,
    ) -> str | None:
        attributes = {
            "task_sha256": _identity_sha256(
                {
                    "capability_id": capability_ref.capability_id,
                    "capability_version": capability_ref.version,
                    "run_id": run_id,
                }
            ),
            "capability_ref_sha256": _capability_ref_sha256(capability_ref),
            "implementation_sha256": _implementation_binding_sha256(
                capability_ref, implementation
            ),
        }
        if owner_package is not None:
            attributes["capability_package_sha256"] = _package_ref_sha256(
                owner_package
            )
        return self._start("task", self._plan_span_id, attributes=attributes)

    def record_capability_outputs(
        self,
        capability_span_id: str | None,
        *,
        manifest: Mapping[str, object],
        artifacts: tuple[Mapping[str, object], ...],
    ) -> None:
        capability_ref = {
            "capability_id": manifest.get("capability_id"),
            "version": manifest.get("version"),
        }
        if manifest.get("kind") == "evaluation":
            span_id = self._start(
                "evaluation",
                capability_span_id,
                attributes={"evaluation_sha256": _identity_sha256(capability_ref)},
            )
            self._terminal(span_id, "completed", "evaluation")
        for artifact in artifacts:
            artifact_id = artifact.get("artifact_id")
            media_type = artifact.get("media_type")
            if type(artifact_id) is not str or type(media_type) is not str:
                continue
            span_id = self._start(
                "artifact",
                capability_span_id,
                attributes={
                    "artifact_sha256": _identity_sha256(
                        {"artifact_id": artifact_id, "media_type": media_type}
                    )
                },
            )
            self._terminal(span_id, "completed", "artifact")

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

    def complete_assembly(self) -> None:
        self._terminal(self._assembly_span_id, "completed", "assembly")

    def fail_assembly(self, failure_class: str) -> None:
        self._terminal(
            self._assembly_span_id,
            "failed",
            "assembly",
            attributes={"failure_class": failure_class},
        )

    def cancel_assembly(self) -> None:
        self._terminal(
            self._assembly_span_id,
            "cancelled",
            "assembly",
            attributes={"failure_class": "cancelled"},
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

    def _start(
        self,
        kind: str,
        parent_span_id: str | None,
        *,
        attributes: Mapping[str, str | int | bool] | None = None,
    ) -> str | None:
        if self._trace_id is None:
            return None
        timestamp_ns = self._now()
        if timestamp_ns is None:
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
                attributes=attributes,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._disable()
            return None
        self._sequence = sequence
        self._record(event)
        if self._trace_id is not None:
            self._started_ns[span_id] = timestamp_ns
        return span_id

    def _terminal(
        self,
        span_id: str | None,
        status: str,
        kind: str,
        *,
        attributes: Mapping[str, str | int | bool] | None = None,
    ) -> None:
        if self._trace_id is None or span_id is None:
            return
        timestamp_ns = self._now()
        started_ns = self._started_ns.get(span_id)
        if timestamp_ns is None or started_ns is None:
            return
        if timestamp_ns <= started_ns:
            self._disable()
            return
        terminal_attributes: dict[str, str | int | bool] = dict(attributes or {})
        terminal_attributes["duration_ns"] = timestamp_ns - started_ns
        sequence = self._next_sequence()
        try:
            event = TraceEvent.terminal(
                self._trace_id,
                span_id,
                sequence,
                status,
                kind=kind,
                attributes=terminal_attributes,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._disable()
            return
        self._sequence = sequence
        self._record(event)
        self._started_ns.pop(span_id, None)

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

    def _now(self) -> int | None:
        try:
            value = self._clock()
        except Exception:
            self._disable()
            return None
        if type(value) is not int or value <= 0:
            self._disable()
            return None
        return value

    def _disable(self) -> None:
        self._recorder = None
        self._trace_id = None


def _identity_sha256(value: object) -> str:
    if type(value) is str:
        rendered = value
    else:
        rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _package_ref_sha256(package_ref: CapabilityPackageRef) -> str:
    return _identity_sha256(
        {"package_id": package_ref.package_id, "version": package_ref.version}
    )


def _capability_ref_sha256(capability_ref: CapabilityRef) -> str:
    return _identity_sha256(
        {
            "capability_id": capability_ref.capability_id,
            "version": capability_ref.version,
        }
    )


def _implementation_binding_sha256(
    capability_ref: CapabilityRef, implementation: CapabilityImplementation
) -> str:
    implementation_type = type(implementation)
    return _identity_sha256(
        {
            "capability_sha256": _capability_ref_sha256(capability_ref),
            "implementation_type": (
                f"{implementation_type.__module__}.{implementation_type.__qualname__}"
            ),
        }
    )


def _assembly_sha256(plan: AssemblyPlan) -> str:
    return _identity_sha256(
        {
            "application_id": plan.application_id,
            "application_version": plan.version,
            "capability_packages": [
                {"package_id": ref.package_id, "version": ref.version}
                for ref in plan.capability_package_refs
            ],
            "capabilities": [
                {"capability_id": ref.capability_id, "version": ref.version}
                for ref in plan.capability_refs
            ],
            "runtime_id": plan.runtime_id,
        }
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
