"""Typed host-service boundary for restricted worker leases."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
import re
from typing import Literal, Protocol

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
    workload_digest: str
    max_runtime_seconds: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        _validate_identifier(self.role_id)
        _validate_digest(self.image_digest)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_digest(self.workload_digest)
        _validate_positive_integer(self.max_runtime_seconds)
        _validate_positive_integer(self.max_output_bytes)


@dataclass(frozen=True)
class RestrictedWorkerLease:
    worker_id: str
    role_id: str
    run_id: str
    challenge_digest: str
    workload_digest: str

    def __post_init__(self) -> None:
        _validate_identifier(self.worker_id)
        _validate_identifier(self.role_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_digest(self.workload_digest)


@dataclass(frozen=True)
class RestrictedWorkerAttestation:
    worker_id: str
    role_id: str
    run_id: str
    challenge_digest: str
    workload_digest: str
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
        _validate_identifier(self.role_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_digest(self.workload_digest)
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
class RestrictedWorkerExecutionReceipt:
    """Body-free terminal result derived by the injected worker service."""

    worker_id: str
    role_id: str
    run_id: str
    challenge_digest: str
    workload_digest: str
    result_digest: str
    terminal: Literal["completed"] = "completed"

    def __post_init__(self) -> None:
        _validate_identifier(self.worker_id)
        _validate_identifier(self.role_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_digest(self.workload_digest)
        _validate_digest(self.result_digest)
        if self.terminal != "completed":
            raise RestrictedWorkerError("restricted worker value is invalid")


@dataclass(frozen=True)
class RestrictedWorkerCleanupReceipt:
    worker_id: str
    role_id: str
    run_id: str
    challenge_digest: str
    workload_digest: str
    destroyed: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.worker_id)
        _validate_identifier(self.role_id)
        _validate_identifier(self.run_id)
        _validate_digest(self.challenge_digest)
        _validate_digest(self.workload_digest)
        if type(self.destroyed) is not bool:
            raise RestrictedWorkerError("restricted worker value is invalid")


def verify_restricted_worker_receipts(
    request: RestrictedWorkerRequest,
    lease: RestrictedWorkerLease,
    attestation: RestrictedWorkerAttestation,
    execution: RestrictedWorkerExecutionReceipt,
    cleanup: RestrictedWorkerCleanupReceipt,
) -> None:
    """Fail closed unless receipts bind one fully destroyed worker lifecycle."""
    if (
        type(request) is not RestrictedWorkerRequest
        or type(lease) is not RestrictedWorkerLease
        or type(attestation) is not RestrictedWorkerAttestation
        or type(execution) is not RestrictedWorkerExecutionReceipt
        or type(cleanup) is not RestrictedWorkerCleanupReceipt
    ):
        raise RestrictedWorkerError("restricted worker value is invalid")
    if (
        request.run_id != lease.run_id
        or request.role_id != lease.role_id
        or request.challenge_digest != lease.challenge_digest
        or request.workload_digest != lease.workload_digest
        or lease.worker_id != attestation.worker_id
        or lease.role_id != attestation.role_id
        or lease.run_id != attestation.run_id
        or lease.challenge_digest != attestation.challenge_digest
        or lease.workload_digest != attestation.workload_digest
        or request.image_digest != attestation.image_digest
        or lease.worker_id != execution.worker_id
        or lease.role_id != execution.role_id
        or lease.run_id != execution.run_id
        or lease.challenge_digest != execution.challenge_digest
        or lease.workload_digest != execution.workload_digest
        or lease.worker_id != cleanup.worker_id
        or lease.role_id != cleanup.role_id
        or lease.run_id != cleanup.run_id
        or lease.challenge_digest != cleanup.challenge_digest
        or lease.workload_digest != cleanup.workload_digest
    ):
        raise RestrictedWorkerError("restricted worker value is invalid")
    _validate_true(cleanup.destroyed)


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

    async def execution_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerExecutionReceipt: ...

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt: ...
