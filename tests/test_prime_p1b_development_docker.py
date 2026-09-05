from __future__ import annotations

import unittest
from time import monotonic
import asyncio
import json
from unittest.mock import patch

from asterion.applications.prime_agent.operator.docker_worker import DockerWorkerLauncherSelfCheck
from asterion.applications.prime_agent.operator.p1b_development_docker import (
    P1BDevelopmentSnapshotTransport, P1BDockerCompletion,
    P1BDockerPersistentWorkerService, P1BDockerCliTransport, _reap_process,
)
from asterion.applications.prime_agent.operator import p1b_development_docker as p1b_docker
from asterion.applications.prime_agent.operator import docker_cli
from asterion.applications.prime_agent.operator.docker_cli import DockerCliResult
from asterion.applications.prime_agent.operator.docker_worker import _LifecycleCallControl
from asterion.applications.prime_agent.operator import p1_development_snapshot as snapshots
from asterion.applications.prime_agent.operator.image_input_lock import ImagePlatformDescriptor
from asterion.applications.prime_agent.operator.p1b_workload import PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST


class _Channel:
    async def self_check(self, **_: object) -> DockerWorkerLauncherSelfCheck:
        return DockerWorkerLauncherSelfCheck(True, True, True, True, 0, 1, 2, 65534)
    async def execute_cell(self, cell: str, **_: object) -> dict[str, object]:
        if cell == "one": return {"cell_count": 1, "kernel_generation": 1, "probe_count": 6, "baseline_recorded": True}
        return {"cell_count": 2, "kernel_generation": 1, "probe_count": 12}
    async def finish(self, **_: object) -> P1BDockerCompletion:
        return P1BDockerCompletion(PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST, 1, 2, 12)
    async def close(self, **_: object) -> None: pass


class _Transport:
    def __init__(self) -> None:
        self.calls: list[str] = []; self.channel_value = _Channel(); self.inspect_error = False; self.remove_error = False
        self.inspect_started: asyncio.Event | None = None; self.allow_inspect: asyncio.Event | None = None
        self.remove_started: asyncio.Event | None = None; self.allow_remove: asyncio.Event | None = None
    async def create(self, **_: object) -> str: self.calls.append("create"); return "d" * 64
    async def inspect(self, *_: object, **__: object) -> None:
        self.calls.append("inspect")
        if self.inspect_started is not None:
            self.inspect_started.set()
        if self.allow_inspect is not None:
            await self.allow_inspect.wait()
        if self.inspect_error: raise ValueError
    async def start(self, *_: object, **__: object) -> None: self.calls.append("start")
    async def channel(self, *_: object, **__: object) -> _Channel: self.calls.append("attach"); return self.channel_value
    async def snapshot(self, *_: object, **__: object) -> bytes: self.calls.append("snapshot"); return b"p1b continuity fixture\n"
    async def initial_snapshot(self, *_: object, **__: object) -> bytes: self.calls.append("initial_snapshot"); return b"def answer() -> int:\n    return 0\n"
    async def force_remove(self, *_: object, **__: object) -> None:
        self.calls.append("remove")
        if self.remove_started is not None:
            self.remove_started.set()
        if self.allow_remove is not None:
            await self.allow_remove.wait()
        if self.remove_error: raise ValueError
    async def assert_absent(self, *_: object, **__: object) -> None: self.calls.append("absent")


def _p1b_projected_inspect(
    container_id: str, image_digest: str, environment: list[str], *, port_bindings: object = {},
) -> bytes:
    return json.dumps([{
        "Id": container_id, "Image": image_digest, "User": "65534:65534", "Env": environment,
        "Entrypoint": ["/usr/local/bin/prime-p1b-persistent-worker.py"], "Labels": {},
        "OpenStdin": True, "NetworkMode": "none", "PortBindings": port_bindings,
        "ReadonlyRootfs": True, "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true", "seccomp=profile"], "Binds": None,
        "VolumesFrom": None,
        "Tmpfs": {"/workspace": "rw,nodev,noexec,nosuid,size=67108864,uid=65534,gid=65534,mode=0700"},
        "PidsLimit": 256, "Memory": 536870912, "MemorySwap": 536870912,
        "NanoCpus": 1000000000, "PidMode": "", "IpcMode": "private", "UTSMode": "",
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}, "Mounts": [], "Running": False,
    }], separators=(",", ":")).encode()


class TestP1BDockerPersistentWorkerService(unittest.IsolatedAsyncioTestCase):
    async def test_p1b_inspect_accepts_reordered_environment_and_rejects_invalid_keys(self) -> None:
        container_id = "d" * 64
        image_digest = "sha256:" + "a" * 64
        subject = object.__new__(P1BDockerCliTransport)
        subject._prefix = ("/operator/docker",)
        subject._seccomp_profile = "profile"
        subject._specifications = {
            container_id: p1b_docker._P1BSpec(
                container_id, image_digest, "role", "run", "challenge", "workload",
            ),
        }
        valid = list(reversed([
            *docker_cli._ENVIRONMENT, *docker_cli._CLEARED_BASE_IMAGE_ENVIRONMENT,
        ]))
        cases = (
            (valid, None, False),
            (valid + [valid[0]], {}, True),
            (valid + ["UNEXPECTED=value"], {}, True),
        )
        for environment, port_bindings, rejected in cases:
            with self.subTest(environment=environment, port_bindings=port_bindings):
                async def call(*_: object, **__: object) -> DockerCliResult:
                    return DockerCliResult(stdout=_p1b_projected_inspect(
                        container_id, image_digest, environment, port_bindings=port_bindings,
                    ))
                subject._call = call
                if rejected:
                    from asterion.services.restricted_worker import RestrictedWorkerError
                    with self.assertRaises(RestrictedWorkerError):
                        await subject.inspect(container_id, control=_LifecycleCallControl(monotonic() + 30, None))
                else:
                    await subject.inspect(container_id, control=_LifecycleCallControl(monotonic() + 30, None))

    def test_local_root_snapshot_transport_requires_explicit_same_guest_confirmation(self) -> None:
        with patch.object(P1BDockerCliTransport, "__init__", return_value=None) as base:
            for platform, euid, confirmed in (
                ("darwin", 0, True),
                ("linux", 501, True),
                ("linux", 0, False),
                ("linux", 0, "true"),
            ):
                with (
                    patch.object(snapshots.sys, "platform", platform),
                    patch.object(snapshots.os, "geteuid", return_value=euid),
                ):
                    with self.assertRaisesRegex(Exception, "restricted worker value is invalid"):
                        P1BDevelopmentSnapshotTransport(
                            docker_executable="/operator/docker", socket_path="/operator/docker.sock",
                            seccomp_profile_fd=9, platform=ImagePlatformDescriptor("linux", "amd64", None),
                            operator_confirmed_same_guest=confirmed,  # type: ignore[arg-type]
                        )
            with (
                patch.object(snapshots.sys, "platform", "linux"),
                patch.object(snapshots.os, "geteuid", return_value=0),
            ):
                P1BDevelopmentSnapshotTransport(
                    docker_executable="/operator/docker", socket_path="/operator/docker.sock",
                    seccomp_profile_fd=9, platform=ImagePlatformDescriptor("linux", "amd64", None),
                    operator_confirmed_same_guest=True,
                )
        self.assertEqual(base.call_count, 1)

    async def test_proc_snapshots_use_fixed_paths_and_validate_continuity_before_solution(self) -> None:
        container = "d" * 64
        subject = object.__new__(P1BDevelopmentSnapshotTransport)
        subject._prefix = ("/operator/docker", "--host", "unix:///operator/docker.sock")
        subject._specifications = {container: object()}
        calls: list[tuple[str, ...]] = []

        async def call(argv: tuple[str, ...], *_: object, **__: object) -> DockerCliResult:
            calls.append(argv)
            if "inspect" in argv:
                return DockerCliResult(stdout=json.dumps([{
                    "Id": container, "Pid": 77, "Running": True, "Paused": True,
                }], separators=(",", ":")).encode())
            return DockerCliResult()

        subject._call = call
        contents = {
            13: b"def answer() -> int:\n    return 0\n",
            17: b"p1b continuity fixture\n",
            18: b"def answer() -> int:\n    return 42\n",
        }
        with (
            patch.object(subject, "_open_proc", return_value=10),
            patch.object(subject, "_same_live_process"),
            patch.object(snapshots, "_identity", return_value=(1, 2)),
            patch.object(snapshots.os, "open", side_effect=[11, 12, 13, 14, 15, 16, 17, 18]) as opened,
            patch.object(snapshots.os, "pread", side_effect=lambda fd, _count, _offset: contents[fd]),
            patch.object(snapshots, "_stable_regular_file", side_effect=lambda fd: (1, fd, len(contents[fd]), 0, 0)),
            patch.object(snapshots.os, "close"),
        ):
            initial = await subject.initial_snapshot(container, control=_LifecycleCallControl(monotonic() + 30, None))
            final = await subject.snapshot(container, control=_LifecycleCallControl(monotonic() + 30, None))

        self.assertEqual(initial, contents[13])
        self.assertEqual(final, contents[18])
        self.assertEqual(
            [item.args[0] for item in opened.call_args_list],
            ["root", "workspace", "solution.py", "root", "workspace", "p1b-state", "continuity.txt", "solution.py"],
        )
        self.assertFalse(any("cp" in argv for argv in calls))

    async def test_reap_completes_wait_before_propagating_cancellation(self) -> None:
        released = asyncio.Event()
        class Process:
            returncode = None
            killed = False
            def kill(self) -> None: self.killed = True
            async def wait(self) -> int:
                await released.wait(); return 0
        process = Process()
        task = asyncio.create_task(_reap_process(process))
        await asyncio.sleep(0)
        task.cancel(); await asyncio.sleep(0)
        self.assertTrue(process.killed)
        self.assertFalse(task.done())
        released.set()
        with self.assertRaises(asyncio.CancelledError): await task

    async def test_reap_rejects_a_wait_that_misses_its_deadline(self) -> None:
        class Process:
            returncode = None
            def kill(self) -> None: pass
            async def wait(self) -> int: await asyncio.Event().wait(); return 0
        from asterion.services.restricted_worker import RestrictedWorkerError
        with self.assertRaises(RestrictedWorkerError):
            await _reap_process(Process(), deadline=monotonic() + 0.001)

    async def test_two_cells_finish_snapshot_and_cleanup_are_ordered(self) -> None:
        transport = _Transport()
        service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        await service.acquire()
        self.assertIn(b"return 0", await service.initial_snapshot())
        self.assertEqual((await service.execute_cell("one"))["cell_count"], 1)
        self.assertEqual((await service.execute_cell("two"))["probe_count"], 12)
        self.assertEqual(await service.finish(), P1BDockerCompletion(PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST, 1, 2, 12))
        self.assertEqual(await service.snapshot(), b"p1b continuity fixture\n")
        await service.cleanup()
        self.assertEqual(transport.calls, ["create", "inspect", "start", "attach", "initial_snapshot", "snapshot", "remove", "absent"])

    async def test_inspect_rejection_after_create_still_removes_and_proves_absence(self) -> None:
        transport = _Transport(); transport.inspect_error = True
        service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        with self.assertRaises(Exception):
            await service.acquire()
        self.assertEqual(transport.calls, ["create", "inspect", "remove", "absent"])

    async def test_cleanup_failure_retains_owner_for_retry(self) -> None:
        transport = _Transport(); service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        await service.acquire(); transport.remove_error = True
        with self.assertRaises(ValueError): await service.cleanup()
        transport.remove_error = False; await service.cleanup()
        self.assertEqual(transport.calls[-3:], ["remove", "remove", "absent"])

    async def test_acquire_cancellation_completes_cleanup_then_propagates_cancellation(self) -> None:
        transport = _Transport()
        transport.inspect_started = asyncio.Event(); transport.allow_inspect = asyncio.Event()
        transport.remove_started = asyncio.Event(); transport.allow_remove = asyncio.Event()
        service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        task = asyncio.create_task(service.acquire())
        await transport.inspect_started.wait()
        task.cancel()
        await transport.remove_started.wait()
        self.assertFalse(task.done())
        transport.allow_remove.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(transport.calls, ["create", "inspect", "remove", "absent"])

    async def test_uncertain_create_compensation_removes_provisional_name_then_asserts_absence(self) -> None:
        class Runner:
            def __init__(self) -> None: self.argv: list[tuple[str, ...]] = []
            async def run(self, *, argv: tuple[str, ...], **_: object) -> DockerCliResult:
                self.argv.append(argv)
                if "rm" in argv: return DockerCliResult(0, b"prime-p1b-provisional\n", b"")
                return DockerCliResult(1, b"", b"Error: No such object: prime-p1b-provisional\n")
        runner = Runner()
        subject = object.__new__(P1BDockerCliTransport)
        subject._prefix = ("/operator/docker", "--host", "unix:///operator/docker.sock")
        subject._runner = runner
        with patch(
            "asterion.applications.prime_agent.operator.p1b_development_docker._PROVISIONAL_SETTLE_INTERVAL_SECONDS",
            0.001,
        ), patch(
            "asterion.applications.prime_agent.operator.p1b_development_docker._PROVISIONAL_SETTLE_SECONDS",
            0.004,
        ):
            await subject._compensate_provisional("prime-p1b-provisional")
        self.assertEqual(runner.argv[0][-4:], ("container", "rm", "--force", "prime-p1b-provisional"))
        self.assertEqual(runner.argv[1][-5:], ("container", "inspect", "--format", "{{.Id}}", "prime-p1b-provisional"))

    async def test_uncertain_create_compensation_waits_for_late_create_then_removes_it(self) -> None:
        class Clock:
            now = 0.0
            def __call__(self) -> float: return self.now

        class Runner:
            def __init__(self) -> None:
                self.argv: list[tuple[str, ...]] = []
                self.remove_count = 0
                self.inspect_count = 0

            async def run(self, *, argv: tuple[str, ...], **_: object) -> DockerCliResult:
                self.argv.append(argv)
                if "rm" in argv:
                    self.remove_count += 1
                    if self.remove_count == 6:
                        return DockerCliResult(0, b"prime-p1b-provisional\n", b"")
                    return DockerCliResult(1, b"", b"Error: No such object: prime-p1b-provisional\n")
                self.inspect_count += 1
                if self.inspect_count == 5:
                    return DockerCliResult(0, b"d" * 64 + b"\n", b"")
                return DockerCliResult(1, b"", b"Error: No such object: prime-p1b-provisional\n")

        clock = Clock()
        async def advance(delay: float) -> None: clock.now += delay
        runner = Runner()
        subject = object.__new__(P1BDockerCliTransport)
        subject._prefix = ("/operator/docker", "--host", "unix:///operator/docker.sock")
        subject._runner = runner
        with patch(
            "asterion.applications.prime_agent.operator.p1b_development_docker._PROVISIONAL_SETTLE_INTERVAL_SECONDS",
            0.001,
        ), patch(
            "asterion.applications.prime_agent.operator.p1b_development_docker._PROVISIONAL_SETTLE_SECONDS",
            0.004,
        ), patch(
            "asterion.applications.prime_agent.operator.p1b_development_docker._PROVISIONAL_FINAL_GRACE_SECONDS",
            0.005,
        ), patch.object(p1b_docker, "monotonic", clock), patch.object(
            docker_cli, "monotonic", clock,
        ), patch.object(
            p1b_docker.asyncio, "sleep", advance,
        ):
            await subject._compensate_provisional("prime-p1b-provisional")
        self.assertEqual(runner.remove_count, 6)
        self.assertEqual(runner.inspect_count, 6)
        self.assertEqual(runner.argv[-1][-5:], ("container", "inspect", "--format", "{{.Id}}", "prime-p1b-provisional"))
