"""Explicit supervised domain authority preserves per-dispatch boundaries."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
from asterion.applications.prime.p7.game import ArcGameContract, P7GameSelection, P7GameSelectionError
from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt, P7_TRACE_IDENTITIES
from asterion.applications.prime.p7.replay import replay_arc_run
from tests.test_prime_p7_native_broker import _Engine
from tests import test_prime_p7_solutions as saved_solutions


class TestP7SupervisedDomain(unittest.TestCase):
    def game(self):
        return replace(P7GameSelection('ls20-9607627b', 0), supervised_research=True)

    def test_selection_requires_explicit_bool_without_override(self):
        self.assertIn('supervised_research', P7GameSelection.__dataclass_fields__)
        game = self.game()
        self.assertIsNone(game.action_cap)
        self.assertEqual(P7GameSelection('ls20-9607627b', 0).action_cap, 500)
        for invalid in (1, None, 'true'):
            with self.subTest(invalid=invalid), self.assertRaises(P7GameSelectionError):
                replace(game, supervised_research=invalid)
        with self.assertRaises(P7GameSelectionError):
            replace(game, action_cap_override=1000)
        with self.assertRaises(P7GameSelectionError):
            ArcGameContract('ls20-9607627b', 7, action_cap=None)

    def test_supervised_crosses_old_cap_with_bounded_batches_and_replay(self):
        self.assertIn('supervised_research', P7GameSelection.__dataclass_fields__)
        broker = ArcBroker(engine=_Engine(), game=self.game())
        broker.bind_history('supervised-run')
        with self.assertRaises(ArcBrokerError):
            broker.act(('ACTION1',) * 65)
        self.assertEqual(broker.actions_dispatched, 0)
        for _ in range(8):
            broker.act(('ACTION1',) * 64)
        self.assertEqual(broker.status().primitive_actions, 512)
        self.assertIsNone(broker.status().actions_remaining)
        checked = broker.act_checked([{'action': {'name': 'ACTION1', 'data': {}},
                                       'expect': {'cell': {'x': 0, 'y': 0, 'value': 3}}}])
        self.assertEqual(checked['applied_count'], 1)
        broker.act(('RESET',))
        self.assertEqual(broker.status().primitive_actions, 514)
        self.assertIsNone(broker.status().actions_remaining)
        broker.interrupt()
        receipt = broker.seal()
        self.assertTrue(receipt.supervised_research)
        self.assertEqual(broker.replay(_Engine), receipt)
        with self.assertRaises(ArcBrokerError):
            replay_arc_run(broker.journal, receipt, _Engine)
        finite = ArcBroker(engine=_Engine())
        finite.act(('ACTION1',) * 500)
        self.assertEqual(finite.seal().terminal_reason, 'action-cap')
        with self.assertRaises(ArcBrokerError):
            finite.act(('ACTION1',))

    def test_finite_optimizer_rejects_supervised_authority(self):
        from asterion.applications.prime.p7.optimizer_arc import ArcReplayOracle
        with self.assertRaises(ValueError):
            ArcReplayOracle(game=self.game(), engine_factory=_Engine)

    def test_supervised_cancellation_and_unknown_effect_block_followup(self):
        self.assertIn('supervised_research', P7GameSelection.__dataclass_fields__)
        engine = _Engine()
        engine._dispatch_cancelled = lambda: len(engine.calls) >= 1
        broker = ArcBroker(engine=engine, game=self.game())
        with self.assertRaises(ArcBrokerError):
            broker.act(('ACTION1',) * 3)
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(broker.actions_dispatched, 1)
        uncertain = ArcBroker(engine=_Engine(raises_on=1), game=self.game())
        with self.assertRaises(ArcBrokerError):
            uncertain.act(('ACTION1',) * 3)
        with self.assertRaises(ArcBrokerError):
            uncertain.act(('ACTION1',))
        self.assertEqual(uncertain.actions_dispatched, 1)

    def test_private_trace_ready_after_old_cap_and_persists_provenance(self):
        self.assertIn('supervised_research', P7GameSelection.__dataclass_fields__)
        with tempfile.TemporaryDirectory() as directory:
            broker = ArcBroker(engine=_Engine(level_after=513), game=self.game())
            recorder = PrimeTraceRecorder(Path(directory))
            receipt = P7PrivateTraceReceipt(broker, recorder)
            def record():
                for item in broker.journal[len([e for e in recorder.snapshot() if e.kind == 'arc.action']):]:
                    recorder.append('arc.action', P7_TRACE_IDENTITIES, {
                        'action': item.action, 'after_sha256': item.after_sha256,
                        'before_sha256': item.before_sha256, 'levels_completed': item.levels_completed,
                        'sequence': item.sequence})
            for _ in range(8):
                broker.act(('ACTION1',) * 64)
                record()
            self.assertTrue(receipt.runtime_ready())
            broker.act(('ACTION1',))
            record()
            digest = receipt.expected_receipt_sha256(run_id='supervised-run')
            receipt.get_receipt(run_id='supervised-run', receipt_sha256=digest)
            marker = next(e.payload for e in recorder.snapshot() if e.kind == 'arc.run.completed')
            self.assertIs(marker['supervised_research'], True)

    def test_reader_admits_long_trace_only_with_agreeing_explicit_provenance(self):
        self.assertIn('supervised_research', P7GameSelection.__dataclass_fields__)
        from asterion.applications.prime.p7 import solutions
        from asterion.applications.prime.p7.score import replay_sha256
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = saved_solutions.TestP7SavedSolutions._arc_root(root)
            run = root / 'p7-supervised'
            (run / 'trace').mkdir(parents=True)
            recorder = PrimeTraceRecorder(run / 'trace')
            broker = ArcBroker(engine=_Engine(level_after=5001), game=self.game())
            while broker.actions_dispatched < 5001:
                broker.act(('ACTION1',) * min(64, 5001 - broker.actions_dispatched))
            for item in broker.journal:
                recorder.append('arc.action', P7_TRACE_IDENTITIES, {
                    'action': item.action, 'after_sha256': item.after_sha256,
                    'before_sha256': item.before_sha256, 'levels_completed': item.levels_completed,
                    'sequence': item.sequence})
            marker = {'game_id': broker.game.game_id, 'seed': 0, 'win_levels': 7,
                      'levels_completed': 1, 'primitive_actions': 5001,
                      'replay_sha256': replay_sha256(broker.journal, terminal_reason='level-completed'),
                      'terminal_reason': 'level-completed', 'supervised_research': True}
            recorder.append('arc.run.completed', P7_TRACE_IDENTITIES, marker)
            recorder.seal()
            recording = run / 'recordings' / 'session'
            recording.mkdir(parents=True)
            def row(name):
                return {'data': {'game_id': broker.game.game_id, 'win_levels': 7,
                                 'action_input': {'id': name, 'data': {}}}}
            (recording / 'ls20.jsonl').write_text('\n'.join(json.dumps(row(name)) for name in ['RESET'] + ['ACTION1'] * 5001))
            summary = {'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': run.name,
                       'replay_verified': True, 'sealed_trace': True, 'cleanup_complete': True,
                       'experiment': {'supervised_research': True, 'action_cap': None},
                       'broker': marker, 'receipt': {'completed_level_count': 1, 'primitive_action_count': 5001}}
            (run / 'summary.json').write_text(json.dumps(summary))
            found = solutions._read_one(arc, run, broker.game.game_id, 0, None)
            self.assertIsNotNone(found)
            prefix, receipt, game = found
            self.assertTrue(game.supervised_research)
            self.assertTrue(prefix.supervised_research)
            self.assertTrue(receipt.supervised_research)
            with patch.object(solutions, '_fresh_engine', side_effect=lambda *_: _Engine(level_after=5001)):
                self.assertIsNotNone(solutions._load_one(arc, run, broker.game.game_id, 0, None))
            summary['experiment'] = {'action_cap': 5000}
            (run / 'summary.json').write_text(json.dumps(summary))
            self.assertIsNone(solutions._read_one(arc, run, broker.game.game_id, 0, None))

    def test_provenance_keeps_legacy_finite_metadata_and_rejects_inference(self):
        from asterion.applications.prime.p7.solutions import _supervised_provenance
        self.assertIs(_supervised_provenance({'experiment': None}, {}), False)
        self.assertIsNone(_supervised_provenance({'experiment': {'action_cap': None}}, {}))
        for marker in (None, False, 1, 'true'):
            with self.subTest(marker=marker):
                self.assertIsNone(_supervised_provenance(
                    {'experiment': {'action_cap': None, 'supervised_research': True}},
                    {'supervised_research': marker}))
