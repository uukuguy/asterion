"""Real adapter boundary with a fake SDK; no game or provider calls."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.p7.action_journal import ActionJournal
from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
from asterion.applications.prime.p7.live import ArcadeEngine


def reply():
    return SimpleNamespace(available_actions=[1], frame=[[[1, 2]]],
                           levels_completed=0, state=SimpleNamespace(value='NOT_FINISHED'), win_levels=7)


class TestDispatchDeadline(unittest.TestCase):
    def fixture(self, root, effect):
        now = [100.]
        task = TaskDeadline(deadline_monotonic=200., deadline_epoch=110.,
                            monotonic_clock=lambda: 100., wall_clock=lambda: now[0])
        settlement = TaskDeadline(deadline_monotonic=380., deadline_epoch=290.,
                                  monotonic_clock=lambda: 100., wall_clock=lambda: now[0])
        journal = ActionJournal(root, {'run_id': 'test'})
        journal.prepare(sequence=1, action={'name': 'ACTION1', 'data': {}}, before={'sequence': 0})
        engine = ArcadeEngine.__new__(ArcadeEngine)
        engine._actions = {'ACTION1': 1}
        engine._environment = SimpleNamespace(step=lambda *args: effect(now))
        engine._current = {'old': True}
        engine._evidence_cancelled, engine._evidence_deadline = None, None
        engine.set_dispatch_control(task_deadline=task, settlement_deadline=settlement, journal=journal)
        return engine, journal, now

    def test_recheck_after_journal_io_prevents_sdk_entry(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            engine, journal, now = self.fixture(Path(directory).resolve(), lambda _: calls.append(1))
            original = journal.dispatch_entered
            def slow_write(action):
                original(action)
                now[0] = 111.
            with patch.object(journal, 'dispatch_entered', side_effect=slow_write):
                with self.assertRaises(EvidenceProcessingError) as caught:
                    engine.step('ACTION1')
            self.assertEqual(caught.exception.stage, 'not-dispatched')
            self.assertEqual(calls, [])
            self.assertEqual(journal.snapshot()['phase'], 'not-dispatched')

    def test_return_after_task_expiry_captures_reply_under_settlement_limit(self):
        def effect(now):
            now[0] = 111.
            return reply()
        with tempfile.TemporaryDirectory() as directory:
            engine, journal, _ = self.fixture(Path(directory).resolve(), effect)
            result = engine.step('ACTION1')
            self.assertEqual(result['frame'][-1], ((1, 2),))
            self.assertEqual(journal.snapshot()['phase'], 'reply-received')
            self.assertTrue(journal.snapshot()['response']['task_deadline_expired'])
            self.assertFalse(journal.snapshot()['outcome_known'])
            self.assertFalse(engine.evidence_control()['cancelled']())
            with self.assertRaises(EvidenceProcessingError) as caught:
                engine.step('ACTION1')
            self.assertEqual(caught.exception.stage, 'not-dispatched')
            self.assertEqual(journal.snapshot()['phase'], 'reply-received')

    def test_settlement_expiry_preserves_metadata_without_claiming_validated_frame(self):
        def effect(now):
            now[0] = 291.
            return reply()
        with tempfile.TemporaryDirectory() as directory:
            engine, journal, _ = self.fixture(Path(directory).resolve(), effect)
            with self.assertRaises(EvidenceProcessingError) as caught:
                engine.step('ACTION1')
            self.assertEqual(caught.exception.stage, 'reply-received-unvalidated')
            reopened = ActionJournal(Path(directory).resolve(), {'run_id': 'test'})
            self.assertTrue(reopened.has_unresolved)
            self.assertEqual(reopened.snapshot()['response']['levels_completed'], 0)
            self.assertFalse(reopened.snapshot()['outcome_known'])

    def test_sdk_exception_keeps_unknown_and_blocks_subsequent_entry(self):
        calls = []
        def effect(_):
            calls.append(1)
            raise RuntimeError('private-sdk-error')
        with tempfile.TemporaryDirectory() as directory:
            engine, journal, _ = self.fixture(Path(directory).resolve(), effect)
            with self.assertRaises(EvidenceProcessingError) as caught:
                engine.step('ACTION1')
            self.assertEqual(caught.exception.stage, 'dispatched-no-reply')
            self.assertNotIn('private-sdk-error', str(caught.exception))
            self.assertEqual(journal.snapshot()['phase'], 'unresolved')
            with self.assertRaises((ValueError, EvidenceProcessingError)):
                engine.step('ACTION1')
            self.assertEqual(calls, [1])

    def test_expired_constructor_never_creates_sdk_game(self):
        task = TaskDeadline(deadline_monotonic=0., deadline_epoch=0.)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(EvidenceProcessingError) as caught:
            ArcadeEngine(arc_root=Path(directory), recordings_dir=Path(directory) / 'recordings',
                         task_deadline=task, settlement_deadline=task)
        self.assertEqual(caught.exception.stage, 'not-dispatched')

    def test_received_reply_survives_task_cancellation(self):
        cancelled = [False]
        def effect(_):
            cancelled[0] = True
            return reply()
        with tempfile.TemporaryDirectory() as directory:
            engine, journal, _ = self.fixture(Path(directory).resolve(), effect)
            engine.set_dispatch_control(task_deadline=engine.task_deadline,
                settlement_deadline=engine._settlement_deadline, journal=journal,
                cancelled=lambda: cancelled[0])
            self.assertEqual(engine.step('ACTION1')['frame'][-1], ((1, 2),))
            self.assertFalse(engine.evidence_control()['cancelled']())

    def test_initial_make_wall_jump_prevents_explicit_reset(self):
        now, calls = [100.], []
        task = TaskDeadline(deadline_monotonic=200., deadline_epoch=110.,
                            monotonic_clock=lambda: 100., wall_clock=lambda: now[0])
        settlement = TaskDeadline(deadline_monotonic=380., deadline_epoch=290.,
                                  monotonic_clock=lambda: 100., wall_clock=lambda: now[0])
        class SDK:
            def __init__(self, **kwargs):
                self.operation_mode = kwargs['operation_mode']
            def make(self, *args, **kwargs):
                calls.append('make')
                now[0] = 111.
                return SimpleNamespace(reset=lambda: calls.append('reset'))
        modules = {'arc_agi': SimpleNamespace(Arcade=SDK, OperationMode=SimpleNamespace(OFFLINE='offline')),
                   'arcengine': SimpleNamespace(GameAction=SimpleNamespace(RESET='RESET', **{f'ACTION{i}': i for i in range(1, 8)}))}
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', modules), \
                self.assertRaises(EvidenceProcessingError):
            ArcadeEngine(arc_root=Path(directory), recordings_dir=Path(directory) / 'recordings',
                         task_deadline=task, settlement_deadline=settlement)
        self.assertEqual(calls, ['make'])

    def test_initial_unresolved_journal_does_not_enter_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            journal = ActionJournal(root / 'journal', {'run_id': 'test'})
            journal.prepare(sequence=1, action={'name': 'ACTION1', 'data': {}}, before={'sequence': 0})
            with self.assertRaises(EvidenceProcessingError) as caught:
                ArcadeEngine(arc_root=root, recordings_dir=root / 'recordings', journal=journal)
            self.assertEqual(caught.exception.stage, 'dispatched-no-reply')
            self.assertEqual(journal.snapshot()['phase'], 'prepared')

    def test_late_valid_reply_reaches_existing_durable_broker_archive(self):
        from asterion.applications.prime.p7.broker import ArcBroker, read_observation
        def effect(now):
            now[0] = 111.
            return reply()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            engine, _, _ = self.fixture(root / 'unused', effect)
            journal = ActionJournal(root / 'journal', {'run_id': 'test'})
            engine.set_dispatch_control(task_deadline=engine.task_deadline,
                settlement_deadline=engine._settlement_deadline, journal=journal)
            initial = reply()
            initial.frame = [[[0, 2]]]
            engine._current = engine._snapshot(initial)
            engine.game_id, engine.seed = 'ls20-9607627b', 0
            engine.evidence_root = root / 'animation-evidence'
            broker = ArcBroker(engine=engine, action_profile='autonomous')
            broker.bind_history('test')
            result = broker.act_checked([{'action': {'name': 'ACTION1', 'data': {}}, 'expect': {}}])
            self.assertEqual(result['applied_count'], 1)
            receipt = journal.snapshot()
            self.assertEqual(receipt['phase'], 'committed')
            self.assertTrue(receipt['response']['task_deadline_expired'])
            restored = read_observation(engine.evidence_root, receipt['observation_ref']['evidence_ref'])
            self.assertEqual(restored.frame[-1], ((1, 2),))
