"""Sealed P3 application receipt for native prime recursive workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json


_P3_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p3-native-receipt+json"
)


class P3ReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("P3 receipt rejected")


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class P3NativeReceipt:
    """Sealed P3 receipt.

    Application-level proof that a root run admitted a child, joined its
    result, and respected the depth / concurrency / budget / cancellation
    limits. If `refusal_reason` is set, the receipt records the refusal
    code but no child ran; `child_run_id` / `child_generation` /
    `child_result_sha256` are `None` and `depth_reached == 1`.
    """

    root_run_id: str
    root_generation: int
    child_run_id: str | None
    child_generation: int | None
    child_result_sha256: str | None
    joined_result_sha256: str
    depth_reached: int
    refusal_reason: str | None
    receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.root_run_id) is not str or not self.root_run_id:
            raise P3ReceiptError()
        if (
            type(self.root_generation) is not int
            or self.root_generation < 1
        ):
            raise P3ReceiptError()
        if self.child_run_id is not None and (
            type(self.child_run_id) is not str or not self.child_run_id
        ):
            raise P3ReceiptError()
        if self.child_generation is not None and (
            type(self.child_generation) is not int
            or self.child_generation != self.root_generation + 1
        ):
            raise P3ReceiptError()
        if self.child_result_sha256 is not None and (
            type(self.child_result_sha256) is not str
            or not self.child_result_sha256
        ):
            raise P3ReceiptError()
        if (
            type(self.joined_result_sha256) is not str
            or not self.joined_result_sha256
        ):
            raise P3ReceiptError()
        if (
            type(self.depth_reached) is not int
            or self.depth_reached not in (1, 2)
        ):
            raise P3ReceiptError()
        if self.refusal_reason is not None and (
            type(self.refusal_reason) is not str
            or not self.refusal_reason
        ):
            raise P3ReceiptError()
        if (
            type(self.receipt_sha256) is not str
            or not self.receipt_sha256
        ):
            raise P3ReceiptError()
        # Cross-field consistency: if a child ran, all child fields agree
        # and refusal_reason is None. If no child ran, all child fields are
        # None and depth=1; refusal_reason may be set (refusal) or None
        # (root ran alone successfully).
        has_child = (
            self.child_run_id is not None
            or self.child_generation is not None
            or self.child_result_sha256 is not None
        )
        if has_child:
            if (
                self.child_run_id is None
                or self.child_generation is None
                or self.child_result_sha256 is None
                or self.depth_reached != 2
                or self.refusal_reason is not None
            ):
                raise P3ReceiptError()
        else:
            if self.depth_reached != 1:
                raise P3ReceiptError()

    def sha256(self) -> str:
        return _digest(asdict(self))

    @staticmethod
    def media_type() -> str:
        return _P3_RECEIPT_MEDIA_TYPE


def seal(
    *,
    root_run_id: str,
    root_generation: int,
    child_run_id: str | None,
    child_generation: int | None,
    child_result_sha256: str | None,
    joined_result_sha256: str,
    depth_reached: int,
    refusal_reason: str | None,
) -> P3NativeReceipt:
    """Compute `receipt_sha256` as canonical-JSON SHA-256 of all other
    fields, then return the frozen receipt. Mirrors P4's seal() exactly.
    """

    digest_payload = {
        "child_generation": child_generation,
        "child_result_sha256": child_result_sha256,
        "child_run_id": child_run_id,
        "depth_reached": depth_reached,
        "joined_result_sha256": joined_result_sha256,
        "refusal_reason": refusal_reason,
        "root_generation": root_generation,
        "root_run_id": root_run_id,
    }
    return P3NativeReceipt(
        root_run_id=root_run_id,
        root_generation=root_generation,
        child_run_id=child_run_id,
        child_generation=child_generation,
        child_result_sha256=child_result_sha256,
        joined_result_sha256=joined_result_sha256,
        depth_reached=depth_reached,
        refusal_reason=refusal_reason,
        receipt_sha256=_digest(digest_payload),
    )


def build(**fields_kwargs: object) -> P3NativeReceipt:
    """Test-only constructor.

    Does NOT recompute `receipt_sha256` — caller supplies it directly. Used
    by tests to construct receipts with known digests for comparison. P4
    has the same pattern.
    """

    allowed = {f.name for f in fields(P3NativeReceipt)}
    unknown = set(fields_kwargs) - allowed
    if unknown:
        raise P3ReceiptError()
    if "receipt_sha256" not in fields_kwargs:
        raise P3ReceiptError()
    return P3NativeReceipt(**fields_kwargs)  # type: ignore[arg-type]


__all__ = (
    "P3NativeReceipt",
    "P3ReceiptError",
    "build",
    "seal",
)