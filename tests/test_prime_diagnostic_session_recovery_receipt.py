from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from asterion.applications.prime_agent.diagnostic_session_recovery_receipt import (
    DiagnosticSessionRecoveryReceiptError,
    DiagnosticSessionRecoveryTrace,
    validate_diagnostic_session_recovery_trace,
)
from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
    P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
    P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
)


def _hash(letter: str) -> str:
    return "sha256:" + letter * 64


class _EqualsIpython(str):
    def __eq__(self, other: object) -> bool:
        return True


def _trace(**changes: object) -> DiagnosticSessionRecoveryTrace:
    values: dict[str, object] = {
        "workload_sha256": P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
        "root_pre_recovery_artifact_sha256": _hash("a"),
        "root_post_recovery_artifact_sha256": _hash("a"),
        "child_registry_sha256": _hash("b"),
        "checkpoint_sha256": _hash("c"),
        "compaction_summary_sha256": _hash("d"),
        "recovery_cursor_sha256": _hash("e"),
        "diagnostic_result_sha256": _hash("f"),
        "oracle_sha256": P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
        "schema_sha256": P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256,
        "model_sha256": P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
        "usage_sha256": _hash("1"),
        "root_tool_names": ("ipython",),
        "child_tool_names": ("ipython",),
        "root_pre_recovery_actions": 1,
        "root_post_recovery_actions": 1,
        "child_actions": 1,
        "detach_count": 1,
        "attach_count": 1,
        "compaction_count": 1,
        "supervisor_recovery_count": 1,
        "checkpoint_cursor_matches_attach": True,
        "compaction_on_active_path": True,
        "same_session_identity": True,
        "same_transcript_identity": True,
        "recovery_required_before_continue": True,
        "durable_assets_only": True,
        "uncertain_effect_fenced": True,
        "oracle_passed": True,
        "disposed": True,
        "reaped": True,
    }
    values.update(changes)
    return DiagnosticSessionRecoveryTrace(**values)  # type: ignore[arg-type]


class TestDiagnosticSessionRecoveryReceipt(unittest.TestCase):
    def test_accepts_only_the_complete_fixed_trace(self) -> None:
        validate_diagnostic_session_recovery_trace(_trace())

    def test_rejects_missing_recovery_and_cleanup_facts(self) -> None:
        for field in (
            "checkpoint_cursor_matches_attach", "compaction_on_active_path",
            "same_session_identity", "same_transcript_identity",
            "recovery_required_before_continue", "durable_assets_only",
            "uncertain_effect_fenced", "oracle_passed", "disposed", "reaped",
        ):
            with self.subTest(field=field), self.assertRaises(DiagnosticSessionRecoveryReceiptError):
                validate_diagnostic_session_recovery_trace(replace(_trace(), **{field: False}))

    def test_rejects_substitution_shape_and_count_bypasses(self) -> None:
        cases = (
            {"workload_sha256": _hash("0")},
            {"root_post_recovery_artifact_sha256": _hash("9")},
            {"model_sha256": _hash("2")},
            {"oracle_sha256": _hash("3")},
            {"schema_sha256": _hash("4")},
            {"root_tool_names": ("shell",)},
            {"child_tool_names": (_EqualsIpython("shell"),)},
            {"child_actions": True},
            {"attach_count": 2},
            {"detach_count": True},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(DiagnosticSessionRecoveryReceiptError):
                validate_diagnostic_session_recovery_trace(_trace(**changes))

    def test_rejects_hidden_fields_and_redacts_private_values(self) -> None:
        trace = _trace()
        object.__setattr__(trace, "private_diagnostic", "PRIVATE-DIAGNOSTIC")
        with self.assertRaises(DiagnosticSessionRecoveryReceiptError) as raised:
            validate_diagnostic_session_recovery_trace(trace)
        self.assertNotIn("PRIVATE-DIAGNOSTIC", repr(trace))
        self.assertNotIn("PRIVATE-DIAGNOSTIC", str(raised.exception))
        with self.assertRaises(FrozenInstanceError):
            _trace().disposed = False  # type: ignore[misc]
