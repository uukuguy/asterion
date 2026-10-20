"""Semantic P3 live-host checks without a provider connection."""

import asyncio
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p3 import live, operator
from asterion.applications.prime.p3.runtime_binding import _P3RuntimeSession
from asterion.agents.prime import application
from asterion.agents.prime.application import PrimeApplicationSpec, PrimeOperatorContext, prepare_prime_application
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.live_model import bounded_text_limits


def _prime(root):
    limits = bounded_text_limits()
    context = PrimeOperatorContext(
        executable=Path("/fake/node"), entry=Path("/fake/pi"), cwd=root.absolute(),
        provider="deepseek", model="deepseek-flash", effort="off", environment={},
        task_deadline=TaskDeadline(deadline_monotonic=time.monotonic() + 120,
                                   deadline_epoch=time.time() + 120),
    )
    return prepare_prime_application(
        PrimeApplicationSpec("prime.test.p3", "1.0.0", "text-only"), context, authorization=limits,
    )


def _owned_session(session, usage):
    prompt = session.prompt
    close = session.close
    reaped = False

    async def measured_prompt(text, *, signal):
        usage.prompts += 1
        try:
            reply = await prompt(text, signal=signal)
        except BaseException:
            usage.blocked = usage.unknown_effect = True
            raise
        usage.input_tokens += reply.usage.input_tokens
        usage.output_tokens += reply.usage.output_tokens
        return reply

    async def owned_close():
        nonlocal reaped
        if reaped:
            return
        try:
            await close()
        except BaseException:
            usage.blocked = True
            raise
        reaped = True

    session.prompt = measured_prompt
    session.close = owned_close
    return session


class Session:
    def __init__(self, role, output, events, *, fail_close=False):
        self.role, self.output, self.events = role, output, events
        self.fail_close = fail_close
        self.closed = False
        self.prompts = []
        self.input_tokens, self.output_tokens, self.cost_micros = 100, 20, 54

    async def open(self, *, signal):
        self.events.append("open:" + self.role)

    async def prompt(self, text, *, signal):
        self.prompts.append(text)
        self.events.append("prompt:" + self.role)
        return SimpleNamespace(
            text=self.output,
            usage=SimpleNamespace(input_tokens=self.input_tokens, output_tokens=self.output_tokens, cost_micros=self.cost_micros),
        )

    async def close(self):
        self.closed = True
        self.events.append("close:" + self.role)
        if self.fail_close:
            raise RuntimeError("SECRET-CLOSE")


class TestP3Live(unittest.IsolatedAsyncioTestCase):
    def test_entry_accepts_owner_without_session_factory(self):
        import inspect
        from asterion.applications.prime.p3 import live
        entry = live.run_live_verification
        self.assertNotIn("session_factory", inspect.signature(entry).parameters)
        self.assertIn("prime", inspect.signature(entry).parameters)

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
        prime = _prime(Path(self.temp.name))
        view = prime.text_model(key="probe", limits=bounded_text_limits())
        for forbidden in ("process", "open", "close"):
            self.assertFalse(hasattr(view, forbidden))
        def session(**material):
            role = "child" if material["usage"].prompts == 0 else "root"
            return _owned_session(self.factory(role, material["cwd"]), material["usage"])
        with patch.object(application, "LiveModelSession", side_effect=session):
            return await live.run_live_verification(prime=prime, private_root=self.root, **kwargs)

    async def test_admission_precedes_child_and_root_consumes_verified_output(self):
        runner = await operator._open_child_runner()
        original = runner.admit_child

        async def admit(**kwargs):
            self.events.append("admit")
            return await original(**kwargs)

        runs = []
        original_run = _P3RuntimeSession.run

        async def spy(self, request, *, signal=None):
            runs.append(request.input_text)
            async for event in original_run(self, request, signal=signal):
                yield event

        with patch.object(runner, "admit_child", side_effect=admit), patch.object(
            runner, "record_child_cost", wraps=runner.record_child_cost
        ) as cost, patch.object(_P3RuntimeSession, "run", spy):
            result = await self.run_live(child_runner=runner)
        self.assertEqual(self.events[0], "admit")
        self.assertEqual(runs, ["fixed-recursive-workflow"])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_call_count, 2)
        self.assertEqual(result.cost_micros, 108)
        self.assertEqual(result.input_tokens, 200)
        self.assertEqual(cost.call_args.args[0], Decimal("0.000054"))
        self.assertEqual([s.role for s in self.sessions], ["child", "root"])
        self.assertIn('{"sum_squares":230}', self.sessions[1].prompts[0])
        self.assertTrue(all(s.closed for s in self.sessions))
        public = json.dumps(asdict(result))
        self.assertNotIn(self.temp.name, public)
        self.assertNotIn("sum_squares", public)

    async def test_known_child_charge_survives_reap_failure_once(self):
        original = self.factory
        def failing_factory(role, cwd):
            session = original(role, cwd)
            session.fail_close = True
            return session
        self.factory = failing_factory
        runner = await operator._open_child_runner()
        with patch.object(runner, "record_child_cost", wraps=runner.record_child_cost) as cost:
            with self.assertRaises(live.P3LiveError):
                await self.run_live(child_runner=runner)
        self.assertEqual(cost.call_count, 1)
        self.assertEqual(cost.call_args.args[0], Decimal("0.000054"))
        self.assertEqual(len(self.sessions), 1)
        self.assertEqual(runner._admitted_run_ids, set())

    async def test_unknown_child_effect_retains_admission_and_blocks_root(self):
        original = self.factory
        def unknown_factory(role, cwd):
            session = original(role, cwd)
            async def unknown(text, *, signal):
                raise RuntimeError("PRIVATE-UNKNOWN")
            session.prompt = unknown
            return session
        self.factory = unknown_factory
        runner = await operator._open_child_runner()
        with patch.object(runner, "record_child_cost", wraps=runner.record_child_cost) as cost:
            with self.assertRaises(live.P3LiveError):
                await self.run_live(child_runner=runner)
        self.assertEqual(cost.call_count, 0)
        self.assertEqual(len(runner._admitted_run_ids), 1)
        self.assertEqual(len(self.sessions), 1)
        self.assertTrue(self.sessions[0].closed)

    async def test_direct_execution_ignores_central_provider_composition(self):
        with (
            patch("asterion.applications.provider.compose_installed_provider", side_effect=AssertionError("central composition")),
            patch("asterion.applications.prime.inventory.prime_application_index", side_effect=AssertionError("central inventory")),
            patch("asterion.applications.prime.inventory.prime_release_application", side_effect=AssertionError("central lookup")),
        ):
            result = await self.run_live()
        self.assertEqual(result.status, "completed")

    async def test_wrong_child_answer_never_reaches_root_and_still_accounts_cost(self):
        self.outputs["child"] = '{"sum_squares":999}'
        runner = await operator._open_child_runner()
        with patch.object(runner, "record_child_cost", wraps=runner.record_child_cost) as cost:
            with self.assertRaises(live.P3LiveError):
                await self.run_live(child_runner=runner)
        self.assertEqual(len(self.sessions), 1)
        self.assertTrue(self.sessions[0].closed)
        self.assertEqual(cost.call_args.args[0], Decimal("0.000054"))

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
            session.input_tokens, session.output_tokens, session.cost_micros = 333_337, 0, 100_002
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
