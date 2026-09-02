"""Closed Docker-engine adapter for the one Prime coding-worker role.

This module deliberately contains no Docker client integration.  An operator
injects the narrow engine transport after establishing its own engine policy.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from secrets import token_hex
from time import monotonic
from types import TracebackType
from typing import Literal, Mapping, Protocol

from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


_ROLE_ID = "prime.ipython-coding"
_NON_ROOT_ID = 65534
_WORKSPACE_TMPFS_BYTES = 67108864
_LIFECYCLE_SECONDS = 30
_CLEANUP_SECONDS = 30
_SAFE_ENVIRONMENT = (
    "HOME=/workspace",
    "PATH=/usr/local/bin:/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE=1",
)
_INSPECTION_FIELDS = frozenset(
    {
        "image_id", "repo_digests", "network_mode", "ports", "readonly_rootfs",
        "privileged", "cap_add", "cap_drop", "security_opt", "user", "devices",
        "mounts", "binds", "volumes", "tmpfs", "env", "pids_limit", "memory",
        "memory_swap", "nano_cpus", "pid_namespace", "ipc_namespace", "uts_namespace",
    }
)


@dataclass(frozen=True)
class _DockerWorkerRole:
    """Code-owned policy for the sole Docker-backed Prime worker role."""

    image_digest: str
    max_runtime_seconds: int = 300
    max_output_bytes: int = 65536
    launcher_id: Literal["prime-ipython-coding"] = "prime-ipython-coding"
    user_id: int = _NON_ROOT_ID
    group_id: int = _NON_ROOT_ID
    role_id: Literal["prime.ipython-coding"] = _ROLE_ID


@dataclass(frozen=True)
class _DockerWorkerSpecification:
    """The complete, non-generic engine create input."""

    role_id: Literal["prime.ipython-coding"]
    image_digest: str
    run_id: str
    challenge_digest: str
    max_runtime_seconds: int
    max_output_bytes: int
    launcher_id: Literal["prime-ipython-coding"]
    user_id: int
    group_id: int
    container_id: str = ""


@dataclass(frozen=True, repr=False)
class _LifecycleCallControl:
    """Code-owned finite call budget; transports cannot select its limits."""

    deadline: float
    signal: CancellationSignal | None

    def cancelled(self) -> bool:
        return self.signal is not None and self.signal.cancelled

    def __repr__(self) -> str:
        return "_LifecycleCallControl(redacted)"


@dataclass(frozen=True, repr=False)
class DockerWorkerLauncherSelfCheck:
    """Typed launcher evidence; its representation never exposes raw values."""

    nonloopback_network_absent: bool
    root_read_only: bool
    workspace_only_writable: bool
    credentials_absent: bool
    effective_capabilities: int
    no_new_privileges: int
    seccomp_mode: int
    effective_user_id: int

    def __post_init__(self) -> None:
        if (
            type(self.nonloopback_network_absent) is not bool
            or type(self.root_read_only) is not bool
            or type(self.workspace_only_writable) is not bool
            or type(self.credentials_absent) is not bool
            or type(self.effective_capabilities) is not int
            or type(self.no_new_privileges) is not int
            or type(self.seccomp_mode) is not int
            or type(self.effective_user_id) is not int
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")

    def __repr__(self) -> str:
        return "DockerWorkerLauncherSelfCheck(redacted)"


class DockerEngineTransport(Protocol):
    """Operator-supplied operations over an opaque, fixed-role container."""

    async def create(
        self,
        specification: _DockerWorkerSpecification,
        *,
        control: _LifecycleCallControl,
    ) -> str: ...

    async def inspect(
        self, container_id: str, *, control: _LifecycleCallControl
    ) -> Mapping[str, object]: ...

    async def start(
        self, container_id: str, *, control: _LifecycleCallControl
    ) -> RestrictedWorkerLease: ...

    async def launcher_self_check(
        self, container_id: str, *, control: _LifecycleCallControl
    ) -> DockerWorkerLauncherSelfCheck: ...

    async def force_remove(
        self, container_id: str, *, control: _LifecycleCallControl
    ) -> None: ...

    async def assert_absent(
        self, container_id: str, *, control: _LifecycleCallControl
    ) -> None: ...


@dataclass
class _LeaseState:
    request: RestrictedWorkerRequest
    container_id: str


@dataclass(frozen=True, repr=False)
class _CleanupTombstone:
    """Minimal post-destruction identity retained until receipt issuance."""

    worker_id: str
    run_id: str
    challenge_digest: str

    def __repr__(self) -> str:
        return "_CleanupTombstone(redacted)"


class DockerRestrictedWorkerService:
    """Admits only the fixed Prime role to an injected engine transport."""

    def __init__(self, *, image_digest: str, transport: DockerEngineTransport) -> None:
        try:
            self._role = _DockerWorkerRole(image_digest=image_digest)
            # Reuse the closed shared contract to reject a tag-like image value.
            RestrictedWorkerRequest(
                _ROLE_ID, image_digest, "role-check", "sha256:" + "0" * 64, 1, 1
            )
        except RestrictedWorkerError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        self._transport = transport
        self._leases: dict[str, _LeaseState] = {}
        self._cleanup_tombstones: dict[str, _CleanupTombstone] = {}

    def request_for(
        self, request: RestrictedWorkerRequest
    ) -> _DockerWorkerSpecification:
        """Return the only engine specification this service can create."""
        if (
            type(request) is not RestrictedWorkerRequest
            or request.role_id != self._role.role_id
            or request.image_digest != self._role.image_digest
            or request.max_runtime_seconds > self._role.max_runtime_seconds
            or request.max_output_bytes > self._role.max_output_bytes
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return _DockerWorkerSpecification(
            role_id=self._role.role_id,
            image_digest=self._role.image_digest,
            run_id=request.run_id,
            challenge_digest=request.challenge_digest,
            max_runtime_seconds=request.max_runtime_seconds,
            max_output_bytes=request.max_output_bytes,
            launcher_id=self._role.launcher_id,
            user_id=self._role.user_id,
            group_id=self._role.group_id,
        )

    def open(
        self,
        request: RestrictedWorkerRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AbstractAsyncContextManager[RestrictedWorkerLease]:
        specification = self.request_for(request)
        return _DockerWorkerLeaseContext(self, request, specification, signal)

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation:
        request = self._request_for_lease(lease)
        return RestrictedWorkerAttestation(
            lease.worker_id,
            lease.run_id,
            lease.challenge_digest,
            request.image_digest,
            True, True, True, True, True, True, True,
        )

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt:
        if type(lease) is not RestrictedWorkerLease:
            raise RestrictedWorkerError("restricted worker value is invalid")
        tombstone = self._cleanup_tombstones.get(lease.worker_id)
        if (
            tombstone is None
            or tombstone.worker_id != lease.worker_id
            or tombstone.run_id != lease.run_id
            or tombstone.challenge_digest != lease.challenge_digest
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        del self._cleanup_tombstones[lease.worker_id]
        return RestrictedWorkerCleanupReceipt(
            lease.worker_id, lease.run_id, lease.challenge_digest, True
        )

    def _admit_lease(
        self, request: RestrictedWorkerRequest, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerLease:
        if (
            type(lease) is not RestrictedWorkerLease
            or lease.run_id != request.run_id
            or lease.challenge_digest != request.challenge_digest
            or lease.worker_id in self._leases
            or lease.worker_id in self._cleanup_tombstones
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._leases[lease.worker_id] = _LeaseState(request, "")
        return lease

    def _bind_container(self, lease: RestrictedWorkerLease, container_id: str) -> None:
        state = self._leases.get(lease.worker_id)
        if state is None or state.container_id or type(container_id) is not str or not container_id:
            raise RestrictedWorkerError("restricted worker value is invalid")
        state.container_id = container_id

    def _record_verified_cleanup(self, lease: RestrictedWorkerLease) -> None:
        state = self._leases.get(lease.worker_id)
        if (
            state is None
            or state.request.run_id != lease.run_id
            or state.request.challenge_digest != lease.challenge_digest
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        del self._leases[lease.worker_id]
        self._cleanup_tombstones[lease.worker_id] = _CleanupTombstone(
            lease.worker_id, lease.run_id, lease.challenge_digest
        )

    def _request_for_lease(self, lease: RestrictedWorkerLease) -> RestrictedWorkerRequest:
        if type(lease) is not RestrictedWorkerLease:
            raise RestrictedWorkerError("restricted worker value is invalid")
        state = self._leases.get(lease.worker_id)
        if state is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        request = state.request
        if (
            request.run_id != lease.run_id
            or request.challenge_digest != lease.challenge_digest
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return request

    def _validate_inspection(self, inspection: Mapping[str, object]) -> None:
        """Validate raw engine evidence without retaining or exposing it."""
        try:
            if type(inspection) is not dict or frozenset(inspection) != _INSPECTION_FIELDS:
                raise ValueError
            expected = {
                "image_id": self._role.image_digest,
                "repo_digests": (self._role.image_digest,),
                "network_mode": "none",
                "ports": (),
                "readonly_rootfs": True,
                "privileged": False,
                "cap_add": (),
                "cap_drop": ("ALL",),
                "security_opt": ("no-new-privileges", "seccomp=prime-ipython-coding"),
                "user": f"{_NON_ROOT_ID}:{_NON_ROOT_ID}",
                "devices": (), "mounts": (), "binds": (), "volumes": (),
                "env": _SAFE_ENVIRONMENT,
                "memory_swap": inspection["memory"],
                "pid_namespace": "private", "ipc_namespace": "private", "uts_namespace": "private",
            }
            if any(
                type(inspection[name]) is not type(value) or inspection[name] != value
                for name, value in expected.items()
            ):
                raise ValueError
            tmpfs = inspection["tmpfs"]
            workspace = tmpfs.get("/workspace") if type(tmpfs) is dict else None
            if (
                type(tmpfs) is not dict
                or frozenset(tmpfs) != {"/workspace"}
                or type(workspace) is not dict
                or frozenset(workspace) != {"size_bytes", "options"}
                or type(workspace["size_bytes"]) is not int
                or workspace["size_bytes"] != _WORKSPACE_TMPFS_BYTES
                or type(workspace["options"]) is not tuple
                or workspace["options"] != ("nodev", "noexec", "nosuid")
            ):
                raise ValueError
            for name in ("pids_limit", "memory", "nano_cpus"):
                if type(inspection[name]) is not int or inspection[name] <= 0:
                    raise ValueError
            if type(inspection["memory_swap"]) is not int:
                raise ValueError
        except Exception:
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    def _validate_launcher_self_check(
        self, self_check: DockerWorkerLauncherSelfCheck
    ) -> None:
        """Require the in-container launcher to corroborate engine evidence."""
        if (
            type(self_check) is not DockerWorkerLauncherSelfCheck
            or self_check.nonloopback_network_absent is not True
            or self_check.root_read_only is not True
            or self_check.workspace_only_writable is not True
            or self_check.credentials_absent is not True
            or self_check.effective_capabilities != 0
            or self_check.no_new_privileges != 1
            or self_check.seccomp_mode != 2
            or self_check.effective_user_id != _NON_ROOT_ID
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")


class _DockerWorkerLeaseContext(AbstractAsyncContextManager[RestrictedWorkerLease]):
    def __init__(
        self,
        service: DockerRestrictedWorkerService,
        request: RestrictedWorkerRequest,
        specification: _DockerWorkerSpecification,
        signal: CancellationSignal | None,
    ) -> None:
        self._service = service
        self._request = request
        self._specification = specification
        self._signal = signal
        self._container_id = "prime-" + token_hex(16)
        self._specification = replace(specification, container_id=self._container_id)
        self._control = _LifecycleCallControl(monotonic() + _LIFECYCLE_SECONDS, signal)
        self._lease: RestrictedWorkerLease | None = None

    async def __aenter__(self) -> RestrictedWorkerLease:
        try:
            container_id = await self._call_create()
            if container_id != self._container_id:
                raise RestrictedWorkerError("restricted worker value is invalid")
            inspection = await self._call_inspect(self._control)
            self._service._validate_inspection(inspection)
            lease = await self._call_start()
            inspection = await self._call_inspect(self._control)
            self._service._validate_inspection(inspection)
            self_check = await self._call_self_check()
            self._service._validate_launcher_self_check(self_check)
            self._lease = self._service._admit_lease(self._request, lease)
            self._service._bind_container(self._lease, container_id)
            return self._lease
        except BaseException as error:
            cleanup_error = await self._cleanup_after_rejection()
            if cleanup_error is not None:
                raise RestrictedWorkerError("restricted worker value is invalid") from None
            if isinstance(error, asyncio.CancelledError):
                raise
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._lease is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        control = _LifecycleCallControl(monotonic() + _CLEANUP_SECONDS, None)
        try:
            inspection = await self._call_inspect(control)
            self._service._validate_inspection(inspection)
        except BaseException as error:
            cleanup_error = await self._cleanup_container(control)
            if cleanup_error is not None:
                raise RestrictedWorkerError("restricted worker value is invalid") from None
            if isinstance(error, asyncio.CancelledError):
                raise
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        try:
            cleanup_error = await self._cleanup_container(control)
            if cleanup_error is not None:
                raise cleanup_error
            self._service._record_verified_cleanup(self._lease)
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        return None

    async def _call_create(self) -> str:
        return await self._within_deadline(
            self._service._transport.create(self._specification, control=self._control), self._control
        )

    async def _call_inspect(self, control: _LifecycleCallControl) -> Mapping[str, object]:
        return await self._within_deadline(
            self._service._transport.inspect(self._container_id, control=control), control
        )

    async def _call_start(self) -> RestrictedWorkerLease:
        return await self._within_deadline(
            self._service._transport.start(self._container_id, control=self._control), self._control
        )

    async def _call_self_check(self) -> DockerWorkerLauncherSelfCheck:
        return await self._within_deadline(
            self._service._transport.launcher_self_check(self._container_id, control=self._control), self._control
        )

    async def _within_deadline(self, awaitable: object, control: _LifecycleCallControl):
        if control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        async with asyncio.timeout_at(control.deadline):
            result = await awaitable  # type: ignore[misc]
        if control.cancelled():
            raise asyncio.CancelledError
        return result

    async def _cleanup_after_rejection(self) -> BaseException | None:
        return await self._cleanup_container(
            _LifecycleCallControl(monotonic() + _CLEANUP_SECONDS, None)
        )

    async def _cleanup_container(self, control: _LifecycleCallControl) -> BaseException | None:
        task = asyncio.create_task(self._cleanup_container_unshielded(control))
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                cancellation = error
            except BaseException as error:
                return error
        if task.cancelled():
            return asyncio.CancelledError()
        error = task.exception()
        return error if error is not None else cancellation

    async def _cleanup_container_unshielded(self, control: _LifecycleCallControl) -> None:
        await self._within_deadline(
            self._service._transport.force_remove(self._container_id, control=control), control
        )
        await self._within_deadline(
            self._service._transport.assert_absent(self._container_id, control=control), control
        )
