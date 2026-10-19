"""The accepted-note epoch is domain-neutral and does not promote orphans."""
import unittest
from pathlib import Path
import tempfile

from asterion.agents.prime.memory import ResearchMemoryStore
from asterion.agents.prime.research_notes import ResearchNotes


class TestResearchNotes(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ResearchMemoryStore(
            root=Path(temporary.name), scope={'opaque': 'session-1'})
        self.notes = ResearchNotes(self.store, accepted_revision=None)

    def test_save_keeps_the_epoch_until_the_application_commits(self):
        saved = self.notes.save(
            'counterexample retained', evidence_refs=[{'opaque-reference': 1}])
        self.assertIsNone(self.notes.accepted_revision)
        self.assertIsNone(self.notes.read())
        self.assertEqual(self.notes.history()['items'], [])
        with self.assertRaises(ValueError):
            self.notes.read(saved['revision'])
        committed = ResearchNotes(self.store, accepted_revision=saved['revision'])
        self.assertEqual(committed.read()['text'], 'counterexample retained')
        self.assertEqual(committed.read()['evidence_refs'], [{'opaque-reference': 1}])
        self.assertNotIn('counterexample retained', repr(committed))

    def test_ancestor_is_readable_and_orphan_is_not_history(self):
        first = self.notes.save('accepted fact')
        epoch = ResearchNotes(self.store, accepted_revision=first['revision'])
        second = epoch.save('later fact')
        orphan = self.store.save('orphan', parent_revision=first['revision'])
        head = ResearchNotes(self.store, accepted_revision=second['revision'])
        self.assertEqual(head.read(first['revision'])['text'], 'accepted fact')
        self.assertEqual(
            [item['text'] for item in head.history(start=0, limit=2)['items']],
            ['later fact', 'accepted fact'])
        with self.assertRaises(ValueError):
            head.read(orphan['revision'])

    def test_returned_record_mutation_does_not_change_the_document(self):
        saved = self.notes.save('stable')
        epoch = ResearchNotes(self.store, accepted_revision=saved['revision'])
        epoch.read()['text'] = 'mutated'
        self.assertEqual(epoch.read()['text'], 'stable')


if __name__ == '__main__':
    unittest.main()
