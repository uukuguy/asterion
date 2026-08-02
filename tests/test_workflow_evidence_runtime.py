from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import AsyncIterator

from asterion.pathlight import MemoryPathlightRecorder
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.workflow_evidence import ObservedRuntimeClient


TRACE_ID = "00000000-0000-4000-8000-000000000001"


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


class WorkflowEvidenceRuntimeTests(unittest.IsolatedAsyncioTestCase):
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
                        and item["status"] == "started"
                        and item["attributes"]
                    )
                    self.assertEqual(
                        usage["attributes"],
                        {
                            "metric_name": "input-tokens",
                            "metric_value": 3,
                            "unit": "tokens",
                        },
                    )
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
        for index, (runtime, error) in enumerate(
            ((FailingRuntime(), RuntimeError), (invalid_runtime, ValueError)), start=5
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
                            RunRequest(run_id="run-1", input_text="SENTINEL_INPUT")
                        )
                    ]

                graph = recorder.snapshot()
                self.assertEqual(graph["events"][-1]["status"], "failed")
                self.assertNotIn("SENTINEL", repr(graph))

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
