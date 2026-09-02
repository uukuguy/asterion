"""Typed host-only boundary for bounded model-session leases."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class BoundedModelSessionError(ValueError):
    """Raised when a bounded model-session value is invalid."""


def _validate_identifier(value: object) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise BoundedModelSessionError("bounded model session value is invalid")


def _validate_positive_integer(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise BoundedModelSessionError("bounded model session value is invalid")


@dataclass(frozen=True)
class BoundedModelSessionRequest:
    """Public finite limits for one host-authorized session."""

    run_id: str
    max_requests: int
    max_input_bytes: int
    max_output_bytes: int
    deadline_seconds: int

    def __post_init__(self) -> None:
        _validate_identifier(self.run_id)
        _validate_positive_integer(self.max_requests)
        _validate_positive_integer(self.max_input_bytes)
        _validate_positive_integer(self.max_output_bytes)
        _validate_positive_integer(self.deadline_seconds)


@dataclass(frozen=True, repr=False)
class BoundedModelSessionLease:
    """Opaque host-issued identity for one bounded session."""

    session_id: str
    run_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.session_id)
        _validate_identifier(self.run_id)

    def __repr__(self) -> str:
        return "BoundedModelSessionLease(<redacted>)"


class BoundedModelSessionService(Protocol):
    """Host lifecycle for issuing and revoking bounded session leases."""

    def open(self, request: BoundedModelSessionRequest) -> BoundedModelSessionLease: ...

    def revoke(self, lease: BoundedModelSessionLease) -> None: ...
