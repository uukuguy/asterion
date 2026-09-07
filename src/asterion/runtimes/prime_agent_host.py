"""Public-safe host boundary for Prime's one fixed verification action."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol, runtime_checkable

from asterion.runtime.host import CancellationSignal


_PRESET = "fixed-small-verification"
_SCOPES = frozenset(
    (
        "p1-b-development",
        "p2-development",
        "p3-development",
        "p4-development",
        "p5-development",
        "p6-development",
        "p7-development",
    )
)
_PROMOTION = "unpromoted"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class PrimeSmallVerificationContractError(ValueError):
    """Raised when a public Prime verification value is malformed."""


class PrimeSmallVerificationCancelled(RuntimeError):
    """Public-safe result of cancellation requested through the host signal."""

    def __init__(self) -> None:
        super().__init__("Prime verification was cancelled")


class PrimePresetExecutionContractError(ValueError):
    """Raised when a generic Prime preset execution value is malformed."""


class PrimePresetExecutionCancelled(RuntimeError):
    """Public-safe result of cancellation requested through the host signal."""

    def __init__(self) -> None:
        super().__init__("Prime preset execution was cancelled")


@dataclass(frozen=True)
class PrimePresetExecutionRequest:
    run_id: str
    preset: str

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or _IDENTIFIER.fullmatch(self.preset) is None
        ):
            raise PrimePresetExecutionContractError("Prime preset request is invalid")


@dataclass(frozen=True)
class PrimePresetExecutionResult:
    run_id: str
    receipt_sha256: str
    scope: str
    promotion: str

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or _SHA256.fullmatch(self.receipt_sha256) is None
            or _IDENTIFIER.fullmatch(self.scope) is None
            or self.promotion != _PROMOTION
        ):
            raise PrimePresetExecutionContractError("Prime preset result is invalid")


@runtime_checkable
class PrimePresetExecutionService(Protocol):
    async def execute(
        self,
        request: PrimePresetExecutionRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimePresetExecutionResult: ...


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
    scope: str = "p1-b-development"
    promotion: str = _PROMOTION

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or type(self.trace_sha256) is not str
            or _SHA256.fullmatch(self.trace_sha256) is None
            or self.scope not in _SCOPES
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


@runtime_checkable
class PrimeP7DevelopmentHostService(Protocol):
    """Narrow host seam for P7's fixed development verification."""

    async def verify(
        self,
        request: PrimeSmallVerificationRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimeSmallVerificationResult: ...


__all__ = (
    "PrimePresetExecutionContractError",
    "PrimePresetExecutionCancelled",
    "PrimePresetExecutionRequest",
    "PrimePresetExecutionResult",
    "PrimePresetExecutionService",
    "PrimeSmallVerificationContractError",
    "PrimeSmallVerificationCancelled",
    "PrimeSmallVerificationRequest",
    "PrimeSmallVerificationResult",
    "PrimeSmallVerificationService",
    "PrimeP7DevelopmentHostService",
)
