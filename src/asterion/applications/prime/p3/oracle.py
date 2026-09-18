"""Closed, content-safe projections of native P3 child-admission verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


class P3OracleError(ValueError):
    def __init__(self, reason: str | None = None) -> None:
        super().__init__("P3 oracle rejected" if reason is None else reason)
        self.reason = reason


def _validate_str(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        raise P3OracleError(f"{field} must be a non-empty string")
    return value


def _validate_optional_str(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value:
        raise P3OracleError(f"{field} must be a non-empty string when present")
    return value


def _validate_positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 1 or isinstance(value, bool):
        raise P3OracleError(f"{field} must be a positive integer")
    return value


def _validate_depth(value: object) -> int:
    if type(value) is not int or value not in (1, 2) or isinstance(value, bool):
        raise P3OracleError("depth_reached must be 1 or 2")
    return value


def _validate_bool(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise P3OracleError(f"{field} must be a bool")
    return value


Verdict = Literal[
    "pass",
    "child-not-joined",
    "limits-violated::depth-exceeded",
    "limits-violated::concurrency-exceeded",
    "limits-violated::budget-exceeded",
    "limits-violated::cancelled",
    "limits-violated::session-backend-rejected",
    "refused-not-replayable",
]


_LIMIT_REASONS: frozenset[str] = frozenset(
    {
        "depth-exceeded",
        "concurrency-exceeded",
        "budget-exceeded",
        "cancelled",
        "session-backend-rejected",
    }
)


@dataclass(frozen=True, slots=True)
class P3OracleReceipt:
    """Sealed oracle verdict for a P3 root run.

    Captures whether the three P3 witness invariants held: the child was
    admitted (generation +1), the child joined (result digest recorded,
    depth reached 2, no refusal), and any limits rejection mapped to the
    closed ``limits-violated::<reason>`` enum.
    """

    verified: bool
    verdict: Verdict
    reason_code: str | None
    reason_detail: str | None
    checked_at: str

    def __post_init__(self) -> None:
        _validate_bool(self.verified, field="verified")
        if type(self.verdict) is not str or not self.verdict:
            raise P3OracleError("verdict must be a non-empty string")
        if self.reason_code is not None and (
            type(self.reason_code) is not str or not self.reason_code
        ):
            raise P3OracleError("reason_code must be a non-empty string when present")
        if self.reason_detail is not None and (
            type(self.reason_detail) is not str
        ):
            raise P3OracleError("reason_detail must be a string when present")
        if (
            type(self.checked_at) is not str
            or not self.checked_at
        ):
            raise P3OracleError("checked_at must be a non-empty ISO 8601 string")
        # Enforce the closed verdict enum at construction time.
        _ALLOWED: frozenset[str] = frozenset(
            {
                "pass",
                "child-not-joined",
                "limits-violated::depth-exceeded",
                "limits-violated::concurrency-exceeded",
                "limits-violated::budget-exceeded",
                "limits-violated::cancelled",
                "limits-violated::session-backend-rejected",
                "refused-not-replayable",
            }
        )
        if self.verdict not in _ALLOWED:
            raise P3OracleError(f"verdict not in closed enum: {self.verdict}")


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class P3Oracle:
    """Read-only verification of one P3 root run's child-admission lifecycle.

    Verifies the three invariants the spec demands for P3 acceptance:

      1. child admitted: ``child_identity.generation == root_generation + 1``,
         ``child_run_id != root_run_id``
      2. child joined: ``child_result_sha256`` present, ``child_run_id``
         present, ``depth_reached == 2``, ``refusal_reason is None``
      3. limits reject: a closed ``refusal_reason`` in
         ``{depth-exceeded, concurrency-exceeded, budget-exceeded,
         cancelled, session-backend-rejected}`` maps to the matching
         ``limits-violated::<reason>`` verdict.

    On success, the returned receipt has ``verified=True`` and
    ``verdict="pass"``. On failure, ``verified=False`` and ``verdict``
    names the violated invariant.
    """

    def __repr__(self) -> str:
        return "<P3Oracle>"

    def check(
        self,
        *,
        root_run_id: str,
        root_generation: int,
        child_run_id: str | None,
        child_generation: int | None,
        child_result_sha256: str | None,
        joined_result_sha256: str,
        depth_reached: int,
        refusal_reason: str | None,
    ) -> P3OracleReceipt:
        """Verify the three witness invariants and seal a receipt.

        Verdict resolution order (first match wins):

          a. ``refusal_reason`` is in the closed limits enum → ``limits-violated::<reason>``
          b. ``refusal_reason`` is set but not in the closed enum → ``refused-not-replayable``
          c. ``refusal_reason`` is ``None`` and ``depth_reached == 2`` and any child field is missing → ``child-not-joined``
          d. ``refusal_reason`` is ``None`` and ``depth_reached == 1`` and all child fields are ``None`` → ``pass``
          e. ``refusal_reason`` is ``None`` and ``depth_reached == 2`` and all child fields are present and ``child_generation == root_generation + 1`` and ``child_run_id != root_run_id`` → ``pass``
          f. otherwise → ``refused-not-replayable``
        """

        # Validate inputs first so a malformed oracle call never silently
        # returns a "pass" receipt.
        _validate_str(root_run_id, field="root_run_id")
        _validate_positive_int(root_generation, field="root_generation")
        _validate_optional_str(child_run_id, field="child_run_id")
        _validate_optional_str(child_result_sha256, field="child_result_sha256")
        _validate_str(joined_result_sha256, field="joined_result_sha256")
        _validate_depth(depth_reached)
        if refusal_reason is not None and (
            type(refusal_reason) is not str or not refusal_reason
        ):
            raise P3OracleError("refusal_reason must be a non-empty string when present")
        if child_generation is not None:
            _validate_positive_int(child_generation, field="child_generation")

        verified = True
        reason_code: str | None = None
        reason_detail: str | None = None
        verdict: Verdict = "refused-not-replayable"

        # (a) closed limits-reason enum → verdict "limits-violated::<reason>"
        if (
            refusal_reason is not None
            and refusal_reason in _LIMIT_REASONS
        ):
            verdict = f"limits-violated::{refusal_reason}"  # type: ignore[assignment]
            verified = False
            reason_code = refusal_reason
            reason_detail = (
                "P3 root run refused before admitting a child"
            )
        # (b) refusal_reason set but not in closed enum → refused-not-replayable
        elif refusal_reason is not None:
            verdict = "refused-not-replayable"
            verified = False
            reason_code = "unknown-refusal-reason"
            reason_detail = (
                f"refusal_reason {refusal_reason!r} is not in the closed "
                "P3 limits enum"
            )
        # (c) no refusal but depth=2 with missing child field → child-not-joined
        elif depth_reached == 2 and (
            child_run_id is None
            or child_generation is None
            or child_result_sha256 is None
        ):
            verdict = "child-not-joined"
            verified = False
            reason_code = "incomplete-child-fields"
            reason_detail = (
                "depth_reached=2 requires child_run_id, child_generation, "
                "and child_result_sha256 to all be present"
            )
        # (d) root alone with depth=1 → pass
        elif (
            depth_reached == 1
            and child_run_id is None
            and child_generation is None
            and child_result_sha256 is None
        ):
            verdict = "pass"
            verified = True
            reason_code = None
            reason_detail = None
        # (e) full child admit + join with generation +1 and distinct run id → pass
        elif (
            depth_reached == 2
            and child_run_id is not None
            and child_generation is not None
            and child_result_sha256 is not None
            and child_generation == root_generation + 1
            and child_run_id != root_run_id
        ):
            verdict = "pass"
            verified = True
            reason_code = None
            reason_detail = None
        else:
            # (f) everything else — depth=2 with cross-field inconsistency
            # (e.g. child_generation != root_generation + 1, or
            # child_run_id == root_run_id), or depth out of bounds.
            verdict = "refused-not-replayable"
            verified = False
            if (
                depth_reached == 2
                and child_generation is not None
                and child_generation != root_generation + 1
            ):
                reason_code = "generation-not-monotonic"
                reason_detail = (
                    f"child_generation={child_generation} must equal "
                    f"root_generation + 1 = {root_generation + 1}"
                )
            elif (
                depth_reached == 2
                and child_run_id is not None
                and child_run_id == root_run_id
            ):
                reason_code = "child-run-id-collides-with-root"
                reason_detail = (
                    "child_run_id must differ from root_run_id"
                )
            elif depth_reached == 1 and (
                child_run_id is not None
                or child_generation is not None
                or child_result_sha256 is not None
            ):
                reason_code = "depth-one-with-child-fields"
                reason_detail = (
                    "depth_reached=1 must have all child fields None"
                )
            else:
                reason_code = "inconsistent-replay-state"
                reason_detail = (
                    "P3 root run state is not consistent with any "
                    "witness invariant"
                )

        receipt = P3OracleReceipt(
            verified=verified,
            verdict=verdict,
            reason_code=reason_code,
            reason_detail=reason_detail,
            checked_at=_now_iso(),
        )
        if not verified:
            # Surface the verdict in the exception chain so callers can
            # distinguish reasons, but the receipt itself is the verdict.
            raise P3OracleError(reason_code) from None
        return receipt


__all__ = (
    "P3Oracle",
    "P3OracleError",
    "P3OracleReceipt",
)
