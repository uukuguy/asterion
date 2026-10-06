from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime.p7.console_events import ConsoleEventWriter, read_console_events
from tests import test_prime_p7_console as fixtures


class TestConsoleEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'run-test'
        self.root.mkdir()
        self.writer = ConsoleEventWriter(self.root, 'run-test', 'sp80-test')

    def decision(self):
        return {'decision_id': 'decision-1', 'source_action_sequence': 0,
                'observation_sha256': 'sha256:' + 'a' * 64,
                'goal': '移到目标旁', 'basis': '已看到位置', 'expected': '观察位置变化'}

    def test_typed_warning_survives_console_projection_without_raw_error_text(self):
        from asterion.applications.prime.p7.processing_diagnostics import DiagnosticLog
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        log = DiagnosticLog()
        warning = log.record({
            'diagnostic_id': 'diagnostic-1', 'code': 'evidence-write-failed',
            'severity': 'error', 'stage': 'validated-not-durable',
            'action_sequence': 0, 'outcome_known': True, 'durable': False,
            'observed': None, 'limit': None, 'unit': None, 'recovery': 'pause-and-rebuild',
        })
        self.writer.append('diagnostic', warning)
        rows = read_console_events(self.root, self.root.name, 'sp80-test')
        self.assertEqual(rows[0]['schema'], 'asterion.prime.p7-console-event/v3')
        snapshot = build_console_snapshot(self.root)
        self.assertEqual(snapshot['diagnostics'], [warning])
        self.assertEqual(snapshot['schema'], 'asterion.arc-agi3-p7-console/v2')
        with self.assertRaises(ValueError):
            self.writer.append('diagnostic', {**warning, 'message': 'SENTINELSECRET'})

    def test_identity_sequence_and_partial_tail(self):
        self.writer.append('decision', self.decision())
        self.writer.append('decision', {**self.decision(), 'decision_id': 'decision-2'})
        path = self.root / 'console-events.jsonl'
        self.assertTrue(path.read_bytes().endswith(b'\n'))
        with path.open('ab') as stream:
            stream.write(b'{"incomplete":')
        rows = read_console_events(self.root, 'run-test', 'sp80-test')
        self.assertEqual([r['sequence'] for r in rows], [1, 2])
        with self.assertRaises(ValueError):
            read_console_events(self.root, 'another-run', 'sp80-test')
        with self.assertRaises(ValueError):
            read_console_events(self.root, 'run-test', 'wrong-game')

    def test_closed_bounded_public_payload(self):
        for changed in ({'prompt': 'SECRET'}, {'goal': '/private/sentinel'},
                        {'basis': 'Bearer SECRET'}, {'expected': 'x' * 601}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.writer.append('decision', {**self.decision(), **changed})
        self.assertFalse((self.root / 'console-events.jsonl').exists())

    def test_prefixed_credential_assignments_never_reach_public_events(self):
        from asterion.applications.prime.p7.console_events import public_narrative, public_text
        for label in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'TOKEN', 'ACCESS_TOKEN', 'SECRET', 'CLIENT_SECRET'):
            with self.subTest(label=label):
                secret = label + '=SENTINELSECRET'
                self.assertEqual(public_text(secret), '')
                self.assertEqual(public_narrative('观察。\n' + secret), '')
                with self.assertRaises(ValueError):
                    self.writer.append('decision', {**self.decision(), 'goal': secret})
        self.assertFalse((self.root / 'console-events.jsonl').exists())

    def test_list_payload_stops_reader_and_snapshot_at_safe_prefix(self):
        self.writer.append('decision', self.decision())
        path = self.root / 'console-events.jsonl'
        row = json.loads(path.read_text())
        row['sequence'] = 2
        row['payload'] = list(row['payload'].items())
        with path.open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        rows = read_console_events(self.root, 'run-test', 'sp80-test')
        self.assertEqual(len(rows), 1)
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        snapshot = build_console_snapshot(self.root)
        self.assertEqual(snapshot['run']['run_id'], 'run-test')
        self.assertIn('部分实时过程事件无效，仅保留可验证前缀。', snapshot['warnings'])

    def test_observation_is_closed_bounded_and_hash_verified(self):
        from asterion.applications.prime.p7.observation_state import ObservationState
        from asterion.applications.prime.p7.score import digest
        raw = {'frame': [[[0, 1]]], 'available_actions': ['ACTION1'],
               'state': 'NOT_FINISHED', 'levels_completed': 0, 'win_levels': 3}
        payload = {'source_action_sequence': 0, 'observation': raw,
                   'observation_sha256': digest(ObservationState.from_observation(raw).to_projection())}
        self.writer.append('observation', payload)
        for changed in ({'prompt': 'SENTINELSECRET'}, {'frame': [[[True]]]},
                        {'frame': [[[256]]]}, {'frame': [[[0]] * 65]},
                        {'frame': [[[0]]] * 65}, {'available_actions': ['ACTION1', 'ACTION1']},
                        {'available_actions': ['RESET']}, {'state': '/private/SENTINELSECRET'},
                        {'levels_completed': 4}, {'win_levels': True},
                        {'hud': {'key': 'SENTINELSECRET'}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.writer.append('observation', {**payload, 'observation': {**raw, **changed}})
        with self.assertRaises(ValueError):
            self.writer.append('observation', {**payload, 'observation_sha256': 'sha256:' + '0' * 64})
        rows = read_console_events(self.root, self.root.name, 'sp80-test')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload'], payload)
        self.assertNotIn('SENTINELSECRET', (self.root / 'console-events.jsonl').read_text())

    def test_unknown_and_malformed_observation_end_safe_prefix(self):
        self.writer.append('decision', self.decision())
        path = self.root / 'console-events.jsonl'
        prefix = path.read_text()
        for kind, payload in [('unknown', {}), ('observation', []), ('observation', {
                'source_action_sequence': 0, 'observation_sha256': 'sha256:' + '0' * 64,
                'observation': {'private': 'SENTINELSECRET'}})]:
            with self.subTest(kind=kind, payload=payload):
                row = json.loads(prefix)
                row.update(sequence=2, kind=kind, payload=payload)
                path.write_text(prefix + json.dumps(row) + '\n')
                warnings = []
                self.assertEqual(len(read_console_events(self.root, self.root.name, 'sp80-test', warnings=warnings)), 1)
                self.assertEqual(warnings, ['console-events-invalid'])

    def test_real_cognition_renderers_preserve_safe_multiline_sections(self):
        from asterion.applications.prime.p7.cognition_narrative import (
            render_stable_game_description_zh, render_cognition_narrative_zh,
        )
        description = render_stable_game_description_zh(None)
        narrative = render_cognition_narrative_zh(None, None)
        self.assertIn('\n', description)
        self.writer.append('cognition', {'cognition_revision': 1, 'source_action_sequence': 0,
                          'observation_sha256': 'sha256:' + 'a' * 64,
                          'stable_description': description, 'cognition_narrative_zh': narrative, 'session': {}})
        payload = read_console_events(self.root, 'run-test', 'sp80-test')[0]['payload']
        self.assertEqual(payload['stable_description'].split('\n'), description.split('\n'))
        self.assertEqual(payload['cognition_narrative_zh'], narrative)

    def test_invalid_sequence_stops_prefix(self):
        self.writer.append('decision', self.decision())
        path = self.root / 'console-events.jsonl'
        row = json.loads(path.read_text())
        row['sequence'] = 3
        with path.open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        self.assertEqual(len(read_console_events(self.root, 'run-test', 'sp80-test')), 1)


class TestConsoleSourceProjection(unittest.TestCase):
    setUp = fixtures.TestPrimeP7Console.setUp
    write_summary = fixtures.TestPrimeP7Console.write_summary
    observation = fixtures.TestPrimeP7Console.observation
    write_recording = fixtures.TestPrimeP7Console.write_recording
    observation_hash = fixtures.TestPrimeP7Console.observation_hash
    action_payload = fixtures.TestPrimeP7Console.action_payload

    def test_complete_repeated_transition_preserves_old_links_and_fresh_cognition(self):
        import io
        from contextlib import redirect_stderr
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        from tests.test_prime_p7_native_broker import _Engine
        class Engine(_Engine):
            def observe(engine):
                return {**super().observe(), 'frame': [[[int(bool(engine.calls))] * 64 for _ in range(64)]]}
        game = P7GameSelection('sp80-test', 0, _metadata_baseline_actions=(10, 10, 10), _metadata_win_levels=3)
        broker = ArcBroker(engine=Engine(game_id='sp80-test', win_levels=3), game=game)
        (self.root / 'trace').mkdir()
        trace = PrimeTraceRecorder(self.root / 'trace')
        self.addCleanup(trace.close)
        client = _P7BrokerClient(broker, trace, console_writer=ConsoleEventWriter(self.root, self.root.name, game.game_id))
        first, after = self.observation(), self.observation('ACTION1', 1)
        # Match the real source's advertised controls, independent of SDK row ordinals.
        first['data']['available_actions'] = after['data']['available_actions'] = [1, 2, 3]
        client._capture_console_cognition()
        client.decision({'goal': '移动', 'basis': '当前画面', 'expected': '观察变化'})
        with redirect_stderr(io.StringIO()):
            client.act([{'name': 'ACTION1', 'data': {}}])
        self.write_recording([first, after])
        before = build_console_snapshot(self.root)['levels'][0]
        self.assertEqual(len(before['cognition_timeline']), 2)
        with redirect_stderr(io.StringIO()):
            client.act([{'name': 'ACTION1', 'data': {}}])
        self.write_recording([first, after, after])
        after_level = build_console_snapshot(self.root)['levels'][0]
        self.assertEqual(after_level['cognition_timeline'][:2], before['cognition_timeline'])
        self.assertEqual([c['source_action_sequence'] for c in after_level['cognition_timeline']], [0, 1, 2])
        self.assertEqual([a['source_action_sequence'] for a in after_level['actions']], [1, 2])
        self.assertEqual(after_level['actions'][0]['decision_id'], 'decision-1')
        self.assertEqual(after_level['cognition_timeline'][-1]['frame_id'], 'f000003')
        # The source owns these frames: withheld or damaged SDK rows cannot
        # relocate source cognition to some later identical SDK picture.
        for sdk_rows in ([first, after], [first, {'invalid': True}, after]):
            self.write_recording(sdk_rows)
            stable = build_console_snapshot(self.root)['levels'][0]
            self.assertEqual(stable['cognition_timeline'], after_level['cognition_timeline'])
            self.assertEqual(stable['actions'], after_level['actions'])
        self.recording.unlink()
        self.assertEqual(build_console_snapshot(self.root)['levels'][0]['frames'], after_level['frames'])

    def test_source_gap_never_links_later_identical_observation_or_cognition(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        from asterion.applications.prime.p7.observation_state import ObservationState
        from asterion.applications.prime.p7.score import digest
        initial, after = self.observation(), self.observation('ACTION1', 1)
        self.write_recording([initial, after, after])
        def public(row):
            data = row['data']
            raw = {k: data[k] for k in ('frame', 'state', 'levels_completed', 'win_levels')}
            raw['available_actions'] = [f'ACTION{i}' for i in data['available_actions']]
            return raw, digest(ObservationState.from_observation(raw).to_projection())
        a, ah = public(initial)
        b, bh = public(after)
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        writer.append('observation', {'source_action_sequence': 0, 'observation_sha256': ah, 'observation': a})
        writer.append('action', {'sequence': 1, 'action': 'ACTION1', 'before_sha256': ah,
                                'after_sha256': bh, 'levels_completed': 0, 'decision_id': None})
        # Observation 1 is withheld. Matching content at source position 2 is
        # not evidence for position 1, even with a complete SDK recording.
        writer.append('observation', {'source_action_sequence': 2, 'observation_sha256': bh, 'observation': b})
        writer.append('cognition', {'cognition_revision': 1, 'source_action_sequence': 1,
                      'observation_sha256': bh, 'stable_description': '位置一', 'cognition_narrative_zh': '位置一', 'session': {}})
        writer.append('cognition', {'cognition_revision': 2, 'source_action_sequence': 0,
                      'observation_sha256': ah, 'stable_description': '缺口后旧位置',
                      'cognition_narrative_zh': '不得越过缺口', 'session': {}})
        level = build_console_snapshot(self.root)['levels'][0]
        self.assertEqual(len(level['frames']), 1)
        self.assertEqual(level['actions'], [])
        self.assertEqual(level['cognition_timeline'], [])

    def test_source_decision_and_cognition_bind_actual_observations_without_summary(self):
        (self.root / 'summary.json').unlink()
        first, after = self.observation(), self.observation('ACTION1', 1)
        self.write_recording([first, after])
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        writer.append('decision', {'decision_id': 'decision-1', 'source_action_sequence': 0,
                      'observation_sha256': self.observation_hash(first),
                      'goal': '移动', 'basis': '已观察位置', 'expected': '位置变化'})
        writer.append('action', {**self.action_payload(first, after), 'decision_id': 'decision-1'})
        writer.append('cognition', {'cognition_revision': 1, 'source_action_sequence': 1,
                      'observation_sha256': self.observation_hash(after),
                      'stable_description': '观察后更新介绍', 'cognition_narrative_zh': '看到位置变化。',
                      'session': {'state': 'OBSERVE', 'episode': 1, 'episode_actions': 1}})
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        snapshot = build_console_snapshot(self.root)
        level = snapshot['levels'][0]
        self.assertEqual(level['actions'][0]['decision_id'], 'decision-1')
        self.assertEqual(level['decisions'][0]['action_ids'], ['a000001'])
        self.assertEqual(level['cognition']['scope'], 'observation')
        self.assertNotIn('没有身份匹配的稳定认知。', snapshot['warnings'])
        self.assertEqual(level['cognition_timeline'][0]['frame_id'], 'f000002')
        self.assertEqual(level['cognition_timeline'][0]['action_id'], 'a000001')

    def test_explicit_source_reset_is_an_action_even_when_the_frame_is_unchanged(self):
        first, reset = self.observation(), self.observation()
        self.write_recording([first, reset])
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        writer.append('action', {**self.action_payload(first, reset), 'decision_id': None})
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        actions = build_console_snapshot(self.root)['levels'][0]['actions']
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['name'], 'RESET')

    def test_recording_gap_cannot_bind_a_later_repeated_frame_to_an_earlier_position(self):
        first, after = self.observation(), self.observation('ACTION1', 1)
        self.write_recording([first, after, {'invalid': True}, after])
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        writer.append('action', {**self.action_payload(first, after), 'decision_id': None})
        writer.append('cognition', {'cognition_revision': 1, 'source_action_sequence': 1,
                      'observation_sha256': self.observation_hash(after),
                      'stable_description': '动作一后的认识', 'cognition_narrative_zh': '位置变化', 'session': {}})
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        timeline = build_console_snapshot(self.root)['levels'][0]['cognition_timeline']
        self.assertEqual(timeline[0]['frame_id'], 'f000002')

    def test_omitted_recording_with_repeated_pixels_cannot_invent_source_position(self):
        for later_action in ('ACTION2', 'ACTION1'):
            with self.subTest(later_action=later_action):
                path = self.root / 'console-events.jsonl'
                path.unlink(missing_ok=True)
                first = self.observation()
                missing = self.observation('ACTION1', 1)
                retained = self.observation(later_action, 1)
                self.write_recording([first, retained])
                writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
                writer.append('action', {**self.action_payload(first, missing), 'decision_id': None})
                writer.append('cognition', {'cognition_revision': 1, 'source_action_sequence': 1,
                              'observation_sha256': self.observation_hash(missing),
                              'stable_description': '只有动作一的认识', 'cognition_narrative_zh': '认识一', 'session': {}})
                writer.append('decision', {'decision_id': 'decision-1', 'source_action_sequence': 1,
                              'observation_sha256': self.observation_hash(missing),
                              'goal': '继续', 'basis': '动作一观察', 'expected': '变化'})
                writer.append('action', {**self.action_payload(missing, retained, sequence=2), 'decision_id': 'decision-1'})
                from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
                level = build_console_snapshot(self.root)['levels'][0]
                self.assertEqual(level['cognition_timeline'], [])
                self.assertEqual(level['decisions'], [])
                self.assertIsNone(level['actions'][0]['source_action_sequence'])

    def test_unmatched_digest_never_associates_decision_or_cognition(self):
        first, after = self.observation(), self.observation('ACTION1', 1)
        self.write_recording([first, after])
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        bad = 'sha256:' + '0' * 64
        writer.append('decision', {'decision_id': 'decision-1', 'source_action_sequence': 0,
                      'observation_sha256': bad, 'goal': '移动', 'basis': '位置', 'expected': '变化'})
        writer.append('action', {**self.action_payload(first, after), 'decision_id': 'decision-1'})
        writer.append('cognition', {'cognition_revision': 1, 'source_action_sequence': 1,
                      'observation_sha256': bad, 'stable_description': '不匹配',
                      'cognition_narrative_zh': '不匹配', 'session': {}})
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        level = build_console_snapshot(self.root)['levels'][0]
        self.assertIsNone(level['actions'][0]['decision_id'])
        self.assertEqual(level['cognition_timeline'], [])

class TestDecisionSource(unittest.TestCase):
    def test_pending_decision_consumed_only_at_matching_plan_start(self):
        from types import SimpleNamespace
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.score import digest
        class Broker:
            journal = ()
            def observation_state(self):
                return SimpleNamespace(to_projection=lambda: {'observation': len(self.journal)})
            def observation_reference(self):
                return {'sequence': len(self.journal),
                        'observation_sha256': digest({'observation': len(self.journal)}),
                        'animation_ref': None}
            def cognition_projection(self):
                return {}
        class Recorder:
            def append(self, *args):
                pass
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'run-test'
            root.mkdir()
            writer = ConsoleEventWriter(root, root.name, 'game-test')
            broker = Broker()
            client = _P7BrokerClient(broker, Recorder(), console_writer=writer)
            summary = {'goal': '试移动', 'basis': '当前位置', 'expected': '位置变化'}
            result = client.decision(summary)
            self.assertEqual(result['execution_authority'], 'none')
            client._begin_console_plan()
            first = ArcTransition(1, 'ACTION1', digest({'observation': 0}), digest({'observation': 1}), 0)
            broker.journal = (first,)
            client._record_transitions((first,))
            client.decision(summary)
            second = ArcTransition(2, 'ACTION1', first.after_sha256, digest({'observation': 2}), 0)
            broker.journal += (second,)  # Another source changed the observed position.
            client._begin_console_plan()
            third = ArcTransition(3, 'ACTION1', second.after_sha256, digest({'observation': 3}), 0)
            broker.journal += (third,)
            client._record_transitions((third,))
            rows = read_console_events(root, root.name, 'game-test')
            actions = [r['payload'] for r in rows if r['kind'] == 'action']
            self.assertEqual(actions[0]['decision_id'], result['decision_id'])
            self.assertIsNone(actions[1]['decision_id'])
            with self.assertRaises(Exception):
                client.decision({**summary, 'goal': '/private/SECRET'})

    def test_optional_writer_does_not_change_actions_and_cognition_has_actual_digest(self):
        import io
        from contextlib import redirect_stderr
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _Engine
        with tempfile.TemporaryDirectory() as temp, redirect_stderr(io.StringIO()):
            root = Path(temp) / 'run-test'
            root.mkdir()
            (root / 'trace').mkdir()
            trace = PrimeTraceRecorder(root / 'trace')
            self.addCleanup(trace.close)
            game = P7GameSelection("ls20-9607627b", 0)
            broker = ArcBroker(engine=_Engine(), game=game)
            writer = ConsoleEventWriter(root, root.name, game.game_id)
            client = _P7BrokerClient(broker, trace, console_writer=writer)
            client._capture_console_cognition()
            summary = {'goal': '试移动', 'basis': '当前观察', 'expected': '位置变化'}
            decision = client.decision(summary)
            client.act([{'name': 'ACTION1', 'data': {}}])
            rows = read_console_events(root, root.name, game.game_id)
            cognition = [r['payload'] for r in rows if r['kind'] == 'cognition']
            action = next(r['payload'] for r in rows if r['kind'] == 'action')
            self.assertEqual(action['decision_id'], decision['decision_id'])
            self.assertEqual(cognition[0]['source_action_sequence'], 0)
            self.assertIn('\n', cognition[0]['stable_description'])
            self.assertIn('\n', cognition[0]['cognition_narrative_zh'])
            self.assertEqual(cognition[-1]['source_action_sequence'], 1)
            self.assertEqual(cognition[-1]['observation_sha256'], action['after_sha256'])
            # A failing display sink remains advisory.
            client._console_writer = type('BrokenWriter', (), {'append': lambda *args: (_ for _ in ()).throw(OSError())})()
            client.act([{'name': 'ACTION1', 'data': {}}])
            self.assertEqual(len(broker.journal), 2)

    def test_settled_source_captures_initial_multistep_reset_and_level_boundary(self):
        import io
        from contextlib import redirect_stderr
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        from asterion.applications.prime.p7.observation_state import ObservationState
        from asterion.applications.prime.p7.score import digest
        from tests.test_prime_p7_native_broker import _Engine
        with tempfile.TemporaryDirectory() as temp, redirect_stderr(io.StringIO()):
            root = Path(temp) / 'run-test'
            root.mkdir()
            (root / 'trace').mkdir()
            trace = PrimeTraceRecorder(root / 'trace')
            self.addCleanup(trace.close)
            intermediate = []
            class Engine(_Engine):
                def step(engine, action):
                    if len(engine.calls) == 1:
                        intermediate.append(build_console_snapshot(root))
                    return super().step(action)
            game = P7GameSelection('ls20-9607627b', 0)
            broker = ArcBroker(engine=Engine(level_after=4), game=game)
            broker.bind_history(root.name)
            writer = ConsoleEventWriter(root, root.name, game.game_id)
            client = _P7BrokerClient(broker, trace, console_writer=writer)
            client._capture_console_cognition()
            client.decision({'goal': '试移动', 'basis': '当前观察', 'expected': '位置变化'})
            client.act_checked([{'action': {'name': name, 'data': {}},
                                 'expect': {'cell': {'x': 0, 'y': 0, 'value': value}}}
                                for name, value in [('ACTION1', 1), ('ACTION2', 2)]])
            client.act([{'name': 'RESET', 'data': {}}])
            client.act([{'name': 'ACTION1', 'data': {}}])
            rows = read_console_events(root, root.name, game.game_id)
            observed = [r['payload'] for r in rows if r['kind'] == 'observation']
            actions = [r['payload'] for r in rows if r['kind'] == 'action']
            self.assertEqual([r['source_action_sequence'] for r in observed], [0, 1, 2, 3, 4])
            self.assertEqual([r['action'] for r in actions], ['ACTION1', 'ACTION2', 'RESET', 'ACTION1'])
            self.assertEqual([r['observation']['frame'][0][0][0] for r in observed], [0, 1, 2, 3, 4])
            self.assertEqual([r['observation']['levels_completed'] for r in observed], [0, 0, 0, 0, 1])
            for row in observed:
                self.assertEqual(row['observation_sha256'], digest(ObservationState.from_observation(row['observation']).to_projection()))
            for transition, row in zip(broker.journal, observed[1:], strict=True):
                self.assertEqual(row['observation_sha256'], transition.after_sha256)
            self.assertEqual(intermediate[0]['run']['primitive_action_count'], 1)
            self.assertEqual(intermediate[0]['run']['status'], 'incomplete')
            self.assertEqual(intermediate[0]['levels'][0]['actions'][0]['source_action_sequence'], 1)
            self.assertEqual(intermediate[0]['levels'][0]['frames'][-1]['grid'][0][0], 1)
            final = build_console_snapshot(root)
            self.assertEqual(final['levels'][0]['decisions'][0]['action_ids'], ['a000001', 'a000002'])
            self.assertEqual(final['levels'][1]['cognition']['source_action_sequence'], 4)
            self.assertEqual(final['levels'][1]['cognition']['frame_id'], 'f000005')

    def test_private_optional_observation_metadata_cannot_be_persisted_or_hash_substituted(self):
        import io
        from contextlib import redirect_stderr
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _Engine
        class Engine(_Engine):
            def observe(engine):
                return {**super().observe(), 'hud': {'note': '/private/SENTINELSECRET'}}
        with tempfile.TemporaryDirectory() as temp, redirect_stderr(io.StringIO()):
            root = Path(temp) / 'run-test'
            root.mkdir()
            (root / 'trace').mkdir()
            trace = PrimeTraceRecorder(root / 'trace')
            self.addCleanup(trace.close)
            game = P7GameSelection('ls20-9607627b', 0)
            broker = ArcBroker(engine=Engine(), game=game)
            client = _P7BrokerClient(broker, trace, console_writer=ConsoleEventWriter(root, root.name, game.game_id))
            client.act([{'name': 'ACTION1', 'data': {}}])
            rows = read_console_events(root, root.name, game.game_id)
            self.assertFalse(any(row['kind'] == 'observation' for row in rows))
            self.assertNotIn('SENTINELSECRET', (root / 'console-events.jsonl').read_text())
            self.assertEqual(len(broker.journal), 1)

    def test_advisory_observer_failure_does_not_change_settlement(self):
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from tests.test_prime_p7_native_broker import _Engine
        broker = ArcBroker(engine=_Engine(), game=P7GameSelection('ls20-9607627b', 0))
        calls = []
        def failing(sequence, observation_hash, observation):
            calls.append(sequence)
            raise OSError('display sink unavailable')
        broker.set_observation_listener(failing)
        result = broker.act((ArcAction('ACTION1'), ArcAction('ACTION2')))
        self.assertEqual(result.applied_count, 2)
        self.assertEqual(calls, [0, 1, 2])
        self.assertEqual(len(broker.journal), 2)

    def test_both_dispatch_paths_forward_the_real_summary(self):
        from asterion.applications.prime.p7.ipython_host import p7_client_facade
        from asterion.applications.prime.p7.operator import _IpythonBridgeServer
        from asterion.applications.prime.p7.live import P7ClientServer, WORKER_PROTOCOL
        from tests.test_prime_p7_bridge_dispatch import _Facade
        class Client(_Facade):
            def act(self, actions):
                return {"applied_count": len(actions)}
            def decision(self, payload):
                return {'received': payload, 'execution_authority': 'none'}
        payload = {'goal': '继续移动', 'basis': '当前观察', 'expected': '位置变化'}
        facade = p7_client_facade(Client())
        bridge = object.__new__(_IpythonBridgeServer)
        bridge._client, bridge._method_calls, bridge._method_failures = facade, {}, {}
        result = bridge._dispatch_method_call('request', 'decision', payload)
        self.assertEqual(json.loads(result['output'])['received'], payload)
        server = object.__new__(P7ClientServer)
        server._client = facade
        result = json.loads(server._dispatch(json.dumps({'id': 1, 'protocol': WORKER_PROTOCOL,
                            'method': 'decision', 'args': [payload]}).encode()))
        self.assertTrue(result['ok'])
        self.assertEqual(result['value']['received'], payload)

    def test_decision_remains_available_before_the_first_cognition_probe(self):
        from unittest.mock import patch
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.ipython_host import p7_client_facade
        from asterion.applications.prime.p7.operator import _IpythonBridgeServer
        from tests.test_prime_p7_bridge_dispatch import _Facade
        class Client(_Facade):
            _cognition_mode = True
            _broker = object.__new__(ArcBroker)
            def act(self, actions):
                return {}
        bridge = object.__new__(_IpythonBridgeServer)
        bridge._client = p7_client_facade(Client())
        with patch.object(ArcBroker, 'cognition_projection', return_value={'cognition_session': {'session': {'state': 'OBSERVE', 'episode_actions': 0}}}):
            self.assertTrue(bridge._first_probe_required('act_checked'))
            self.assertFalse(bridge._first_probe_required('decision'))

    def test_unidentified_cognition_snapshots_are_not_deduplicated_across_runs(self):
        import io
        from contextlib import redirect_stderr
        from asterion.applications.prime.p7.operator import _log_cognition_refresh
        stream = io.StringIO()
        with redirect_stderr(stream):
            _log_cognition_refresh({'semantic': {'natural_language_context': 'first-run-marker'}}, phase='read')
            _log_cognition_refresh({'semantic': {'natural_language_context': 'next-run-marker'}}, phase='startup')
        self.assertIn('first-run-marker', stream.getvalue())
        self.assertIn('next-run-marker', stream.getvalue())
        self.assertNotIn('reason=duplicate-snapshot', stream.getvalue())

    def test_native_worker_close_owns_and_closes_all_pipe_streams(self):
        import asyncio
        from types import SimpleNamespace
        from asterion.applications.prime.p7.ipython_host import p7_client_facade
        from asterion.applications.prime.p7.live import SubprocessPythonWorker
        from tests.test_prime_p7_bridge_dispatch import _Facade
        class Client(_Facade):
            def act(self, actions):
                return {}
        async def exercise(root):
            worker = SubprocessPythonWorker(root=root)
            await worker.start(p7_client_facade(Client()), signal=SimpleNamespace(cancelled=False))
            process = worker._process
            try:
                await worker.close()
                self.assertTrue(process.stdin.closed)
                self.assertTrue(process.stdout.closed)
                self.assertTrue(process.stderr.closed)
            finally:
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
        with tempfile.TemporaryDirectory() as temp:
            asyncio.run(exercise(Path(temp)))


def research_payloads(observation_hash='sha256:' + 'a' * 64):
    common = dict(source_action_sequence=0, observation_sha256=observation_hash, level=1,
                  workspace_revision='model-1', task_id='task-1', origin='actor')
    return {
        'compute_task': {**common, 'status': 'started', 'operation': 'search', 'goal': '先打开门',
                         'obstacles': ['门未打开'], 'question': '开关是否持续有效', 'summary': '',
                         'elapsed_ms': None, 'completed_units': None},
        'model_revision': {**common, 'revision': 'model-1', 'parent_revision': None,
                           'description_zh': '游戏规则：开关使门暂时开放。\n未知：终点条件。',
                           'state_summary': '角色在门外', 'rule_summaries': ['开关使门开放'],
                           'unknowns': ['终点条件'], 'coverage_summary': '仅覆盖门附近',
                           'validation_summary': '已检查观察0', 'correction_summary': '', 'evidence_sequences': [0]},
        'plan': {**common, 'plan_id': 'plan-1', 'status': 'proposed', 'goal': '先打开门',
                 'assumptions': ['门在执行期间保持开放'], 'actions': [{'name': 'ACTION4', 'data': {}}],
                 'applied_count': 0, 'stop_reason': None},
        'feedback': {**common, 'origin': 'environment', 'plan_id': 'plan-1',
                     'expected_summary': '角色进入门内', 'actual_summary': '角色仍在门外',
                     'mismatch_kind': 'dynamics', 'unexecuted_count': 1, 'counterexample_sequence': 0},
        'run_control': {**common, 'origin': 'operator', 'state': 'paused', 'command_id': 'pause-1',
                        'request_sequence': 1, 'reason': None},
    }


class TestConsoleResearchEvents(unittest.TestCase):
    setUp = TestConsoleEvents.setUp
    decision = TestConsoleEvents.decision
    def test_native_action_labels_are_optional_public_and_evidence_bounded(self):
        label = {'action': 'ACTION5', 'label': '旋转 ↻', 'purpose': '将选中形状顺时针旋转一次。',
                 'confidence': 'certain', 'evidence_sequences': [0]}
        payload = {**research_payloads()['model_revision'], 'action_labels': [label]}
        self.writer.append('model_revision', payload)
        label['label'] = 'mutated'
        rows = read_console_events(self.root, 'run-test', 'sp80-test')
        self.assertEqual(rows[0]['payload']['action_labels'][0]['label'], '旋转 ↻')
        for change in ({'evidence_sequences': [1]}, {'purpose': 'token=SENTINEL'},
                       {'debug': 'SENTINEL'}, {'confidence': 'unknown'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.writer.append('model_revision', {**payload, 'action_labels': [{**label, **change}]})

    def test_v1_and_v2_share_real_contiguous_sequence(self):
        self.writer.append('decision', self.decision())
        for kind, payload in research_payloads().items():
            self.writer.append(kind, payload)
        rows = read_console_events(self.root, 'run-test', 'sp80-test')
        self.assertEqual([row['sequence'] for row in rows], list(range(1, 7)))
        self.assertTrue(rows[0]['schema'].endswith('/v1'))
        self.assertTrue(all(row['schema'].endswith('/v2') for row in rows[1:]))
        path = self.root / 'console-events.jsonl'
        copied = [dict(row) for row in rows]
        copied[1]['schema'] = copied[0]['schema']
        path.write_text(''.join(json.dumps(row) + '\n' for row in copied))
        self.assertEqual(len(read_console_events(self.root, 'run-test', 'sp80-test')), 1)

    def test_research_is_closed_public_and_rejects_fake_shape(self):
        for kind, payload in research_payloads().items():
            for changes in ({'stdout': 'SENTINEL'}, {'origin': []}, {'level': True},
                            {'workspace_revision': '/private/SENTINEL'}):
                with self.subTest(kind=kind, changes=changes), self.assertRaises(ValueError):
                    self.writer.append(kind, {**payload, **changes})
        for field in ('description_zh', 'state_summary', 'validation_summary'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.writer.append('model_revision', {**research_payloads()['model_revision'],
                                   field: 'TOKEN=SENTINEL'})
        self.assertFalse((self.root / 'console-events.jsonl').exists())


class TestConsoleResearchProjection(unittest.TestCase):
    setUp = TestConsoleSourceProjection.setUp
    write_summary = TestConsoleSourceProjection.write_summary
    observation = TestConsoleSourceProjection.observation
    write_recording = TestConsoleSourceProjection.write_recording
    observation_hash = TestConsoleSourceProjection.observation_hash
    def test_native_labels_follow_exact_model_revision_without_filling_absence(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        initial = self.observation()
        self.write_recording([initial])
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        payload = research_payloads(self.observation_hash(initial))['model_revision']
        labels = [{'action': 'ACTION5', 'label': '提交', 'purpose': '提交当前布局。',
                   'confidence': 'certain', 'evidence_sequences': [0]}]
        writer.append('model_revision', {**payload, 'action_labels': labels})
        snapshot = build_console_snapshot(self.root)
        bucket = snapshot['levels'][0]
        self.assertEqual(bucket['cognition']['action_labels'], labels)
        self.assertEqual(bucket['cognition_timeline'][0]['action_labels'], labels)
        self.assertEqual(bucket['research_timeline'][0]['payload']['action_labels'], labels)
        writer.append('model_revision', {**payload, 'revision': 'model-2', 'parent_revision': 'model-1',
                      'workspace_revision': 'model-2'})
        bucket = build_console_snapshot(self.root)['levels'][0]
        self.assertNotIn('action_labels', bucket['cognition'])
        self.assertNotIn('action_labels', bucket['cognition_timeline'][1])
        self.assertEqual(bucket['cognition_timeline'][0]['action_labels'], labels)

    def test_same_observation_keeps_distinct_model_revisions_and_real_event_cursor(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        initial = self.observation()
        self.write_recording([initial])
        writer = ConsoleEventWriter(self.root, self.root.name, 'sp80-test')
        payloads = research_payloads(self.observation_hash(initial))
        writer.append('compute_task', payloads['compute_task'])
        writer.append('model_revision', payloads['model_revision'])
        writer.append('plan', payloads['plan'])
        writer.append('feedback', payloads['feedback'])
        writer.append('model_revision', {**payloads['model_revision'], 'revision': 'model-2',
                      'parent_revision': 'model-1', 'workspace_revision': 'model-2',
                      'description_zh': '游戏规则：门仅开放一步。', 'correction_summary': '动作后的门立即关闭'})
        snapshot = build_console_snapshot(self.root)
        events = snapshot['process_events']
        self.assertEqual([event['event_sequence'] for event in events], [1, 2, 3, 4, 5])
        self.assertEqual(len({event['frame_id'] for event in events}), 1)
        self.assertEqual(snapshot['levels'][0]['research_timeline'], events)
        self.assertEqual(events[1]['payload']['revision'], 'model-1')
        self.assertEqual(events[-1]['payload']['revision'], 'model-2')
        self.assertNotIn('description_zh', snapshot['levels'][0]['cognition'])
        writer.append('model_revision', {**payloads['model_revision'], 'revision': 'unlinked',
                      'observation_sha256': 'sha256:' + '0' * 64})
        self.assertEqual(len(build_console_snapshot(self.root)['process_events']), 5)


class TestRestoredResearchProjection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs = Path(self.tmp.name).resolve()

    def publish(self, name, count, revisions, source=None, restored=0, game='sp80-test', startup=False):
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.observation_state import ObservationState
        from asterion.applications.prime.p7.score import digest
        root = self.runs / name
        root.mkdir()
        (root / 'trace').mkdir()
        writer = ConsoleEventWriter(root, name, game)
        trace = PrimeTraceRecorder(root / 'trace')
        previous = None
        for position in range(count + 1):
            raw = {'frame': [[[position]]], 'available_actions': ['ACTION1'],
                   'levels_completed': position, 'win_levels': 3, 'state': 'NOT_FINISHED'}
            hashed = digest(ObservationState.from_observation(raw).to_projection())
            if previous is not None:
                action = {'sequence': position, 'action': 'ACTION1', 'data': {},
                          'before_sha256': previous, 'after_sha256': hashed, 'levels_completed': position}
                writer.append('action', {**action, 'decision_id': None})
                trace.append('arc.action', {'application_id': 'prime.arc-agi-3-solving', 'model_id': 'test-model'}, action)
            writer.append('observation', {'source_action_sequence': position,
                          'observation_sha256': hashed, 'observation': raw})
            if startup and position == (0 if startup == 'early' else restored):
                context = {'run_id': name, 'game_id': game, 'seed': 0, 'win_levels': 3,
                           'model_id': 'test-model', 'target_level': 3,
                           'source_run_id': source, 'restoration_actions': restored}
                if startup == 'model':
                    context['model_id'] = 'other-model'
                elif startup == 'extra':
                    context['prompt'] = 'PRIVATE-CONTEXT-SENTINEL'
                for _ in range(2 if startup == 'duplicate' else 1):
                    trace.append('arc.run.context', {'application_id': 'prime.arc-agi-3-solving', 'model_id': 'test-model'}, context)
            if position in revisions:
                revision = research_payloads(hashed)['model_revision']
                writer.append('model_revision', {**revision, 'source_action_sequence': position,
                              'level': position + 1, 'description_zh': revisions[position]})
            previous = hashed
        trace.seal()
        (root / 'summary.json').write_text(json.dumps({
            'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': name,
            'experiment': {'game_id': game, 'seed': 0, 'model': 'test-model'},
            'sealed_trace': True, 'replay_verified': True,
            'diagnostics': {'execution_mode': 'resumed', 'source_run_id': source,
                            'restoration_actions': restored} if source else {}}))
        return root

    def launch(self, current, source, game):
        launches = self.runs / 'launches'
        launches.mkdir(exist_ok=True)
        value = {'run_id': current.name, 'game': game, 'seed': 0,
                 'expected_model_id': 'test-model', 'target_level': 3,
                 'source_run_id': source.name, 'restoration_actions': 1,
                 'source_validation': {'game_id': game, 'seed': 0, 'win_levels': 3,
                     'source_run_id': source.name, 'restoration_actions': 1,
                     'levels_completed': 1, 'replay_sha256': 'sha256:' + 'a' * 64}}
        path = launches / (current.name + '.json')
        path.write_text(json.dumps(value))
        return path, value

    def test_active_without_summary_has_same_source_beliefs_for_any_game(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        for game in ('sp80-test', 'dc22-test'):
            for provenance in ('startup', 'launch'):
                with self.subTest(game=game, provenance=provenance):
                    tag = game + '-' + provenance
                    source = self.publish('source-' + tag, 1, {0: '本关历史规划'}, game=game)
                    current = self.publish('current-' + tag, 1, {1: '当前新关规划'}, source.name, 1,
                                           game=game, startup=provenance == 'startup')
                    finalized = build_console_snapshot(current)
                    (current / 'summary.json').unlink()
                    if provenance == 'launch':
                        self.launch(current, source, game)
                    live = build_console_snapshot(current)
                    self.assertEqual(live['levels'][0]['cognition'], finalized['levels'][0]['cognition'])
                    self.assertEqual(live['run']['model'], 'test-model')
                    self.assertEqual(live['run']['seed'], 0)
                    self.assertEqual(live['levels'][1]['cognition']['stable_description'], '当前新关规划')

    def test_bad_present_summary_or_live_provenance_does_not_fall_back(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        for failure in ('summary', 'launch-model', 'launch-seed', 'validation-source', 'validation-count'):
            with self.subTest(failure=failure):
                source = self.publish('source-' + failure, 1, {0: '不应导入'})
                current = self.publish('current-' + failure, 1, {}, source.name, 1)
                path, value = self.launch(current, source, 'sp80-test')
                if failure == 'summary':
                    (current / 'summary.json').write_text('{}')
                else:
                    (current / 'summary.json').unlink()
                    if failure == 'launch-model':
                        value['expected_model_id'] = 'other-model'
                    elif failure == 'launch-seed':
                        value['seed'] = True
                    elif failure == 'validation-source':
                        value['source_validation']['source_run_id'] = 'another-source'
                    else:
                        value['source_validation']['restoration_actions'] = 2
                    path.write_text(json.dumps(value))
                self.assertEqual(build_console_snapshot(current)['levels'][0]['cognition']['scope'], 'unavailable')

    def test_invalid_startup_context_never_uses_valid_launcher_fallback(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        for invalid in ('early', 'duplicate', 'model', 'extra'):
            with self.subTest(invalid=invalid):
                source = self.publish('source-context-' + invalid, 1, {0: '不应导入'})
                current = self.publish('current-context-' + invalid, 1, {}, source.name, 1, startup=invalid)
                (current / 'summary.json').unlink()
                self.launch(current, source, 'sp80-test')
                snapshot = build_console_snapshot(current)
                self.assertEqual(snapshot['levels'][0]['cognition']['scope'], 'unavailable')
                self.assertNotIn('PRIVATE-CONTEXT-SENTINEL', json.dumps(snapshot))

    def test_recursive_exact_prefix_keeps_original_level_beliefs_and_provenance(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        self.publish('run-first', 2, {0: '第一关规划', 1: '第二关旧规划', 2: '第三关旧规划'})
        self.publish('run-second', 2, {1: '第二关修订规划'}, 'run-first', 1)
        current = self.publish('run-current', 2, {2: '第三关当前规划'}, 'run-second', 2)
        snapshot = build_console_snapshot(current)
        first, second, third = snapshot['levels']
        self.assertEqual(first['cognition']['stable_description'], '第一关规划')
        self.assertEqual(second['cognition']['stable_description'], '第二关修订规划')
        self.assertEqual(third['cognition']['stable_description'], '第三关当前规划')
        self.assertEqual(first['cognition']['provenance']['run_id'], 'run-first')
        self.assertEqual(second['cognition']['provenance']['run_id'], 'run-second')
        self.assertEqual(third['cognition']['provenance'], {'run_id': 'run-current', 'event_sequence': 6})
        self.assertNotIn('第三关旧规划', json.dumps(snapshot, ensure_ascii=False))
        events = snapshot['process_events']
        self.assertEqual([e['event_sequence'] for e in events], sorted({e['event_sequence'] for e in events}))
        self.assertLess(first['cognition']['event_sequence'], second['cognition']['event_sequence'])
        self.assertLess(second['cognition']['event_sequence'], third['cognition']['event_sequence'])
        self.assertNotIn(str(self.runs), json.dumps(snapshot))

    def test_ineligible_scope_trace_prefix_and_cycle_never_supply_cognition(self):
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        for reason in ('model', 'seed', 'unsealed', 'prefix', 'source-journal', 'current-journal', 'cycle', 'symlink'):
            with self.subTest(reason=reason):
                name = 'source-' + reason
                source = self.publish(name, 1, {0: '不能导入的规划'})
                current = self.publish('current-' + reason, 1, {}, name, 1)
                summary = json.loads((source / 'summary.json').read_text())
                if reason in ('model', 'seed'):
                    summary['experiment'][reason] = 'other-model' if reason == 'model' else 1
                elif reason == 'unsealed':
                    summary['sealed_trace'] = False
                elif reason == 'cycle':
                    summary['diagnostics'] = {'execution_mode': 'resumed', 'source_run_id': current.name, 'restoration_actions': 1}
                elif reason == 'prefix':
                    path = current / 'trace' / 'prime-trace.jsonl'
                    path.write_text(path.read_text().replace('ACTION1', 'ACTION2'))
                elif reason in ('source-journal', 'current-journal'):
                    path = (source if reason == 'source-journal' else current) / 'console-events.jsonl'
                    rows = [json.loads(line) for line in path.read_text().splitlines()]
                    for row in rows:
                        if row['kind'] == 'action':
                            row['payload']['action'] = 'ACTION2'
                    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                elif reason == 'symlink':
                    alias = self.runs / 'alias-source'
                    alias.symlink_to(source, target_is_directory=True)
                    own = json.loads((current / 'summary.json').read_text())
                    own['diagnostics']['source_run_id'] = alias.name
                    (current / 'summary.json').write_text(json.dumps(own))
                (source / 'summary.json').write_text(json.dumps(summary))
                snapshot = build_console_snapshot(current)
                self.assertEqual(snapshot['levels'][0]['cognition']['scope'], 'unavailable')
                self.assertNotIn('不能导入的规划', json.dumps(snapshot, ensure_ascii=False))
