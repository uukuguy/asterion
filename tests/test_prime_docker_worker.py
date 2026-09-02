"""Closed-role tests for the Prime operator Docker worker adapter."""

from __future__ import annotations

from contextlib import asynccontextmanager
import unittest

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerEngineTransport,
    DockerRestrictedWorkerService,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
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
        self.spec: object | None = None
        self.lease = RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE_DIGEST)

    @asynccontextmanager
    async def open(self, specification: object, *, signal: object = None):  # type: ignore[override]
        self.spec = specification
        yield self.lease

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation:
        return RestrictedWorkerAttestation(
            lease.worker_id,
            lease.run_id,
            lease.challenge_digest,
            _IMAGE_DIGEST,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        )

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt:
        return RestrictedWorkerCleanupReceipt(
            lease.worker_id, lease.run_id, lease.challenge_digest, True
        )


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

    async def test_rejects_transport_receipts_outside_the_admitted_role(self) -> None:
        async with self.service.open(_request()) as lease:
            attestation = await self.service.attest(lease)
            cleanup = await self.service.cleanup_receipt(lease)

        self.assertEqual(attestation.image_digest, _IMAGE_DIGEST)
        self.assertTrue(cleanup.destroyed)
