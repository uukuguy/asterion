"""Write-ahead effect accounting and final dispatch admission are distinct."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.p7.action_journal import ActionJournal
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
from tests.test_prime_p7_native_broker import _Engine


class TestP7BrokerTransactions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.clocks = [0.0, 0.0]
        self.deadline = TaskDeadline(deadline_monotonic=10, deadline_epoch=10,
            monotonic_clock=lambda: self.clocks[0], wall_clock=lambda: self.clocks[1])
        self.engine = _Engine()
        self.engine.task_deadline = self.deadline
        self.engine.action_journal = self.journal = ActionJournal(self.root / 'journal', {'run_id': 'test'})
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history('test')

    def step(self):
        return self.broker.act_checked([{'action': {'name': 'ACTION1', 'data': {}}, 'expect': {}}])

    def test_deadline_crossed_during_prepare_is_definitely_not_dispatched(self):
        prepare = self.journal.prepare
        def delayed(**kwargs):
            prepare(**kwargs)
            self.clocks[1] = 11
        with patch.object(self.journal, 'prepare', side_effect=delayed):
            with self.assertRaises(EvidenceProcessingError) as caught:
                self.step()
        self.assertEqual(caught.exception.stage, 'not-dispatched')
        self.assertTrue(caught.exception.outcome_known)
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.broker.actions_dispatched, 0)
        self.assertEqual(self.journal.snapshot()['phase'], 'not-dispatched')

    def test_failed_intent_write_never_calls_engine_or_counts_dispatch(self):
        with patch.object(self.journal, 'prepare', side_effect=OSError):
            with self.assertRaises(EvidenceProcessingError) as caught:
                self.step()
        self.assertEqual(caught.exception.stage, 'not-dispatched')
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.broker.actions_dispatched, 0)

    def test_unknown_effect_survives_reopen_and_blocks_followup(self):
        self.engine.raises_on = 1
        with self.assertRaises(EvidenceProcessingError):
            self.step()
        reopened = ActionJournal(self.root / 'journal', {'run_id': 'test'})
        self.assertTrue(reopened.has_unresolved)
        self.assertEqual(reopened.snapshot()['phase'], 'unresolved')
        self.engine.action_journal = reopened
        with self.assertRaises(EvidenceProcessingError):
            self.step()
        self.assertEqual(self.engine.calls, ['ACTION1'])
        self.assertEqual(self.broker.actions_dispatched, 1)

    def test_received_action_commits_after_task_expiry_and_next_action_is_stopped(self):
        original = self.engine.step
        def received(action):
            reply = original(action)
            self.clocks[:] = [11, 11]
            return reply
        self.engine.step = received
        result = self.step()
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(self.journal.snapshot()['phase'], 'committed')
        self.assertTrue(self.journal.snapshot()['outcome_known'])
        self.assertEqual(self.journal.snapshot()['observation_ref']['sequence'], 1)
        with self.assertRaises(EvidenceProcessingError) as caught:
            self.step()
        self.assertEqual(caught.exception.stage, 'not-dispatched')
        self.assertEqual(self.engine.calls, ['ACTION1'])
        self.assertEqual(self.broker.actions_dispatched, 1)

    def test_failed_commit_preserves_known_reply_and_blocks_without_downgrade(self):
        with patch.object(self.journal, 'commit', side_effect=OSError):
            with self.assertRaises(EvidenceProcessingError) as caught:
                self.step()
        self.assertTrue(caught.exception.outcome_known)
        self.assertEqual(len(self.broker.journal), 1)
        self.assertEqual(self.journal.snapshot()['phase'], 'unresolved')
        self.assertTrue(self.journal.snapshot()['outcome_known'])
        with self.assertRaises(EvidenceProcessingError) as blocked:
            self.step()
        self.assertTrue(blocked.exception.outcome_known)
        self.assertEqual(blocked.exception.stage, 'derived-failed')
        self.assertEqual(self.engine.calls, ['ACTION1'])
