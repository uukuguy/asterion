"""Finite research admission remains independent of any application's domain."""

import asyncio
from dataclasses import FrozenInstanceError
import os
import unittest
from unittest.mock import patch

from asterion.agents.prime import continuation
from asterion.agents.prime.execution import (
    ASTERION_PRIME_LIMITS, ASTERION_PRIME_RESEARCH_LIMITS, AsterionPrimeLimits,
)
from asterion.agents.prime.session import AsterionPrimeSession
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcEvent, PiRpcResult
from tests.test_asterion_prime_session import FakePiRpcSession, FakeSignal, SessionFixture


class RetainedResearchRpc(FakePiRpcSession):
    """A reusable native session retaining document-research findings."""

    def __init__(self, config):
        super().__init__(config, ())
        self.opens = self.closes = self.sequence = 0
        self.findings = []

    async def open(self, *, signal):
        self.opens += 1

    async def close(self):
        self.closes += 1

    async def run(self, *args, **kwargs):
        raise AssertionError("Research must retain its native session")

    async def prompt(self, prompt, *, signal, on_event):
        self.calls += 1
        self.findings.append(f"document-{self.calls}")
        self.sequence += 1
        event = PiRpcEvent(self.sequence, "agent_end", {})
        on_event(event)
        return PiRpcResult("research recorded", (event,), b"")


class TestPrimeContinuation(unittest.IsolatedAsyncioTestCase):
    def make_reusable(self, rpc_type=RetainedResearchRpc, **kwargs):
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        lease = fixture.binding.preflight()
        config = PiRpcConfig(command=("pi", *lease.command_args()), cwd=fixture.root,
            environment=dict(lease.environment), inherited_fds=lease.inherited_fds,
            deadline_seconds=5400)
        rpc = rpc_type(config)
        session = AsterionPrimeSession(rpc_session=rpc, extension_binding=fixture.binding,
            extension_lease=lease, approved_command=config.command,
            limits=ASTERION_PRIME_RESEARCH_LIMITS, reusable_session=True, **kwargs)
        return fixture, lease, rpc, session

    async def collect_reusable(self, session, signal=None):
        return [event async for event in session.run(RunRequest(run_id="documents-admission",
            input_text="Research documents", requested_capabilities=("prime.tool.ipython",)), signal=signal)]

    async def test_denied_first_round_does_not_open_native_session(self):
        async def deny(index, signal):
            return False

        fixture, lease, rpc, session = self.make_reusable(round_admission=deny)
        events = await self.collect_reusable(session)
        self.assertEqual(rpc.opens, 0)
        self.assertEqual(events[-1].payload, {"status": "cancelled"})
        self.assertTrue(lease.closed)

    async def test_invalidated_lease_does_not_open_native_session(self):
        fixture, lease, rpc, session = self.make_reusable()
        os.close(lease.inherited_fds[0])
        events = await self.collect_reusable(session)
        self.assertEqual(rpc.opens, 0)
        self.assertEqual(events[-1].type, "run.failed")
        self.assertTrue(lease.closed)

    async def test_open_failure_is_classified_inside_kernel_and_cleans_up(self):
        class FailedOpen(RetainedResearchRpc):
            async def open(self, *, signal):
                self.opens += 1
                raise RuntimeError("private transport startup failure")

        fixture, lease, rpc, session = self.make_reusable(FailedOpen)
        events = await self.collect_reusable(session)
        self.assertEqual(events[-1].type, "run.failed")
        self.assertEqual(events[-1].payload["code"], "asterion_prime_failed")
        self.assertNotIn("private", str(events[-1].payload))
        self.assertEqual((rpc.opens, rpc.closes), (1, 1))
        self.assertTrue(lease.closed)

    async def test_cancellation_at_open_is_classified_and_cleans_up(self):
        class CancelledOpen(RetainedResearchRpc):
            async def open(self, *, signal):
                self.opens += 1
                signal.cancelled = True
                raise RuntimeError("cancelled during native startup")

        fixture, lease, rpc, session = self.make_reusable(CancelledOpen)
        events = await self.collect_reusable(session, FakeSignal())
        self.assertEqual(events[-1].payload, {"status": "cancelled"})
        self.assertEqual((rpc.opens, rpc.closes, rpc.calls), (1, 1, 0))
        self.assertTrue(lease.closed)

    async def test_six_round_cap_and_snapshot_do_not_renew_deadline(self):
        budget = continuation.PrimeContinuationBudget(100.0, 6)
        controller = continuation.PrimeContinuationController(budget)
        with patch.object(continuation.time, "monotonic", return_value=90.0):
            self.assertEqual([await controller.admit(i, FakeSignal()) for i in range(7)],
                             [True] * 6 + [False])
            snapshot = controller.snapshot()
            self.assertEqual(snapshot, {"deadline_monotonic": 100.0,
                             "max_natural_rounds": 6, "wall_time_remaining_seconds": 10.0})
            snapshot["deadline_monotonic"] = 1000.0
        with patch.object(continuation.time, "monotonic", return_value=100.0):
            self.assertFalse(await controller.admit(1, FakeSignal()))
            self.assertEqual(controller.snapshot()["wall_time_remaining_seconds"], 0.0)
        with self.assertRaises(FrozenInstanceError):
            budget.deadline_monotonic = 200.0

    async def test_cancellation_and_invalid_admission_reject(self):
        controller = continuation.PrimeContinuationController(
            continuation.PrimeContinuationBudget(100.0, 6))
        with patch.object(continuation.time, "monotonic", return_value=90.0):
            self.assertFalse(await controller.admit(0, FakeSignal(True)))
            self.assertFalse(await controller.admit(-1, FakeSignal()))
            for index in (True, "1", 1.0):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    await controller.admit(index, FakeSignal())

    async def test_document_research_retains_one_session_until_goal_or_round_cap(self):
        for goal in (3, 7):
            with self.subTest(goal=goal):
                fixture = SessionFixture()
                self.addCleanup(fixture.close)
                lease = fixture.binding.preflight()
                config = PiRpcConfig(command=("pi", *lease.command_args()), cwd=fixture.root,
                    environment=dict(lease.environment), inherited_fds=lease.inherited_fds,
                    deadline_seconds=5400)
                rpc = RetainedResearchRpc(config)
                controller = continuation.PrimeContinuationController(
                    continuation.PrimeContinuationBudget(continuation.time.monotonic() + 60, 6))
                session = AsterionPrimeSession(rpc_session=rpc, extension_binding=fixture.binding,
                    extension_lease=lease, approved_command=config.command,
                    limits=ASTERION_PRIME_RESEARCH_LIMITS, reusable_session=True,
                    completion_predicate=lambda: len(rpc.findings) >= goal,
                    round_admission=controller.admit)
                events = [event async for event in session.run(RunRequest(run_id=f"documents-{goal}",
                    input_text="Research the supplied documents and compare their evidence.",
                    requested_capabilities=("prime.tool.ipython",), deadline_ms=5400000))]
                validate_event_stream([event.to_mapping() for event in events])
                self.assertEqual(rpc.calls, min(goal, 6))
                self.assertEqual((rpc.opens, rpc.closes), (1, 1))
                self.assertEqual(events[-1].payload, {"status": "completed" if goal == 3 else "cancelled"})
                self.assertTrue(lease.closed)

    async def test_reusable_session_closes_after_task_cancellation(self):
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        lease = fixture.binding.preflight()
        config = PiRpcConfig(command=("pi", *lease.command_args()), cwd=fixture.root,
            environment=dict(lease.environment), inherited_fds=lease.inherited_fds,
            deadline_seconds=5400)
        entered = asyncio.Event()

        class WaitingRpc(RetainedResearchRpc):
            async def prompt(self, prompt, *, signal, on_event):
                entered.set()
                await asyncio.Event().wait()

        rpc = WaitingRpc(config)
        session = AsterionPrimeSession(rpc_session=rpc, extension_binding=fixture.binding,
            extension_lease=lease, approved_command=config.command,
            limits=ASTERION_PRIME_RESEARCH_LIMITS, reusable_session=True)

        async def collect():
            return [event async for event in session.run(RunRequest(run_id="documents-cancel",
                input_text="Research documents", requested_capabilities=("prime.tool.ipython",)))]

        pending = asyncio.create_task(collect())
        await asyncio.wait_for(entered.wait(), 1)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual((rpc.opens, rpc.closes), (1, 1))
        self.assertTrue(lease.closed)


class TestPrimeResearchLimits(unittest.TestCase):
    def test_ceiling_defaults_and_invalid_bounds(self):
        self.assertEqual(ASTERION_PRIME_RESEARCH_LIMITS, AsterionPrimeLimits(1024, 4096, 5400000))
        self.assertEqual(ASTERION_PRIME_LIMITS, AsterionPrimeLimits(128, 500, 3600000))
        self.assertEqual(AsterionPrimeLimits(None, None, None).deadline_ms, None)
        for bounds in ((1025, 4096, 5400000), (1024, 4097, 5400000),
                       (1024, 4096, 5400001), (None, 500, 3600000),
                       (128, None, None), (True, 500, 3600000), (0, 500, 3600000)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                AsterionPrimeLimits(*bounds)
        for deadline, rounds in ((float("inf"), 6), (float("nan"), 6), (True, 6),
                                 (100.0, 0), (100.0, True), (100.0, 1.5)):
            with self.subTest(deadline=deadline, rounds=rounds), self.assertRaises(ValueError):
                continuation.PrimeContinuationBudget(deadline, rounds)

    def test_trusted_narrow_limits_require_exact_transport_agreement(self):
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        limits = AsterionPrimeLimits(200, 700, 4000000)
        for transport_seconds in (4000, 3600):
            with self.subTest(transport_seconds=transport_seconds):
                lease = fixture.binding.preflight()
                config = PiRpcConfig(command=("pi", *lease.command_args()), cwd=fixture.root,
                    environment=dict(lease.environment), inherited_fds=lease.inherited_fds,
                    deadline_seconds=transport_seconds)
                kwargs = dict(rpc_session=FakePiRpcSession(config, ()), extension_binding=fixture.binding,
                    extension_lease=lease, approved_command=config.command, limits=limits)
                if transport_seconds == 4000:
                    session = AsterionPrimeSession(**kwargs)
                    with self.assertRaisesRegex(ProtocolError, "fixed deadline"):
                        asyncio.run(_collect_mismatched_request(session))
                else:
                    with self.assertRaisesRegex(ProtocolError, "launch material"):
                        AsterionPrimeSession(**kwargs)
                self.assertTrue(lease.closed)

    def test_reusable_session_requires_native_lifecycle_and_boolean_opt_in(self):
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        for enabled in (True, 1):
            with self.subTest(enabled=enabled):
                lease = fixture.binding.preflight()
                config = PiRpcConfig(command=("pi", *lease.command_args()), cwd=fixture.root,
                    environment=dict(lease.environment), inherited_fds=lease.inherited_fds,
                    deadline_seconds=3600)
                with self.assertRaisesRegex(ProtocolError, "launch material"):
                    AsterionPrimeSession(rpc_session=FakePiRpcSession(config, ()),
                        extension_binding=fixture.binding, extension_lease=lease,
                        approved_command=config.command, reusable_session=enabled)
                self.assertTrue(lease.closed)


async def _collect_mismatched_request(session):
    return [event async for event in session.run(RunRequest(run_id="mismatch", input_text="documents",
            requested_capabilities=("prime.tool.ipython",), deadline_ms=3600000))]
