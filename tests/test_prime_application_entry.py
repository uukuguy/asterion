"""Effect-free, immutable independent Prime application construction."""

import asyncio
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from asterion.agents.prime import _launch

from asterion.agents.prime.application import (
    PrimeApplicationSpec,
    PrimeBackendSpec,
    PrimeOperatorContext,
    PrimeRunHooks,
    PrimeTextLimits,
    PrimeToolModuleArtifact,
    prepare_prime_application,
)
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.deadline import TaskDeadline
from asterion.agents.prime.execution import AsterionPrimeLimits
from asterion.agents.prime.tool_registry import PrimeApplicationToolRegistry
from asterion.agents.prime._text_model import LiveModelError
from asterion.runtime.protocol import ProtocolError
from tests.test_prime_live_model import _NeverCancelled, _PRODUCER
import sys


class TestPrimeApplicationEntry(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.executable = self.root / 'node'
        self.executable.write_text('#!/bin/sh\nexit 0\n')
        self.executable.chmod(0o700)
        self.environment = {'SECRET': 'private-sentinel'}
        self.deadline = TaskDeadline(
            deadline_monotonic=time.monotonic() + 60,
            deadline_epoch=time.time() + 60,
        )
        self.operator = PrimeOperatorContext(
            executable=self.executable, entry=None, cwd=self.root,
            provider='deepseek', model='deepseek-flash', effort='off',
            environment=self.environment, task_deadline=self.deadline,
        )
        self.spec = PrimeApplicationSpec('example.independent', '1.0.0', 'text-only')
        self.limits = PrimeTextLimits(deadline_seconds=30, max_prompts=2)
        self.run_limits = AsterionPrimeLimits(2, 2, 30_000)

    def test_prepare_is_effect_free_and_profile_checked(self):
        with (
            patch('asterion.runtimes.pi_rpc.PiRpcSession') as rpc,
            patch('asterion.agents.prime.ipython_worker.SubprocessPythonWorker') as worker,
            patch('threading.Thread.start') as thread,
            patch('builtins.open', side_effect=AssertionError('unexpected read')),
        ):
            app = prepare_prime_application(self.spec, self.operator, authorization=self.limits)
            self.assertEqual(app.state, 'prepared')
            with self.assertRaises(ProtocolError):
                app.runtime(services=object(), limits=self.run_limits, hooks=PrimeRunHooks())
            rpc.assert_not_called()
            worker.assert_not_called()
            thread.assert_not_called()
        self.assertNotIn('private-sentinel', repr(app))

    def test_context_is_immutable_and_redacted(self):
        self.environment['SECRET'] = 'changed'
        self.assertEqual(self.operator.environment['SECRET'], 'private-sentinel')
        self.assertIs(self.operator.task_deadline, self.deadline)
        with self.assertRaises(TypeError):
            self.operator.environment['SECRET'] = 'changed'
        with self.assertRaises(FrozenInstanceError):
            self.operator.model = 'changed'
        for value in (self.operator, self.spec):
            self.assertNotIn(str(self.root), repr(value))
            self.assertNotIn('private-sentinel', repr(value))
        with self.assertRaises(ProtocolError) as failure:
            replace(self.operator, environment={'private-sentinel': object()})
        self.assertNotIn('private-sentinel', str(failure.exception))
        self.assertNotIn(str(self.root), str(failure.exception))

    def test_identity_and_profile_tool_combinations_are_checked(self):
        registry = PrimeApplicationToolRegistry('example.tools', 'example.capability', ('example_tool',))
        artifact = PrimeToolModuleArtifact(self.root / 'tools.mjs', registry)
        invalid = (
            dict(application_id='private-sentinel/path'),
            dict(application_version='latest'),
            dict(profile='unknown'),
            dict(tools=artifact),
            dict(profile='persistent-code-tools'),
            dict(system_prompt=object()),
        )
        for changes in invalid:
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ProtocolError) as failure:
                    replace(self.spec, **changes)
                self.assertNotIn('private-sentinel', str(failure.exception))
        persistent = replace(self.spec, profile='persistent-code-tools', tools=artifact)
        app = prepare_prime_application(persistent, self.operator, authorization=self.run_limits)
        self.assertEqual(app.state, 'prepared')

    def test_text_limits_reject_invalid_values_and_unpriced_cost(self):
        for changes in (
            dict(deadline_seconds=0), dict(deadline_seconds=float('nan')),
            dict(max_prompts=True), dict(max_input_tokens=-1),
            dict(max_output_bytes=0), dict(max_cost_micros=10),
            dict(provider_output_tokens=1.5),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ProtocolError):
                    replace(self.limits, **changes)
        priced = replace(self.limits, max_cost_micros=10, price=ModelPrice(2, 3))
        self.assertEqual(priced.price, ModelPrice(2, 3))

    def test_prepare_rejects_mismatched_authorization(self):
        with self.assertRaises(ProtocolError):
            prepare_prime_application(self.spec, self.operator, authorization=self.run_limits)
        with self.assertRaises(ProtocolError):
            prepare_prime_application(self.spec, self.operator, authorization=object())

    def test_owner_text_admission_does_not_regrant_or_change_key_limits(self):
        app = prepare_prime_application(self.spec, self.operator, authorization=self.limits)
        app._admit_text_limits('conversation.one', self.limits)
        app._admit_text_limits('conversation.one', self.limits)
        with self.assertRaises(ProtocolError):
            app._admit_text_limits('conversation.one', replace(self.limits, max_prompts=1))
        for limits in (
            replace(self.limits, max_prompts=3), replace(self.limits, max_prompts=None),
            replace(self.limits, deadline_seconds=31),
        ):
            with self.subTest(limits=limits):
                with self.assertRaises(ProtocolError):
                    app._admit_text_limits('conversation.two', limits)
        app._admit_text_limits('conversation.two', replace(self.limits, max_prompts=1))
        self.assertIs(app._operator.task_deadline, self.deadline)
        self.assertEqual(app.state, 'prepared')

    def test_unassembled_factories_reject_without_effect_and_close_is_idempotent(self):
        app = prepare_prime_application(self.spec, self.operator, authorization=self.limits)
        with self.assertRaises(ProtocolError):
            asyncio.run(app.open_backend(spec=object(), services=object()))
        receipt = asyncio.run(app.close())
        self.assertTrue(receipt.complete)
        self.assertEqual(app.state, 'closed')
        self.assertEqual(receipt, asyncio.run(app.close()))
        with self.assertRaises(ProtocolError):
            app._admit_text_limits('conversation.one', self.limits)

    def test_text_view_has_no_launch_handles(self):
        app = prepare_prime_application(self.spec, self.operator, authorization=self.limits)
        view = app.text_model(key='candidate', limits=self.limits)
        self.assertFalse(any(hasattr(view, name) for name in ('open', 'close', 'process', 'config')))
        self.assertEqual(app.state, 'prepared')
        asyncio.run(app.close())

    def _text_app(self, limits=None, deadline=None):
        script = self.root / 'producer.py'
        script.write_text(_PRODUCER)
        operator = replace(self.operator, executable=Path(sys.executable).resolve(),
                           entry=None, task_deadline=deadline or self.deadline)
        app = prepare_prime_application(self.spec, operator, authorization=limits or self.limits)
        return app, (sys.executable, '-I', str(script))

    def test_text_once_reaps_before_return(self):
        app, command = self._text_app()
        async def run():
            with patch('asterion.agents.prime._launch.text_command', return_value=command):
                reply = await app.text_once(key='checkpoint', text='hello',
                                            limits=self.limits, signal=_NeverCancelled())
            self.assertEqual(reply.text, 'private answer')
            self.assertIsNone(app._text_sessions['checkpoint'].process)
            with self.assertRaises(ProtocolError):
                app.text_model(key='checkpoint', limits=self.limits)
            self.assertTrue((await app.close()).complete)
        asyncio.run(run())

    def test_unlisted_application_runs_without_provider_lookup(self):
        app, command = self._text_app()
        async def run():
            with (patch('asterion.agents.prime._launch.text_command', return_value=command),
                  patch('asterion.applications.discovery.list_application_providers',
                        side_effect=AssertionError('provider lookup')),
                  patch('asterion.applications.discovery.load_application_provider',
                        side_effect=AssertionError('provider lookup')),
                  patch('asterion.applications.prime.inventory.prime_release_application',
                        side_effect=AssertionError('inventory lookup'))):
                one = app.text_model(key='one', limits=self.limits)
                two = app.text_model(key='two', limits=self.limits)
                await one.prompt('hello', signal=_NeverCancelled())
                await two.prompt('hello', signal=_NeverCancelled())
                self.assertIsNot(app._text_sessions['one'], app._text_sessions['two'])
                with self.assertRaises(LiveModelError):
                    await app.text_once(key='three', text='hello', limits=self.limits,
                                        signal=_NeverCancelled())
                self.assertEqual(app._text_usage.prompts, 2)
                self.assertTrue((await app.close()).complete)
        asyncio.run(run())

    def test_unknown_usage_blocks_other_keys(self):
        app, command = self._text_app()
        async def run():
            with patch('asterion.agents.prime._launch.text_command', return_value=command):
                with self.assertRaises(LiveModelError):
                    await app.text_once(key='one', text='missing-usage', limits=self.limits,
                                        signal=_NeverCancelled())
                with self.assertRaises(LiveModelError):
                    await app.text_once(key='two', text='hello', limits=self.limits,
                                        signal=_NeverCancelled())
                self.assertEqual(app._text_usage.prompts, 1)
                await app.close()
        asyncio.run(run())

    def test_task_deadline_is_shared_and_not_renewed(self):
        clock = [0.0]
        deadline = TaskDeadline(deadline_monotonic=10, deadline_epoch=10,
                                monotonic_clock=lambda: clock[0], wall_clock=lambda: clock[0])
        app, command = self._text_app(deadline=deadline)
        async def run():
            with patch('asterion.agents.prime._launch.text_command', return_value=command):
                await app.text_once(key='one', text='hello', limits=self.limits,
                                    signal=_NeverCancelled())
                clock[0] = 11
                with self.assertRaises(LiveModelError):
                    await app.text_once(key='two', text='hello', limits=self.limits,
                                        signal=_NeverCancelled())
                self.assertEqual(app._text_usage.prompts, 1)
                await app.close()
        asyncio.run(run())

    def test_close_failure_prevents_success_and_cleanup_can_retry(self):
        limits = replace(self.limits, max_prompts=3)
        app, command = self._text_app(limits)
        async def run():
            with patch('asterion.agents.prime._launch.text_command', return_value=command):
                view = app.text_model(key='one', limits=limits)
                await view.prompt('hello', signal=_NeverCancelled())
                rpc = app._text_sessions['one']._rpc
                original_stop = rpc.stop
                with patch.object(rpc, 'stop', side_effect=RuntimeError('private-close')):
                    with self.assertRaises(LiveModelError):
                        await app.text_once(key='one', text='hello', limits=limits,
                                            signal=_NeverCancelled())
                    with self.assertRaises(LiveModelError):
                        await app.text_once(key='two', text='hello', limits=limits,
                                            signal=_NeverCancelled())
                    receipt = await app.close()
                    self.assertFalse(receipt.complete)
                    self.assertEqual(app.state, 'closing')
                original_stop()
                self.assertTrue((await app.close()).complete)
                self.assertEqual(app.state, 'closed')
        asyncio.run(run())

    def test_overlapping_keys_do_not_bypass_shared_prompt_cap(self):
        limits = replace(self.limits, max_prompts=1)
        app, command = self._text_app(limits)
        async def run():
            with patch('asterion.agents.prime._launch.text_command', return_value=command):
                replies = await asyncio.gather(*(
                    app.text_once(key=key, text='hello', limits=limits, signal=_NeverCancelled())
                    for key in ('one', 'two')), return_exceptions=True)
                self.assertEqual(sum(isinstance(reply, LiveModelError) for reply in replies), 1)
                self.assertEqual(app._text_usage.prompts, 1)
                self.assertTrue((await app.close()).complete)
        asyncio.run(run())

    def test_consumed_ceilings_reject_next_key_before_rpc_dispatch(self):
        cases = (
            ('max_input_tokens', 1000, 1000),
            ('max_output_tokens', 500, 500),
            ('max_output_bytes', len('private answer'.encode()), len('private answer'.encode())),
            ('max_cost_micros', 900, 900),
            ('max_input_tokens', 2000, 500),
        )
        for field, approved, requested in cases:
            with self.subTest(field=field, approved=approved, requested=requested):
                limits = replace(self.limits, **{field: approved}, price=ModelPrice(300000, 1200000))
                app, command = self._text_app(limits)
                dispatches = []
                original_rpc = _launch.text_rpc
                def make_rpc(config):
                    rpc = original_rpc(config)
                    rpc.prompt = AsyncMock(wraps=rpc.prompt)
                    dispatches.append(rpc.prompt)
                    return rpc
                async def run():
                    try:
                        with (patch('asterion.agents.prime._launch.text_command', return_value=command),
                              patch('asterion.agents.prime._launch.text_rpc', side_effect=make_rpc)):
                            await app.text_once(key='one', text='hello', limits=limits,
                                                signal=_NeverCancelled())
                            with self.assertRaises(LiveModelError):
                                await app.text_once(key='two', text='hello',
                                                    limits=replace(limits, **{field: requested}),
                                                    signal=_NeverCancelled())
                            self.assertEqual(sum(call.await_count for call in dispatches), 1)
                            self.assertEqual(app._text_usage.prompts, 1)
                    finally:
                        await app.close()
                asyncio.run(run())

    def test_hooks_and_backend_inputs_are_immutable_and_checked(self):
        with self.assertRaises(ProtocolError):
            PrimeRunHooks(completion_predicate='private-sentinel')
        instructions = {'manual': 'private-sentinel'}
        spec = PrimeBackendSpec(
            session_id='session.one', generation=1, private_root=self.root,
            continuation_policy_id='continuation.one', limits=self.run_limits,
            aggregate_tokens=100, cost_micros=10, model_price=ModelPrice(2, 3),
            authority_id=None, compaction_instructions=instructions,
        )
        instructions['manual'] = 'changed'
        self.assertEqual(spec.compaction_instructions['manual'], 'private-sentinel')
        self.assertNotIn('private-sentinel', repr(spec))
        self.assertNotIn(str(self.root), repr(spec))
        with self.assertRaises(ProtocolError):
            replace(spec, generation=0)
        compatible = replace(
            spec, continuation_policy_id='Continuation:One',
            generation=(1 << 53) - 1, aggregate_tokens=(1 << 53) - 1,
            cost_micros=(1 << 53) - 1,
            compaction_instructions={'Manual:One': 'private-sentinel'},
        )
        self.assertEqual(compatible.continuation_policy_id, 'Continuation:One')
        for changes in (
            dict(generation=1 << 53), dict(aggregate_tokens=1 << 53),
            dict(cost_micros=1 << 53), dict(continuation_policy_id='invalid handle'),
            dict(compaction_instructions={'invalid handle': 'private-sentinel'}),
            dict(compaction_instructions={'Manual:One': ''}),
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ProtocolError):
                    replace(spec, **changes)


if __name__ == '__main__':
    unittest.main()
