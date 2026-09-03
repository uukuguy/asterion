"""Provider-free contract tests for the sealed P2 worker facade."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import unittest

from asterion.applications.prime_agent.operator.programmatic_long_context_worker import (
    ProgrammaticLongContextBrokerRelay,
    ProgrammaticLongContextDockerWorker,
)
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
    ProgrammaticLongContextCompletion,
    canonical_programmatic_long_context_completion_bytes,
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
        self.removed_lease: RestrictedWorkerLease | None = None
        self.env: object = None
        self.raw = canonical_programmatic_long_context_completion_bytes(
            ProgrammaticLongContextCompletion(
                "sha256:" + "c" * 64,
                "sha256:" + "c" * 64,
                "sha256:" + "d" * 64,
            )
        )
        self.lease: RestrictedWorkerLease | None = None

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
        self.lease = RestrictedWorkerLease(
            "worker-1", role_id, "run-1", _CHALLENGE, workload_digest
        )
        return self.lease

    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
        return self.raw

    async def remove(self, lease: RestrictedWorkerLease) -> None:
        self.removed = True
        self.removed_lease = lease


class _Broker:
    def __init__(self) -> None:
        self.revoked = False
        self.quiescent = False

    async def request(self, body: bytes) -> bytes:
        return b"response"

    async def revoke(self) -> None:
        self.revoked = True
        self.quiescent = True


class _BlockingRemoveEngine(_Engine):
    def __init__(self) -> None:
        super().__init__()
        self.started, self.release = asyncio.Event(), asyncio.Event()

    async def remove(self, lease: RestrictedWorkerLease) -> None:
        self.started.set()
        await self.release.wait()
        await super().remove(lease)


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
            "sha256:" + sha256(engine.raw).hexdigest(),
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

    async def test_rejects_noncanonical_completion_and_execution_after_destruction(
        self,
    ) -> None:
        engine = _Engine()
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=engine
        )
        context = service.open(_request())
        lease = await context.__aenter__()
        engine.raw = b'{"arbitrary":"result"}'
        with self.assertRaises(RestrictedWorkerError):
            await service.execution_receipt(lease)
        with self.assertRaises(RestrictedWorkerError):
            await context.__aexit__(None, None, None)
        with self.assertRaises(RestrictedWorkerError):
            await service.execution_receipt(lease)
        with self.assertRaises(RestrictedWorkerError):
            await service.cleanup_receipt(lease)

    async def test_cleanup_receipt_requires_execution_and_is_one_shot(self) -> None:
        engine = _Engine()
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=engine
        )
        with self.assertRaises(RestrictedWorkerError):
            async with service.open(_request()) as lease:
                pass
        self.assertTrue(engine.removed)
        engine = _Engine()
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=engine
        )
        async with service.open(_request()) as lease:
            await service.execution_receipt(lease)
        self.assertTrue((await service.cleanup_receipt(lease)).destroyed)
        with self.assertRaises(RestrictedWorkerError):
            await service.cleanup_receipt(lease)

    async def test_rejecting_returned_lease_still_removes_it(self) -> None:
        engine = _Engine()
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=engine
        )
        original = engine.launch

        async def wrong_lease(**kwargs: object) -> RestrictedWorkerLease:
            lease = await original(**kwargs)  # type: ignore[arg-type]
            return RestrictedWorkerLease(
                "worker-2",
                lease.role_id,
                "wrong-run",
                lease.challenge_digest,
                lease.workload_digest,
            )

        engine.launch = wrong_lease  # type: ignore[method-assign]
        with self.assertRaises(RestrictedWorkerError):
            async with service.open(_request()):
                pass
        self.assertTrue(engine.removed)
        self.assertEqual(
            engine.removed_lease.worker_id if engine.removed_lease else None, "worker-2"
        )

    async def test_relay_consumes_one_request_even_when_the_request_fails(self) -> None:
        broker = _Broker()
        relay = ProgrammaticLongContextBrokerRelay(broker)
        self.assertEqual(await relay.request(b"one"), b"response")
        with self.assertRaises(RestrictedWorkerError):
            await relay.request(b"two")
        await relay.close()
        self.assertTrue(broker.revoked)

    async def test_cancellation_waits_for_removal_then_preserves_cancellation(
        self,
    ) -> None:
        engine = _BlockingRemoveEngine()
        service = ProgrammaticLongContextDockerWorker(
            image_digest=_IMAGE, engine=engine
        )
        context = service.open(_request())
        lease = await context.__aenter__()
        await service.execution_receipt(lease)
        exiting = asyncio.create_task(context.__aexit__(None, None, None))
        await engine.started.wait()
        exiting.cancel()
        await asyncio.sleep(0)
        self.assertFalse(engine.removed)
        engine.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await exiting
        self.assertTrue(engine.removed)
        self.assertTrue((await service.cleanup_receipt(lease)).destroyed)
