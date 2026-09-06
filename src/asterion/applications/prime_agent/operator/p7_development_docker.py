"""Restricted direct-Docker worker for the isolated P7 game episode."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import secrets
from time import monotonic

from .docker_cli import (
    _CLEARED_BASE_IMAGE_ENVIRONMENT,
    _ENVIRONMENT,
    _INSPECT_OUTPUT_CAP,
    _INSPECT_PROJECTION,
)
from .docker_worker import _LifecycleCallControl
from .p5_development_docker import P5DevelopmentDockerTransport, _CELL_CAP, _READ_CAP

_ID = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_P7_SNAPSHOT_CAP = 128 * 1024
_NAMES = (
    ("p7_client.py",),
    ("p7_client.py", "initial.json"),
    ("p7_client.py", "initial.json", "actions.json"),
    ("p7_client.py", "initial.json", "actions.json", "status.json"),
)
_READ_PROGRAM = "import os,stat,sys\nroot,name=sys.argv[1:3];expected=set(sys.argv[3:])\ntry:\n names=set(os.listdir(root))\n if names!=expected or name not in expected: raise ValueError\n d=os.open(root,os.O_RDONLY|os.O_DIRECTORY)\n try:\n  before=os.stat(name,dir_fd=d,follow_symlinks=False)\n  if not stat.S_ISREG(before.st_mode): raise ValueError\n  fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=d)\n  try:\n   after=os.fstat(fd)\n   if not stat.S_ISREG(after.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino): raise ValueError\n   data=os.read(fd,131073)\n   if not data or len(data)>131072: raise ValueError\n  finally: os.close(fd)\n finally: os.close(d)\nexcept BaseException: raise SystemExit(1)\nsys.stdout.buffer.write(data)\n"


class PrimeP7DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 development docker worker is unavailable")


def _path(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("/")
        and not value.startswith("//")
        and "\x00" not in value
    )


class P7DevelopmentDockerTransport(P5DevelopmentDockerTransport):
    """P7-only Docker calls, with the model socket as the sole broker mount."""

    async def create_p7(
        self,
        *,
        image_digest: str,
        workspace: str,
        broker_private_dir: str,
        broker_model_socket: str,
        control: _LifecycleCallControl,
    ) -> str:
        if (
            _DIGEST.fullmatch(image_digest) is None
            or not all(
                _path(item)
                for item in (workspace, broker_private_dir, broker_model_socket)
            )
            or Path(broker_model_socket).parent != Path(broker_private_dir)
            or Path(broker_model_socket).name != "model.sock"
        ):
            raise PrimeP7DevelopmentDockerError()
        name, fd = "prime-p7-" + secrets.token_hex(16), self._seccomp_profile_fd
        self._seccomp_profile_fd = None
        if type(fd) is not int:
            raise PrimeP7DevelopmentDockerError()
        platform = "/".join(
            item
            for item in (
                self._platform.os,
                self._platform.architecture,
                self._platform.variant,
            )
            if item is not None
        )
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
            "--volume",
            broker_model_socket + ":/broker/model.sock:ro,rprivate",
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
            await self._preflight(control)
            result = await self._call(argv, control, pass_fds=(fd,))
            daemon = self._parse_daemon_id(result.stdout)
            await self._inspect_p7_admission(
                daemon, image_digest, workspace, broker_model_socket, control
            )
            await self._call(self._prefix + ("container", "start", daemon), control)
            return daemon
        except asyncio.CancelledError:
            await self._uncertain(name)
            raise
        except BaseException:
            await self._uncertain(name)
            raise PrimeP7DevelopmentDockerError() from None
        finally:
            self._close_fd(fd)

    async def _inspect_p7_admission(
        self,
        daemon: str,
        image: str,
        workspace: str,
        socket_path: str,
        control: _LifecycleCallControl,
    ) -> None:
        result = await self._call(
            self._prefix
            + ("container", "inspect", "--format", _INSPECT_PROJECTION, daemon),
            control,
            max_output_bytes=_INSPECT_OUTPUT_CAP,
        )
        try:
            values = json.loads(result.stdout)[0]
            environment, ports, security, mounts = (
                values.pop("Env"),
                values.pop("PortBindings"),
                values.pop("SecurityOpt"),
                values.pop("Mounts"),
            )
            normalized = [
                {
                    key: item.get(key)
                    for key in ("Type", "Source", "Destination", "RW", "Propagation")
                }
                for item in mounts
            ]
            exact = {
                "Id": daemon,
                "Image": image,
                "User": "65534:65534",
                "Entrypoint": ["python", "-c", "import time; time.sleep(300)"],
                "Labels": {},
                "OpenStdin": False,
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapAdd": None,
                "CapDrop": ["ALL"],
                "Binds": [
                    workspace + ":/workspace:rw,rprivate",
                    socket_path + ":/broker/model.sock:ro,rprivate",
                ],
                "VolumesFrom": None,
                "Tmpfs": {
                    "/tmp": "rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700"
                },
                "PidsLimit": 64,
                "Memory": 268435456,
                "MemorySwap": 268435456,
                "NanoCpus": 1000000000,
                "PidMode": "",
                "IpcMode": "private",
                "UTSMode": "",
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "Running": False,
            }
            if (
                type(values) is not dict
                or values != exact
                or normalized
                != [
                    {
                        "Type": "bind",
                        "Source": workspace,
                        "Destination": "/workspace",
                        "RW": True,
                        "Propagation": "rprivate",
                    },
                    {
                        "Type": "bind",
                        "Source": socket_path,
                        "Destination": "/broker/model.sock",
                        "RW": False,
                        "Propagation": "rprivate",
                    },
                ]
                or not self._valid_environment(environment)
                or ports not in (None, {})
                or security
                != ["no-new-privileges:true", "seccomp=" + self._seccomp_profile]
                or result.stderr
            ):
                raise ValueError
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise PrimeP7DevelopmentDockerError() from None

    async def execute_p7(
        self, container_id: str, cell: str, control: _LifecycleCallControl
    ) -> None:
        if (
            _ID.fullmatch(container_id) is None
            or type(cell) is not str
            or not cell
            or len(cell.encode()) > _CELL_CAP
        ):
            raise PrimeP7DevelopmentDockerError()
        try:
            await self._call(
                self._prefix
                + (
                    "container",
                    "exec",
                    "--workdir",
                    "/workspace",
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
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP7DevelopmentDockerError() from None

    async def read_p7(
        self,
        container_id: str,
        name: str,
        expected: tuple[str, ...],
        control: _LifecycleCallControl,
    ) -> bytes:
        if (
            _ID.fullmatch(container_id) is None
            or expected not in _NAMES
            or name not in expected
        ):
            raise PrimeP7DevelopmentDockerError()
        try:
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
                    "/workspace",
                    name,
                    *expected,
                ),
                control,
                max_output_bytes=_P7_SNAPSHOT_CAP,
            )
            if (
                result.stderr
                or type(result.stdout) is not bytes
                or not result.stdout
                or len(result.stdout) > _P7_SNAPSHOT_CAP
            ):
                raise ValueError
            return result.stdout
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeP7DevelopmentDockerError() from None

    async def remove_p7(
        self, container_id: str, control: _LifecycleCallControl
    ) -> None:
        await self.remove_p5(container_id, control)

    async def assert_p7_absent(
        self, container_id: str, control: _LifecycleCallControl
    ) -> None:
        await self.assert_p5_absent(container_id, control)


class P7DevelopmentDockerWorkerService:
    def __init__(
        self,
        *,
        image_digest: str,
        transport: object,
        run_id: str,
        session_id: str,
        goal_id: str,
        workspace: str,
        broker_private_dir: str,
        broker_model_socket: str,
        client_module: bytes | None = None,
    ) -> None:
        if (
            _DIGEST.fullmatch(image_digest) is None
            or not all(
                type(value) is str and value for value in (run_id, session_id, goal_id)
            )
            or not all(
                _path(item)
                for item in (workspace, broker_private_dir, broker_model_socket)
            )
            or Path(broker_model_socket).parent != Path(broker_private_dir)
            or Path(broker_model_socket).name != "model.sock"
            or (
                client_module is not None
                and (
                    type(client_module) is not bytes
                    or not client_module
                    or len(client_module) > _READ_CAP
                    or b"/broker/model.sock" not in client_module
                )
            )
        ):
            raise PrimeP7DevelopmentDockerError()
        self._transport, self._image, self._workspace = (
            transport,
            image_digest,
            workspace,
        )
        self._private, self._socket, self._client = (
            broker_private_dir,
            broker_model_socket,
            client_module,
        )
        self._container: str | None = None
        self._stage = 0

    @property
    def daemon_id(self) -> str:
        if self._container is None:
            raise PrimeP7DevelopmentDockerError()
        return self._container

    @property
    def container_digest(self) -> str:
        return "sha256:" + self.daemon_id

    @property
    def image_digest(self) -> str:
        return self._image

    async def acquire(
        self, client: bytes | None = None, broker_mount: str = "/broker"
    ) -> None:
        create = getattr(self._transport, "create_p7", None)
        module = self._client if client is None else client
        if (
            not callable(create)
            or self._stage
            or broker_mount != "/broker"
            or type(module) is not bytes
            or not module
            or len(module) > _READ_CAP
            or b"/broker/model.sock" not in module
        ):
            raise PrimeP7DevelopmentDockerError()
        self._client = module
        self._seed_client()
        value = await create(
            image_digest=self._image,
            workspace=self._workspace,
            broker_private_dir=self._private,
            broker_model_socket=self._socket,
            control=_control(),
        )
        if type(value) is not str or _ID.fullmatch(value) is None:
            raise PrimeP7DevelopmentDockerError()
        self._container, self._stage = value, 1

    def _seed_client(self) -> None:
        try:
            root = os.open(
                self._workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                if os.listdir(root):
                    raise ValueError
                fd = os.open(
                    "p7_client.py",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=root,
                )
                try:
                    if os.write(fd, self._client) != len(self._client):
                        raise ValueError
                    os.fchown(fd, 65534, 65534)
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)
            finally:
                os.close(root)
        except (OSError, ValueError):
            raise PrimeP7DevelopmentDockerError() from None

    async def snapshot(self) -> dict[str, bytes]:
        expected = _NAMES[self._stage - 1] if self._stage in range(1, 5) else None
        if expected is None:
            raise PrimeP7DevelopmentDockerError()
        values = {name: await self._read(name, expected) for name in expected}
        if values["p7_client.py"] != self._client:
            raise PrimeP7DevelopmentDockerError()
        return values

    async def execute_cell(self, cell: str) -> dict[str, object]:
        execute = getattr(self._transport, "execute_p7", None)
        if self._stage not in {1, 2, 3} or not callable(execute):
            raise PrimeP7DevelopmentDockerError()
        await execute(self.daemon_id, cell, _control())
        self._stage += 1
        return {"cell_count": self._stage - 1}

    async def cleanup(self) -> None:
        if self._stage == 5:
            return
        remove, absent = (
            getattr(self._transport, "remove_p7", None),
            getattr(self._transport, "assert_p7_absent", None),
        )
        if self._container is None or not callable(remove) or not callable(absent):
            raise PrimeP7DevelopmentDockerError()

        async def destroy() -> None:
            await remove(self._container, _control())
            await absent(self._container, _control())
            self._stage = 5

        task = asyncio.ensure_future(destroy())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError()

    async def _read(self, name: str, expected: tuple[str, ...]) -> bytes:
        read = getattr(self._transport, "read_p7", None)
        if not callable(read):
            raise PrimeP7DevelopmentDockerError()
        value = await read(self.daemon_id, name, expected, _control())
        cap = _READ_CAP if name == "p7_client.py" else _P7_SNAPSHOT_CAP
        if type(value) is not bytes or not value or len(value) > cap:
            raise PrimeP7DevelopmentDockerError()
        return value


def _control() -> _LifecycleCallControl:
    return _LifecycleCallControl(monotonic() + 30, None)


__all__ = (
    "P7DevelopmentDockerTransport",
    "P7DevelopmentDockerWorkerService",
    "PrimeP7DevelopmentDockerError",
)
