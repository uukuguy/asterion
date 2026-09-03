from __future__ import annotations

import unittest
from typing import cast

from asterion.applications.prime_agent.diagnostic_session_recovery_acceptance import (
    DiagnosticRecoveryProviderFreeObservation,
    DiagnosticSessionRecoveryAcceptanceError,
    accept_diagnostic_session_recovery,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_completion import (
    DiagnosticSessionRecoveryCompletion,
)


class TestDiagnosticSessionRecoveryAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_invalid_observation_before_gateway_access(self) -> None:
        with self.assertRaises(DiagnosticSessionRecoveryAcceptanceError):
            await accept_diagnostic_session_recovery(
                gateway=object(),
                checkpoint=object(),
                before_detach=object(),
                observation=DiagnosticRecoveryProviderFreeObservation(
                    cast(DiagnosticSessionRecoveryCompletion, object()), True, True
                ),
            )
