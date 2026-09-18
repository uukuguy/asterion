"""Sealed P6 application receipt for native prime continual-improvement.

Mirrors ``src/asterion/applications/prime/p5/receipt.py`` exactly: a
frozen dataclass + canonical-form SHA-256 + ``seal()`` factory. The
load-bearing differences from P5 are:

* Closed 2-element ``terminal_outcome`` enum
  (``preserved`` | ``rolled-back``). The oracle's internal 3-element
  verdict enum (``preserved`` | ``rolled-back`` | ``global-rejected``)
  NEVER surfaces on the receipt — ``global-rejected`` folds into
  ``terminal_outcome="rolled-back"`` +
  ``global_activation_approved=False`` so the public enum stays at 2
  (spec L274–L290).
* ``global_activation_approved`` boolean field distinguishes
  project-scope (``False``) from global-scope-with-operator-authorization
  (``True``). The closed 2-element ``terminal_outcome`` enum is
  invariant — ``global-rejected`` is the oracle's internal verdict,
  never the public surface (spec L266–L267, L376–L380).
* ``rollback_invocation_count`` (0 if preserved, 1 if rolled-back —
  one inverse revision per spec L52).
* Diagnostic ``failure_digest`` field (10th field, beyond the 9-field
  spec shape at L257–L269). When the wrapper's Task-3
  ``_error_digest(exc)`` walks ``__cause__`` / ``__context__`` (max 4
  hops) and produces a 64-hex SHA-256 fingerprint of the exception
  chain (spec L437–L438: no prompt bodies, no model prose, no source
  locations), the wrapper threads that digest through here. The
  diagnostic digest is a single 64-hex SHA-256 or ``None``; it does
  NOT replace any of the 9 spec fields and does NOT extend the public
  ``terminal_outcome`` enum (spec L283–L292).

Public redaction (spec L293–L295): the public surface MUST NOT include
prompts, model prose, generated code, worker output, credentials,
provider bodies, private paths, source locations, raw external logs,
the per-step holdout verdict stream, or the oracle's internal
``global-rejected`` verdict. Only the fields named in
``P6NativeReceipt`` plus ``status`` and ``private_root_redacted=True``
are public.

``seal()`` computes ``receipt_sha256`` as the canonical-JSON SHA-256 of
the other fields (everything except ``receipt_sha256`` itself). Two
receipts that differ ONLY in their pre-existing ``receipt_sha256``
field produce identical digests after re-sealing (the digest is over
the OTHER fields, never over itself).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
import json
from typing import Literal


_P6_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p6-native-receipt+json"
)


TerminalOutcome = Literal["preserved", "rolled-back"]


_TERMINAL_OUTCOMES: frozenset[str] = frozenset(
    {"preserved", "rolled-back"}
)


class P6ReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("P6 receipt rejected")


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


# 9-field spec shape at L257–L269. The 10th field ``failure_digest``
# is added below as the diagnostic-digest carrier committed to by
# Task 3's ``_error_digest(exc)`` contract (see module docstring).
@dataclass(frozen=True, slots=True)
class P6NativeReceipt:
    """Sealed P6 receipt.

    Application-level proof that a continual-improvement run terminated
    exactly once with one of the closed :data:`TerminalOutcome` values
    (``preserved`` | ``rolled-back``) — never ``"still-running"`` and
    never the oracle's private 3-element verdict. The public enum is
    closed at 2; cancellation, candidate-admission errors,
    holdout-evaluation errors, promotion-action errors, and the
    oracle's ``global-rejected`` boundary verdict all fold into
    ``terminal_outcome="rolled-back"`` (spec L283–L292).

    ``receipt_sha256`` is the canonical-JSON SHA-256 of every OTHER
    field. ``failure_digest`` (10th field, beyond the 9-field spec
    shape at L257–L269) carries the wrapper's ``_error_digest(exc)``
    output when an error path fires; ``None`` on the success path.
    """

    root_run_id: str
    baseline_snapshot_digest: str
    candidate_revision_digest: str
    task_a_evidence_digest: str
    task_b_result_digest: str
    terminal_outcome: TerminalOutcome
    global_activation_approved: bool
    rollback_invocation_count: int
    receipt_sha256: str
    failure_digest: str | None

    def __post_init__(self) -> None:
        if type(self.root_run_id) is not str or not self.root_run_id:
            raise P6ReceiptError()
        if (
            type(self.baseline_snapshot_digest) is not str
            or not self.baseline_snapshot_digest
        ):
            raise P6ReceiptError()
        if (
            type(self.candidate_revision_digest) is not str
            or not self.candidate_revision_digest
        ):
            raise P6ReceiptError()
        if (
            type(self.task_a_evidence_digest) is not str
            or not self.task_a_evidence_digest
        ):
            raise P6ReceiptError()
        if (
            type(self.task_b_result_digest) is not str
            or not self.task_b_result_digest
        ):
            raise P6ReceiptError()
        if self.terminal_outcome not in _TERMINAL_OUTCOMES:
            raise P6ReceiptError()
        if type(self.global_activation_approved) is not bool:
            raise P6ReceiptError()
        if (
            type(self.rollback_invocation_count) is not int
            or self.rollback_invocation_count < 0
            or self.rollback_invocation_count > 1
        ):
            raise P6ReceiptError()
        if (
            type(self.receipt_sha256) is not str
            or not self.receipt_sha256
        ):
            raise P6ReceiptError()
        if self.failure_digest is not None and (
            type(self.failure_digest) is not str
            or not self.failure_digest
        ):
            raise P6ReceiptError()

    def sha256(self) -> str:
        return _digest(
            {
                "baseline_snapshot_digest": self.baseline_snapshot_digest,
                "candidate_revision_digest": self.candidate_revision_digest,
                "failure_digest": self.failure_digest,
                "global_activation_approved": self.global_activation_approved,
                "receipt_sha256": self.receipt_sha256,
                "rollback_invocation_count": self.rollback_invocation_count,
                "root_run_id": self.root_run_id,
                "task_a_evidence_digest": self.task_a_evidence_digest,
                "task_b_result_digest": self.task_b_result_digest,
                "terminal_outcome": self.terminal_outcome,
            }
        )

    @staticmethod
    def media_type() -> str:
        return _P6_RECEIPT_MEDIA_TYPE


def media_type() -> str:
    """Return the closed media type string for P6 receipts:

    ``application/vnd.asterion.prime.p6-native-receipt+json``.

    Mirror of P5's module-level helper.
    """

    return _P6_RECEIPT_MEDIA_TYPE


def seal_p6_native_receipt(
    receipt: P6NativeReceipt,
) -> P6NativeReceipt:
    """Compute ``receipt_sha256`` as canonical-JSON SHA-256 of the
    9 OTHER fields (everything except ``receipt_sha256`` itself),
    then return a new :class:`P6NativeReceipt` with the computed
    digest set. ``failure_digest`` (10th field) IS included in the
    digest — the diagnostic digest is part of the public surface
    when present.

    The receipt's ``receipt_sha256`` field is replaced; all other
    fields are preserved. Two receipts that differ ONLY in their
    pre-existing ``receipt_sha256`` (with all 9 other fields plus
    ``failure_digest`` identical) produce the same digest after
    re-sealing.

    Raises :class:`P6ReceiptError` on invalid input — the public
    2-element ``terminal_outcome`` enum is closed; the oracle's
    internal ``global-rejected`` verdict MUST NOT appear on the
    receipt (defense in depth alongside :meth:`__post_init__`).
    """

    if receipt.terminal_outcome not in _TERMINAL_OUTCOMES:
        raise P6ReceiptError()
    digest_payload = {
        "baseline_snapshot_digest": receipt.baseline_snapshot_digest,
        "candidate_revision_digest": receipt.candidate_revision_digest,
        "failure_digest": receipt.failure_digest,
        "global_activation_approved": receipt.global_activation_approved,
        "rollback_invocation_count": receipt.rollback_invocation_count,
        "root_run_id": receipt.root_run_id,
        "task_a_evidence_digest": receipt.task_a_evidence_digest,
        "task_b_result_digest": receipt.task_b_result_digest,
        "terminal_outcome": receipt.terminal_outcome,
    }
    return P6NativeReceipt(
        root_run_id=receipt.root_run_id,
        baseline_snapshot_digest=receipt.baseline_snapshot_digest,
        candidate_revision_digest=receipt.candidate_revision_digest,
        task_a_evidence_digest=receipt.task_a_evidence_digest,
        task_b_result_digest=receipt.task_b_result_digest,
        terminal_outcome=receipt.terminal_outcome,
        global_activation_approved=receipt.global_activation_approved,
        rollback_invocation_count=receipt.rollback_invocation_count,
        receipt_sha256=_digest(digest_payload),
        failure_digest=receipt.failure_digest,
    )


def build(**fields_kwargs: object) -> P6NativeReceipt:
    """Test-only constructor.

    Does NOT recompute ``receipt_sha256`` — caller supplies it directly.
    Mirrors P5's :func:`build` test-only constructor shape.

    Raises :class:`P6ReceiptError` on unknown field names or when
    ``receipt_sha256`` is missing.
    """

    allowed = {f.name for f in fields(P6NativeReceipt)}
    unknown = set(fields_kwargs) - allowed
    if unknown:
        raise P6ReceiptError()
    if "receipt_sha256" not in fields_kwargs:
        raise P6ReceiptError()
    return P6NativeReceipt(**fields_kwargs)  # type: ignore[arg-type]


__all__ = (
    "P6NativeReceipt",
    "P6ReceiptError",
    "TerminalOutcome",
    "build",
    "media_type",
    "seal_p6_native_receipt",
)
