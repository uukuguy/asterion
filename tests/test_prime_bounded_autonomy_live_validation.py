from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_live_validation import (
    BoundedAutonomyLiveAuthorization,
    BoundedAutonomyLiveValidationError,
    validate_bounded_autonomy_live_result,
)


class TestBoundedAutonomyLiveValidation(unittest.TestCase):
    def test_raw_trace_and_missing_authorization_are_rejected(self) -> None:
        authorization = BoundedAutonomyLiveAuthorization(
            "sha256:" + "a" * 64, True, True, True, True
        )
        with self.assertRaises(BoundedAutonomyLiveValidationError):
            validate_bounded_autonomy_live_result(object(), authorization)
        with self.assertRaises(BoundedAutonomyLiveValidationError):
            validate_bounded_autonomy_live_result(object(), object())
