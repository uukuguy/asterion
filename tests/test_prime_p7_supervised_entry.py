"""Provider-free authorization and lifecycle boundaries for supervised research."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.game import DEFAULT_GAME
from asterion.applications.prime.p7.operator import (
    P7OperatorError, _select_game_for_mode, resolve_p7_runtime, p7_runtime_options,
)
from asterion.applications.prime.p7.solver_control import SolverControl


class TestSupervisedEntry(unittest.TestCase):
    def test_research_authorizes_null_limits_and_rejects_mixing(self):
        from dataclasses import replace
        game = replace(DEFAULT_GAME, supervised_research=True)
        environment = {'ASTERION_PRIME_P7_RUN_MODE': 'research',
                       'ASTERION_PRIME_PI_AGENT_DIR': str(Path.home() / '.pi/agent')}
        selection = resolve_p7_runtime(environment, game)
        self.assertIsNone(selection.deadline_ms)
        self.assertIsNone(selection.max_callbacks)
        self.assertIsNone(selection.max_actions)
        self.assertEqual({k: p7_runtime_options(selection, game)[k]
                          for k in ('deadline_ms', 'max_callbacks', 'max_actions')},
                         dict.fromkeys(('deadline_ms', 'max_callbacks', 'max_actions'), 'none'))
        for changed, selected_game in (({}, DEFAULT_GAME),
            ({'ASTERION_PRIME_P7_RUN_MODE': 'solve'}, game),
            ({'ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND': '1'}, game)):
            with self.subTest(changed=changed), self.assertRaises(P7OperatorError):
                resolve_p7_runtime({**environment, **changed}, selected_game)

    def test_research_resources_have_no_hidden_control_deadline_and_one_cleanup_window(self):
        import asyncio
        from dataclasses import replace
        from tests.test_prime_p7_native_provider import _CompletingEngine, _Worker
        from asterion.applications.prime.p7.operator import build_p7_operator_resources
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / 'extension.mjs'
            extension.write_text('export default function () {}')
            (root / 'trace').mkdir()
            engine = _CompletingEngine()
            game = replace(DEFAULT_GAME, supervised_research=True)
            resources = build_p7_operator_resources(
                environment={'ASTERION_PRIME_P7_RUN_MODE': 'research',
                             'ASTERION_PRIME_PI_AGENT_DIR': str(Path.home() / '.pi/agent')},
                executable=Path('/usr/bin/pi'), extension_path=extension,
                working_directory=root, worker=_Worker(), engine=engine,
                private_trace_root=root / 'trace', game=game)
            try:
                limits = resources.application.authorized_limits
                self.assertEqual((limits.model_callbacks, limits.tool_callbacks, limits.deadline_ms),
                                 (None, None, None))
                host = resources.host_services['prime.ipython']
                self.assertIsNone(host.control._deadline)
                self.assertIsNone(engine._supervised_settlement.budget)
                host.request_stop()
                host.poll()
                deadline = engine._supervised_settlement.budget
                self.assertIsNotNone(deadline)
                self.assertIs(engine._supervised_settlement.start(), deadline)
                self.assertLessEqual(deadline.remaining_seconds(), 180.)
                self.assertFalse(host.control.action_allowed())
            finally:
                asyncio.run(resources.close())

    def test_win_marker_matches_summary_after_native_finalization_failure(self):
        from dataclasses import replace
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7 import live
        from asterion.applications.prime.p7.operator import _P7BrokerClient, _seal_verified_game_win
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from tests.test_prime_p7_native_broker import _FullGameEngine
        for supervised in (False, True):
            with self.subTest(supervised=supervised), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                run = root / 'run-test'
                run.mkdir()
                (run / 'trace').mkdir()
                game = replace(DEFAULT_GAME, target_level=7, supervised_research=supervised)
                broker = ArcBroker(engine=_FullGameEngine(), game=game)
                recorder = PrimeTraceRecorder(run / 'trace')
                self.addCleanup(recorder.close)
                client = _P7BrokerClient(broker, recorder, variant='legacy')
                for _ in range(7):
                    client.act([{'name': 'ACTION1', 'data': {}}])
                receipt = broker.seal()
                broker.replay(_FullGameEngine)
                evidence = P7PrivateTraceReceipt(broker, recorder)
                self.assertTrue(_seal_verified_game_win(broker, evidence, receipt))
                marker = next(entry.payload for entry in recorder.snapshot()
                              if entry.kind == 'arc.run.game-won')
                live.write_summary(root, run, run_id=run.name, receipt={}, broker_receipt=receipt,
                    game=game, replay_verified=True, sealed_trace=True, cleanup_complete=True,
                    comparison_report=None, reason='native finalization failed',
                    failure=RuntimeError('model settlement failed'), diagnostics={})
                summary = json.loads((run / 'summary.json').read_text())
                self.assertEqual(marker, summary['broker'])
                self.assertEqual(marker.get('supervised_research', False), supervised)
                if not supervised:
                    self.assertNotIn('supervised_research', marker)

    def test_research_default_is_full_game_and_config_cannot_authorize(self):
        with patch('asterion.applications.prime.p7.operator.resolve_game_selection',
                   return_value=DEFAULT_GAME) as resolve:
            game = _select_game_for_mode({'ASTERION_PRIME_P7_RUN_MODE': 'research'},
                {'ASTERION_PRIME_P7_TARGET_LEVEL': '1'}, Path('/unused'))
        self.assertTrue(game.supervised_research)
        self.assertNotIn('ASTERION_PRIME_P7_TARGET_LEVEL', resolve.call_args.args[0])

    def test_unbounded_control_survives_hours_pause_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'run-test'
            root.mkdir()
            now = [0.]
            control = SolverControl(root, root.name, None, clock=lambda: now[0])
            now[0] = 100_000.
            self.assertTrue(control.action_allowed())
            self.assertIsNone(control.budget_snapshot()['wall_time_remaining_seconds'])
            control.request('pause', 'pause')
            self.assertFalse(control.action_allowed())
            control.request('resume', 'resume')
            self.assertTrue(control.action_allowed())
            control.request('stop', 'stop')
            self.assertFalse(control.action_allowed())
            self.assertEqual(control.snapshot()['state'], 'stop_requested')

    def test_research_guest_has_no_runtime_cutoff_and_bounded_stop(self):
        from tools.run_prime_p7_guest import research
        with patch.dict(os.environ, {'ASTERION_PRIME_P7_RUN_MODE': 'research'}, clear=True), \
             patch('tools.run_prime_p7_guest.Path.is_file', return_value=True), \
             patch('tools.run_prime_p7_guest._supervise', side_effect=SystemExit(0)) as execute:
            with self.assertRaises(SystemExit):
                research(['python3', '-V'])
        args = execute.call_args.args[1]
        self.assertIn('--property=TimeoutStopSec=180s', args)
        self.assertFalse(any(arg.startswith('--property=RuntimeMaxSec=') for arg in args))

    def test_research_supervisor_checks_cleanup_after_wait(self):
        from tools.run_prime_p7_guest import _supervise
        unit = 'asterion-p7-' + 'a' * 32 + '.service'
        with patch('tools.run_prime_p7_guest.subprocess.Popen') as child, \
             patch('tools.run_prime_p7_guest.cleanup', return_value=True) as cleaned:
            child.return_value.wait.return_value = 0
            self.assertEqual(_supervise(unit, ['systemd-run', '--wait']), 0)
        cleaned.assert_called_once_with(unit)

    def test_research_signal_fences_launcher_before_group_cleanup(self):
        import signal
        import subprocess
        from tools.run_prime_p7_guest import _supervise
        unit = 'asterion-p7-' + 'a' * 32 + '.service'
        handlers, order = {}, []
        def register(signum, handler):
            handlers[signum] = handler
            return signal.SIG_DFL
        waits = [True, False]
        def wait(**_kwargs):
            if waits.pop(0):
                handlers[signal.SIGTERM](signal.SIGTERM, None)
                raise subprocess.TimeoutExpired('systemd-run', 1)
            order.append('launcher-reaped')
            return 0
        with patch('tools.run_prime_p7_guest.signal.signal', side_effect=register), \
             patch('tools.run_prime_p7_guest.subprocess.Popen') as child, \
             patch('tools.run_prime_p7_guest.cleanup', side_effect=lambda _unit: order.append('cleanup') or True):
            child.return_value.wait.side_effect = wait
            child.return_value.terminate.side_effect = lambda: order.append('launcher-fenced')
            self.assertEqual(_supervise(unit, ['systemd-run', '--wait']), 130)
        self.assertEqual(order, ['launcher-fenced', 'launcher-reaped', 'cleanup'])

    def test_monitor_keeps_counters_heartbeat_and_safe_atomic_projection(self):
        from types import SimpleNamespace
        from asterion.applications.prime.p7.research_monitor import ResearchMonitor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'run-test'
            root.mkdir()
            now = [2.]
            status = SimpleNamespace(primitive_actions=6000, levels_completed=1)
            broker = SimpleNamespace(status=lambda: status,
                                     journal=[SimpleNamespace(action='RESET')])
            owner = SimpleNamespace(runtime_observation=lambda: {
                'model_callbacks': 129, 'tool_callbacks': 600})
            monitor = ResearchMonitor(root, root.name, broker, owner, clock=lambda: now[0])
            monitor.event('usage.reported', {'input_tokens': 9, 'output_tokens': 4,
                                           'prompt': 'SECRET_SENTINEL'})
            now[0] = 4002.
            monitor.sample()
            record = json.loads((root / 'research-status.json').read_text())
            self.assertEqual((record['model_callbacks'], record['tool_callbacks']), (129, 600))
            self.assertEqual((record['primitive_actions'], record['resets']), (6000, 1))
            self.assertEqual(record['elapsed_seconds'], 4000.)
            self.assertNotIn('SECRET_SENTINEL', json.dumps(record))
            monitor.finish(cleanup_complete=False, stop_requested=True)
            record = json.loads((root / 'research-status.json').read_text())
            self.assertEqual(record['phase'], 'closed')
            self.assertFalse(record['cleanup_complete'])
            self.assertTrue(record['stop_requested'])


class TestResearchHeartbeat(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_model_updates_without_native_events(self):
        import asyncio
        from types import SimpleNamespace
        from asterion.applications.prime.p7.research_monitor import ResearchMonitor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'run-test'
            root.mkdir()
            broker = SimpleNamespace(status=lambda: SimpleNamespace(primitive_actions=0,
                levels_completed=0), journal=[])
            owner = SimpleNamespace(runtime_observation=lambda: {'model_callbacks': 1})
            clock = [0.]
            monitor = ResearchMonitor(root, root.name, broker, owner, clock=lambda: clock[0])
            stopped = asyncio.Event()
            heartbeat = asyncio.create_task(monitor.heartbeat(stopped,
                SimpleNamespace(cancelled=False), SimpleNamespace(poll=lambda: {'state': 'running'})))
            await asyncio.sleep(.01)
            clock[0] = 5000.
            await asyncio.sleep(1.05)
            stopped.set()
            await heartbeat
            record = json.loads((root / 'research-status.json').read_text())
            self.assertEqual(record['elapsed_seconds'], 5000.)
            self.assertEqual(record['model_callbacks'], 1)
            self.assertEqual(record['phase'], 'running')
