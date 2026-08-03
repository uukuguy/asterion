from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asterion.capabilities.dci.implementation.config import DciPaths, DciPiPaths
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    DciArtifactError,
    DciRunRecorder,
)
from asterion.capabilities.dci.implementation.evaluation.provider_requests import (
    ProviderRequestCapture,
    ProviderRequestCaptureError,
)
from asterion.capabilities.dci.implementation.runtime.run import (
    DciRunError,
    DciRunRequest,
    run_pi_research,
)
from asterion.workflow_evidence import read_workflow_observation_bundle


_SENTINEL = "SENTINEL_PRIVATE_DCI_CONTENT"
_PROVIDER_FIXTURES = (
    Path(__file__).parent / "fixtures" / "pathlight-provider-request" / "v1"
)


def _provider_capture_pair(
    fixture_name: str, request_index: int
) -> tuple[bytes, dict[str, object]]:
    fixture = json.loads(
        _PROVIDER_FIXTURES.joinpath(fixture_name).read_text(encoding="utf-8")
    )
    payload = fixture["payload"]
    summary = fixture["summary"]
    assert isinstance(summary, dict)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    record = {
        "schema": "dci.private-provider-request/v1",
        "request_index": request_index,
        "captured_at": "2026-08-03T04:05:06.789Z",
        "payload_json": payload_json,
        "payload_sha256": summary["payload_sha256"],
        "payload_bytes": summary["payload_bytes"],
        "shape_sha256": summary["shape_sha256"],
        "summary_sha256": summary["summary_sha256"],
    }
    raw = (json.dumps(record, separators=(",", ":")) + "\n").encode()
    safe = {
        "schema": "dci.provider-request-observation/v1",
        "request_index": request_index,
        "capture_status": "captured",
        **summary,
    }
    return raw, safe


def _provider_entry(data: dict[str, object], request_index: int) -> dict[str, object]:
    return {
        "id": f"provider-request-{request_index}",
        "parentId": None,
        "timestamp": "2026-08-03T04:05:06.789Z",
        "type": "custom",
        "customType": "dci-provider-request-observation",
        "data": data,
    }


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
                "message": _assistant_message(
                    "answer", input_tokens=1, output_tokens=1
                ),
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "answer"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


class _CapturedClient:
    construction: dict[str, object] = {}
    stop_calls = 0
    write_capture = True

    def __init__(self, **kwargs: object) -> None:
        type(self).construction = dict(kwargs)
        type(self).stop_calls = 0
        self.observation_fd = kwargs.get("observation_fd")
        self.entries: tuple[dict[str, object], ...] = ()

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        pairs = (
            _provider_capture_pair("valid-simple.json", 1),
            _provider_capture_pair("valid-tools.json", 2),
        )
        assert isinstance(self.observation_fd, int)
        if self.write_capture:
            for raw, _safe in pairs:
                offset = 0
                while offset < len(raw):
                    offset += os.write(self.observation_fd, raw[offset:])
        self.entries = tuple(
            _provider_entry(safe, index) for index, (_raw, safe) in enumerate(pairs, 1)
        )
        for event in (
            {"type": "agent_start"},
            {
                "type": "message_start",
                "message": {
                    "role": "assistant",
                    "provider": f"provider-{_SENTINEL}",
                    "model": f"model-{_SENTINEL}",
                    "content": [],
                },
            },
            {
                "type": "message_end",
                "message": _assistant_message(
                    f"calling-{_SENTINEL}", input_tokens=5, output_tokens=1
                ),
            },
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
                "result": "tool result",
                "isError": False,
            },
            {
                "type": "message_end",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "call-1",
                    "content": "tool result",
                },
            },
            {
                "type": "message_start",
                "message": {
                    "role": "assistant",
                    "provider": f"provider-{_SENTINEL}",
                    "model": f"model-{_SENTINEL}",
                    "content": [],
                },
            },
            {
                "type": "message_end",
                "message": _assistant_message(
                    f"answer-{_SENTINEL}", input_tokens=7, output_tokens=2
                ),
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return f"answer-{_SENTINEL}"

    def get_provider_request_entries(self) -> tuple[dict[str, object], ...]:
        return self.entries

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        type(self).stop_calls += 1


class _MismatchedCapturedClient(_CapturedClient):
    def get_provider_request_entries(self) -> tuple[dict[str, object], ...]:
        entries = json.loads(json.dumps(self.entries))
        entries[0]["data"]["payload_sha256"] = "0" * 64
        return tuple(entries)


class _MissingCapturedClient(_CapturedClient):
    def get_provider_request_entries(self) -> tuple[dict[str, object], ...]:
        return self.entries[:1]


class _WriteFailedCapturedClient(_CapturedClient):
    write_capture = False


class _RpcFailedCapturedClient(_CapturedClient):
    def get_provider_request_entries(self) -> tuple[dict[str, object], ...]:
        raise RuntimeError("injected observer RPC failure")


class _PostRpcWriteClient(_CapturedClient):
    evidence_path: Path | None = None
    published_before_stop = False
    stop_calls = 0

    def stop(self) -> None:
        type(self).stop_calls += 1
        target = type(self).evidence_path
        type(self).published_before_stop = bool(target is not None and target.exists())
        assert isinstance(self.observation_fd, int)
        os.write(self.observation_fd, b"SENTINEL_POST_RPC_WRITE\n")


class _EarlyStopFailedClient(_CapturedClient):
    def stop(self) -> None:
        type(self).stop_calls += 1
        raise RuntimeError("injected early stop failure")


class _ProviderFailedClient:
    observation_fd: int | None = None

    def __init__(self, **kwargs: object) -> None:
        value = kwargs.get("observation_fd")
        type(self).observation_fd = value if isinstance(value, int) else None

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        on_event({"type": "agent_start"})
        raise RuntimeError("injected provider failure")

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


class _ConstructionFailedClient:
    observation_fd: int | None = None

    def __init__(self, **kwargs: object) -> None:
        value = kwargs.get("observation_fd")
        type(self).observation_fd = value if isinstance(value, int) else None
        raise RuntimeError("injected construction failure")


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


def _assistant_message(
    text: str, *, input_tokens: int, output_tokens: int
) -> dict[str, object]:
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
    def test_child_is_quiesced_before_capture_validation_and_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "post-rpc-write"
            _PostRpcWriteClient.evidence_path = output / "workflow-evidence.json"
            _PostRpcWriteClient.published_before_stop = False
            _PostRpcWriteClient.stop_calls = 0
            with patch(
                "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                _PostRpcWriteClient,
            ):
                result = run_pi_research(
                    _paths(root),
                    DciRunRequest(
                        run_id="post-rpc-write-run",
                        question=f"question-{_SENTINEL}",
                        cwd=root,
                        tools="read",
                        timeout_seconds=None,
                    ),
                    output_dir=output,
                )

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            model_calls = [
                event
                for event in bundle.pathlight_traces[0]["events"]
                if event["kind"] == "model-call" and event["status"] == "started"
            ]
            self.assertEqual(result.status, "completed")
            self.assertEqual(_PostRpcWriteClient.stop_calls, 1)
            self.assertFalse(_PostRpcWriteClient.published_before_stop)
            self.assertTrue(
                all("request_shape_sha256" not in event["attributes"] for event in model_calls)
            )
            capture = output / "provider-requests.jsonl"
            self.assertEqual(capture.stat().st_mode & 0o777, 0o400)
            with self.assertRaises(OSError):
                capture.open("ab").write(b"late-write")

    def test_early_stop_failure_is_single_attempt_and_observation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "early-stop-failure"
            with patch(
                "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                _EarlyStopFailedClient,
            ):
                result = run_pi_research(
                    _paths(root),
                    DciRunRequest(
                        run_id="early-stop-failure-run",
                        question=f"question-{_SENTINEL}",
                        cwd=root,
                        tools="read",
                        timeout_seconds=None,
                    ),
                    output_dir=output,
                )

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            model_calls = [
                event
                for event in bundle.pathlight_traces[0]["events"]
                if event["kind"] == "model-call" and event["status"] == "started"
            ]
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_text, f"answer-{_SENTINEL}")
            self.assertEqual(_EarlyStopFailedClient.stop_calls, 1)
            self.assertTrue(
                all("request_shape_sha256" not in event["attributes"] for event in model_calls)
            )
            self.assertEqual(
                (output / "provider-requests.jsonl").stat().st_mode & 0o777,
                0o600,
            )

    def test_validation_fsync_failure_preserves_result_and_seals_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "validation-fsync-failure"
            with (
                patch(
                    "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                    _CapturedClient,
                ),
                patch.object(
                    ProviderRequestCapture,
                    "validate",
                    autospec=True,
                    side_effect=ProviderRequestCaptureError(
                        "provider request capture is invalid"
                    ),
                ),
            ):
                result = run_pi_research(
                    _paths(root),
                    DciRunRequest(
                        run_id="validation-fsync-failure-run",
                        question=f"question-{_SENTINEL}",
                        cwd=root,
                        tools="read",
                        timeout_seconds=None,
                    ),
                    output_dir=output,
                )

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            model_calls = [
                event
                for event in bundle.pathlight_traces[0]["events"]
                if event["kind"] == "model-call" and event["status"] == "started"
            ]
            descriptor = _CapturedClient.construction["observation_fd"]
            assert isinstance(descriptor, int)
            self.assertEqual(result.status, "completed")
            self.assertEqual(_CapturedClient.stop_calls, 1)
            self.assertEqual(
                (output / "provider-requests.jsonl").stat().st_mode & 0o777,
                0o400,
            )
            with self.assertRaises(OSError):
                os.fstat(descriptor)
            self.assertTrue(
                all("request_shape_sha256" not in event["attributes"] for event in model_calls)
            )

    def test_capture_close_failure_keeps_fallback_and_runs_all_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "capture-close-failure"
            extension = root / "observation.ts"
            extension.write_text("fixture", encoding="utf-8")
            cleanup: list[str] = []
            capture_close_calls = 0
            recorder_close = DciRunRecorder.close
            capture_close = ProviderRequestCapture.close

            @contextmanager
            def resolver():
                try:
                    yield SimpleNamespace(
                        path=extension,
                        contract_version="dci.pathlight-provider-request-capture/v1",
                    )
                finally:
                    cleanup.append("extension")

            def tracked_recorder_close(recorder: DciRunRecorder) -> None:
                cleanup.append("recorder")
                recorder_close(recorder)

            def failing_capture_close(capture: ProviderRequestCapture) -> None:
                nonlocal capture_close_calls
                capture_close_calls += 1
                cleanup.append("capture")
                capture_close(capture)
                if capture_close_calls == 1:
                    raise ProviderRequestCaptureError(
                        "provider request capture is invalid"
                    )

            with (
                patch(
                    "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                    _CapturedClient,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.research.pathlight_observation.resolve_pathlight_observation_extension",
                    resolver,
                ),
                patch.object(
                    DciRunRecorder, "close", autospec=True, side_effect=tracked_recorder_close
                ),
                patch.object(
                    ProviderRequestCapture,
                    "close",
                    autospec=True,
                    side_effect=failing_capture_close,
                ),
            ):
                result = run_pi_research(
                    _paths(root),
                    DciRunRequest(
                        run_id="capture-close-failure-run",
                        question=f"question-{_SENTINEL}",
                        cwd=root,
                        tools="read",
                        timeout_seconds=None,
                    ),
                    output_dir=output,
                )

            bundle = read_workflow_observation_bundle(
                output / "workflow-evidence.json"
            )
            model_calls = [
                event
                for event in bundle.pathlight_traces[0]["events"]
                if event["kind"] == "model-call" and event["status"] == "started"
            ]
            self.assertEqual(result.status, "completed")
            self.assertEqual(_CapturedClient.stop_calls, 1)
            self.assertGreaterEqual(capture_close_calls, 2)
            self.assertIn("capture", cleanup)
            self.assertIn("recorder", cleanup)
            self.assertIn("extension", cleanup)
            self.assertTrue(
                all("request_shape_sha256" not in event["attributes"] for event in model_calls)
            )

    def test_observation_setup_failures_leave_completed_safe_gap(self) -> None:
        cases = ("resolver", "capture-open")
        for name in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                output = root / name
                target = (
                    "asterion.capabilities.dci.implementation.research.pathlight_observation.resolve_pathlight_observation_extension"
                    if name == "resolver"
                    else None
                )
                client_patch = patch(
                    "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                    _CompletedClient,
                )
                failure_patch = (
                    patch(target, side_effect=RuntimeError("injected resolver failure"))
                    if target is not None
                    else patch.object(
                        DciRunRecorder,
                        "open_provider_request_capture",
                        side_effect=OSError("injected capture open failure"),
                    )
                )
                with client_patch, failure_patch:
                    result = run_pi_research(
                        _paths(root),
                        DciRunRequest(
                            run_id=f"{name}-run",
                            question="question",
                            cwd=root,
                            tools="read",
                            timeout_seconds=None,
                        ),
                        output_dir=output,
                    )

                self.assertEqual(result.status, "completed")
                bundle = read_workflow_observation_bundle(
                    output / "workflow-evidence.json"
                )
                self.assertNotIn(
                    "model-call", _started_kinds(bundle.pathlight_traces[0])
                )
                self.assertTrue(
                    any(
                        event["kind"] == "context-frame"
                        and event["status"] == "started"
                        and event["attributes"]["missing_evidence"]
                        for event in bundle.pathlight_traces[0]["events"]
                    )
                )

    def test_observation_failures_preserve_completed_result_and_inferred_lineage(
        self,
    ) -> None:
        cases = (
            ("mismatch", _MismatchedCapturedClient, None),
            ("missing-entry", _MissingCapturedClient, None),
            ("write-failure", _WriteFailedCapturedClient, None),
            ("rpc-failure", _RpcFailedCapturedClient, None),
            (
                "reconciliation-failure",
                _CapturedClient,
                RuntimeError("injected reconciliation failure"),
            ),
        )
        for name, client_type, reconciliation_error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                output = root / name
                patches = [
                    patch(
                        "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                        client_type,
                    )
                ]
                if reconciliation_error is not None:
                    patches.append(
                        patch.object(
                            DciRunRecorder,
                            "reconcile_provider_requests",
                            side_effect=reconciliation_error,
                        )
                    )
                with patches[0]:
                    if len(patches) == 2:
                        patches[1].start()
                    try:
                        result = run_pi_research(
                            _paths(root),
                            DciRunRequest(
                                run_id=f"{name}-run",
                                question=f"question-{_SENTINEL}",
                                cwd=root,
                                tools="read",
                                timeout_seconds=None,
                            ),
                            output_dir=output,
                        )
                    finally:
                        if len(patches) == 2:
                            patches[1].stop()

                self.assertEqual(result.status, "completed")
                self.assertEqual(result.final_text, f"answer-{_SENTINEL}")
                bundle = read_workflow_observation_bundle(
                    output / "workflow-evidence.json"
                )
                trace = bundle.pathlight_traces[0]
                model_calls = [
                    event
                    for event in trace["events"]
                    if event["kind"] == "model-call" and event["status"] == "started"
                ]
                self.assertEqual(len(model_calls), 2)
                self.assertTrue(
                    all(
                        "request_shape_sha256" not in event["attributes"]
                        and "private_reference_sha256" not in event["attributes"]
                        for event in model_calls
                    )
                )
                self.assertEqual(_started_kinds(trace).count("tool-call"), 1)
                descriptor = client_type.construction["observation_fd"]
                assert isinstance(descriptor, int)
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_construction_and_provider_failures_close_private_capture(self) -> None:
        cases = (
            ("construction", _ConstructionFailedClient),
            ("provider", _ProviderFailedClient),
        )
        for name, client_type in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                output = root / name
                with patch(
                    "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                    client_type,
                ):
                    with self.assertRaises(DciRunError):
                        run_pi_research(
                            _paths(root),
                            DciRunRequest(
                                run_id=f"{name}-run",
                                question="question",
                                cwd=root,
                                tools="read",
                                timeout_seconds=None,
                            ),
                            output_dir=output,
                        )

                state = json.loads((output / "state.json").read_text())
                self.assertEqual(state["status"], "failed")
                self.assertFalse((output / "workflow-evidence.json").exists())
                descriptor = client_type.observation_fd
                assert descriptor is not None
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_observation_extension_teardown_cannot_change_completed_result(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "resolver-teardown"
            extension = root / "observation.ts"
            extension.write_text("fixture", encoding="utf-8")

            @contextmanager
            def resolver():
                yield SimpleNamespace(
                    path=extension,
                    contract_version="dci.pathlight-provider-request-capture/v1",
                )
                raise RuntimeError("injected observation resolver teardown")

            with (
                patch(
                    "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                    _CapturedClient,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.research.pathlight_observation.resolve_pathlight_observation_extension",
                    resolver,
                ),
            ):
                result = run_pi_research(
                    _paths(root),
                    DciRunRequest(
                        run_id="resolver-teardown-run",
                        question=f"question-{_SENTINEL}",
                        cwd=root,
                        tools="read",
                        timeout_seconds=None,
                    ),
                    output_dir=output,
                )

            self.assertEqual(result.status, "completed")
            self.assertTrue((output / "workflow-evidence.json").is_file())

    def test_native_run_reconciles_exact_private_provider_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "captured-native"
            request = DciRunRequest(
                run_id="captured-native-run",
                question=f"question-{_SENTINEL}",
                cwd=root,
                tools="read",
                timeout_seconds=None,
            )
            with patch(
                "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                _CapturedClient,
            ):
                result = run_pi_research(_paths(root), request, output_dir=output)

            construction = _CapturedClient.construction
            self.assertEqual(
                construction["observation_contract"],
                "dci.pathlight-provider-request-capture/v1",
            )
            extension = construction["observation_extension_path"]
            self.assertIsInstance(extension, Path)
            self.assertTrue(extension.is_absolute())
            capture = output / "provider-requests.jsonl"
            self.assertTrue(capture.is_file())
            self.assertEqual(capture.stat().st_mode & 0o777, 0o400)
            bundle = read_workflow_observation_bundle(output / "workflow-evidence.json")
            record = bundle.records[0]
            trace = bundle.pathlight_traces[0]
            self.assertEqual(result.status, "completed")
            self.assertEqual(_started_kinds(trace).count("model-call"), 2)
            self.assertEqual(_started_kinds(trace).count("tool-call"), 1)
            model_calls = [
                event
                for event in trace["events"]
                if event["kind"] == "model-call" and event["status"] == "started"
            ]
            self.assertTrue(
                all(
                    "request_sha256" in event["attributes"]
                    and "request_shape_sha256" in event["attributes"]
                    and "private_reference_sha256" in event["attributes"]
                    for event in model_calls
                )
            )
            self.assertTrue(
                all(
                    event["attributes"]["boundary_observed"] is False
                    and event["attributes"]["missing_evidence"] is True
                    for event in model_calls
                )
            )
            tool_segments = [
                event
                for event in trace["events"]
                if event["kind"] == "context-frame"
                and event["status"] == "started"
                and event["attributes"].get("segment_role") == "tool-result"
            ]
            self.assertEqual(len(tool_segments), 1)
            self.assertIsNotNone(tool_segments[0]["attributes"]["source_call_sha256"])
            rendered = json.dumps(
                {"record": record, "trace": trace}, default=dict, sort_keys=True
            )
            for private in (
                _SENTINEL,
                str(root),
                "system contract",
                "tool result",
            ):
                self.assertNotIn(private, rendered)

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

            bundle = read_workflow_observation_bundle(output / "workflow-evidence.json")
            trace = bundle.pathlight_traces[0]
            kinds = _started_kinds(trace)
            self.assertEqual(kinds.count("model-call"), 2)
            self.assertEqual(kinds.count("tool-call"), 1)
            self.assertEqual(
                sum(
                    "frame_index" in event["attributes"]
                    for event in trace["events"]
                    if event["kind"] == "context-frame" and event["status"] == "started"
                ),
                2,
            )
            rendered = json.dumps(trace, default=dict, sort_keys=True)
            self.assertTrue(
                all(
                    event["attributes"]["missing_evidence"]
                    for event in trace["events"]
                    if event["kind"] == "model-call" and event["status"] == "started"
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
                    if event["kind"] == "context-frame" and event["status"] == "started"
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

            bundle = read_workflow_observation_bundle(output / "workflow-evidence.json")
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

            bundle = read_workflow_observation_bundle(output / "workflow-evidence.json")
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
                _CapturedClient,
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
            descriptor = _CapturedClient.construction["observation_fd"]
            assert isinstance(descriptor, int)
            with self.assertRaises(OSError):
                os.fstat(descriptor)


if __name__ == "__main__":
    unittest.main()
