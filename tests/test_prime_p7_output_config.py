"""P7 output capacity is application configuration, validated before execution."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import operator
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.model_selection import P7ModelSelection
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_native_provider import _Worker


OUTPUT_BYTES = 'ASTERION_PRIME_P7_OUTPUT_BYTES'


class TestP7OutputConfiguration(unittest.TestCase):
    def test_default_and_explicit_output_capacity_reach_research_kernel(self):
        for selected, expected in ((None, 2 * 1024 * 1024), ('256', 256), ('4194304', 4194304)):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                extension = root / 'extension.mjs'
                extension.write_text('export default function extension() {}\n')
                trace = root / 'trace'
                trace.mkdir()
                env = {} if selected is None else {OUTPUT_BYTES: selected}
                with patch.object(operator, 'resolve_model_selection', return_value=P7ModelSelection('openai-codex', 'gpt-6.1-sol')), \
                     patch.object(operator, 'prepare_prime_application', wraps=operator.prepare_prime_application) as prepare:
                    resources = operator.build_p7_operator_resources(
                        environment=env, executable=Path('/usr/bin/pi'), extension_path=extension,
                        working_directory=root, worker=_Worker(), engine=_Engine(),
                        private_trace_root=trace, game=P7GameSelection('ls20-9607627b', 0, 1))
                    try:
                        self.assertEqual(resources.host_services['prime.ipython']._limits.max_output_bytes, expected)
                        self.assertNotIn(OUTPUT_BYTES, prepare.call_args.args[1].environment)
                    finally:
                        asyncio.run(resources.close())

    def test_invalid_output_capacity_rejects_before_run_effects(self):
        for value in ('', '255', '0', '-1', '256.0', 'NaN', 'SENTINEL_SECRET', None,
                      str(((2**53 - 1) - 8192) // 6 + 1)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                invocation = operator.P7Invocation(root, {OUTPUT_BYTES: value}, root,
                    root / 'pi', None, root / 'extension.mjs', P7GameSelection('test-1', 0, 1, (10,) * 9, 9))
                with patch.object(operator.live, 'private_root') as private, \
                     patch.object(operator.live, 'ArcadeEngine') as engine, \
                     patch.object(operator, 'build_p7_operator_resources',
                                  side_effect=operator.P7OperatorError('execution occurred')) as build, \
                     self.assertRaisesRegex(operator.P7OperatorError, '^P7 output capacity is invalid$'):
                    asyncio.run(operator.run_live(invocation, 'p7-invalid-output'))
                private.assert_not_called()
                engine.assert_not_called()
                build.assert_not_called()

    def test_preflight_rejects_invalid_output_before_configuration_reads(self):
        with patch.object(operator.live, 'load_operator_environment') as load, \
             self.assertRaisesRegex(operator.P7OperatorError, '^P7 output capacity is invalid$'):
            operator._preflight({OUTPUT_BYTES: 'invalid'})
        load.assert_not_called()
