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
_WORKLOAD = "sha256:" + "b" * 64


def _session(**changes: object) -> BoundedModelSessionRequest:
    values: dict[str, object] = {"run_id": "run-1", "max_requests": 2,
        "max_input_tokens": 12, "max_output_tokens": 12, "max_input_bytes": 12,
        "max_output_bytes": 12, "max_cost_microunits": 12, "deadline_seconds": 10}
    values.update(changes)
    return BoundedModelSessionRequest(**values)  # type: ignore[arg-type]


def _worker() -> RestrictedWorkerLease:
    return RestrictedWorkerLease(
        "worker-1", "prime.ipython-coding", "run-1", _CHALLENGE, _WORKLOAD
    )


def _barrier() -> PrimeLauncherBarrier:
    worker = _worker()
    barrier = PrimeLauncherBarrier(
        role_id="prime.ipython-coding",
        run_id="run-1",
        challenge_digest=_CHALLENGE,
        workload_digest=_WORKLOAD,
    )
    barrier.admit(worker, RestrictedWorkerAttestation(
        worker_id="worker-1", role_id="prime.ipython-coding", run_id="run-1", challenge_digest=_CHALLENGE, workload_digest=_WORKLOAD,
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
    async def test_normal_worker_scope_has_only_channel_not_host_routes(self) -> None:
        calls = 0
        async def provider(_body: bytes) -> bytes:
            nonlocal calls
            calls += 1
            return b"ok"

        host = _host(provider)
        channel = host._activate()
        self.assertIsInstance(channel, PrimeModelChannel)
        self.assertEqual(set(model_broker.__all__), {
            "PrimeModelBrokerError", "PrimeModelBrokerUsage", "PrimeModelBrokerReceipt", "PrimeModelChannel", "Provider"})
        self.assertEqual({name for name in dir(channel) if not name.startswith("_")}, {"request"})
        for name in dir(channel):
            self.assertFalse(any(word in name.lower() for word in (
                "coordinator", "broker", "provider", "barrier", "release", "activate", "revoke", "usage")))
        endpoint = channel._transport  # noqa: SLF001 - ordinary worker object traversal
        for name in dir(endpoint):
            self.assertFalse(any(word in name.lower() for word in (
                "coordinator", "broker", "provider", "barrier", "release", "activate", "revoke", "usage")))
        self.assertEqual(calls, 0)
        await host.revoke()

    async def test_charges_attempted_output_before_rejecting_cap(self) -> None:
        calls = 0
        async def provider(body: bytes) -> bytes:
            nonlocal calls
            calls += 1
            return b"123456" if body == b"one" else b"1234567"

        host = _host(provider)
        channel = host._activate()
        self.assertEqual(await channel.request(b"one"), b"123456")
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"two")
        self.assertEqual(host.usage().output_bytes, 13)
        with self.assertRaises(PrimeModelBrokerError):
            await channel.request(b"two")
        self.assertEqual(calls, 2)

    async def test_provider_cancellations_are_generic_but_outer_cancellation_propagates(self) -> None:
        def sync_cancel(_body: bytes) -> object:
            raise asyncio.CancelledError("SECRET-CREDENTIAL")

        async def async_cancel(_body: bytes) -> bytes:
            raise asyncio.CancelledError("SECRET-ENDPOINT")

        for provider in (sync_cancel, async_cancel):
            host = _host(provider)  # type: ignore[arg-type]
            with self.subTest(provider=provider), self.assertRaises(PrimeModelBrokerError) as raised:
                await host._activate().request(b"SECRET-PROMPT")
            self.assertNotIn("SECRET", str(raised.exception))
            await host.revoke()

        started = asyncio.Event()
        async def waiting(_body: bytes) -> bytes:
            started.set()
            await asyncio.Event().wait()
            return b"never"

        host = _host(waiting)
        task = asyncio.create_task(host._activate().request(b"one"))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await host.revoke()

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
