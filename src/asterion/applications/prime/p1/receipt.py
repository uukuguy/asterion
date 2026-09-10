"""Closed, content-safe projections of native P1 verification and cleanup."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal

from .oracle import P1Oracle, P1OracleReceipt, _digest
from .worker import P1WorkerCleanupReceipt

P1_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p1-native-receipt+json"


class P1ReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("P1 receipt rejected")


def _validate_safe_fields(value: P1CleanupReceipt | P1NativeReceipt) -> None:
    for key, item in asdict(value).items():
        if key.endswith("_sha256"):
            if type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None:
                raise P1ReceiptError()
        elif key.endswith("_generation") or key.endswith("_tokens"):
            if type(item) is not int or item < 0:
                raise P1ReceiptError()


@dataclass(frozen=True, slots=True)
class P1CleanupReceipt:
    worker_identity_sha256: str
    oracle_receipt_sha256: str
    worker_cleanup_sha256: str
    backend_closed: bool
    pi_reaped: bool
    extension_closed: bool
    private_store_removed: bool

    def __post_init__(self) -> None:
        _validate_safe_fields(self)
        if not all(
            value is True
            for value in (
                self.backend_closed,
                self.pi_reaped,
                self.extension_closed,
                self.private_store_removed,
            )
        ):
            raise P1ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class P1NativeReceipt:
    application: Literal["prime.ipython-coding@1.0.0"]
    runtime: Literal["asterion.prime"]
    kernel_generation: int
    worker_identity_sha256: str
    checkpoint_sha256: str
    compact_receipt_sha256: str
    stage_one_effect_sha256: str
    stage_two_effect_sha256: str
    oracle_receipt_sha256: str
    cleanup_receipt_sha256: str
    compact_usage: Literal["reservation-charged"]
    before_context_tokens: int
    after_context_tokens: int
    control_reconstruction_generation: int
    final_status: Literal["verified"]

    def __post_init__(self) -> None:
        _validate_safe_fields(self)
        if (
            self.application != "prime.ipython-coding@1.0.0"
            or self.runtime != "asterion.prime"
            or self.compact_usage != "reservation-charged"
            or self.final_status != "verified"
            or self.kernel_generation < 1
            or self.control_reconstruction_generation < 2
            or self.after_context_tokens >= self.before_context_tokens
        ):
            raise P1ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))


def seal_cleanup_receipt(
    oracle: P1Oracle,
    result: P1OracleReceipt,
    worker_cleanup: P1WorkerCleanupReceipt,
    *,
    backend_closed: bool,
    pi_reaped: bool,
    extension_closed: bool,
    private_store_removed: bool,
) -> P1CleanupReceipt:
    """Seal owner-observed external cleanup and the worker's actual close receipt.

    External flags are trusted operator observations, never model/tool inputs.
    They must come from the resource owners after their close operations return.
    """
    if not oracle.validates_result(result) or not oracle.validates_worker_cleanup(
        worker_cleanup
    ):
        raise P1ReceiptError()
    receipt = P1CleanupReceipt(
        result.worker_identity_sha256,
        result.sha256(),
        worker_cleanup.sha256(),
        backend_closed,
        pi_reaped,
        extension_closed,
        private_store_removed,
    )
    if oracle._cleanup is not None:
        if receipt != oracle._cleanup:
            raise P1ReceiptError()
        return oracle._cleanup
    oracle._cleanup = receipt
    return receipt


def build_native_receipt(
    oracle: P1Oracle,
    result: P1OracleReceipt,
    cleanup: P1CleanupReceipt,
) -> P1NativeReceipt:
    if (
        not oracle.validates_result(result)
        or cleanup is not oracle._cleanup
        or type(cleanup) is not P1CleanupReceipt
        or cleanup.worker_identity_sha256 != result.worker_identity_sha256
        or cleanup.oracle_receipt_sha256 != result.sha256()
        or not result.succeeded
        or result.after_attachment_generation != result.before_attachment_generation + 1
    ):
        raise P1ReceiptError()
    return P1NativeReceipt(
        application="prime.ipython-coding@1.0.0",
        runtime="asterion.prime",
        kernel_generation=result.kernel_generation,
        worker_identity_sha256=result.worker_identity_sha256,
        checkpoint_sha256=result.checkpoint_sha256,
        compact_receipt_sha256=result.compact_receipt_sha256,
        stage_one_effect_sha256=result.stage_one_effect_sha256,
        stage_two_effect_sha256=result.stage_two_effect_sha256,
        oracle_receipt_sha256=result.sha256(),
        cleanup_receipt_sha256=cleanup.sha256(),
        compact_usage="reservation-charged",
        before_context_tokens=result.before_context_tokens,
        after_context_tokens=result.after_context_tokens,
        control_reconstruction_generation=result.after_attachment_generation,
        final_status="verified",
    )
