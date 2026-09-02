"""Provider-free checks for the enforcing Prime operator model broker."""

from __future__ import annotations

import asyncio
import time
import unittest

from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBroker,
    PrimeModelBrokerError,
    PrimeModelChannel,
    Provider,
    _LauncherReleaseProof,
    _launcher_release_proof,
)
from asterion.applications.prime_agent.operator.launcher_barrier import PrimeLauncherBarrier
from asterion.services.bounded_model_session import (
    BoundedModelSessionLease,
    BoundedModelSessionRequest,
)
from asterion.services.restricted_worker import RestrictedWorkerAttestation, RestrictedWorkerLease


_CHALLENGE = "sha256:" + "a" * 64


async def _bytes_result() -> bytes:
    return b"ok"


def _session(**changes: object) -> BoundedModelSessionRequest:
    values: dict[str, object] = dict(run_id="run-1", max_requests=2, max_input_bytes=12,
        max_output_bytes=12, deadline_seconds=10)
    values.update(changes)
    return BoundedModelSessionRequest(**values)  # type: ignore[arg-type]


def _broker(provider: Provider, **changes: object) -> PrimeModelBroker:
    session = _session(**changes)
    return PrimeModelBroker(
        lease=BoundedModelSessionLease("session-1", "run-1"), session=session,
        worker=RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE), provider=provider,
        worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE,
    )


def _channel(broker: PrimeModelBroker) -> PrimeModelChannel:
    worker = RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE)
    barrier = PrimeLauncherBarrier(run_id="run-1", challenge_digest=_CHALLENGE)
    barrier.admit(worker, RestrictedWorkerAttestation(
        worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE,
        image_digest="sha256:" + "b" * 64, network_isolated=True, root_read_only=True,
        workspace_disposable=True, credentials_absent=True, kernel_credential_absent=True,
        source_read_only=True, resource_limited=True,
    ))
    proofs: list[_LauncherReleaseProof] = []
    barrier.release(worker, lambda: proofs.append(_launcher_release_proof(barrier, worker, broker)))
    return broker._release_after_launcher(proofs[0])


class TestPrimeModelBroker(unittest.IsolatedAsyncioTestCase):
    async def test_reserves_attempt_before_provider_call_and_counts_retries(self) -> None:
        started = asyncio.Event()
        unblock = asyncio.Event()
        calls: list[bytes] = []

        async def provider(body: bytes) -> bytes:
            calls.append(body)
            started.set()
            await unblock.wait()
            return b"ok"

        broker = _broker(provider)
        channel = _channel(broker)
        pending = asyncio.create_task(channel.request(b"one"))
        await started.wait()
        self.assertEqual(broker.usage().request_count, 1)
        unblock.set()
        self.assertEqual(await pending, b"ok")
        self.assertEqual(await channel.request(b"two"), b"ok")
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"three")
        self.assertEqual(calls, [b"one", b"two"])

    async def test_enforces_cumulative_input_and_output_limits(self) -> None:
        async def provider(body: bytes) -> bytes:
            return b"123456" if body == b"one" else b"1234567"

        broker = _broker(provider, max_input_bytes=5)
        channel = _channel(broker)
        self.assertEqual(await channel.request(b"one"), b"123456")
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"two")
        self.assertEqual(broker.usage().input_bytes, 3)

        output_broker = _broker(provider)
        output_channel = _channel(output_broker)
        self.assertEqual(await output_channel.request(b"one"), b"123456")
        with self.assertRaises(PrimeModelBrokerError):
            await output_channel.request(b"two")
        self.assertEqual(output_broker.usage().output_bytes, 13)

    async def test_times_out_provider_call_and_revoke_does_not_wait_forever(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def provider(_body: bytes) -> bytes:
            started.set()
            try:
                await asyncio.Event().wait()
                return b"never"
            except asyncio.CancelledError:
                cancelled.set()
                await asyncio.sleep(0.02)
                return b"late"

        broker = _broker(provider)
        broker._deadline = time.monotonic() + 0.01  # noqa: SLF001 - bounded provider await
        request = asyncio.create_task(_channel(broker).request(b"one"))
        await started.wait()
        with self.assertRaises(PrimeModelBrokerError):
            await request
        receipt = await asyncio.wait_for(broker.revoke(), timeout=0.1)
        self.assertEqual(receipt.status, "revoked")
        await cancelled.wait()
        await asyncio.sleep(0.03)

    async def test_provider_cancellation_is_redacted_but_external_cancellation_propagates(self) -> None:
        async def cancelled_provider(_body: bytes) -> bytes:
            raise asyncio.CancelledError("SECRET-PROVIDER-CREDENTIAL")

        with self.assertRaises(PrimeModelBrokerError) as raised:
            await _channel(_broker(cancelled_provider)).request(b"one")
        self.assertNotIn("SECRET-PROVIDER-CREDENTIAL", str(raised.exception))

        started = asyncio.Event()

        async def waiting_provider(_body: bytes) -> bytes:
            started.set()
            await asyncio.Event().wait()
            return b"never"

        task = asyncio.create_task(_channel(_broker(waiting_provider)).request(b"one"))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_rejects_directly_forged_release_proof(self) -> None:
        broker = _broker(lambda _body: _bytes_result())
        worker = RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE)
        with self.assertRaises((PrimeModelBrokerError, TypeError)):
            broker._release_after_launcher(_LauncherReleaseProof(worker))  # type: ignore[call-arg]

    async def test_rejects_concurrent_expired_and_revoked_calls_without_provider_call(self) -> None:
        started = asyncio.Event()
        unblock = asyncio.Event()
        calls = 0

        async def provider(_body: bytes) -> bytes:
            nonlocal calls
            calls += 1
            started.set()
            await unblock.wait()
            return b"ok"

        broker = _broker(provider)
        channel = _channel(broker)
        pending = asyncio.create_task(channel.request(b"one"))
        await started.wait()
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"two")
        unblock.set()
        await pending
        await broker.revoke()
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"three")
        self.assertEqual(calls, 1)

        ticks = iter((100.0, 111.0))
        expired = PrimeModelBroker(
            lease=BoundedModelSessionLease("session-1", "run-1"), session=_session(),
            worker=RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE), provider=provider,
            worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE,
            monotonic=lambda: next(ticks),
        )
        with self.assertRaises(PrimeModelBrokerError):
            await _channel(expired).request(b"late")
        self.assertEqual(calls, 1)

    async def test_revoke_waits_for_inflight_and_receipt_has_exact_body_free_identity(self) -> None:
        started = asyncio.Event()
        unblock = asyncio.Event()

        async def provider(_body: bytes) -> bytes:
            started.set()
            await unblock.wait()
            return b"ok"

        broker = _broker(provider, max_input_bytes=20)
        task = asyncio.create_task(_channel(broker).request(b"SECRET-PROMPT"))
        await started.wait()
        revoked = asyncio.create_task(broker.revoke())
        await asyncio.sleep(0)
        self.assertFalse(revoked.done())
        unblock.set()
        await task
        receipt = await revoked
        self.assertEqual((receipt.session_id, receipt.run_id, receipt.worker_id, receipt.challenge_digest),
            ("session-1", "run-1", "worker-1", _CHALLENGE))
        self.assertEqual(receipt.status, "revoked")
        rendered = repr(receipt)
        for secret in ("SECRET-PROMPT", "SECRET-ANSWER", "credential", "provider", "model", "endpoint", "socket", "token"):
            self.assertNotIn(secret, rendered)

    async def test_rejects_identity_substitutions_and_redacts_errors(self) -> None:
        async def provider(_body: bytes) -> bytes:
            raise RuntimeError("provider credential endpoint SECRET-PROMPT")

        for changes in (
            {"lease": BoundedModelSessionLease("session-2", "run-1")},
            {"session": _session(run_id="run-2")},
            {"worker": RestrictedWorkerLease("worker-2", "run-1", _CHALLENGE)},
            {"worker": RestrictedWorkerLease("worker-1", "run-1", "sha256:" + "c" * 64)},
        ):
            values = dict(lease=BoundedModelSessionLease("session-1", "run-1"), session=_session(),
                worker=RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE), provider=provider,
                worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE)
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(PrimeModelBrokerError):
                PrimeModelBroker(**values)  # type: ignore[arg-type]
        broker = _broker(provider)
        with self.assertRaises(PrimeModelBrokerError) as raised:
            await _channel(broker).request(b"SECRET-PROMPT")
        self.assertNotIn("SECRET-PROMPT", str(raised.exception))
