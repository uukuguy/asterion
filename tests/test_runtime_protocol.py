"""Regression tests for the Agent Runtime Protocol v1 reference validator."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.runtime.protocol import (
    RUNTIME_PROTOCOL_VERSION,
    ProtocolError,
    validate_event_stream,
    validate_run_request,
    validate_runtime_manifest,
)


PROJECT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "agent_runtime" / "v1"


def _json(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _jsonl(name: str) -> list[object]:
    return [
        json.loads(line)
        for line in (FIXTURES / name).read_text().splitlines()
        if line
    ]


class TestRuntimeProtocol(unittest.TestCase):
    def test_runtime_protocol_is_asterion_owned(self) -> None:
        self.assertEqual(RUNTIME_PROTOCOL_VERSION, "asterion.agent-runtime/v1")
        for path in (PROJECT / "schemas/agent-runtime/v1").glob("*.json"):
            self.assertNotIn("dci.agent-runtime/v1", path.read_text(encoding="utf-8"))

    def test_rejects_shared_invalid_runtime_manifests(self) -> None:
        for name in (
            "invalid-runtime-manifest.json",
            "invalid-noncanonical-runtime-id.json",
            "invalid-unsorted-runtime-capabilities.json",
        ):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                validate_runtime_manifest(_json(name))

    def test_rejects_unsorted_request_capabilities(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_run_request(_json("invalid-unsorted-request-capabilities.json"))

    def test_rejects_unsorted_started_capabilities(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_event_stream(_jsonl("invalid-unsorted-started-capabilities.jsonl"))

    def test_rejects_invalid_event_streams(self) -> None:
        for name in (
            "invalid-sequence-gap.jsonl",
            "invalid-unmatched-tool-result.jsonl",
            "invalid-post-terminal.jsonl",
            "invalid-unmatched-tool-call-at-terminal.jsonl",
        ):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                validate_event_stream(_jsonl(name))

    def test_unexpected_fields_are_rejected_without_echoing_keys(self) -> None:
        sentinel = "SECRET-UNEXPECTED-KEY"
        cases = (
            (
                "runtime-manifest",
                validate_runtime_manifest,
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "runtime_id": "fixture.runtime",
                    "capabilities": [],
                    sentinel: "provider-controlled",
                },
            ),
            (
                "request",
                validate_run_request,
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "fixture-run",
                    "input": {"text": "fixture"},
                    sentinel: "provider-controlled",
                },
            ),
            (
                "request-input",
                validate_run_request,
                {
                    "protocol": "asterion.agent-runtime/v1",
                    "run_id": "fixture-run",
                    "input": {
                        "text": "fixture",
                        sentinel: "provider-controlled",
                    },
                },
            ),
            (
                "event",
                validate_event_stream,
                [
                    {
                        "protocol": "asterion.agent-runtime/v1",
                        "run_id": "fixture-run",
                        "sequence": 1,
                        "type": "run.started",
                        "payload": {"capabilities": []},
                        sentinel: "provider-controlled",
                    }
                ],
            ),
            (
                "event-payload",
                validate_event_stream,
                [
                    {
                        "protocol": "asterion.agent-runtime/v1",
                        "run_id": "fixture-run",
                        "sequence": 1,
                        "type": "run.started",
                        "payload": {
                            "capabilities": [],
                            sentinel: "provider-controlled",
                        },
                    }
                ],
            ),
        )

        for label, validator, value in cases:
            with (
                self.subTest(label=label),
                self.assertRaises(ProtocolError) as caught,
            ):
                validator(value)  # type: ignore[arg-type]
            self.assertIn("unknown fields", str(caught.exception))
            self.assertNotIn(sentinel, str(caught.exception))

    def test_tool_lifecycle_errors_do_not_echo_call_ids(self) -> None:
        sentinel = "SECRET-PROVIDER-CALL-ID"
        started = _event(1, "run.started", {"capabilities": []})
        call = _event(
            2,
            "tool.call",
            {"call_id": sentinel, "name": "fixture", "arguments": {}},
        )
        result = _event(
            3,
            "tool.result",
            {"call_id": sentinel, "output": None, "is_error": False},
        )
        cases = (
            (
                "duplicate-call",
                (started, call, {**call, "sequence": 3}),
                "duplicate tool.call",
            ),
            (
                "unmatched-result",
                (
                    started,
                    _event(
                        2,
                        "tool.result",
                        {
                            "call_id": sentinel,
                            "output": None,
                            "is_error": False,
                        },
                    ),
                ),
                "no matching call_id",
            ),
            (
                "duplicate-result",
                (started, call, result, {**result, "sequence": 4}),
                "duplicate tool.result",
            ),
        )

        for label, events, structural_message in cases:
            with (
                self.subTest(label=label),
                self.assertRaises(ProtocolError) as caught,
            ):
                validate_event_stream(events)
            self.assertIn(structural_message, str(caught.exception))
            self.assertNotIn(sentinel, str(caught.exception))


def _event(
    sequence: int,
    event_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "protocol": "asterion.agent-runtime/v1",
        "run_id": "fixture-run",
        "sequence": sequence,
        "type": event_type,
        "payload": payload,
    }
