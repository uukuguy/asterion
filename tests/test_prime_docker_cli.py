"""Tests for the closed, operator-owned Docker CLI transport."""

from __future__ import annotations

import asyncio
import json
import unittest

from asterion.applications.prime_agent.operator.docker_cli import (
    DockerCliEngineTransport,
    DockerCliResult as _Result,
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


def _spec() -> _DockerWorkerSpecification:
    return _DockerWorkerSpecification("prime.ipython-coding", _IMAGE, "run-1", _CHALLENGE, 30, 1024, "prime-ipython-coding", 65534, 65534, _CONTAINER)


def _inspect(*, container_id: str = _CONTAINER, extra: object = None) -> bytes:
    value: dict[str, object] = {
        "Id": container_id,
        "Image": _IMAGE,
        "RepoDigests": [_IMAGE],
        "Config": {"User": "65534:65534", "Env": ["HOME=/workspace", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1"], "Entrypoint": ["/usr/local/bin/prime-ipython-coding"], "Labels": {}},
        "HostConfig": {"NetworkMode": "none", "PortBindings": None, "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true", f"seccomp={_SECCOMP}"], "Binds": None, "VolumesFrom": None, "Tmpfs": {"/workspace": "rw,nodev,noexec,nosuid,size=67108864"}, "PidsLimit": 256, "Memory": 536870912, "MemorySwap": 536870912, "NanoCpus": 1000000000, "PidMode": "private", "IpcMode": "private", "UTSMode": "private", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        "Mounts": [],
        "State": {"Running": False},
    }
    if extra is not None:
        value["unexpected"] = extra
    return json.dumps([value]).encode()


class TestDockerCliEngineTransport(unittest.IsolatedAsyncioTestCase):
    def _transport(self, results: list[_Result]) -> tuple[DockerCliEngineTransport, _Runner]:
        runner = _Runner(results)
        return DockerCliEngineTransport(docker_executable="/usr/local/bin/docker", socket_path=_SOCKET, seccomp_profile=_SECCOMP, runner=runner), runner

    def _control(self) -> _LifecycleCallControl:
        return _LifecycleCallControl(asyncio.get_running_loop().time() + 10, None)

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
        selfcheck = json.dumps({"nonloopback_network_absent": True, "root_read_only": True, "workspace_only_writable": True, "credentials_absent": True, "effective_capabilities": 0, "no_new_privileges": 1, "seccomp_mode": 2, "effective_user_id": 65534}).encode()
        transport, runner = self._transport([_Result(stdout=_inspect()), _Result(), _Result(stdout=selfcheck), _Result(returncode=1, stderr=("No such container: " + _CONTAINER).encode())])
        transport._specifications[_CONTAINER] = _spec()
        inspection = await transport.inspect(_CONTAINER, control=self._control())
        lease = await transport.start(_CONTAINER, control=self._control())
        check = await transport.launcher_self_check(_CONTAINER, control=self._control())
        await transport.assert_absent(_CONTAINER, control=self._control())
        self.assertEqual(inspection["network_mode"], "none")
        self.assertEqual(lease.worker_id, _CONTAINER)
        self.assertEqual(check.effective_user_id, 65534)
        self.assertEqual(runner.calls[1][0][-2:], ("start", _CONTAINER))
        self.assertEqual(runner.calls[2][0][-4:], ("attach", "--no-stdin", "--sig-proxy=false", _CONTAINER))
        self.assertEqual(runner.calls[3][0][-4:], ("inspect", "--format", "{{.Id}}", _CONTAINER))

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
