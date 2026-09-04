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

    def test_adapter_rejects_semantic_but_noncanonical_json(self) -> None:
        import json
        from pathlib import Path

        from asterion.applications.prime_agent.operator.diagnostic_session_recovery_worker import (
            _parse,
        )

        payload = json.loads(
            (Path(__file__).parent / "fixtures" / "prime_gateway" / "v1"
             / "prime-diagnostic-session-recovery.json").read_text(encoding="utf-8")
        )
        self.assertFalse(_parse(json.dumps(payload, indent=2).encode("utf-8")))

    def test_adapter_accepts_the_canonical_completion_fixture(self) -> None:
        from pathlib import Path

        from asterion.applications.prime_agent.operator.diagnostic_session_recovery_worker import (
            _parse,
        )

        raw = (Path(__file__).parent / "fixtures" / "prime_gateway" / "v1"
               / "prime-diagnostic-session-recovery.json").read_bytes()
        self.assertTrue(_parse(raw))
