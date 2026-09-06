"""Strict redacted receipt for the fixed independent P5 development loop."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from .p5_development_workload import P5_DEVELOPMENT_MODEL_DIGEST, P5_DEVELOPMENT_ORACLE_DIGEST, P5_DEVELOPMENT_SCHEMA_DIGEST, P5_DEVELOPMENT_WORKLOAD_DIGEST

_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")


class P5DevelopmentReceiptError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P5 development receipt is invalid")


@dataclass(frozen=True, repr=False)
class P5DevelopmentReceipt:
    workload_sha256: str; schema_sha256: str; model_sha256: str; oracle_sha256: str
    goal_sha256: str; session_sha256: str; container_sha256: str
    initial_snapshot_sha256: str; repaired_snapshot_sha256: str
    first_result_sha256: str; second_result_sha256: str; first_quality_sha256: str; second_quality_sha256: str
    feedback_sha256: str; artifact_sha256: str; usage_sha256: str
    prompt_count: int; provider_callback_count: int; ipython_call_count: int; result_gate_count: int; quality_gate_count: int; feedback_count: int; repair_count: int; retry_count: int; child_count: int; compact_count: int
    same_goal: bool; same_session: bool; same_container: bool; first_result_passed: bool; second_result_passed: bool; first_quality_failed: bool; second_quality_passed: bool; workspace_changed: bool; full_cleanup: bool
    def __repr__(self) -> str:
        return "P5DevelopmentReceipt(redacted)"


_FIELDS: Final = frozenset(P5DevelopmentReceipt.__dataclass_fields__)
_DIGEST_FIELDS: Final = tuple(name for name in _FIELDS if name.endswith("_sha256"))
_COUNTS: Final = {"prompt_count": 2, "provider_callback_count": 4, "ipython_call_count": 2, "result_gate_count": 2, "quality_gate_count": 2, "feedback_count": 1, "repair_count": 1, "retry_count": 0, "child_count": 0, "compact_count": 0}
_TRUTHS: Final = ("same_goal", "same_session", "same_container", "first_result_passed", "second_result_passed", "first_quality_failed", "second_quality_passed", "workspace_changed", "full_cleanup")


def validate_p5_development_receipt(receipt: object) -> None:
    if (
        type(receipt) is not P5DevelopmentReceipt or frozenset(vars(receipt)) != _FIELDS
        or any(type(getattr(receipt, name)) is not str or _DIGEST.fullmatch(getattr(receipt, name)) is None for name in _DIGEST_FIELDS)
        or receipt.workload_sha256 != P5_DEVELOPMENT_WORKLOAD_DIGEST or receipt.schema_sha256 != P5_DEVELOPMENT_SCHEMA_DIGEST or receipt.model_sha256 != P5_DEVELOPMENT_MODEL_DIGEST or receipt.oracle_sha256 != P5_DEVELOPMENT_ORACLE_DIGEST
        or receipt.initial_snapshot_sha256 == receipt.repaired_snapshot_sha256
        or any(type(getattr(receipt, name)) is not int or getattr(receipt, name) != expected for name, expected in _COUNTS.items())
        or any(getattr(receipt, name) is not True for name in _TRUTHS)
    ):
        raise P5DevelopmentReceiptError()


__all__ = ("P5DevelopmentReceipt", "P5DevelopmentReceiptError", "validate_p5_development_receipt")
