from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import AsyncIterator
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from asterion.pathlight import MemoryPathlightRecorder, TraceEvent
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.workflow_evidence import ObservedRuntimeClient
from asterion.workflow_evidence.storage import write_workflow_observation_bundle


TRACE_ID = "00000000-0000-4000-8000-000000000001"
ROOT_SPAN_ID = "00000000-0000-4000-8000-000000000010"
PLAN_SPAN_ID = "00000000-0000-4000-8000-000000000011"
CAPABILITY_SPAN_ID = "00000000-0000-4000-8000-000000000012"


class CompletedRuntime:
    manifest = RuntimeManifest(runtime_id="fixture.runtime", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "answer",
                    "kind": "answer",
                    "media_type": "text/plain",
                    "uri": "file:///private/SENTINEL_ARTIFACT",
                    "sha256": "b" * 64,
                }
            },
        )
        yield RunEvent(
            request.run_id,
            3,
            "usage.reported",
            {"input_tokens": 3, "output_tokens": 5},
        )
        yield RunEvent(request.run_id, 4, "run.completed", {"status": "completed"})


class FailingRuntime:
    manifest = RuntimeManifest(runtime_id="fixture.runtime", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        raise RuntimeError("SENTINEL_PRIVATE_FAILURE")
        yield RunEvent("unreachable", 1, "run.started", {})


class ToolRuntime:
    manifest = RuntimeManifest(runtime_id="fixture.runtime", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(
            request.run_id,
            2,
            "tool.call",
            {
                "call_id": "SENTINEL_PRIVATE_CALL",
                "name": "private.tool",
                "arguments": {"query": "SENTINEL_SECRET_ARGUMENT"},
            },
        )
        yield RunEvent(
            request.run_id,
            3,
            "tool.result",
            {
                "call_id": "SENTINEL_PRIVATE_CALL",
                "output": "SENTINEL_PRIVATE_RESULT",
                "is_error": False,
            },
        )
        yield RunEvent(request.run_id, 4, "run.completed", {"status": "completed"})


class EventRuntime:
    manifest = RuntimeManifest(runtime_id="fixture.runtime", capabilities=())

    def __init__(self, events: tuple[tuple[str, dict[str, object]], ...]) -> None:
        self.events = events
        self.yielded: list[RunEvent] = []

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        for sequence, (event_type, payload) in enumerate(self.events, start=1):
            event = RunEvent(request.run_id, sequence, event_type, payload)
            self.yielded.append(event)
            yield event


class CancelledSignal:
    cancelled = True


class IncrementingClock:
    def __init__(self, start: int = 1_000) -> None:
        self.value = start

    def __call__(self) -> int:
        value = self.value
        self.value += 10
        return value


class RepeatedClock:
    def __init__(self, value: int = 1_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class PrefixRejectingRecorder:
    """Reject a batch after inspecting its prefix without committing it."""

    def __init__(self) -> None:
        self.trace_id = TRACE_ID
        self.next_sequence = 1
        self.active_span_id = None
        self._accepted: list[TraceEvent] = []
        self.record_many_calls = 0

    @property
    def event_count(self) -> int:
        return len(self._accepted)

    def record(self, event: TraceEvent) -> None:
        self._accepted.append(event)
        if len(self._accepted) == 3:
            raise RuntimeError("recorder rejected trace after a prefix")

    def record_many(self, events: tuple[TraceEvent, ...]) -> None:
        self.record_many_calls += 1
        for index, event in enumerate(events, start=1):
            assert isinstance(event, TraceEvent)
            if index == 3:
                raise RuntimeError("recorder rejected trace after a prefix")
        self._accepted.extend(events)

    def snapshot(self) -> None:
        return None


class WorkflowEvidenceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_projection_rejection_does_not_persist_a_partial_trace(self) -> None:
        recorder = PrefixRejectingRecorder()
        observed = ObservedRuntimeClient(
            CompletedRuntime(),
            pathlight=recorder,
            monotonic_ns=IncrementingClock(),
        )

        events = [
            event
            async for event in observed.run(
                RunRequest(run_id="run-1", input_text="SENTINEL_SECRET_INPUT")
            )
        ]

        self.assertEqual(events[-1].type, "run.completed")
        self.assertEqual(len(observed.records), 1)
        self.assertEqual(recorder.record_many_calls, 1)
        self.assertEqual(recorder.event_count, 0)
        self.assertIsNone(recorder.snapshot())

    async def test_repeated_clock_values_keep_runtime_projection_complete(self) -> None:
        runtime = CompletedRuntime()
        recorder = MemoryPathlightRecorder(TRACE_ID)
        observed = ObservedRuntimeClient(
            runtime,
            pathlight=recorder,
            monotonic_ns=RepeatedClock(),
        )

        events = [
            event
            async for event in observed.run(
                RunRequest(run_id="run-1", input_text="SENTINEL_SECRET_INPUT")
            )
        ]

        self.assertEqual(
            [event.type for event in events],
            [
                "run.started",
                "artifact.created",
                "usage.reported",
                "run.completed",
            ],
        )
        self.assertEqual(len(observed.records), 1)
        graph = recorder.snapshot()
        with TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "workflow-evidence.json"
            write_workflow_observation_bundle(
                target,
                observed.records,
                pathlight_traces=(graph,),
            )
            exported = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(exported["pathlight_traces"][0]["trace_id"], TRACE_ID)
        trace_events = cast(list[Mapping[str, object]], graph["events"])
        starts = {
            event["span_id"]: event
            for event in trace_events
            if event["status"] == "started"
        }
        for event in trace_events:
            if event["status"] != "started":
                attributes = cast(Mapping[str, object], event["attributes"])
                self.assertGreater(attributes["duration_ns"], 0)
                self.assertEqual(
                    attributes["duration_ns"],
                    event["timestamp_ns"] - starts[event["span_id"]]["timestamp_ns"],
                )

    async def test_runtime_trace_has_safe_identity_timing_tokens_and_artifact(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        observed = ObservedRuntimeClient(
            CompletedRuntime(),
            pathlight=recorder,
            monotonic_ns=IncrementingClock(),
        )

        _ = [
            event
            async for event in observed.run(
                RunRequest(
                    run_id="SENTINEL-PRIVATE-RUN",
                    input_text="SENTINEL_SECRET_INPUT",
                )
            )
        ]

        graph = recorder.snapshot()
        events = cast(list[Mapping[str, object]], graph["events"])
        starts = {item["span_id"]: item for item in events if item["status"] == "started"}
        runtime_start = next(
            item
            for item in events
            if item["kind"] == "runtime" and item["status"] == "started"
        )
        runtime_terminal = next(
            item
            for item in events
            if item["span_id"] == runtime_start["span_id"]
            and item["status"] == "completed"
        )
        start_attributes = cast(Mapping[str, object], runtime_start["attributes"])
        terminal_attributes = cast(Mapping[str, object], runtime_terminal["attributes"])
        self.assertEqual(
            start_attributes["run_sha256"],
            hashlib.sha256(b"SENTINEL-PRIVATE-RUN").hexdigest(),
        )
        self.assertEqual(
            start_attributes["runtime_sha256"],
            hashlib.sha256(b"fixture.runtime").hexdigest(),
        )
        self.assertEqual(terminal_attributes["input_tokens"], 3)
        self.assertEqual(terminal_attributes["output_tokens"], 5)
        self.assertNotIn("cost_microunits", terminal_attributes)
        self.assertGreater(terminal_attributes["duration_ns"], 0)
        self.assertIn("artifact", [item["kind"] for item in events])
        for item in events:
            self.assertGreater(item["timestamp_ns"], 0)
            if item["status"] != "started":
                attributes = cast(Mapping[str, object], item["attributes"])
                self.assertEqual(
                    attributes["duration_ns"],
                    item["timestamp_ns"] - starts[item["span_id"]]["timestamp_ns"],
                )
                self.assertGreater(attributes["duration_ns"], 0)
        rendered = json.dumps(graph, default=dict, sort_keys=True)
        for source in (
            "SENTINEL-PRIVATE-RUN",
            "fixture.runtime",
            "answer",
            "text/plain",
            "SENTINEL_ARTIFACT",
            "SENTINEL_SECRET_INPUT",
        ):
            self.assertNotIn(source, rendered)

    async def test_projection_composes_with_open_lifecycle_trace(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        recorder.record(TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"))
        recorder.record(TraceEvent.start(TRACE_ID, PLAN_SPAN_ID, ROOT_SPAN_ID, 2, "plan"))
        recorder.record(
            TraceEvent.start(TRACE_ID, CAPABILITY_SPAN_ID, PLAN_SPAN_ID, 3, "task")
        )
        observed = ObservedRuntimeClient(ToolRuntime(), pathlight=recorder)

        events = [
            event
            async for event in observed.run(
                RunRequest(run_id="run-1", input_text="SENTINEL_SECRET_INPUT")
            )
        ]

        recorder.record(
            TraceEvent.complete(
                TRACE_ID, CAPABILITY_SPAN_ID, recorder.next_sequence, kind="task"
            )
        )
        recorder.record(
            TraceEvent.complete(TRACE_ID, PLAN_SPAN_ID, recorder.next_sequence, kind="plan")
        )
        recorder.record(TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, recorder.next_sequence))

        self.assertEqual(events[-1].type, "run.completed")
        graph = recorder.snapshot()
        runtime_start = next(
            item
            for item in graph["events"]
            if item["kind"] == "runtime" and item["status"] == "started"
        )
        self.assertEqual(runtime_start["parent_span_id"], CAPABILITY_SPAN_ID)

    async def test_observed_runtime_links_tool_result_to_next_context_frame(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        observed = ObservedRuntimeClient(ToolRuntime(), pathlight=recorder)

        events = [
            event
            async for event in observed.run(
                RunRequest(run_id="run-1", input_text="SENTINEL_SECRET_INPUT")
            )
        ]

        self.assertEqual([event.type for event in events], [
            "run.started",
            "tool.call",
            "tool.result",
            "run.completed",
        ])
        graph = recorder.snapshot()
        tool_result = next(
            item
            for item in graph["events"]
            if item["kind"] == "tool-call" and item["status"] == "completed"
        )
        self.assertIn("derived-from", [link["relation"] for link in tool_result["links"]])
        next_context = next(
            item
            for item in graph["events"]
            if item["kind"] == "context-frame"
            and item["status"] == "started"
            and any(link["span_id"] == tool_result["span_id"] for link in item["links"])
        )
        self.assertIn("derived-from", [link["relation"] for link in next_context["links"]])
        self.assertNotIn("model-call", [item["kind"] for item in graph["events"]])
        self.assertTrue(next_context["attributes"]["missing_evidence"])
        self.assertNotIn("SENTINEL_SECRET", repr(graph))
        self.assertNotIn("SENTINEL_PRIVATE", repr(graph))

    async def test_runtime_pathlight_projection_handles_safe_terminal_matrix(self) -> None:
        cases = {
            "tool-error": (
                (
                    ("run.started", {"capabilities": []}),
                    (
                        "tool.call",
                        {
                            "call_id": "SENTINEL_CALL",
                            "name": "private.tool",
                            "arguments": {"secret": "SENTINEL_ARGUMENT"},
                        },
                    ),
                    (
                        "tool.result",
                        {
                            "call_id": "SENTINEL_CALL",
                            "output": "SENTINEL_RESULT",
                            "is_error": True,
                        },
                    ),
                    ("run.completed", {"status": "completed"}),
                ),
                None,
                "completed",
                "failed",
            ),
            "cancelled": (
                (
                    ("run.started", {"capabilities": []}),
                    ("run.completed", {"status": "cancelled"}),
                ),
                CancelledSignal(),
                "cancelled",
                None,
            ),
            "usage-only": (
                (
                    ("run.started", {"capabilities": []}),
                    ("usage.reported", {"input_tokens": 3, "output_tokens": 5}),
                    ("run.completed", {"status": "completed"}),
                ),
                None,
                "completed",
                None,
            ),
        }
        for index, (name, (event_specs, signal, status, tool_status)) in enumerate(
            cases.items(), start=2
        ):
            with self.subTest(name=name):
                runtime = EventRuntime(event_specs)
                recorder = MemoryPathlightRecorder(
                    f"00000000-0000-4000-8000-{index:012x}"
                )
                observed = ObservedRuntimeClient(runtime, pathlight=recorder)

                events = [
                    event
                    async for event in observed.run(
                        RunRequest(run_id="run-1", input_text="SENTINEL_INPUT"),
                        signal=signal,
                    )
                ]

                self.assertEqual(events, runtime.yielded)
                self.assertTrue(all(left is right for left, right in zip(events, runtime.yielded)))
                graph = recorder.snapshot()
                root_terminal = graph["events"][-1]
                self.assertEqual(root_terminal["kind"], "runtime")
                self.assertEqual(root_terminal["status"], status)
                if tool_status is not None:
                    self.assertEqual(
                        next(
                            item["status"]
                            for item in graph["events"]
                            if item["kind"] == "tool-call"
                            and item["status"] != "started"
                        ),
                        tool_status,
                    )
                if name == "usage-only":
                    usage = next(
                        item
                        for item in graph["events"]
                        if item["kind"] == "runtime"
                        and item["status"] == "completed"
                    )
                    self.assertEqual(usage["attributes"]["input_tokens"], 3)
                    self.assertEqual(usage["attributes"]["output_tokens"], 5)
                    self.assertNotIn("cost_microunits", usage["attributes"])
                self.assertNotIn("SENTINEL", repr(graph))

    async def test_pathlight_failure_graph_redacts_stream_exception_and_invalid_tool_event(
        self,
    ) -> None:
        invalid_runtime = EventRuntime(
            (
                ("run.started", {"capabilities": []}),
                (
                    "tool.result",
                    {
                        "call_id": "SENTINEL_UNMATCHED_CALL",
                        "output": "SENTINEL_UNMATCHED_RESULT",
                        "is_error": False,
                    },
                ),
                ("run.completed", {"status": "completed"}),
            )
        )
        for index, (runtime, error, signal) in enumerate(
            (
                (FailingRuntime(), RuntimeError, CancelledSignal()),
                (invalid_runtime, ValueError, None),
            ),
            start=5,
        ):
            with self.subTest(runtime=type(runtime).__name__):
                recorder = MemoryPathlightRecorder(
                    f"00000000-0000-4000-8000-{index:012x}"
                )
                observed = ObservedRuntimeClient(runtime, pathlight=recorder)

                with self.assertRaises(error):
                    _ = [
                        event
                        async for event in observed.run(
                            RunRequest(run_id="run-1", input_text="SENTINEL_INPUT"),
                            signal=signal,
                        )
                    ]

                self.assertEqual(recorder.event_count, 0)

    async def test_records_a_validated_runtime_stream_without_input_or_uri(self) -> None:
        observed = ObservedRuntimeClient(CompletedRuntime())

        events = [
            event
            async for event in observed.run(
                RunRequest(run_id="run-1", input_text="SENTINEL_SECRET_INPUT")
            )
        ]

        self.assertEqual(events[-1].type, "run.completed")
        self.assertEqual(observed.manifest.runtime_id, "fixture.runtime")
        self.assertEqual(len(observed.records), 1)
        record = observed.records[0]
        self.assertEqual(record["schema"], "asterion.workflow-evidence/v1")
        self.assertEqual(record["run_id"], "run-1")
        self.assertEqual(
            record["input_digest"],
            hashlib.sha256(b"SENTINEL_SECRET_INPUT").hexdigest(),
        )
        rendered = json.dumps(dict(record), sort_keys=True)
        self.assertNotIn("SENTINEL_SECRET_INPUT", rendered)
        self.assertNotIn("SENTINEL_ARTIFACT", rendered)

    async def test_records_fixed_failure_class_without_exception_text(self) -> None:
        observed = ObservedRuntimeClient(FailingRuntime())

        with self.assertRaises(RuntimeError):
            _ = [
                event
                async for event in observed.run(
                    RunRequest(run_id="run-2", input_text="SENTINEL_SECRET_INPUT")
                )
            ]

        self.assertEqual(observed.records, ())
        self.assertEqual(observed.failed_attempts, (
            {
                "schema": "asterion.workflow-observation/v1",
                "run_id": "run-2",
                "input_digest": hashlib.sha256(b"SENTINEL_SECRET_INPUT").hexdigest(),
                "status": "failed",
                "failure_class": "runtime-invocation-failed",
            },
        ))
        self.assertNotIn(
            "SENTINEL_PRIVATE_FAILURE",
            json.dumps([dict(item) for item in observed.failed_attempts]),
        )


if __name__ == "__main__":
    unittest.main()
