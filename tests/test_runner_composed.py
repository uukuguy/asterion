from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import cast

from asterion.assembly.protocol import resolve_assembly
from asterion.capabilities.catalog import (
    CapabilityCatalog,
    CapabilityRef,
    CatalogEntry,
)
from asterion.capabilities.execution import (
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.pathlight import MemoryPathlightRecorder
from asterion.runner.application import ApplicationRunError
from asterion.runner.composed import run_composed_application
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest


PROJECT = Path(__file__).resolve().parents[1]
TRACE_ID = "00000000-0000-4000-8000-000000000001"


class FixtureRuntime:
    manifest = RuntimeManifest(runtime_id="pi.reference", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        if False:
            yield RunEvent("", 0, "", {})


class CompletedImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(events=(), artifacts=())


class FailingImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        raise RuntimeError("SECRET-CAPABILITY-DIAGNOSTIC")


class EvaluationImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": "private-evaluation-artifact",
                    "media_type": "application/evaluation+json",
                    "value": {"answer": "SENTINEL-PRIVATE-EVALUATION"},
                },
            ),
        )


class FailingAfterCancellationImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        signal = cast(MutableSignal, invocation.signal)
        signal.cancelled = True
        raise RuntimeError("SECRET-CAPABILITY-DIAGNOSTIC")


class CancelledSignal:
    cancelled = True


class MutableSignal:
    def __init__(self) -> None:
        self.cancelled = False


class IncrementingClock:
    def __init__(self, start: int = 100) -> None:
        self.value = start

    def __call__(self) -> int:
        value = self.value
        self.value += 10
        return value


class RaisingRecorder:
    trace_id = TRACE_ID

    def record(self, event: object) -> None:
        del event
        raise RuntimeError("recorder failure")

    def snapshot(self) -> None:
        return None


class InvalidTraceRecorder:
    trace_id = "not-a-uuid"

    def record(self, event: object) -> None:
        del event
        raise AssertionError("invalid recorder must not receive events")

    def snapshot(self) -> None:
        return None


def trace_events(recorder: MemoryPathlightRecorder) -> Sequence[Mapping[str, object]]:
    snapshot = recorder.snapshot()
    events = snapshot["events"]
    assert isinstance(events, list)
    assert all(isinstance(event, Mapping) for event in events)
    return tuple(cast(Mapping[str, object], event) for event in events)


def plan(
    *,
    kind: str = "capability",
    produces_artifacts: tuple[str, ...] = (),
):
    manifest = {
        "protocol": "asterion.capability/v1",
        "capability_id": "trace.capability",
        "version": "1.0.0",
        "kind": kind,
        "provides_capabilities": [],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": [],
        "consumes_events": [],
        "produces_artifacts": list(produces_artifacts),
        "consumes_artifacts": [],
    }
    catalog = CapabilityCatalog(
        entries=(
            CatalogEntry(
                ref=CapabilityRef("trace.capability", "1.0.0"),
                source=PROJECT / "trace-capability.json",
                manifest=manifest,
            ),
        )
    )
    return resolve_assembly(
        {
            "protocol": "asterion.application-assembly/v1",
            "application_id": "trace.application",
            "version": "1.0.0",
            "runtime_id": "pi.reference",
            "capability_packages": [{"package_id": "trace", "version": "1.0.0"}],
            "capabilities": [{"capability_id": "trace.capability", "version": "1.0.0"}],
            "host_capabilities": [],
            "host_policies": [],
            "host_events": [],
            "host_artifacts": [],
        },
        catalog=catalog,
        runtime_manifest=FixtureRuntime.manifest.to_mapping(),
    )


class ComposedRunnerPathlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_trace_links_available_evaluation_and_artifact_identity(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        p = plan(
            kind="evaluation",
            produces_artifacts=("application/evaluation+json",),
        )

        await run_composed_application(
            p,
            implementations=(
                (CapabilityRef("trace.capability", "1.0.0"), EvaluationImplementation()),
            ),
            runtime=FixtureRuntime(),
            run_id="private-evaluation-run",
            input_text="SECRET-INPUT",
            host_services={},
            pathlight=recorder,
            monotonic_ns=IncrementingClock(),
        )

        events = trace_events(recorder)
        capability = next(
            item
            for item in events
            if item["kind"] == "task"
            and "capability_ref_sha256"
            in cast(Mapping[str, object], item["attributes"])
        )
        evaluation = next(item for item in events if item["kind"] == "evaluation")
        artifact = next(item for item in events if item["kind"] == "artifact")
        self.assertEqual(evaluation["parent_span_id"], capability["span_id"])
        self.assertEqual(artifact["parent_span_id"], capability["span_id"])
        self.assertIn(
            "evaluation_sha256", cast(Mapping[str, object], evaluation["attributes"])
        )
        self.assertIn(
            "artifact_sha256", cast(Mapping[str, object], artifact["attributes"])
        )
        rendered = json.dumps(recorder.snapshot(), default=dict, sort_keys=True)
        self.assertNotIn("private-evaluation-artifact", rendered)
        self.assertNotIn("application/evaluation+json", rendered)
        self.assertNotIn("SENTINEL-PRIVATE-EVALUATION", rendered)

    async def test_trace_links_safe_execution_identity_and_real_span_timing(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        p = plan()
        implementation = CompletedImplementation()

        await run_composed_application(
            p,
            implementations=((CapabilityRef("trace.capability", "1.0.0"), implementation),),
            runtime=FixtureRuntime(),
            run_id="SENTINEL-PRIVATE-RUN",
            input_text="SECRET-INPUT",
            host_services={"private.host": object()},
            pathlight=recorder,
            monotonic_ns=IncrementingClock(),
        )

        events = trace_events(recorder)
        starts = {item["span_id"]: item for item in events if item["status"] == "started"}
        self.assertEqual([item["timestamp_ns"] for item in events], sorted(
            item["timestamp_ns"] for item in events
        ))
        for item in events:
            self.assertGreater(item["timestamp_ns"], 0)
            if item["status"] != "started":
                attributes = cast(Mapping[str, object], item["attributes"])
                self.assertGreater(attributes["duration_ns"], 0)
                self.assertEqual(
                    attributes["duration_ns"],
                    item["timestamp_ns"] - starts[item["span_id"]]["timestamp_ns"],
                )

        kinds = [item["kind"] for item in events]
        self.assertIn("assembly", kinds)
        self.assertIn("host-service", kinds)
        root = events[0]
        root_attributes = cast(Mapping[str, object], root["attributes"])
        self.assertEqual(
            root_attributes["run_sha256"],
            hashlib.sha256(b"SENTINEL-PRIVATE-RUN").hexdigest(),
        )
        assembly = next(item for item in events if item["kind"] == "assembly")
        assembly_attributes = cast(Mapping[str, object], assembly["attributes"])
        for name in ("application_sha256", "assembly_sha256", "runtime_sha256"):
            self.assertRegex(str(assembly_attributes[name]), r"^[0-9a-f]{64}$")
        capability = next(
            item
            for item in events
            if item["kind"] == "task"
            and item["parent_span_id"] is not None
            and "capability_ref_sha256" in cast(Mapping[str, object], item["attributes"])
        )
        capability_attributes = cast(Mapping[str, object], capability["attributes"])
        for name in ("task_sha256", "capability_ref_sha256", "implementation_sha256"):
            self.assertRegex(str(capability_attributes[name]), r"^[0-9a-f]{64}$")
        package = next(
            item
            for item in events
            if "capability_package_sha256"
            in cast(Mapping[str, object], item["attributes"])
        )
        self.assertEqual(package["parent_span_id"], assembly["span_id"])

        rendered = json.dumps(recorder.snapshot(), default=dict, sort_keys=True)
        for source in (
            "SENTINEL-PRIVATE-RUN",
            "trace.application",
            "pi.reference",
            "trace.capability",
            "private.host",
            "CompletedImplementation",
        ):
            self.assertNotIn(source, rendered)

    async def test_composed_run_records_lifecycle_in_execution_order(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)

        await run_composed_application(
            plan(),
            implementations=(
                (CapabilityRef("trace.capability", "1.0.0"), CompletedImplementation()),
            ),
            runtime=FixtureRuntime(),
            run_id="run-1",
            input_text="SECRET-INPUT",
            host_services={},
            pathlight=recorder,
        )

        snapshot = recorder.snapshot()
        events = trace_events(recorder)
        self.assertEqual(
            [(item["kind"], item["status"]) for item in events],
            [
                ("task", "started"),
                ("assembly", "started"),
                ("plan", "started"),
                ("plan", "completed"),
                ("plan", "started"),
                ("task", "started"),
                ("task", "completed"),
                ("plan", "completed"),
                ("assembly", "completed"),
                ("task", "completed"),
            ],
        )
        self.assertIsNone(events[0]["parent_span_id"])
        self.assertEqual(events[1]["parent_span_id"], events[0]["span_id"])
        self.assertEqual(events[4]["parent_span_id"], events[1]["span_id"])
        self.assertEqual(events[5]["parent_span_id"], events[4]["span_id"])
        self.assertNotIn("SECRET-INPUT", repr(snapshot))

    async def test_composed_failure_records_fixed_failure_class(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)

        with self.assertRaises(ApplicationRunError) as raised:
            await run_composed_application(
                plan(),
                implementations=(
                    (
                        CapabilityRef("trace.capability", "1.0.0"),
                        FailingImplementation(),
                    ),
                ),
                runtime=FixtureRuntime(),
                run_id="run-1",
                input_text="SECRET-INPUT",
                host_services={},
                pathlight=recorder,
            )

        snapshot = recorder.snapshot()
        failed = [item for item in trace_events(recorder) if item["status"] == "failed"]
        self.assertEqual(
            str(raised.exception), "application capability execution failed"
        )
        self.assertEqual(len(failed), 4)
        self.assertEqual(
            [failure_class(item) for item in failed],
            ["capability-execution-failed"] * 4,
        )
        self.assertNotIn("SECRET-CAPABILITY-DIAGNOSTIC", repr(snapshot))

    async def test_preflight_cancellation_records_cancelled_root_and_plan(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)

        with self.assertRaisesRegex(
            ApplicationRunError, "application run was cancelled before invocation"
        ):
            await run_composed_application(
                plan(),
                implementations=(
                    (
                        CapabilityRef("trace.capability", "1.0.0"),
                        CompletedImplementation(),
                    ),
                ),
                runtime=FixtureRuntime(),
                run_id="run-1",
                input_text="SECRET-INPUT",
                host_services={},
                signal=CancelledSignal(),
                pathlight=recorder,
            )

        events = trace_events(recorder)
        self.assertEqual(
            [(item["kind"], item["status"]) for item in events],
            [
                ("task", "started"),
                ("assembly", "started"),
                ("plan", "started"),
                ("plan", "completed"),
                ("plan", "started"),
                ("plan", "cancelled"),
                ("assembly", "cancelled"),
                ("task", "cancelled"),
            ],
        )

    async def test_capability_failure_remains_failed_after_late_cancellation(
        self,
    ) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)

        with self.assertRaisesRegex(
            ApplicationRunError, "application capability execution failed"
        ):
            await run_composed_application(
                plan(),
                implementations=(
                    (
                        CapabilityRef("trace.capability", "1.0.0"),
                        FailingAfterCancellationImplementation(),
                    ),
                ),
                runtime=FixtureRuntime(),
                run_id="run-1",
                input_text="SECRET-INPUT",
                host_services={},
                signal=MutableSignal(),
                pathlight=recorder,
            )

        self.assertEqual(
            [item["status"] for item in trace_events(recorder)],
            [
                "started",
                "started",
                "started",
                "completed",
                "started",
                "started",
                "failed",
                "failed",
                "failed",
                "failed",
            ],
        )

    async def test_recorder_failure_does_not_change_the_application_result(self) -> None:
        result = await run_composed_application(
            plan(),
            implementations=(
                (CapabilityRef("trace.capability", "1.0.0"), CompletedImplementation()),
            ),
            runtime=FixtureRuntime(),
            run_id="run-1",
            input_text="SECRET-INPUT",
            host_services={},
            pathlight=RaisingRecorder(),
        )

        self.assertEqual(result.application_id, "trace.application")

    async def test_invalid_recorder_identity_does_not_change_the_application_result(
        self,
    ) -> None:
        result = await run_composed_application(
            plan(),
            implementations=(
                (CapabilityRef("trace.capability", "1.0.0"), CompletedImplementation()),
            ),
            runtime=FixtureRuntime(),
            run_id="run-1",
            input_text="SECRET-INPUT",
            host_services={},
            pathlight=InvalidTraceRecorder(),
        )

        self.assertEqual(result.application_id, "trace.application")


def failure_class(event: Mapping[str, object]) -> str:
    attributes = event["attributes"]
    assert isinstance(attributes, Mapping)
    value = attributes["failure_class"]
    assert isinstance(value, str)
    return value


if __name__ == "__main__":
    unittest.main()
