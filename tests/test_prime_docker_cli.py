"""Tests for the closed, operator-owned Docker CLI transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from typing import cast
from unittest import mock

from asterion.applications.prime_agent.operator.docker_cli import (
    DockerCliAttachRunner,
    DockerCliEngineTransport,
    DockerCliResult as _Result,
    _ProductionRunner,
)
from asterion.applications.prime_agent.operator.docker_worker import (
    DockerWorkerCompletion,
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


class _Runner:
    def __init__(self, results: list[_Result]) -> None:
        self.results = results
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float, int]] = []

    async def run(self, *, argv: tuple[str, ...], env: dict[str, str], timeout: float, max_output_bytes: int) -> _Result:
        self.calls.append((argv, env, timeout, max_output_bytes))
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
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    async def open(self, *, argv: tuple[str, ...], env: dict[str, str]) -> _AttachProcess:
        self.calls.append((argv, env))
        return self.process


def _spec() -> _DockerWorkerSpecification:
    return _DockerWorkerSpecification("prime.ipython-coding", _IMAGE, "run-1", _CHALLENGE, "sha256:" + "d" * 64, 30, 1024, "prime-ipython-coding", 65534, 65534, _CONTAINER)


def _inspect(*, container_id: str = _CONTAINER, extra: object = None) -> bytes:
    value: dict[str, object] = {
        "Id": container_id,
        "Image": _IMAGE,
        "RepoDigests": [],
        "Config": {"User": "65534:65534", "Env": ["HOME=/workspace", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1"], "Entrypoint": ["/usr/local/bin/prime-ipython-coding"], "Labels": {}},
        "HostConfig": {"NetworkMode": "none", "PortBindings": None, "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true", f"seccomp={_SECCOMP}"], "Binds": None, "VolumesFrom": None, "Tmpfs": {"/workspace": "rw,nodev,noexec,nosuid,size=67108864"}, "PidsLimit": 256, "Memory": 536870912, "MemorySwap": 536870912, "NanoCpus": 1000000000, "PidMode": "private", "IpcMode": "private", "UTSMode": "private", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        "Mounts": [],
        "State": {"Running": False},
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
        transport, runner = self._transport([_Result(stdout=b"{}"), _Result(stdout=b"{}"), _Result(stdout=(_CONTAINER + "\n").encode())])

        self.assertEqual(await transport.create(_spec(), control=self._control()), _CONTAINER)
        self.assertEqual(runner.calls[0][0], ("/usr/local/bin/docker", "--host", "unix:///var/run/docker.sock", "version", "--format", "{{json .Server}}"))
        self.assertEqual(runner.calls[1][0][-3:], ("info", "--format", "{{json .}}"))
        self.assertEqual(runner.calls[2][0], ("/usr/local/bin/docker", "--host", "unix:///var/run/docker.sock", "create", "--name", _CONTAINER, "--pull=never", "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--security-opt", f"seccomp={_SECCOMP}", "--tmpfs", "/workspace:rw,nodev,noexec,nosuid,size=67108864", "--env", "HOME=/workspace", "--env", "PATH=/usr/local/bin:/usr/bin:/bin", "--env", "PYTHONDONTWRITEBYTECODE=1", "--pid", "private", "--ipc", "private", "--uts", "private", "--pids-limit", "256", "--memory", "536870912", "--memory-swap", "536870912", "--cpus", "1", "--restart", "no", "--entrypoint", "/usr/local/bin/prime-ipython-coding", _IMAGE))
        self.assertTrue(all(env == {} for _, env, _, _ in runner.calls))

    async def test_inspect_rejects_unknown_or_mismatched_raw_json_without_leaking_it(self) -> None:
        cases = (_inspect(extra=True), _inspect(container_id="other"), b"not-json", b"{}")
        for raw in cases:
            with self.subTest(raw=raw):
                transport, _ = self._transport([_Result(stdout=raw)])
                transport._specifications[_CONTAINER] = _spec()
                with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                    await transport.inspect(_CONTAINER, control=self._control())
                self.assertNotIn("other", str(raised.exception))

    async def test_lifecycle_operations_are_closed_and_parse_only_narrow_evidence(self) -> None:
        selfcheck = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        attach = _AttachRunner(_AttachProcess(selfcheck))
        transport, runner = self._transport([_Result(stdout=_inspect()), _Result(), _Result(returncode=1, stderr=("No such container: " + _CONTAINER).encode())], attach)
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
        self.assertEqual(attach.process.stdin.writes, [b'{"release":true}\n'])
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
        self.assertEqual(attach.process.stdin.writes, [b'{"release":true}\n'])

    async def test_attach_returns_only_the_fixed_workload_completion(self) -> None:
        selfcheck = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        attach = _AttachRunner(_AttachProcess(selfcheck))
        transport, _ = self._transport([], attach)
        transport._specifications[_CONTAINER] = _spec()
        channel = await transport.open_launcher_channel(_CONTAINER, control=self._control())

        await channel.self_check(control=self._control())
        await channel.release(control=self._control())
        result = b'{"fixture":"passed","oracle":"passed","tool":"ipython"}'
        digest = "sha256:" + hashlib.sha256(result).hexdigest()
        frame = json.dumps(
            {
                "result": json.loads(result),
                "result_digest": digest,
                "terminal": "completed",
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

    async def test_production_runner_caps_combined_streams_and_reaps_without_exposing_output(self) -> None:
        process = _Process(_Pipe(b"ab"), _Pipe(b"sentinel"))
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                await _ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=1, max_output_bytes=3)

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertLessEqual(max(process.stdout.requests + process.stderr.requests), 1)
        self.assertNotIn("sentinel", str(raised.exception))

    async def test_production_runner_timeout_reaps_and_redacts(self) -> None:
        process = _Process(_Pipe(blocks=True), _Pipe(blocks=True))
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                await _ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=0.001, max_output_bytes=3)

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn("docker", str(raised.exception))

    async def test_production_runner_pipe_failure_reaps_and_redacts(self) -> None:
        process = _Process(_Pipe(failure=OSError("sentinel pipe failure")), _Pipe())
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                await _ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=1, max_output_bytes=3)

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn("sentinel", str(raised.exception))

    async def test_production_runner_cancellation_reaps_the_child(self) -> None:
        process = _Process(_Pipe(blocks=True), _Pipe(blocks=True))
        with mock.patch("asterion.applications.prime_agent.operator.docker_cli.asyncio.create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            running = asyncio.create_task(_ProductionRunner().run(argv=("/operator/docker", "version"), env={}, timeout=1, max_output_bytes=3))
            await asyncio.sleep(0)
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
