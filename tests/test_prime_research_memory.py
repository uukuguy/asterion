"""Private domain-neutral memory blobs, without a second commit pointer."""

import importlib
import tempfile
import unittest
from pathlib import Path


class TestPrimeResearchMemory(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('asterion.agents.prime.memory')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = {'opaque': {'session': 'one'}}
        self.store = self.module.ResearchMemoryStore(root=self.root, scope=self.scope)

    def test_freeform_revisions_are_detached_scoped_and_paged(self):
        refs = [{'opaque-reference': ['evidence', 0]}]
        first = self.store.save('partial hypothesis; next test?', evidence_refs=refs)
        self.scope['opaque']['session'] = 'changed'
        refs[0]['opaque-reference'][0] = 'changed'
        first['text'] = 'mutated result'
        saved = self.store.read(first['revision'])
        self.assertEqual(saved['text'], 'partial hypothesis; next test?')
        self.assertEqual(saved['scope'], {'opaque': {'session': 'one'}})
        self.assertEqual(saved['evidence_refs'], [{'opaque-reference': ['evidence', 0]}])
        second = self.store.save('counterexample retained', parent_revision=first['revision'])
        self.assertEqual(self.store.history(second['revision'], start=0, limit=1)['items'], [second])
        self.assertEqual(self.store.history(second['revision'], start=1, limit=1)['items'], [saved])
        self.assertFalse((self.root / 'current.json').exists())
        other = self.module.ResearchMemoryStore(root=self.root, scope={'opaque': 'other'})
        with self.assertRaises(ValueError):
            other.read(second['revision'])

    def test_rejects_empty_oversized_nonfinite_unknown_parents_and_corruption(self):
        for text in ('', '  ', '\N{GRINNING FACE}' * 4097, None):
            with self.subTest(text=type(text)), self.assertRaises(ValueError):
                self.store.save(text)
        with self.assertRaises(ValueError):
            self.store.save('valid', evidence_refs=[float('nan')])
        with self.assertRaises(ValueError):
            self.store.save('valid', parent_revision='sha256:' + 'a' * 64)
        value = self.store.save('valid')
        path = self.root / 'revisions' / (value['revision'][7:] + '.json')
        path.write_text('{}')
        with self.assertRaises(ValueError):
            self.store.read(value['revision'])

