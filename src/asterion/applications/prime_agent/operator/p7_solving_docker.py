"""Persistent restricted Docker worker used by the P7 solving tool."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import re
import secrets
from time import monotonic

from .docker_cli import (
    DockerCliEngineTransport,
    _CLEARED_BASE_IMAGE_ENVIRONMENT,
    _ENVIRONMENT,
    _INSPECT_OUTPUT_CAP,
    _INSPECT_PROJECTION,
)
from .docker_worker import _LifecycleCallControl
from .p7_development_docker import _normalized_bind_mounts, _normalized_mounts

_ID = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CELL_CAP = 16 * 1024
_OUTPUT_CAP = 4096
_FRAME_CAP = 65536
_CELL_LIMIT = 128


class P7SolvingDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving Docker worker is unavailable")


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _path(value: object) -> bool:
    return type(value) is str and value.startswith("/") and not value.startswith("//") and "\x00" not in value


def _control() -> _LifecycleCallControl:
    return _LifecycleCallControl(monotonic() + 30, None)


class P7SolvingDockerTransport(DockerCliEngineTransport):
    """Docker call/control adapter for one long-lived solve-image container."""

    async def create_solving(
        self, *, image_digest: str, workspace: str, broker_private_dir: str,
        broker_model_socket: str, control: _LifecycleCallControl,
    ) -> str:
        if (_DIGEST.fullmatch(image_digest) is None or not all(_path(value) for value in (workspace, broker_private_dir, broker_model_socket)) or Path(broker_model_socket).parent != Path(broker_private_dir) or Path(broker_model_socket).name != "model.sock"):
            raise P7SolvingDockerError()
        name, fd = "prime-p7-solving-" + secrets.token_hex(16), self._seccomp_profile_fd
        self._seccomp_profile_fd = None
        if type(fd) is not int:
            raise P7SolvingDockerError()
        platform = "/".join(item for item in (self._platform.os, self._platform.architecture, self._platform.variant) if item is not None)
        argv = self._prefix + (
            "create", "--name", name, "--pull=never", "--platform", platform,
            "--network", "none", "--read-only", "--user", "65534:65534",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--security-opt", "seccomp=/proc/self/fd/" + str(fd), "--tmpfs",
            "/tmp:rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700",
            "--volume", workspace + ":/workspace:rw,rprivate", "--volume",
            broker_model_socket + ":/broker/model.sock:ro,rprivate", "--env", _ENVIRONMENT[0],
            "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2], "--env",
            _CLEARED_BASE_IMAGE_ENVIRONMENT[0], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[1],
            "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[2], "--env",
            _CLEARED_BASE_IMAGE_ENVIRONMENT[3], "--pids-limit", "64", "--memory",
            "268435456", "--memory-swap", "268435456", "--cpus", "1", "--restart", "no", image_digest,
        )
        try:
            await self._preflight(control)
            result = await self._call(argv, control, pass_fds=(fd,))
            daemon = self._parse_daemon_id(result.stdout)
            await self._inspect_solving(daemon, image_digest, workspace, broker_model_socket, control)
            await self._call(self._prefix + ("container", "start", daemon), control)
            return daemon
        except asyncio.CancelledError:
            await self._uncertain(name)
            raise
        except BaseException:
            await self._uncertain(name)
            raise P7SolvingDockerError() from None
        finally:
            self._close_fd(fd)

    async def _inspect_solving(self, daemon: str, image: str, workspace: str, socket_path: str, control: _LifecycleCallControl) -> None:
        result = await self._call(self._prefix + ("container", "inspect", "--format", _INSPECT_PROJECTION, daemon), control, max_output_bytes=_INSPECT_OUTPUT_CAP)
        try:
            values = json.loads(result.stdout)[0]
            environment, ports, security, mounts, binds = (values.pop("Env"), values.pop("PortBindings"), values.pop("SecurityOpt"), values.pop("Mounts"), values.pop("Binds"))
            exact = {"Id": daemon, "Image": image, "User": "65534:65534", "Entrypoint": ["/usr/local/bin/prime-p7-solving"], "Labels": {}, "OpenStdin": False, "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "VolumesFrom": None, "Tmpfs": {"/tmp": "rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700"}, "PidsLimit": 64, "Memory": 268435456, "MemorySwap": 268435456, "NanoCpus": 1000000000, "PidMode": "", "IpcMode": "private", "UTSMode": "", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}, "Running": False}
            if (type(values) is not dict or values != exact or _normalized_bind_mounts(binds) != tuple(sorted(((workspace + ":/workspace:rw,rprivate",), (socket_path + ":/broker/model.sock:ro,rprivate",)))) or _normalized_mounts(mounts) != tuple(sorted((("bind", workspace, "/workspace", True, "rprivate"), ("bind", socket_path, "/broker/model.sock", False, "rprivate")))) or not self._valid_environment(environment) or ports not in (None, {}) or security != ["no-new-privileges:true", "seccomp=" + self._seccomp_profile] or result.stderr):
                raise ValueError
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise P7SolvingDockerError() from None

    async def execute_solving(self, container_id: str, code: str, control: _LifecycleCallControl) -> dict[str, object]:
        if _ID.fullmatch(container_id) is None or type(code) is not str or not code or len(code.encode()) > _CELL_CAP:
            raise P7SolvingDockerError()
        try:
            result = await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", "--workdir", "/workspace", "--env", "HOME=/tmp", "--env", "IPYTHONDIR=/tmp/ipython", container_id, "/usr/local/bin/prime-p7-solving", "--client", base64.b64encode(code.encode()).decode("ascii")), control, max_output_bytes=_FRAME_CAP)
            value = json.loads(result.stdout)
            if result.stderr or type(value) is not dict or _canonical(value) != result.stdout or set(value) != {"cell_count", "output", "is_error"} or type(value["cell_count"]) is not int or type(value["output"]) is not str or type(value["is_error"]) is not bool or len(value["output"].encode()) > _OUTPUT_CAP:
                raise ValueError
            return value
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise P7SolvingDockerError() from None

    async def remove_solving(self, container_id: str, control: _LifecycleCallControl) -> None:
        result = await self._call(self._prefix + ("container", "rm", "--force", container_id), control)
        if result.stderr or result.stdout not in (b"", (container_id + "\n").encode()):
            raise P7SolvingDockerError()

    async def assert_solving_absent(self, container_id: str, control: _LifecycleCallControl) -> None:
        result = await self._call_raw(self._prefix + ("container", "inspect", "--format", "{{.Id}}", container_id), control)
        absent = {("Error: No such object: " + container_id + "\n").encode(), ("Error: No such container: " + container_id + "\n").encode(), ("Error response from daemon: No such container: " + container_id + "\n").encode(), ("No such container: " + container_id).encode()}
        if result.returncode != 1 or result.stdout not in (b"", b"\n") or result.stderr not in absent:
            raise P7SolvingDockerError()

    async def _uncertain(self, identity: str) -> None:
        try:
            await self.remove_solving(identity, _control())
        except BaseException:
            pass
        try:
            await self.assert_solving_absent(identity, _control())
        except BaseException:
            raise P7SolvingDockerError() from None

    async def _cleanup_cancelled(self, identity: str) -> None:
        await self._uncertain(identity)
        raise asyncio.CancelledError()


class P7SolvingDockerWorker:
    """Bounded cell API without workspace discovery or public host details."""

    def __init__(self, *, image_digest: str, transport: object, workspace: str, broker_private_dir: str, broker_model_socket: str) -> None:
        if (_DIGEST.fullmatch(image_digest) is None or not all(_path(value) for value in (workspace, broker_private_dir, broker_model_socket)) or Path(broker_model_socket).parent != Path(broker_private_dir) or Path(broker_model_socket).name != "model.sock"):
            raise P7SolvingDockerError()
        self._image, self._transport, self._workspace = image_digest, transport, workspace
        self._private, self._socket, self._container, self._count, self._cleaned = broker_private_dir, broker_model_socket, None, 0, False

    def __repr__(self) -> str:
        return "P7SolvingDockerWorker(redacted)"

    async def acquire(self, client: bytes) -> None:
        create = getattr(self._transport, "create_solving", None)
        if self._container is not None or not callable(create) or type(client) is not bytes or not client or len(client) > _CELL_CAP:
            raise P7SolvingDockerError()
        self._seed_client(client)
        value = await create(image_digest=self._image, workspace=self._workspace, broker_private_dir=self._private, broker_model_socket=self._socket, control=_control())
        if type(value) is not str or _ID.fullmatch(value) is None:
            raise P7SolvingDockerError()
        self._container = value

    def _seed_client(self, client: bytes) -> None:
        try:
            root = os.open(self._workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if os.listdir(root):
                    raise ValueError
                fd = os.open("p7_client.py", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
                try:
                    if os.write(fd, client) != len(client):
                        raise ValueError
                    os.fchown(fd, 65534, 65534)
                finally:
                    os.close(fd)
            finally:
                os.close(root)
        except (OSError, ValueError):
            raise P7SolvingDockerError() from None

    async def execute_cell(self, code: str) -> dict[str, object]:
        execute = getattr(self._transport, "execute_solving", None)
        if self._container is None or self._cleaned or not callable(execute) or self._count >= _CELL_LIMIT or type(code) is not str or not code or len(code.encode()) > _CELL_CAP:
            raise P7SolvingDockerError()
        value = await execute(self._container, code, _control())
        if type(value) is not dict or set(value) != {"cell_count", "output", "is_error"} or value.get("cell_count") != self._count + 1 or type(value.get("output")) is not str or type(value.get("is_error")) is not bool or len(value["output"].encode()) > _OUTPUT_CAP:
            raise P7SolvingDockerError()
        self._count += 1
        return value

    async def cleanup(self) -> None:
        if self._cleaned:
            return
        remove, absent = getattr(self._transport, "remove_solving", None), getattr(self._transport, "assert_solving_absent", None)
        if self._container is None or not callable(remove) or not callable(absent):
            raise P7SolvingDockerError()
        async def destroy() -> None:
            await remove(self._container, _control())
            await absent(self._container, _control())
            self._cleaned = True
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


__all__ = ("P7SolvingDockerError", "P7SolvingDockerTransport", "P7SolvingDockerWorker")
