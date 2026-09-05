"""Public-safe host boundary for Prime's one fixed verification action."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol, runtime_checkable

from asterion.runtime.host import CancellationSignal


_PRESET = "fixed-small-verification"
_SCOPE = "p1-b-development"
_PROMOTION = "unpromoted"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PrimeSmallVerificationContractError(ValueError):
    """Raised when a public Prime verification value is malformed."""


class PrimeSmallVerificationCancelled(RuntimeError):
    """Public-safe result of cancellation requested through the host signal."""

    def __init__(self) -> None:
        super().__init__("Prime verification was cancelled")


@dataclass(frozen=True)
class PrimeSmallVerificationRequest:
    run_id: str
    preset: str = _PRESET

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or not self.run_id or self.preset != _PRESET:
            raise PrimeSmallVerificationContractError("Prime verification request is invalid")


@dataclass(frozen=True)
class PrimeSmallVerificationResult:
    run_id: str
    trace_sha256: str
    scope: str = _SCOPE
    promotion: str = _PROMOTION

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or type(self.trace_sha256) is not str
            or _SHA256.fullmatch(self.trace_sha256) is None
            or self.scope != _SCOPE
            or self.promotion != _PROMOTION
        ):
            raise PrimeSmallVerificationContractError("Prime verification result is invalid")


@runtime_checkable
class PrimeSmallVerificationService(Protocol):
    async def verify(
        self,
        request: PrimeSmallVerificationRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimeSmallVerificationResult: ...


__all__ = (
    "PrimeSmallVerificationContractError",
    "PrimeSmallVerificationCancelled",
    "PrimeSmallVerificationRequest",
    "PrimeSmallVerificationResult",
    "PrimeSmallVerificationService",
)
