"""Regression tests for the Agent Runtime Protocol v1 reference validator."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.runtime.protocol import (
    ProtocolError,
    validate_event_stream,
    validate_run_request,
    validate_runtime_manifest,
)


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
