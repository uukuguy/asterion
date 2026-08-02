from __future__ import annotations

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


class RaisingRecorder:
    trace_id = TRACE_ID

    def record(self, event: object) -> None:
        del event
        raise RuntimeError("recorder failure")

    def snapshot(self) -> None:
        return None


def trace_events(recorder: MemoryPathlightRecorder) -> Sequence[Mapping[str, object]]:
    snapshot = recorder.snapshot()
    events = snapshot["events"]
    assert isinstance(events, list)
    assert all(isinstance(event, Mapping) for event in events)
    return tuple(cast(Mapping[str, object], event) for event in events)


def plan():
    manifest = {
        "protocol": "asterion.capability/v1",
        "capability_id": "trace.capability",
        "version": "1.0.0",
        "kind": "capability",
        "provides_capabilities": [],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": [],
        "consumes_events": [],
        "produces_artifacts": [],
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
                ("plan", "started"),
                ("task", "started"),
                ("task", "completed"),
                ("plan", "completed"),
                ("task", "completed"),
            ],
        )
        self.assertIsNone(events[0]["parent_span_id"])
        self.assertEqual(events[1]["parent_span_id"], events[0]["span_id"])
        self.assertEqual(events[2]["parent_span_id"], events[1]["span_id"])
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
        self.assertEqual(len(failed), 3)
        self.assertEqual(
            [failure_class(item) for item in failed],
            ["capability-execution-failed"] * 3,
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
                ("plan", "started"),
                ("plan", "cancelled"),
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
            ["started", "started", "started", "failed", "failed", "failed"],
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


def failure_class(event: Mapping[str, object]) -> str:
    attributes = event["attributes"]
    assert isinstance(attributes, Mapping)
    value = attributes["failure_class"]
    assert isinstance(value, str)
    return value


if __name__ == "__main__":
    unittest.main()
