"""Typed host-service boundary for restricted worker leases."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
import re
from typing import Protocol

from asterion.runtime.host import CancellationSignal


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class RestrictedWorkerError(ValueError):
    """Raised when a restricted-worker value is invalid."""


def _validate_identifier(value: object) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise RestrictedWorkerError("restricted worker value is invalid")


def _validate_digest(value: object) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise RestrictedWorkerError("restricted worker value is invalid")


def _validate_positive_integer(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise RestrictedWorkerError("restricted worker value is invalid")


def _validate_true(value: object) -> None:
    if value is not True:
        raise RestrictedWorkerError("restricted worker value is invalid")


@dataclass(frozen=True)
class RestrictedWorkerRequest:
    role_id: str
    image_digest: str
    run_id: str
    challenge_digest: str
    max_runtime_seconds: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        _validate_identifier(self.role_id)
        _validate_digest(self.image_digest)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_positive_integer(self.max_runtime_seconds)
        _validate_positive_integer(self.max_output_bytes)


@dataclass(frozen=True)
class RestrictedWorkerLease:
    worker_id: str
    run_id: str
    challenge_digest: str

    def __post_init__(self) -> None:
        _validate_identifier(self.worker_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)


@dataclass(frozen=True)
class RestrictedWorkerAttestation:
    worker_id: str
    run_id: str
    challenge_digest: str
    image_digest: str
    network_isolated: bool
    root_read_only: bool
    workspace_disposable: bool
    credentials_absent: bool
    kernel_credential_absent: bool
    source_read_only: bool
    resource_limited: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.worker_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_digest(self.image_digest)
        for value in (
            self.network_isolated,
            self.root_read_only,
            self.workspace_disposable,
            self.credentials_absent,
            self.kernel_credential_absent,
            self.source_read_only,
            self.resource_limited,
        ):
            _validate_true(value)


@dataclass(frozen=True)
class RestrictedWorkerCleanupReceipt:
    worker_id: str
    run_id: str
    challenge_digest: str
    destroyed: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.worker_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        if type(self.destroyed) is not bool:
            raise RestrictedWorkerError("restricted worker value is invalid")


class RestrictedWorkerService(Protocol):
    def open(
        self,
        request: RestrictedWorkerRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AbstractAsyncContextManager[RestrictedWorkerLease]: ...

    async def attest(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerAttestation: ...

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt: ...
