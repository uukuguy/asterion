"""Closed validation for the fixed Prime P4 diagnostic recovery trace."""

from __future__ import annotations

from dataclasses import dataclass
import re

from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
    P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
    P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TRACE_FIELDS = frozenset({
    "workload_sha256", "root_pre_recovery_artifact_sha256",
    "root_post_recovery_artifact_sha256", "child_registry_sha256",
    "checkpoint_sha256", "compaction_summary_sha256", "recovery_cursor_sha256",
    "diagnostic_result_sha256", "oracle_sha256", "schema_sha256", "model_sha256",
    "usage_sha256", "root_tool_names", "child_tool_names",
    "root_pre_recovery_actions", "root_post_recovery_actions", "child_actions",
    "detach_count", "attach_count", "compaction_count", "supervisor_recovery_count",
    "checkpoint_cursor_matches_attach", "compaction_on_active_path",
    "same_session_identity", "same_transcript_identity",
    "recovery_required_before_continue", "durable_assets_only",
    "uncertain_effect_fenced", "oracle_passed", "disposed", "reaped",
})


class DiagnosticSessionRecoveryReceiptError(ValueError):
    """Raised when a diagnostic recovery trace is incomplete or invalid."""


@dataclass(frozen=True, repr=False)
class DiagnosticSessionRecoveryTrace:
    """Private normalized facts for one fixed diagnostic recovery."""

    workload_sha256: str
    root_pre_recovery_artifact_sha256: str
    root_post_recovery_artifact_sha256: str
    child_registry_sha256: str
    checkpoint_sha256: str
    compaction_summary_sha256: str
    recovery_cursor_sha256: str
    diagnostic_result_sha256: str
    oracle_sha256: str
    schema_sha256: str
    model_sha256: str
    usage_sha256: str
    root_tool_names: tuple[str]
    child_tool_names: tuple[str]
    root_pre_recovery_actions: int
    root_post_recovery_actions: int
    child_actions: int
    detach_count: int
    attach_count: int
    compaction_count: int
    supervisor_recovery_count: int
    checkpoint_cursor_matches_attach: bool
    compaction_on_active_path: bool
    same_session_identity: bool
    same_transcript_identity: bool
    recovery_required_before_continue: bool
    durable_assets_only: bool
    uncertain_effect_fenced: bool
    oracle_passed: bool
    disposed: bool
    reaped: bool

    def __repr__(self) -> str:
        return "DiagnosticSessionRecoveryTrace(redacted)"


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _ipython_only(value: object) -> bool:
    return type(value) is tuple and value == ("ipython",)


def validate_diagnostic_session_recovery_trace(trace: object) -> None:
    """Fail closed unless *trace* proves every fixed P4 recovery fact."""

    if (
        type(trace) is not DiagnosticSessionRecoveryTrace
        or frozenset(vars(trace)) != _TRACE_FIELDS
        or trace.workload_sha256 != P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST
        or trace.oracle_sha256 != P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256
        or trace.schema_sha256 != P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256
        or trace.model_sha256 != P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256
        or any(not _digest(value) for value in (
            trace.root_pre_recovery_artifact_sha256,
            trace.root_post_recovery_artifact_sha256,
            trace.child_registry_sha256,
            trace.checkpoint_sha256,
            trace.compaction_summary_sha256,
            trace.recovery_cursor_sha256,
            trace.diagnostic_result_sha256,
            trace.usage_sha256,
        ))
        or trace.root_pre_recovery_artifact_sha256 != trace.root_post_recovery_artifact_sha256
        or not _ipython_only(trace.root_tool_names)
        or not _ipython_only(trace.child_tool_names)
        or any(not _positive_int(value) for value in (
            trace.root_pre_recovery_actions,
            trace.root_post_recovery_actions,
            trace.child_actions,
        ))
        or any(value != 1 for value in (
            trace.detach_count,
            trace.attach_count,
            trace.compaction_count,
            trace.supervisor_recovery_count,
        ))
        or any(value is not True for value in (
            trace.checkpoint_cursor_matches_attach,
            trace.compaction_on_active_path,
            trace.same_session_identity,
            trace.same_transcript_identity,
            trace.recovery_required_before_continue,
            trace.durable_assets_only,
            trace.uncertain_effect_fenced,
            trace.oracle_passed,
            trace.disposed,
            trace.reaped,
        ))
    ):
        raise DiagnosticSessionRecoveryReceiptError(
            "diagnostic session recovery trace is invalid"
        )
