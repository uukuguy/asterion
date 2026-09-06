"""Restricted direct-Docker worker for the staged P6 evidence protocol."""

from __future__ import annotations

import asyncio
import re
import secrets
from time import monotonic

from .docker_cli import _CLEARED_BASE_IMAGE_ENVIRONMENT, _ENVIRONMENT
from .docker_worker import _LifecycleCallControl
from .p5_development_docker import (
    P5DevelopmentDockerTransport,
    _CELL_CAP,
    _READ_CAP,
)

_ID = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RESTORE_PROGRAM = "import os,stat,sys\nroot=sys.argv[1]\ntry:\n d=os.open(root,os.O_RDONLY|os.O_DIRECTORY)\n try:\n  if set(os.listdir(root))!=set(['baseline.py','task-a.json','candidate.py','task-b.json']): raise ValueError\n  for n in ['baseline.py','task-a.json','candidate.py','task-b.json']:\n   s=os.stat(n,dir_fd=d,follow_symlinks=False)\n   if not stat.S_ISREG(s.st_mode): raise ValueError\n  for n in ['task-a.json','candidate.py','task-b.json']: os.unlink(n,dir_fd=d)\n  if set(os.listdir(root))!=set(['baseline.py']): raise ValueError\n finally: os.close(d)\nexcept BaseException: raise SystemExit(1)\n"


class PrimeP6DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P6 development docker worker is unavailable")


class P6DevelopmentDockerTransport(P5DevelopmentDockerTransport):
    """P3 direct Docker profile with P6-only operation names.

    The inherited create path is the reviewed P3 profile: networkless, private
    IPC, read-only root, no capabilities, seccomp, bounded resources, and a
    cleared environment.  P6's reader additionally admits its exact inventory.
    """

    async def create_p6(self, *, image_digest: str, workspace: str, control: _LifecycleCallControl) -> str:
        if _DIGEST.fullmatch(image_digest) is None or not workspace.startswith("/") or workspace.startswith("//") or "\x00" in workspace:
            raise PrimeP6DevelopmentDockerError()
        name, fd = "prime-p6-" + secrets.token_hex(16), self._seccomp_profile_fd
        self._seccomp_profile_fd = None
        if type(fd) is not int:
            raise PrimeP6DevelopmentDockerError()
        platform = "/".join(item for item in (self._platform.os, self._platform.architecture, self._platform.variant) if item is not None)
        argv = self._prefix + ("create", "--name", name, "--pull=never", "--platform", platform, "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--security-opt", "seccomp=/proc/self/fd/" + str(fd), "--tmpfs", "/tmp:rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700", "--volume", workspace + ":/workspace:rw,rprivate", "--env", _ENVIRONMENT[0], "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[0], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[1], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[2], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[3], "--pids-limit", "64", "--memory", "268435456", "--memory-swap", "268435456", "--cpus", "1", "--restart", "no", image_digest)
        try:
            await self._preflight(control)
            result = await self._call(argv, control, pass_fds=(fd,))
            daemon = self._parse_daemon_id(result.stdout)
            await self._inspect_admission(daemon, image_digest, workspace, control)
            await self._call(self._prefix + ("container", "start", daemon), control)
            return daemon
        except asyncio.CancelledError:
            await self._uncertain(name)
            raise
        except BaseException:
            await self._uncertain(name)
            raise PrimeP6DevelopmentDockerError() from None
        finally:
            self._close_fd(fd)

    async def execute_p6(self, container_id: str, cell: str, control: _LifecycleCallControl) -> None:
        if _ID.fullmatch(container_id) is None or type(cell) is not str or not cell or len(cell.encode()) > _CELL_CAP:
            raise PrimeP6DevelopmentDockerError()
        try:
            await self._call(self._prefix + ("container", "exec", "--workdir", "/workspace", "--user", "65534:65534", "--env", "HOME=/tmp", "--env", "IPYTHONDIR=/tmp/ipython", container_id, "/usr/local/bin/ipython", "--no-banner", "--no-confirm-exit", "-c", cell), control, max_output_bytes=4096)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP6DevelopmentDockerError() from None

    async def read_p6(self, container_id: str, name: str, expected: tuple[str, ...], control: _LifecycleCallControl) -> bytes:
        if _ID.fullmatch(container_id) is None or name not in expected or expected not in {("baseline.py",), ("baseline.py", "task-a.json"), ("baseline.py", "task-a.json", "candidate.py"), ("baseline.py", "task-a.json", "candidate.py", "task-b.json")}:
            raise PrimeP6DevelopmentDockerError()
        try:
            from .p5_development_docker import _READ_PROGRAM

            result = await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", container_id, "/usr/local/bin/python3", "-I", "-c", _READ_PROGRAM, "/workspace", name, *expected), control, max_output_bytes=_READ_CAP)
            if result.stderr or type(result.stdout) is not bytes or not result.stdout or len(result.stdout) > _READ_CAP:
                raise ValueError
            return result.stdout
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP6DevelopmentDockerError() from None

    async def remove_p6(self, container_id: str, control: _LifecycleCallControl) -> None:
        await self.remove_p5(container_id, control)

    async def assert_p6_absent(self, container_id: str, control: _LifecycleCallControl) -> None:
        await self.assert_p5_absent(container_id, control)

    async def restore_p6_baseline(self, container_id: str, control: _LifecycleCallControl) -> None:
        if _ID.fullmatch(container_id) is None:
            raise PrimeP6DevelopmentDockerError()
        try:
            result = await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", container_id, "/usr/local/bin/python3", "-I", "-c", _RESTORE_PROGRAM, "/workspace"), control, max_output_bytes=4096)
            if result.stdout or result.stderr:
                raise ValueError
            baseline = await self.read_p6(container_id, "baseline.py", ("baseline.py",), control)
            from .p6_development_host import _BASELINE_SOURCE
            if baseline != _BASELINE_SOURCE:
                raise ValueError
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP6DevelopmentDockerError() from None


class P6DevelopmentDockerWorkerService:
    """One container, actual bounded bytes, and no more than three cells."""

    def __init__(self, *, image_digest: str, transport: object, run_id: str, session_id: str, goal_id: str, workspace: str = "/workspace") -> None:
        if _DIGEST.fullmatch(image_digest) is None or not all(type(item) is str and item for item in (run_id, session_id, goal_id)) or not workspace.startswith("/") or workspace.startswith("//"):
            raise PrimeP6DevelopmentDockerError()
        self._transport, self._image, self._workspace = transport, image_digest, workspace
        self._container: str | None = None
        self._stage = 0

    @property
    def daemon_id(self) -> str:
        if self._container is None:
            raise PrimeP6DevelopmentDockerError()
        return self._container

    @property
    def image_digest(self) -> str:
        return self._image

    async def acquire(self) -> None:
        create = getattr(self._transport, "create_p6", None)
        if not callable(create) or self._stage:
            raise PrimeP6DevelopmentDockerError()
        value = await create(image_digest=self._image, workspace=self._workspace, control=_control())
        if type(value) is not str or _ID.fullmatch(value) is None:
            raise PrimeP6DevelopmentDockerError()
        self._container, self._stage = value, 1

    async def snapshot(self) -> dict[str, bytes]:
        expected = {1: ("baseline.py",), 2: ("baseline.py", "task-a.json"), 3: ("baseline.py", "task-a.json", "candidate.py"), 4: ("baseline.py", "task-a.json", "candidate.py", "task-b.json"), 5: ("baseline.py",)}.get(self._stage)
        if expected is None:
            raise PrimeP6DevelopmentDockerError()
        return {name: await self._read(name, expected) for name in expected}

    async def execute_cell(self, cell: str) -> dict[str, object]:
        execute = getattr(self._transport, "execute_p6", None)
        if self._stage not in {1, 2, 3} or not callable(execute):
            raise PrimeP6DevelopmentDockerError()
        await execute(self.daemon_id, cell, _control())
        self._stage += 1
        return {"cell_count": self._stage - 1}

    async def restore_baseline(self) -> None:
        restore = getattr(self._transport, "restore_p6_baseline", None)
        if self._stage != 4 or not callable(restore):
            raise PrimeP6DevelopmentDockerError()
        await restore(self.daemon_id, _control())
        self._stage = 5

    async def cleanup(self) -> None:
        if self._stage == 6:
            return
        remove, absent = getattr(self._transport, "remove_p6", None), getattr(self._transport, "assert_p6_absent", None)
        if self._container is None or not callable(remove) or not callable(absent):
            raise PrimeP6DevelopmentDockerError()
        async def destroy() -> None:
            await remove(self._container, _control())
            await absent(self._container, _control())
            self._stage = 6
        task = asyncio.ensure_future(destroy())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        task.result()
        if interrupted:
            raise asyncio.CancelledError()

    async def _read(self, name: str, expected: tuple[str, ...]) -> bytes:
        read = getattr(self._transport, "read_p6", None)
        if not callable(read):
            raise PrimeP6DevelopmentDockerError()
        value = await read(self.daemon_id, name, expected, _control())
        if type(value) is not bytes or not value or len(value) > _READ_CAP:
            raise PrimeP6DevelopmentDockerError()
        return value


def _control() -> _LifecycleCallControl:
    return _LifecycleCallControl(monotonic() + 30, None)


__all__ = ("P6DevelopmentDockerTransport", "P6DevelopmentDockerWorkerService", "PrimeP6DevelopmentDockerError")
