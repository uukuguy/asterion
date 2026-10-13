"""Finite P7 callback capacity, using local native-event fakes only."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime import _launch
from asterion.agents.prime.execution import AsterionPrimeLimits
from asterion.applications.prime.p7 import operator
from asterion.applications.prime.p7.game import DEFAULT_GAME, ArcGameContract
from asterion.applications.prime.p7.runtime_binding import build_p7_direct_runtime
from asterion.runtime.factory import RuntimeFactoryError
from asterion.runtime.protocol import ProtocolError
from asterion.services.diagnostics import limit_diagnostic
from tests.test_asterion_prime_session import FakePiRpcSession, SessionFixture, collect, native_events
from tests.test_prime_p7_native_provider import _CompletingEngine, _Worker


MODEL_ENV = 'ASTERION_PRIME_P7_MODEL_CALLBACKS'
TOOL_ENV = 'ASTERION_PRIME_P7_TOOL_CALLBACKS'


def environment(**extra):
    return {'ASTERION_PRIME_PI_AGENT_DIR': str(Path.home() / '.pi/agent'),
            'ASTERION_PRIME_PROVIDER': 'openai-codex',
            'ASTERION_PRIME_MODEL': 'gpt-6.1-sol', **extra}


class TestCallbackCapacity(unittest.TestCase):
    def test_generic_capacities_are_positive_exact_safe_integers_not_presets(self):
        for model, tool in ((2048, 8192), (2**53 - 2, 2**53 - 2)):
            with self.subTest(model=model, tool=tool):
                try:
                    limits = AsterionPrimeLimits(model, tool, 3600000)
                except ValueError:
                    self.fail('Valid finite capacities must exceed legacy preset ceilings')
                self.assertEqual((limits.model_callbacks, limits.tool_callbacks), (model, tool))
        for model, tool in ((True, 1), (1, False), (1.0, 1), (1, '2'),
                            (None, 1), (1, None), (0, 1), (1, -1),
                            (2**53 - 1, 1), (1, 2**53 - 1), (2**53, 1), (1, 2**53)):
            with self.subTest(model=model, tool=tool), self.assertRaises(ValueError):
                AsterionPrimeLimits(model, tool, 3600000)

    def test_solve_defaults_and_independent_operator_overrides(self):
        for extra, expected in (({}, (1024, 4096)),
            ({MODEL_ENV: '2048'}, (2048, 4096)),
            ({TOOL_ENV: '8192'}, (1024, 8192)),
            ({MODEL_ENV: str(2**53 - 2), TOOL_ENV: str(2**53 - 2)}, (2**53 - 2, 2**53 - 2)),
            ({MODEL_ENV: '256', TOOL_ENV: '600'}, (256, 600))):
            with self.subTest(extra=extra):
                selection = operator.resolve_p7_runtime(environment(**extra))
                self.assertEqual((selection.max_callbacks, getattr(selection, 'max_tool_callbacks', None)), expected)
                options = operator.p7_runtime_options(selection)
                self.assertEqual((options['max_callbacks'], options['max_tool_callbacks']),
                                 tuple(map(str, expected)))
                with self.assertRaises(TypeError):
                    options['max_callbacks'] = 'none'

    def test_config_cannot_grant_unbounded_or_change_closed_presets(self):
        for name in (MODEL_ENV, TOOL_ENV):
            for value in ('none', '', '0', '-1', '1.0', 'NaN', ' 256 ', True,
                          '9007199254740991', '9007199254740992'):
                with self.subTest(name=name, value=value), self.assertRaises(operator.P7OperatorError):
                    operator.resolve_p7_runtime(environment(**{name: value}))
            for mode in ('witness', 'research', 'autonomy'):
                game = replace(DEFAULT_GAME, supervised_research=True) if mode == 'research' else DEFAULT_GAME
                with self.subTest(name=name, mode=mode), self.assertRaises(operator.P7OperatorError):
                    operator.resolve_p7_runtime(environment(**{
                        name: '256', 'ASTERION_PRIME_P7_RUN_MODE': mode}), game)
            sweep = operator._sweep_game(DEFAULT_GAME, None)
            with self.assertRaises(operator.P7OperatorError):
                operator.resolve_p7_runtime(environment(**{
                    name: '256', 'ASTERION_PRIME_P7_RUN_MODE': 'sweep',
                    operator.UNBOUNDED_FIRST_ROUND_ENV: '1', 'OPERATION_MODE': 'offline'}), sweep)

    def test_guest_forwards_callback_capacity_to_operator(self):
        names = (Path(__file__).resolve().parents[1] / 'tools/p7_guest_environment.txt').read_text().splitlines()
        self.assertIn(MODEL_ENV, names)
        self.assertIn(TOOL_ENV, names)

    def test_factory_revalidates_forged_limits_before_mode_or_options_admission(self):
        for fields in ((None, None, 3600000), (None, 600, 3600000),
                       (256, True, 3600000), ('PRIVATE-CALLBACK-CAPACITY', 600, 3600000),
                       (2**53 - 1, 600, 3600000), None):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                extension = root / 'extension.mjs'
                extension.write_text('export default function extension() {}\n')
                (root / 'trace').mkdir()
                resources = operator.build_p7_operator_resources(
                    environment=environment(**{MODEL_ENV: '256', TOOL_ENV: '600'}),
                    executable=Path('/usr/bin/pi'), extension_path=extension,
                    working_directory=root, worker=_Worker(), engine=_CompletingEngine(),
                    private_trace_root=root / 'trace')
                owner = resources.application
                authorization = owner.authorized_limits
                runtime_material = owner._runtime_material
                forged = object.__new__(AsterionPrimeLimits)
                options = dict(resources.runtime_options)
                if fields is not None:
                    for name, value in zip(('model_callbacks', 'tool_callbacks', 'deadline_ms'), fields):
                        object.__setattr__(forged, name, value)
                    options.update(max_callbacks=str(fields[0]), max_tool_callbacks=str(fields[1]),
                                   deadline_ms=str(fields[2]))
                owner._authorization = forged
                try:
                    try:
                        build_p7_direct_runtime(resources.host_services, options)
                    except RuntimeFactoryError as error:
                        self.assertEqual(str(error), 'Asterion-prime runtime configuration is invalid')
                        self.assertIsNone(error.__cause__)
                        self.assertNotIn('PRIVATE-CALLBACK-CAPACITY', str(error))
                    except Exception as error:
                        self.fail(f'Invalid limits must produce a redacted RuntimeFactoryError, got {type(error).__name__}')
                    else:
                        self.fail('Factory accepted invalid forged limits')
                    self.assertIs(owner._runtime_material, runtime_material)
                    self.assertIsNone(owner._persistent)
                finally:
                    owner._authorization = authorization
                    asyncio.run(resources.close())

    def test_largest_capacity_keeps_overflow_diagnostic_exact_without_large_loop(self):
        capacity = 2**53 - 2
        for kind in ('model', 'tool'):
            with self.subTest(kind=kind):
                fixture = SessionFixture()
                try:
                    session, _, _ = fixture.make(native_events(
                        ('turn_start', {}),
                        ('tool_execution_start', {'toolCallId': 'call', 'toolName': 'ipython', 'args': {}})))
                    session._kernel._limits = AsterionPrimeLimits(capacity, capacity, 3600000)
                    setattr(session._kernel, f'{kind}_callbacks', capacity)
                    with self.assertRaises(ProtocolError) as caught:
                        asyncio.run(collect(session))
                    diagnostic = limit_diagnostic(caught.exception)
                    self.assertEqual((diagnostic.limit_code, diagnostic.observed, diagnostic.limit),
                        (f'prime-{kind}-callback-limit', capacity + 1, capacity))
                finally:
                    fixture.close()

    def test_official_options_reject_non_preset_callback_limits_before_factory(self):
        game = ArcGameContract('ab12-12345678', win_levels=12)
        selected = operator.resolve_p7_runtime(environment(), game)
        self.assertEqual(operator.p7_runtime_options(selected, game)['max_tool_callbacks'], '500')
        for model, tool in ((256, 500), (128, 600)):
            with self.subTest(model=model, tool=tool), self.assertRaises(operator.P7OperatorError):
                operator.p7_runtime_options(replace(selected, max_callbacks=model, max_tool_callbacks=tool), game)

    def test_resolved_limits_bind_options_owner_native_session_and_diagnostics(self):
        for kind, count, expected in (('model', 129, None), ('model', 257, (257, 256)),
                                    ('tool', 501, None), ('tool', 601, (601, 600))):
            with self.subTest(kind=kind, count=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                extension = root / 'extension.mjs'
                extension.write_text('export default function extension() {}\n')
                (root / 'trace').mkdir()
                resources = operator.build_p7_operator_resources(
                    environment=environment(**{MODEL_ENV: '256', TOOL_ENV: '600'}),
                    executable=Path('/usr/bin/pi'), extension_path=extension,
                    working_directory=root, worker=_Worker(), engine=_CompletingEngine(),
                    private_trace_root=root / 'trace')
                try:
                    owner = resources.application
                    self.assertEqual(owner.authorized_limits, AsterionPrimeLimits(256, 600, 3600000))
                    self.assertNotIn(MODEL_ENV, owner._operator.environment)
                    self.assertNotIn(TOOL_ENV, owner._operator.environment)
                    build_p7_direct_runtime(resources.host_services, resources.runtime_options)
                    for name in ('max_callbacks', 'max_tool_callbacks'):
                        with self.assertRaises(RuntimeFactoryError):
                            build_p7_direct_runtime(resources.host_services,
                                {**resources.runtime_options, name: '999'})
                    limits, hooks = owner._runtime_material
                    owner._persistent = _launch.persistent_launch(
                        owner._operator, owner._spec, owner.services, limits, hooks)
                    session = owner._persistent.session
                    self.assertEqual(session._limits, owner.authorized_limits)
                    values = [('turn_start', {})] * count if kind == 'model' else [('turn_start', {})]
                    if kind == 'tool':
                        for index in range(count):
                            values.extend([
                                ('tool_execution_start', {'toolCallId': f'call-{index}',
                                    'toolName': 'ipython', 'args': {}}),
                                ('tool_execution_end', {'toolCallId': f'call-{index}',
                                    'toolName': 'ipython', 'result': {'content': []}, 'isError': False})])
                    values.append(('agent_end', {}))
                    fake = FakePiRpcSession(owner._persistent.rpc.config, native_events(*values))
                    # Only transport is synthetic; application-selected limits and
                    # the native callback validator are the actual launch objects.
                    session._kernel._completion_predicate = lambda: True
                    session._kernel._round_diagnostic = None
                    async def native_driver(prompt, *, signal, on_event, diagnostic_subject_id):
                        self.assertEqual(diagnostic_subject_id, 'prime-run-1')
                        return await fake.run(prompt, signal=signal, on_event=on_event)
                    with patch.object(owner._persistent.rpc, 'run', native_driver):
                        if expected is None:
                            result = asyncio.run(collect(session))
                            self.assertEqual(result[-1].payload, {'status': 'completed'})
                        else:
                            with self.assertRaises(ProtocolError) as caught:
                                asyncio.run(collect(session))
                            diagnostic = limit_diagnostic(caught.exception)
                            self.assertEqual((diagnostic.limit_code, diagnostic.observed, diagnostic.limit),
                                (f'prime-{kind}-callback-limit', *expected))
                    self.assertEqual(fake.calls, 1)
                finally:
                    asyncio.run(resources.close())
