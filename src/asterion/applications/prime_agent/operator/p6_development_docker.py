"""Restricted direct-Docker worker for the staged P6 evidence protocol."""

from __future__ import annotations

import asyncio
import re
from time import monotonic

from .docker_worker import _LifecycleCallControl
from .p5_development_docker import (
    P5DevelopmentDockerTransport,
    PrimeP5DevelopmentDockerError,
    _READ_CAP,
)

_ID = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


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
        try:
            return await self.create_p5(image_digest=image_digest, workspace=workspace, control=control)
        except PrimeP5DevelopmentDockerError as error:
            raise PrimeP6DevelopmentDockerError() from error

    async def execute_p6(self, container_id: str, cell: str, control: _LifecycleCallControl) -> None:
        try:
            await self.execute_p5(container_id, cell, control)
        except PrimeP5DevelopmentDockerError as error:
            raise PrimeP6DevelopmentDockerError() from error

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
