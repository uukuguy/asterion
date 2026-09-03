"""Live P3 bounded evidence requires explicit authorization and a real trace."""

from __future__ import annotations

import unittest

from asterion.applications.prime_agent.recursive_code_review_live_validation import (
    RecursiveCodeReviewLiveAuthorization,
    RecursiveCodeReviewLiveValidationError,
    validate_recursive_code_review_live_result,
)


class TestRecursiveCodeReviewLiveValidation(unittest.TestCase):
    def test_provider_free_or_missing_authorization_cannot_issue_bounded(self) -> None:
        with self.assertRaises(RecursiveCodeReviewLiveValidationError):
            validate_recursive_code_review_live_result(object(), object())
        with self.assertRaises(RecursiveCodeReviewLiveValidationError):
            validate_recursive_code_review_live_result(
                object(), RecursiveCodeReviewLiveAuthorization("sha256:" + "a" * 64, True, True, True)
            )
