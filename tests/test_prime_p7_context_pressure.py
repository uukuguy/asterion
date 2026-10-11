"""Application input pressure configuration; no model or game execution."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p7 import operator
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.model_selection import P7ModelSelection
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_native_provider import _Worker


class TestPrimeP7ContextPressure(unittest.TestCase):
    def test_application_capacity_default_and_override_are_explicit_bytes(self):
        resolve = getattr(operator, '_resolve_context_capacity_bytes', None)
        self.assertTrue(callable(resolve))
        self.assertEqual(resolve({}), 128 * 1024)
        self.assertEqual(resolve({'ASTERION_PRIME_P7_CONTEXT_CAPACITY_BYTES': '64'}), 64)
        self.assertEqual(resolve({'ASTERION_PRIME_P7_CONTEXT_CAPACITY_BYTES': '8388608'}), 8388608)

    def test_invalid_capacity_is_rejected_before_services_or_engine(self):
        class Engine:
            def set_dispatch_control(self, **kwargs):
                raise AssertionError('invalid configuration reached engine')

        for value in ('0', '-1', '8388609', '1.5', 'secret-value', ''):
            with self.subTest(value=value), patch.object(operator, 'prepare_prime_application') as prepare:
                with self.assertRaisesRegex(operator.P7OperatorError, 'context capacity is invalid'):
                    operator.build_p7_operator_resources(
                        environment={'ASTERION_PRIME_P7_CONTEXT_CAPACITY_BYTES': value},
                        executable=Path('/unused'), entry=None, extension_path=Path('/unused'),
                        working_directory=Path('/unused'), engine=Engine(),
                        private_trace_root=Path('/unused/trace'))
                prepare.assert_not_called()

    def test_capacity_guidance_is_only_in_the_research_experiment_appendix(self):
        self.assertEqual(operator._append_research_experiment('MAIN', {}), 'MAIN')
        prompt = operator._append_research_experiment('MAIN', {'ASTERION_PRIME_P7_RUN_MODE': 'research'})
        self.assertIn('asterion_p7_context_capacity', prompt)
        self.assertIn('NOTES', prompt)
        self.assertIn('未总结', prompt)

    def test_research_override_reaches_extension_and_legacy_ignores_it(self):
        key = operator.P7_CONTEXT_CAPACITY_BYTES_ENV
        for variant, value, expected in (('verified', '00064', '64'),
                                          ('verified', None, '131072'),
                                          ('legacy', 'invalid', None)):
            with self.subTest(variant=variant, value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                extension = root / 'extension.mjs'
                extension.write_text('export default function extension() {}\n')
                trace = root / 'trace'
                trace.mkdir()
                environment = {operator.P7_HISTORY_VARIANT_ENV: variant}
                if value is not None:
                    environment[key] = value
                with patch.object(operator, 'resolve_model_selection', return_value=P7ModelSelection('openai-codex', 'gpt-6.1-sol')), \
                     patch.object(operator, 'prepare_prime_application', wraps=operator.prepare_prime_application) as prepare:
                    resources = operator.build_p7_operator_resources(
                        environment=environment, executable=Path('/usr/bin/pi'), extension_path=extension,
                        working_directory=root, worker=_Worker(), engine=_Engine(), private_trace_root=trace,
                        game=P7GameSelection('ls20-9607627b', 0, 1))
                    try:
                        self.assertEqual(prepare.call_args.args[1].environment.get(key), expected)
                    finally:
                        asyncio.run(resources.close())


if __name__ == '__main__':
    unittest.main()
