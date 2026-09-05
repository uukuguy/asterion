"""Closed Docker CLI transport for the Prime coding worker.

The Docker executable, daemon socket, and seccomp profile are operator-owned.
Nothing supplied by an application request is permitted to alter a command.
"""

from __future__ import annotations

import asyncio
import fcntl
import io
import json
import os
import re
import stat
import sys
import tarfile
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from typing import Mapping, Protocol, cast

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerEngineTransport,
    DockerLauncherChannel,
    DockerWorkerCompletion,
    DockerWorkerLauncherSelfCheck,
    DockerWorkerModelRequest,
    DockerWorkerModelResponse,
    _DockerWorkerSpecification,
    _LifecycleCallControl,
)
from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
    PrimeImageInputLockError,
    validate_image_platform_descriptor,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError,
    RestrictedWorkerLease,
)


_ENVIRONMENT = ("HOME=/workspace", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1")
_ENTRYPOINT = "/usr/local/bin/prime-ipython-coding.py"
_TMPFS = "/workspace:rw,nodev,noexec,nosuid,size=67108864"
_OUTPUT_CAP = 65536
_SECCOMP_PROFILE_CAP = 65536
# Inspect encodes SecurityOpt as a JSON string.  A canonical profile may be
# entirely escaped (six bytes per source byte), so this is intentionally not
# the normal Docker output limit.
_INSPECT_OUTPUT_CAP = 6 * _SECCOMP_PROFILE_CAP + 4096
_SNAPSHOT_CAP = 65536
_CONTAINER_ID = re.compile(r"prime-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NORMALIZED_RESULT = {"fixture": "passed", "oracle": "passed", "tool": "ipython"}
# Do not accept Docker's evolving full inspect document.  This is a fixed,
# operator-owned JSON projection; the parser below rejects anything outside it.
_INSPECT_PROJECTION = (
    '[{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"User":{{json .Config.User}},"Env":{{json .Config.Env}},'
    '"Entrypoint":{{json .Config.Entrypoint}},"Labels":{{json .Config.Labels}},'
    '"NetworkMode":{{json .HostConfig.NetworkMode}},"PortBindings":{{json .HostConfig.PortBindings}},'
    '"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},"Privileged":{{json .HostConfig.Privileged}},'
    '"CapAdd":{{json .HostConfig.CapAdd}},"CapDrop":{{json .HostConfig.CapDrop}},'
    '"SecurityOpt":{{json .HostConfig.SecurityOpt}},"Binds":{{json .HostConfig.Binds}},'
    '"VolumesFrom":{{json .HostConfig.VolumesFrom}},"Tmpfs":{{json .HostConfig.Tmpfs}},'
    '"PidsLimit":{{json .HostConfig.PidsLimit}},"Memory":{{json .HostConfig.Memory}},'
    '"MemorySwap":{{json .HostConfig.MemorySwap}},"NanoCpus":{{json .HostConfig.NanoCpus}},'
    '"PidMode":{{json .HostConfig.PidMode}},"IpcMode":{{json .HostConfig.IpcMode}},'
    '"UTSMode":{{json .HostConfig.UTSMode}},"RestartPolicy":{{json .HostConfig.RestartPolicy}},'
    '"Mounts":{{json .Mounts}},"Running":{{json .State.Running}}}]'
)


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
        max_output_bytes: int, pass_fds: tuple[int, ...],
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
        self, *, argv: tuple[str, ...], env: dict[str, str], pass_fds: tuple[int, ...]
    ) -> DockerCliAttachProcess: ...


class _ProductionRunner:
    async def run(
        self, *, argv: tuple[str, ...], env: dict[str, str], timeout: float,
        max_output_bytes: int, pass_fds: tuple[int, ...],
    ) -> DockerCliResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, pass_fds=pass_fds,
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
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
        self, *, argv: tuple[str, ...], env: dict[str, str], pass_fds: tuple[int, ...]
    ) -> DockerCliAttachProcess:
        return cast(DockerCliAttachProcess, await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env, pass_fds=pass_fds,
        ))


class _DockerCliLauncherChannel(DockerLauncherChannel):
    """One private interactive attach process; never expose its stream."""

    _CONTROL = (
        b'{"control":"begin","prime_sdk_session":"prime-agent@0.7.1","workload_digest":"'
        + PRIME_IPYTHON_CODING_WORKLOAD_DIGEST.encode()
        + b'"}\n'
    )

    def __init__(self, process: DockerCliAttachProcess) -> None:
        self._process = process
        self._read = False
        self._released = False
        self._result_read = False
        self._model_request_read = False
        self._model_response_sent = False
        self._pending = b""
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
        self._process.stdin.write(self._CONTROL)
        async with asyncio.timeout_at(control.deadline):
            await self._process.stdin.drain()
        if control.cancelled():
            raise asyncio.CancelledError

    async def model_request(
        self, *, control: _LifecycleCallControl
    ) -> DockerWorkerModelRequest:
        if not self._released or self._model_request_read or self._closed:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._model_request_read = True
        return DockerCliEngineTransport._parse_model_request_line(
            await self._read_bounded(control)
        )

    async def model_response(
        self, response: DockerWorkerModelResponse, *, control: _LifecycleCallControl
    ) -> None:
        if (
            not self._model_request_read
            or self._model_response_sent
            or self._closed
            or self._process.stdin is None
            or type(response) is not DockerWorkerModelResponse
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        raw = json.dumps(
            {"cell": response.cell, "kind": "model-response", "tool": "ipython",
             "workload_digest": response.workload_digest},
            separators=(",", ":"), sort_keys=True,
        ).encode() + b"\n"
        if len(raw) > _OUTPUT_CAP or control.cancelled() or monotonic() >= control.deadline:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._model_response_sent = True
        self._process.stdin.write(raw)
        async with asyncio.timeout_at(control.deadline):
            await self._process.stdin.drain()

    async def completed_result(
        self, *, control: _LifecycleCallControl
    ) -> DockerWorkerCompletion:
        if (
            not self._read
            or not self._released
            or not self._model_response_sent
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
        raw = self._pending
        self._pending = b""
        while b"\n" not in raw and len(raw) <= 1024:
            async with asyncio.timeout_at(control.deadline):
                chunk = await self._process.stdout.read(1025)  # type: ignore[union-attr]
            if type(chunk) is not bytes or not chunk:
                break
            raw += chunk
        newline = raw.find(b"\n")
        if newline >= 0:
            frame, self._pending = raw[:newline + 1], raw[newline + 1:]
            if self._pending and b"\n" not in self._pending:
                raise RestrictedWorkerError("restricted worker value is invalid")
        else:
            frame = raw
        if control.cancelled() or type(frame) is not bytes or not frame or len(frame) > 1024:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return frame


class DockerCliEngineTransport(DockerEngineTransport):
    """The exact DockerEngineTransport lifecycle, mapped to fixed CLI argv."""

    def __init__(
        self, *, docker_executable: str, socket_path: str, seccomp_profile_fd: int,
        platform: ImagePlatformDescriptor,
        runner: DockerCliRunner | None = None,
        attach_runner: DockerCliAttachRunner | None = None,
    ) -> None:
        if not all(type(value) is str and value.startswith("/") for value in (docker_executable, socket_path)):
            raise RestrictedWorkerError("restricted worker value is invalid")
        if socket_path.startswith("//") or "\x00" in socket_path or "\x00" in docker_executable:
            raise RestrictedWorkerError("restricted worker value is invalid")
        try:
            platform = validate_image_platform_descriptor(platform)
            if sys.platform != "linux" or os.name != "posix" or type(seccomp_profile_fd) is not int:
                raise ValueError
            required_seals = (
                fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
            )
            metadata = os.fstat(seccomp_profile_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not 0 < metadata.st_size <= _SECCOMP_PROFILE_CAP
                or not fcntl.fcntl(seccomp_profile_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
                or fcntl.fcntl(seccomp_profile_fd, fcntl.F_GET_SEALS) != required_seals
            ):
                raise ValueError
            owned_seccomp_profile_fd = os.dup(seccomp_profile_fd)
            os.set_inheritable(owned_seccomp_profile_fd, False)
            metadata = os.fstat(owned_seccomp_profile_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not 0 < metadata.st_size <= _SECCOMP_PROFILE_CAP
                or not fcntl.fcntl(owned_seccomp_profile_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
                or fcntl.fcntl(owned_seccomp_profile_fd, fcntl.F_GET_SEALS) != required_seals
            ):
                raise ValueError
            raw_profile = os.pread(owned_seccomp_profile_fd, metadata.st_size, 0)
            profile = json.loads(raw_profile.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError))
            canonical_profile = json.dumps(
                profile, separators=(",", ":"), sort_keys=True, ensure_ascii=False,
            ).encode("utf-8")
            if type(profile) is not dict or raw_profile != canonical_profile:
                raise ValueError
        except (AttributeError, OSError, RecursionError, UnicodeDecodeError, json.JSONDecodeError, PrimeImageInputLockError, ValueError):
            if "owned_seccomp_profile_fd" in locals():
                try:
                    os.close(owned_seccomp_profile_fd)
                except OSError:
                    pass
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        self._prefix = (docker_executable, "--host", "unix://" + socket_path)
        self._seccomp_profile_fd: int | None = owned_seccomp_profile_fd
        self._seccomp_profile = canonical_profile.decode("utf-8")
        self._platform = platform
        self._runner = runner or _ProductionRunner()
        self._attach_runner = attach_runner or _ProductionAttachRunner()
        self._specifications: dict[str, _DockerWorkerSpecification] = {}

    def close(self) -> None:
        """Release the one-create seccomp descriptor without touching caller state."""
        fd, self._seccomp_profile_fd = self._seccomp_profile_fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    async def create(self, specification: _DockerWorkerSpecification, *, control: _LifecycleCallControl) -> str:
        self._valid_specification(specification)
        if specification.container_id in self._specifications:
            raise RestrictedWorkerError("restricted worker value is invalid")
        # Keep the requested name only long enough to compensate an uncertain
        # create; successful creation is immediately re-keyed by daemon ID.
        self._specifications[specification.container_id] = specification
        fd = self._seccomp_profile_fd
        if type(fd) is not int:
            raise RestrictedWorkerError("restricted worker value is invalid")
        argv = self._prefix + (
            "create", "--name", specification.container_id, "--pull=never", "--platform",
            "/".join(part for part in (self._platform.os, self._platform.architecture, self._platform.variant) if part is not None), "--network", "none",
            "--read-only", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--security-opt", "seccomp=/proc/self/fd/" + str(fd),
            "--tmpfs", _TMPFS, "--env", _ENVIRONMENT[0], "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2],
            "--pid", "private", "--ipc", "private", "--uts", "private", "--pids-limit", "256",
            "--memory", "536870912", "--memory-swap", "536870912", "--cpus", "1", "--restart", "no",
            "--entrypoint", _ENTRYPOINT, specification.image_digest,
        )
        try:
            await self._preflight(control)
            result = await self._call(argv, control, pass_fds=(fd,))
        finally:
            self.close()
        daemon_id = self._parse_daemon_id(result.stdout)
        if daemon_id in self._specifications:
            raise RestrictedWorkerError("restricted worker value is invalid")
        # Docker create prints the daemon's opaque ID, never the requested name.
        del self._specifications[specification.container_id]
        self._specifications[daemon_id] = specification
        return daemon_id

    async def inspect(self, container_id: str, *, control: _LifecycleCallControl) -> Mapping[str, object]:
        specification = self._specification(container_id)
        result = await self._call(
            self._prefix + ("container", "inspect", "--format", _INSPECT_PROJECTION, container_id),
            control, max_output_bytes=_INSPECT_OUTPUT_CAP,
        )
        return self._parse_inspection(result.stdout, container_id, specification)

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
            argv=self._prefix + ("container", "attach", "--sig-proxy=false", container_id),
            env={}, pass_fds=(),
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

    async def snapshot_solution(self, container_id: str, *, control: _LifecycleCallControl) -> bytes:
        """Return the sole host-private workspace snapshot while the worker lives."""
        self._specification(container_id)
        pause_attempted = True
        paused = False
        try:
            await self._call(self._prefix + ("container", "pause", container_id), control)
            paused = True
            archive = await self._call(
                self._prefix + ("container", "cp", container_id + ":/workspace/solution.py", "-"), control
            )
            return self._parse_solution_archive(archive.stdout)
        finally:
            # The original lease may have been cancelled while copying.  Cleanup
            # is a separate bounded operator action and must still run.
            if paused:
                await self._resume_or_destroy(container_id)
            elif pause_attempted:
                await self._destroy_after_uncertain_pause(container_id)

    async def _resume_or_destroy(self, container_id: str) -> None:
        control = _LifecycleCallControl(monotonic() + 30, None)
        try:
            await self._shield_cleanup(
                self._call(self._prefix + ("container", "unpause", container_id), control)
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            await self._destroy_after_uncertain_pause(container_id)
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def _destroy_after_uncertain_pause(self, container_id: str) -> None:
        control = _LifecycleCallControl(monotonic() + 30, None)
        try:
            await self._shield_cleanup(self.force_remove(container_id, control=control))
            await self._shield_cleanup(self.assert_absent(container_id, control=control))
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    @staticmethod
    async def _shield_cleanup(awaitable: object) -> object:
        task = asyncio.create_task(awaitable)  # type: ignore[arg-type]
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _preflight(self, control: _LifecycleCallControl) -> None:
        for argv in (
            self._prefix + ("version", "--format", "{{json .Server}}"),
            self._prefix + ("info", "--format", "{{json .}}"),
        ):
            result = await self._call(argv, control)
            if not isinstance(self._json(result.stdout), dict):
                raise RestrictedWorkerError("restricted worker value is invalid")

    async def _call(
        self, argv: tuple[str, ...], control: _LifecycleCallControl, *,
        max_output_bytes: int = _OUTPUT_CAP, pass_fds: tuple[int, ...] = (),
    ) -> DockerCliResult:
        result = await self._call_raw(
            argv, control, max_output_bytes=max_output_bytes, pass_fds=pass_fds,
        )
        if result.returncode != 0:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return result

    async def _call_raw(
        self, argv: tuple[str, ...], control: _LifecycleCallControl, *,
        max_output_bytes: int = _OUTPUT_CAP, pass_fds: tuple[int, ...] = (),
    ) -> DockerCliResult:
        if control.cancelled() or monotonic() >= control.deadline:
            raise asyncio.CancelledError
        result = await self._runner.run(
            argv=argv, env={}, timeout=control.deadline - monotonic(),
            max_output_bytes=max_output_bytes, pass_fds=pass_fds,
        )
        if type(result.returncode) is not int or type(result.stdout) is not bytes or type(result.stderr) is not bytes or len(result.stdout) + len(result.stderr) > max_output_bytes:
            raise RestrictedWorkerError("restricted worker value is invalid")
        if control.cancelled():
            raise asyncio.CancelledError
        return result

    def _specification(self, container_id: str) -> _DockerWorkerSpecification:
        if type(container_id) is not str or container_id not in self._specifications:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return self._specifications[container_id]

    @staticmethod
    def _parse_daemon_id(raw: bytes) -> str:
        try:
            value = raw.decode("ascii")
        except UnicodeDecodeError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        if not re.fullmatch(r"[0-9a-f]{64}\n", value):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return value[:-1]

    @staticmethod
    def _parse_solution_archive(raw: bytes) -> bytes:
        if (
            type(raw) is not bytes
            or not raw
            or len(raw) > _SNAPSHOT_CAP
            or len(raw) % tarfile.BLOCKSIZE != 0
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
                members = archive.getmembers()
                if len(members) != 1:
                    raise ValueError
                member = members[0]
                if (
                    member.name != "solution.py"
                    or not member.isreg()
                    or member.pax_headers
                    or member.size < 0
                    or member.size > _SNAPSHOT_CAP
                ):
                    raise ValueError
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError
                data = source.read(_SNAPSHOT_CAP + 1)
                if len(data) != member.size or len(data) > _SNAPSHOT_CAP:
                    raise ValueError
                data_end = member.offset_data + member.size
                padded_end = (data_end + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE * tarfile.BLOCKSIZE
                if (
                    len(raw) < padded_end + 2 * tarfile.BLOCKSIZE
                    or any(raw[data_end:padded_end])
                    or any(raw[padded_end:])
                ):
                    raise ValueError
                return data
        except (tarfile.TarError, OSError, ValueError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None

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

    def _parse_inspection(
        self, raw: bytes, container_id: str, specification: _DockerWorkerSpecification
    ) -> Mapping[str, object]:
        value = self._json(raw)
        try:
            if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
                raise ValueError
            item = value[0]
            fields = {
                "Id", "Image", "User", "Env", "Entrypoint", "Labels", "NetworkMode",
                "PortBindings", "ReadonlyRootfs", "Privileged", "CapAdd", "CapDrop",
                "SecurityOpt", "Binds", "VolumesFrom", "Tmpfs", "PidsLimit", "Memory",
                "MemorySwap", "NanoCpus", "PidMode", "IpcMode", "UTSMode", "RestartPolicy",
                "Mounts", "Running",
            }
            if set(item) != fields or item["Id"] != container_id or item["Image"] != specification.image_digest or item["Mounts"] != [] or type(item["Running"]) is not bool:
                raise ValueError
            if item["User"] != "65534:65534" or item["Env"] != list(_ENVIRONMENT) or item["Entrypoint"] != [_ENTRYPOINT] or type(item["Labels"]) is not dict or any("run" in key.lower() or "challenge" in key.lower() for key in item["Labels"]):
                raise ValueError
            expected = {"NetworkMode": "none", "PortBindings": None, "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true", "seccomp=" + self._seccomp_profile], "Binds": None, "VolumesFrom": None, "Tmpfs": {"/workspace": _TMPFS.removeprefix("/workspace:")}, "PidsLimit": 256, "Memory": 536870912, "MemorySwap": 536870912, "NanoCpus": 1000000000, "PidMode": "private", "IpcMode": "private", "UTSMode": "private", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}}
            if any(item[name] != expected[name] for name in expected):
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
    def _parse_model_request_line(raw: bytes) -> DockerWorkerModelRequest:
        if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise RestrictedWorkerError("restricted worker value is invalid")
        body = raw[:-1]
        value = DockerCliEngineTransport._json(body)
        if (
            type(value) is not dict
            or set(value) != {"kind", "prime_sdk_session", "tools", "workload_digest"}
            or value["kind"] != "model-request"
            or value["prime_sdk_session"] != "prime-agent@0.7.1"
            or value["tools"] != ["ipython"]
            or json.dumps(value, separators=(",", ":"), sort_keys=True).encode() != body
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        try:
            return DockerWorkerModelRequest(value["workload_digest"])
        except RestrictedWorkerError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    @staticmethod
    def _parse_completed_result_line(raw: bytes) -> DockerWorkerCompletion:
        if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise RestrictedWorkerError("restricted worker value is invalid")
        body = raw[:-1]
        if not body:
            raise RestrictedWorkerError("restricted worker value is invalid")
        value = DockerCliEngineTransport._json(body)
        fields = {
            "host_model_operations", "model_caused_ipython_mutation",
            "oracle_eventually_passed", "oracle_initially_failed", "result",
            "result_digest", "terminal", "tools", "workload_digest",
        }
        if (
            type(value) is not dict
            or set(value) != fields
            or value["terminal"] != "completed"
            or type(value["result"]) is not dict
            or value["result"] != _NORMALIZED_RESULT
            or value["host_model_operations"] != 1
            or value["model_caused_ipython_mutation"] is not True
            or value["oracle_initially_failed"] is not True
            or value["oracle_eventually_passed"] is not True
            or value["tools"] != ["ipython"]
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        result_bytes = json.dumps(
            value["result"], separators=(",", ":"), sort_keys=True
        ).encode()
        if (
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode() != body
            or value["result_digest"] != "sha256:" + sha256(result_bytes).hexdigest()
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        try:
            return DockerWorkerCompletion(value["workload_digest"], result_bytes)
        except RestrictedWorkerError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
