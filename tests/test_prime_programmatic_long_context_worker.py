"""Provider-free contract tests for the sealed P2 worker facade."""

from __future__ import annotations

from hashlib import sha256
import unittest

from asterion.applications.prime_agent.operator.programmatic_long_context_worker import (
    ProgrammaticLongContextBrokerRelay,
    ProgrammaticLongContextDockerWorker,
)
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)

_IMAGE = "sha256:" + "a" * 64
_CHALLENGE = "sha256:" + "b" * 64


def _request(**changes: object) -> RestrictedWorkerRequest:
    values: dict[str, object] = dict(
        role_id="prime.programmatic-long-context",
        image_digest=_IMAGE,
        run_id="run-1",
        challenge_digest=_CHALLENGE,
        workload_digest=PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
        max_runtime_seconds=30,
        max_output_bytes=4096,
    )
    values.update(changes)
    return RestrictedWorkerRequest(**values)  # type: ignore[arg-type]


class _Engine:
    def __init__(self) -> None:
        self.removed = False
        self.env: object = None

    async def launch(
        self,
        *,
        role_id: str,
        image_digest: str,
        workload_digest: str,
        env: tuple[str, ...],
        entrypoint: str,
        seccomp: str,
        signal: object,
    ) -> RestrictedWorkerLease:
        self.env = env
        if (role_id, image_digest, workload_digest, entrypoint, seccomp) != (
            "prime.programmatic-long-context",
            _IMAGE,
            PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
            "/usr/local/bin/prime-programmatic-long-context.mjs",
            "prime-programmatic-long-context",
        ):
            raise ValueError
        return RestrictedWorkerLease(
            "worker-1", role_id, "run-1", _CHALLENGE, workload_digest
        )

    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
        return b'{"canonical":"p2-completion"}'

    async def remove(self, lease: RestrictedWorkerLease) -> None:
        self.removed = True


class _Broker:
    def __init__(self) -> None:
        self.revoked = False
        self.quiescent = False

    async def request(self, body: bytes) -> bytes:
        return b"response"

    async def revoke(self) -> None:
        self.revoked = True
        self.quiescent = True


class TestProgrammaticLongContextWorker(unittest.IsolatedAsyncioTestCase):
    async def test_exact_p2_admission_empty_environment_and_canonical_receipt(
        self,
    ) -> None:
        engine = _Engine()
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=engine
        )
        async with service.open(_request()) as lease:
            receipt = await service.execution_receipt(lease)
        self.assertEqual(engine.env, ())
        self.assertEqual(
            receipt.result_digest,
            "sha256:" + sha256(b'{"canonical":"p2-completion"}').hexdigest(),
        )
        self.assertTrue(engine.removed)

    async def test_rejects_p1_role_and_p1_workload(self) -> None:
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=_Engine()
        )
        for request in (
            _request(role_id="prime.ipython-coding"),
            _request(workload_digest="sha256:" + "d" * 64),
        ):
            with (
                self.subTest(request=request),
                self.assertRaises(RestrictedWorkerError),
            ):
                service.request_for(request)

    async def test_broker_is_revoked_quiescent_before_cleanup(self) -> None:
        broker = _Broker()
        relay = ProgrammaticLongContextBrokerRelay(broker)
        self.assertEqual(await relay.request(b"sealed"), b"response")
        await relay.close()
        self.assertTrue(broker.revoked and broker.quiescent)
        with self.assertRaises(RestrictedWorkerError):
            await relay.request(b"again")
