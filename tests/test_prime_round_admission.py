"""Application admission must fence model requests without a second loop."""
import asyncio
import unittest

from tests.test_asterion_prime_session import FakeSignal, SessionFixture, collect
from asterion.runtime.host import RunRequest


class TestPrimeRoundAdmission(unittest.TestCase):
    def test_admission_waits_before_transport_and_applies_to_continuation(self):
        async def exercise():
            fixture = SessionFixture()
            self.addCleanup(fixture.close)
            entered, release = asyncio.Event(), asyncio.Event()
            admitted = []

            async def admit(index, signal):
                admitted.append(index)
                entered.set()
                await release.wait()
                return index == 0

            session, rpc, lease = fixture.make(
                completion_predicate=lambda: False, round_admission=admit
            )
            pending = asyncio.create_task(collect(session))
            await asyncio.wait_for(entered.wait(), 0.5)
            self.assertEqual(rpc.calls, 0)
            release.set()
            events = await pending
            self.assertEqual(rpc.calls, 1)
            self.assertEqual(admitted, [0, 1])
            self.assertEqual(events[-1].payload, {"status": "cancelled"})
            self.assertTrue(lease.closed)

        asyncio.run(exercise())

    def test_waiting_admission_obeys_cancellation_and_deadline(self):
        async def exercise(cancel):
            fixture = SessionFixture()
            self.addCleanup(fixture.close)
            entered, exited = asyncio.Event(), asyncio.Event()
            signal = FakeSignal()

            async def admit(index, passed_signal):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    exited.set()

            session, rpc, lease = fixture.make(round_admission=admit)
            events = []
            pending = asyncio.create_task(session._kernel.invoke(
                RunRequest(run_id="admission-test", input_text="task",
                           requested_capabilities=("prime.tool.ipython",), deadline_ms=100),
                signal, lambda kind, payload: events.append((kind, payload)),
            ))
            await asyncio.wait_for(entered.wait(), 0.5)
            if cancel:
                signal.cancelled = True
            await asyncio.wait_for(pending, 1)
            session.close()
            self.assertEqual(rpc.calls, 0)
            self.assertTrue(exited.is_set())
            self.assertTrue(lease.closed)
            self.assertEqual(events[-1][0], "run.completed" if cancel else "run.failed")

        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                asyncio.run(exercise(cancel))
