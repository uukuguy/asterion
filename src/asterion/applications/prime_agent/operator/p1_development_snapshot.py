"""Operator-confirmed local-root snapshot transport for P1 development only.

The operator has confirmed that Docker's daemon and this host run in the same
Linux guest.  A Unix socket path alone never establishes that fact.  This is a
local development root operation, not a reduced-privilege authority feature.
"""

from __future__ import annotations

import json
import os
import stat
import sys

from .docker_cli import DockerCliAttachRunner, DockerCliEngineTransport, DockerCliRunner
from .docker_worker import _LifecycleCallControl
from .image_input_lock import ImagePlatformDescriptor
from asterion.services.restricted_worker import RestrictedWorkerError

_INSPECT_PROJECTION = (
    '[{"Id":{{json .Id}},"Pid":{{json .State.Pid}},'
    '"Running":{{json .State.Running}},"Paused":{{json .State.Paused}}}]'
)
_SNAPSHOT_CAP = 16 * 1024
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _require_local_root_snapshot_authority(operator_confirmed_same_guest: bool) -> None:
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or type(operator_confirmed_same_guest) is not bool
        or not operator_confirmed_same_guest
    ):
        raise RestrictedWorkerError("restricted worker value is invalid")


class _LocalRootProcSnapshot:
    """Private fixed-path snapshot primitive for an explicitly local daemon."""

    async def _snapshot_workspace_from_proc(
        self,
        container_id: str,
        *,
        control: _LifecycleCallControl,
        continuity_fixture: bytes | None = None,
    ) -> bytes:
        self._specification(container_id)  # type: ignore[reportAttributeAccessIssue] - concrete Docker transport
        pause_attempted = True
        paused = False
        try:
            await self._call(
                self._prefix + ("container", "pause", container_id),  # type: ignore[reportAttributeAccessIssue] - fixed base CLI prefix
                control,
            )
            paused = True
            inspection = await self._snapshot_inspection(container_id, control)
            proc_fd = workspace_fd = solution_fd = root_fd = state_fd = continuity_fd = None
            try:
                proc_fd = self._open_proc(inspection["Pid"])
                proc_identity = _identity(proc_fd)
                self._same_live_process(proc_fd, inspection["Pid"], proc_identity)
                root_fd = os.open(
                    "root", os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC, dir_fd=proc_fd
                )
                workspace_fd = os.open(
                    "workspace",
                    os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC | _NOFOLLOW,
                    dir_fd=root_fd,
                )
                if continuity_fixture is not None:
                    state_fd = os.open(
                        "p1b-state",
                        os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC | _NOFOLLOW,
                        dir_fd=workspace_fd,
                    )
                    continuity_fd = os.open(
                        "continuity.txt",
                        os.O_RDONLY | os.O_NONBLOCK | _CLOEXEC | _NOFOLLOW,
                        dir_fd=state_fd,
                    )
                    if _read_stable_regular_file(continuity_fd) != continuity_fixture:
                        raise ValueError
                solution_fd = os.open(
                    "solution.py",
                    os.O_RDONLY | os.O_NONBLOCK | _CLOEXEC | _NOFOLLOW,
                    dir_fd=workspace_fd,
                )
                data = _read_stable_regular_file(solution_fd)
                after = await self._snapshot_inspection(container_id, control)
                if after != inspection:
                    raise ValueError
                self._same_live_process(proc_fd, inspection["Pid"], proc_identity)
                return data
            finally:
                for descriptor in (
                    solution_fd, continuity_fd, state_fd, workspace_fd, root_fd, proc_fd,
                ):
                    _close_quietly(descriptor)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        finally:
            if paused:
                await self._resume_or_destroy(container_id)  # type: ignore[reportAttributeAccessIssue] - concrete Docker transport
            elif pause_attempted:
                await self._destroy_after_uncertain_pause(container_id)  # type: ignore[reportAttributeAccessIssue] - concrete Docker transport

    async def _snapshot_inspection(
        self, container_id: str, control: _LifecycleCallControl
    ) -> dict[str, object]:
        result = await self._call(
            self._prefix  # type: ignore[reportAttributeAccessIssue] - fixed base CLI prefix
            + ("container", "inspect", "--format", _INSPECT_PROJECTION, container_id),
            control,
            max_output_bytes=1024,
        )
        value = json.loads(result.stdout.decode("utf-8", "strict"))
        if (
            type(value) is not list
            or len(value) != 1
            or type(value[0]) is not dict
            or set(value[0]) != {"Id", "Pid", "Running", "Paused"}
        ):
            raise ValueError
        item = value[0]
        if (
            item["Id"] != container_id
            or type(item["Pid"]) is not int
            or item["Pid"] <= 0
            or item["Running"] is not True
            or item["Paused"] is not True
        ):
            raise ValueError
        return item

    @staticmethod
    def _open_proc(pid: object) -> int:
        if type(pid) is not int or pid <= 0:
            raise ValueError
        return os.open(
            "/proc/" + str(pid), os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC | _NOFOLLOW
        )

    @staticmethod
    def _same_live_process(
        proc_fd: int, pid: object, expected: tuple[int, int]
    ) -> None:
        if type(pid) is not int or pid <= 0 or _identity(proc_fd) != expected:
            raise ValueError
        current = os.stat("/proc/" + str(pid), follow_symlinks=False)
        if (current.st_dev, current.st_ino) != expected:
            raise ValueError
        os.kill(pid, 0)


class P1DevelopmentSnapshotTransport(_LocalRootProcSnapshot, DockerCliEngineTransport):
    """Read a paused tmpfs workspace through its daemon-bound container PID."""

    def __init__(
        self,
        *,
        docker_executable: str,
        socket_path: str,
        seccomp_profile_fd: int,
        platform: ImagePlatformDescriptor,
        operator_confirmed_same_guest: bool,
        runner: DockerCliRunner | None = None,
        attach_runner: DockerCliAttachRunner | None = None,
    ) -> None:
        _require_local_root_snapshot_authority(operator_confirmed_same_guest)
        super().__init__(
            docker_executable=docker_executable,
            socket_path=socket_path,
            seccomp_profile_fd=seccomp_profile_fd,
            platform=platform,
            runner=runner,
            attach_runner=attach_runner,
        )

    async def snapshot_solution(
        self, container_id: str, *, control: _LifecycleCallControl
    ) -> bytes:
        return await self._snapshot_workspace_from_proc(container_id, control=control)


def _stable_regular_file(descriptor: int) -> tuple[int, int, int, int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or not 0 <= metadata.st_size <= _SNAPSHOT_CAP:
        raise ValueError
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_stable_regular_file(descriptor: int) -> bytes:
    before = _stable_regular_file(descriptor)
    data = os.pread(descriptor, before[2] + 1, 0)
    if len(data) != before[2] or _stable_regular_file(descriptor) != before:
        raise ValueError
    return data


def _identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError
    return metadata.st_dev, metadata.st_ino


def _close_quietly(descriptor: int | None) -> None:
    if type(descriptor) is int and descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = ("P1DevelopmentSnapshotTransport",)
