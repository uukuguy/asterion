"""Semantic P3 live-host checks without a provider connection."""

import asyncio
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p3 import live, operator


class Session:
    def __init__(self, role, output, events, *, fail_close=False):
        self.role, self.output, self.events = role, output, events
        self.fail_close = fail_close
        self.closed = False
        self.prompts = []
        self.cost_micros = 28

    async def open(self, *, signal):
        self.events.append("open:" + self.role)

    async def prompt(self, text, *, signal):
        self.prompts.append(text)
        self.events.append("prompt:" + self.role)
        return SimpleNamespace(
            text=self.output,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20, cost_micros=self.cost_micros),
        )

    async def close(self):
        self.closed = True
        self.events.append("close:" + self.role)
        if self.fail_close:
            raise RuntimeError("SECRET-CLOSE")


class TestP3Live(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.events = []
        self.sessions = []
        self.outputs = {"child": '{"sum_squares":230}', "root": '{"result":463}'}

    def factory(self, role, cwd):
        session = Session(role, self.outputs[role], self.events)
        self.sessions.append(session)
        return session

    async def run_live(self, **kwargs):
        return await live.run_live_verification(
            session_factory=self.factory, private_root=self.root,
            command_sha256="a" * 64, binding_sha256="b" * 64, **kwargs,
        )

    async def test_admission_precedes_child_and_root_consumes_verified_output(self):
        runner = await operator._open_child_runner()
        original = runner.admit_child

        async def admit(**kwargs):
            self.events.append("admit")
            return await original(**kwargs)

        with patch.object(runner, "admit_child", side_effect=admit), patch.object(
            runner, "record_child_cost", wraps=runner.record_child_cost
        ) as cost, patch.object(operator, "run_composed_application", wraps=operator.run_composed_application) as composed:
            result = await self.run_live(child_runner=runner)
        self.assertEqual(self.events[0], "admit")
        self.assertEqual(composed.await_count, 1)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_call_count, 2)
        self.assertEqual(result.cost_micros, 56)
        self.assertEqual(result.input_tokens, 200)
        self.assertEqual(cost.call_args.args[0], Decimal("0.000028"))
        self.assertEqual([s.role for s in self.sessions], ["child", "root"])
        self.assertIn('{"sum_squares":230}', self.sessions[1].prompts[0])
        self.assertTrue(all(s.closed for s in self.sessions))
        public = json.dumps(asdict(result))
        self.assertNotIn(self.temp.name, public)
        self.assertNotIn("sum_squares", public)

    async def test_wrong_child_answer_never_reaches_root_and_still_accounts_cost(self):
        self.outputs["child"] = '{"sum_squares":999}'
        runner = await operator._open_child_runner()
        with patch.object(runner, "record_child_cost", wraps=runner.record_child_cost) as cost:
            with self.assertRaises(live.P3LiveError):
                await self.run_live(child_runner=runner)
        self.assertEqual(len(self.sessions), 1)
        self.assertTrue(self.sessions[0].closed)
        self.assertEqual(cost.call_args.args[0], Decimal("0.000028"))

    async def test_invalid_or_wrong_root_result_cannot_be_success(self):
        for output in ('SECRET', '{"result":false}', '{"result":462}', '{"result":463,"extra":1}'):
            with self.subTest(output=output):
                self.root = Path(self.temp.name) / str(len(self.sessions))
                self.outputs["root"] = output
                with self.assertRaises(live.P3LiveError) as caught:
                    await self.run_live()
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertTrue(all(s.closed for s in self.sessions))

    async def test_cancelled_before_admission_starts_no_sessions(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.run_live(signal=SimpleNamespace(cancelled=True))
        self.assertEqual(self.sessions, [])

    async def test_cleanup_failure_prevents_completion(self):
        original = self.factory

        def failing_factory(role, cwd):
            session = original(role, cwd)
            session.fail_close = role == "root"
            return session

        self.factory = failing_factory
        with self.assertRaises(live.P3LiveError) as caught:
            await self.run_live()
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertTrue(all(s.closed for s in self.sessions))

    async def test_child_budget_exhaustion_prevents_root_call(self):
        original = self.factory

        def expensive_factory(role, cwd):
            session = original(role, cwd)
            session.cost_micros = 100_001
            return session

        self.factory = expensive_factory
        with self.assertRaises(live.P3LiveError):
            await self.run_live()
        self.assertEqual(len(self.sessions), 1)
        self.assertTrue(self.sessions[0].closed)

    async def test_active_cancellation_closes_child_before_return(self):
        started = asyncio.Event()
        original = self.factory

        def blocked_factory(role, cwd):
            session = original(role, cwd)

            async def blocked_prompt(text, *, signal):
                started.set()
                await asyncio.Event().wait()

            session.prompt = blocked_prompt
            return session

        self.factory = blocked_factory
        task = asyncio.create_task(self.run_live())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel("SECRET-CANCEL")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.sessions), 1)
        self.assertTrue(self.sessions[0].closed)

    async def test_refused_admission_starts_no_models(self):
        runner = await operator._open_child_runner()
        with patch.object(runner, "admit_child", return_value=live.ChildAdmissionRefused(
            refusal_reason="budget-exceeded", attempted_depth=2,
            attempted_at="2026-09-24T00:00:00Z",
        )):
            with self.assertRaises(live.P3LiveError):
                await self.run_live(child_runner=runner)
        self.assertEqual(self.sessions, [])
