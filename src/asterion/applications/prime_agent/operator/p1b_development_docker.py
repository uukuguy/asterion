"""Closed Docker attach transport for the two-cell P1-B development proof.

This development-only surface has its own fixed profile.  It deliberately does
not widen P1-A's one-cell worker contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
import json
import tarfile
from time import monotonic
from typing import Protocol

from .docker_cli import (
    DockerCliAttachProcess, DockerCliAttachRunner, DockerCliEngineTransport,
    DockerCliRunner, _CLEARED_BASE_IMAGE_ENVIRONMENT, _ENVIRONMENT, _TMPFS,
)
from .docker_worker import DockerWorkerLauncherSelfCheck, _LifecycleCallControl
from .image_input_lock import ImagePlatformDescriptor
from .p1b_workload import PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST
from asterion.services.restricted_worker import RestrictedWorkerError

_ENTRYPOINT = "/usr/local/bin/prime-p1b-persistent-worker.py"
_PROTOCOL = "prime-p1-b-development-worker/v1"
_FRAME_CAP = 64 * 1024
_DIGEST = PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST
_FIXTURE = b"p1b continuity fixture\n"


@dataclass(frozen=True)
class _P1BSpec:
    container_id: str
    image_digest: str
    role_id: str
    run_id: str
    challenge_digest: str
    workload_digest: str


class P1BDockerCliTransport(DockerCliEngineTransport):
    """Fixed P1-B CLI profile; no caller can supply Docker create arguments."""
    def __init__(self, *, docker_executable: str, socket_path: str, seccomp_profile_fd: int,
                 platform: ImagePlatformDescriptor, runner: DockerCliRunner | None = None,
                 attach_runner: DockerCliAttachRunner | None = None) -> None:
        super().__init__(docker_executable=docker_executable, socket_path=socket_path,
                         seccomp_profile_fd=seccomp_profile_fd, platform=platform,
                         runner=runner, attach_runner=attach_runner)

    async def create(self, *, image_digest: str, run_id: str, session_id: str,
                     control: _LifecycleCallControl) -> str:
        if (type(image_digest) is not str or len(image_digest) != 71 or not image_digest.startswith("sha256:")
                or type(run_id) is not str or not run_id or type(session_id) is not str or not session_id):
            raise RestrictedWorkerError("restricted worker value is invalid")
        requested = "prime-p1b-" + __import__("secrets").token_hex(16)
        fd, self._seccomp_profile_fd = self._seccomp_profile_fd, None  # type: ignore[attr-defined]
        if type(fd) is not int: raise RestrictedWorkerError("restricted worker value is invalid")
        argv = self._prefix + (  # type: ignore[attr-defined]
            "create", "--name", requested, "--pull=never", "--platform",
            "/".join(x for x in (self._platform.os, self._platform.architecture, self._platform.variant) if x is not None),  # type: ignore[attr-defined]
            "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--security-opt", "seccomp=/proc/self/fd/" + str(fd),
            "--tmpfs", _TMPFS, "--env", _ENVIRONMENT[0], "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2],
            "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[0], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[1],
            "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[2], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[3],
            "--interactive", "--ipc", "private", "--pids-limit", "256", "--memory", "536870912",
            "--memory-swap", "536870912", "--cpus", "1", "--restart", "no", "--entrypoint", _ENTRYPOINT, image_digest,
        )
        try:
            await self._preflight(control)  # type: ignore[attr-defined]
            result = await self._call(argv, control, pass_fds=(fd,))  # type: ignore[attr-defined]
        finally:
            self._close_fd(fd)  # type: ignore[attr-defined]
        daemon = self._parse_daemon_id(result.stdout)  # type: ignore[attr-defined]
        self._specifications[daemon] = _P1BSpec(daemon, image_digest, "prime.ipython-coding-p1b-development", run_id, "sha256:" + "0" * 64, _DIGEST)  # type: ignore[attr-defined]
        return daemon

    async def inspect(self, container_id: str, *, control: _LifecycleCallControl) -> None:  # type: ignore[override]
        self._specification(container_id)  # type: ignore[attr-defined]
        spec = self._specification(container_id)  # type: ignore[attr-defined]
        projection = '{{json .Id}} {{json .Image}} {{json .Config.Entrypoint}} {{json .HostConfig.NetworkMode}} {{json .HostConfig.ReadonlyRootfs}} {{json .Config.User}} {{json .HostConfig.Privileged}} {{json .HostConfig.CapDrop}} {{json .HostConfig.SecurityOpt}} {{json .HostConfig.Tmpfs}}'
        result = await self._call(self._prefix + ("container", "inspect", "--format", projection, container_id), control)  # type: ignore[attr-defined]
        try:
            parts = result.stdout.rstrip(b"\n").split(b" ", 9)
            values = [json.loads(part) for part in parts]
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        if (len(values) != 10 or values[0] != container_id or values[1] != spec.image_digest or values[2] != [_ENTRYPOINT]
                or values[3] != "none" or values[4] is not True or values[5] != "65534:65534" or values[6] is not False
                or values[7] != ["ALL"] or "no-new-privileges:true" not in values[8] or type(values[9]) is not dict
                or values[9].get("/workspace") != "rw,nodev,noexec,nosuid,size=67108864,uid=65534,gid=65534,mode=0700" or result.stderr):
            raise RestrictedWorkerError("restricted worker value is invalid")

    async def start(self, container_id: str, *, control: _LifecycleCallControl) -> None:  # type: ignore[override]
        self._specification(container_id)  # type: ignore[attr-defined]
        process = await self._attach_runner.open(argv=self._prefix + ("container", "start", "--attach", "--interactive", container_id), env={}, pass_fds=())  # type: ignore[attr-defined]
        if process.stdin is None or process.stdout is None: raise RestrictedWorkerError("restricted worker value is invalid")
        self._started_processes[container_id] = process  # type: ignore[attr-defined]

    async def channel(self, container_id: str, *, run_id: str, session_id: str, control: _LifecycleCallControl) -> _P1BChannel:
        process = self._started_processes.pop(container_id, None)  # type: ignore[attr-defined]
        if process is None: raise RestrictedWorkerError("restricted worker value is invalid")
        return _P1BChannel(process, run_id=run_id, session_id=session_id)

    async def snapshot(self, container_id: str, *, control: _LifecycleCallControl) -> bytes:
        self._specification(container_id)  # type: ignore[attr-defined]
        await self._call(self._prefix + ("container", "pause", container_id), control)  # type: ignore[attr-defined]
        try:
            continuity = await self._call(self._prefix + ("container", "cp", container_id + ":/workspace/p1b-state/continuity.txt", "-"), control)  # type: ignore[attr-defined]
            if self._archive_file(continuity.stdout, "continuity.txt") != _FIXTURE: raise ValueError
            solution = await self._call(self._prefix + ("container", "cp", container_id + ":/workspace/solution.py", "-"), control)  # type: ignore[attr-defined]
            return self._archive_file(solution.stdout, "solution.py")
        except (tarfile.TarError, ValueError, OSError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        finally:
            cleanup = _LifecycleCallControl(monotonic() + 30, None)
            await self._call(self._prefix + ("container", "unpause", container_id), cleanup)  # type: ignore[attr-defined]

    @staticmethod
    def _archive_file(raw: bytes, name: str) -> bytes:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            members = tar.getmembers()
            if len(members) != 1 or members[0].name != name or not members[0].isreg() or members[0].size > _FRAME_CAP: raise ValueError
            source = tar.extractfile(members[0])
            if source is None: raise ValueError
            data = source.read(_FRAME_CAP + 1)
            if len(data) != members[0].size or len(data) > _FRAME_CAP: raise ValueError
            return data


@dataclass(frozen=True, repr=False)
class P1BDockerCompletion:
    """The public-safe witness from a completed persistent kernel."""
    workload_digest: str
    kernel_generation: int
    cell_count: int
    probe_count: int

    def __post_init__(self) -> None:
        if (self.workload_digest != _DIGEST or self.kernel_generation != 1
                or self.cell_count != 2 or self.probe_count != 12):
            raise RestrictedWorkerError("restricted worker value is invalid")

    def __repr__(self) -> str:
        return "P1BDockerCompletion(redacted)"


class _P1BChannel:
    """One canonical JSONL attach session; cells never leave this private object."""
    def __init__(self, process: DockerCliAttachProcess, *, run_id: str, session_id: str) -> None:
        self._process, self._identity = process, {"run_id": run_id, "session_id": session_id}
        self._state, self._pending = "self-check", b""

    async def self_check(self, *, control: _LifecycleCallControl) -> DockerWorkerLauncherSelfCheck:
        if self._state != "self-check":
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._state = "cell-1"
        return DockerCliEngineTransport._parse_self_check_line(await self._read(control))

    async def execute_cell(self, cell: str, *, control: _LifecycleCallControl) -> dict[str, object]:
        if self._state not in {"cell-1", "cell-2"} or type(cell) is not str or not cell:
            raise RestrictedWorkerError("restricted worker value is invalid")
        sequence = 1 if self._state == "cell-1" else 2
        await self._write({"protocol": _PROTOCOL, "identity": self._identity, "sequence": sequence, "kind": "cell.execute", "cell": cell}, control)
        event = self._event(await self._read(control), sequence, "baseline.recorded" if sequence == 1 else "continuity.verified")
        expected = {"baseline_recorded", "cell_count", "kernel_generation", "probe_count"} if sequence == 1 else {"cell_count", "kernel_generation", "preserved", "probe_count"}
        if set(event) != expected or event["cell_count"] != sequence or event["kernel_generation"] != 1 or event["probe_count"] != sequence * 6:
            raise RestrictedWorkerError("restricted worker value is invalid")
        if sequence == 1 and event["baseline_recorded"] is not True:
            raise RestrictedWorkerError("restricted worker value is invalid")
        if sequence == 2 and (type(event["preserved"]) is not dict or set(event["preserved"]) != {"cwd", "file_bytes", "function_behavior", "function_identity", "namespace_value", "path_alias"} or not all(value is True for value in event["preserved"].values())):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._state = "cell-2" if sequence == 1 else "finish"
        return {key: event[key] for key in sorted(event) if key != "preserved"}

    async def finish(self, *, control: _LifecycleCallControl) -> P1BDockerCompletion:
        if self._state != "finish":
            raise RestrictedWorkerError("restricted worker value is invalid")
        await self._write({"protocol": _PROTOCOL, "identity": self._identity, "sequence": 3, "kind": "finish"}, control)
        event = self._event(await self._read(control), 3, "completed")
        if set(event) != {"cell_count", "completed", "kernel_generation", "probe_count"} or event["completed"] is not True:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._state = "completed"
        return P1BDockerCompletion(_DIGEST, event["kernel_generation"], event["cell_count"], event["probe_count"])

    async def close(self, *, control: _LifecycleCallControl) -> None:
        if self._state == "closed": return
        self._state = "closed"
        if self._process.stdin is not None: self._process.stdin.close()
        if self._process.returncode is None: self._process.kill()
        await asyncio.wait_for(self._process.wait(), max(0.001, control.deadline - monotonic()))

    async def _read(self, control: _LifecycleCallControl) -> bytes:
        if self._process.stdout is None: raise RestrictedWorkerError("restricted worker value is invalid")
        raw = self._pending; self._pending = b""
        while b"\n" not in raw and len(raw) <= 1024:
            async with asyncio.timeout_at(control.deadline): raw += await self._process.stdout.read(1025)
        line, sep, self._pending = raw.partition(b"\n")
        if not sep or len(line) > 1024 or self._pending:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return line + sep

    async def _write(self, value: dict[str, object], control: _LifecycleCallControl) -> None:
        if self._process.stdin is None: raise RestrictedWorkerError("restricted worker value is invalid")
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        if len(raw) > _FRAME_CAP: raise RestrictedWorkerError("restricted worker value is invalid")
        self._process.stdin.write(raw)
        async with asyncio.timeout_at(control.deadline): await self._process.stdin.drain()

    def _event(self, raw: bytes, sequence: int, kind: str) -> dict[str, object]:
        try: value = json.loads(raw[:-1]); canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        except (TypeError, ValueError, json.JSONDecodeError): raise RestrictedWorkerError("restricted worker value is invalid") from None
        if type(value) is not dict or raw != canonical or value.get("protocol") != _PROTOCOL or value.get("identity") != self._identity or value.get("sequence") != sequence or value.get("kind") != kind:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return {key: value[key] for key in value if key not in {"protocol", "identity", "sequence", "kind"}}


class P1BDockerTransport(Protocol):
    async def create(self, *, image_digest: str, run_id: str, session_id: str, control: _LifecycleCallControl) -> str: ...
    async def inspect(self, container_id: str, *, control: _LifecycleCallControl) -> None: ...
    async def start(self, container_id: str, *, control: _LifecycleCallControl) -> None: ...
    async def channel(self, container_id: str, *, run_id: str, session_id: str, control: _LifecycleCallControl) -> _P1BChannel: ...
    async def snapshot(self, container_id: str, *, control: _LifecycleCallControl) -> bytes: ...
    async def force_remove(self, container_id: str, *, control: _LifecycleCallControl) -> None: ...
    async def assert_absent(self, container_id: str, *, control: _LifecycleCallControl) -> None: ...


class P1BDockerPersistentWorkerService:
    """Fixed acquire → two cells → finish → snapshot → destroy workflow."""
    def __init__(self, *, image_digest: str, transport: P1BDockerTransport, run_id: str, session_id: str) -> None:
        if not (type(image_digest) is str and image_digest.startswith("sha256:") and len(image_digest) == 71 and all(c in "0123456789abcdef" for c in image_digest[7:]) and type(run_id) is str and run_id and type(session_id) is str and session_id):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._image, self._transport, self._run, self._session = image_digest, transport, run_id, session_id
        self._container: str | None = None; self._channel: _P1BChannel | None = None; self._state = "new"

    def __repr__(self) -> str: return "P1BDockerPersistentWorkerService(redacted)"

    async def acquire(self) -> None:
        if self._state != "new": raise RestrictedWorkerError("restricted worker value is invalid")
        control = _LifecycleCallControl(monotonic() + 30, None)
        try:
            container = await self._transport.create(image_digest=self._image, run_id=self._run, session_id=self._session, control=control)
            await self._transport.inspect(container, control=control); await self._transport.start(container, control=control)
            channel = await self._transport.channel(container, run_id=self._run, session_id=self._session, control=control)
            check = await channel.self_check(control=control)
            if not (check.nonloopback_network_absent and check.root_read_only and check.workspace_only_writable and check.credentials_absent and check.effective_capabilities == 0 and check.no_new_privileges == 1 and check.seccomp_mode == 2 and check.effective_user_id == 65534): raise ValueError
            self._container, self._channel, self._state = container, channel, "cell-1"
        except BaseException:
            await self.cleanup(); raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def execute_cell(self, cell: str) -> dict[str, object]:
        if self._channel is None or self._state not in {"cell-1", "cell-2"}: raise RestrictedWorkerError("restricted worker value is invalid")
        result = await self._channel.execute_cell(cell, control=_LifecycleCallControl(monotonic() + 30, None))
        self._state = "cell-2" if self._state == "cell-1" else "finish"
        return result

    async def finish(self) -> P1BDockerCompletion:
        if self._channel is None or self._state != "finish": raise RestrictedWorkerError("restricted worker value is invalid")
        result = await self._channel.finish(control=_LifecycleCallControl(monotonic() + 30, None)); self._state = "snapshot"; return result

    async def snapshot(self) -> bytes:
        if self._container is None or self._state != "snapshot": raise RestrictedWorkerError("restricted worker value is invalid")
        value = await self._transport.snapshot(self._container, control=_LifecycleCallControl(monotonic() + 30, None))
        if type(value) is not bytes or not value or len(value) > _FRAME_CAP:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._state = "cleanup"; return value

    async def cleanup(self) -> None:
        container, self._container = self._container, None
        if container is None: return
        control = _LifecycleCallControl(monotonic() + 30, None)
        close_error = False
        try:
            if self._channel is not None:
                try: await self._channel.close(control=control)
                except BaseException: close_error = True
            await asyncio.shield(self._transport.force_remove(container, control=control))
            await asyncio.shield(self._transport.assert_absent(container, control=control))
            if close_error: raise RestrictedWorkerError("restricted worker value is invalid")
        finally: self._channel = None; self._state = "closed"
