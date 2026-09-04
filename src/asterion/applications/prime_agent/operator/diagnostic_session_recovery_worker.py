"""Sealed P4 restricted-worker adapter."""
from __future__ import annotations

import json

from asterion.applications.prime_agent.operator.diagnostic_session_recovery_completion import (
    DiagnosticSessionRecoveryCompletionError,
    parse_diagnostic_session_recovery_completion,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_ROLE_ID,
    P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioAdapter,
    RestrictedScenarioEngine,
    RestrictedScenarioWorker,
)


def _parse(raw: bytes) -> bool:
    try:
        parse_diagnostic_session_recovery_completion(json.loads(raw.decode("utf-8")))
        return True
    except (DiagnosticSessionRecoveryCompletionError, UnicodeDecodeError, json.JSONDecodeError):
        return False


P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER = RestrictedScenarioAdapter(
    P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID,
    P4_DIAGNOSTIC_RECOVERY_ROLE_ID,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
    "/usr/local/bin/prime-diagnostic-session-recovery.mjs",
    "prime-diagnostic-session-recovery",
    300,
    4096,
    _parse,
)


class DiagnosticSessionRecoveryWorker(RestrictedScenarioWorker):
    def __init__(self, *, image_digest: str, engine: RestrictedScenarioEngine) -> None:
        super().__init__(image_digest=image_digest, engine=engine, adapter=P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER)
