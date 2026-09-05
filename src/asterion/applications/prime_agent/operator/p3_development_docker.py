"""Fixed three-worker Docker lifecycle for the P3 development route."""

from __future__ import annotations

import asyncio
import os
import re
import secrets
from dataclasses import dataclass
from time import monotonic

from .docker_cli import DockerCliEngineTransport, _CLEARED_BASE_IMAGE_ENVIRONMENT, _ENVIRONMENT, _TMPFS
from .docker_worker import _LifecycleCallControl

_ROLES = ("root", "implementation", "review")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CELL_CAP = 16 * 1024
_OUTPUT_CAP = 4 * 1024
_RESULT_CAP = 16 * 1024
_CLEANUP_SECONDS = 35.0


class PrimeP3DevelopmentDockerError(ValueError):
    """Body-free P3 Docker lifecycle failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development docker worker is unavailable")


@dataclass(frozen=True, repr=False)
class P3DevelopmentContainer:
    """Opaque daemon identity bound to exactly one P3 role."""

    role: str
    container_id: str

    def __post_init__(self) -> None:
        if self.role not in _ROLES or _CONTAINER_ID.fullmatch(self.container_id) is None:
            raise PrimeP3DevelopmentDockerError()

    def __repr__(self) -> str:
        return "P3DevelopmentContainer(redacted)"


class PrimeP3DevelopmentDockerTransport(DockerCliEngineTransport):
    """Direct Docker CLI calls with a shared workspace and root-only RLM mount."""

    async def create_workers(self, *, image_digest: str, run_id: str, workspace: str, rlm_socket_directory: str, control: _LifecycleCallControl) -> tuple[P3DevelopmentContainer, ...]:
        if _IMAGE_DIGEST.fullmatch(image_digest) is None or type(run_id) is not str or not run_id or not _absolute_directory(workspace) or not _absolute_directory(rlm_socket_directory):
            raise PrimeP3DevelopmentDockerError()
        names = tuple("prime-p3-" + role + "-" + secrets.token_hex(16) for role in _ROLES)
        fds = self._claim_seccomp_fds(len(_ROLES))
        containers: list[P3DevelopmentContainer] = []
        try:
            await self._preflight(control)  # type: ignore[attr-defined]
            for role, name, fd in zip(_ROLES, names, fds, strict=True):
                result = await self._call(self._create_argv(role=role, name=name, image_digest=image_digest, workspace=workspace, rlm_socket_directory=rlm_socket_directory, fd=fd), control, pass_fds=(fd,))  # type: ignore[attr-defined]
                containers.append(P3DevelopmentContainer(role, self._parse_daemon_id(result.stdout)))  # type: ignore[attr-defined]
            return tuple(containers)
        except asyncio.CancelledError:
            await self._cleanup_uncertain(tuple(containers), names)
            raise
        except BaseException:
            await self._cleanup_uncertain(tuple(containers), names)
            raise PrimeP3DevelopmentDockerError() from None
        finally:
            for fd in fds:
                self._close_fd(fd)  # type: ignore[attr-defined]

    async def start_workers(self, containers: tuple[P3DevelopmentContainer, ...], control: _LifecycleCallControl) -> None:
        self._exact_workers(containers)
        try:
            for container in containers:
                await self._call(self._prefix + ("container", "start", container.container_id), control)  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            await self._cleanup_uncertain(containers, ())
            raise
        except BaseException:
            await self._cleanup_uncertain(containers, ())
            raise PrimeP3DevelopmentDockerError() from None

    async def execute(self, container: P3DevelopmentContainer, cell: str, control: _LifecycleCallControl) -> None:
        if type(cell) is not str or not cell or len(cell.encode("utf-8")) > _CELL_CAP:
            raise PrimeP3DevelopmentDockerError()
        try:
            await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", "--env", "HOME=/workspace", container.container_id, "/usr/local/bin/ipython", "--no-banner", "--no-confirm-exit", "-c", cell), control, max_output_bytes=_OUTPUT_CAP)  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP3DevelopmentDockerError() from None

    async def read(self, container: P3DevelopmentContainer, name: str, control: _LifecycleCallControl) -> bytes:
        if type(name) is not str or name not in {"solution.py", "test_solution.py", "aggregate.json"}:
            raise PrimeP3DevelopmentDockerError()
        try:
            result = await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", container.container_id, "cat", "/workspace/" + name), control, max_output_bytes=_RESULT_CAP)  # type: ignore[attr-defined]
            if type(result.stdout) is not bytes or len(result.stdout) > _RESULT_CAP or result.stderr:
                raise ValueError
            return result.stdout
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP3DevelopmentDockerError() from None

    async def cleanup(self, containers: tuple[P3DevelopmentContainer, ...], control: _LifecycleCallControl) -> None:
        self._exact_workers(containers)
        try:
            for container in reversed(containers):
                result = await self._call(self._prefix + ("container", "rm", "--force", container.container_id), control)  # type: ignore[attr-defined]
                if result.stdout not in (b"", (container.container_id + "\n").encode()) or result.stderr:
                    raise ValueError
        except asyncio.CancelledError:
            await self._cleanup_uncertain(containers, ())
            raise
        except BaseException:
            await self._cleanup_uncertain(containers, ())
            raise PrimeP3DevelopmentDockerError() from None

    def _create_argv(self, *, role: str, name: str, image_digest: str, workspace: str, rlm_socket_directory: str, fd: int) -> tuple[str, ...]:
        platform = "/".join(item for item in (self._platform.os, self._platform.architecture, self._platform.variant) if item is not None)  # type: ignore[attr-defined]
        argv = self._prefix + (  # type: ignore[attr-defined]
            "create", "--name", name, "--pull=never", "--platform", platform, "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--security-opt", "seccomp=/proc/self/fd/" + str(fd), "--tmpfs", _TMPFS, "--volume", workspace + ":/workspace:rw,rprivate", "--env", _ENVIRONMENT[0], "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[0], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[1], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[2], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[3], "--pids-limit", "64", "--memory", "268435456", "--memory-swap", "268435456", "--cpus", "1", "--restart", "no", "--label", "asterion.prime.p3.role=" + role,
        )
        if role == "root":
            argv += ("--volume", rlm_socket_directory + ":/run/asterion-rlm:ro,rprivate")
        return argv + (image_digest,)

    def _claim_seccomp_fds(self, count: int) -> tuple[int, ...]:
        fd, self._seccomp_profile_fd = self._seccomp_profile_fd, None  # type: ignore[attr-defined]
        if type(fd) is not int:
            raise PrimeP3DevelopmentDockerError()
        duplicates: list[int] = []
        try:
            for _ in range(count):
                duplicate = os.dup(fd)
                os.set_inheritable(duplicate, False)
                duplicates.append(duplicate)
            return tuple(duplicates)
        except OSError:
            for duplicate in duplicates:
                self._close_fd(duplicate)  # type: ignore[attr-defined]
            raise PrimeP3DevelopmentDockerError() from None
        finally:
            self._close_fd(fd)  # type: ignore[attr-defined]

    @staticmethod
    def _exact_workers(containers: tuple[P3DevelopmentContainer, ...]) -> None:
        if type(containers) is not tuple or tuple(container.role for container in containers) != _ROLES:
            raise PrimeP3DevelopmentDockerError()

    async def _cleanup_uncertain(self, containers: tuple[P3DevelopmentContainer, ...], names: tuple[str, ...]) -> None:
        control = _LifecycleCallControl(monotonic() + _CLEANUP_SECONDS, None)
        for identity in reversed(tuple(container.container_id for container in containers) + names):
            try:
                await self._call_raw(self._prefix + ("container", "rm", "--force", identity), control)  # type: ignore[attr-defined]
            except BaseException:
                pass


def _absolute_directory(value: object) -> bool:
    return type(value) is str and value.startswith("/") and not value.startswith("//") and "\x00" not in value


__all__ = ("P3DevelopmentContainer", "PrimeP3DevelopmentDockerError", "PrimeP3DevelopmentDockerTransport")
