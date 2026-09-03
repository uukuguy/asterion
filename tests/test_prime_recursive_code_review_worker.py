"""Provider-free contract tests for sealed P3 lifecycle facades."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
import unittest

from asterion.applications.prime_agent.operator.recursive_code_review_release import (
    canonical_recursive_code_review_frame,
)
from asterion.applications.prime_agent.operator.recursive_code_review_worker import (
    RecursiveCodeReviewBroker, RecursiveCodeReviewDockerWorker,
)
from asterion.applications.prime_agent.operator.recursive_code_review_workload import (
    RECURSIVE_CODE_REVIEW_P3_ROLE_ID, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerError, RestrictedWorkerLease, RestrictedWorkerRequest,
)

_IMAGE = "sha256:" + "a" * 64
_CHALLENGE = "sha256:" + "b" * 64


def _request(**changes: object) -> RestrictedWorkerRequest:
    values: dict[str, object] = {
        "role_id": RECURSIVE_CODE_REVIEW_P3_ROLE_ID, "image_digest": _IMAGE,
        "run_id": "run-1", "challenge_digest": _CHALLENGE,
        "workload_digest": RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
        "max_runtime_seconds": 1, "max_output_bytes": 53260,
    }
    values.update(changes)
    return RestrictedWorkerRequest(**values)  # type: ignore[arg-type]


def _completion() -> bytes:
    lines: list[bytes] = []
    # The fixture frames are a static private protocol corpus; reconstructing them
    # with fake lease identity keeps this test independent of a Node/Docker launch.
    # Build the canonical stream from the source parser's existing test fixture.
    from tests.test_prime_recursive_code_review_launcher_protocol import _stream

    for raw in _stream().rstrip(b"\n").split(b"\n"):
        value = json.loads(raw)
        lines.append(canonical_recursive_code_review_frame(
            worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE,
            workload_digest=RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
            sequence=value["sequence"], kind=value["kind"], payload=value["payload"],
        ))
    return b"\n".join(lines) + b"\n"


class _Engine:
    def __init__(self) -> None:
        self.raw = _completion()
        self.removed: RestrictedWorkerLease | None = None
        self.args: tuple[object, ...] | None = None

    async def launch(self, **kwargs: object) -> RestrictedWorkerLease:
        self.args = tuple(kwargs[name] for name in ("role_id", "image_digest", "workload_digest", "env", "entrypoint", "seccomp"))
        return RestrictedWorkerLease("worker-1", RECURSIVE_CODE_REVIEW_P3_ROLE_ID, "run-1", _CHALLENGE, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST)

    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
        return self.raw

    async def remove(self, lease: RestrictedWorkerLease) -> None:
        self.removed = lease


class _Endpoint:
    def __init__(self, result: bytes) -> None:
        self.result, self.events = result, []

    async def admit_root(self, lease: RestrictedWorkerLease) -> None:
        self.events.append("admit")

    async def relay_once(self, body: bytes) -> bytes:
        self.events.append("relay")
        return self.result

    async def revoke(self) -> None:
        self.events.append("revoke")


class _BlockingEngine(_Engine):
    def __init__(self) -> None:
        super().__init__()
        self.started, self.release = asyncio.Event(), asyncio.Event()

    async def remove(self, lease: RestrictedWorkerLease) -> None:
        self.started.set()
        await self.release.wait()
        await super().remove(lease)


class TestRecursiveCodeReviewWorker(unittest.IsolatedAsyncioTestCase):
    async def test_exact_p3_worker_parses_canonical_completion_before_hash(self) -> None:
        engine = _Engine()
        worker = RecursiveCodeReviewDockerWorker(image_digest=_IMAGE, engine=engine)
        async with worker.open(_request()) as lease:
            receipt = await worker.execution_receipt(lease)
        self.assertEqual(receipt.result_digest, "sha256:" + sha256(engine.raw).hexdigest())
        self.assertEqual(engine.args, (RECURSIVE_CODE_REVIEW_P3_ROLE_ID, _IMAGE, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST, (), "/usr/local/bin/prime-recursive-code-review.mjs", "prime-recursive-code-review"))
        self.assertEqual(engine.removed, lease)
        self.assertTrue((await worker.cleanup_receipt(lease)).destroyed)

    async def test_rejects_p1_p2_and_noncanonical_bytes(self) -> None:
        worker = RecursiveCodeReviewDockerWorker(image_digest=_IMAGE, engine=_Engine())
        for request in (_request(role_id="prime.ipython-coding"), _request(role_id="prime.programmatic-long-context")):
            with self.subTest(request=request), self.assertRaises(RestrictedWorkerError):
                worker.request_for(request)
        context = worker.open(_request())
        lease = await context.__aenter__()
        worker._engine.raw = b'{"not":"canonical"}'  # type: ignore[attr-defined]
        with self.assertRaises(RestrictedWorkerError):
            await worker.execution_receipt(lease)
        with self.assertRaises(RestrictedWorkerError):
            await context.__aexit__(None, None, None)

    async def test_broker_is_one_use_and_requires_causal_completed_trace_before_revoke(self) -> None:
        endpoint = _Endpoint(_completion())
        broker = RecursiveCodeReviewBroker(endpoint)
        lease = RestrictedWorkerLease("worker-1", RECURSIVE_CODE_REVIEW_P3_ROLE_ID, "run-1", _CHALLENGE, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST)
        await broker.admit_root(lease)
        self.assertEqual(await broker.relay_once(b"sealed"), _completion())
        with self.assertRaises(RestrictedWorkerError):
            await broker.relay_once(b"again")
        await broker.revoke()
        self.assertEqual(endpoint.events, ["admit", "relay", "revoke"])

    async def test_rejected_lease_and_cancelled_cleanup_are_removed(self) -> None:
        engine = _Engine()
        worker = RecursiveCodeReviewDockerWorker(image_digest=_IMAGE, engine=engine)
        original = engine.launch

        async def wrong_lease(**kwargs: object) -> RestrictedWorkerLease:
            lease = await original(**kwargs)
            return RestrictedWorkerLease("worker-2", lease.role_id, "wrong-run", lease.challenge_digest, lease.workload_digest)

        engine.launch = wrong_lease  # type: ignore[method-assign]
        with self.assertRaises(RestrictedWorkerError):
            async with worker.open(_request()):
                pass
        self.assertEqual(engine.removed.worker_id if engine.removed else None, "worker-2")

        blocking = _BlockingEngine()
        worker = RecursiveCodeReviewDockerWorker(image_digest=_IMAGE, engine=blocking)
        context = worker.open(_request())
        lease = await context.__aenter__()
        await worker.execution_receipt(lease)
        exiting = asyncio.create_task(context.__aexit__(None, None, None))
        await blocking.started.wait()
        exiting.cancel()
        blocking.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await exiting
        self.assertEqual(blocking.removed, lease)
        self.assertTrue((await worker.cleanup_receipt(lease)).destroyed)
