from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import patch

from tools.run_prime_p7_guest import cleanup, launch


class TestPrimeP7Guest(unittest.TestCase):
    def test_only_explicit_zero_sentinel_removes_guest_deadline(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid attempt bounds"):
            launch('asterion-p7-' + 'a' * 32 + '.service', None, ['python3', '-V'])
        with (
            patch('tools.run_prime_p7_guest.Path.is_file', return_value=True),
            patch.dict('os.environ', {'ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND': '1'}, clear=True),
            patch('tools.run_prime_p7_guest.os.execvp', side_effect=SystemExit(0)) as call,
        ):
            with self.assertRaises(SystemExit):
                launch('asterion-p7-' + 'a' * 32 + '.service', 0, ['python3', '-V'])
        args = call.call_args.args[1]
        self.assertIn('--property=KillMode=control-group', args)
        self.assertIn('--property=TimeoutStopSec=20s', args)
        self.assertIn('--setenv=ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND=1', args)
        self.assertFalse(any(arg.startswith('--property=RuntimeMaxSec=') for arg in args))

    def test_guest_drops_empty_runtime_marker_and_offline_mode(self) -> None:
        with (
            patch('tools.run_prime_p7_guest.Path.is_file', return_value=True),
            patch.dict('os.environ', {
                'ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND': '', 'OPERATION_MODE': 'offline',
            }, clear=True),
            patch('tools.run_prime_p7_guest.os.execvp', side_effect=SystemExit(0)) as call,
        ):
            with self.assertRaises(SystemExit):
                launch('asterion-p7-' + 'a' * 32 + '.service', 30, ['python3', '-V'])
        args = call.call_args.args[1]
        self.assertNotIn('--setenv=ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND=', args)
        self.assertNotIn('--setenv=OPERATION_MODE=offline', args)

    def test_launch_contains_descendants_without_forwarding_credentials(self) -> None:
        with (
            patch('tools.run_prime_p7_guest.Path.is_file', return_value=True),
            patch.dict('os.environ', {
                'ASTERION_PRIME_P7_GAME_ID': 'a-1',
                'ASTERION_PRIME_PROVIDER': 'openai-codex',
                'ASTERION_PRIME_MODEL': 'gpt-6.1-sol',
                'SECRET_KEY': 'sentinel',
            }, clear=True),
            patch('tools.run_prime_p7_guest.os.execvp', side_effect=SystemExit(0)) as call,
        ):
            with self.assertRaises(SystemExit):
                launch('asterion-p7-' + 'a' * 32 + '.service', 30, ['python3', '-V'])
        args = call.call_args.args[1]
        self.assertIn('--property=KillMode=control-group', args)
        self.assertIn('--property=RuntimeMaxSec=30s', args)
        self.assertIn('--setenv=ASTERION_PRIME_P7_GAME_ID=a-1', args)
        self.assertIn('--setenv=ASTERION_PRIME_PROVIDER=openai-codex', args)
        self.assertIn('--setenv=ASTERION_PRIME_MODEL=gpt-6.1-sol', args)
        self.assertNotIn('sentinel', ' '.join(args))

    def test_sweep_launch_forwards_history_variant_to_contained_operator(self) -> None:
        unit = 'asterion-p7-' + 'a' * 32 + '.service'
        for variant in ('legacy', 'verified'):
            with self.subTest(variant=variant), patch(
                'tools.run_prime_p7_guest.Path.is_file', return_value=True,
            ), patch.dict(
                'os.environ', {'ASTERION_PRIME_P7_HISTORY_VARIANT': variant}, clear=True,
            ), patch(
                'tools.run_prime_p7_guest.os.execvp', side_effect=SystemExit(0),
            ) as call:
                with self.assertRaises(SystemExit):
                    launch(unit, 30, ['python3', '-V'])
                self.assertIn(
                    f'--setenv=ASTERION_PRIME_P7_HISTORY_VARIANT={variant}',
                    call.call_args.args[1],
                )

    def test_retry_marker_is_forwarded_to_contained_operator(self) -> None:
        unit = 'asterion-p7-' + 'a' * 32 + '.service'
        with (
            patch('tools.run_prime_p7_guest.Path.is_file', return_value=True),
            patch.dict('os.environ', {'ASTERION_PRIME_P7_RETRY_MODE': 'same-game-failed-attempt'}, clear=True),
            patch('tools.run_prime_p7_guest.os.execvp', side_effect=SystemExit(0)) as call,
        ):
            with self.assertRaises(SystemExit):
                launch(unit, 30, ['python3', '-V'])
        self.assertIn('--setenv=ASTERION_PRIME_P7_RETRY_MODE=same-game-failed-attempt', call.call_args.args[1])

    def test_cleanup_rejects_unconfirmed_guest_state(self) -> None:
        unit = 'asterion-p7-' + 'a' * 32 + '.service'
        for state in ('', 'LoadState=loaded\nActiveState=active\n'):
            with self.subTest(state=state), patch('tools.run_prime_p7_guest.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0, stdout=state),
            ]):
                self.assertFalse(cleanup(unit))

    def test_cleanup_cannot_target_an_unrelated_unit(self) -> None:
        with patch('tools.run_prime_p7_guest.subprocess.run') as run:
            with self.assertRaises(ValueError):
                cleanup('sshd.service')
            run.assert_not_called()

    @unittest.skipUnless(os.environ.get('ASTERION_TEST_ORB') == '1', 'explicit zero-model Orb probe')
    def test_orb_budget_stop_kills_detached_descendant_only_for_attempt(self) -> None:
        import json
        import secrets
        import sys
        import tempfile
        import time
        from pathlib import Path
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        repo = Path(__file__).resolve().parents[1]
        helper = str(repo / 'tools/run_prime_p7_guest.py')
        control_unit = 'asterion-p7-' + secrets.token_hex(16) + '.service'
        marker = 'p7-probe-' + secrets.token_hex(16)
        orb = ['orb', '-m', 'ubuntu', '-u', 'root', '-w', '/tmp', 'python3']
        with tempfile.TemporaryDirectory(prefix='.p7-cancel-test-', dir=repo) as directory:
            root = Path(directory)
            control = subprocess.Popen([
                *orb, helper, 'launch', '--unit', control_unit, '--seconds', '30', '--',
                'python3', '-c',
                'import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(25)',
                str(root / 'control.pid'), marker,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (root / 'control.pid').exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue((root / 'control.pid').exists())
                guest = '''import os,sys,subprocess,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from asterion.agents.prime.trace import PrimeTraceRecorder
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(25)',sys.argv[3]],start_new_session=True)
Path(sys.argv[2]).write_text(json.dumps({'parent':os.getpid(),'child':child.pid}))
trace=Path(sys.argv[4])/'run-1'/'trace';trace.mkdir(parents=True)
recorder=PrimeTraceRecorder(trace)
recorder.append('arc.usage.reported',{'runtime':'test'},{'input_tokens':6,'output_tokens':5})
time.sleep(25)
'''
                wrapper = '''import os,sys
os.execvp('orb',['orb','-m','ubuntu','-u','root','-w','/tmp','python3',sys.argv[1],'launch','--unit',os.environ['ASTERION_PRIME_P7_ATTEMPT_UNIT'],'--seconds',os.environ['ASTERION_PRIME_P7_ATTEMPT_SECONDS'],'--','python3','-c',sys.argv[2],*sys.argv[3:7]])
'''
                scheduler = SweepScheduler(SweepConfig(
                    arc_root=root / 'arc', runs_root=root / 'runs', repo_root=repo,
                    global_token_cap=10,
                    command=(sys.executable, '-c', wrapper, helper, guest, str(repo / 'src'),
                             str(root / 'pids.json'), marker, str(root / 'runs')),
                ))
                scheduler._attempt('a-1', 1, 10)
                self.assertEqual(scheduler._stop_reason, 'token-cap')
                self.assertEqual(scheduler._input_tokens + scheduler._output_tokens, 11)
                pids = json.loads((root / 'pids.json').read_text())
                pids['unrelated'] = int((root / 'control.pid').read_text())
                inspect = '''import json,sys
from pathlib import Path
result={}
for name,pid in json.loads(sys.argv[2]).items():
    try: result[name]=sys.argv[1].encode() in (Path('/proc')/str(pid)/'cmdline').read_bytes()
    except FileNotFoundError: result[name]=False
print(json.dumps(result))
'''
                checked = subprocess.run([*orb, '-c', inspect, marker, json.dumps(pids)],
                                         capture_output=True, text=True, timeout=5, check=True)
                self.assertEqual(json.loads(checked.stdout), {'parent': False, 'child': False, 'unrelated': True})
            finally:
                subprocess.run([*orb, helper, 'cleanup', '--unit', control_unit],
                               timeout=20, check=True)
                control.wait(timeout=5)
