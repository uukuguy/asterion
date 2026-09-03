from __future__ import annotations

import json
from pathlib import Path
import unittest

from asterion.applications.prime_agent.operator.diagnostic_session_recovery_completion import (
    DiagnosticSessionRecoveryCompletionError,
    parse_diagnostic_session_recovery_completion,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "prime_gateway" / "v1"
    / "prime-diagnostic-session-recovery.json"
)


class TestDiagnosticSessionRecoveryCompletion(unittest.TestCase):
    def test_parses_only_the_fixed_redacted_completion(self) -> None:
        completion = parse_diagnostic_session_recovery_completion(
            json.loads(FIXTURE.read_text(encoding="utf-8"))
        )

        self.assertEqual(
            completion.trace.workload_sha256,
            P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
        )
        self.assertTrue(completion.trace.uncertain_effect_fenced)
        self.assertNotIn("PRIVATE-DIAGNOSTIC", repr(completion))

    def test_rejects_noncanonical_or_private_payloads(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cases = (
            {"format": "wrong"},
            {**payload, "unexpected": True},
            {**payload, "root_tool_names": ["shell"]},
            {**payload, "attach_count": 2},
            {**payload, "checkpoint_cursor_matches_attach": False},
            {**payload, "compaction_on_active_path": False},
            {**payload, "durable_assets_only": False},
            {**payload, "uncertain_effect_fenced": False},
            {**payload, "private_diagnostic": "PRIVATE-DIAGNOSTIC"},
        )
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(
                DiagnosticSessionRecoveryCompletionError
            ) as raised:
                parse_diagnostic_session_recovery_completion(candidate)
            self.assertNotIn("PRIVATE-DIAGNOSTIC", str(raised.exception))
