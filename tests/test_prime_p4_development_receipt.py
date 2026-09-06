from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.operator.p4_development_receipt import (
    P4DevelopmentReceipt,
    P4DevelopmentReceiptError,
    validate_p4_development_receipt,
)
from asterion.applications.prime_agent.operator.p4_development_workload import (
    P4_DEVELOPMENT_MODEL_DIGEST,
    P4_DEVELOPMENT_ORACLE_DIGEST,
    P4_DEVELOPMENT_SCHEMA_DIGEST,
    P4_DEVELOPMENT_WORKLOAD_DIGEST,
)


def _digest(value: str) -> str:
    return "sha256:" + value * 64


def _receipt(**changes: object) -> P4DevelopmentReceipt:
    values: dict[str, object] = {
        "workload_sha256": P4_DEVELOPMENT_WORKLOAD_DIGEST,
        "schema_sha256": P4_DEVELOPMENT_SCHEMA_DIGEST,
        "model_sha256": P4_DEVELOPMENT_MODEL_DIGEST,
        "initial_oracle_sha256": P4_DEVELOPMENT_ORACLE_DIGEST,
        "recovery_oracle_sha256": P4_DEVELOPMENT_ORACLE_DIGEST,
        "runtime_identity_sha256": _digest("1"),
        "session_identity_sha256": _digest("2"),
        "transcript_identity_sha256": _digest("3"),
        "kernel_identity_sha256": _digest("4"),
        "initial_attach_cursor_sha256": _digest("5"),
        "detach_cursor_sha256": _digest("5"),
        "reattach_cursor_sha256": _digest("5"),
        "checkpoint_readback_cursor_sha256": _digest("5"),
        "supervisor_recovery_count": 0,
        "daemon_restart_count": 0,
        "initial_attach_count": 1,
        "detach_count": 1,
        "reattach_count": 1,
        "prompt_count": 2,
        "provider_callback_count": 5,
        "ipython_call_count": 2,
        "manual_compact_count": 1,
        "runtime_identity_count": 1,
        "session_identity_count": 1,
        "transcript_identity_count": 1,
        "kernel_identity_count": 1,
        "kernel_restart_count": 0,
        "child_count": 0,
        "zero_gap_replay_exact": True,
        "checkpoint_readback": True,
        "model_settled": True,
        "tool_settled": True,
        "full_cleanup": True,
    }
    values.update(changes)
    return P4DevelopmentReceipt(**values)  # type: ignore[arg-type]


class TestP4DevelopmentReceipt(unittest.TestCase):
    def test_accepts_the_complete_native_direct_reattach_receipt(self) -> None:
        validate_p4_development_receipt(_receipt())

    def test_rejects_identity_cursor_and_cleanup_substitutions(self) -> None:
        cases = (
            {"runtime_identity_count": 2},
            {"kernel_restart_count": 1},
            {"recovery_oracle_sha256": _digest("a")},
            {"reattach_cursor_sha256": _digest("6")},
            {"checkpoint_readback_cursor_sha256": _digest("7")},
            {"zero_gap_replay_exact": False},
            {"checkpoint_readback": False},
            {"full_cleanup": False},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(P4DevelopmentReceiptError):
                    validate_p4_development_receipt(_receipt(**changes))

    def test_rejects_bool_as_int_hidden_fields_and_exposes_no_private_values(self) -> None:
        for field in ("supervisor_recovery_count", "prompt_count", "child_count"):
            with self.subTest(field=field):
                with self.assertRaises(P4DevelopmentReceiptError):
                    validate_p4_development_receipt(_receipt(**{field: True}))

        receipt = _receipt()
        object.__setattr__(receipt, "private_value", "P4-PRIVATE-SENTINEL")
        with self.assertRaises(P4DevelopmentReceiptError) as raised:
            validate_p4_development_receipt(receipt)
        self.assertNotIn("P4-PRIVATE-SENTINEL", repr(receipt))
        self.assertNotIn("P4-PRIVATE-SENTINEL", str(raised.exception))
        with self.assertRaises(FrozenInstanceError):
            _receipt().full_cleanup = False  # type: ignore[misc]
