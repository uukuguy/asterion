"""Public-safe action execution result contracts."""

from __future__ import annotations

from dataclasses import dataclass

from asterion.control.authority import BudgetUsage
from asterion.control.protocol import IDENTIFIER, MEDIA_TYPE, OPAQUE_ID
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


class ActionExecutionError(ValueError):
    """Raised when an action executor result violates the closed contract."""


@dataclass(frozen=True, repr=False)
class ActionExecutionReceipt:
    """Safe, immutable proof of one completed action execution."""

    action_id: str
    receipt_ref: str
    usage: BudgetUsage
    artifact_ids: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action_id, str)
            or OPAQUE_ID.fullmatch(self.action_id) is None
            or not isinstance(self.receipt_ref, str)
            or OPAQUE_ID.fullmatch(self.receipt_ref) is None
            or not isinstance(self.usage, BudgetUsage)
            or type(self.artifact_ids) is not tuple
            or type(self.media_types) is not tuple
            or not is_sorted_unique_scalar_strings(list(self.artifact_ids))
            or not is_sorted_unique_scalar_strings(list(self.media_types))
            or any(OPAQUE_ID.fullmatch(value) is None for value in self.artifact_ids)
            or any(MEDIA_TYPE.fullmatch(value) is None for value in self.media_types)
        ):
            raise ActionExecutionError("action execution receipt is invalid")

    def __repr__(self) -> str:
        return (
            "ActionExecutionReceipt("
            f"usage={self.usage!r}, artifact_count={len(self.artifact_ids)}, "
            f"media_type_count={len(self.media_types)})"
        )


@dataclass(frozen=True, repr=False)
class ActionExecutionFailure(Exception):
    """Controlled executor exception with public-safe terminal semantics."""

    status: str
    reason_code: str
    receipt_ref: str | None

    def __post_init__(self) -> None:
        valid_receipt = self.receipt_ref is None or (
            isinstance(self.receipt_ref, str)
            and OPAQUE_ID.fullmatch(self.receipt_ref) is not None
        )
        if (
            self.status not in {"failed", "cancelled", "uncertain"}
            or not isinstance(self.reason_code, str)
            or IDENTIFIER.fullmatch(self.reason_code) is None
            or not valid_receipt
            or (self.status == "failed" and self.receipt_ref is None)
            or (self.status == "uncertain" and self.receipt_ref is not None)
        ):
            raise ActionExecutionError("action execution failure is invalid")
        object.__setattr__(self, "args", ("controlled action execution failure",))

    def __repr__(self) -> str:
        return f"ActionExecutionFailure(status={self.status!r})"

    def __str__(self) -> str:
        return "controlled action execution failure"
