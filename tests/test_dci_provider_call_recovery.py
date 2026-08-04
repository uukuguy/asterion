from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import traceback
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.dci.implementation.evaluation.provider_requests import (
    _summarize_payload,
)
from asterion.capabilities.dci.implementation.pathlight.provider_call_recovery import (
    DciProviderCallRecoveryError,
    recover_provider_call_companion,
)
from asterion.runtime.host import RunEvent, RunRequest
from asterion.workflow_evidence import (
    build_workflow_observation_bundle,
    project_completed_runtime_evidence,
    read_workflow_observation_bundle_mapping,
)


COMPANION_NAME = "workflow-evidence.provider-calls.offline.json"
FIXED_ERROR = "DCI provider call recovery is invalid"
SENTINEL = "SENTINEL_PRIVATE_PROVIDER_RECOVERY"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _jsonl(values: list[dict[str, object]]) -> bytes:
    return b"".join(_json_bytes(value) + b"\n" for value in values)


def _private_pair(
    request_index: int, *, unicode_payload: bool = False
) -> tuple[bytes, dict[str, object]]:
    request_content = (
        f"请求-{request_index}-café-😀-{SENTINEL}"
        if unicode_payload
        else f"request-{request_index}-{SENTINEL}"
    )
    payload = {
        "messages": [
            {"role": "system", "content": f"system-{SENTINEL}"},
            {"role": "user", "content": request_content},
        ]
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    summary = _summarize_payload(payload, payload_json.encode("utf-8"))
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
    safe = {
        "schema": "dci.provider-request-observation/v1",
        "request_index": request_index,
        "capture_status": "captured",
        **summary,
    }
    return _json_bytes(record) + b"\n", safe


def _marker(safe: dict[str, object], request_index: int) -> dict[str, object]:
    return {
        "type": "entry_appended",
        "entry": {
            "id": f"provider-{request_index}",
            "parentId": None,
            "timestamp": "2026-08-03T04:05:06.789Z",
            "type": "custom",
            "customType": "dci-provider-request-observation",
            "data": safe,
        },
    }


def _message_start() -> dict[str, object]:
    return {"type": "message_start", "message": {"role": "assistant", "content": []}}


def _message_end(index: int) -> dict[str, object]:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": f"response-{index}-{SENTINEL}"}],
            "stopReason": "stop",
            "usage": {"input": index * 10, "output": index},
        },
    }


def _native_fixture(safe_entries: list[dict[str, object]]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    tool_index = 1
    for request_index, tool_count in ((1, 2), (2, 2)):
        events.extend((_marker(safe_entries[request_index - 1], request_index), _message_start()))
        for _ in range(tool_count):
            call_id = f"call-{tool_index}-{SENTINEL}"
            events.extend(
                (
                    {
                        "type": "tool_execution_start",
                        "toolCallId": call_id,
                        "toolName": "filesystem.read",
                        "args": {"query": f"argument-{tool_index}-{SENTINEL}"},
                    },
                    {
                        "type": "tool_execution_end",
                        "toolCallId": call_id,
                        "result": f"result-{tool_index}-{SENTINEL}",
                        "isError": False,
                    },
                )
            )
            tool_index += 1
        events.append(_message_end(request_index))
    events.extend(
        (
            _marker(safe_entries[2], 3),
            {
                "type": "entry_appended",
                "entry": {
                    "type": "custom",
                    "customType": "dci-context-telemetry",
                    "data": {"event": "compaction", "private": SENTINEL},
                },
            },
            _marker(safe_entries[3], 4),
            _message_start(),
        )
    )
    while tool_index <= 7:
        call_id = f"call-{tool_index}-{SENTINEL}"
        events.extend(
            (
                {
                    "type": "tool_execution_start",
                    "toolCallId": call_id,
                    "toolName": "filesystem.read",
                    "args": {"query": f"argument-{tool_index}-{SENTINEL}"},
                },
                {
                    "type": "tool_execution_end",
                    "toolCallId": call_id,
                    "result": f"result-{tool_index}-{SENTINEL}",
                    "isError": False,
                },
            )
        )
        tool_index += 1
    events.append(_message_end(3))
    return events


def _protocol_fixture() -> tuple[dict[str, object], list[dict[str, object]]]:
    request = RunRequest(
        run_id="offline-recovery-run",
        input_text=f"question-{SENTINEL}",
        requested_capabilities=("filesystem.read",),
    ).to_mapping()
    events = [
        RunEvent(
            "offline-recovery-run", 1, "run.started", {"capabilities": ["filesystem.read"]}
        ).to_mapping()
    ]
    sequence = 2
    for index in range(1, 8):
        events.append(
            RunEvent(
                "offline-recovery-run",
                sequence,
                "tool.call",
                {
                    "call_id": f"call-{index}-{SENTINEL}",
                    "name": "filesystem.read",
                    "arguments": {"query": f"argument-{index}-{SENTINEL}"},
                },
            ).to_mapping()
        )
        sequence += 1
        events.append(
            RunEvent(
                "offline-recovery-run",
                sequence,
                "tool.result",
                {
                    "call_id": f"call-{index}-{SENTINEL}",
                    "output": f"result-{index}-{SENTINEL}",
                    "is_error": False,
                },
            ).to_mapping()
        )
        sequence += 1
    events.append(
        RunEvent(
            "offline-recovery-run", sequence, "run.completed", {"status": "completed"}
        ).to_mapping()
    )
    return request, events


def _original_bundle(
    request_mapping: dict[str, object], events: list[dict[str, object]]
) -> dict[str, object]:
    request_input = request_mapping["input"]
    assert isinstance(request_input, dict)
    request = RunRequest(
        run_id=str(request_mapping["run_id"]),
        input_text=str(request_input["text"]),
        requested_capabilities=tuple(request_mapping["requested_capabilities"]),  # type: ignore[arg-type]
    )
    projected = project_completed_runtime_evidence(
        request=request,
        event_observations=tuple(
            (event, index * 2, index * 2 + 1) for index, event in enumerate(events, 1)
        ),
        native_observation=None,
        runtime_id="pi.dci-native",
        trace_id="00000000-0000-4000-8000-000000000001",
        invocation_started_ns=1,
        invocation_ended_ns=len(events) * 2 + 2,
    )
    return build_workflow_observation_bundle(
        (projected.record,), pathlight_traces=(projected.trace,)
    )


def _write_private(path: Path, raw: bytes, mode: int = 0o600) -> None:
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(mode)


class ProviderCallRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "generation"
        self.root.mkdir(mode=0o700)
        protocol = self.root / "protocol"
        protocol.mkdir(mode=0o700)
        pairs = [_private_pair(index) for index in range(1, 5)]
        safe_entries = [safe for _raw, safe in pairs]
        request, protocol_events = _protocol_fixture()
        _write_private(self.root / "events.jsonl", _jsonl(_native_fixture(safe_entries)))
        _write_private(
            self.root / "provider-requests.jsonl",
            b"".join(raw for raw, _safe in pairs),
            0o400,
        )
        _write_private(
            self.root / "workflow-evidence.json",
            _json_bytes(_original_bundle(request, protocol_events)),
        )
        _write_private(protocol / "attempt-0001.request.json", _json_bytes(request))
        _write_private(
            protocol / "attempt-0001.events.jsonl", _jsonl(protocol_events)
        )
        self.companion = self.root / COMPANION_NAME

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _sources(self) -> tuple[Path, ...]:
        return (
            self.root / "events.jsonl",
            self.root / "provider-requests.jsonl",
            self.root / "workflow-evidence.json",
            self.root / "protocol/attempt-0001.request.json",
            self.root / "protocol/attempt-0001.events.jsonl",
        )

    def _snapshot(self) -> dict[str, tuple[bytes, int, int, str]]:
        return {
            str(path.relative_to(self.root)): (
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in self._sources()
        }

    def _assert_invalid(self, root: Path, companion: Path) -> None:
        try:
            recover_provider_call_companion(root, companion)
        except Exception as error:
            raised = error
        else:
            self.fail("invalid provider-call recovery was accepted")
        rendered = "".join(traceback.format_exception(raised))
        self.assertIsInstance(raised, DciProviderCallRecoveryError)
        self.assertEqual(str(raised), FIXED_ERROR)
        self.assertIsNone(raised.__cause__)
        self.assertNotIn(SENTINEL, rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_publishes_validated_offline_companion_without_mutating_sources(self) -> None:
        before = self._snapshot()
        original_names = {str(path.relative_to(self.root)) for path in self.root.rglob("*")}

        with (
            patch("subprocess.run") as process_run,
            patch("subprocess.Popen") as process_open,
            patch("socket.create_connection") as network,
            patch("urllib.request.urlopen") as urlopen,
            patch("asterion.applications.discovery.load_application_provider") as provider,
            patch("asterion.runtime.factory.RuntimeFactoryRegistry.select") as runtime_select,
            patch(
                "asterion.capabilities.dci.implementation.evaluation.judge.judge_answer_sync"
            ) as judge,
            patch("asterion.benchmarks.planning.create_benchmark_plan") as authorize,
        ):
            bundle = recover_provider_call_companion(self.root, self.companion)

        self.assertEqual(self._snapshot(), before)
        self.assertEqual(
            {str(path.relative_to(self.root)) for path in self.root.rglob("*")},
            original_names | {COMPANION_NAME},
        )
        self.assertEqual(stat.S_IMODE(self.companion.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(self.companion.read_bytes()),
            json.loads(json.dumps(bundle, default=dict)),
        )
        read_workflow_observation_bundle_mapping(bundle)
        with self.assertRaises(TypeError):
            bundle["unexpected"] = True  # type: ignore[index]

        traces = bundle["pathlight_traces"]
        self.assertIsInstance(traces, tuple)
        assert isinstance(traces, tuple)
        trace = traces[0]
        assert isinstance(trace, Mapping)
        trace_events = trace["events"]
        assert isinstance(trace_events, tuple)
        starts = [event for event in trace_events if event["status"] == "started"]
        frames = [
            event
            for event in starts
            if event["kind"] == "context-frame"
            and "frame_index" in event["attributes"]
        ]
        calls = [event for event in starts if event["kind"] == "model-call"]
        tools = [event for event in starts if event["kind"] == "tool-call"]
        self.assertEqual((len(frames), len(calls), len(tools)), (4, 4, 7))
        self.assertEqual(
            sum("private_reference_sha256" in event["attributes"] for event in calls),
            4,
        )
        self.assertEqual(sum("response_sha256" in event["attributes"] for event in calls), 3)
        request_only = next(
            event for event in calls if event["attributes"]["request_index"] == 3
        )
        self.assertEqual(
            tuple(request_only["attributes"]["missing_evidence_labels"]),
            (
                "model-identity",
                "model-request-boundary",
                "model-response",
                "token-usage",
            ),
        )
        rendered = json.dumps(bundle, default=dict, sort_keys=True)
        self.assertNotIn(SENTINEL, rendered)
        keys: list[str] = []

        def collect_keys(value: object) -> None:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    keys.append(str(key))
                    collect_keys(item)
            elif isinstance(value, tuple):
                for item in value:
                    collect_keys(item)

        collect_keys(bundle)
        self.assertFalse(any("offline" in key.lower() for key in keys))
        self.assertIn("offline", (recover_provider_call_companion.__doc__ or "").lower())
        for operation in (
            process_run,
            process_open,
            network,
            urlopen,
            provider,
            runtime_select,
            judge,
            authorize,
        ):
            operation.assert_not_called()

    def test_rejects_invalid_roots_inputs_and_targets_with_fixed_error(self) -> None:
        with self.subTest(case="relative-root"):
            self._assert_invalid(Path("generation"), self.companion)
        with self.subTest(case="relative-target"):
            self._assert_invalid(self.root, Path(COMPANION_NAME))
        with self.subTest(case="different-directory"):
            outside = Path(self.temporary.name).resolve() / COMPANION_NAME
            self._assert_invalid(self.root, outside)

        symlink_root = Path(self.temporary.name).resolve() / "generation-link"
        symlink_root.symlink_to(self.root, target_is_directory=True)
        with self.subTest(case="symlink-root"):
            self._assert_invalid(symlink_root, symlink_root / COMPANION_NAME)

        self.companion.write_text(SENTINEL, encoding="utf-8")
        self.companion.chmod(0o600)
        with self.subTest(case="existing-output"):
            self._assert_invalid(self.root, self.companion)
        self.assertEqual(self.companion.read_text(encoding="utf-8"), SENTINEL)
        self.companion.unlink()

        for relative, invalid_mode in (
            (".", 0o755),
            ("protocol", 0o755),
            ("events.jsonl", 0o644),
            ("workflow-evidence.json", 0o400),
            ("protocol/attempt-0001.request.json", 0o644),
        ):
            with self.subTest(case="mode", relative=relative):
                path = self.root / relative
                original_mode = stat.S_IMODE(path.stat().st_mode)
                path.chmod(invalid_mode)
                self._assert_invalid(self.root, self.companion)
                self.assertFalse(self.companion.exists())
                path.chmod(original_mode)

        source = self.root / "events.jsonl"
        saved = source.read_bytes()
        source.unlink()
        backing = self.root / f"events-{SENTINEL}.jsonl"
        _write_private(backing, saved)
        source.symlink_to(backing.name)
        with self.subTest(case="symlink-source"):
            self._assert_invalid(self.root, self.companion)
        source.unlink()
        backing.unlink()
        _write_private(source, saved)

        source.unlink()
        source.mkdir(mode=0o600)
        with self.subTest(case="directory-source"):
            self._assert_invalid(self.root, self.companion)
        source.rmdir()
        _write_private(source, saved)

        for relative in (
            "events.jsonl",
            "provider-requests.jsonl",
            "workflow-evidence.json",
            "protocol/attempt-0001.request.json",
            "protocol/attempt-0001.events.jsonl",
        ):
            with self.subTest(case="missing", relative=relative):
                path = self.root / relative
                saved = path.read_bytes()
                mode = stat.S_IMODE(path.stat().st_mode)
                path.unlink()
                self._assert_invalid(self.root, self.companion)
                self.assertFalse(self.companion.exists())
                _write_private(path, saved, mode)

        malformed = {
            "events.jsonl": (SENTINEL + "\n").encode(),
            "provider-requests.jsonl": (SENTINEL + "\n").encode(),
            "workflow-evidence.json": (SENTINEL + "\n").encode(),
            "protocol/attempt-0001.request.json": (SENTINEL + "\n").encode(),
            "protocol/attempt-0001.events.jsonl": (SENTINEL + "\n").encode(),
        }
        for relative, replacement in malformed.items():
            with self.subTest(case="malformed", relative=relative):
                path = self.root / relative
                saved = path.read_bytes()
                mode = stat.S_IMODE(path.stat().st_mode)
                _write_private(path, replacement, mode)
                self._assert_invalid(self.root, self.companion)
                self.assertFalse(self.companion.exists())
                _write_private(path, saved, mode)

    def test_rejects_intermediate_symlink_in_generation_root(self) -> None:
        linked_parent = Path(self.temporary.name).resolve() / "linked-parent"
        linked_parent.symlink_to(self.root.parent, target_is_directory=True)
        traversed_root = linked_parent / self.root.name

        self._assert_invalid(
            traversed_root, traversed_root / COMPANION_NAME
        )

        self.assertFalse(self.companion.exists())

    def test_retry_replay_retains_process_global_attempt_evidence(self) -> None:
        pairs = [_private_pair(index) for index in range(1, 6)]
        safe_entries = [safe for _raw, safe in pairs]
        _write_private(
            self.root / "provider-requests.jsonl",
            b"".join(raw for raw, _safe in pairs),
            0o400,
        )
        native_events = _native_fixture(safe_entries[1:])
        abandoned_call = f"abandoned-call-{SENTINEL}"
        abandoned_response = {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"abandoned-response-{SENTINEL}"}
                ],
                "stopReason": "stop",
                "usage": {"input": 999, "output": 999},
            },
        }
        retry_events = [
            {"type": "agent_start"},
            _marker(safe_entries[0], 1),
            _message_start(),
            {
                "type": "tool_execution_start",
                "toolCallId": abandoned_call,
                "toolName": "filesystem.grep",
                "args": {"query": f"abandoned-argument-{SENTINEL}"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": abandoned_call,
                "result": f"abandoned-result-{SENTINEL}",
                "isError": False,
            },
            abandoned_response,
            {"type": "agent_end", "willRetry": True},
            {"type": "agent_start"},
            *native_events,
            {"type": "agent_end"},
        ]
        _write_private(self.root / "events.jsonl", _jsonl(retry_events))
        _request, protocol_events = _protocol_fixture()
        protocol_events[1:1] = [
            RunEvent(
                "offline-recovery-run",
                1,
                "tool.call",
                {
                    "call_id": abandoned_call,
                    "name": "filesystem.grep",
                    "arguments": {"query": f"abandoned-argument-{SENTINEL}"},
                },
            ).to_mapping(),
            RunEvent(
                "offline-recovery-run",
                1,
                "tool.result",
                {
                    "call_id": abandoned_call,
                    "output": f"abandoned-result-{SENTINEL}",
                    "is_error": False,
                },
            ).to_mapping(),
        ]
        for sequence, event in enumerate(protocol_events, 1):
            event["sequence"] = sequence
        _write_private(
            self.root / "protocol/attempt-0001.events.jsonl",
            _jsonl(protocol_events),
        )

        bundle = recover_provider_call_companion(self.root, self.companion)

        traces = bundle["pathlight_traces"]
        assert isinstance(traces, tuple)
        trace = traces[0]
        assert isinstance(trace, Mapping)
        events = trace["events"]
        assert isinstance(events, tuple)
        starts = [event for event in events if event["status"] == "started"]
        frames = [
            event
            for event in starts
            if event["kind"] == "context-frame"
            and "frame_index" in event["attributes"]
        ]
        calls = [event for event in starts if event["kind"] == "model-call"]
        tools = [event for event in starts if event["kind"] == "tool-call"]
        self.assertEqual((len(frames), len(calls), len(tools)), (5, 5, 8))
        self.assertEqual(
            tuple(event["attributes"]["request_index"] for event in calls),
            (1, 2, 3, 4, 5),
        )
        self.assertEqual(
            sum("response_sha256" in event["attributes"] for event in calls), 4
        )
        expected_response = _message_end(1)["message"]
        assert isinstance(expected_response, dict)
        expected_content = expected_response["content"]
        abandoned_message = abandoned_response["message"]
        assert isinstance(abandoned_message, dict)
        abandoned_content = abandoned_message["content"]
        expected_response_sha256 = hashlib.sha256(
            json.dumps(
                expected_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        abandoned_response_sha256 = hashlib.sha256(
            json.dumps(
                abandoned_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            calls[0]["attributes"]["response_sha256"], abandoned_response_sha256
        )
        self.assertEqual(
            calls[1]["attributes"]["response_sha256"], expected_response_sha256
        )
        rendered = json.dumps(bundle, default=dict, sort_keys=True)
        self.assertIn(hashlib.sha256(abandoned_call.encode()).hexdigest(), rendered)
        self.assertIn(
            hashlib.sha256(b"filesystem.grep").hexdigest(),
            rendered,
        )
        self.assertNotIn(SENTINEL, rendered)

    def test_recovers_canonical_unicode_provider_payloads_without_raw_content(
        self,
    ) -> None:
        pairs = [
            _private_pair(index, unicode_payload=True) for index in range(1, 5)
        ]
        safe_entries = [safe for _raw, safe in pairs]
        _write_private(
            self.root / "provider-requests.jsonl",
            b"".join(raw for raw, _safe in pairs),
            0o400,
        )
        native_events = [
            json.loads(line)
            for line in (self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for event in native_events:
            entry = event.get("entry")
            if (
                isinstance(entry, dict)
                and entry.get("customType")
                == "dci-provider-request-observation"
            ):
                data = entry.get("data")
                assert isinstance(data, dict)
                request_index = data["request_index"]
                assert isinstance(request_index, int)
                entry["data"] = safe_entries[request_index - 1]
        _write_private(self.root / "events.jsonl", _jsonl(native_events))

        bundle = recover_provider_call_companion(self.root, self.companion)

        traces = bundle["pathlight_traces"]
        assert isinstance(traces, tuple)
        trace = traces[0]
        assert isinstance(trace, Mapping)
        events = trace["events"]
        assert isinstance(events, tuple)
        model_calls = [
            event
            for event in events
            if event["kind"] == "model-call" and event["status"] == "started"
        ]
        self.assertEqual(len(model_calls), 4)
        self.assertTrue(
            all("private_reference_sha256" in event["attributes"] for event in model_calls)
        )
        rendered = json.dumps(bundle, default=dict, ensure_ascii=False, sort_keys=True)
        for private_text in ("请求", "café", "😀"):
            self.assertNotIn(private_text, rendered)

    def test_rolls_back_owned_inode_and_preserves_concurrent_replacement(self) -> None:
        module = __import__(
            "asterion.capabilities.dci.implementation.pathlight.provider_call_recovery",
            fromlist=["_write_all"],
        )
        def fail_before_publication(*_args: object, **_kwargs: object) -> None:
            self.assertFalse(self.companion.exists())
            raise OSError(SENTINEL)

        with self.subTest(case="write-failure"), patch.object(
            module, "_write_all", side_effect=fail_before_publication
        ):
            self._assert_invalid(self.root, self.companion)
        self.assertFalse(self.companion.exists())
        self.assertFalse((self.root / module._STAGING_NAME).exists())

        with self.subTest(case="mode-failure"), patch.object(
            module.os, "fchmod", side_effect=OSError(SENTINEL)
        ):
            self._assert_invalid(self.root, self.companion)
        self.assertFalse(self.companion.exists())
        self.assertFalse((self.root / module._STAGING_NAME).exists())

        replacement = b"SENTINEL_CONCURRENT_REPLACEMENT"

        def replace_target(*_args: object, **_kwargs: object) -> None:
            self.companion.unlink()
            _write_private(self.companion, replacement)
            raise OSError(SENTINEL)

        with self.subTest(case="concurrent-replacement"), patch.object(
            module, "_verify_published_target", side_effect=replace_target
        ):
            self._assert_invalid(self.root, self.companion)
        self.assertEqual(self.companion.read_bytes(), replacement)
        self.assertFalse((self.root / module._STAGING_NAME).exists())


if __name__ == "__main__":
    unittest.main()
