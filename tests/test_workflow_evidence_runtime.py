from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import AsyncIterator
from collections.abc import Iterator, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from asterion.pathlight import (
    ContextFrameObservation,
    ContextSegmentSummary,
    MemoryPathlightRecorder,
    ModelCallObservation,
    RuntimeObservationBatch,
    ToolCallObservation,
    TraceEvent,
)
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


class NonmonotonicClock:
    def __init__(self) -> None:
        self.values = iter((1_000, 1_010, 1_005, *range(1_020, 1_200, 10)))

    def __call__(self) -> int:
        return next(self.values)


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


class RichRejectingRecorder:
    """Atomically reject rich candidates while accepting fallback candidates."""

    def __init__(self) -> None:
        self._recorder = MemoryPathlightRecorder(TRACE_ID)
        self.record_many_calls = 0

    @property
    def trace_id(self) -> str:
        return self._recorder.trace_id

    @property
    def next_sequence(self) -> int:
        return self._recorder.next_sequence

    @property
    def active_span_id(self) -> str | None:
        return self._recorder.active_span_id

    def record(self, event: TraceEvent) -> None:
        self._recorder.record(event)

    def record_many(self, events: tuple[TraceEvent, ...]) -> None:
        self.record_many_calls += 1
        if any(event.kind == "model-call" for event in events):
            raise RuntimeError("SENTINEL_RICH_REJECTION")
        self._recorder.record_many(events)

    def snapshot(self) -> Mapping[str, object]:
        return self._recorder.snapshot()


class HostileObservationMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        del key
        raise RuntimeError("SENTINEL_HOSTILE_SOURCE")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("SENTINEL_HOSTILE_SOURCE")

    def __len__(self) -> int:
        raise RuntimeError("SENTINEL_HOSTILE_SOURCE")


class PropertyExplodingRuntime(EventRuntime):
    def __init__(self) -> None:
        super().__init__(_native_events())

    @property
    def pathlight_runtime_observation(self) -> object:
        raise RuntimeError("SENTINEL_SOURCE_PROPERTY")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request() -> RunRequest:
    return RunRequest(run_id="native-run", input_text="SENTINEL_NATIVE_INPUT")


def _native_events() -> tuple[tuple[str, dict[str, object]], ...]:
    return (
        ("run.started", {"capabilities": []}),
        (
            "tool.call",
            {
                "call_id": "SENTINEL_NATIVE_CALL",
                "name": "private.native.tool",
                "arguments": {"query": "SENTINEL_NATIVE_ARGUMENT"},
            },
        ),
        (
            "tool.result",
            {
                "call_id": "SENTINEL_NATIVE_CALL",
                "output": "SENTINEL_NATIVE_RESULT",
                "is_error": False,
            },
        ),
        ("usage.reported", {"input_tokens": 7, "output_tokens": 11}),
        ("run.completed", {"status": "completed"}),
    )


def _batch(
    *,
    wrong_tool_digest: bool = False,
    run_id: str = "native-run",
) -> RuntimeObservationBatch:
    tool = ToolCallObservation(
        call_sha256=_digest("SENTINEL_NATIVE_CALL"),
        tool_sha256=_digest("private.native.tool"),
        arguments_sha256=_digest(
            json.dumps(
                {"query": "WRONG" if wrong_tool_digest else "SENTINEL_NATIVE_ARGUMENT"},
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
        result_sha256=_digest("SENTINEL_NATIVE_RESULT"),
        result_length=len("SENTINEL_NATIVE_RESULT"),
        status="completed",
    )
    frame = ContextFrameObservation(
        frame_index=1,
        segments=(
            ContextSegmentSummary(
                segment_index=0,
                role="user",
                structure_kind="message",
                content_sha256=_digest("SENTINEL_NATIVE_INPUT"),
                content_length=len("SENTINEL_NATIVE_INPUT"),
                source_call_sha256=None,
                missing_evidence=False,
            ),
            ContextSegmentSummary(
                segment_index=1,
                role="assistant",
                structure_kind="message",
                content_sha256=_digest("SENTINEL_MODEL_RESPONSE"),
                content_length=len("SENTINEL_MODEL_RESPONSE"),
                source_call_sha256=None,
                missing_evidence=False,
            ),
            ContextSegmentSummary(
                segment_index=2,
                role="tool-result",
                structure_kind="tool-result",
                content_sha256=tool.result_sha256,
                content_length=tool.result_length,
                source_call_sha256=tool.call_sha256,
                missing_evidence=False,
            ),
        ),
    )
    model_calls = tuple(
        ModelCallObservation(
            request_index=index,
            frame_sha256=frame.frame_sha256,
            model_sha256=_digest("private.model"),
            request_sha256=_digest(f"SENTINEL_MODEL_REQUEST_{index}"),
            response_sha256=_digest(f"SENTINEL_MODEL_RESPONSE_{index}"),
            response_length=len(f"SENTINEL_MODEL_RESPONSE_{index}"),
            input_tokens=index + 2,
            output_tokens=index + 3,
            status="completed",
            boundary_observed=True,
        )
        for index in (1, 2)
    )
    return RuntimeObservationBatch.build(
        run_sha256=_digest(run_id),
        frames=(frame,),
        model_calls=model_calls,
        tools=(tool,),
    )


class ObservedFixtureRuntime(EventRuntime):
    def __init__(
        self,
        observation: Mapping[str, object],
        events: tuple[tuple[str, dict[str, object]], ...] | None = None,
    ) -> None:
        super().__init__(_native_events() if events is None else events)
        self.observation = observation

    def pathlight_runtime_observation(self, run_id: str) -> Mapping[str, object] | None:
        del run_id
        return self.observation


def _started_events(graph: Mapping[str, object]) -> list[Mapping[str, object]]:
    events = cast(list[Mapping[str, object]], graph["events"])
    return [event for event in events if event["status"] == "started"]


def _kinds(graph: Mapping[str, object]) -> list[object]:
    return [event["kind"] for event in _started_events(graph)]


def _segment_indexes(graph: Mapping[str, object]) -> list[object]:
    return [
        attributes["segment_index"]
        for event in _started_events(graph)
        if "segment_index" in (attributes := cast(Mapping[str, object], event["attributes"]))
    ]


def _relations(graph: Mapping[str, object]) -> list[object]:
    events = cast(list[Mapping[str, object]], graph["events"])
    return [link["relation"] for event in events for link in event["links"]]


def _context_frames(graph: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [event for event in _started_events(graph) if event["kind"] == "context-frame"]


class WorkflowEvidenceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_observation_projects_frame_segments_model_calls_and_tool_flow(
        self,
    ) -> None:
        runtime = ObservedFixtureRuntime(_batch().to_mapping())
        recorder = MemoryPathlightRecorder(TRACE_ID)
        observed = ObservedRuntimeClient(
            runtime,
            pathlight=recorder,
            monotonic_ns=IncrementingClock(),
        )

        yielded = [event async for event in observed.run(_request())]
        graph = recorder.snapshot()

        self.assertEqual(yielded, runtime.yielded)
        self.assertEqual(_kinds(graph).count("model-call"), 2)
        self.assertEqual(_segment_indexes(graph), [0, 1, 2])
        self.assertIn("consumed-by", _relations(graph))
        self.assertIn("produced-by", _relations(graph))
        self.assertFalse(
            any(
                event["attributes"].get("missing_evidence") is True
                for event in _context_frames(graph)
            )
        )
        self.assertNotIn("SENTINEL", repr(graph))

    async def test_native_projection_failure_atomically_retries_fallback(self) -> None:
        runtime = ObservedFixtureRuntime(_batch().to_mapping())
        recorder = RichRejectingRecorder()
        observed = ObservedRuntimeClient(runtime, pathlight=recorder)

        yielded = [event async for event in observed.run(_request())]
        graph = recorder.snapshot()

        self.assertEqual(yielded, runtime.yielded)
        self.assertEqual(recorder.record_many_calls, 2)
        self.assertNotIn("model-call", _kinds(graph))
        self.assertTrue(_context_frames(graph)[0]["attributes"]["missing_evidence"])
        self.assertNotIn("SENTINEL", repr(graph))

    async def test_hostile_cross_run_and_noncanonical_sources_fail_closed_to_fallback(
        self,
    ) -> None:
        duplicate_frame = _batch().to_mapping()
        duplicate_frame["frames"].append(duplicate_frame["frames"][0])
        duplicate_tool = _batch().to_mapping()
        duplicate_tool["tools"].append(duplicate_tool["tools"][0])
        cases = (
            PropertyExplodingRuntime(),
            ObservedFixtureRuntime(HostileObservationMapping()),
            ObservedFixtureRuntime(_batch(run_id="foreign-run").to_mapping()),
            ObservedFixtureRuntime(
                RuntimeObservationBatch.build(
                    run_sha256=_digest("native-run"),
                    frames=(),
                    model_calls=(),
                    tools=(),
                    missing_evidence=(
                        "context-frame",
                        "model-request",
                        "model-request-boundary",
                    ),
                ).to_mapping(),
                (
                    ("run.started", {"capabilities": []}),
                    ("run.completed", {"status": "completed"}),
                ),
            ),
            ObservedFixtureRuntime(duplicate_frame),
            ObservedFixtureRuntime(duplicate_tool),
        )
        for index, runtime in enumerate(cases, start=20):
            with self.subTest(runtime=type(runtime).__name__, index=index):
                recorder = MemoryPathlightRecorder(
                    f"00000000-0000-4000-8000-{index:012x}"
                )
                observed = ObservedRuntimeClient(runtime, pathlight=recorder)

                yielded = [event async for event in observed.run(_request())]
                graph = recorder.snapshot()

                self.assertEqual(yielded, runtime.yielded)
                self.assertNotIn("model-call", _kinds(graph))
                self.assertTrue(
                    _context_frames(graph)[0]["attributes"]["missing_evidence"]
                )
                self.assertNotIn("SENTINEL", repr(graph))

    async def test_nonmonotonic_observation_clock_falls_back_without_partial_rich_trace(
        self,
    ) -> None:
        runtime = ObservedFixtureRuntime(_batch().to_mapping())
        recorder = MemoryPathlightRecorder(TRACE_ID)
        observed = ObservedRuntimeClient(
            runtime,
            pathlight=recorder,
            monotonic_ns=NonmonotonicClock(),
        )

        yielded = [event async for event in observed.run(_request())]
        graph = recorder.snapshot()

        self.assertEqual(yielded, runtime.yielded)
        self.assertNotIn("model-call", _kinds(graph))
        self.assertTrue(_context_frames(graph)[0]["attributes"]["missing_evidence"])
        self.assertNotIn("SENTINEL", repr(graph))

    async def test_mismatched_native_tool_digest_does_not_publish_a_partial_rich_trace(
        self,
    ) -> None:
        runtime = ObservedFixtureRuntime(_batch(wrong_tool_digest=True).to_mapping())
        recorder = MemoryPathlightRecorder(TRACE_ID)
        observed = ObservedRuntimeClient(runtime, pathlight=recorder)

        yielded = [event async for event in observed.run(_request())]
        graph = recorder.snapshot()

        self.assertEqual(yielded, runtime.yielded)
        self.assertNotIn("model-call", _kinds(graph))
        self.assertTrue(_context_frames(graph)[0]["attributes"]["missing_evidence"])
        self.assertNotIn("SENTINEL", repr(graph))

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
