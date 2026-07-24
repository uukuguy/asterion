from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from asterion.services.controlled_executor import (
    ControlledExecutionRequest,
    ControlledExecutionResult,
    ControlledExecutorError,
)


class ControlledExecutorServiceValueTests(unittest.TestCase):
    def test_request_accepts_only_a_logical_relative_target(self) -> None:
        request = ControlledExecutionRequest(target="src/example.py")
        self.assertEqual(request.target, "src/example.py")
        with self.assertRaises(FrozenInstanceError):
            request.target = "other.py"  # type: ignore[misc]
        for target in ("", "/secret.py", "../secret.py", "src/../../secret.py", "a\x00b"):
            with self.subTest(target=target):
                with self.assertRaises(ControlledExecutorError):
                    ControlledExecutionRequest(target=target)

    def test_result_is_closed_immutable_and_contains_no_output_bodies(self) -> None:
        result = ControlledExecutionResult(
            status="succeeded",
            exit_code=0,
            stdout_bytes=12,
            stderr_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=8,
            failure_class=None,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertFalse(hasattr(result, "stdout"))
        self.assertFalse(hasattr(result, "stderr"))
        with self.assertRaises(FrozenInstanceError):
            result.status = "failed"  # type: ignore[misc]

    def test_invalid_results_fail_without_echoing_values(self) -> None:
        cases = (
            {"status": "SECRET", "exit_code": 0},
            {"status": "succeeded", "exit_code": None},
            {"status": "rejected", "exit_code": 0},
            {"status": "failed", "exit_code": -1},
        )
        defaults = {
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "duration_ms": 0,
            "failure_class": None,
        }
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ControlledExecutorError) as caught:
                    ControlledExecutionResult(**defaults, **values)  # type: ignore[arg-type]
                self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
