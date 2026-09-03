from __future__ import annotations

import unittest

from asterion.applications.prime_agent.diagnostic_session_recovery_adapter import (
    DiagnosticRecoveryCheckpoint,
    DiagnosticRecoveryGatewayState,
    DiagnosticSessionRecoveryAdapterError,
    recover_diagnostic_session,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
    P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
)


def _digest(letter: str) -> str:
    return "sha256:" + letter * 64


def _checkpoint() -> DiagnosticRecoveryCheckpoint:
    return DiagnosticRecoveryCheckpoint(
        P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
        _digest("a"),
        _digest("b"),
        P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
        P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
        _digest("c"),
    )


def _state(generation: int, required: bool, **changes: object) -> DiagnosticRecoveryGatewayState:
    values: dict[str, object] = {
        "session_sha256": _digest("1"), "transcript_sha256": _digest("2"),
        "cursor_sha256": _digest("c"), "supervisor_generation": generation,
        "recovery_required": required, "compaction_on_active_path": True,
        "durable_assets_only": True, "uncertain_effect_fenced": True,
    }
    values.update(changes)
    return DiagnosticRecoveryGatewayState(**values)  # type: ignore[arg-type]


class _Gateway:
    def __init__(self, states: list[DiagnosticRecoveryGatewayState]) -> None:
        self.states = states
        self.calls: list[str] = []

    async def detach(self) -> DiagnosticRecoveryGatewayState:
        self.calls.append("detach")
        return self.states.pop(0)

    async def attach(self, cursor_sha256: str) -> DiagnosticRecoveryGatewayState:
        self.calls.append("attach")
        return self.states.pop(0)

    async def compact(self) -> DiagnosticRecoveryGatewayState:
        self.calls.append("compact")
        return self.states.pop(0)


class TestDiagnosticSessionRecoveryAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_runs_only_sealed_recovery_order(self) -> None:
        gateway = _Gateway([_state(1, False), _state(2, True), _state(2, True)])

        result = await recover_diagnostic_session(gateway, _checkpoint(), _state(1, False))

        self.assertEqual(gateway.calls, ["detach", "attach", "compact"])
        self.assertEqual(result.supervisor_generation, 2)

    async def test_rejects_invalid_input_before_gateway_calls(self) -> None:
        gateway = _Gateway([])

        with self.assertRaises(DiagnosticSessionRecoveryAdapterError):
            await recover_diagnostic_session(gateway, object(), _state(1, False))

        self.assertEqual(gateway.calls, [])

    async def test_rejects_identity_generation_and_recovery_fence_mismatches(self) -> None:
        for final in (
            _state(1, True),
            _state(2, False),
            _state(2, True, durable_assets_only=False),
            _state(2, True, session_sha256=_digest("9")),
        ):
            with self.subTest(final=final), self.assertRaises(DiagnosticSessionRecoveryAdapterError):
                await recover_diagnostic_session(
                    _Gateway([_state(1, False), _state(2, True), final]),
                    _checkpoint(),
                    _state(1, False),
                )
