"""Sealed P5 application receipt for native prime bounded-autonomy loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
from typing import Literal


_P5_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p5-native-receipt+json"
)


TerminalReason = Literal[
    "success",
    "iteration-cap-exceeded",
    "duration-cap-exceeded",
    "no-progress",
    "cancelled",
]


_TERMINAL_REASONS: frozenset[str] = frozenset(
    {
        "success",
        "iteration-cap-exceeded",
        "duration-cap-exceeded",
        "no-progress",
        "cancelled",
    }
)


class P5ReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("P5 receipt rejected")


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class P5NativeReceipt:
    """Sealed P5 receipt.

    Application-level proof that a bounded propose/verify/repair loop
    terminated exactly once with one of the closed
    :data:`TerminalReason` values — never ``"still-running"``.
    ``joined_workspace_digest`` is the final workspace digest (the last
    progress-making propose / repair digest, or the prior gate's digest
    if the loop terminated with ``no-progress``). ``receipt_sha256`` is
    the canonical-JSON SHA-256 of every other field.
    """

    root_run_id: str
    root_generation: int
    propose_step_count: int
    verify_step_count: int
    repair_step_count: int
    failed_verify_count: int
    terminal_reason: TerminalReason
    joined_workspace_digest: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.root_run_id) is not str or not self.root_run_id:
            raise P5ReceiptError()
        if (
            type(self.root_generation) is not int
            or self.root_generation < 1
        ):
            raise P5ReceiptError()
        if (
            type(self.propose_step_count) is not int
            or self.propose_step_count < 1
        ):
            raise P5ReceiptError()
        if (
            type(self.verify_step_count) is not int
            or self.verify_step_count < 1
        ):
            raise P5ReceiptError()
        if (
            type(self.repair_step_count) is not int
            or self.repair_step_count < 0
        ):
            raise P5ReceiptError()
        if (
            type(self.failed_verify_count) is not int
            or self.failed_verify_count < 1
        ):
            raise P5ReceiptError()
        if self.terminal_reason not in _TERMINAL_REASONS:
            raise P5ReceiptError()
        if (
            type(self.joined_workspace_digest) is not str
            or not self.joined_workspace_digest
        ):
            raise P5ReceiptError()
        if (
            type(self.receipt_sha256) is not str
            or not self.receipt_sha256
        ):
            raise P5ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))

    @staticmethod
    def media_type() -> str:
        return _P5_RECEIPT_MEDIA_TYPE


def media_type() -> str:
    """Return the closed media type string for P5 receipts:

    ``application/vnd.asterion.prime.p5-native-receipt+json``.

    Mirror P3's :attr:`P3NativeReceipt.media_type` helper. Mirrored as a
    module-level function so callers can resolve it without importing the
    dataclass.
    """

    return _P5_RECEIPT_MEDIA_TYPE


def seal(
    *,
    root_run_id: str,
    root_generation: int,
    propose_step_count: int,
    verify_step_count: int,
    repair_step_count: int,
    failed_verify_count: int,
    terminal_reason: TerminalReason,
    joined_workspace_digest: str,
) -> P5NativeReceipt:
    """Compute ``receipt_sha256`` as canonical-JSON SHA-256 of all other
    fields, then return the frozen receipt. Mirrors P3's ``seal()``
    exactly.
    """

    digest_payload = {
        "failed_verify_count": failed_verify_count,
        "joined_workspace_digest": joined_workspace_digest,
        "propose_step_count": propose_step_count,
        "repair_step_count": repair_step_count,
        "root_generation": root_generation,
        "root_run_id": root_run_id,
        "terminal_reason": terminal_reason,
        "verify_step_count": verify_step_count,
    }
    return P5NativeReceipt(
        root_run_id=root_run_id,
        root_generation=root_generation,
        propose_step_count=propose_step_count,
        verify_step_count=verify_step_count,
        repair_step_count=repair_step_count,
        failed_verify_count=failed_verify_count,
        terminal_reason=terminal_reason,
        joined_workspace_digest=joined_workspace_digest,
        receipt_sha256=_digest(digest_payload),
    )


def build(**fields_kwargs: object) -> P5NativeReceipt:
    """Test-only constructor.

    Does NOT recompute ``receipt_sha256`` — caller supplies it directly.
    Used by tests to construct receipts with known digests for
    comparison. P3 has the same pattern.
    """

    allowed = {f.name for f in fields(P5NativeReceipt)}
    unknown = set(fields_kwargs) - allowed
    if unknown:
        raise P5ReceiptError()
    if "receipt_sha256" not in fields_kwargs:
        raise P5ReceiptError()
    return P5NativeReceipt(**fields_kwargs)  # type: ignore[arg-type]


__all__ = (
    "P5NativeReceipt",
    "P5ReceiptError",
    "TerminalReason",
    "build",
    "media_type",
    "seal",
)
