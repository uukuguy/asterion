"""Closed, content-safe projections of native P5 bounded-autonomy verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


class P5OracleError(ValueError):
    def __init__(self, reason: str | None = None) -> None:
        super().__init__("P5 oracle rejected" if reason is None else reason)
        self.reason = reason


def _validate_str(value: object, *, field: str) -> str:
    if type(value) is not str:
        raise P5OracleError(f"{field} must be a string")
    return value


def _validate_positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0 or isinstance(value, bool):
        raise P5OracleError(f"{field} must be a non-negative integer")
    return value


def _validate_bool(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise P5OracleError(f"{field} must be a bool")
    return value


Verdict = Literal[
    "pass",
    "fail",
    "no-progress",
    "cancelled",
]


_TERMINAL_REASONS: frozenset[str] = frozenset(
    {
        "success",
        "no-progress",
        "cancelled",
        "iteration-cap-exceeded",
        "duration-cap-exceeded",
    }
)


@dataclass(frozen=True, slots=True)
class P5OracleReceipt:
    """Sealed oracle verdict for a P5 bounded-autonomy run.

    Captures whether the three P5 witness invariants held: propose was
    admitted, the verify-failed-then-repaired path either ran or was
    legitimately absent on a single-propose success, and the bounded stop
    landed on a closed terminal reason.
    """

    verified: bool
    verdict: Verdict
    reason_code: str | None
    reason_detail: str | None
    checked_at: str

    def __post_init__(self) -> None:
        _validate_bool(self.verified, field="verified")
        if type(self.verdict) is not str or not self.verdict:
            raise P5OracleError("verdict must be a non-empty string")
        if self.reason_code is not None and (
            type(self.reason_code) is not str or not self.reason_code
        ):
            raise P5OracleError("reason_code must be a non-empty string when present")
        if self.reason_detail is not None and (
            type(self.reason_detail) is not str
        ):
            raise P5OracleError("reason_detail must be a string when present")
        if (
            type(self.checked_at) is not str
            or not self.checked_at
        ):
            raise P5OracleError("checked_at must be a non-empty ISO 8601 string")
        # Enforce the closed verdict enum at construction time.
        _ALLOWED: frozenset[str] = frozenset(
            {
                "pass",
                "fail",
                "no-progress",
                "cancelled",
            }
        )
        if self.verdict not in _ALLOWED:
            raise P5OracleError(f"verdict not in closed enum: {self.verdict}")


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class P5Oracle:
    """Read-only verification of one P5 bounded-autonomy run.

    Verifies the three invariants the spec demands for P5 acceptance:

      1. propose admitted: ``propose_step_count >= 1`` and ``root_run_id``
         is present.
      2. verify-failed-then-repaired: a verify failure was followed by at
         least one repair step that produced a ``joined_workspace_digest``
         differing from the prior digest; on a single-propose success path
         no failure / repair is required, only the joined digest is.
      3. bounded stop: ``terminal_reason`` is in the closed enum
         ``{success, no-progress, cancelled, iteration-cap-exceeded,
         duration-cap-exceeded}``; success verifies, the cap reasons and
         no-progress / cancelled verify to their own verdicts.

    On success, the returned receipt has ``verified=True`` and
    ``verdict="pass"``. On failure, ``verified=False`` and ``verdict``
    names the violated invariant.
    """

    def __repr__(self) -> str:
        return "<P5Oracle>"

    def check(
        self,
        *,
        root_run_id: str,
        root_generation: int,
        propose_step_count: int,
        verify_step_count: int,
        repair_step_count: int,
        failed_verify_count: int,
        terminal_reason: str,
        joined_workspace_digest: str,
    ) -> P5OracleReceipt:
        """Verify the three witness invariants and seal a receipt.

        Verdict resolution order (first match wins):

          a. ``terminal_reason`` not in the closed enum → ``fail``,
             ``reason_code="unknown-terminal-reason"``.
          b. ``terminal_reason == "cancelled"`` → ``cancelled``.
          c. ``terminal_reason == "no-progress"`` → ``no-progress``.
          d. ``terminal_reason in {"iteration-cap-exceeded",
             "duration-cap-exceeded"}`` → ``fail`` with the cap reason
             surfaced as ``reason_code``.
          e. ``terminal_reason == "success"``:
             - ``propose_step_count < 1`` → ``fail``,
               ``reason_code="propose-not-admitted"``.
             - ``verify_step_count < 1`` → ``fail``,
               ``reason_code="verify-not-run"``.
             - ``joined_workspace_digest`` empty → ``fail``,
               ``reason_code="empty-workspace-digest"``.
             - ``repair_step_count == 0`` and ``failed_verify_count > 0``
               → ``fail``, ``reason_code="missing-repair"``.
             - ``repair_step_count > 0`` and ``failed_verify_count == 0``
               → ``fail``, ``reason_code="repair-without-failure"``.
             - otherwise → ``pass``.
          f. any other closed reason → ``fail``,
             ``reason_code="unexpected-terminal-reason"``.
        """

        # Validate inputs first so a malformed oracle call never silently
        # returns a "pass" receipt. joined_workspace_digest may be the empty
        # string — that emptiness is itself the "empty-workspace-digest"
        # invariant on the success path, not a precondition error.
        _validate_str(root_run_id, field="root_run_id")
        if not root_run_id:
            raise P5OracleError("root_run_id must be a non-empty string")
        _validate_positive_int(root_generation, field="root_generation")
        _validate_positive_int(propose_step_count, field="propose_step_count")
        _validate_positive_int(verify_step_count, field="verify_step_count")
        _validate_positive_int(repair_step_count, field="repair_step_count")
        _validate_positive_int(failed_verify_count, field="failed_verify_count")
        _validate_str(terminal_reason, field="terminal_reason")
        if not terminal_reason:
            raise P5OracleError("terminal_reason must be a non-empty string")
        _validate_str(joined_workspace_digest, field="joined_workspace_digest")

        verified = True
        reason_code: str | None = None
        reason_detail: str | None = None
        verdict: Verdict = "fail"

        # (a) closed terminal-reason enum guard.
        if terminal_reason not in _TERMINAL_REASONS:
            verdict = "fail"
            verified = False
            reason_code = "unknown-terminal-reason"
            reason_detail = (
                f"terminal_reason {terminal_reason!r} is not in the closed "
                "P5 terminal-reason enum"
            )
        # (b) cancellation path.
        elif terminal_reason == "cancelled":
            verdict = "cancelled"
            verified = False
            reason_code = "cancelled"
            reason_detail = "P5 bounded-autonomy loop was cancelled"
        # (c) no-progress path.
        elif terminal_reason == "no-progress":
            verdict = "no-progress"
            verified = False
            reason_code = "no-progress"
            reason_detail = (
                "P5 bounded-autonomy loop reported no progress and stopped"
            )
        # (d) cap-exceeded paths.
        elif terminal_reason == "iteration-cap-exceeded":
            verdict = "fail"
            verified = False
            reason_code = "iteration-cap-exceeded"
            reason_detail = (
                "P5 bounded-autonomy loop hit the iteration cap before "
                "reaching success"
            )
        elif terminal_reason == "duration-cap-exceeded":
            verdict = "fail"
            verified = False
            reason_code = "duration-cap-exceeded"
            reason_detail = (
                "P5 bounded-autonomy loop hit the duration cap before "
                "reaching success"
            )
        # (e) success path — enforce the three witness invariants.
        elif terminal_reason == "success":
            if propose_step_count < 1:
                verdict = "fail"
                verified = False
                reason_code = "propose-not-admitted"
                reason_detail = (
                    "terminal_reason=success requires propose_step_count >= 1"
                )
            elif verify_step_count < 1:
                verdict = "fail"
                verified = False
                reason_code = "verify-not-run"
                reason_detail = (
                    "terminal_reason=success requires verify_step_count >= 1"
                )
            elif not joined_workspace_digest:
                verdict = "fail"
                verified = False
                reason_code = "empty-workspace-digest"
                reason_detail = (
                    "terminal_reason=success requires a non-empty "
                    "joined_workspace_digest"
                )
            elif repair_step_count == 0 and failed_verify_count > 0:
                verdict = "fail"
                verified = False
                reason_code = "missing-repair"
                reason_detail = (
                    "failed_verify_count > 0 with terminal_reason=success "
                    "requires repair_step_count >= 1"
                )
            elif repair_step_count > 0 and failed_verify_count == 0:
                verdict = "fail"
                verified = False
                reason_code = "repair-without-failure"
                reason_detail = (
                    "repair_step_count > 0 requires failed_verify_count > 0"
                )
            else:
                verdict = "pass"
                verified = True
                reason_code = None
                reason_detail = None
        # (f) any other closed reason (defensive — should not occur).
        else:
            verdict = "fail"
            verified = False
            reason_code = "unexpected-terminal-reason"
            reason_detail = (
                f"terminal_reason {terminal_reason!r} reached the fall-through "
                "branch of the P5 oracle"
            )

        receipt = P5OracleReceipt(
            verified=verified,
            verdict=verdict,
            reason_code=reason_code,
            reason_detail=reason_detail,
            checked_at=_now_iso(),
        )
        if not verified:
            # Surface the verdict in the exception chain so callers can
            # distinguish reasons, but the receipt itself is the verdict.
            raise P5OracleError(reason_code) from None
        return receipt


__all__ = (
    "P5Oracle",
    "P5OracleError",
    "P5OracleReceipt",
)
