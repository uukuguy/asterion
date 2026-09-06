"""One direct restricted P3-image container for P5 repair evidence."""

from __future__ import annotations
import asyncio
import os
import re
import secrets
import stat
from time import monotonic
from .docker_cli import (
    DockerCliEngineTransport,
    _CLEARED_BASE_IMAGE_ENVIRONMENT,
    _ENVIRONMENT,
)
from .docker_worker import _LifecycleCallControl

_ID = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CELL_CAP, _READ_CAP = 16 * 1024, 16 * 1024
_READ_PROGRAM = "import os,stat,sys\nroot='/workspace';name=sys.argv[1];expected=set(sys.argv[2:])\ntry:\n names=set(os.listdir(root))\n if names!=expected or name not in expected: raise ValueError\n d=os.open(root,os.O_RDONLY|os.O_DIRECTORY)\n try:\n  before=os.stat(name,dir_fd=d,follow_symlinks=False)\n  if not stat.S_ISREG(before.st_mode): raise ValueError\n  fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=d)\n  try:\n   after=os.fstat(fd)\n   if not stat.S_ISREG(after.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino): raise ValueError\n   data=os.read(fd,16385)\n   if not data or len(data)>16384: raise ValueError\n  finally: os.close(fd)\n finally: os.close(d)\nexcept BaseException: raise SystemExit(1)\nsys.stdout.buffer.write(data)\n"


class PrimeP5DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 development docker worker is unavailable")


class P5DevelopmentDockerTransport(DockerCliEngineTransport):
    """Fixed direct Docker operations; there is deliberately no RLM mount."""

    async def create_p5(
        self, *, image_digest: str, workspace: str, control: _LifecycleCallControl
    ) -> str:
        if _DIGEST.fullmatch(image_digest) is None or not _path(workspace):
            raise PrimeP5DevelopmentDockerError()
        name, fd = "prime-p5-" + secrets.token_hex(16), self._seccomp_profile_fd  # type: ignore[attr-defined]
        self._seccomp_profile_fd = None  # type: ignore[attr-defined]
        if type(fd) is not int:
            raise PrimeP5DevelopmentDockerError()
        platform = "/".join(
            x
            for x in (
                self._platform.os,
                self._platform.architecture,
                self._platform.variant,
            )
            if x is not None
        )  # type: ignore[attr-defined]
        argv = self._prefix + (
            "create",
            "--name",
            name,
            "--pull=never",
            "--platform",
            platform,
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--security-opt",
            "seccomp=/proc/self/fd/" + str(fd),
            "--tmpfs",
            "/tmp:rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700",
            "--volume",
            workspace + ":/workspace:rw,rprivate",
            "--env",
            _ENVIRONMENT[0],
            "--env",
            _ENVIRONMENT[1],
            "--env",
            _ENVIRONMENT[2],
            "--env",
            _CLEARED_BASE_IMAGE_ENVIRONMENT[0],
            "--env",
            _CLEARED_BASE_IMAGE_ENVIRONMENT[1],
            "--env",
            _CLEARED_BASE_IMAGE_ENVIRONMENT[2],
            "--env",
            _CLEARED_BASE_IMAGE_ENVIRONMENT[3],
            "--pids-limit",
            "64",
            "--memory",
            "268435456",
            "--memory-swap",
            "268435456",
            "--cpus",
            "1",
            "--restart",
            "no",
            image_digest,
        )
        try:
            await self._preflight(control)  # type: ignore[attr-defined]
            result = await self._call(argv, control, pass_fds=(fd,))  # type: ignore[attr-defined]
            daemon = self._parse_daemon_id(result.stdout)  # type: ignore[attr-defined]
            await self._call(self._prefix + ("container", "start", daemon), control)  # type: ignore[attr-defined]
            return daemon
        except asyncio.CancelledError:
            await self._uncertain(name)
            raise
        except BaseException:
            await self._uncertain(name)
            raise PrimeP5DevelopmentDockerError() from None
        finally:
            self._close_fd(fd)  # type: ignore[attr-defined]

    async def execute_p5(
        self, container_id: str, cell: str, control: _LifecycleCallControl
    ) -> None:
        if (
            _ID.fullmatch(container_id) is None
            or type(cell) is not str
            or not cell
            or len(cell.encode()) > _CELL_CAP
        ):
            raise PrimeP5DevelopmentDockerError()
        try:
            await self._call(
                self._prefix
                + (
                    "container",
                    "exec",
                    "--user",
                    "65534:65534",
                    "--env",
                    "HOME=/tmp",
                    "--env",
                    "IPYTHONDIR=/tmp/ipython",
                    container_id,
                    "/usr/local/bin/ipython",
                    "--no-banner",
                    "--no-confirm-exit",
                    "-c",
                    cell,
                ),
                control,
                max_output_bytes=4096,
            )  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP5DevelopmentDockerError() from None

    async def read_p5(
        self,
        container_id: str,
        name: str,
        result_required: bool,
        control: _LifecycleCallControl,
    ) -> bytes:
        if _ID.fullmatch(container_id) is None or name not in {
            "solution.py",
            "result.json",
        }:
            raise PrimeP5DevelopmentDockerError()
        try:
            expected = (
                ("solution.py", "result.json") if result_required else ("solution.py",)
            )
            result = await self._call(
                self._prefix
                + (
                    "container",
                    "exec",
                    "--user",
                    "65534:65534",
                    container_id,
                    "/usr/local/bin/python3",
                    "-I",
                    "-c",
                    _READ_PROGRAM,
                    name,
                    *expected,
                ),
                control,
                max_output_bytes=_READ_CAP,
            )  # type: ignore[attr-defined]
            if (
                result.stderr
                or type(result.stdout) is not bytes
                or not result.stdout
                or len(result.stdout) > _READ_CAP
            ):
                raise ValueError
            return result.stdout
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP5DevelopmentDockerError() from None

    async def remove_p5(
        self, container_id: str, control: _LifecycleCallControl
    ) -> None:
        result = await self._call(
            self._prefix + ("container", "rm", "--force", container_id), control
        )  # type: ignore[attr-defined]
        if result.stderr or result.stdout not in (b"", (container_id + "\n").encode()):
            raise PrimeP5DevelopmentDockerError()

    async def assert_p5_absent(
        self, container_id: str, control: _LifecycleCallControl
    ) -> None:
        result = await self._call_raw(
            self._prefix
            + ("container", "inspect", "--format", "{{.Id}}", container_id),
            control,
        )  # type: ignore[attr-defined]
        absent = {
            ("Error: No such object: " + container_id + "\n").encode(),
            ("Error: No such container: " + container_id + "\n").encode(),
            (
                "Error response from daemon: No such container: " + container_id + "\n"
            ).encode(),
            ("No such container: " + container_id).encode(),
        }
        if (
            result.returncode != 1
            or result.stdout not in (b"", b"\n")
            or result.stderr not in absent
        ):
            raise PrimeP5DevelopmentDockerError()

    async def _uncertain(self, identity: str) -> None:
        try:
            await self._call_raw(
                self._prefix + ("container", "rm", "--force", identity), _control()
            )  # type: ignore[attr-defined]
        except BaseException:
            pass


class P5DevelopmentDockerWorkerService:
    __slots__ = (
        "_container",
        "_goal",
        "_image",
        "_run",
        "_stage",
        "_transport",
        "_workspace",
    )

    def __init__(
        self,
        *,
        image_digest: str,
        transport: object,
        run_id: str,
        session_id: str,
        goal_id: str,
        workspace: str = "/workspace",
    ) -> None:
        if (
            _DIGEST.fullmatch(image_digest) is None
            or not all(type(x) is str and x for x in (run_id, session_id, goal_id))
            or not _path(workspace)
        ):
            raise PrimeP5DevelopmentDockerError()
        (
            self._transport,
            self._image,
            self._run,
            self._goal,
            self._workspace,
            self._container,
            self._stage,
        ) = transport, image_digest, run_id, goal_id, workspace, None, 0

    @property
    def daemon_id(self) -> str:
        if self._container is None:
            raise PrimeP5DevelopmentDockerError()
        return self._container

    @property
    def image_digest(self) -> str:
        return self._image

    async def acquire(self) -> None:
        create = getattr(self._transport, "create_p5", None)
        if not callable(create) or self._stage:
            raise PrimeP5DevelopmentDockerError()
        value = await create(
            image_digest=self._image, workspace=self._workspace, control=_control()
        )
        if type(value) is not str or _ID.fullmatch(value) is None:
            raise PrimeP5DevelopmentDockerError()
        self._container, self._stage = value, 1

    async def snapshot(self) -> dict[str, bytes]:
        if self._stage not in {1, 2, 3}:
            raise PrimeP5DevelopmentDockerError()
        return {"solution.py": await self._read("solution.py")}

    async def execute_cell(self, cell: str) -> dict[str, object]:
        if self._stage not in {1, 2}:
            raise PrimeP5DevelopmentDockerError()
        execute = getattr(self._transport, "execute_p5", None)
        if not callable(execute):
            raise PrimeP5DevelopmentDockerError()
        await execute(self.daemon_id, cell, _control())
        self._stage += 1
        return {"cell_count": self._stage - 1}

    async def artifact(self) -> bytes:
        if self._stage not in {2, 3}:
            raise PrimeP5DevelopmentDockerError()
        return await self._read("result.json")

    async def cleanup(self) -> None:
        if self._container is None:
            raise PrimeP5DevelopmentDockerError()
        remove, absent = (
            getattr(self._transport, "remove_p5", None),
            getattr(self._transport, "assert_p5_absent", None),
        )
        if not callable(remove) or not callable(absent):
            raise PrimeP5DevelopmentDockerError()
        await _shield_cleanup(remove(self._container, _control()))
        await _shield_cleanup(absent(self._container, _control()))
        self._stage = 4

    async def _read(self, name: str) -> bytes:
        read = getattr(self._transport, "read_p5", None)
        if not callable(read):
            raise PrimeP5DevelopmentDockerError()
        value = await read(self.daemon_id, name, self._stage >= 2, _control())
        if type(value) is not bytes or not value or len(value) > _READ_CAP:
            raise PrimeP5DevelopmentDockerError()
        return value


def _control() -> _LifecycleCallControl:
    return _LifecycleCallControl(monotonic() + 30, None)


async def _shield_cleanup(awaitable: object) -> None:
    if not hasattr(awaitable, "__await__"):
        raise PrimeP5DevelopmentDockerError()
    task = asyncio.ensure_future(awaitable)  # type: ignore[arg-type]
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


def _path(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("/")
        and not value.startswith("//")
        and "\x00" not in value
    )


def _trusted_workspace_read(root: str, name: str, expected: tuple[str, ...]) -> bytes:
    """Provider-free equivalent of the fixed in-container read program."""
    if name not in expected or set(os.listdir(root)) != set(expected):
        raise PrimeP5DevelopmentDockerError()
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise PrimeP5DevelopmentDockerError()
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            after = os.fstat(descriptor)
            if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (
                after.st_dev,
                after.st_ino,
            ):
                raise PrimeP5DevelopmentDockerError()
            value = os.read(descriptor, _READ_CAP + 1)
            if not value or len(value) > _READ_CAP:
                raise PrimeP5DevelopmentDockerError()
            return value
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


__all__ = (
    "P5DevelopmentDockerTransport",
    "P5DevelopmentDockerWorkerService",
    "PrimeP5DevelopmentDockerError",
)
