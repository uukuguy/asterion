"""Historical experience requires an explicit P7 experiment or continuation."""

import asyncio
import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import experience, operator
from asterion.applications.prime.p7.game import P7GameSelection
from tests.test_prime_p7_autonomy import environment as autonomy_environment


EXPERIENCE_MODE = 'ASTERION_PRIME_P7_EXPERIENCE_MODE'


class _StopBeforeRuntime(Exception):
    pass


class TestP7ExperienceOptIn(unittest.TestCase):
    def test_new_runs_do_not_load_or_scan_history_without_explicit_opt_in(self):
        for supervised, mode in ((False, None), (True, None), (False, 'off'), (True, 'off'),
                                 (False, 'on'), (True, 'on')):
            with self.subTest(supervised=supervised, mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                history = root / '.asterion-private' / 'prime-p7-live'
                history.mkdir(parents=True)
                (history / 'p7-unrelated-history').mkdir()
                game = replace(P7GameSelection('test-1', 0, 1, (10,) * 9, 9),
                               supervised_research=supervised)
                env = {'ASTERION_PRIME_P7_RUN_MODE': 'research' if supervised else 'solve'}
                if mode is not None:
                    env[EXPERIENCE_MODE] = mode
                invocation = operator.P7Invocation(root, env, root, root / 'pi', None,
                                                   root / 'extension.mjs', game)
                scans = []
                original_iterdir = Path.iterdir
                def tracked_iterdir(path):
                    if path == history:
                        scans.append(path)
                    return original_iterdir(path)
                output = io.StringIO()
                with patch.object(experience, 'load_experience', wraps=experience.load_experience) as loader, \
                     patch.object(Path, 'iterdir', tracked_iterdir), \
                     patch('asterion.applications.prime.p7.solutions.load_best_prefix') as prefix, \
                     patch.object(operator.live, 'ArcadeEngine'), \
                     patch.object(operator, 'build_p7_operator_resources', side_effect=_StopBeforeRuntime) as build, \
                     patch.dict('os.environ', {'ASTERION_PRIME_P7_COLOR': 'never'}), \
                     contextlib.redirect_stderr(output):
                    with self.assertRaises(_StopBeforeRuntime):
                        asyncio.run(operator.run_live(invocation, 'p7-new-run'))
                enabled = mode == 'on'
                self.assertEqual(loader.call_count, int(enabled))
                self.assertEqual(len(scans), int(enabled))
                prefix.assert_not_called()
                self.assertIsNone(build.call_args.kwargs['cognition_store'])
                self.assertIsNone(build.call_args.kwargs['semantic_cognition_store'])
                self.assertEqual(build.call_args.kwargs['experience'] is not None, enabled)
                startup = next(line.split(' startup ', 1)[1] for line in output.getvalue().splitlines()
                               if '[p7-cognition] startup ' in line)
                self.assertEqual(json.loads(startup).get('experience_mode'), 'on' if enabled else 'off')

    def test_invalid_mode_and_cold_opt_in_reject_before_history_or_execution(self):
        cases = [{'ASTERION_PRIME_P7_RUN_MODE': 'solve', EXPERIENCE_MODE: value}
                 for value in ('', 'ON', 'true', 'SENTINEL_SECRET', None)]
        cases += [{**autonomy_environment(), EXPERIENCE_MODE: 'on'},
                  {'ASTERION_PRIME_P7_RUN_MODE': 'cognition', EXPERIENCE_MODE: 'on'}]
        for env in cases:
            with self.subTest(environment=env), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                game = P7GameSelection('test-1', 0, 1, (10,) * 9, 9)
                invocation = operator.P7Invocation(root, env, root, root / 'pi', None,
                                                   root / 'extension.mjs', game)
                with patch.object(operator.live, 'private_root') as private, \
                     patch.object(operator.live, 'ArcadeEngine') as engine, \
                     patch.object(experience, 'load_experience') as loader, \
                     self.assertRaisesRegex(operator.P7OperatorError, '^P7 experience mode is invalid$'):
                    asyncio.run(operator.run_live(invocation, 'p7-invalid-mode'))
                private.assert_not_called()
                engine.assert_not_called()
                loader.assert_not_called()

    def test_preflight_selects_experience_from_process_instead_of_operator_file(self):
        import asterion
        for selected in (None, 'off', 'on'):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                root = base / 'operator'
                root.mkdir()
                package = base / 'site-packages' / 'asterion.py'
                package.parent.mkdir()
                package.touch()
                env = {operator.live.OPERATOR_ROOT_ENV: str(root)}
                if selected is not None:
                    env[EXPERIENCE_MODE] = selected
                    env['ASTERION_PRIME_P7_OUTPUT_BYTES'] = '4194304'
                with patch.object(asterion, '__file__', str(package)), \
                     patch.object(operator.live, 'load_operator_environment', return_value={
                         EXPERIENCE_MODE: 'on', 'ASTERION_PRIME_P7_OUTPUT_BYTES': '9999'}), \
                     patch.object(operator.live, 'resolve_pi_agent_dir', return_value=base), \
                     patch.object(operator.live, 'resolve_arc_root', return_value=base), \
                     patch.object(operator.live, 'resolve_node', return_value=base / 'node'), \
                     patch.object(operator.live, 'resolve_pi_entry', return_value=None), \
                     patch.object(operator.live, 'extension_path', return_value=base / 'extension.mjs'), \
                     patch.object(operator, 'resolve_game_selection', return_value=P7GameSelection('test-1', 0, 1, (10,) * 9, 9)):
                    invocation = operator._preflight(env)
                self.assertEqual(invocation.environment[EXPERIENCE_MODE], selected or 'off')
                self.assertEqual(invocation.environment.get('ASTERION_PRIME_P7_OUTPUT_BYTES'),
                                 None if selected is None else '4194304')

    def test_preflight_rejects_invalid_mode_before_configuration_reads(self):
        with patch.object(operator.live, 'load_operator_environment') as load, \
             self.assertRaisesRegex(operator.P7OperatorError, '^P7 experience mode is invalid$'):
            operator._preflight({EXPERIENCE_MODE: 'invalid'})
        load.assert_not_called()
