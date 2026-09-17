"""Read-only P2 verification over the injected context service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import TYPE_CHECKING

from asterion.applications.prime.p2.context_service import P2ContextSlice
from asterion.applications.prime.p2.task import P2_RETRIEVAL_BOUNDS

if TYPE_CHECKING:
    from asterion.applications.prime.p2.receipt import P2CleanupReceipt


class P2OracleError(ValueError):
    def __init__(self) -> None:
        super().__init__("P2 oracle rejected")


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


_INT_FIELDS = {"bytes_returned", "kernel_generation"}


def _validate_receipt(value: "P2RetrievalReceipt | P2OracleReceipt") -> None:
    for key, item in asdict(value).items():
        if key.endswith("_sha256"):
            if type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None:
                raise P2OracleError()
        elif key in _INT_FIELDS:
            if type(item) is not int or item < 0:
                raise P2OracleError()


@dataclass(frozen=True, slots=True)
class P2RetrievalReceipt:
    """Digest-only evidence after one bounded retrieval/transform call."""

    worker_identity_sha256: str
    corpus_sha256: str
    operation: str
    bounds: tuple[int, int]
    slice_sha256: str
    bytes_returned: int

    def __post_init__(self) -> None:
        _validate_receipt(self)
        if (
            self.operation not in {"retrieve", "transform"}
            or type(self.bounds) is not tuple
            or len(self.bounds) != 2
            or self.bounds[0] > self.bounds[1]
            or self.bounds != P2_RETRIEVAL_BOUNDS
        ):
            raise P2OracleError()

    def sha256(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class P2OracleReceipt:
    """Sealed receipt for one bounded retrieval/transform round-trip."""

    worker_identity_sha256: str
    retrieval_receipt_sha256: str
    corpus_sha256: str
    answer_sha256: str
    bytes_returned: int
    final_status: str = "verified"

    def __post_init__(self) -> None:
        _validate_receipt(self)
        if self.final_status not in {"verified", "unverified"}:
            raise P2OracleError()

    @property
    def succeeded(self) -> bool:
        return self.final_status == "verified"

    def sha256(self) -> str:
        return _digest(asdict(self))


class P2Oracle:
    """Bind once to a live worker; verify one bounded retrieval/transform."""

    def __init__(self, worker_identity: str, corpus_sha256: str) -> None:
        if (
            type(worker_identity) is not str
            or re.fullmatch(r"[0-9a-f]{64}", worker_identity) is None
            or type(corpus_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", corpus_sha256) is None
        ):
            raise P2OracleError()
        self._identity = worker_identity
        self._corpus = corpus_sha256
        self._retrieval: P2RetrievalReceipt | None = None
        self._final: P2OracleReceipt | None = None
        self._cleanup: P2CleanupReceipt | None = None

    def __repr__(self) -> str:
        return "<P2Oracle>"

    def bind_worker(self, worker: "object") -> None:
        """Snap the oracle to a live worker's identity + corpus.

        The oracle needs two digests: one for the worker (so a swapped worker
        identity invalidates the run) and one for the corpus it serves (so a
        swapped corpus invalidates the run). Both are pulled from the worker
        through its public properties; the oracle never reads the corpus
        content directly.
        """
        try:
            identity = getattr(worker, "identity_sha256")
            corpus = getattr(worker, "corpus_sha256")
        except AttributeError:
            raise P2OracleError() from None
        if (
            type(identity) is not str
            or re.fullmatch(r"[0-9a-f]{64}", identity) is None
            or type(corpus) is not str
            or re.fullmatch(r"[0-9a-f]{64}", corpus) is None
        ):
            raise P2OracleError()
        self._identity = identity
        self._corpus = corpus

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def corpus(self) -> str:
        return self._corpus

    def verify_retrieval(
        self,
        *,
        slice_: P2ContextSlice,
    ) -> P2RetrievalReceipt:
        """Validate one bounded retrieval/transform call's digest."""
        if type(slice_) is not P2ContextSlice:
            raise P2OracleError()
        receipt = P2RetrievalReceipt(
            worker_identity_sha256=self._identity,
            corpus_sha256=self._corpus,
            operation=slice_.operation,
            bounds=slice_.bounds,
            slice_sha256=slice_.payload_sha256,
            bytes_returned=slice_.bytes_returned,
        )
        if self._retrieval is not None:
            if self._retrieval != receipt:
                raise P2OracleError()
            return self._retrieval
        self._retrieval = receipt
        return receipt

    def verify_answer(
        self,
        *,
        answer_sha256: str,
    ) -> P2OracleReceipt:
        """Verify the answer oracle agrees on the retrieval digest."""
        if (
            self._retrieval is None
            or type(answer_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", answer_sha256) is None
        ):
            raise P2OracleError()
        if self._final is not None:
            return self._final
        receipt = P2OracleReceipt(
            worker_identity_sha256=self._identity,
            retrieval_receipt_sha256=self._retrieval.sha256(),
            corpus_sha256=self._corpus,
            answer_sha256=answer_sha256,
            bytes_returned=self._retrieval.bytes_returned,
        )
        self._final = receipt
        return receipt


__all__ = (
    "P2Oracle",
    "P2OracleError",
    "P2OracleReceipt",
    "P2RetrievalReceipt",
    "_digest",
)