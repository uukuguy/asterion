"""Provider-free checks for the guest-owned witness wall deadline."""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import operator
from asterion.applications.prime.p7.solver_control import SolverControl
from asterion.applications.prime.p7.runtime_binding import build_p7_runtime
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from tests.test_prime_p7_native_provider import ASSEMBLY, _Worker, _CompletingEngine
from tests.test_asterion_prime_session import SessionFixture, FakePiRpcSession
from asterion.agents.prime.session import AsterionPrimeSession, AsterionPrimeLimits, ASTERION_PRIME_LIMITS
from asterion.runtimes.pi_rpc import PiRpcConfig
from asterion.runtime.protocol import ProtocolError
from tools import run_prime_p7_guest as guest


STARTED = 'ASTERION_PRIME_P7_ATTEMPT_STARTED_MONOTONIC'


def environment(start='100.0'):
    return {
        'ASTERION_PRIME_P7_RUN_MODE': 'witness',
        'ASTERION_PRIME_P7_ATTEMPT_SECONDS': '900',
        'ASTERION_PRIME_P7_ATTEMPT_UNIT': 'asterion-p7-' + 'a' * 32 + '.service',
        'ASTERION_PRIME_P7_CONSOLE_RUN_ID': 'p7-live-20261005123456-' + 'a' * 24,
        STARTED: start,
    }


class TestWitnessDeadline(unittest.TestCase):
    def test_plain_make_witness_preset_gets_guest_identity_and_fixed_deadline(self):
        makefile = (Path(__file__).resolve().parents[1] / 'Makefile').read_text()
        self.assertIn('if [ "$$ASTERION_PRIME_P7_RUN_MODE" = witness ]; then exec python3 '
                      '"$$ASTERION_PRIME_OPERATOR_ROOT/tools/run_prime_p7_guest.py" witness -- "$$@"', makefile)
        with patch.dict(os.environ, {'ASTERION_PRIME_P7_RUN_MODE': 'witness'}, clear=True), \
             patch.object(guest.Path, 'is_file', return_value=True), \
             patch('time.monotonic', return_value=100.0), \
             patch.object(guest.sys, 'argv', ['guest', 'witness', '--', 'python3', '-V']), \
             patch.object(guest.os, 'execvp', side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                guest.main()
            self.assertRegex(os.environ['ASTERION_PRIME_P7_ATTEMPT_UNIT'], r'^asterion-p7-[0-9a-f]{32}\.service$')
            self.assertEqual(os.environ['ASTERION_PRIME_P7_ATTEMPT_SECONDS'], '900')
            self.assertEqual(operator._witness_deadline({**os.environ, STARTED: '100.0'}), 1000.0)
        args = execute.call_args.args[1]
        self.assertIn('--property=RuntimeMaxSec=900s', args)
        self.assertIn('--setenv=' + STARTED + '=100.0', args)

    def test_witness_preset_preserves_complete_identity_and_rejects_partial_or_extended(self):
        original = environment()
        for env in (original, {'ASTERION_PRIME_P7_RUN_MODE': 'witness',
                              'ASTERION_PRIME_P7_ATTEMPT_SECONDS': '900'},
                    {**original, 'ASTERION_PRIME_P7_ATTEMPT_SECONDS': '3600'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), \
                 patch.object(guest.Path, 'is_file', return_value=True), \
                 patch.object(guest.os, 'execvp', side_effect=SystemExit) as execute:
                if env == original:
                    with self.assertRaises(SystemExit):
                        guest.witness(['python3', '-V'])
                    self.assertIn('--unit=' + original['ASTERION_PRIME_P7_ATTEMPT_UNIT'], execute.call_args.args[1])
                else:
                    with self.assertRaises(ValueError):
                        guest.witness(['python3', '-V'])
                    execute.assert_not_called()

    def test_native_host_can_only_narrow_time_and_must_keep_callback_contract(self):
        baseline = ASTERION_PRIME_LIMITS
        for deadline, callbacks in ((1, baseline.model_callbacks), (900000, baseline.model_callbacks),
                                    (900000, baseline.model_callbacks - 1)):
            with self.subTest(deadline=deadline, callbacks=callbacks):
                fixture = SessionFixture()
                lease = fixture.binding.preflight()
                try:
                    limits = AsterionPrimeLimits(callbacks, baseline.tool_callbacks, deadline)
                    config = PiRpcConfig(command=('pi', *lease.command_args()), cwd=fixture.root,
                                         environment=dict(lease.environment),
                                         deadline_seconds=deadline / 1000,
                                         inherited_fds=lease.inherited_fds)
                    def build():
                        return AsterionPrimeSession(
                            rpc_session=FakePiRpcSession(config, ()), extension_binding=fixture.binding,
                            extension_lease=lease, approved_command=config.command, limits=limits)
                    if callbacks != baseline.model_callbacks:
                        with self.assertRaises(ProtocolError):
                            build()
                    else:
                        build().close()
                finally:
                    lease.close()
                    fixture.close()
        for deadline in (0, baseline.deadline_ms + 1, float('inf'), float('nan')):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                AsterionPrimeLimits(baseline.model_callbacks, baseline.tool_callbacks, deadline)

    def test_exact_operator_host_binds_native_limits_and_rejects_option_only_override(self):
        for witness in (False, True):
            with self.subTest(witness=witness), tempfile.TemporaryDirectory() as directory, \
                 patch('time.monotonic', return_value=125.0):
                root = Path(directory).resolve()
                extension = root / 'extension.mjs'
                extension.write_text('export default function extension() {}\n')
                (root / 'trace').mkdir()
                env = {'ASTERION_PRIME_PI_AGENT_DIR': str(Path.home() / '.pi/agent'),
                       'ASTERION_PRIME_PROVIDER': 'openai-codex',
                       'ASTERION_PRIME_MODEL': 'gpt-6-sol',
                       'ASTERION_PRIME_P7_HISTORY_VARIANT': 'verified',
                       **(environment() if witness else {})}
                worker = _Worker()
                resources = operator.build_p7_operator_resources(
                    environment=env, pi_base_command=('/usr/bin/pi', '--mode', 'rpc'),
                    extension_path=extension, working_directory=root,
                    worker=worker, engine=_CompletingEngine(), private_trace_root=root / 'trace')
                try:
                    launch = resources.host_services['prime.launch']
                    self.assertEqual(launch.deadline_seconds, 900.0 if witness else 3600.0)
                    self.assertNotIn(STARTED, launch.approved_environment)
                    self.assertEqual(resources.runtime_options['deadline_ms'], '900000' if witness else '3600000')
                    ipython = resources.host_services['prime.ipython']
                    self.assertEqual(ipython.control.budget_snapshot()['wall_time_remaining_seconds'],
                                     875.0 if witness else 3600.0)
                    context = RuntimeFactoryContext(
                        provider_id='prime-applications', application_id='prime.arc-agi-3-solving',
                        application_version='1.0.0', runtime_id='asterion.prime',
                        assembly_path=ASSEMBLY, options=resources.runtime_options,
                        host_services=resources.host_services)
                    if not witness:
                        context = replace(context, options={**resources.runtime_options, 'deadline_ms': '900000'})
                        with self.assertRaises(RuntimeFactoryError):
                            build_p7_runtime(context)
                    else:
                        runtime = build_p7_runtime(context)
                        self.assertEqual(runtime._session._limits.deadline_ms, 900000)
                        self.assertEqual(runtime._session._rpc_session.config.deadline_seconds, 900.0)
                        runtime._session.close()
                    self.assertEqual(worker.starts, 0)
                finally:
                    asyncio.run(resources.close())

    def test_guest_overwrites_caller_clock_and_keeps_fixed_external_limit(self):
        env = environment('999999999')
        with patch.dict(os.environ, env, clear=True), \
             patch.object(guest.Path, 'is_file', return_value=True), \
             patch('time.monotonic', return_value=100.0), \
             patch.object(guest.os, 'execvp', side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                guest.launch(env['ASTERION_PRIME_P7_ATTEMPT_UNIT'], 900, ['python3', '-V'])
        args = execute.call_args.args[1]
        self.assertIn('--property=RuntimeMaxSec=900s', args)
        self.assertIn('--setenv=' + STARTED + '=100.0', args)
        self.assertNotIn('999999999', ' '.join(args))
        self.assertNotIn(STARTED, guest._environment_names())

    def test_effective_deadline_counts_startup_and_rejects_untrusted_bounds(self):
        with patch('time.monotonic', return_value=125.0):
            self.assertEqual(operator._witness_deadline(environment()), 1000.0)
            self.assertIsNone(operator._witness_deadline({}))
            for changed in ({STARTED: '126'}, {STARTED: 'nan'}, {STARTED: 'inf'},
                            {STARTED: '-1'}, {'ASTERION_PRIME_P7_ATTEMPT_SECONDS': '3600'},
                            {'ASTERION_PRIME_P7_RUN_MODE': 'solve'}):
                with self.subTest(changed=changed), self.assertRaises(operator.P7OperatorError):
                    operator._witness_deadline({**environment(), **changed})
            with self.assertRaises(operator.P7OperatorError):
                operator._witness_deadline({k: v for k, v in environment().items() if k != STARTED})
        with patch('time.monotonic', return_value=1000.0), self.assertRaises(operator.P7OperatorError):
            operator._witness_deadline(environment())

    def test_wall_budget_and_cancellation_share_deadline_without_pause_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'run-test'
            root.mkdir()
            now = [125.0]
            control = SolverControl(root, root.name, 1000.0, clock=lambda: now[0])
            self.assertEqual(control.budget_snapshot(), {'wall_time_remaining_seconds': 875.0})
            control.request('pause', 'pause')
            now[0] = 995.0
            self.assertEqual(control.budget_snapshot()['wall_time_remaining_seconds'], 5.0)
            parent = SimpleNamespace(cancelled=False)
            with patch('time.monotonic', side_effect=lambda: now[0]):
                signal = operator._WitnessDeadlineSignal(parent, 1000.0)
                self.assertFalse(signal.cancelled)
                now[0] = 1000.0
                self.assertTrue(signal.cancelled)
                self.assertEqual(control.budget_snapshot()['wall_time_remaining_seconds'], 0.0)
                self.assertFalse(control.action_allowed())
            self.assertNotIn('wall_time_remaining_seconds', control.snapshot())


if __name__ == '__main__':
    unittest.main()
