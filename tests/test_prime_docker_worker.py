"""Closed-role tests for the Prime operator Docker worker adapter."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerEngineTransport,
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

    async def create(self, specification: object, *, signal: object = None) -> str:  # type: ignore[override]
        self.calls.append("create")
        self.spec = specification
        return "container-1"

    async def inspect(self, container_id: str) -> Mapping[str, object]:
        self.calls.append("inspect")
        self.assert_container_id(container_id)
        return self.inspection

    async def start(self, container_id: str) -> RestrictedWorkerLease:
        self.calls.append("start")
        self.assert_container_id(container_id)
        return self.lease

    async def remove(self, container_id: str) -> None:
        self.calls.append("remove")
        self.assert_container_id(container_id)

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
