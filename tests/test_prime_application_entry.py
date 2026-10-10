"""Effect-free, immutable independent Prime application construction."""

import asyncio
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

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
from asterion.runtime.protocol import ProtocolError


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
            app.text_model(key='conversation.one', limits=self.limits)
        with self.assertRaises(ProtocolError):
            asyncio.run(app.text_once(key='conversation.one', text='private-sentinel',
                                      limits=self.limits, signal=object()))
        with self.assertRaises(ProtocolError):
            asyncio.run(app.open_backend(spec=object(), services=object()))
        receipt = asyncio.run(app.close())
        self.assertTrue(receipt.complete)
        self.assertEqual(app.state, 'closed')
        self.assertEqual(receipt, asyncio.run(app.close()))
        with self.assertRaises(ProtocolError):
            app._admit_text_limits('conversation.one', self.limits)

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


if __name__ == '__main__':
    unittest.main()
