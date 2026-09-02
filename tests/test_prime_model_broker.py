"""Provider-free tests for Prime's host-private model mediation coordinator."""

from __future__ import annotations

import asyncio
import time
import unittest

import asterion.applications.prime_agent.operator.model_broker as model_broker
from asterion.applications.prime_agent.operator.launcher_barrier import PrimeLauncherBarrier
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerError, PrimeModelChannel, Provider, _HostModelCoordinator,
    _new_host_coordinator,
)
from asterion.services.bounded_model_session import BoundedModelSessionLease, BoundedModelSessionRequest
from asterion.services.restricted_worker import RestrictedWorkerAttestation, RestrictedWorkerLease


_CHALLENGE = "sha256:" + "a" * 64


def _session(**changes: object) -> BoundedModelSessionRequest:
    values: dict[str, object] = {"run_id": "run-1", "max_requests": 2, "max_input_bytes": 12,
        "max_output_bytes": 12, "deadline_seconds": 10}
    values.update(changes)
    return BoundedModelSessionRequest(**values)  # type: ignore[arg-type]


def _worker() -> RestrictedWorkerLease:
    return RestrictedWorkerLease("worker-1", "run-1", _CHALLENGE)


def _barrier() -> PrimeLauncherBarrier:
    worker = _worker()
    barrier = PrimeLauncherBarrier(run_id="run-1", challenge_digest=_CHALLENGE)
    barrier.admit(worker, RestrictedWorkerAttestation(
        worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE,
        image_digest="sha256:" + "b" * 64, network_isolated=True, root_read_only=True,
        workspace_disposable=True, credentials_absent=True, kernel_credential_absent=True,
        source_read_only=True, resource_limited=True))
    return barrier


def _host(provider: Provider, **changes: object) -> _HostModelCoordinator:
    return _new_host_coordinator(
        lease=BoundedModelSessionLease("session-1", "run-1"), session=_session(**changes),
        worker=_worker(), barrier=_barrier(), provider=provider, session_id="session-1", worker_id="worker-1",
        run_id="run-1", challenge_digest=_CHALLENGE, cleanup_grace_seconds=0.05)


class TestPrimeModelBroker(unittest.IsolatedAsyncioTestCase):
    def test_normal_worker_scope_has_only_channel_not_host_routes(self) -> None:
        async def provider(_body: bytes) -> bytes:
            return b"ok"

        channel = _host(provider)._activate()
        self.assertIsInstance(channel, PrimeModelChannel)
        self.assertEqual(set(model_broker.__all__), {
            "PrimeModelBrokerError", "PrimeModelBrokerUsage", "PrimeModelBrokerReceipt", "PrimeModelChannel", "Provider"})
        self.assertEqual({name for name in dir(channel) if not name.startswith("_")}, {"request"})

    async def test_charges_attempted_output_before_rejecting_cap(self) -> None:
        async def provider(body: bytes) -> bytes:
            return b"123456" if body == b"one" else b"1234567"

        host = _host(provider)
        channel = host._activate()
        self.assertEqual(await channel.request(b"one"), b"123456")
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"two")
        self.assertEqual(host.usage().output_bytes, 13)

    async def test_provider_cancellations_are_generic_but_outer_cancellation_propagates(self) -> None:
        def sync_cancel(_body: bytes) -> object:
            raise asyncio.CancelledError("SECRET-CREDENTIAL")

        async def async_cancel(_body: bytes) -> bytes:
            raise asyncio.CancelledError("SECRET-ENDPOINT")

        for provider in (sync_cancel, async_cancel):
            with self.subTest(provider=provider), self.assertRaises(PrimeModelBrokerError) as raised:
                await _host(provider)._activate().request(b"SECRET-PROMPT")  # type: ignore[arg-type]
            self.assertNotIn("SECRET", str(raised.exception))

        started = asyncio.Event()
        async def waiting(_body: bytes) -> bytes:
            started.set()
            await asyncio.Event().wait()
            return b"never"

        task = asyncio.create_task(_host(waiting)._activate().request(b"one"))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_deadline_cancels_provider_and_revoke_receipts_after_terminal_cleanup(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def provider(_body: bytes) -> bytes:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                return b"late"
            return b"never"

        host = _host(provider)
        host._deadline = time.monotonic() + 0.01  # noqa: SLF001
        request = asyncio.create_task(host._activate().request(b"one"))
        await started.wait()
        with self.assertRaises(PrimeModelBrokerError):
            await request
        self.assertEqual((await host.revoke()).status, "revoked")
        self.assertTrue(cancelled.is_set())

    async def test_cleanup_suppression_is_permanently_uncertain_without_receipt(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()
        async def suppressing(_body: bytes) -> bytes:
            started.set()
            while not release.is_set():
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    continue
            return b"late"

        host = _host(suppressing)
        host._deadline = time.monotonic() + 0.01  # noqa: SLF001
        request = asyncio.create_task(host._activate().request(b"one"))
        await started.wait()
        with self.assertRaises(PrimeModelBrokerError):
            await request
        with self.assertRaises(PrimeModelBrokerError):
            await host.revoke()
        release.set()
        await asyncio.sleep(0)
        with self.assertRaises(PrimeModelBrokerError):
            await host.revoke()

    async def test_revoke_waits_for_terminal_provider_and_closes_future_admission(self) -> None:
        started = asyncio.Event()
        async def provider(_body: bytes) -> bytes:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return b"ok"
            return b"never"

        host = _host(provider)
        channel = host._activate()
        request = asyncio.create_task(channel.request(b"one"))
        await started.wait()
        self.assertEqual((await host.revoke()).status, "revoked")
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"two")
        with self.assertRaises(PrimeModelBrokerError):
            await request
