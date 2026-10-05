from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime.p7.console_session import ConsoleSession, ConsoleSessionError, _stop_process


RUN_ID = 'p7-live-20261005123456-' + 'a' * 24
CATALOG = ({'game_id': 'test-1', 'alias': 'test', 'win_levels': 2},)


class FakeProcess:
    pid = 12345

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


class ConsoleSessionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.process = FakeProcess()
        self.launched = threading.Event()
        self.calls = []
        self.cleanup_units = []

    def session(self, **changes):
        def launch(argv, **kwargs):
            self.calls.append((argv, kwargs))
            self.launched.set()
            return self.process

        def stop(process):
            process.returncode = -15

        def cleanup(unit):
            self.cleanup_units.append(unit)
            return True

        options = dict(catalog=CATALOG, process_factory=launch, process_stopper=stop,
                       guest_cleanup=cleanup, guest_activity_reader=lambda: False,
                       operator_environment_reader=lambda _: {'ASTERION_PRIME_MODEL': 'gpt-6.1-sol'},
                       run_id_factory=lambda: RUN_ID,
                       environment={}, poll_interval=0.01)
        options.update(changes)
        session = ConsoleSession(self.root, self.root, **options)
        self.addCleanup(session.close)
        return session

    def wait_state(self, session, *states):
        until = time.monotonic() + 2
        while time.monotonic() < until:
            view = session.view()
            if view['state'] in states:
                return view
            time.sleep(0.01)
        self.fail(f"state did not reach {states}: {session.view()}")


class TestPrimeP7ConsoleSession(ConsoleSessionFixture):
    def test_games_propagate_exact_arc_catalog_baselines_and_copy_results(self):
        resource = self.root / 'environment_files' / 'vc33' / 'test'
        resource.mkdir(parents=True)
        (resource / 'metadata.json').write_text(json.dumps({
            'game_id': 'vc33-test', 'win_levels': 2, 'baseline_actions': [7, 11]}))
        (resource / 'vc33.py').write_text('raise AssertionError("must not import game source")')
        session = self.session(catalog=None)
        expected = [{'game_id': 'vc33-test', 'alias': 'vc33', 'win_levels': 2,
                     'baseline_actions': [7, 11]}]
        self.assertEqual(session.games(), expected)
        session.games()[0]['baseline_actions'][0] = 99
        self.assertEqual(session.games(), expected)
        mismatch = self.session(catalog=({'game_id': 'vc33-test', 'alias': 'vc33', 'win_levels': 1},))
        self.assertNotIn('baseline_actions', mismatch.games()[0])
        self.assertNotIn('baseline_actions', self.session().games()[0])

    def test_real_process_group_cleans_term_ignoring_child_after_parent_exit(self):
        child_code = (
            "import os,signal,sys,time;from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)"
        )
        parent_code = (
            "import subprocess,sys,time;from pathlib import Path;"
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);"
            "\nwhile not Path(sys.argv[2]).exists(): time.sleep(.01)"
            "\nif sys.argv[3]=='natural': sys.exit(0)"
            "\ntime.sleep(60)"
        )
        for mode in ('terminated', 'natural'):
            with self.subTest(mode=mode):
                marker = self.root / (mode + '.pid')
                processes = []
                cleanup_observed = []
                def launch(*args, **kwargs):
                    process = subprocess.Popen(
                        [sys.executable, '-c', parent_code, child_code, str(marker), mode],
                        start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    processes.append(process)
                    return process
                def cleanup(unit):
                    try:
                        os.killpg(processes[0].pid, 0)
                    except ProcessLookupError:
                        cleanup_observed.append('group-gone')
                        return True
                    cleanup_observed.append('group-survived')
                    return False
                session = self.session(process_factory=launch, process_stopper=_stop_process,
                                       guest_cleanup=cleanup)
                try:
                    started = session.start('test-1', 'start')
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists(), 'child readiness was not recorded')
                    if mode == 'terminated':
                        session.stop(started['session_id'], 'stop')
                    view = self.wait_state(session, 'cancelled', 'incomplete', 'cleanup-unconfirmed')
                    self.assertTrue(view['cleanup_confirmed'])
                    self.assertEqual(cleanup_observed, ['group-gone'])
                    self.assertIsNotNone(processes[0].poll())
                    with self.assertRaises(ProcessLookupError):
                        os.killpg(processes[0].pid, 0)
                finally:
                    for process in processes:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=5)
                    session.close()


    def test_concurrent_start_deduplicates_and_read_never_launches(self):
        session = self.session()
        self.assertEqual(session.view()['state'], 'idle')
        self.assertFalse(self.calls)
        results = []
        threads = [threading.Thread(target=lambda: results.append(session.start('test-1', 'same'))) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(self.launched.wait(1))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len({r['session_id'] for r in results}), 1)
        with self.assertRaises(ConsoleSessionError):
            session.start('test-1', 'different')
        with self.assertRaises(ConsoleSessionError):
            session.start('other-1', 'same')
        self.assertEqual(session.view()['run_id'], RUN_ID)

    def test_contaminated_environment_does_not_change_finite_preset(self):
        polluted = {key: 'sentinel' for key in (
            'MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES', 'GNUMAKEFLAGS', 'MAKEFILES',
            'ASTERION_PRIME_P7_RUN_MODE', 'ASTERION_PRIME_P7_ATTEMPT_UNIT',
            'ASTERION_PRIME_P7_ATTEMPT_SECONDS', 'ASTERION_PRIME_P7_CONSOLE_RUN_ID',
            'OPERATION_MODE')}
        polluted['ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND'] = '1'
        session = self.session(environment=polluted)
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        argv, options = self.calls[0]
        self.assertEqual(argv[:4], ['make', 'asterion-prime-p7-level-witness', 'GAME=test-1', 'LEVEL=1'])
        self.assertIn('ASTERION_PRIME_P7_ATTEMPT_SECONDS=900', argv)
        self.assertTrue(options['start_new_session'])
        self.assertEqual(options['cwd'], self.root.resolve())
        self.assertEqual(options['env']['ASTERION_PRIME_P7_CONSOLE_RUN_ID'], RUN_ID)
        for key in polluted:
            if key != 'ASTERION_PRIME_P7_CONSOLE_RUN_ID':
                self.assertNotIn(key, options['env'])
        self.assertNotIn('sentinel', json.dumps(session.view()))

    def test_stop_during_startup_is_nonblocking_then_cleans_exact_unit(self):
        release = threading.Event()
        def launch(*args, **kwargs):
            self.calls.append((args[0], kwargs))
            self.launched.set()
            release.wait(2)
            return self.process
        session = self.session(process_factory=launch)
        started = session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        stopped = session.stop(started['session_id'], 'stop')
        self.assertEqual(stopped['state'], 'stopping')
        self.assertEqual(session.stop(started['session_id'], 'stop'), stopped)
        release.set()
        view = self.wait_state(session, 'cancelled')
        self.assertTrue(view['cleanup_confirmed'])
        unit_arg = next(v for v in self.calls[0][0] if v.startswith('ASTERION_PRIME_P7_ATTEMPT_UNIT='))
        self.assertEqual(self.cleanup_units, [unit_arg.split('=', 1)[1]])

    def test_natural_exit_zero_is_not_success_and_cleanup_failure_blocks_restart(self):
        session = self.session(guest_cleanup=lambda _: False)
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        self.process.returncode = 0
        view = self.wait_state(session, 'cleanup-unconfirmed')
        self.assertFalse(view['cleanup_confirmed'])
        with self.assertRaises(ConsoleSessionError):
            session.start('test-1', 'next')

    def test_unconfirmed_host_group_blocks_restart_even_when_guest_is_clean(self):
        def unconfirmed(process):
            raise ConsoleSessionError('launcher-cleanup-unconfirmed')
        session = self.session(process_stopper=unconfirmed)
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        self.process.returncode = 0
        view = self.wait_state(session, 'cleanup-unconfirmed')
        self.assertFalse(view['cleanup_confirmed'])
        self.assertTrue(self.cleanup_units)
        with self.assertRaises(ConsoleSessionError):
            session.start('test-1', 'next')

    def test_snapshot_identity_and_exit_receipt_are_checked(self):
        snapshot = {'schema': 'asterion.arc-agi3-p7-console/v1', 'generated_at': 'one',
                    'run': {'run_id': RUN_ID, 'game_id': 'test-1', 'status': 'incomplete'},
                    'levels': [], 'decisions': [], 'warnings': []}
        session = self.session(snapshot_reader=lambda _: snapshot)
        run = self.root / '.asterion-private' / 'prime-p7-live' / RUN_ID
        session.start('test-1', 'start')
        run.mkdir(parents=True)
        self.wait_state(session, 'running')
        until = time.monotonic() + 1
        while session.view()['snapshot'] is None and time.monotonic() < until:
            time.sleep(0.01)
        first = session.view()
        self.assertIsNotNone(first['snapshot'])
        snapshot['generated_at'] = 'two'
        time.sleep(0.05)
        self.assertEqual(session.view()['revision'], first['revision'])
        self.process.returncode = 0
        self.assertEqual(self.wait_state(session, 'incomplete')['state'], 'incomplete')
        self.assertTrue(self.cleanup_units)

    def test_reused_run_directory_and_unknown_game_are_rejected(self):
        session = self.session()
        (self.root / '.asterion-private' / 'prime-p7-live' / RUN_ID).mkdir(parents=True)
        for game in ('test-1', 'test', '../secret'):
            with self.subTest(game=game), self.assertRaises(ConsoleSessionError):
                session.start(game, 'start-' + str(len(game)))
        self.assertFalse(self.calls)

    def test_close_stops_owned_process_and_confirms_guest_cleanup(self):
        session = self.session()
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        session.close()
        self.assertEqual(session.view()['state'], 'cancelled')
        self.assertTrue(session.view()['cleanup_confirmed'])
        self.assertEqual(len(self.cleanup_units), 1)

    def test_operator_only_accepts_exact_new_console_run_id(self):
        from asterion.applications.prime.p7 import operator
        invocation = SimpleNamespace(operator_root=self.root, environment={})
        for requested, reused in ((RUN_ID, False), (RUN_ID, True), ('../private', False), ('', False)):
            with self.subTest(requested=requested, reused=reused):
                path = self.root / '.asterion-private' / 'prime-p7-live' / RUN_ID
                if reused:
                    path.mkdir(parents=True)
                with patch.dict('os.environ', {'ASTERION_PRIME_P7_CONSOLE_RUN_ID': requested}, clear=True), \
                     patch.object(operator, '_preflight', return_value=invocation), \
                     patch.object(operator, '_run_live_with_process_signals', side_effect=KeyboardInterrupt) as run, \
                     redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    operator.main([])
                if requested == RUN_ID and not reused:
                    run.assert_called_once_with(invocation, RUN_ID)
                else:
                    run.assert_not_called()
                if reused:
                    path.rmdir()

    def test_deadline_stops_process_before_guest_cleanup(self):
        clock = [0.0]
        order = []
        def stop(process):
            order.append('host')
            process.returncode = -15
        def cleanup(unit):
            order.append('guest')
            return True
        session = self.session(clock=lambda: clock[0], process_stopper=stop, guest_cleanup=cleanup)
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        clock[0] = 901.0
        self.assertEqual(self.wait_state(session, 'timed-out')['state'], 'timed-out')
        self.assertEqual(order, ['host', 'guest'])

    def test_final_snapshot_after_cleanup_proves_success_and_reaps_parent_group(self):
        snapshot = {'run': {'run_id': RUN_ID, 'game_id': 'test-1', 'status': 'incomplete'},
                    'generated_at': 'one', 'levels': []}
        order = []
        def cleanup(unit):
            order.append('guest')
            snapshot['run'].update(status='successful', replay_verified=True, sealed_trace=True)
            return True
        def stop(process):
            order.append('host')
        session = self.session(snapshot_reader=lambda _: snapshot, guest_cleanup=cleanup, process_stopper=stop)
        session.start('test-1', 'start')
        (self.root / '.asterion-private' / 'prime-p7-live' / RUN_ID).mkdir(parents=True)
        self.assertTrue(self.launched.wait(1))
        self.process.returncode = 0
        self.assertEqual(self.wait_state(session, 'completed')['state'], 'completed')
        self.assertEqual(order, ['host', 'guest'])

    def test_slow_guest_cleanup_does_not_block_view_or_stop_response(self):
        entered, release = threading.Event(), threading.Event()
        def cleanup(unit):
            entered.set()
            release.wait(2)
            return True
        session = self.session(guest_cleanup=cleanup)
        started = session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        session.stop(started['session_id'], 'stop')
        self.assertTrue(entered.wait(1))
        before = time.monotonic()
        self.assertEqual(session.view()['state'], 'stopping')
        self.assertEqual(session.stop(started['session_id'], 'another-stop')['state'], 'stopping')
        self.assertLess(time.monotonic() - before, 0.5)
        release.set()
        self.wait_state(session, 'cancelled')

    def test_mismatched_live_and_replay_identity_is_not_exposed(self):
        session = self.session(snapshot_reader=lambda _: {'run': {'run_id': RUN_ID, 'game_id': 'other-1'}})
        session.start('test-1', 'start')
        (self.root / '.asterion-private' / 'prime-p7-live' / RUN_ID).mkdir(parents=True)
        self.assertTrue(self.launched.wait(1))
        time.sleep(0.05)
        self.assertIsNone(session.view()['snapshot'])
        with self.assertRaises(ConsoleSessionError):
            session.replay(RUN_ID)
        self.assertEqual(session.recorded_runs(), [])


class TestP7ConsoleControlHandshake(ConsoleSessionFixture):
    def test_request_is_pending_until_matching_guest_ack_and_stop_stays_global(self):
        from asterion.applications.prime.p7.solver_control import SolverControl
        session = self.session()
        started = session.start('test-1', 'start')
        self.wait_state(session, 'running')
        run_root = session._run_path(RUN_ID)
        run_root.mkdir(parents=True)
        control = SolverControl(run_root, RUN_ID, time.monotonic() + 30)
        self.assertTrue(control.enter('action'))
        requested = session.pause(started['session_id'], 'pause')
        self.assertEqual(requested['state'], 'pause_requested')
        self.assertEqual(session.pause(started['session_id'], 'pause'), requested)
        with self.assertRaises(ConsoleSessionError):
            session.resume(started['session_id'], 'early-resume')
        control.poll(0, 'sha256:' + 'a' * 64)
        session._refresh_control(RUN_ID)
        self.assertEqual(session.view()['state'], 'pause_requested')
        ack_path = run_root / 'control-ack.json'
        ack = json.loads(ack_path.read_text())
        ack_path.write_text(json.dumps({**ack, 'state': 'paused', 'command_id': 'wrong-command'}))
        session._refresh_control(RUN_ID)
        self.assertEqual(session.view()['state'], 'pause_requested')
        control.leave('action')
        self.wait_state(session, 'paused')
        with self.assertRaises(ConsoleSessionError):
            session.start('test-1', 'another-start')
        with self.assertRaises(ConsoleSessionError):
            session.resume('wrong-session', 'wrong-resume')
        self.assertEqual(session.resume(started['session_id'], 'resume')['state'], 'resume_requested')
        self.assertEqual(session.view()['state'], 'resume_requested')
        control.poll(0, 'sha256:' + 'a' * 64)
        self.wait_state(session, 'running')
        session.pause(started['session_id'], 'pause-again')
        control.poll(0, 'sha256:' + 'a' * 64)
        self.wait_state(session, 'paused')
        session.stop(started['session_id'], 'stop')
        self.wait_state(session, 'cancelled')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(session.view()['cleanup_confirmed'])


class TestConsoleOverviewStarts(ConsoleSessionFixture):
    def test_target_and_resume_source_are_explicit_and_idempotent(self):
        session = self.session(environment={
            'ASTERION_PRIME_P7_HISTORY_VARIANT': 'legacy',
            'ASTERION_PRIME_P7_RESUME_RUN_ID': 'ambient-source',
            'ASTERION_PRIME_P7_TARGET_LEVEL': '99',
            'ASTERION_PRIME_P7_SEED': '9', 'LEVEL': '99'})
        overview = {'games': [{'game_id': 'test-1', 'runs': [
            {'run_id': 'chosen-source', 'verified': True, 'resume_eligible': True,
             'completed_levels': 1}]}]}
        with patch.object(session, 'overview', return_value=overview):
            started = session.start('test-1', 'start-selected', target_level=2,
                                    resume_run_id='chosen-source')
            self.assertEqual(started['start_level'], 2)
            self.assertEqual(started['source_run_id'], 'chosen-source')
            self.assertEqual(session.start('test-1', 'start-selected', target_level=2,
                                           resume_run_id='chosen-source'), started)
            with self.assertRaisesRegex(ConsoleSessionError, 'command-conflict'):
                session.start('test-1', 'start-selected', target_level=1)
        self.assertTrue(self.launched.wait(1))
        argv, kwargs = self.calls[0]
        self.assertIn('LEVEL=2', argv)
        self.assertIn('ASTERION_PRIME_P7_ATTEMPT_SECONDS=900', argv)
        self.assertEqual(kwargs['env']['ASTERION_PRIME_P7_HISTORY_VARIANT'], 'verified')
        self.assertEqual(kwargs['env']['ASTERION_PRIME_P7_RESUME_RUN_ID'], 'chosen-source')
        self.assertEqual(kwargs['env']['ASTERION_PRIME_P7_SEED'], '0')
        self.assertNotIn('ASTERION_PRIME_P7_TARGET_LEVEL', kwargs['env'])
        self.assertNotIn('LEVEL', kwargs['env'])

    def test_bad_target_or_resume_never_launches(self):
        session = self.session()
        with patch.object(session, 'overview', return_value={'games': []}):
            for target, source in ((True, None), (0, None), (3, None), (2, '../source'),
                                   (2, 'missing-source'), (1, 'chosen-source')):
                with self.subTest(target=target, source=source):
                    with self.assertRaises(ConsoleSessionError):
                        session.start('test-1', 'bad', target_level=target, resume_run_id=source)
        self.assertFalse(self.calls)

    def test_fresh_start_clears_ambient_source(self):
        session = self.session(environment={'ASTERION_PRIME_P7_RESUME_RUN_ID': 'ambient',
                                           'ASTERION_PRIME_P7_HISTORY_VARIANT': 'legacy'})
        session.start('test-1', 'fresh')
        self.assertTrue(self.launched.wait(1))
        argv, kwargs = self.calls[0]
        self.assertIn('LEVEL=1', argv)
        self.assertNotIn('ASTERION_PRIME_P7_RESUME_RUN_ID', kwargs['env'])
        self.assertEqual(kwargs['env']['ASTERION_PRIME_P7_HISTORY_VARIANT'], 'verified')

    def test_stale_external_recording_does_not_block_idle_guest(self):
        session = self.session()
        overview = {'games': [{'game_id': 'test-1', 'runs': [
            {'run_id': 'external-run', 'recording': True}]}]}
        with patch.object(session, 'overview', return_value=overview):
            session.start('test-1', 'new-start', target_level=2)
        self.assertTrue(self.launched.wait(1))

    def test_busy_or_unavailable_guest_rejects_before_launch(self):
        for reader, error in ((lambda: True, 'session-busy'), (lambda: None, 'guest-unavailable')):
            with self.subTest(error=error):
                session = self.session(guest_activity_reader=reader)
                with self.assertRaisesRegex(ConsoleSessionError, error):
                    session.start('test-1', 'busy')
        self.assertFalse(self.calls)

    def test_actual_model_selection_rejects_fresh_and_resume_before_launch(self):
        session = self.session(operator_environment_reader=lambda _: {
            'ASTERION_PRIME_MODEL': 'wrong-model', 'PRIVATE': 'sk-sentinel-secret'})
        for source in (None, 'chosen-source'):
            with self.subTest(source=source):
                with patch.object(session, 'overview', return_value={'games': []}):
                    with self.assertRaisesRegex(ConsoleSessionError, '^model-mismatch$'):
                        session.start('test-1', 'mismatch', target_level=2, resume_run_id=source)
        self.assertFalse(self.calls)

    def test_guest_activity_overview_cache_does_not_authorize_launch(self):
        states = iter((False, True))
        session = self.session(catalog=({'game_id': 'test-1', 'alias': 'test', 'win_levels': 2,
                                         'baseline_actions': (20, 20)},),
                               guest_activity_reader=lambda: next(states))
        value = session.overview()
        self.assertIs(value['guest_busy'], False)
        self.assertIs(value['start_ready'], True)
        self.assertIs(session.overview()['guest_busy'], False)
        with self.assertRaisesRegex(ConsoleSessionError, 'session-busy'):
            session.start('test-1', 'fresh-after-cache')
        self.assertFalse(self.calls)

    def test_guest_query_is_fixed_read_only_and_rejects_ambiguous_output(self):
        session = self.session()
        unit = 'asterion-p7-' + 'a' * 32 + '.service'
        for output, expected in (('', False), (unit + ' loaded active running witness\n', True)):
            with self.subTest(output=output):
                with patch('asterion.applications.prime.p7.console_session.subprocess.run',
                           return_value=SimpleNamespace(returncode=0, stdout=output)) as run:
                    self.assertIs(session._query_guest_activity(), expected)
                    argv = run.call_args.args[0]
                    self.assertEqual(argv[-7:], ['systemctl', 'list-units', '--all', '--no-legend',
                                                 '--plain', '--state=active,activating,deactivating',
                                                 'asterion-p7-*.service'])
                    self.assertEqual(run.call_args.kwargs['timeout'], 8)
                    self.assertNotIn('shell', run.call_args.kwargs)
        for code, output in ((1, ''), (0, 'foreign.service loaded active running sk-secret'),
                             (0, unit + ' loaded inactive dead witness')):
            with self.subTest(code=code, output=output):
                with patch('asterion.applications.prime.p7.console_session.subprocess.run',
                           return_value=SimpleNamespace(returncode=code, stdout=output)):
                    with self.assertRaisesRegex(ConsoleSessionError, '^guest-unavailable$'):
                        session._query_guest_activity()

    def test_final_replay_exports_once_after_cleanup_and_failure_does_not_change_outcome(self):
        for fail in (False, True):
            with self.subTest(export_fails=fail):
                run_id = 'p7-live-20261005123456-' + ('b' if fail else 'c') * 24
                order = []
                def launch(*args, **kwargs):
                    path = self.root / '.asterion-private' / 'prime-p7-live' / run_id
                    path.mkdir(parents=True)
                    (path / 'summary.json').write_text('{}')
                    self.process.returncode = 0
                    return self.process
                def snapshot(path):
                    order.append('refresh')
                    return {'run': {'run_id': run_id, 'game_id': 'test-1', 'status': 'successful',
                                    'replay_verified': True, 'sealed_trace': True}}
                def cleanup(unit):
                    order.append('cleanup')
                    return True
                def export(path, *, replay_config):
                    self.assertEqual(replay_config, {"games": session.games()})
                    order.append('export')
                    if fail:
                        raise ValueError('sk-private-export-failure')
                    return path / 'p7-console.html'
                session = self.session(process_factory=launch, snapshot_reader=snapshot,
                                       guest_cleanup=cleanup, run_id_factory=lambda: run_id)
                with patch('asterion.applications.prime.p7.console_session.export_console', side_effect=export) as exporter:
                    session.start('test-1', 'export')
                    view = self.wait_state(session, 'completed')
                    self.assertEqual(exporter.call_count, 1)
                self.assertEqual(view['replay_saved'], not fail)
                self.assertIs(view['cleanup_confirmed'], True)
                self.assertLess(order.index('cleanup'), len(order) - 2)
                self.assertEqual(order[-2:], ['refresh', 'export'])
