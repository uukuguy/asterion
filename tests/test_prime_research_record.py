"""Prime research relationships stay private, bounded, and semantically modest."""
import json
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.research_record import ResearchRecordStore


class TestResearchRecordStore(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve() / 'research-chain.json'
        self.scope = {'run_id': 'record-story'}

    def test_reload_checks_integrity_and_retains_temporal_only_relationship(self):
        store = ResearchRecordStore(path=self.path, scope=self.scope)
        store.append(key='note-1', kind='notes', origin='model_statement',
                     statement={'preview': 'private-sentinel'}, evidence_refs=[{'revision': 'original'}])
        store.append(key='experiment-1', kind='experiment', origin='behavioral_evidence')
        reloaded = ResearchRecordStore(path=self.path, scope=self.scope)
        reloaded.append(key='experiment-1', kind='experiment', origin='behavioral_evidence')
        self.assertEqual(reloaded.summary()['record_count'], 2)
        self.assertNotIn('private-sentinel', json.dumps(reloaded.summary()))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        value = json.loads(self.path.read_text())
        self.assertEqual(value['records'][1]['links'], [{'relation': 'observed_after',
            'record_id': value['records'][0]['record_id']}])
        value['records'][0]['causal_support'] = 'certified'
        self.path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            ResearchRecordStore(path=self.path, scope=self.scope)

    def test_limits_explicitly_count_missing_references_and_records(self):
        from unittest.mock import patch
        store = ResearchRecordStore(path=self.path, scope=self.scope)
        with patch('asterion.agents.prime.research_record._MAX_RECORDS', 2):
            store.append(key='first', kind='notes', origin='model_statement',
                         evidence_refs=[{'ordinal': index} for index in range(66)])
            store.append(key='second', kind='notes', origin='model_statement')
            store.append(key='third', kind='notes', origin='model_statement')
        self.assertEqual(store.summary(), {'record_count': 2, 'omitted_record_count': 1,
                                          'omitted_reference_count': 2})
        self.assertEqual(ResearchRecordStore(path=self.path, scope=self.scope).summary(), store.summary())

    def test_corrupt_index_shapes_are_rejected_without_unexpected_exceptions(self):
        for record in (None, [], {'key': []}, {'record_id': 'invalid', 'key': []}):
            with self.subTest(record=record):
                self.path.write_text(json.dumps({'version': 'asterion.prime-research-record/v1',
                    'scope': self.scope, 'records': [record], 'omitted_records': 0, 'omitted_refs': 0}))
                with self.assertRaises(ValueError):
                    ResearchRecordStore(path=self.path, scope=self.scope)


if __name__ == '__main__':
    unittest.main()
