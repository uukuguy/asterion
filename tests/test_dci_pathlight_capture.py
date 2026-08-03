from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.dci.implementation.config import DciPaths, DciPiPaths
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    DciArtifactError,
    DciRunRecorder,
)
from asterion.capabilities.dci.implementation.runtime.run import (
    DciRunError,
    DciRunRequest,
    run_pi_research,
)
from asterion.workflow_evidence import read_workflow_observation_bundle


_SENTINEL = "SENTINEL_PRIVATE_DCI_CONTENT"


class _CompletedClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "agent_start"},
            {
                "type": "message_end",
                "message": _assistant_message("answer", input_tokens=1, output_tokens=1),
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "answer"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


class _BrokenObservationBuilder:
    def __init__(self, *_args: object) -> None:
        pass

    def checkpoint(self) -> object:
        return object()

    def consume(self, *_args: object) -> None:
        raise ValueError("injected observation failure")


def _paths(root: Path) -> DciPaths:
    pi = root / "pi"
    package = pi / "package"
    agent = pi / "agent"
    package.mkdir(parents=True)
    agent.mkdir()
    return DciPaths(
        repo_root=root,
        pi=DciPiPaths(repo_dir=pi, package_dir=package, agent_dir=agent),
        output_root=root,
    )


def _assistant_message(text: str, *, input_tokens: int, output_tokens: int) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "stopReason": "stop",
        "usage": {"input": input_tokens, "output": output_tokens},
    }


def _started_kinds(trace: Mapping[str, object]) -> list[str]:
    events = trace["events"]
    assert isinstance(events, tuple)
    return [
        str(event["kind"])
        for event in events
        if isinstance(event, Mapping) and event["status"] == "started"
    ]


class DciPathlightCaptureTests(unittest.TestCase):
    def test_message_start_reconstructs_safe_model_mainline_without_context_hook(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "message-boundary"
            request = DciRunRequest(
                run_id="message-boundary-run",
                question=f"question-{_SENTINEL}",
                cwd=root,
                tools="read",
                timeout_seconds=None,
            )
            first_assistant = _assistant_message(
                f"tool-request-{_SENTINEL}", input_tokens=10, output_tokens=2
            )
            final_assistant = _assistant_message(
                f"answer-{_SENTINEL}", input_tokens=14, output_tokens=3
            )
            with DciRunRecorder(
                output_dir=output,
                request=request,
                paths=_paths(root),
            ) as recorder:
                for event in (
                    {"type": "agent_start"},
                    {
                        "type": "message_end",
                        "message": {
                            "role": "user",
                            "content": f"question-{_SENTINEL}",
                        },
                    },
                    {
                        "type": "message_start",
                        "message": {
                            "role": "assistant",
                            "provider": "private-provider",
                            "model": "private-model",
                            "content": [],
                        },
                    },
                    {"type": "message_end", "message": first_assistant},
                    {
                        "type": "tool_execution_start",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "args": {"path": f"private-{_SENTINEL}.txt"},
                    },
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "result": f"result-{_SENTINEL}",
                        "isError": False,
                    },
                    {
                        "type": "message_end",
                        "message": {
                            "role": "toolResult",
                            "toolCallId": "call-1",
                            "content": f"result-{_SENTINEL}",
                        },
                    },
                    {
                        "type": "message_start",
                        "message": {
                            "role": "assistant",
                            "provider": "private-provider",
                            "model": "private-model",
                            "content": [],
                        },
                    },
                    {"type": "message_end", "message": final_assistant},
                    {"type": "agent_end", "willRetry": None},
                ):
                    recorder.record_event(event)
                recorder.finalize(
                    status="completed",
                    final_text=f"answer-{_SENTINEL}",
                    release_lock=False,
                )
                recorder.persist_workflow_evidence()

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            trace = bundle.pathlight_traces[0]
            kinds = _started_kinds(trace)
            self.assertEqual(kinds.count("model-call"), 2)
            self.assertEqual(kinds.count("tool-call"), 1)
            self.assertEqual(
                sum(
                    "frame_index" in event["attributes"]
                    for event in trace["events"]
                    if event["kind"] == "context-frame"
                    and event["status"] == "started"
                ),
                2,
            )
            rendered = json.dumps(trace, default=dict, sort_keys=True)
            self.assertTrue(
                all(
                    event["attributes"]["missing_evidence"]
                    for event in trace["events"]
                    if event["kind"] == "model-call"
                    and event["status"] == "started"
                )
            )
            for private_value in (
                _SENTINEL,
                "private-provider",
                "private-model",
                str(root),
            ):
                self.assertNotIn(private_value, rendered)

    def test_completed_native_attempt_persists_safe_rich_workflow_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = _paths(root)
            output = root / "native"
            request = DciRunRequest(
                run_id="prospective-run",
                question=f"question-{_SENTINEL}",
                cwd=root,
                tools="read",
                timeout_seconds=None,
            )
            first_assistant = _assistant_message(
                f"tool-request-{_SENTINEL}", input_tokens=10, output_tokens=2
            )
            tool_result = {
                "role": "toolResult",
                "toolCallId": "call-1",
                "toolName": "read",
                "content": [{"type": "text", "text": f"result-{_SENTINEL}"}],
                "isError": False,
            }
            final_assistant = _assistant_message(
                f"answer-{_SENTINEL}", input_tokens=14, output_tokens=3
            )

            with DciRunRecorder(
                output_dir=output,
                request=request,
                paths=paths,
            ) as recorder:
                recorder.record_event({"type": "agent_start"})
                recorder.record_event(
                    {
                        "type": "provider_request_context",
                        "requestIndex": 1,
                        "provider": "private-provider",
                        "model": "private-model",
                        "messages": [
                            {"role": "user", "content": f"question-{_SENTINEL}"}
                        ],
                    }
                )
                recorder.record_event(
                    {"type": "message_end", "message": first_assistant}
                )
                recorder.record_event(
                    {
                        "type": "tool_execution_start",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "args": {"path": f"private-{_SENTINEL}.txt"},
                    }
                )
                recorder.record_event(
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "call-1",
                        "toolName": "read",
                        "result": f"result-{_SENTINEL}",
                        "isError": False,
                    }
                )
                recorder.record_event({"type": "message_end", "message": tool_result})
                recorder.record_event(
                    {
                        "type": "provider_request_context",
                        "requestIndex": 2,
                        "provider": "private-provider",
                        "model": "private-model",
                        "messages": [
                            {"role": "user", "content": f"question-{_SENTINEL}"},
                            first_assistant,
                            tool_result,
                        ],
                    }
                )
                recorder.record_event(
                    {"type": "message_end", "message": final_assistant}
                )
                recorder.finalize(
                    status="completed",
                    final_text=f"answer-{_SENTINEL}",
                    release_lock=False,
                )
                recorder.persist_workflow_evidence()

            evidence = output / "workflow-evidence.json"
            self.assertTrue(evidence.is_file())
            bundle = read_workflow_observation_bundle(evidence)
            self.assertEqual(len(bundle.records), 1)
            self.assertEqual(len(bundle.pathlight_traces), 1)
            kinds = _started_kinds(bundle.pathlight_traces[0])
            self.assertEqual(kinds.count("model-call"), 2)
            self.assertEqual(kinds.count("tool-call"), 1)
            self.assertEqual(
                sum(
                    "frame_index" in event["attributes"]
                    for event in bundle.pathlight_traces[0]["events"]
                    if event["kind"] == "context-frame"
                    and event["status"] == "started"
                ),
                2,
            )
            rendered = json.dumps(
                {
                    "records": bundle.records,
                    "traces": bundle.pathlight_traces,
                },
                default=dict,
                sort_keys=True,
            )
            for private_value in (
                _SENTINEL,
                "private-provider",
                "private-model",
                str(root),
            ):
                self.assertNotIn(private_value, rendered)

    def test_failed_attempt_does_not_publish_workflow_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "failed"
            with DciRunRecorder(
                output_dir=output,
                request=DciRunRequest(
                    run_id="failed-run",
                    question="question",
                    cwd=root,
                    tools="read",
                    timeout_seconds=None,
                ),
                paths=_paths(root),
            ) as recorder:
                recorder.record_event({"type": "agent_start"})
                recorder.finalize(status="failed", release_lock=False)

            self.assertFalse((output / "workflow-evidence.json").exists())

    def test_observation_failure_publishes_explicit_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "missing-observation"
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.artifacts.PiObservationBuilder",
                _BrokenObservationBuilder,
            ):
                with DciRunRecorder(
                    output_dir=output,
                    request=DciRunRequest(
                        run_id="missing-observation-run",
                        question="question",
                        cwd=root,
                        tools="read",
                        timeout_seconds=None,
                    ),
                    paths=_paths(root),
                ) as recorder:
                    recorder.record_event({"type": "agent_start"})
                    recorder.finalize(
                        status="completed", final_text="answer", release_lock=False
                    )
                    recorder.persist_workflow_evidence()

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            trace = bundle.pathlight_traces[0]
            self.assertNotIn("model-call", _started_kinds(trace))
            self.assertTrue(
                any(
                    event["kind"] == "context-frame"
                    and event["status"] == "started"
                    and event["attributes"]["missing_evidence"]
                    for event in trace["events"]
                )
            )

    def test_retry_rolls_back_abandoned_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "retry"
            with DciRunRecorder(
                output_dir=output,
                request=DciRunRequest(
                    run_id="retry-run",
                    question="question",
                    cwd=root,
                    tools="read",
                    timeout_seconds=None,
                ),
                paths=_paths(root),
            ) as recorder:
                for event in (
                    {"type": "agent_start"},
                    {
                        "type": "provider_request_context",
                        "requestIndex": 1,
                        "provider": "private-provider",
                        "model": "private-model",
                        "messages": [{"role": "user", "content": "abandoned"}],
                    },
                    {
                        "type": "message_end",
                        "message": _assistant_message(
                            "abandoned", input_tokens=5, output_tokens=1
                        ),
                    },
                    {"type": "agent_end", "willRetry": True},
                    {"type": "agent_start"},
                    {
                        "type": "provider_request_context",
                        "requestIndex": 2,
                        "provider": "private-provider",
                        "model": "private-model",
                        "messages": [{"role": "user", "content": "kept"}],
                    },
                    {
                        "type": "message_end",
                        "message": _assistant_message(
                            "kept", input_tokens=7, output_tokens=2
                        ),
                    },
                ):
                    recorder.record_event(event)
                recorder.finalize(
                    status="completed", final_text="kept", release_lock=False
                )
                recorder.persist_workflow_evidence()

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            self.assertEqual(
                _started_kinds(bundle.pathlight_traces[0]).count("model-call"), 1
            )

    def test_existing_workflow_bundle_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "existing"
            with DciRunRecorder(
                output_dir=output,
                request=DciRunRequest(
                    run_id="existing-run",
                    question="question",
                    cwd=root,
                    tools="read",
                    timeout_seconds=None,
                ),
                paths=_paths(root),
            ) as recorder:
                target = output / "workflow-evidence.json"
                target.write_text("foreign-evidence\n", encoding="utf-8")
                recorder.record_event({"type": "agent_start"})
                recorder.finalize(
                    status="completed", final_text="answer", release_lock=False
                )
                with self.assertRaises(DciArtifactError):
                    recorder.persist_workflow_evidence()

            self.assertEqual(target.read_text(encoding="utf-8"), "foreign-evidence\n")

    def test_writer_exception_does_not_change_completed_run_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = _paths(root)
            output = root / "writer-failure"
            request = DciRunRequest(
                run_id="writer-failure-run",
                question="question",
                cwd=root,
                tools="read",
                timeout_seconds=None,
            )
            with (
                patch(
                    "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                    _CompletedClient,
                ),
                patch.object(
                    DciRunRecorder,
                    "persist_workflow_evidence",
                    side_effect=OSError("injected writer failure"),
                ),
            ):
                result = run_pi_research(paths, request, output_dir=output)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_text, "answer")
            self.assertFalse((output / "workflow-evidence.json").exists())

    def test_cancelled_run_does_not_publish_workflow_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "cancelled"
            cancelled = threading.Event()
            cancelled.set()
            with patch(
                "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                _CompletedClient,
            ):
                with self.assertRaises(DciRunError):
                    run_pi_research(
                        _paths(root),
                        DciRunRequest(
                            run_id="cancelled-run",
                            question="question",
                            cwd=root,
                            tools="read",
                            timeout_seconds=None,
                        ),
                        output_dir=output,
                        _cancel_event=cancelled,
                    )

            self.assertFalse((output / "workflow-evidence.json").exists())


if __name__ == "__main__":
    unittest.main()
