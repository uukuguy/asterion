"""Closed Docker attach transport for the two-cell P1-B development proof.

This development-only surface has its own fixed profile.  It deliberately does
not widen P1-A's one-cell worker contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from secrets import token_hex
from time import monotonic
from typing import Protocol

from .docker_cli import DockerCliAttachProcess, DockerCliAttachRunner, DockerCliEngineTransport
from .docker_worker import DockerWorkerLauncherSelfCheck, _LifecycleCallControl
from .p1b_workload import PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST
from asterion.services.restricted_worker import RestrictedWorkerError

_ENTRYPOINT = "/usr/local/bin/prime-p1b-persistent-worker.py"
_PROTOCOL = "prime-p1-b-development-worker/v1"
_FRAME_CAP = 64 * 1024
_DIGEST = PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST


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
        if sequence == 2 and (type(event["preserved"]) is not dict or not all(value is True for value in event["preserved"].values())):
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
        self._container: str | None = None; self._channel: _P1BChannel | None = None

    def __repr__(self) -> str: return "P1BDockerPersistentWorkerService(redacted)"

    async def acquire(self) -> None:
        control = _LifecycleCallControl(monotonic() + 30, None)
        try:
            container = await self._transport.create(image_digest=self._image, run_id=self._run, session_id=self._session, control=control)
            await self._transport.inspect(container, control=control); await self._transport.start(container, control=control)
            channel = await self._transport.channel(container, run_id=self._run, session_id=self._session, control=control)
            check = await channel.self_check(control=control)
            if not (check.nonloopback_network_absent and check.root_read_only and check.workspace_only_writable and check.credentials_absent and check.effective_capabilities == 0 and check.no_new_privileges == 1 and check.seccomp_mode == 2 and check.effective_user_id == 65534): raise ValueError
            self._container, self._channel = container, channel
        except BaseException:
            await self.cleanup(); raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def execute_cell(self, cell: str) -> dict[str, object]:
        if self._channel is None: raise RestrictedWorkerError("restricted worker value is invalid")
        return await self._channel.execute_cell(cell, control=_LifecycleCallControl(monotonic() + 30, None))

    async def finish(self) -> P1BDockerCompletion:
        if self._channel is None: raise RestrictedWorkerError("restricted worker value is invalid")
        return await self._channel.finish(control=_LifecycleCallControl(monotonic() + 30, None))

    async def snapshot(self) -> bytes:
        if self._container is None: raise RestrictedWorkerError("restricted worker value is invalid")
        return await self._transport.snapshot(self._container, control=_LifecycleCallControl(monotonic() + 30, None))

    async def cleanup(self) -> None:
        container, self._container = self._container, None
        if container is None: return
        control = _LifecycleCallControl(monotonic() + 30, None)
        try:
            if self._channel is not None: await self._channel.close(control=control)
            await self._transport.force_remove(container, control=control); await self._transport.assert_absent(container, control=control)
        finally: self._channel = None

