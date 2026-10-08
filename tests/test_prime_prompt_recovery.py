from __future__ import annotations

import json
import asyncio
import sys
import time
import unittest
from types import SimpleNamespace

from asterion.agents.prime import execution
from asterion.agents.prime.session import AsterionPrimeSession
from asterion.runtime.protocol import validate_event_stream
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession
from tests.test_asterion_prime_session import FakeSignal, SessionFixture, collect


SCRIPT = r'''
import json, os, sys
def emit(kind, **payload):
    print(json.dumps(dict(type=kind, **payload)), flush=True)
count = 0
for line in sys.stdin:
    request = json.loads(line)
    if request['type'] != 'prompt':
        continue
    count += 1
    with open(os.environ['PROMPTS'], 'a') as stream:
        stream.write(json.dumps(request['message']) + '\n')
    emit('response', id=request['id'], success=True)
    emit('agent_start')
    emit('turn_start')
    if count > 1 and (os.environ['SCENARIO'] not in ('twice', 'later') or
                      os.environ['SCENARIO'] == 'later' and count == 2):
        emit('message_end', message=dict(role='assistant', stopReason='stop'))
        emit('agent_end', willRetry=False)
        emit('agent_settled')
        continue
    if os.environ['SCENARIO'] == 'provider-rejection':
        emit('message_end', message=dict(role='assistant', stopReason='error',
                                        status=400, errorMessage='PRIVATE-ERROR'))
        emit('agent_end', willRetry=False)
        emit('agent_settled')
        continue
    if count == 1 and os.environ['SCENARIO'] in ('certain', 'uncertain', 'unmatched'):
        emit('tool_execution_start', toolCallId='call-1', toolName='ipython', args={})
        if os.environ['SCENARIO'] != 'unmatched':
            emit('tool_execution_end', toolCallId='call-1', isError=False,
                 effect='uncertain' if os.environ['SCENARIO'] == 'uncertain' else 'certain')
    emit('message_end', message=dict(role='assistant', stopReason='error', errorMessage='PRIVATE-ERROR'))
    emit('agent_end', willRetry=True)
    emit('auto_retry_start', attempt=1, maxAttempts=1, delayMs=0, errorMessage='PRIVATE-ERROR')
    emit('agent_start')
    emit('turn_start')
    emit('message_end', message=dict(role='assistant', stopReason='error', errorMessage='PRIVATE-ERROR',
                                    **({'status': 400} if os.environ['SCENARIO'] == 'permanent' else {})))
    emit('agent_end', willRetry=False)
    emit('auto_retry_end', success=False, attempt=1, finalError='PRIVATE-ERROR')
    emit('agent_settled')
'''


class TestPrimePromptRecovery(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, *, scenario='certain', guard=lambda: True,
                       compact=False, backoff=0, deadline_ms=2000, signal=None,
                       completion=None, model_callbacks=20, host_deadline_seconds=None):
        self.assertTrue(hasattr(execution, 'PrimePromptRecovery'))
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        script = fixture.root / 'fake.py'
        script.write_text(SCRIPT)
        prompts = fixture.root / 'prompts.jsonl'
        lease = fixture.binding.preflight()
        limits = execution.AsterionPrimeLimits(model_callbacks, 20, deadline_ms)
        config = PiRpcConfig(
            command=(sys.executable, str(script), *lease.command_args()),
            cwd=fixture.root,
            environment={**lease.environment, 'SCENARIO': scenario, 'PROMPTS': str(prompts)},
            inherited_fds=lease.inherited_fds, deadline_seconds=deadline_ms / 1000,
            compact_events=compact,
        )
        rpc = PiRpcSession(config)
        session = AsterionPrimeSession(
            rpc_session=rpc, extension_binding=fixture.binding, extension_lease=lease,
            approved_command=config.command, approved_environment=config.environment,
            limits=limits,
            completion_predicate=completion,
            prompt_recovery=execution.PrimePromptRecovery(
                guard, backoff_seconds=backoff,
                deadline_monotonic=(None if host_deadline_seconds is None
                                    else time.monotonic() + host_deadline_seconds),
            ),
        )
        public = await collect(session, signal=signal, deadline_ms=deadline_ms)
        validate_event_stream([event.to_mapping() for event in public])
        sent = [json.loads(line) for line in prompts.read_text().splitlines()]
        self.assertIsNone(rpc.process)
        self.assertTrue(lease.closed)
        self.assertNotIn('PRIVATE-ERROR', repr(public))
        return public, sent, session

    async def test_exhausted_native_retry_continues_once_with_same_ledger(self):
        for compact in (False, True):
            with self.subTest(compact=compact):
                public, prompts, session = await self.run_case(compact=compact)
                self.assertEqual(public[-1].type, 'run.completed')
                self.assertEqual(len(prompts), 2)
                self.assertNotEqual(prompts[0], prompts[1])
                self.assertEqual(sum(event.type == 'tool.call' for event in public), 1)
                self.assertEqual(session._kernel.tool_callbacks, 1)
                self.assertEqual(session._kernel.model_callbacks, 3)

    async def test_second_exhaustion_cannot_renew_recovery_allowance(self):
        public, prompts, _ = await self.run_case(scenario='twice')
        self.assertEqual(public[-1].type, 'run.failed')
        self.assertEqual(len(prompts), 2)

    async def test_uncertain_unmatched_or_application_effect_blocks_recovery(self):
        for scenario, guard in (('uncertain', lambda: True), ('unmatched', lambda: True),
                                ('certain', lambda: False)):
            with self.subTest(scenario=scenario):
                public, prompts, _ = await self.run_case(scenario=scenario, guard=guard)
                self.assertEqual(public[-1].type, 'run.failed')
                self.assertEqual(len(prompts), 1)

    async def test_deadline_during_backoff_never_sends_continuation(self):
        public, prompts, _ = await self.run_case(backoff=.2, deadline_ms=150)
        self.assertEqual(public[-1].type, 'run.failed')
        self.assertEqual(len(prompts), 1)

    async def test_effect_guard_is_rechecked_after_backoff(self):
        calls = []
        def guard():
            calls.append(True)
            return len(calls) == 1
        public, prompts, _ = await self.run_case(guard=guard)
        self.assertEqual(public[-1].type, 'run.failed')
        self.assertEqual(len(prompts), 1)
        self.assertEqual(len(calls), 2)

    async def test_natural_continuation_does_not_reset_recovery_allowance(self):
        public, prompts, _ = await self.run_case(scenario='later', completion=lambda: False)
        self.assertEqual(public[-1].type, 'run.failed')
        self.assertEqual(len(prompts), 3)

    async def test_provider_rejection_and_exhausted_callback_budget_do_not_recover(self):
        for scenario, limit in (('provider-rejection', 20), ('permanent', 20), ('certain', 2)):
            with self.subTest(scenario=scenario):
                public, prompts, _ = await self.run_case(scenario=scenario, model_callbacks=limit)
                self.assertEqual(public[-1].type, 'run.failed')
                self.assertEqual(len(prompts), 1)

    async def test_cancellation_during_backoff_never_sends_continuation(self):
        signal = FakeSignal()
        def guard():
            asyncio.get_running_loop().call_later(.01, setattr, signal, 'cancelled', True)
            return True
        public, prompts, _ = await self.run_case(guard=guard, signal=signal, backoff=.1)
        self.assertEqual(public[-1].payload, {'status': 'cancelled'})
        self.assertEqual(len(prompts), 1)

    async def test_prime_admission_honors_earlier_host_deadline_and_completion(self):
        for options in ({'host_deadline_seconds': .15, 'backoff': .2},
                        {'completion': lambda: True}):
            with self.subTest(options=options):
                public, prompts, _ = await self.run_case(**options)
                self.assertEqual(public[-1].type, 'run.failed')
                self.assertEqual(len(prompts), 1)


class TestP7RecoveryEffects(unittest.IsolatedAsyncioTestCase):
    async def test_pending_action_receipt_and_busy_worker_block_recovery(self):
        from asterion.applications.prime.p7.action_journal import ActionJournal
        from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
        from asterion.applications.prime.p7.runtime_binding import _p7_recovery_effects_settled
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        journal = ActionJournal(fixture.root / 'journal', {'run_id': 'one'})
        broker = SimpleNamespace(
            _engine=SimpleNamespace(action_journal=journal, task_deadline=SimpleNamespace(expired=lambda: False)),
            _processing_blocked=False, status=lambda: SimpleNamespace(terminal_reason='active'),
        )
        worker = object.__new__(P7ResearchRuntime)
        worker._closed = worker._lost = False
        lock = asyncio.Lock()
        worker.kernel = SimpleNamespace(status=lambda: {'lost': False, 'closed': False}, _lock=lock)
        worker.solver = SimpleNamespace(current_context=lambda: {'processing_blocked': False})
        self.assertTrue(_p7_recovery_effects_settled(worker, broker))
        await lock.acquire()
        self.assertFalse(_p7_recovery_effects_settled(worker, broker))
        lock.release()
        journal.prepare(sequence=1, action={'name': 'ACTION1', 'data': {}}, before={'sequence': 0})
        self.assertFalse(_p7_recovery_effects_settled(worker, broker))
        journal.not_dispatched('rejected')
        self.assertTrue(_p7_recovery_effects_settled(worker, broker))
        broker._processing_blocked = True
        self.assertFalse(_p7_recovery_effects_settled(worker, broker))
