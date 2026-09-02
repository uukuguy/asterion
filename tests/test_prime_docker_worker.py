"""Closed-role tests for the Prime operator Docker worker adapter."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerEngineTransport,
    DockerWorkerLauncherSelfCheck,
    DockerRestrictedWorkerService,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


_IMAGE_DIGEST = "sha256:" + "a" * 64
_CHALLENGE_DIGEST = "sha256:" + "b" * 64


def _request(**changes: object) -> RestrictedWorkerRequest:
    values: dict[str, object] = {
        "role_id": "prime.ipython-coding",
        "image_digest": _IMAGE_DIGEST,
        "run_id": "run-1",
        "challenge_digest": _CHALLENGE_DIGEST,
        "max_runtime_seconds": 300,
        "max_output_bytes": 65536,
    }
    values.update(changes)
    return RestrictedWorkerRequest(**values)  # type: ignore[arg-type]


class _Transport(DockerEngineTransport):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.spec: object | None = None
        self.lease = RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE_DIGEST)
        self.inspection = _safe_inspection()
        self.post_start_inspection = _safe_inspection()
        self.final_inspection = _safe_inspection()
        self.self_check = _safe_self_check()
        self.force_remove_error: Exception | None = None
        self.absence_error: Exception | None = None

    async def create(self, specification: object, *, signal: object = None) -> str:  # type: ignore[override]
        self.calls.append("create")
        self.spec = specification
        return "container-1"

    async def inspect(self, container_id: str) -> Mapping[str, object]:
        self.calls.append("inspect")
        self.assert_container_id(container_id)
        inspections = (
            self.inspection,
            self.post_start_inspection,
            self.final_inspection,
        )
        return inspections[self.calls.count("inspect") - 1]

    async def start(self, container_id: str) -> RestrictedWorkerLease:
        self.calls.append("start")
        self.assert_container_id(container_id)
        return self.lease

    async def launcher_self_check(
        self, container_id: str
    ) -> DockerWorkerLauncherSelfCheck:
        self.calls.append("launcher_self_check")
        self.assert_container_id(container_id)
        return self.self_check

    async def remove(self, container_id: str) -> None:
        self.calls.append("remove")
        self.assert_container_id(container_id)

    async def force_remove(self, container_id: str) -> None:
        self.calls.append("force_remove")
        self.assert_container_id(container_id)
        if self.force_remove_error is not None:
            raise self.force_remove_error

    async def assert_absent(self, container_id: str) -> None:
        self.calls.append("assert_absent")
        self.assert_container_id(container_id)
        if self.absence_error is not None:
            raise self.absence_error

    @staticmethod
    def assert_container_id(container_id: str) -> None:
        if container_id != "container-1":
            raise AssertionError("unexpected container identity")


def _safe_inspection() -> dict[str, object]:
    return {
        "image_id": _IMAGE_DIGEST,
        "repo_digests": (_IMAGE_DIGEST,),
        "network_mode": "none",
        "ports": (),
        "readonly_rootfs": True,
        "privileged": False,
        "cap_add": (),
        "cap_drop": ("ALL",),
        "security_opt": ("no-new-privileges", "seccomp=prime-ipython-coding"),
        "user": "65534:65534",
        "devices": (),
        "mounts": (),
        "binds": (),
        "volumes": (),
        "tmpfs": {
            "/workspace": {
                "size_bytes": 67108864,
                "options": ("nodev", "noexec", "nosuid"),
            }
        },
        "env": (
            "HOME=/workspace",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE=1",
        ),
        "pids_limit": 256,
        "memory": 536870912,
        "memory_swap": 536870912,
        "nano_cpus": 1000000000,
        "pid_namespace": "private",
        "ipc_namespace": "private",
        "uts_namespace": "private",
    }


def _safe_self_check(**changes: object) -> DockerWorkerLauncherSelfCheck:
    values: dict[str, object] = {
        "nonloopback_network_absent": True,
        "root_read_only": True,
        "workspace_only_writable": True,
        "credentials_absent": True,
        "effective_capabilities": 0,
        "no_new_privileges": 1,
        "seccomp_mode": 2,
        "effective_user_id": 65534,
    }
    values.update(changes)
    return DockerWorkerLauncherSelfCheck(**values)  # type: ignore[arg-type]


class TestDockerRestrictedWorkerService(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.transport = _Transport()
        self.service = DockerRestrictedWorkerService(
            image_digest=_IMAGE_DIGEST, transport=self.transport
        )

    def test_rejects_an_unknown_role(self) -> None:
        with self.assertRaises(RestrictedWorkerError):
            self.service.request_for(_request(role_id="other.role"))

    def test_rejects_image_mismatch_and_relaxed_limits(self) -> None:
        cases = (
            _request(image_digest="sha256:" + "c" * 64),
            _request(max_runtime_seconds=301),
            _request(max_output_bytes=65537),
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaises(RestrictedWorkerError):
                self.service.request_for(request)

    def test_service_constructor_rejects_a_tag_like_role_image(self) -> None:
        with self.assertRaises(RestrictedWorkerError):
            DockerRestrictedWorkerService(image_digest="latest", transport=self.transport)

    async def test_opens_only_a_fixed_role_specification(self) -> None:
        async with self.service.open(_request(max_runtime_seconds=30)) as lease:
            self.assertEqual(lease, self.transport.lease)

        self.assertIsNotNone(self.transport.spec)
        fields = frozenset(vars(self.transport.spec))  # type: ignore[arg-type]
        self.assertEqual(
            fields,
            {
                "role_id",
                "image_digest",
                "run_id",
                "challenge_digest",
                "max_runtime_seconds",
                "max_output_bytes",
                "launcher_id",
                "user_id",
                "group_id",
            },
        )
        self.assertNotIn("command", fields)
        self.assertNotIn("environment", fields)
        self.assertNotIn("mounts", fields)

    async def test_creates_and_inspects_before_starting(self) -> None:
        context = self.service.open(_request())
        lease = await context.__aenter__()
        self.addAsyncCleanup(context.__aexit__, None, None, None)

        self.assertEqual(lease, self.transport.lease)
        self.assertEqual(self.transport.calls[:2], ["create", "inspect"])
        self.assertIn("start", self.transport.calls)

    async def test_revalidates_engine_safety_after_start_before_admission(self) -> None:
        context = self.service.open(_request())
        lease = await context.__aenter__()
        self.addAsyncCleanup(context.__aexit__, None, None, None)

        self.assertEqual(lease, self.transport.lease)
        self.assertEqual(
            self.transport.calls,
            ["create", "inspect", "start", "inspect", "launcher_self_check"],
        )

    async def test_unsafe_post_start_inspection_never_produces_an_attestation(self) -> None:
        self.transport.post_start_inspection["network_mode"] = "bridge"

        with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid"):
            await self.service.open(_request()).__aenter__()

        self.assertEqual(self.transport.calls, ["create", "inspect", "start", "inspect", "remove"])
        with self.assertRaises(RestrictedWorkerError):
            await self.service.attest(self.transport.lease)

    async def test_rejects_unsafe_launcher_self_checks_without_an_attestation(self) -> None:
        controls = (
            ("nonloopback_network_absent", False),
            ("root_read_only", False),
            ("workspace_only_writable", False),
            ("credentials_absent", False),
            ("effective_capabilities", 1),
            ("no_new_privileges", 0),
            ("seccomp_mode", 0),
            ("effective_user_id", 0),
        )
        for field, value in controls:
            with self.subTest(field=field):
                self.transport.calls.clear()
                self.transport.self_check = _safe_self_check(**{field: value})
                with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                    await self.service.open(_request(run_id="run-2")).__aenter__()
                self.assertEqual(
                    self.transport.calls,
                    ["create", "inspect", "start", "inspect", "launcher_self_check", "remove"],
                )
                self.assertNotIn("DockerWorkerLauncherSelfCheck", str(raised.exception))
                with self.assertRaises(RestrictedWorkerError):
                    await self.service.attest(self.transport.lease)

    def test_launcher_self_check_representation_is_redacted(self) -> None:
        self_check = _safe_self_check()

        self.assertEqual(repr(self_check), "DockerWorkerLauncherSelfCheck(redacted)")
        self.assertNotIn("65534", repr(self_check))

    async def test_unsafe_inspection_never_starts_and_is_redacted(self) -> None:
        controls = (
            ("network_mode", "bridge"),
            ("ports", ("published",)),
            ("readonly_rootfs", False),
            ("privileged", True),
            ("cap_add", ("NET_ADMIN",)),
            ("cap_drop", ()),
            ("security_opt", ("no-new-privileges",)),
            ("user", "0:0"),
            ("devices", ("device",)),
            ("mounts", ("host",)),
            ("binds", ("host",)),
            ("volumes", ("volume",)),
            ("tmpfs", {}),
            ("env", ("SECRET=sentinel",)),
            ("pids_limit", 0),
            ("memory", 0),
            ("memory_swap", 1),
            ("nano_cpus", 0),
            ("image_id", "sha256:" + "c" * 64),
            ("repo_digests", ("sha256:" + "c" * 64,)),
            ("pid_namespace", "host"),
            ("ipc_namespace", "host"),
            ("uts_namespace", "host"),
            ("unexpected", True),
        )
        for field, value in controls:
            with self.subTest(field=field):
                self.transport.calls.clear()
                inspection = _safe_inspection()
                inspection[field] = value
                self.transport.inspection = inspection
                with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
                    await self.service.open(_request(run_id="run-2")).__aenter__()
                self.assertNotIn("start", self.transport.calls)
                self.assertNotIn("sentinel", str(raised.exception))

    async def test_missing_inspection_control_never_starts(self) -> None:
        inspection = _safe_inspection()
        del inspection["network_mode"]
        self.transport.inspection = inspection

        with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid"):
            await self.service.open(_request()).__aenter__()

        self.assertEqual(self.transport.calls, ["create", "inspect", "remove"])

    async def test_returns_only_attestation_and_cleanup_for_admitted_lease(self) -> None:
        async with self.service.open(_request()) as lease:
            attestation = await self.service.attest(lease)
        cleanup = await self.service.cleanup_receipt(lease)

        self.assertEqual(attestation.image_digest, _IMAGE_DIGEST)
        self.assertTrue(cleanup.destroyed)

    async def test_verified_teardown_inspects_removes_and_proves_absence_in_order(self) -> None:
        async with self.service.open(_request()) as lease:
            pass

        self.assertEqual(
            self.transport.calls,
            [
                "create", "inspect", "start", "inspect", "launcher_self_check",
                "inspect", "force_remove", "assert_absent",
            ],
        )
        self.assertTrue((await self.service.cleanup_receipt(lease)).destroyed)

    async def test_unsafe_final_inspection_fails_closed_without_a_cleanup_receipt(self) -> None:
        self.transport.final_inspection["env"] = ("SECRET=sentinel",)
        context = self.service.open(_request())
        lease = await context.__aenter__()

        with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
            await context.__aexit__(None, None, None)

        self.assertNotIn("sentinel", str(raised.exception))
        self.assertEqual(
            self.transport.calls,
            [
                "create", "inspect", "start", "inspect", "launcher_self_check",
                "inspect", "force_remove",
            ],
        )
        with self.assertRaises(RestrictedWorkerError):
            await self.service.cleanup_receipt(lease)

    async def test_force_remove_failure_fails_closed_without_a_cleanup_receipt(self) -> None:
        self.transport.force_remove_error = RuntimeError("sentinel force-remove failure")
        context = self.service.open(_request())
        lease = await context.__aenter__()

        with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
            await context.__aexit__(None, None, None)

        self.assertNotIn("sentinel", str(raised.exception))
        self.assertEqual(self.transport.calls[-2:], ["inspect", "force_remove"])
        with self.assertRaises(RestrictedWorkerError):
            await self.service.cleanup_receipt(lease)

    async def test_absence_assertion_failure_fails_closed_without_a_cleanup_receipt(self) -> None:
        self.transport.absence_error = RuntimeError("sentinel absence failure")
        context = self.service.open(_request())
        lease = await context.__aenter__()

        with self.assertRaisesRegex(RestrictedWorkerError, "restricted worker value is invalid") as raised:
            await context.__aexit__(None, None, None)

        self.assertNotIn("sentinel", str(raised.exception))
        self.assertEqual(self.transport.calls[-3:], ["inspect", "force_remove", "assert_absent"])
        with self.assertRaises(RestrictedWorkerError):
            await self.service.cleanup_receipt(lease)

    async def test_teardown_erases_active_state_and_receipt_tombstone_is_exact_and_one_time(self) -> None:
        async with self.service.open(_request()) as lease:
            pass

        self.assertNotIn(lease.worker_id, self.service._leases)
        self.assertNotIn("container-1", repr(self.service._cleanup_tombstones))
        self.assertEqual(
            repr(next(iter(self.service._cleanup_tombstones.values()))),
            "_CleanupTombstone(redacted)",
        )
        forged = RestrictedWorkerLease(lease.worker_id, "run-2", _CHALLENGE_DIGEST)
        with self.assertRaises(RestrictedWorkerError):
            await self.service.cleanup_receipt(forged)
        cleanup = await self.service.cleanup_receipt(lease)
        self.assertEqual(
            (cleanup.worker_id, cleanup.run_id, cleanup.challenge_digest),
            (lease.worker_id, lease.run_id, lease.challenge_digest),
        )
        with self.assertRaises(RestrictedWorkerError):
            await self.service.cleanup_receipt(lease)
