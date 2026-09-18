"""Sealed cross-process continuity receipt for native P4."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Literal

from asterion.applications.prime.p4.oracle import P4OracleReceipt


P4_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p4-native-receipt+json"
)


class P4ReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("P4 receipt rejected")


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _validate_digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise P4ReceiptError()
    return value


@dataclass(frozen=True, slots=True)
class P4NativeReceipt:
    """Sealed cross-process continuity record.

    One receipt seals both operator invocations (commit-mode and recover-mode)
    against the same private_root. The oracle receipt captures whether the
    three continuity invariants held; this receipt is the content-safe public
    projection of that verdict plus the digests needed to reconstruct the
    continuity chain.
    """

    application: Literal["prime.long-session-continuity@1.0.0"]
    runtime: Literal["asterion.prime"]
    prior_checkpoint_sha256: str
    new_checkpoint_sha256: str
    continuation_id: str
    prior_generation: int
    new_generation: int
    oracle_receipt_sha256: str
    cleanup_receipt_sha256: str
    bytes_returned: int
    final_status: Literal["verified"]

    def __post_init__(self) -> None:
        _validate_digest(self.prior_checkpoint_sha256)
        _validate_digest(self.new_checkpoint_sha256)
        if (
            type(self.continuation_id) is not str
            or not self.continuation_id
        ):
            raise P4ReceiptError()
        if (
            type(self.prior_generation) is not int
            or self.prior_generation < 1
        ):
            raise P4ReceiptError()
        if (
            type(self.new_generation) is not int
            or self.new_generation < 1
            or self.new_generation != self.prior_generation + 1
        ):
            raise P4ReceiptError()
        _validate_digest(self.oracle_receipt_sha256)
        _validate_digest(self.cleanup_receipt_sha256)
        if (
            type(self.bytes_returned) is not int
            or self.bytes_returned < 0
        ):
            raise P4ReceiptError()
        if (
            self.application != "prime.long-session-continuity@1.0.0"
            or self.runtime != "asterion.prime"
            or self.final_status != "verified"
        ):
            raise P4ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))


def build_native_receipt(
    *,
    prior_checkpoint_sha256: str,
    new_checkpoint_sha256: str,
    continuation_id: str,
    prior_generation: int,
    new_generation: int,
    oracle: P4OracleReceipt,
    cleanup_receipt_sha256: str,
    bytes_returned: int,
) -> P4NativeReceipt:
    """Build the cross-process sealed receipt from oracle + cleanup digests."""

    if (
        type(oracle) is not P4OracleReceipt
        or not oracle.succeeded
    ):
        raise P4ReceiptError()
    return P4NativeReceipt(
        application="prime.long-session-continuity@1.0.0",
        runtime="asterion.prime",
        prior_checkpoint_sha256=prior_checkpoint_sha256,
        new_checkpoint_sha256=new_checkpoint_sha256,
        continuation_id=continuation_id,
        prior_generation=prior_generation,
        new_generation=new_generation,
        oracle_receipt_sha256=oracle.sha256(),
        cleanup_receipt_sha256=cleanup_receipt_sha256,
        bytes_returned=bytes_returned,
        final_status="verified",
    )


__all__ = (
    "P4_RECEIPT_MEDIA_TYPE",
    "P4NativeReceipt",
    "P4ReceiptError",
    "build_native_receipt",
)