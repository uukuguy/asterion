"""Durable unresolved effects survive object/process-local state loss."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.action_journal import ActionJournal

ACTION = {'name': 'ACTION6', 'data': {'x': 2, 'y': 3}}
BEFORE = {'sequence': 0, 'observation_sha256': 'sha256:' + 'a' * 64}
SCOPE = {'run_id': 'run-test', 'game_id': 'test', 'seed': 0}


class TestActionJournal(unittest.TestCase):
    def test_pending_reopen_blocks_another_dispatch_and_does_not_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ActionJournal(Path(directory).resolve(), SCOPE)
            journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            reopened = ActionJournal(Path(directory).resolve(), SCOPE)
            self.assertTrue(reopened.has_unresolved)
            with self.assertRaises(ValueError):
                reopened.prepare(sequence=1, action=ACTION, before=BEFORE)
            self.assertEqual(reopened.snapshot()['phase'], 'prepared')

    def test_reply_metadata_is_not_a_validated_outcome_then_commit_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ActionJournal(Path(directory).resolve(), SCOPE)
            journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            journal.dispatch_entered(ACTION)
            journal.response_received({'state': 'GAME_OVER', 'levels_completed': 0})
            self.assertFalse(journal.snapshot()['outcome_known'])
            journal.commit(sequence=1, observation_ref={'sequence': 1, 'sha256': 'sha256:' + 'b' * 64})
            reopened = ActionJournal(Path(directory).resolve(), SCOPE)
            self.assertFalse(reopened.has_unresolved)
            self.assertTrue(reopened.snapshot()['outcome_known'])
            self.assertEqual(reopened.snapshot()['phase'], 'committed')
            journal.prepare(sequence=2, action=ACTION, before={'sequence': 1})
            journal.unresolved('dispatched-no-reply')
            self.assertTrue(ActionJournal(Path(directory).resolve(), SCOPE).has_unresolved)

    def test_not_dispatched_can_retry_and_failed_write_does_not_publish_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ActionJournal(Path(directory).resolve(), SCOPE)
            with patch('asterion.applications.prime.p7.action_journal.write_atomic_file', side_effect=OSError):
                with self.assertRaises(OSError):
                    journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            self.assertIsNone(journal.snapshot())
            journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            journal.not_dispatched('deadline-expired')
            self.assertFalse(journal.has_unresolved)

    def test_wrong_action_scope_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'journal'
            journal = ActionJournal(root, SCOPE)
            journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            with self.assertRaises(ValueError):
                journal.dispatch_entered({'name': 'RESET', 'data': {}})
            with self.assertRaises(ValueError):
                ActionJournal(root, {'run_id': 'other'})
            link = Path(directory).resolve() / 'link'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                ActionJournal(link, SCOPE)

    def test_directory_fsync_failure_keeps_published_pending_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ActionJournal(Path(directory).resolve(), SCOPE)
            calls = [0]
            def fail_directory(_):
                calls[0] += 1
                if calls[0] == 2:
                    raise OSError('directory fsync failed')
            with patch('asterion.applications.prime.p7.action_journal.os.fsync', side_effect=fail_directory):
                with self.assertRaises(OSError):
                    journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            self.assertTrue(journal.has_unresolved)
            self.assertTrue(ActionJournal(Path(directory).resolve(), SCOPE).has_unresolved)
