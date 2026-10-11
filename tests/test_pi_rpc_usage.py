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
            {"input_tokens": 20, "output_tokens": 4, "uncached_input_tokens": 10,
             "cache_read_tokens": 7, "cache_write_tokens": 3},
        )

    def test_normalizes_legacy_usage_without_cache_tokens(self) -> None:
        self.assertEqual(
            normalize_pi_usage(_message_end_usage({"input": 10, "output": 4})),
            {"input_tokens": 10, "output_tokens": 4, "uncached_input_tokens": 10},
        )

    def test_cost_is_reported_as_sdk_estimate_without_inventing_missing_fields(self) -> None:
        native = {"type": "message_end", "message": {"role": "assistant", "usage": {
            "input": 10, "output": 4, "cacheRead": 0,
            "cost": {"total": 0.0125, "private": "not public"},
        }}}
        compacted = _compact_rpc_event(native)
        self.assertEqual(compacted["message"]["usage"]["cost"], {"total": 0.0125})
        normalized = normalize_pi_usage(compacted)
        self.assertEqual(normalized["reported_cost"], {
            "currency": "USD", "total": 0.0125, "source": "pi_sdk_estimate",
        })
        self.assertEqual(normalized["cache_read_tokens"], 0)
        self.assertNotIn("cache_write_tokens", normalized)
        self.assertNotIn("reported_cost", normalize_pi_usage(_message_end_usage({"input": 1, "output": 2})))
        self.assertEqual(native["message"]["usage"]["cost"]["private"], "not public")

    def test_rejects_malformed_reported_cost(self) -> None:
        for value in (True, -1, "0.5", float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "usage event is invalid"):
                normalize_pi_usage(_message_end_usage({"input": 1, "output": 2, "cost": {"total": value}}))

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
