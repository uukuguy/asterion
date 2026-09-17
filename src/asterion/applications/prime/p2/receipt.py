"""Closed, content-safe projections of native P2 verification and cleanup."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal

from asterion.applications.prime.p2.oracle import P2Oracle, P2OracleReceipt, _digest
from asterion.applications.prime.p2.worker import P2WorkerCleanupReceipt


P2_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p2-native-receipt+json"
)


class P2ReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("P2 receipt rejected")


def _validate_safe_fields(value: "P2CleanupReceipt | P2NativeReceipt") -> None:
    for key, item in asdict(value).items():
        if key.endswith("_sha256"):
            if type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None:
                raise P2ReceiptError()
        elif key.endswith("_bytes"):
            if type(item) is not int or item < 0:
                raise P2ReceiptError()


@dataclass(frozen=True, slots=True)
class P2CleanupReceipt:
    worker_identity_sha256: str
    oracle_receipt_sha256: str
    worker_cleanup_sha256: str
    oracle_closed: bool
    worker_closed: bool
    bridge_closed: bool
    private_store_removed: bool

    def __post_init__(self) -> None:
        _validate_safe_fields(self)
        if not all(
            value is True
            for value in (
                self.oracle_closed,
                self.worker_closed,
                self.bridge_closed,
                self.private_store_removed,
            )
        ):
            raise P2ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class P2NativeReceipt:
    application: Literal["prime.programmatic-long-context@1.0.0"]
    runtime: Literal["asterion.prime"]
    worker_identity_sha256: str
    corpus_sha256: str
    retrieval_receipt_sha256: str
    oracle_receipt_sha256: str
    cleanup_receipt_sha256: str
    bytes_returned: int
    answer_sha256: str
    final_status: Literal["verified"]

    def __post_init__(self) -> None:
        _validate_safe_fields(self)
        if (
            self.application != "prime.programmatic-long-context@1.0.0"
            or self.runtime != "asterion.prime"
            or self.final_status != "verified"
        ):
            raise P2ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))


def seal_cleanup_receipt(
    oracle: P2Oracle,
    result: P2OracleReceipt,
    worker_cleanup: P2WorkerCleanupReceipt,
    *,
    oracle_closed: bool,
    worker_closed: bool,
    bridge_closed: bool,
    private_store_removed: bool,
) -> P2CleanupReceipt:
    """Seal owner-observed external cleanup and the worker's actual close receipt."""
    if (
        not result.succeeded
        or result.worker_identity_sha256 != worker_cleanup.worker_identity_sha256
    ):
        raise P2ReceiptError()
    receipt = P2CleanupReceipt(
        result.worker_identity_sha256,
        result.sha256(),
        worker_cleanup.sha256(),
        oracle_closed,
        worker_closed,
        bridge_closed,
        private_store_removed,
    )
    if oracle._cleanup is not None:
        if receipt != oracle._cleanup:
            raise P2ReceiptError()
        return oracle._cleanup
    oracle._cleanup = receipt
    return receipt


def build_native_receipt(
    oracle: P2Oracle,
    result: P2OracleReceipt,
    cleanup: P2CleanupReceipt,
) -> P2NativeReceipt:
    if (
        type(cleanup) is not P2CleanupReceipt
        or cleanup is not oracle._cleanup
        or cleanup.worker_identity_sha256 != result.worker_identity_sha256
        or cleanup.oracle_receipt_sha256 != result.sha256()
        or not result.succeeded
    ):
        raise P2ReceiptError()
    return P2NativeReceipt(
        application="prime.programmatic-long-context@1.0.0",
        runtime="asterion.prime",
        worker_identity_sha256=result.worker_identity_sha256,
        corpus_sha256=result.corpus_sha256,
        retrieval_receipt_sha256=result.retrieval_receipt_sha256,
        oracle_receipt_sha256=result.sha256(),
        cleanup_receipt_sha256=cleanup.sha256(),
        bytes_returned=result.bytes_returned,
        answer_sha256=result.answer_sha256,
        final_status="verified",
    )


__all__ = (
    "P2CleanupReceipt",
    "P2NativeReceipt",
    "P2_RECEIPT_MEDIA_TYPE",
    "P2ReceiptError",
    "build_native_receipt",
    "seal_cleanup_receipt",
)