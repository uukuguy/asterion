"""Strict redacted receipt for the independent P6 development loop."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Final, Literal

from .p6_development_workload import (
    P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256,
    P6_DEVELOPMENT_MODEL_DIGEST,
    P6_DEVELOPMENT_ORACLE_DIGEST,
    P6_DEVELOPMENT_SCHEMA_DIGEST,
    P6_DEVELOPMENT_WORKLOAD_DIGEST,
    p6_development_branch_facts,
)


_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")


class P6DevelopmentReceiptError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P6 development receipt is invalid")


@dataclass(frozen=True, repr=False)
class P6DevelopmentReceipt:
    workload_sha256: str
    schema_sha256: str
    model_sha256: str
    oracle_sha256: str
    baseline_source_sha256: str
    candidate_source_sha256: str
    task_a_result_sha256: str
    holdout_result_sha256: str
    final_source_sha256: str
    outcome_sha256: str
    run_sha256: str
    session_sha256: str
    container_sha256: str
    image_sha256: str
    usage_sha256: str
    project_scope_sha256: str
    baseline_harness_snapshot_sha256: str
    candidate_harness_snapshot_sha256: str
    final_harness_snapshot_sha256: str
    proposal_sha256: str
    candidate_revision_sha256: str
    rollback_revision_sha256: str | None
    scope_kind: Literal["project"]
    tool_names: tuple[str, ...]
    prompt_count: int
    provider_callback_count: int
    ipython_call_count: int
    candidate_count: int
    holdout_count: int
    rollback_count: int
    outcome: Literal["preserved", "rolled-back"]
    terminal: bool
    full_cleanup: bool

    @property
    def trace_sha256(self) -> str:
        validate_p6_development_receipt(self)
        payload = dict(vars(self))
        payload["tool_names"] = list(self.tool_names)
        return "sha256:" + sha256(
            json.dumps(
                {"format": "asterion.prime-p6-development-trace/v1", "receipt": payload},
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def __repr__(self) -> str:
        return "P6DevelopmentReceipt(redacted)"


_FIELDS: Final = frozenset(P6DevelopmentReceipt.__dataclass_fields__)
_DIGEST_FIELDS: Final = tuple(
    name
    for name in _FIELDS
    if name.endswith("_sha256") and name != "rollback_revision_sha256"
)
_COUNTS: Final = {
    "prompt_count": 3,
    "provider_callback_count": 6,
    "ipython_call_count": 3,
    "candidate_count": 1,
    "holdout_count": 1,
}


def validate_p6_development_receipt(receipt: object) -> None:
    if (
        type(receipt) is not P6DevelopmentReceipt
        or frozenset(vars(receipt)) != _FIELDS
        or any(
            type(getattr(receipt, name)) is not str
            or _DIGEST.fullmatch(getattr(receipt, name)) is None
            for name in _DIGEST_FIELDS
        )
        or receipt.workload_sha256 != P6_DEVELOPMENT_WORKLOAD_DIGEST
        or receipt.schema_sha256 != P6_DEVELOPMENT_SCHEMA_DIGEST
        or receipt.model_sha256 != P6_DEVELOPMENT_MODEL_DIGEST
        or receipt.oracle_sha256 != P6_DEVELOPMENT_ORACLE_DIGEST
        or receipt.baseline_source_sha256 != P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256
        or receipt.scope_kind != "project"
        or receipt.tool_names != ("ipython",)
        or any(
            type(getattr(receipt, name)) is not int
            or getattr(receipt, name) != expected
            for name, expected in _COUNTS.items()
        )
        or type(receipt.rollback_count) is not int
        or receipt.outcome not in {"preserved", "rolled-back"}
        or any(getattr(receipt, name) is not True for name in ("terminal", "full_cleanup"))
    ):
        raise P6DevelopmentReceiptError()
    try:
        branch = p6_development_branch_facts(receipt.outcome)
    except ValueError:
        raise P6DevelopmentReceiptError() from None
    if (
        receipt.candidate_source_sha256 != branch["candidate_source_sha256"]
        or receipt.final_source_sha256 != branch["final_source_sha256"]
        or receipt.rollback_count != branch["rollback_count"]
    ):
        raise P6DevelopmentReceiptError()
    if (
        receipt.baseline_harness_snapshot_sha256
        == receipt.candidate_harness_snapshot_sha256
        or receipt.outcome == "preserved"
        and (
            receipt.final_harness_snapshot_sha256
            != receipt.candidate_harness_snapshot_sha256
            or receipt.rollback_revision_sha256 is not None
        )
        or receipt.outcome == "rolled-back"
        and (
            receipt.final_harness_snapshot_sha256
            != receipt.baseline_harness_snapshot_sha256
            or type(receipt.rollback_revision_sha256) is not str
            or _DIGEST.fullmatch(receipt.rollback_revision_sha256) is None
        )
    ):
        raise P6DevelopmentReceiptError()


__all__ = (
    "P6DevelopmentReceipt",
    "P6DevelopmentReceiptError",
    "validate_p6_development_receipt",
)
