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
        with self.assertRaises(ProtocolError):
            replace(self.operator, private_root=Path('relative-private-root'))
        self.assertNotIn(str(self.root), repr(replace(self.operator, private_root=self.root)))
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

    def test_text_private_identity_and_known_usage_survive_cleanup_failure(self):
        limits = replace(self.limits, price=ModelPrice(300000, 1200000))
        app, command = self._text_app(limits)
        async def run():
            with patch('asterion.agents.prime._launch.text_command', return_value=command):
                identity = app._text_identity_summary()
                self.assertEqual(len(identity.command_sha256), 64)
                self.assertEqual(len(identity.binding_sha256), 64)
                with self.assertRaises(FrozenInstanceError):
                    identity.command_sha256 = 'changed'
                view = app.text_model(key='one', limits=limits)
                await view.prompt('hello', signal=_NeverCancelled())
                rpc = app._text_sessions['one']._rpc
                with patch.object(rpc, 'stop', side_effect=RuntimeError('private-sentinel')):
                    self.assertFalse((await app.close()).complete)
                usage = app._text_usage_summary()
                self.assertEqual((usage.prompts, usage.input_tokens, usage.output_tokens, usage.cost_micros),
                                 (1, 1000, 500, 900))
                self.assertTrue(usage.blocked)
                self.assertFalse(usage.unknown_effect)
                self.assertNotIn('900', repr(usage))
                self.assertTrue((await app.close()).complete)
                self.assertEqual(app._text_identity_summary(), identity)
                self.assertEqual(app._text_usage_summary(), usage)
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
                self.assertTrue(app._text_usage_summary().unknown_effect)
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


class _Services:
    identity_sha256 = 'a' * 64

    def __init__(self):
        self.closed = self.stopped = False

    def validate_lifecycle(self):
        if self.closed:
            raise ValueError('closed')

    async def execute(self, request_id, code, signal):
        from asterion.agents.prime.tools import PrimeToolResult
        return PrimeToolResult(request_id, 'ok', ({'type': 'text', 'text': code},))

    async def call(self, request_id, method, params, signal, *, params_present=True):
        return {'protocol': 'asterion.prime-ipython/v1', 'request_id': request_id,
                'type': 'method_result', 'status': 'ok', 'output': '{}'}

    def request_stop(self):
        self.stopped = True

    async def close(self):
        self.closed = True


class TestPrimePersistentOwner(unittest.TestCase):
    setUp = TestPrimeApplicationEntry.setUp
    def _persistent_app(self):
        from asterion.agents.prime.tool_registry import CORE_TOOL_REGISTRY
        from importlib.resources import files
        artifact = PrimeToolModuleArtifact(Path(str(files('asterion.applications.prime').joinpath(
            'resources/ipython-extension.mjs'))).resolve(), CORE_TOOL_REGISTRY)
        spec = PrimeApplicationSpec('example.unregistered', '1.0.0', 'persistent-code-tools', tools=artifact)
        return prepare_prime_application(spec, self.operator, authorization=self.run_limits)

    def test_runtime_view_is_lazy_and_cannot_regrant_limits(self):
        app, services = self._persistent_app(), _Services()
        hooks = PrimeRunHooks()
        with patch.object(_launch, 'persistent_launch', create=True) as launch:
            runtime = app.runtime(services=services, limits=self.run_limits, hooks=hooks)
            self.assertIs(runtime, app.runtime(services=services, limits=self.run_limits, hooks=hooks))
            launch.assert_not_called()
            with self.assertRaises(ProtocolError):
                app.runtime(services=_Services(), limits=self.run_limits, hooks=hooks)
            with self.assertRaises(ProtocolError):
                app.runtime(services=services, limits=replace(self.run_limits, model_callbacks=3), hooks=hooks)
        self.assertTrue(asyncio.run(app.close()).complete)
        self.assertTrue(services.stopped and services.closed)

    def test_pause_does_not_reset_owner_budget(self):
        from asterion.runtime.host import RunRequest
        app, services = self._persistent_app(), _Services()
        clock = [0.0]
        deadline = TaskDeadline(deadline_monotonic=10, deadline_epoch=10,
            monotonic_clock=lambda: clock[0], wall_clock=lambda: clock[0])
        app._operator = replace(app._operator, task_deadline=deadline)
        async def run():
            paused, resume = asyncio.Event(), asyncio.Event()
            async def admission(index, signal):
                paused.set()
                await resume.wait()
                return True
            hooks = PrimeRunHooks(round_admission=admission)
            runtime = app.runtime(services=services, limits=self.run_limits, hooks=hooks)
            with patch('asterion.runtimes.pi_rpc.PiRpcSession.run', new_callable=AsyncMock) as driver:
                async def collect():
                    return [e async for e in runtime.run(RunRequest('pause', 'hello', ('prime.tool.ipython',)), signal=_NeverCancelled())]
                task = asyncio.create_task(collect())
                await paused.wait()
                self.assertIs(runtime, app.runtime(services=services, limits=self.run_limits, hooks=hooks))
                clock[0] = 11
                resume.set()
                events = await task
                self.assertEqual(events[-1].payload['status'], 'cancelled')
                self.assertIs(app.task_deadline, deadline)
                self.assertEqual(app.authorized_limits, self.run_limits)
                driver.assert_not_called()
                with self.assertRaises(ProtocolError):
                    await collect()
            self.assertTrue((await app.close()).complete)
        asyncio.run(run())

    def test_lease_failure_closes_owned_services_without_starting_rpc(self):
        from asterion.runtime.host import RunRequest
        app, services = self._persistent_app(), _Services()
        async def run():
            runtime = app.runtime(services=services, limits=self.run_limits, hooks=PrimeRunHooks())
            with (patch('asterion.runtime.pinned_extension.ExtensionBinding.preflight', side_effect=ValueError('unavailable')),
                  patch('asterion.runtime.native_rpc.build_rpc_session') as rpc):
                with self.assertRaises(ValueError):
                    _ = [e async for e in runtime.run(RunRequest('failure', 'hello', ('prime.tool.ipython',)), signal=_NeverCancelled())]
                rpc.assert_not_called()
            self.assertTrue(services.closed)
            self.assertTrue((await app.close()).complete)
            self.assertTrue(services.closed)
        asyncio.run(run())

    def test_invalid_request_does_not_acquire_or_consume_owner(self):
        app, services = self._persistent_app(), _Services()
        async def run():
            runtime = app.runtime(services=services, limits=self.run_limits, hooks=PrimeRunHooks())
            with patch.object(_launch, 'persistent_launch') as launch:
                with self.assertRaises(ProtocolError):
                    _ = [event async for event in runtime.run(object(), signal=_NeverCancelled())]
                launch.assert_not_called()
                self.assertFalse(app._run_claimed)
            await app.close()
        asyncio.run(run())

    def test_cleanup_reaps_before_rpc_close_and_finishes_other_resources(self):
        from types import SimpleNamespace
        app, services = self._persistent_app(), _Services()
        app.runtime(services=services, limits=self.run_limits, hooks=PrimeRunHooks())
        order = []
        async def close_rpc():
            self.assertEqual(order, ['stop'])
            raise RuntimeError('active command close failed')
        app._persistent = SimpleNamespace(
            rpc=SimpleNamespace(stop=lambda: order.append('stop'), close=close_rpc),
            bridge=SimpleNamespace(close=lambda: order.append('bridge')),
            close_descriptors=lambda: order.append('descriptors'))
        cleanup = asyncio.run(app.close())
        self.assertEqual(order, ['stop', 'bridge', 'descriptors'])
        self.assertFalse(cleanup.model_closed)
        self.assertTrue(cleanup.bridge_closed and cleanup.extension_closed and cleanup.workspace_closed)
        self.assertTrue(services.stopped)

    def test_workspace_api_does_not_accept_a_caller_worker(self):
        import inspect
        from asterion.agents.prime._workspace_owner import WorkspaceOwner
        from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
        app = self._persistent_app()
        for create in (app.create_workspace, WorkspaceOwner.create_workspace, P7ResearchRuntime):
            self.assertNotIn('worker', inspect.signature(create).parameters)
        asyncio.run(app.close())

    def test_owner_close_stops_active_workspace_without_caller_cancellation(self):
        from asterion.agents.prime.ipython import KernelBootstrap, KernelLimits
        app = self._persistent_app()
        async def run():
            kernel = app.create_workspace(KernelBootstrap({}, {}, self.root / 'active-workspace'),
                                         KernelLimits(deadline_seconds=30))
            services = _Services()
            services.close = kernel.close
            app.runtime(services=services, limits=self.run_limits, hooks=PrimeRunHooks())
            marker = kernel._bootstrap.workspace / 'started'
            caller = _NeverCancelled()
            cell = asyncio.create_task(kernel.execute('active-cell',
                "from pathlib import Path\nimport time\nPath('started').touch()\nwhile True: time.sleep(0.01)", caller))
            try:
                async with asyncio.timeout(3):
                    while not marker.exists():
                        await asyncio.sleep(0.01)
                process = kernel._worker._process
                async with asyncio.timeout(3):
                    cleanup = await app.close()
                self.assertTrue(cleanup.complete)
                result = await asyncio.wait_for(cell, 1)
                self.assertEqual(result.status, 'uncertain')
                self.assertFalse(caller.cancelled)
                self.assertIsNotNone(process.returncode)
                self.assertTrue(kernel.status()['closed'])
            finally:
                if not cell.done():
                    cell.cancel()
                await asyncio.gather(cell, return_exceptions=True)
                await app.close()
        asyncio.run(run())

    def test_owner_reaps_workspace_on_its_execution_loop(self):
        from asterion.agents.prime.ipython import KernelBootstrap, KernelLimits
        app = self._persistent_app()
        async def run():
            kernel = app.create_workspace(KernelBootstrap({}, {}, self.root / 'thread-workspace'),
                                         KernelLimits(deadline_seconds=30))
            marker = kernel._bootstrap.workspace / 'started'
            execution = {}
            async def execute():
                execution['loop'] = asyncio.get_running_loop()
                execution['task'] = asyncio.current_task()
                return await kernel.execute('thread-cell',
                    "from pathlib import Path\nimport time\nPath('started').touch()\nwhile True: time.sleep(0.01)",
                    _NeverCancelled())
            cell = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(execute())))
            try:
                async with asyncio.timeout(3):
                    while not marker.exists():
                        await asyncio.sleep(0.01)
                process = kernel._worker._process
                async with asyncio.timeout(3):
                    cleanup = await app.close()
                self.assertTrue(cleanup.complete)
                self.assertEqual((await cell).status, 'uncertain')
                self.assertIsNotNone(process.returncode)
                self.assertTrue(kernel.status()['closed'])
            finally:
                if not cell.done() and 'loop' in execution:
                    execution['loop'].call_soon_threadsafe(execution['task'].cancel)
                await asyncio.gather(cell, return_exceptions=True)
                await app.close()
        asyncio.run(run())

    def test_explicit_workspace_restore_advances_generation(self):
        from asterion.agents.prime.ipython import KernelBootstrap, KernelLimits
        app = self._persistent_app()
        async def run():
            kernel = app.create_workspace(KernelBootstrap({}, {}, self.root / 'workspace'), KernelLimits())
            generation = kernel.generation
            result = await kernel.execute('cell-one', "prime_workspace.export('source', 'def answer(): return 42')", _NeverCancelled())
            self.assertEqual(result.status, 'ok')
            # Explicit exported source/data are the existing restore inputs.
            exports = __import__('json').loads(result.content[0]['text'])['kernel_exports']
            source = kernel.read_export(exports[0]['export_id'])
            restored = await app.restore_workspace(kernel, (source,), {}, _NeverCancelled())
            self.assertNotEqual(restored.generation, generation)
            self.assertTrue(kernel.status()['closed'])
            self.assertTrue((await app.close()).complete)
            self.assertTrue(restored.status()['closed'])
        asyncio.run(run())


class TestPrimeIndependentPersistent(unittest.IsolatedAsyncioTestCase):
    async def test_unregistered_tools_run_through_owned_pin_and_registration(self):
        import json
        import shutil
        import subprocess
        from importlib.resources import files
        from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcEvent, PiRpcResult
        from asterion.runtime.host import RunRequest
        from asterion.runtime.pinned_extension import extension_loader_path
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            core = Path(str(files('asterion.applications.prime').joinpath('resources/ipython-extension.mjs')))
            source, bundle = root / 'tools.ts', root / 'tools.mjs'
            source.write_text('import {registerPrime} from ' + json.dumps(str(core)) + ';\n'
                'const module={registry:{module_id:"example.tools",capability_id:"example.lookup",'
                'tool_names:["example_lookup","ipython"]},createTools:()=>[{name:"example_lookup",label:"Lookup",'
                'description:"Read example state",parameters:{type:"object",properties:{}},'
                'execute:async()=>({content:[{type:"text",text:"found"}],details:{}})}]};\n'
                'export default function register(pi,dependencies){registerPrime(pi,dependencies,module);}')
            esbuild = Path(__file__).resolve().parents[1] / 'packages/typescript/asterion-prime-extension/node_modules/.bin/esbuild'
            built = subprocess.run([str(esbuild), str(source), '--bundle', '--platform=node', '--format=esm',
                '--supported:template-literal=false', '--minify-syntax', '--minify-whitespace', '--legal-comments=none',
                '--outfile='+str(bundle)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            # The existing loader receives deterministic host mechanics through Node's resolver.
            stub = root / 'host.mjs'
            stub.write_text("export const buildSessionContext=()=>({messages:[]}); export const convertToLlm=x=>x; export const serializeConversation=()=>'';")
            resolver = root / 'resolver.mjs'
            resolver.write_text('export async function resolve(s,c,next){if(s==="@earendil-works/pi-coding-agent")return {url:'
                                + json.dumps(stub.as_uri()) + ',shortCircuit:true};return next(s,c);}')
            script = 'const tools=[],hooks=[]; const m=await import('+json.dumps(extension_loader_path().as_uri())+'); await m.default({registerTool:t=>tools.push(t.name),on:n=>hooks.push(n)}); process.stdout.write(JSON.stringify({tools:tools.sort(),hooks}));'
            seen = []
            class Rpc:
                def __init__(self, **kwargs):
                    kwargs.pop('diagnostics', None)
                    kwargs.pop('private_failure_sink', None)
                    self.config = PiRpcConfig(**kwargs)
                    self.stderr = b''
                    self.last_failure = None
                async def run(self, prompt, *, signal, on_event):
                    result = await asyncio.to_thread(subprocess.run,
                        [shutil.which('node'), '--loader', str(resolver), '--input-type=module', '-e', script],
                        env={**self.config.environment, **({'ASTERION_PI_EXTENSION_SOURCE_SHA256': '0' * 64}
                             if mismatch == 'digest' else {})}, pass_fds=self.config.inherited_fds,
                        capture_output=True, text=True)
                    if result.returncode:
                        raise RuntimeError('registration rejected')
                    seen.append(json.loads(result.stdout))
                    events = tuple(PiRpcEvent(i+1, name, {}) for i, name in enumerate(
                        ('agent_start', 'turn_start', 'turn_end', 'agent_end', 'agent_settled')))
                    for event in events:
                        on_event(event)
                    return PiRpcResult('', events, b'')
                def stop(self):
                    pass
                async def close(self):
                    pass
            registry = PrimeApplicationToolRegistry('example.tools', 'example.lookup', ('example_lookup', 'ipython'))
            spec = PrimeApplicationSpec('example.unregistered', '1.0.0', 'persistent-code-tools',
                                       tools=PrimeToolModuleArtifact(bundle, registry))
            operator = PrimeOperatorContext(Path(shutil.which('node')), None, root, 'openai-codex',
                'gpt-6.1-sol', 'medium', {}, TaskDeadline(deadline_monotonic=time.monotonic()+60, deadline_epoch=time.time()+60))
            limits = AsterionPrimeLimits(2, 2, 30_000)
            for mismatch in (False, 'registry', 'digest'):
                with self.subTest(mismatch=mismatch):
                    selected = replace(spec, tools=replace(spec.tools, registry=replace(registry, tool_names=('ipython',)))) if mismatch == 'registry' else spec
                    app = prepare_prime_application(selected, operator, authorization=limits)
                    with (patch('asterion.runtime.native_rpc.build_rpc_session', side_effect=Rpc),
                          patch.object(_launch, 'persistent_launch', wraps=_launch.persistent_launch) as launch,
                          patch('asterion.applications.discovery.list_application_providers', side_effect=AssertionError('lookup')),
                          patch('asterion.applications.discovery.load_application_provider', side_effect=AssertionError('lookup')),
                          patch('asterion.applications.prime.inventory.prime_release_application', side_effect=AssertionError('lookup'))):
                        runtime = app.runtime(services=_Services(), limits=limits, hooks=PrimeRunHooks())
                        self.assertEqual(launch.call_count, 0)
                        events = [e async for e in runtime.run(RunRequest('independent', 'hello', ('prime.tool.ipython',)), signal=_NeverCancelled())]
                        self.assertEqual(events[0].type, 'run.started')
                        self.assertEqual(launch.call_count, 1)
                        self.assertEqual(events[-1].type, 'run.failed' if mismatch else 'run.completed')
                        self.assertTrue((await app.close()).complete)
            self.assertEqual(seen, [{'tools': ['example_lookup', 'ipython'], 'hooks': []}])
