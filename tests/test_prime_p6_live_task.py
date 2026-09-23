"""Semantic evidence for a bounded P6 model-proposed candidate."""

from __future__ import annotations

import hashlib
import json
import unittest

from asterion.applications.prime.p6.live_task import (
    P6LiveTaskError,
    evaluate_holdout,
    parse_candidate,
    task_a_evidence,
)


class TestP6LiveTask(unittest.TestCase):
    def test_holdout_compares_actual_candidate_with_baseline(self) -> None:
        good = parse_candidate('{"multiplier":3,"offset":1}')
        bad = parse_candidate('{"multiplier":1,"offset":0}')

        good_result = evaluate_holdout(good)
        bad_result = evaluate_holdout(bad)

        self.assertEqual(good_result.baseline_error, bad_result.baseline_error)
        self.assertEqual(good_result.candidate_error, 0)
        self.assertTrue(good_result.improved)
        self.assertFalse(bad_result.improved)
        self.assertGreater(bad_result.candidate_error, good_result.candidate_error)
        self.assertNotEqual(
            good_result.task_b_result_sha256, bad_result.task_b_result_sha256
        )

    def test_candidate_body_and_training_evidence_bind_real_values(self) -> None:
        first = parse_candidate('{"multiplier":3,"offset":1}')
        second = parse_candidate('{"multiplier":3,"offset":2}')

        self.assertEqual(
            first.body_sha256,
            hashlib.sha256(first.body).hexdigest(),
        )
        self.assertEqual(json.loads(first.body), {"multiplier": 3, "offset": 1})
        self.assertNotEqual(first.body_sha256, second.body_sha256)
        self.assertNotEqual(task_a_evidence(first), task_a_evidence(second))

    def test_malformed_or_unsafe_candidate_is_rejected_without_text_leak(self) -> None:
        for text in (
            "secret-payload",
            '{"multiplier":true,"offset":1}',
            '{"multiplier":3,"offset":1,"command":"secret-payload"}',
            '{"multiplier":1000000,"offset":1}',
        ):
            with self.subTest(text=text), self.assertRaises(P6LiveTaskError) as raised:
                parse_candidate(text)
            self.assertNotIn("secret-payload", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
