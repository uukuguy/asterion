"""Closed Docker CLI transport for the Prime coding worker.

The Docker executable, daemon socket, and seccomp profile are operator-owned.
Nothing supplied by an application request is permitted to alter a command.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from time import monotonic
from typing import Mapping, Protocol, cast

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerEngineTransport,
    DockerLauncherChannel,
    DockerWorkerLauncherSelfCheck,
    _DockerWorkerSpecification,
    _LifecycleCallControl,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError,
    RestrictedWorkerLease,
)


_ENVIRONMENT = ("HOME=/workspace", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1")
_ENTRYPOINT = "/usr/local/bin/prime-ipython-coding"
_TMPFS = "/workspace:rw,nodev,noexec,nosuid,size=67108864"
_OUTPUT_CAP = 65536
_CONTAINER_ID = re.compile(r"prime-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class DockerCliResult:
    """Bounded subprocess result, deliberately without process details."""

    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


class DockerCliRunner(Protocol):
    """The sole test seam for direct, non-shell Docker invocations."""

    async def run(
        self, *, argv: tuple[str, ...], env: dict[str, str], timeout: float,
        max_output_bytes: int,
    ) -> DockerCliResult: ...


class DockerCliAttachProcess(Protocol):
    stdin: asyncio.StreamWriter | None
    stdout: asyncio.StreamReader | None
    @property
    def returncode(self) -> int | None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


class DockerCliAttachRunner(Protocol):
    async def open(
        self, *, argv: tuple[str, ...], env: dict[str, str]
    ) -> DockerCliAttachProcess: ...


class _ProductionRunner:
    async def run(
        self, *, argv: tuple[str, ...], env: dict[str, str], timeout: float,
        max_output_bytes: int,
    ) -> DockerCliResult:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env,
        )
        if process.stdout is None or process.stderr is None:
            await self._stop_and_reap(process, ())
            raise RestrictedWorkerError("restricted worker value is invalid")
        stdout = bytearray()
        stderr = bytearray()
        total = 0

        async def read_pipe(pipe: asyncio.StreamReader, destination: bytearray) -> None:
            nonlocal total
            while True:
                chunk = await pipe.read(1)
                if not chunk:
                    return
                if type(chunk) is not bytes or len(chunk) != 1 or total >= max_output_bytes:
                    raise _DockerCliOutputLimit
                destination.extend(chunk)
                total += 1

        readers = (
            asyncio.create_task(read_pipe(process.stdout, stdout)),
            asyncio.create_task(read_pipe(process.stderr, stderr)),
        )
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*readers)
                await process.wait()
        except asyncio.CancelledError:
            await self._stop_and_reap(process, readers)
            raise
        except BaseException:
            await self._stop_and_reap(process, readers)
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        return DockerCliResult(process.returncode or 0, bytes(stdout), bytes(stderr))

    @staticmethod
    async def _stop_and_reap(
        process: asyncio.subprocess.Process,
        readers: tuple[asyncio.Task[None], ...],
    ) -> None:
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        if process.returncode is None:
            process.kill()
        reaping = asyncio.create_task(process.wait())
        while not reaping.done():
            try:
                await asyncio.shield(reaping)
            except asyncio.CancelledError:
                continue
        try:
            reaping.result()
        except BaseException:
            pass


class _DockerCliOutputLimit(Exception):
    pass


class _ProductionAttachRunner:
    async def open(
        self, *, argv: tuple[str, ...], env: dict[str, str]
    ) -> DockerCliAttachProcess:
        return cast(DockerCliAttachProcess, await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env,
        ))


class _DockerCliLauncherChannel(DockerLauncherChannel):
    """One private interactive attach process; never expose its stream."""

    _RELEASE = b'{"release":true}\n'

    def __init__(self, process: DockerCliAttachProcess) -> None:
        self._process = process
        self._read = False
        self._released = False
        self._result_read = False
        self._closed = False

    async def self_check(self, *, control: _LifecycleCallControl) -> DockerWorkerLauncherSelfCheck:
        if self._read or self._closed or self._process.stdout is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._read = True
        raw = await self._read_bounded(control)
        return DockerCliEngineTransport._parse_self_check_line(raw)

    async def release(self, *, control: _LifecycleCallControl) -> None:
        if self._released or self._closed or self._process.stdin is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._released = True
        if control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        self._process.stdin.write(self._RELEASE)
        async with asyncio.timeout_at(control.deadline):
            await self._process.stdin.drain()
        if control.cancelled():
            raise asyncio.CancelledError

    async def completed_result(self, *, control: _LifecycleCallControl) -> bytes:
        if (
            not self._read
            or not self._released
            or self._result_read
            or self._closed
            or self._process.stdout is None
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._result_read = True
        raw = await self._read_bounded(control)
        return DockerCliEngineTransport._parse_completed_result_line(raw)

    async def close(self, *, control: _LifecycleCallControl) -> None:
        if self._closed:
            return
        self._closed = True
        cancelled = control.cancelled() or monotonic() >= control.deadline
        if self._process.stdin is not None:
            self._process.stdin.close()
        if self._process.returncode is None:
            self._process.kill()
        reaping = asyncio.create_task(self._process.wait())
        reap_error: BaseException | None = None
        while not reaping.done():
            try:
                await asyncio.shield(reaping)
            except asyncio.CancelledError:
                cancelled = True
            except BaseException as error:
                reap_error = error
        try:
            reaping.result()
        except BaseException as error:
            reap_error = error
        if cancelled or control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        if reap_error is not None:
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def _read_bounded(self, control: _LifecycleCallControl) -> bytes:
        if control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        async with asyncio.timeout_at(control.deadline):
            raw = await self._process.stdout.read(1025)  # type: ignore[union-attr]
        if control.cancelled() or type(raw) is not bytes or not raw or len(raw) > 1024:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return raw


class DockerCliEngineTransport(DockerEngineTransport):
    """The exact DockerEngineTransport lifecycle, mapped to fixed CLI argv."""

    def __init__(
        self, *, docker_executable: str, socket_path: str, seccomp_profile: str,
        runner: DockerCliRunner | None = None,
        attach_runner: DockerCliAttachRunner | None = None,
    ) -> None:
        if not all(type(value) is str and value.startswith("/") for value in (docker_executable, socket_path, seccomp_profile)):
            raise RestrictedWorkerError("restricted worker value is invalid")
        if socket_path.startswith("//") or "\x00" in socket_path or "\x00" in docker_executable or "\x00" in seccomp_profile:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._prefix = (docker_executable, "--host", "unix://" + socket_path)
        self._seccomp_profile = seccomp_profile
        self._runner = runner or _ProductionRunner()
        self._attach_runner = attach_runner or _ProductionAttachRunner()
        self._specifications: dict[str, _DockerWorkerSpecification] = {}

    async def create(self, specification: _DockerWorkerSpecification, *, control: _LifecycleCallControl) -> str:
        self._valid_specification(specification)
        await self._preflight(control)
        argv = self._prefix + (
            "create", "--name", specification.container_id, "--pull=never", "--network", "none",
            "--read-only", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--security-opt", "seccomp=" + self._seccomp_profile,
            "--tmpfs", _TMPFS, "--env", _ENVIRONMENT[0], "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2],
            "--pid", "private", "--ipc", "private", "--uts", "private", "--pids-limit", "256",
            "--memory", "536870912", "--memory-swap", "536870912", "--cpus", "1", "--restart", "no",
            "--entrypoint", _ENTRYPOINT, specification.image_digest,
        )
        result = await self._call(argv, control)
        if result.stdout != (specification.container_id + "\n").encode():
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._specifications[specification.container_id] = specification
        return specification.container_id

    async def inspect(self, container_id: str, *, control: _LifecycleCallControl) -> Mapping[str, object]:
        specification = self._specification(container_id)
        result = await self._call(self._prefix + ("container", "inspect", container_id), control)
        return self._parse_inspection(result.stdout, specification)

    async def start(self, container_id: str, *, control: _LifecycleCallControl) -> RestrictedWorkerLease:
        specification = self._specification(container_id)
        result = await self._call(self._prefix + ("container", "start", container_id), control)
        if result.stdout not in (b"", (container_id + "\n").encode()) or result.stderr:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return RestrictedWorkerLease(container_id, specification.role_id, specification.run_id, specification.challenge_digest, specification.workload_digest)

    async def open_launcher_channel(self, container_id: str, *, control: _LifecycleCallControl) -> DockerLauncherChannel:
        self._specification(container_id)
        if control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        process = await self._attach_runner.open(
            argv=self._prefix + ("container", "attach", "--sig-proxy=false", container_id), env={}
        )
        if process.stdin is None or process.stdout is None:
            await _DockerCliLauncherChannel(process).close(control=control)
            raise RestrictedWorkerError("restricted worker value is invalid")
        if control.cancelled():
            await _DockerCliLauncherChannel(process).close(control=control)
            raise asyncio.CancelledError
        return _DockerCliLauncherChannel(process)

    async def force_remove(self, container_id: str, *, control: _LifecycleCallControl) -> None:
        self._specification(container_id)
        result = await self._call(self._prefix + ("container", "rm", "--force", container_id), control)
        if result.stdout not in (b"", (container_id + "\n").encode()) or result.stderr:
            raise RestrictedWorkerError("restricted worker value is invalid")

    async def assert_absent(self, container_id: str, *, control: _LifecycleCallControl) -> None:
        self._specification(container_id)
        result = await self._call_raw(self._prefix + ("container", "inspect", "--format", "{{.Id}}", container_id), control)
        absent_errors = {
            ("Error: No such object: " + container_id + "\n").encode(),
            ("Error: No such container: " + container_id + "\n").encode(),
            ("No such container: " + container_id).encode(),
        }
        if result.returncode != 1 or result.stdout or result.stderr not in absent_errors:
            raise RestrictedWorkerError("restricted worker value is invalid")
        del self._specifications[container_id]

    async def _preflight(self, control: _LifecycleCallControl) -> None:
        for argv in (
            self._prefix + ("version", "--format", "{{json .Server}}"),
            self._prefix + ("info", "--format", "{{json .}}"),
        ):
            result = await self._call(argv, control)
            if not isinstance(self._json(result.stdout), dict):
                raise RestrictedWorkerError("restricted worker value is invalid")

    async def _call(self, argv: tuple[str, ...], control: _LifecycleCallControl) -> DockerCliResult:
        result = await self._call_raw(argv, control)
        if result.returncode != 0:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return result

    async def _call_raw(self, argv: tuple[str, ...], control: _LifecycleCallControl) -> DockerCliResult:
        if control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        result = await self._runner.run(argv=argv, env={}, timeout=control.deadline - monotonic(), max_output_bytes=_OUTPUT_CAP)
        if type(result.returncode) is not int or type(result.stdout) is not bytes or type(result.stderr) is not bytes or len(result.stdout) + len(result.stderr) > _OUTPUT_CAP:
            raise RestrictedWorkerError("restricted worker value is invalid")
        if control.cancelled():
            raise asyncio.CancelledError
        return result

    def _specification(self, container_id: str) -> _DockerWorkerSpecification:
        if type(container_id) is not str or container_id not in self._specifications:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return self._specifications[container_id]

    @staticmethod
    def _valid_specification(specification: _DockerWorkerSpecification) -> None:
        if (
            type(specification) is not _DockerWorkerSpecification
            or specification.role_id != "prime.ipython-coding"
            or specification.launcher_id != "prime-ipython-coding"
            or _CONTAINER_ID.fullmatch(specification.container_id) is None
            or _DIGEST.fullmatch(specification.image_digest) is None
            or _DIGEST.fullmatch(specification.workload_digest) is None
            or type(specification.max_runtime_seconds) is not int
            or not 0 < specification.max_runtime_seconds <= 300
            or type(specification.max_output_bytes) is not int
            or not 0 < specification.max_output_bytes <= _OUTPUT_CAP
            or specification.user_id != 65534
            or specification.group_id != 65534
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")

    @staticmethod
    def _json(raw: bytes) -> object:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    def _parse_inspection(self, raw: bytes, specification: _DockerWorkerSpecification) -> Mapping[str, object]:
        value = self._json(raw)
        try:
            if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
                raise ValueError
            item = value[0]
            if set(item) != {"Id", "Image", "RepoDigests", "Config", "HostConfig", "Mounts", "State"} or item["Id"] != specification.container_id or item["Image"] != specification.image_digest or item["RepoDigests"] != [] or item["Mounts"] != [] or item["State"] not in ({"Running": False}, {"Running": True}):
                raise ValueError
            config, host = item["Config"], item["HostConfig"]
            if type(config) is not dict or set(config) != {"User", "Env", "Entrypoint", "Labels"} or config["User"] != "65534:65534" or config["Env"] != list(_ENVIRONMENT) or config["Entrypoint"] != [_ENTRYPOINT] or type(config["Labels"]) is not dict or any("run" in key.lower() or "challenge" in key.lower() for key in config["Labels"]):
                raise ValueError
            expected = {"NetworkMode": "none", "PortBindings": None, "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true", "seccomp=" + self._seccomp_profile], "Binds": None, "VolumesFrom": None, "Tmpfs": {"/workspace": _TMPFS.removeprefix("/workspace:")}, "PidsLimit": 256, "Memory": 536870912, "MemorySwap": 536870912, "NanoCpus": 1000000000, "PidMode": "private", "IpcMode": "private", "UTSMode": "private", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}}
            if type(host) is not dict or host != expected:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        return {"image_id": specification.image_digest, "repo_digests": (), "network_mode": "none", "ports": (), "readonly_rootfs": True, "privileged": False, "cap_add": (), "cap_drop": ("ALL",), "security_opt": ("no-new-privileges", "seccomp=prime-ipython-coding"), "user": "65534:65534", "devices": (), "mounts": (), "binds": (), "volumes": (), "tmpfs": {"/workspace": {"size_bytes": 67108864, "options": ("nodev", "noexec", "nosuid")}}, "env": _ENVIRONMENT, "pids_limit": 256, "memory": 536870912, "memory_swap": 536870912, "nano_cpus": 1000000000, "pid_namespace": "private", "ipc_namespace": "private", "uts_namespace": "private"}

    @staticmethod
    def _parse_self_check_line(raw: bytes) -> DockerWorkerLauncherSelfCheck:
        if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise RestrictedWorkerError("restricted worker value is invalid")
        raw = raw[:-1]
        if not raw:
            raise RestrictedWorkerError("restricted worker value is invalid")
        value = DockerCliEngineTransport._json(raw)
        fields = {"nonloopback_network_absent", "root_read_only", "workspace_only_writable", "credentials_absent", "effective_capabilities", "no_new_privileges", "seccomp_mode", "effective_user_id"}
        if type(value) is not dict or set(value) != fields:
            raise RestrictedWorkerError("restricted worker value is invalid")
        if json.dumps(value, separators=(",", ":"), sort_keys=True).encode() != raw:
            raise RestrictedWorkerError("restricted worker value is invalid")
        try:
            return DockerWorkerLauncherSelfCheck(**value)
        except (TypeError, RestrictedWorkerError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    @staticmethod
    def _parse_completed_result_line(raw: bytes) -> bytes:
        if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise RestrictedWorkerError("restricted worker value is invalid")
        body = raw[:-1]
        if not body:
            raise RestrictedWorkerError("restricted worker value is invalid")
        value = DockerCliEngineTransport._json(body)
        if (
            type(value) is not dict
            or value != {"terminal": "completed"}
            or json.dumps(value, separators=(",", ":"), sort_keys=True).encode() != body
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return body
