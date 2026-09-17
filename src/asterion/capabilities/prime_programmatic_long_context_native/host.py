"""Narrow runtime-facing host contract for native P2 programmatic-long-context."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol, runtime_checkable

from asterion.runtime.host import CancellationSignal


P2PendingClassification = Literal[
    "completed", "cancelled", "budget-limited", "recovery-required"
]
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class P2RuntimeHostError(RuntimeError):
    """Classify a stopped execution without exposing private host failures."""

    classification: Literal["budget-limited", "recovery-required"]

    def __init__(
        self, classification: Literal["budget-limited", "recovery-required"]
    ) -> None:
        if classification not in {"budget-limited", "recovery-required"}:
            raise ValueError("P2 runtime host classification is invalid")
        self.classification = classification
        super().__init__("P2 runtime host operation failed")


@dataclass(frozen=True, slots=True)
class P2RetrievalCall:
    """One bounded retrieval/transform round call against the injected service."""

    call_id: str
    operation: Literal["retrieve", "transform"]
    corpus_path: str
    query: str
    bounds: tuple[int, int]

    def __post_init__(self) -> None:
        if (
            type(self.call_id) is not str
            or not self.call_id
            or self.operation not in {"retrieve", "transform"}
            or type(self.corpus_path) is not str
            or not self.corpus_path
            or type(self.query) is not str
            or type(self.bounds) is not tuple
            or len(self.bounds) != 2
            or not all(_count(part) for part in self.bounds)
        ):
            raise ValueError("P2 retrieval call is invalid")


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True, slots=True)
class P2RetrievalReceipt:
    """Digest-only evidence emitted after one bounded retrieval/transform call."""

    call_id: str
    operation: Literal["retrieve", "transform"]
    result_sha256: str
    bytes_returned: int
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if (
            type(self.call_id) is not str
            or not self.call_id
            or self.operation not in {"retrieve", "transform"}
            or not _DIGEST.fullmatch(self.result_sha256)
            or not _count(self.bytes_returned)
            or not _count(self.input_tokens)
            or not _count(self.output_tokens)
        ):
            raise ValueError("P2 retrieval receipt is invalid")


@dataclass(frozen=True, slots=True)
class P2Finalization:
    """Cleanup-gated terminal classification transferred to to the runtime."""

    classification: P2PendingClassification
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
                raise ValueError("P2 finalization receipt is invalid")
            valid_receipt = _DIGEST.fullmatch(receipt) is not None
        else:
            valid_receipt = self.receipt_sha256 is None
        if not valid_classification or not valid_receipt:
            raise ValueError("P2 finalization is invalid")


@runtime_checkable
class P2RuntimeHost(Protocol):
    """Host barriers consumed by the P2 runtime session; never a delegated run."""

    def validate_runtime_services(
        self,
        *,
        ipython: object,
        oracle: object,
        extension: object,
        private_trace: object,
    ) -> None: ...

    async def execute_retrieval(
        self,
        *,
        run_id: str,
        call: P2RetrievalCall,
        signal: CancellationSignal | None,
    ) -> P2RetrievalReceipt: ...

    async def report_execution_stopped(
        self, *, run_id: str, pending_classification: P2PendingClassification
    ) -> None: ...

    async def wait_finalization(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P2Finalization: ...


__all__ = (
    "P2Finalization",
    "P2PendingClassification",
    "P2RetrievalCall",
    "P2RetrievalReceipt",
    "P2RuntimeHost",
    "P2RuntimeHostError",
)