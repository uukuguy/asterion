"""Tests for the closed, operator-owned Docker CLI transport."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
import unittest
from typing import cast
from unittest import mock

from asterion.applications.prime_agent.operator.docker_cli import (
    DockerCliAttachRunner,
    DockerCliEngineTransport,
    DockerCliResult as _Result,
    _ProductionAttachRunner,
    _ProductionRunner,
)
from asterion.applications.prime_agent.operator.docker_worker import (
    DockerWorkerCompletion, DockerWorkerModelRequest, DockerWorkerModelResponse,
)
from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.docker_worker import (
    _DockerWorkerSpecification,
    _LifecycleCallControl,
)
from asterion.services.restricted_worker import RestrictedWorkerError


_IMAGE = "sha256:" + "a" * 64
_CHALLENGE = "sha256:" + "b" * 64
_CONTAINER = "prime-" + "c" * 32
_SOCKET = "/var/run/docker.sock"
_SECCOMP = "/etc/asterion/prime-ipython-coding.json"
_CONTROL = (
    b'{"control":"begin","prime_sdk_session":"prime-agent@0.7.1","workload_digest":"'
    + PRIME_IPYTHON_CODING_WORKLOAD_DIGEST.encode()
    + b'"}\n'
)


class _Runner:
    def __init__(self, results: list[_Result]) -> None:
        self.results = results
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float, int, tuple[int, ...]]] = []

    async def run(self, *, argv: tuple[str, ...], env: dict[str, str], timeout: float, max_output_bytes: int, pass_fds: tuple[int, ...]) -> _Result:
        self.calls.append((argv, env, timeout, max_output_bytes, pass_fds))
        return self.results.pop(0)


class _Pipe:
    def __init__(self, data: bytes = b"", *, blocks: bool = False, failure: Exception | None = None) -> None:
        self.data = data
        self.blocks = blocks
        self.failure = failure
        self.requests: list[int] = []

    async def read(self, size: int) -> bytes:
        self.requests.append(size)
        if self.failure is not None:
            raise self.failure
        if self.blocks:
            await asyncio.Event().wait()
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


class _Process:
    def __init__(self, stdout: _Pipe, stderr: _Pipe) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = None
        self.killed = False
        self.waited = False

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        self.returncode = -9
        return self.returncode


class _Writer:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _AttachProcess(_Process):
    def __init__(self, data: bytes) -> None:
        super().__init__(_Pipe(data), _Pipe())
        self.stdin = _Writer()


class _BlockingAttachProcess(_AttachProcess):
    def __init__(self) -> None:
        super().__init__(b"")
        self.wait_started = asyncio.Event()
        self.allow_wait = asyncio.Event()

    async def wait(self) -> int:
        self.waited = True
        self.wait_started.set()
        await self.allow_wait.wait()
        self.returncode = -9
        return self.returncode


class _FailingAttachProcess(_AttachProcess):
    async def wait(self) -> int:
        self.waited = True
        raise RuntimeError("socket /var/run/docker.sock sentinel")


class _Signal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class _AttachRunner:
    def __init__(self, process: _AttachProcess) -> None:
        self.process = process
        self.calls: list[tuple[tuple[str, ...], dict[str, str], tuple[int, ...]]] = []

    async def open(
        self, *, argv: tuple[str, ...], env: dict[str, str], pass_fds: tuple[int, ...]
    ) -> _AttachProcess:
        self.calls.append((argv, env, pass_fds))
        return self.process


def _spec() -> _DockerWorkerSpecification:
    return _DockerWorkerSpecification("prime.ipython-coding", _IMAGE, "run-1", _CHALLENGE, "sha256:" + "d" * 64, 30, 1024, "prime-ipython-coding", 65534, 65534, _CONTAINER)


def _inspect(*, container_id: str = _CONTAINER, extra: object = None) -> bytes:
    value: dict[str, object] = {
        "Id": container_id,
        "Image": _IMAGE,
        "RepoDigests": [],
        "Config": {"User": "65534:65534", "Env": ["HOME=/workspace", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1"], "Entrypoint": ["/usr/local/bin/prime-ipython-coding.py"], "Labels": {}},
        "HostConfig": {"NetworkMode": "none", "PortBindings": None, "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true", f"seccomp={_SECCOMP}"], "Binds": None, "VolumesFrom": None, "Tmpfs": {"/workspace": "rw,nodev,noexec,nosuid,size=67108864"}, "PidsLimit": 256, "Memory": 536870912, "MemorySwap": 536870912, "NanoCpus": 1000000000, "PidMode": "private", "IpcMode": "private", "UTSMode": "private", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        "Mounts": [],
        "State": {"Running": False},
    }
    if extra is not None:
        value["unexpected"] = extra
    return json.dumps([value]).encode()


def _projected_inspect(*, container_id: str = _CONTAINER, extra: object = None) -> bytes:
    """The deliberately small response emitted by the fixed inspect format."""
    value: dict[str, object] = {
        "Id": container_id,
        "Image": _IMAGE,
        "User": "65534:65534",
        "Env": ["HOME=/workspace", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1"],
        "Entrypoint": ["/usr/local/bin/prime-ipython-coding.py"],
        "Labels": {},
        "NetworkMode": "none",
        "PortBindings": None,
        "ReadonlyRootfs": True,
        "Privileged": False,
        "CapAdd": None,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true", f"seccomp={_SECCOMP}"],
        "Binds": None,
        "VolumesFrom": None,
        "Tmpfs": {"/workspace": "rw,nodev,noexec,nosuid,size=67108864"},
        "PidsLimit": 256,
        "Memory": 536870912,
        "MemorySwap": 536870912,
        "NanoCpus": 1000000000,
        "PidMode": "private",
        "IpcMode": "private",
        "UTSMode": "private",
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "Mounts": [],
        "Running": False,
    }
    if extra is not None:
        value["unexpected"] = extra
    return json.dumps([value]).encode()


class TestDockerCliEngineTransport(unittest.IsolatedAsyncioTestCase):
    def _transport(self, results: list[_Result], attach: _AttachRunner | None = None) -> tuple[DockerCliEngineTransport, _Runner]:
        runner = _Runner(results)
        return DockerCliEngineTransport(docker_executable="/usr/local/bin/docker", socket_path=_SOCKET, seccomp_profile=_SECCOMP, runner=runner, attach_runner=cast(DockerCliAttachRunner | None, attach)), runner

    def _control(self, signal: _Signal | None = None) -> _LifecycleCallControl:
        return _LifecycleCallControl(asyncio.get_running_loop().time() + 10, signal)

    async def test_create_preflights_and_uses_only_the_fixed_argv_and_empty_environment(self) -> None:
        daemon_id = "a" * 64
        transport, runner = self._transport([_Result(stdout=b"{}"), _Result(stdout=b"{}"), _Result(stdout=(daemon_id + "\n").encode())])

        self.assertEqual(await transport.create(_spec(), control=self._control()), daemon_id)
        self.assertEqual(runner.calls[0][0], ("/usr/local/bin/docker", "--host", "unix:///var/run/docker.sock", "version", "--format", "{{json .Server}}"))
        self.assertEqual(runner.calls[1][0][-3:], ("info", "--format", "{{json .}}"))
        self.assertEqual(runner.calls[2][0], ("/usr/local/bin/docker", "--host", "unix:///var/run/docker.sock", "create", "--name", _CONTAINER, "--pull=never", "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--security-opt", f"seccomp={_SECCOMP}", "--tmpfs", "/workspace:rw,nodev,noexec,nosuid,size=67108864", "--env", "HOME=/workspace", "--env", "PATH=/usr/local/bin:/usr/bin:/bin", "--env", "PYTHONDONTWRITEBYTECODE=1", "--pid", "private", "--ipc", "private", "--uts", "private", "--pids-limit", "256", "--memory", "536870912", "--memory-swap", "536870912", "--cpus", "1", "--restart", "no", "--entrypoint", "/usr/local/bin/prime-ipython-coding.py", _IMAGE))
        self.assertTrue(all(env == {} for _, env, _, _, _ in runner.calls))
        self.assertTrue(all(pass_fds == () for _, _, _, _, pass_fds in runner.calls))

    async def test_create_keeps_requested_name_separate_from_daemon_id(self) -> None:
        daemon_id = "a" * 64
        transport, runner = self._transport([_Result(stdout=b"{}"), _Result(stdout=b"{}"), _Result(stdout=(daemon_id + "\n").encode())])

        self.assertEqual(await transport.create(_spec(), control=self._control()), daemon_id)
        self.assertEqual(runner.calls[-1][0][runner.calls[-1][0].index("--name") + 1], _CONTAINER)
        self.assertNotIn(daemon_id, runner.calls[-1][0])

    async def test_create_then_inspect_uses_daemon_id_and_real_projected_shape(self) -> None:
        daemon_id = "a" * 64
        transport, runner = self._transport([
            _Result(stdout=b"{}"), _Result(stdout=b"{}"),
            _Result(stdout=(daemon_id + "\n").encode()),
            _Result(stdout=_projected_inspect(container_id=daemon_id)),
        ])

        created = await transport.create(_spec(), control=self._control())
        inspection = await transport.inspect(created, control=self._control())

        self.assertEqual(created, daemon_id)
        self.assertEqual(inspection["image_id"], _IMAGE)
        self.assertEqual(runner.calls[-1][0][-1], daemon_id)

    async def test_inspect_rejects_full_container_document_and_requires_leaf_projection(self) -> None:
        transport, _ = self._transport([_Result(stdout=_inspect())])
        transport._specifications[_CONTAINER] = _spec()

        with self.assertRaises(RestrictedWorkerError):
            await transport.inspect(_CONTAINER, control=self._control())

    async def test_snapshot_pauses_archives_exact_solution_and_resumes(self) -> None:
        daemon_id = "a" * 64
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as output:
            info = tarfile.TarInfo("solution.py")
            body = b"def answer(): return 42\n"
            info.size = len(body)
            output.addfile(info, io.BytesIO(body))
        transport, runner = self._transport([_Result(), _Result(stdout=archive.getvalue()), _Result()])
        transport._specifications[daemon_id] = _spec()

        snapshot = await transport.snapshot_solution(daemon_id, control=self._control())
        self.assertEqual(snapshot, b"def answer(): return 42\n")
        self.assertEqual([call[0][-2:] for call in runner.calls], [("pause", daemon_id), (daemon_id + ":/workspace/solution.py", "-"), ("unpause", daemon_id)])

    async def test_snapshot_rejects_archive_attacks_and_still_resumes(self) -> None:
        daemon_id = "a" * 64
        for kind in (tarfile.SYMTYPE, tarfile.DIRTYPE):
            with self.subTest(kind=kind):
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as output:
                    info = tarfile.TarInfo("solution.py")
                    info.type = kind
                    output.addfile(info)
                transport, runner = self._transport([_Result(), _Result(stdout=archive.getvalue()), _Result()])
                transport._specifications[daemon_id] = _spec()
                with self.assertRaises(RestrictedWorkerError):
                    await transport.snapshot_solution(daemon_id, control=self._control())
                self.assertEqual(runner.calls[-1][0][-2:], ("unpause", daemon_id))

    async def test_snapshot_rejects_truncated_multiple_hardlink_pax_and_trailing_archives(self) -> None:
        daemon_id = "a" * 64
        archives: list[bytes] = []
        normal = io.BytesIO()
        with tarfile.open(fileobj=normal, mode="w") as output:
            info = tarfile.TarInfo("solution.py")
            info.size = 1
            output.addfile(info, io.BytesIO(b"x"))
        archives.extend((normal.getvalue()[:-513], normal.getvalue() + b"trailing"))
        multiple = io.BytesIO()
        with tarfile.open(fileobj=multiple, mode="w") as output:
            for name in ("solution.py", "extra.py"):
                info = tarfile.TarInfo(name)
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
        archives.append(multiple.getvalue())
        hardlink = io.BytesIO()
        with tarfile.open(fileobj=hardlink, mode="w") as output:
            info = tarfile.TarInfo("solution.py")
            info.type = tarfile.LNKTYPE
            info.linkname = "other.py"
            output.addfile(info)
        archives.append(hardlink.getvalue())
        pax = io.BytesIO()
        with tarfile.open(fileobj=pax, mode="w", format=tarfile.PAX_FORMAT) as output:
            info = tarfile.TarInfo("solution.py")
            info.pax_headers = {"comment": "untrusted"}
            info.size = 1
            output.addfile(info, io.BytesIO(b"x"))
        archives.append(pax.getvalue())
        over_budget = io.BytesIO()
        with tarfile.open(fileobj=over_budget, mode="w") as output:
            info = tarfile.TarInfo("solution.py")
            info.size = 65536
            output.addfile(info, io.BytesIO(b"x" * info.size))
        # The file alone meets the cap, but its tar metadata exceeds the
        # bounded transport budget and must not be accepted.
        archives.append(over_budget.getvalue())
        for archive in archives:
            with self.subTest(length=len(archive)):
                transport, _ = self._transport([_Result(), _Result(stdout=archive), _Result()])
                transport._specifications[daemon_id] = _spec()
                with self.assertRaises(RestrictedWorkerError):
                    await transport.snapshot_solution(daemon_id, control=self._control())

    async def test_snapshot_unpauses_with_fresh_control_after_copy_cancels(self) -> None:
        daemon_id = "a" * 64
        signal = _Signal()

        class _CancellingRunner(_Runner):
            async def run(self, **kwargs: object) -> _Result:  # type: ignore[override]
                result = await super().run(**kwargs)  # type: ignore[arg-type]
                if cast(tuple[str, ...], kwargs["argv"])[-2:] == (daemon_id + ":/workspace/solution.py", "-"):
                    signal.cancelled = True
                return result

        runner = _CancellingRunner([_Result(), _Result(stdout=b"invalid"), _Result()])
        transport = DockerCliEngineTransport(
            docker_executable="/usr/local/bin/docker", socket_path=_SOCKET,
            seccomp_profile=_SECCOMP, runner=runner,
        )
        transport._specifications[daemon_id] = _spec()

        with self.assertRaises(asyncio.CancelledError):
            await transport.snapshot_solution(daemon_id, control=self._control(signal))
        self.assertEqual([call[0][-2:] for call in runner.calls], [
            ("pause", daemon_id), (daemon_id + ":/workspace/solution.py", "-"),
            ("unpause", daemon_id),
        ])

    async def test_snapshot_reraises_outer_cancellation_after_successful_unpause(self) -> None:
        daemon_id = "a" * 64
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as output:
            info = tarfile.TarInfo("solution.py")
            info.size = 1
            output.addfile(info, io.BytesIO(b"x"))

        class _BlockingUnpauseRunner(_Runner):
            def __init__(self) -> None:
                super().__init__([_Result(), _Result(stdout=archive.getvalue()), _Result()])
                self.unpause_started = asyncio.Event()
                self.allow_unpause = asyncio.Event()

            async def run(self, **kwargs: object) -> _Result:  # type: ignore[override]
                result = await super().run(**kwargs)  # type: ignore[arg-type]
                if cast(tuple[str, ...], kwargs["argv"])[-2:] == ("unpause", daemon_id):
                    self.unpause_started.set()
                    await self.allow_unpause.wait()
                return result

        runner = _BlockingUnpauseRunner()
        transport = DockerCliEngineTransport(
            docker_executable="/usr/local/bin/docker", socket_path=_SOCKET,
            seccomp_profile=_SECCOMP, runner=runner,
        )
        transport._specifications[daemon_id] = _spec()

        snapshot = asyncio.create_task(
            transport.snapshot_solution(daemon_id, control=self._control())
        )
        await runner.unpause_started.wait()
        snapshot.cancel()
        runner.allow_unpause.set()
        with self.assertRaises(asyncio.CancelledError):
            await snapshot
        self.assertEqual([call[0][-2:] for call in runner.calls], [
            ("pause", daemon_id), (daemon_id + ":/workspace/solution.py", "-"),
            ("unpause", daemon_id),
        ])

    async def test_snapshot_unpause_failure_force_removes_and_proves_absence(self) -> None:
        daemon_id = "a" * 64
        transport, runner = self._transport([
            _Result(), _Result(stdout=b"invalid"), _Result(returncode=1), _Result(),
            _Result(returncode=1, stderr=("No such container: " + daemon_id).encode()),
        ])
        transport._specifications[daemon_id] = _spec()

        with self.assertRaises(RestrictedWorkerError):
            await transport.snapshot_solution(daemon_id, control=self._control())
        self.assertEqual([call[0][-2:] for call in runner.calls], [
            ("pause", daemon_id), (daemon_id + ":/workspace/solution.py", "-"),
            ("unpause", daemon_id), ("--force", daemon_id), ("{{.Id}}", daemon_id),
        ])

    async def test_failed_pause_response_force_removes_and_proves_absence(self) -> None:
        daemon_id = "a" * 64
        transport, runner = self._transport([
            _Result(returncode=1), _Result(),
            _Result(returncode=1, stderr=("No such container: " + daemon_id).encode()),
        ])
        transport._specifications[daemon_id] = _spec()
        with self.assertRaises(RestrictedWorkerError):
            await transport.snapshot_solution(daemon_id, control=self._control())
        self.assertEqual([call[0][-2:] for call in runner.calls], [
            ("pause", daemon_id), ("--force", daemon_id), ("{{.Id}}", daemon_id),
        ])

    async def test_cancelled_pause_response_force_removes_and_proves_absence(self) -> None:
        daemon_id = "a" * 64
        signal = _Signal()

        class _CancellingRunner(_Runner):
            async def run(self, **kwargs: object) -> _Result:  # type: ignore[override]
                result = await super().run(**kwargs)  # type: ignore[arg-type]
                if cast(tuple[str, ...], kwargs["argv"])[-2:] == ("pause", daemon_id):
                    signal.cancelled = True
                return result

        runner = _CancellingRunner([
            _Result(), _Result(),
            _Result(returncode=1, stderr=("No such container: " + daemon_id).encode()),
        ])
        transport = DockerCliEngineTransport(
            docker_executable="/usr/local/bin/docker", socket_path=_SOCKET,
            seccomp_profile=_SECCOMP, runner=runner,
        )
        transport._specifications[daemon_id] = _spec()
        with self.assertRaises(asyncio.CancelledError):
            await transport.snapshot_solution(daemon_id, control=self._control(signal))
        self.assertEqual([call[0][-2:] for call in runner.calls], [
            ("pause", daemon_id), ("--force", daemon_id), ("{{.Id}}", daemon_id),
        ])

    async def test_inspect_rejects_unknown_or_mismatched_raw_json_without_leaking_it(self) -> None:
        cases = (_projected_inspect(extra=True), _projected_inspect(container_id="other"), b"not-json", b"{}")
        for raw in cases:
            with self.subTest(raw=raw):
                transport, _ = self._transport([_Result(stdout=raw)])
                transport._specifications[_CONTAINER] = _spec()
                with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                    await transport.inspect(_CONTAINER, control=self._control())
                self.assertNotIn("other", str(raised.exception))

    async def test_inspect_uses_the_fixed_host_owned_projection(self) -> None:
        transport, runner = self._transport([_Result(stdout=_projected_inspect())])
        transport._specifications[_CONTAINER] = _spec()

        await transport.inspect(_CONTAINER, control=self._control())
        argv = runner.calls[0][0]
        self.assertEqual(argv[-3], "--format")
        self.assertIn('"NetworkMode":{{json .HostConfig.NetworkMode}}', argv[-2])
        self.assertNotIn("RepoDigests", argv[-2])
        self.assertEqual(argv[-1], _CONTAINER)

    async def test_lifecycle_operations_are_closed_and_parse_only_narrow_evidence(self) -> None:
        selfcheck = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        attach = _AttachRunner(_AttachProcess(selfcheck))
        transport, runner = self._transport([_Result(stdout=_projected_inspect()), _Result(), _Result(returncode=1, stderr=("No such container: " + _CONTAINER).encode())], attach)
        transport._specifications[_CONTAINER] = _spec()
        inspection = await transport.inspect(_CONTAINER, control=self._control())
        lease = await transport.start(_CONTAINER, control=self._control())
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())
        check = await channel.self_check(control=self._control())
        await channel.release(control=self._control())
        await channel.close(control=self._control())
        await transport.assert_absent(_CONTAINER, control=self._control())
        self.assertEqual(inspection["network_mode"], "none")
        self.assertEqual(lease.worker_id, _CONTAINER)
        self.assertEqual(check.effective_user_id, 65534)
        self.assertEqual(runner.calls[1][0][-2:], ("start", _CONTAINER))
        self.assertEqual(attach.calls[0][0][-3:], ("attach", "--sig-proxy=false", _CONTAINER))
        self.assertEqual(attach.calls[0][2], ())
        self.assertEqual(attach.process.stdin.writes, [_CONTROL])
        self.assertTrue(attach.process.waited)
        self.assertEqual(runner.calls[2][0][-4:], ("inspect", "--format", "{{.Id}}", _CONTAINER))

    async def test_attach_rejects_noncanonical_extra_eof_or_oversize_frames(self) -> None:
        canonical = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode()
        cases = (canonical, canonical + b"\nextra", canonical + b" \n", b"x" * 1025)
        for frame in cases:
            with self.subTest(frame_length=len(frame)):
                attach = _AttachRunner(_AttachProcess(frame))
                transport, _ = self._transport([], attach)
                transport._specifications[_CONTAINER] = _spec()
                channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())
                with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                    await channel.self_check(control=self._control())
                await channel.close(control=self._control())
                self.assertTrue(attach.process.waited)
                self.assertNotIn("extra", str(raised.exception))

    async def test_attach_release_is_exactly_once_and_reaped(self) -> None:
        frame = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        attach = _AttachRunner(_AttachProcess(frame))
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())
        await channel.self_check(control=self._control())
        await channel.release(control=self._control())
        with self.assertRaises(RestrictedWorkerError):
            await channel.release(control=self._control())
        await channel.close(control=self._control())
        self.assertEqual(attach.process.stdin.writes, [_CONTROL])

    async def test_attach_relays_only_closed_model_frames_between_host_and_launcher(self) -> None:
        selfcheck = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        request = json.dumps({"kind": "model-request", "prime_sdk_session": "prime-agent@0.7.1", "tools": ["ipython"], "workload_digest": PRIME_IPYTHON_CODING_WORKLOAD_DIGEST}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        attach = _AttachRunner(_AttachProcess(selfcheck + request))
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())

        await channel.self_check(control=self._control())
        await channel.release(control=self._control())
        self.assertEqual(await channel.model_request(control=self._control()), DockerWorkerModelRequest(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST))
        await channel.model_response(DockerWorkerModelResponse(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, "ipython", "private cell"), control=self._control())
        self.assertNotIn(b"private cell", repr(channel).encode())
        self.assertIn(b'"model-response"', attach.process.stdin.writes[-1])

    async def test_attach_returns_only_the_fixed_workload_completion(self) -> None:
        selfcheck = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        request = json.dumps({"kind": "model-request", "prime_sdk_session": "prime-agent@0.7.1", "tools": ["ipython"], "workload_digest": PRIME_IPYTHON_CODING_WORKLOAD_DIGEST}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        attach = _AttachRunner(_AttachProcess(selfcheck + request))
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())

        await channel.self_check(control=self._control())
        await channel.release(control=self._control())
        await channel.model_request(control=self._control())
        await channel.model_response(DockerWorkerModelResponse(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, "ipython", "private cell"), control=self._control())
        result = b'{"fixture":"passed","oracle":"passed","tool":"ipython"}'
        digest = "sha256:" + hashlib.sha256(result).hexdigest()
        frame = json.dumps(
            {
                "host_model_operations": 1,
                "model_caused_ipython_mutation": True,
                "oracle_eventually_passed": True,
                "oracle_initially_failed": True,
                "result": json.loads(result),
                "result_digest": digest,
                "terminal": "completed",
                "tools": ["ipython"],
                "workload_digest": PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode() + b"\n"
        attach.process.stdout.data = frame

        self.assertEqual(
            await channel.completed_result(control=self._control()),
            DockerWorkerCompletion(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, result),
        )
        for invalid in (
            frame.replace(digest.encode(), b"sha256:" + b"0" * 64),
            frame.replace(b'"completed"', b'"failed"'),
            frame[:-1] + b" \n",
            frame + b"extra\n",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(RestrictedWorkerError):
                DockerCliEngineTransport._parse_completed_result_line(invalid)

    def test_completed_result_rejects_non_normalized_content(self) -> None:
        expected = {"fixture": "passed", "oracle": "passed", "tool": "ipython"}

        def frame_for(result: object) -> bytes:
            result_bytes = json.dumps(
                result, separators=(",", ":"), sort_keys=True
            ).encode()
            return json.dumps(
                {
                    "result": result,
                    "result_digest": "sha256:" + hashlib.sha256(result_bytes).hexdigest(),
                    "terminal": "completed",
                    "workload_digest": PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode() + b"\n"

        for result in (
            {**expected, "source": "print('sentinel')"},
            {**expected, "output": "sentinel"},
            {**expected, "prompt": "sentinel"},
            {**expected, "credential": "sentinel"},
            {**expected, "path": "/private/sentinel"},
            {**expected, "transcript": "sentinel"},
            {**expected, "detail": {"nested": "sentinel"}},
            {"fixture": "passed", "oracle": "passed"},
            {"fixture": "failed", "oracle": "passed", "tool": "ipython"},
            {"fixture": "passed", "oracle": "failed", "tool": "ipython"},
            {"fixture": "passed", "oracle": "passed", "tool": "python"},
            {"fixture": True, "oracle": "passed", "tool": "ipython"},
            {"fixture": "passed", "oracle": 1, "tool": "ipython"},
            {"fixture": "passed", "oracle": "passed", "tool": ["ipython"]},
        ):
            with self.subTest(result=result), self.assertRaises(RestrictedWorkerError):
                DockerCliEngineTransport._parse_completed_result_line(frame_for(result))

    async def test_attach_close_reaps_when_control_is_already_cancelled(self) -> None:
        process = _AttachProcess(b"")
        attach = _AttachRunner(process)
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())

        with self.assertRaises(asyncio.CancelledError):
            await channel.close(control=self._control(_Signal(True)))

        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)

    async def test_attach_close_reaps_after_outer_cancellation(self) -> None:
        process = _BlockingAttachProcess()
        attach = _AttachRunner(process)
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())
        closing = asyncio.create_task(channel.close(control=self._control()))
        await process.wait_started.wait()
        closing.cancel()
        process.allow_wait.set()

        with self.assertRaises(asyncio.CancelledError):
            await closing

        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)

    async def test_attach_close_redacts_reap_failure_after_killing_and_waiting(self) -> None:
        process = _FailingAttachProcess(b"")
        attach = _AttachRunner(process)
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())

        with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
            await channel.close(control=self._control())

        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn("socket", str(raised.exception))

    async def test_absence_daemon_failure_and_non_absence_are_rejected(self) -> None:
        for result in (_Result(returncode=1, stderr=b"daemon unavailable"), _Result(stdout=(_CONTAINER + "\n").encode())):
            with self.subTest(result=result):
                transport, _ = self._transport([result])
                transport._specifications[_CONTAINER] = _spec()
                with self.assertRaises(RestrictedWorkerError):
                    await transport.assert_absent(_CONTAINER, control=self._control())

    def test_constructor_rejects_nonlocal_or_relative_operator_configuration(self) -> None:
        for values in (("docker", _SOCKET, _SECCOMP), ("/docker", "tcp://host", _SECCOMP), ("/docker", "/socket", "profile")):
            with self.subTest(values=values), self.assertRaises(RestrictedWorkerError):
                DockerCliEngineTransport(docker_executable=values[0], socket_path=values[1], seccomp_profile=values[2], runner=_Runner([]))

    async def test_production_runner_forwards_requested_file_descriptors(self) -> None:
        process = _Process(_Pipe(), _Pipe())
        subprocess_exec = mock.AsyncMock(return_value=process)
        with mock.patch(
            "asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec",
            new=subprocess_exec,
        ):
            await _ProductionRunner().run(
                argv=("/operator/docker", "version"), env={}, timeout=1,
                max_output_bytes=3, pass_fds=(41, 42),
            )

        subprocess_exec.assert_awaited_once_with(
            "/operator/docker", "version", stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={},
            pass_fds=(41, 42),
        )

    async def test_production_attach_runner_forwards_requested_file_descriptors(self) -> None:
        process = _AttachProcess(b"")
        subprocess_exec = mock.AsyncMock(return_value=process)
        with mock.patch(
            "asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec",
            new=subprocess_exec,
        ):
            self.assertIs(
                await _ProductionAttachRunner().open(
                    argv=("/operator/docker", "attach"), env={}, pass_fds=(41, 42),
                ),
                process,
            )

        subprocess_exec.assert_awaited_once_with(
            "/operator/docker", "attach", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env={},
            pass_fds=(41, 42),
        )

    async def test_production_runner_caps_combined_streams_and_reaps_without_exposing_output(self) -> None:
        process = _Process(_Pipe(b"ab"), _Pipe(b"sentinel"))
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                await _ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=1, max_output_bytes=3, pass_fds=())

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertLessEqual(max(process.stdout.requests + process.stderr.requests), 1)
        self.assertNotIn("sentinel", str(raised.exception))

    async def test_production_runner_timeout_reaps_and_redacts(self) -> None:
        process = _Process(_Pipe(blocks=True), _Pipe(blocks=True))
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                await _ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=0.001, max_output_bytes=3, pass_fds=())

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn("docker", str(raised.exception))

    async def test_production_runner_pipe_failure_reaps_and_redacts(self) -> None:
        process = _Process(_Pipe(failure=OSError("sentinel pipe failure")), _Pipe())
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                await _ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=1, max_output_bytes=3, pass_fds=())

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn("sentinel", str(raised.exception))

    async def test_production_runner_cancellation_reaps_the_child(self) -> None:
        process = _Process(_Pipe(blocks=True), _Pipe(blocks=True))
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            running = asyncio.create_task(_ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=1, max_output_bytes=3, pass_fds=()))
            await asyncio.sleep(0)
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
