from __future__ import annotations

import unittest


class TestDiagnosticSessionRecoveryWorker(unittest.TestCase):
    def test_adapter_has_only_fixed_p4_execution_identity(self) -> None:
        from asterion.applications.prime_agent.operator.diagnostic_session_recovery_worker import (
            P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER,
        )
        self.assertEqual(P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER.scenario_id, "prime.long-session-continuity/v1")
        self.assertEqual(P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER.role_id, "prime.long-session-continuity")
        self.assertEqual(P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER.entrypoint, "/usr/local/bin/prime-diagnostic-session-recovery.mjs")
