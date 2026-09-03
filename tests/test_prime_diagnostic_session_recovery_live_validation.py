from __future__ import annotations

import unittest

from asterion.applications.prime_agent.diagnostic_session_recovery_live_validation import (
    DiagnosticSessionRecoveryLiveAuthorization,
    DiagnosticSessionRecoveryLiveValidationError,
    validate_diagnostic_session_recovery_live_result,
)


class TestDiagnosticSessionRecoveryLiveValidation(unittest.TestCase):
    def test_raw_trace_or_missing_authorization_cannot_issue_bounded_evidence(
        self,
    ) -> None:
        authorization = DiagnosticSessionRecoveryLiveAuthorization(
            "sha256:" + "a" * 64, True, True, True, True, True
        )

        with self.assertRaises(DiagnosticSessionRecoveryLiveValidationError):
            validate_diagnostic_session_recovery_live_result(object(), authorization)
        with self.assertRaises(DiagnosticSessionRecoveryLiveValidationError):
            validate_diagnostic_session_recovery_live_result(object(), object())
