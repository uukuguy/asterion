"""Provider-free finite cold autonomy contract; no actual ARC game input."""
import os
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import operator, runtime_binding
from asterion.applications.prime.p7.game import P7GameSelection
from tools import run_prime_p7_guest as guest


def environment(wrapper=None):
    return {'ASTERION_PRIME_P7_RUN_MODE': 'autonomy',
            'ASTERION_PRIME_P7_TARGET_LEVEL': '6', 'OPERATION_MODE': 'offline',
            'ASTERION_PRIME_P7_ATTEMPT_SECONDS': '5400',
            'ASTERION_PRIME_P7_ATTEMPT_UNIT': 'asterion-p7-' + 'a' * 32 + '.service',
            'ASTERION_PRIME_P7_ATTEMPT_STARTED_MONOTONIC': '100.0',
            **({'ASTERION_PRIME_P7_RESEARCH_PYTHON': str(wrapper)} if wrapper else {})}


class TestP7Autonomy(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.wrapper = Path(temporary.name).resolve() / 'research-python'
        self.wrapper.write_text('#!/bin/sh\nexit 0\n')
        self.wrapper.chmod(0o700)

    def test_research_python_wrapper_is_explicit_autonomy_only_and_not_symlink(self):
        self.assertTrue(callable(getattr(operator, '_research_python', None)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            wrapper = root / 'research-python'
            wrapper.write_text('#!/bin/sh\nexit 0\n')
            wrapper.chmod(0o700)
            field = 'ASTERION_PRIME_P7_RESEARCH_PYTHON'
            selected = {**environment(self.wrapper), field: str(wrapper)}
            self.assertEqual(operator._research_python(selected), wrapper)
            self.assertIsNone(operator._research_python({}))
            with self.assertRaises(operator.P7OperatorError):
                operator._research_python({"ASTERION_PRIME_P7_RUN_MODE": "autonomy"})
            link = root / 'linked-python'
            link.symlink_to(wrapper)
            for changed in ({field: str(link)}, {field: 'relative-wrapper'},
                            {'ASTERION_PRIME_P7_RUN_MODE': 'solve'}):
                with self.subTest(changed=changed), self.assertRaises(operator.P7OperatorError):
                    operator._research_python({**selected, **changed})
            wrapper.chmod(0o600)
            with self.assertRaises(operator.P7OperatorError):
                operator._research_python(selected)

    def test_autonomous_initial_guidance_has_actor_choice_and_feedback(self):
        self.assertTrue(callable(getattr(operator, '_autonomy_prompt', None)))
        text = operator._autonomy_prompt()
        self.assertIn('actual feedback', text)
        self.assertIn('partial', text.lower())
        self.assertNotIn('实际运行程序比较路线', text)
        self.assertNotIn('same-game past attempts', text)

    def test_actual_closed_broker_goal_and_cap_are_task_stop(self):
        from asterion.applications.prime.p7.broker import ArcBroker
        from tests.test_prime_p7_native_broker import _Engine
        from dataclasses import replace
        for cap_reason in ('human-baseline', 'action-cap'):
            game = replace(P7GameSelection('ls20-9607627b', 0, 6),
                           action_cap_override=1, action_cap_reason=cap_reason)
            broker = ArcBroker(engine=_Engine(), game=game)
            self.assertFalse(runtime_binding._p7_terminal(broker))
            broker.act(('ACTION1',))
            self.assertTrue(runtime_binding._p7_terminal(broker))
            self.assertEqual(broker.terminal_snapshot().status.terminal_reason, cap_reason)

    def test_exact_factory_uses_finite_profile_and_absolute_outer_admission(self):
        from dataclasses import replace
        from asterion.runtime.factory import RuntimeFactoryContext
        from tests.test_prime_p7_native_provider import ASSEMBLY, _Worker
        from tests.test_prime_p7_native_broker import _Engine
        from asterion.applications.prime.p7.model_selection import P7ModelSelection
        with tempfile.TemporaryDirectory() as directory, patch('time.monotonic', return_value=125.0), \
             patch.object(operator, 'resolve_model_selection', return_value=P7ModelSelection('openai-codex', 'gpt-6.1-sol')):
            root = Path(directory).resolve() / 'cold-run'
            root.mkdir()
            extension = root / 'extension.mjs'
            extension.write_text('export default function extension() {}\n')
            (root / 'trace').mkdir()
            env = {**environment(self.wrapper), 'ASTERION_PRIME_MODEL': 'gpt-6.1-sol'}
            game = replace(P7GameSelection('ls20-9607627b', 0, 6),
                           action_cap_override=1000, action_cap_reason='action-cap')
            resources = operator.build_p7_operator_resources(environment=env,
                pi_base_command=('/usr/bin/pi', '--mode', 'rpc'), extension_path=extension,
                working_directory=root, worker=_Worker(), engine=_Engine(),
                private_trace_root=root / 'trace', game=game)
            try:
                launch = resources.host_services['prime.launch']
                host = resources.host_services['prime.ipython']
                self.assertNotIn('ASTERION_PRIME_P7_RESEARCH_PYTHON', launch.approved_environment)
                self.assertEqual(launch.autonomy_deadline_monotonic, 5500.0)
                self.assertEqual(host.control._deadline, 5500.0)
                context = RuntimeFactoryContext(provider_id='prime-applications',
                    application_id='prime.arc-agi-3-solving', application_version='1.0.0',
                    runtime_id='asterion.prime', assembly_path=ASSEMBLY,
                    options=resources.runtime_options, host_services=resources.host_services)
                runtime = runtime_binding.build_p7_runtime(context)
                session = runtime._session
                self.assertEqual(session._limits.model_callbacks, 1024)
                self.assertEqual(session._limits.tool_callbacks, 4096)
                self.assertEqual(session._limits.deadline_ms, 5400000)
                self.assertEqual(session._rpc_session.config.deadline_seconds, 5400.0)
                self.assertTrue(session._kernel._reusable)
                signal = SimpleNamespace(cancelled=False)
                self.assertTrue(asyncio.run(session._kernel._round_admission(5, signal)))
                for _ in range(10):
                    self.assertTrue(asyncio.run(host.admit_round(0, signal)))
                self.assertFalse(asyncio.run(session._kernel._round_admission(6, signal)))
                session.close()
            finally:
                asyncio.run(resources.close())

    def test_cold_run_never_loads_prior_experience_or_prefix(self):
        class StopBeforeRuntime(Exception):
            pass
        with tempfile.TemporaryDirectory() as directory, patch('time.monotonic', return_value=125.0):
            root = Path(directory).resolve()
            game = P7GameSelection('test-1', 0, 6, (10,) * 9, 9, 1000, 'action-cap')
            invocation = operator.P7Invocation(root, environment(self.wrapper), root,
                                               ('pi',), root / 'extension.mjs', game)
            with patch('asterion.applications.prime.p7.experience.load_experience') as experience, \
                 patch('asterion.applications.prime.p7.solutions.load_best_prefix') as prefix, \
                 patch.object(operator.live, 'SubprocessPythonWorker'), \
                 patch.object(operator.live, 'ArcadeEngine'), \
                 patch.object(operator, 'build_p7_operator_resources', side_effect=StopBeforeRuntime):
                with self.assertRaises(StopBeforeRuntime):
                    asyncio.run(operator.run_live(invocation, 'cold-empty-run'))
                experience.assert_not_called()
                prefix.assert_not_called()

    def test_task_terminal_keeps_reset_actor_owned_and_recoverable(self):
        for reason in ('active', 'reset-required', 'level-completed', 'action-cap', 'evidence-unavailable'):
            with self.subTest(reason=reason):
                broker = SimpleNamespace(status=lambda: SimpleNamespace(terminal_reason=reason),
                                         seal=lambda: object())
                self.assertEqual(runtime_binding._p7_terminal(broker),
                                 reason not in {'active', 'reset-required'})

    def test_autonomy_deadline_is_launcher_origin_and_rejects_conflicting_authority(self):
        self.assertTrue(callable(getattr(operator, '_autonomy_deadline', None)))
        with patch('time.monotonic', return_value=125.0):
            self.assertEqual(operator._autonomy_deadline(environment(self.wrapper)), 5500.0)
            for change in ({'OPERATION_MODE': 'online'},
                           {'ASTERION_PRIME_P7_TARGET_LEVEL': '5'},
                           {'ASTERION_PRIME_P7_ATTEMPT_SECONDS': '900'},
                           {'ASTERION_PRIME_P7_RESUME_RUN_ID': 'prior'},
                           {'ASTERION_PRIME_P7_HISTORY_VARIANT': 'legacy'}):
                with self.subTest(change=change), self.assertRaises(operator.P7OperatorError):
                    operator._autonomy_deadline({**environment(self.wrapper), **change})
        with patch('time.monotonic', return_value=5500.0), self.assertRaises(operator.P7OperatorError):
            operator._autonomy_deadline(environment(self.wrapper))

    def test_autonomy_selection_has_fixed_target_and_paid_cap(self):
        game = P7GameSelection('test-1', 0, 6, (10,) * 9, 9)
        with patch.object(operator, 'resolve_game_selection', return_value=game), \
             patch('time.monotonic', return_value=125.0):
            selected = operator._select_game_for_mode(environment(self.wrapper), environment(self.wrapper), Path('/unused'))
        self.assertEqual(selected.target_level, 6)
        self.assertEqual(selected.action_cap, 1000)
        self.assertEqual(selected.action_cap_reason, "action-cap")

    def test_guest_cold_preset_is_finite_and_keeps_cleanup_separate(self):
        self.assertTrue(callable(getattr(guest, 'autonomy', None)))
        with patch.dict(os.environ, environment(self.wrapper), clear=True), \
             patch.object(guest.Path, 'is_file', return_value=True), \
             patch('time.monotonic', return_value=100.0), \
             patch.object(guest.os, 'execvp', side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                guest.autonomy(['python3', '-V'])
        args = execute.call_args.args[1]
        self.assertIn('--property=RuntimeMaxSec=5400s', args)
        self.assertIn('--property=TimeoutStopSec=180s', args)
        self.assertIn('--setenv=ASTERION_PRIME_P7_ATTEMPT_STARTED_MONOTONIC=100.0', args)
        self.assertFalse(any('CONSOLE_RUN_ID' in value for value in args))
