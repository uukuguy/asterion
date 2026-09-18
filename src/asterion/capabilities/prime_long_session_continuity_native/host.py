"""Narrow runtime-facing host contract for native P4 long-session-continuity."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol, runtime_checkable

from asterion.runtime.host import CancellationSignal


P4PendingClassification = Literal[
    "completed", "cancelled", "budget-limited", "recovery-required"
]
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class P4RuntimeHostError(RuntimeError):
    """Classify a stopped execution without exposing private host failures."""

    classification: Literal["budget-limited", "recovery-required"]

    def __init__(
        self, classification: Literal["budget-limited", "recovery-required"]
    ) -> None:
        if classification not in {"budget-limited", "recovery-required"}:
            raise ValueError("P4 runtime host classification is invalid")
        self.classification = classification
        super().__init__("P4 runtime host operation failed")


@dataclass(frozen=True, slots=True)
class P4CommitCall:
    """One cross-generation checkpoint-commit round call against the injected service."""

    call_id: str
    prior_checkpoint_sha256: str | None
    continuation_id: str
    generation: int

    def __post_init__(self) -> None:
        if (
            type(self.call_id) is not str
            or not self.call_id
            or (
                self.prior_checkpoint_sha256 is not None
                and not _DIGEST.fullmatch(self.prior_checkpoint_sha256)
            )
            or type(self.continuation_id) is not str
            or not self.continuation_id
            or type(self.generation) is not int
            or self.generation < 1
        ):
            raise ValueError("P4 commit call is invalid")


@dataclass(frozen=True, slots=True)
class P4CommitReceipt:
    """Digest-only evidence emitted after one cross-generation commit round."""

    call_id: str
    checkpoint_sha256: str
    result_sha256: str
    generation: int
    bytes_returned: int

    def __post_init__(self) -> None:
        if (
            type(self.call_id) is not str
            or not self.call_id
            or not _DIGEST.fullmatch(self.checkpoint_sha256)
            or not _DIGEST.fullmatch(self.result_sha256)
            or type(self.generation) is not int
            or self.generation < 1
            or type(self.bytes_returned) is not int
            or self.bytes_returned < 0
        ):
            raise ValueError("P4 commit receipt is invalid")


@dataclass(frozen=True, slots=True)
class P4RecoveredSession:
    """Material recovered from the prior generation's checkpoint."""

    prior_checkpoint_sha256: str
    prior_generation: int
    recovered_payload_sha256: str
    bytes_returned: int

    def __post_init__(self) -> None:
        if (
            not _DIGEST.fullmatch(self.prior_checkpoint_sha256)
            or type(self.prior_generation) is not int
            or self.prior_generation < 1
            or not _DIGEST.fullmatch(self.recovered_payload_sha256)
            or type(self.bytes_returned) is not int
            or self.bytes_returned < 0
        ):
            raise ValueError("P4 recovered session is invalid")


@dataclass(frozen=True, slots=True)
class P4Finalization:
    """Cleanup-gated terminal classification transferred to the runtime."""

    classification: P4PendingClassification
    receipt_sha256: str | None

    def __post_init__(self) -> None:
        valid_classification = self.classification in {
            "completed",
            "cancelled",
            "budget-limited",
            "recovery-required",
        }
        valid_receipt: bool
        if self.classification == "completed":
            receipt = self.receipt_sha256
            if not isinstance(receipt, str):
                raise ValueError("P4 finalization receipt is invalid")
            valid_receipt = _DIGEST.fullmatch(receipt) is not None
        else:
            valid_receipt = self.receipt_sha256 is None
        if not valid_classification or not valid_receipt:
            raise ValueError("P4 finalization is invalid")


@runtime_checkable
class P4RuntimeHost(Protocol):
    """Host barriers consumed by the P4 runtime session; never a delegated run."""

    def validate_runtime_services(
        self,
        *,
        continuity_store: object,
        oracle: object,
        extension: object,
        private_trace: object,
        session_backend: object,
    ) -> None: ...

    async def commit_checkpoint(
        self,
        *,
        run_id: str,
        call: P4CommitCall,
        signal: CancellationSignal | None,
    ) -> P4CommitReceipt: ...

    async def wait_recovery(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P4RecoveredSession | None: ...

    async def report_recovery_stopped(
        self, *, run_id: str, pending_classification: P4PendingClassification
    ) -> None: ...

    async def wait_finalization(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P4Finalization: ...


__all__ = (
    "P4CommitCall",
    "P4CommitReceipt",
    "P4Finalization",
    "P4PendingClassification",
    "P4RecoveredSession",
    "P4RuntimeHost",
    "P4RuntimeHostError",
)