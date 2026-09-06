"""Strict, redacted receipt validation for independent Prime P4 development."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from asterion.applications.prime_agent.operator.p4_development_workload import (
    P4_DEVELOPMENT_MODEL_DIGEST,
    P4_DEVELOPMENT_ORACLE_DIGEST,
    P4_DEVELOPMENT_SCHEMA_DIGEST,
    P4_DEVELOPMENT_WORKLOAD_DIGEST,
)


_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")


class P4DevelopmentReceiptError(ValueError):
    """Raised when the independent P4 receipt is not complete and exact."""

    def __init__(self, *_: object) -> None:
        super().__init__("P4 development receipt is invalid")


@dataclass(frozen=True, repr=False)
class P4DevelopmentReceipt:
    """Private normalized facts for the sole native direct reattachment run."""

    workload_sha256: str
    schema_sha256: str
    model_sha256: str
    initial_oracle_sha256: str
    recovery_oracle_sha256: str
    runtime_identity_sha256: str
    session_identity_sha256: str
    transcript_identity_sha256: str
    kernel_identity_sha256: str
    initial_attach_cursor_sha256: str
    checkpoint_cursor_sha256: str
    detach_cursor_sha256: str
    reattach_cursor_sha256: str
    checkpoint_sha256: str
    compaction_witness_sha256: str
    provider_usage_sha256: str
    diagnostic_result_sha256: str
    initial_attach_sequence: int
    checkpoint_sequence: int
    reattach_sequence: int
    zero_gap_from_sequence: int
    zero_gap_to_sequence: int
    supervisor_recovery_count: int
    daemon_restart_count: int
    initial_attach_count: int
    detach_count: int
    reattach_count: int
    prompt_count: int
    provider_callback_count: int
    ipython_call_count: int
    manual_compact_count: int
    runtime_identity_count: int
    session_identity_count: int
    transcript_identity_count: int
    kernel_identity_count: int
    kernel_restart_count: int
    child_count: int
    zero_gap_replay_exact: bool
    checkpoint_readback: bool
    model_settled: bool
    tool_settled: bool
    compaction_on_active_path: bool
    same_runtime_identity: bool
    same_session_identity: bool
    same_transcript_identity: bool
    same_kernel_identity: bool
    same_oracle: bool
    uncertain_effect_fenced: bool
    full_cleanup: bool

    def __repr__(self) -> str:
        return "P4DevelopmentReceipt(redacted)"


_FIELDS: Final = frozenset(P4DevelopmentReceipt.__dataclass_fields__)


def _is_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _is_exact_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _is_sequence(value: object) -> bool:
    return type(value) is int and value >= 0


def validate_p4_development_receipt(receipt: object) -> None:
    """Fail closed unless *receipt* proves every fixed P4 lifecycle fact."""

    if (
        type(receipt) is not P4DevelopmentReceipt
        or frozenset(vars(receipt)) != _FIELDS
        or receipt.workload_sha256 != P4_DEVELOPMENT_WORKLOAD_DIGEST
        or receipt.schema_sha256 != P4_DEVELOPMENT_SCHEMA_DIGEST
        or receipt.model_sha256 != P4_DEVELOPMENT_MODEL_DIGEST
        or receipt.initial_oracle_sha256 != P4_DEVELOPMENT_ORACLE_DIGEST
        or receipt.recovery_oracle_sha256 != P4_DEVELOPMENT_ORACLE_DIGEST
        or any(
            not _is_digest(value)
            for value in (
                receipt.runtime_identity_sha256,
                receipt.session_identity_sha256,
                receipt.transcript_identity_sha256,
                receipt.kernel_identity_sha256,
                receipt.initial_attach_cursor_sha256,
                receipt.checkpoint_cursor_sha256,
                receipt.detach_cursor_sha256,
                receipt.reattach_cursor_sha256,
                receipt.checkpoint_sha256,
                receipt.compaction_witness_sha256,
                receipt.provider_usage_sha256,
                receipt.diagnostic_result_sha256,
            )
        )
        or not all(
            _is_exact_int(value, expected)
            for value, expected in (
                (receipt.supervisor_recovery_count, 0),
                (receipt.daemon_restart_count, 0),
                (receipt.initial_attach_count, 1),
                (receipt.detach_count, 1),
                (receipt.reattach_count, 1),
                (receipt.prompt_count, 2),
                (receipt.provider_callback_count, 5),
                (receipt.ipython_call_count, 2),
                (receipt.manual_compact_count, 1),
                (receipt.runtime_identity_count, 1),
                (receipt.session_identity_count, 1),
                (receipt.transcript_identity_count, 1),
                (receipt.kernel_identity_count, 1),
                (receipt.kernel_restart_count, 0),
                (receipt.child_count, 0),
            )
        )
        or any(
            not _is_sequence(value)
            for value in (
                receipt.initial_attach_sequence,
                receipt.checkpoint_sequence,
                receipt.reattach_sequence,
                receipt.zero_gap_from_sequence,
                receipt.zero_gap_to_sequence,
            )
        )
        or receipt.initial_attach_sequence >= receipt.checkpoint_sequence
        or receipt.reattach_sequence != receipt.checkpoint_sequence
        or receipt.zero_gap_from_sequence != receipt.checkpoint_sequence
        or receipt.zero_gap_to_sequence != receipt.reattach_sequence
        or receipt.checkpoint_cursor_sha256 != receipt.detach_cursor_sha256
        or receipt.detach_cursor_sha256 != receipt.reattach_cursor_sha256
        or any(
            value is not True
            for value in (
                receipt.zero_gap_replay_exact,
                receipt.checkpoint_readback,
                receipt.model_settled,
                receipt.tool_settled,
                receipt.compaction_on_active_path,
                receipt.same_runtime_identity,
                receipt.same_session_identity,
                receipt.same_transcript_identity,
                receipt.same_kernel_identity,
                receipt.same_oracle,
                receipt.uncertain_effect_fenced,
                receipt.full_cleanup,
            )
        )
    ):
        raise P4DevelopmentReceiptError()


__all__ = (
    "P4DevelopmentReceipt",
    "P4DevelopmentReceiptError",
    "validate_p4_development_receipt",
)
