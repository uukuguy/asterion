from __future__ import annotations

import unittest

from asterion.adapters.claude_code import ClaudeCodeProtocolAdapter
from asterion.adapters.pi import PiProtocolAdapter
from asterion.runtime.protocol import ProtocolError


SENTINEL_CALL_ID = "SECRET-PROVIDER-CALL-ID"


class RuntimeAdapterRedactionTests(unittest.TestCase):
    def test_pi_tool_lifecycle_errors_do_not_echo_call_ids(self) -> None:
        cases = (
            ("duplicate-call", _pi_duplicate_call, "duplicate"),
            ("unmatched-result", _pi_unmatched_result, "no matching"),
            ("duplicate-result", _pi_duplicate_result, "duplicate"),
        )

        for label, operation, structural_message in cases:
            adapter = PiProtocolAdapter(
                run_id="fixture-run",
                capabilities=[],
                emit=lambda event: None,
            )
            adapter.start()
            with (
                self.subTest(label=label),
                self.assertRaises(ProtocolError) as caught,
            ):
                operation(adapter)
            self.assertIn(structural_message, str(caught.exception))
            self.assertNotIn(SENTINEL_CALL_ID, str(caught.exception))

    def test_claude_tool_lifecycle_errors_do_not_echo_call_ids(self) -> None:
        cases = (
            ("duplicate-call", _claude_duplicate_call, "duplicate"),
            ("unmatched-result", _claude_unmatched_result, "no matching"),
            ("duplicate-result", _claude_duplicate_result, "duplicate"),
        )

        for label, operation, structural_message in cases:
            adapter = ClaudeCodeProtocolAdapter(
                run_id="fixture-run",
                emit=lambda event: None,
            )
            adapter.consume({"type": "system", "subtype": "init", "tools": []})
            with (
                self.subTest(label=label),
                self.assertRaises(ProtocolError) as caught,
            ):
                operation(adapter)
            self.assertIn(structural_message, str(caught.exception))
            self.assertNotIn(SENTINEL_CALL_ID, str(caught.exception))


def _pi_call() -> dict[str, object]:
    return {
        "type": "tool_execution_start",
        "toolCallId": SENTINEL_CALL_ID,
        "toolName": "fixture",
        "args": {},
    }


def _pi_result() -> dict[str, object]:
    return {
        "type": "tool_execution_end",
        "toolCallId": SENTINEL_CALL_ID,
        "result": None,
        "isError": False,
    }


def _pi_duplicate_call(adapter: PiProtocolAdapter) -> None:
    adapter.consume(_pi_call())
    adapter.consume(_pi_call())


def _pi_unmatched_result(adapter: PiProtocolAdapter) -> None:
    adapter.consume(_pi_result())


def _pi_duplicate_result(adapter: PiProtocolAdapter) -> None:
    adapter.consume(_pi_call())
    adapter.consume(_pi_result())
    adapter.consume(_pi_result())


def _claude_call() -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": SENTINEL_CALL_ID,
                    "name": "fixture",
                    "input": {},
                }
            ]
        },
    }


def _claude_result() -> dict[str, object]:
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": SENTINEL_CALL_ID,
                    "content": None,
                    "is_error": False,
                }
            ]
        },
    }


def _claude_duplicate_call(adapter: ClaudeCodeProtocolAdapter) -> None:
    adapter.consume(_claude_call())
    adapter.consume(_claude_call())


def _claude_unmatched_result(adapter: ClaudeCodeProtocolAdapter) -> None:
    adapter.consume(_claude_result())


def _claude_duplicate_result(adapter: ClaudeCodeProtocolAdapter) -> None:
    adapter.consume(_claude_call())
    adapter.consume(_claude_result())
    adapter.consume(_claude_result())


if __name__ == "__main__":
    unittest.main()
