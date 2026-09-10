"""Narrow runtime-facing host contract for native P1 coordination."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol, runtime_checkable

from asterion.runtime.host import CancellationSignal


P1PendingClassification = Literal[
    "completed", "cancelled", "budget-limited", "recovery-required"
]
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class P1RuntimeHostError(RuntimeError):
    """Classify a stopped execution without exposing private host failures."""

    classification: Literal["budget-limited", "recovery-required"]

    def __init__(
        self, classification: Literal["budget-limited", "recovery-required"]
    ) -> None:
        if classification not in {"budget-limited", "recovery-required"}:
            raise ValueError("P1 runtime host classification is invalid")
        self.classification = classification
        super().__init__("P1 runtime host operation failed")


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True, slots=True)
class P1StageMilestone:
    """Digest-only evidence emitted after one runtime-owned coding stage."""

    stage: Literal["stage-one", "stage-two"]
    effect_sha256: str
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if (
            self.stage not in {"stage-one", "stage-two"}
            or not _digest(self.effect_sha256)
            or not _count(self.input_tokens)
            or not _count(self.output_tokens)
        ):
            raise ValueError("P1 stage milestone is invalid")


@dataclass(frozen=True, slots=True)
class P1StageTwoRelease:
    """Safe checkpoint evidence authorizing the second stage."""

    checkpoint_sha256: str
    compact_receipt_sha256: str
    before_context_tokens: int
    after_context_tokens: int
    reconstruction_generation: int
    compact_reserved_tokens: int

    def __post_init__(self) -> None:
        if (
            not _digest(self.checkpoint_sha256)
            or not _digest(self.compact_receipt_sha256)
            or not _count(self.before_context_tokens)
            or not _count(self.after_context_tokens)
            or self.after_context_tokens >= self.before_context_tokens
            or type(self.reconstruction_generation) is not int
            or self.reconstruction_generation < 2
            or not _count(self.compact_reserved_tokens)
        ):
            raise ValueError("P1 stage-two release is invalid")


@dataclass(frozen=True, slots=True)
class P1Finalization:
    """Cleanup-gated terminal classification transferred to the runtime."""

    classification: P1PendingClassification
    receipt_sha256: str | None

    def __post_init__(self) -> None:
        valid_classification = self.classification in {
            "completed",
            "cancelled",
            "budget-limited",
            "recovery-required",
        }
        valid_receipt = (
            _digest(self.receipt_sha256)
            if self.classification == "completed"
            else self.receipt_sha256 is None
        )
        if not valid_classification or not valid_receipt:
            raise ValueError("P1 finalization is invalid")


@runtime_checkable
class P1RuntimeHost(Protocol):
    """Task-8-implementable barriers; never a delegated runtime ``run``."""

    def validate_runtime_services(
        self,
        *,
        ipython: object,
        oracle: object,
        pi_extension: object,
        private_trace: object,
    ) -> None: ...

    async def execute_stage_one(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P1StageMilestone: ...

    async def publish_milestone(
        self, *, run_id: str, milestone: P1StageMilestone
    ) -> None: ...

    async def wait_stage_two_release(
        self,
        *,
        run_id: str,
        stage_one: P1StageMilestone,
        signal: CancellationSignal | None,
    ) -> P1StageTwoRelease: ...

    async def execute_stage_two(
        self,
        *,
        run_id: str,
        release: P1StageTwoRelease,
        signal: CancellationSignal | None,
    ) -> P1StageMilestone: ...

    async def report_execution_stopped(
        self, *, run_id: str, pending_classification: P1PendingClassification
    ) -> None: ...

    async def wait_finalization(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P1Finalization: ...


__all__ = (
    "P1Finalization",
    "P1PendingClassification",
    "P1RuntimeHost",
    "P1RuntimeHostError",
    "P1StageMilestone",
    "P1StageTwoRelease",
)
