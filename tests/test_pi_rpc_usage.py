from __future__ import annotations

import unittest

from asterion.runtimes.pi_rpc import _compact_rpc_event, normalize_pi_usage


def _message_end_usage(usage: dict[str, object]) -> dict[str, object]:
    return {"message": {"role": "assistant", "usage": usage}}


class TestPiRpcUsage(unittest.TestCase):
    def test_normalizes_cache_tokens_into_total_input(self) -> None:
        self.assertEqual(
            normalize_pi_usage(
                _message_end_usage(
                    {"input": 10, "output": 4, "cacheRead": 7, "cacheWrite": 3}
                )
            ),
            {"input_tokens": 20, "output_tokens": 4},
        )

    def test_normalizes_legacy_usage_without_cache_tokens(self) -> None:
        self.assertEqual(
            normalize_pi_usage(_message_end_usage({"input": 10, "output": 4})),
            {"input_tokens": 10, "output_tokens": 4},
        )

    def test_rejects_malformed_cache_token_counts(self) -> None:
        for field, value in (
            ("cacheRead", -1),
            ("cacheWrite", -1),
            ("cacheRead", True),
            ("cacheWrite", "3"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, "usage event is invalid"):
                    normalize_pi_usage(
                        _message_end_usage(
                            {"input": 1, "output": 2, field: value}
                        )
                    )

    def test_compaction_retains_cache_token_counts(self) -> None:
        compacted = _compact_rpc_event(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "usage": {
                        "input": 10,
                        "output": 4,
                        "cacheRead": 7,
                        "cacheWrite": 3,
                        "private": "discarded",
                    },
                },
            }
        )
        self.assertEqual(
            compacted["message"]["usage"],
            {"input": 10, "output": 4, "cacheRead": 7, "cacheWrite": 3},
        )


if __name__ == "__main__":
    unittest.main()
