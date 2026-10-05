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
