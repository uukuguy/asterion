"""Read-only bundles over actual committed P7 action evidence; provider free."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p7.action_journal import ActionJournal
from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from tests.test_prime_p7_research_runtime import _TraceClient
from tests.test_prime_p7_research_runtime import _Signal


class _Engine:
    game_id, seed = 'ls20-9607627b', 0

    def __init__(self):
        self.calls = []
        self.levels_completed, self.state = 0, 'NOT_FINISHED'
        self.frames = [[[0, 1]]]
        self.fail = False

    def observe(self):
        return {'available_actions': ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION6'],
                'frame': self.frames, 'levels_completed': self.levels_completed,
                'state': self.state, 'win_levels': 7}

    def step(self, action, data=None):
        self.calls.append((action, data or {}))
        if self.fail:
            raise RuntimeError('private engine fault')
        if action == 'ACTION2':
            self.frames = [[[0, 1]], [[1, 1]], [[2, 1]]]
        elif action == 'ACTION3':
            self.levels_completed += 1
            self.frames = [[[3, 1]]]
        elif action == 'ACTION6':
            self.state, self.frames = 'GAME_OVER', [[[4, 1]]]
        elif action == 'RESET':
            self.state, self.frames = 'NOT_FINISHED', [[[5, 1]]]
        return self.observe()


class TestP7ResearchTransition(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runner = asyncio.Runner()
        self.addCleanup(self.runner.close)
        self.root = Path(temporary.name).resolve() / 'transition-story'
        self.root.mkdir()
        self.engine = _Engine()
        game = P7GameSelection(self.engine.game_id, self.engine.seed, target_level=2,
                              _metadata_win_levels=7, _metadata_baseline_actions=(1,) * 7)
        self.broker = ArcBroker(engine=self.engine, game=game, action_profile='autonomous')
        self.broker.bind_history(self.root.name)
        self.host = P7ResearchRuntime(broker=self.broker, trace_client=_TraceClient(),
            run_root=self.root, run_id=self.root.name, deadline_seconds=30,
            event_sink=lambda *_: None)
        self.addCleanup(lambda: self.runner.run(self.host.close()))

    def read(self, sequence):
        return self.host._read_server.dispatch({'method': 'transition', 'args': [sequence]})

    def test_bundle_matches_committed_action_and_exact_observation_references(self):
        before = self.host.current_context()['observation_ref']
        self.broker.act((ArcAction('ACTION6', (('x', 0), ('y', 0))),))
        after = self.host.current_context()['observation_ref']
        result = self.read(1)
        self.assertEqual(result['status'], 'ok')
        value = result['value']
        self.assertEqual(set(value), {'sequence', 'action', 'data', 'before_observation_ref',
            'after_observation_ref', 'state', 'levels_completed', 'after_animation_ref'})
        self.assertEqual((value['sequence'], value['action'], value['data']),
                         (1, 'ACTION6', {'x': 0, 'y': 0}))
        self.assertEqual(value['before_observation_ref'], before)
        self.assertEqual(value['after_observation_ref'], after)
        self.assertEqual((value['state'], value['levels_completed']), ('GAME_OVER', 0))
        self.assertEqual(value['after_animation_ref']['frame_count'], 1)
        value['data']['x'] = 9
        value['before_observation_ref']['run_id'] = 'wrong'
        value['after_animation_ref']['frame_count'] = 99
        self.assertEqual(self.read(1)['value']['data'], {'x': 0, 'y': 0})
        self.assertEqual(self.read(1)['value']['before_observation_ref'], before)
        self.assertEqual(self.read(1)['value']['after_animation_ref']['frame_count'], 1)
        self.assertEqual(self.engine.calls, [('ACTION6', {'x': 0, 'y': 0})])

    def test_sdk_frames_and_animation_reuse_exact_bundle_references(self):
        module = {}
        exec(self.host._read_server.start(), module)
        self.assertTrue(callable(module.get('transition')))
        for sequence, action, count in ((1, 'ACTION1', 1), (2, 'ACTION2', 3)):
            with self.subTest(sequence=sequence):
                self.broker.act((ArcAction(action, (('x', 0), ('y', 0)))
                                 if action == 'ACTION6' else action,))
                value = module['transition'](sequence)
                before, after = value['before_observation_ref'], value['after_observation_ref']
                self.assertEqual((before['sequence'], after['sequence']), (sequence - 1, sequence))
                self.assertEqual(module['frame'](after['sequence']), self.broker.frame_at(sequence))
                animation = module['animation'](after)
                self.assertEqual(animation['observation_ref'], after)
                self.assertEqual(animation['animation_ref'], value['after_animation_ref'])
                self.assertEqual(len(animation['frames']), count)
                self.assertEqual(animation['frames'][-1], module['frame'](sequence))
                if count > 1:
                    page = module['animation'](after, start=1, limit=1)
                    self.assertEqual(page['frames'], [animation['frames'][1]])
                    self.assertEqual(page['animation_ref'], value['after_animation_ref'])
                    self.assertEqual(page['observation_ref'], after)
        self.assertEqual(module['frame'](0), module['frame'](1))
        self.assertEqual(len(self.engine.calls), 2)

    def test_persistent_worker_reads_action_committed_by_runtime_plan(self):
        self.host.solver.learner_profile = 'autonomous'
        before = self.host.current_context()
        result = self.host.method_call('execute_plan', {
            'plan_id': 'transition-worker', 'start': before['observation_ref'],
            'workspace_revision': before['workspace_revision'], 'goal': 'observe',
            'purpose': 'probe', 'assumptions': [], 'stop_on_mismatch': False,
            'steps': [{'action': {'name': 'ACTION2', 'data': {}}, 'expect': {}}],
        }, _Signal())
        self.assertEqual(result['applied_count'], 1)
        read = self.runner.run(self.host.execute('read-transition',
            "import p7_research as r\n"
            "t = r.transition(1)\n"
            "assert t['action'] == 'ACTION2' and t['data'] == {}\n"
            "assert t['before_observation_ref']['sequence'] == 0\n"
            "assert t['after_observation_ref']['sequence'] == 1\n"
            "a = r.animation(t['after_observation_ref'])\n"
            "assert a['animation_ref'] == t['after_animation_ref']\n"
            "assert len(a['frames']) == 3\n"
            "assert a['frames'][-1] == r.frame(1)\n"
            "print('transition-worker-ok')", _Signal()))
        self.assertEqual(read.status, 'ok')
        self.assertEqual(len(self.engine.calls), 1)

    def test_level_pass_and_reset_retain_each_side_level_and_state(self):
        self.assertTrue(callable(self.host._read_server._readers.get('transition')))
        for sequence, action, levels, state, before_level, after_level in (
            (1, 'ACTION3', 1, 'NOT_FINISHED', 1, 2),
            (2, 'ACTION6', 1, 'GAME_OVER', 2, 2),
            (3, 'RESET', 1, 'NOT_FINISHED', 2, 2),
        ):
            with self.subTest(action=action):
                self.broker.act((ArcAction(action, (('x', 0), ('y', 0)))
                                 if action == 'ACTION6' else action,))
                result = self.read(sequence)
                self.assertEqual(result['status'], 'ok')
                value = result['value']
                self.assertEqual((value['levels_completed'], value['state']), (levels, state))
                self.assertEqual(value['before_observation_ref']['level'], before_level)
                self.assertEqual(value['after_observation_ref']['level'], after_level)
                self.assertEqual(value['after_observation_ref'], self.host.current_context()['observation_ref'])
        self.assertEqual(self.read(1)['value']['levels_completed'], 1)
        self.assertEqual(self.read(2)['value']['state'], 'GAME_OVER')

    def test_invalid_and_unknown_sequences_reject_without_actions(self):
        self.broker.act(('ACTION1',))
        before = self.broker.journal
        for sequence in (True, False, 0, -1, 2, 999, '1', 1.0, None):
            with self.subTest(sequence=sequence):
                self.assertEqual(self.read(sequence)['status'], 'rejected')
        self.assertEqual(self.broker.journal, before)
        self.assertEqual(len(self.engine.calls), 1)
        self.engine.fail = True
        with self.assertRaises(EvidenceProcessingError):
            self.broker.act(('ACTION1',))
        self.assertEqual(self.read(2)['status'], 'rejected')
        self.assertEqual(self.read(1)['status'], 'ok')
        self.assertEqual(len(self.engine.calls), 2)

    def test_pending_transaction_and_failed_commit_tail_are_not_readable(self):
        journal = ActionJournal(self.root / 'transactions', {'run_id': self.root.name})
        self.engine.action_journal = journal
        self.broker.act(('ACTION1',))
        self.assertEqual(self.read(1)['status'], 'ok')
        with patch.object(journal, 'commit', side_effect=OSError('private path fault')):
            with self.assertRaises(EvidenceProcessingError):
                self.broker.act(('ACTION2',))
        self.assertEqual(len(self.broker.journal), 2)
        self.assertEqual(journal.snapshot()['phase'], 'unresolved')
        self.assertEqual(self.read(2)['status'], 'rejected')
        self.assertEqual(self.read(1)['status'], 'ok')
        self.assertEqual(len(self.engine.calls), 2)

    def test_wire_validation_precedes_reader_and_transport_is_authenticated(self):
        self.broker.act(('ACTION1',))
        with patch.dict(self.host._read_server._readers, transition=lambda *_: self.fail('invalid callback')):
            for args in ([], [1, 2], [False], [0], [-1], ['1']):
                with self.subTest(args=args):
                    result = self.host._read_server.dispatch({'method': 'transition', 'args': args})
                    self.assertEqual(result['status'], 'rejected')
        module = {}
        exec(self.host._read_server.start(), module)
        self.assertTrue(callable(module.get('transition')))
        self.assertEqual(module['transition'](1)['sequence'], 1)
        # The SDK's authenticated transport is reused unchanged by this route.
        import json
        import socket
        address = self.host._read_server._server.server_address
        with socket.create_connection(address, timeout=5) as connection:
            connection.sendall((json.dumps({'token': 'wrong', 'request':
                {'method': 'transition', 'args': [1]}}) + '\n').encode())
            self.assertEqual(json.loads(connection.makefile('rb').readline())['status'], 'rejected')
        self.assertEqual(len(self.engine.calls), 1)
