"""Save-time replay certificates keep official selection provider/engine free."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_prime_p7_solutions as fixtures


class TestP7SolutionCertificates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.arc = fixtures.TestP7SavedSolutions._arc_root(self.root)
        self.runs = self.root / 'runs'
        self.game = 'ls20-9607627b'
        self.model = 'gpt-6.1-sol'
        self.catalog = ({'game_id': self.game, 'win_levels': 7,
                         'baseline_actions': (22, 123, 73, 84, 96, 192, 186)},)
        self.sdk = patch('asterion.applications.prime.p7.solution_certificates._sdk_identity',
                         return_value={'fixture-sdk': 'a' * 64})
        self.sdk.start()
        self.addCleanup(self.sdk.stop)

    def save(self, name='p7-selected'):
        from asterion.applications.prime.p7.private_trace import trace_identities_for
        from asterion.applications.prime.p7.score import digest
        run = self.runs / name
        with patch('asterion.applications.prime.p7.private_trace.P7_TRACE_IDENTITIES', trace_identities_for(self.model)):
            fixtures.TestP7SavedSolutions._write_run(run)
        p = run / 'summary.json'
        summary = json.loads(p.read_text())
        summary['experiment'] = {'game_id': self.game, 'seed': 0, 'model': self.model,
                                 'prediction_variant': 'verified', 'target_level': 1}
        p.write_text(json.dumps(summary))
        scope = {'game_id': self.game, 'seed': 0, 'win_levels': 7, 'run_id': name, 'attempt_id': name}
        world = {'scope': scope, 'worldmap': {'description_zh': '移动', 'state_summary': '第一关',
                 'rules': [], 'unknowns': [], 'competing_hypotheses': []}}
        revision = digest(world)
        research = run / 'research' / digest(scope)[7:]
        (research / 'revisions').mkdir(parents=True)
        (research / 'current.json').write_text(json.dumps({'scope': scope, 'revision': revision}))
        (research / 'revisions' / (revision[7:] + '.json')).write_text(json.dumps(world))
        return run

    def certify(self, run):
        from asterion.applications.prime.p7 import solution_certificates as cert, solutions
        evidence = solutions._read_one(self.arc, run, self.game, 0, None, self.model, strict_model=True)
        self.assertIsNotNone(evidence)
        prefix, receipt, game = evidence
        calls = []
        def engine():
            calls.append(True)
            return fixtures._Engine()
        actual, witness = cert.verify_for_save(self.arc, game, prefix.transitions, receipt, prefix.observations, engine)
        self.assertEqual(actual, receipt)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(witness)
        return cert.publish_verified_save(self.arc, run, witness, expected_model_id=self.model)

    def test_saved_certificate_selection_performs_no_sdk_execution(self):
        from asterion.applications.prime.p7 import solution_certificates as cert
        run = self.save()
        prefix = self.certify(run)
        with patch('asterion.applications.prime.p7.solutions._fresh_engine', side_effect=AssertionError('SDK')):
            selected = cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
        self.assertEqual(selected, (prefix,))
        (run / 'view.html').write_text('derived output')
        self.assertEqual(cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model), (prefix,))

    def test_reader_static_parses_only_registered_winner_and_rejects_new_source_before_parse(self):
        from asterion.applications.prime.p7 import solution_certificates as cert, solutions
        first = self.save('p7-first')
        self.certify(first)
        second = self.save('p7-second')
        self.certify(second)
        with patch.object(solutions, '_read_one', wraps=solutions._read_one) as read:
            cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
        self.assertEqual([call.args[1].name for call in read.call_args_list], ['p7-first'])
        self.save('p7-unregistered')
        with patch.object(solutions, '_read_one', side_effect=AssertionError('submit parsed a new source')):
            with self.assertRaises(cert.SolutionCertificateError):
                cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)

    def test_missing_new_source_mutated_evidence_game_or_sdk_rejects_without_fallback(self):
        from asterion.applications.prime.p7 import solution_certificates as cert
        run = self.save()
        with self.assertRaises(ValueError):
            cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
        self.certify(run)
        other = self.save('p7-new')
        with self.assertRaises(ValueError):
            cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
        self.certify(other)
        path = run / 'summary.json'
        original = path.read_bytes()
        path.write_text(json.dumps({**json.loads(original), 'reason': 'changed source'}))
        with self.assertRaises(ValueError):
            cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
        path.write_bytes(original)
        code = self.arc / 'environment_files' / 'ls20' / '9607627b' / 'ls20.py'
        code.write_text('# changed game\n')
        with self.assertRaises(ValueError):
            cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
        code.write_text('# fixture\n')
        with patch('asterion.applications.prime.p7.solution_certificates._sdk_identity', return_value={'fixture-sdk': 'b' * 64}):
            with self.assertRaises(ValueError):
                cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)

    def test_replay_failure_or_identity_change_cannot_mint_save_witness(self):
        from asterion.applications.prime.p7 import solution_certificates as cert, solutions
        run = self.save()
        prefix, receipt, game = solutions._read_one(self.arc, run, self.game, 0, None, self.model, strict_model=True)
        with self.assertRaises(RuntimeError):
            cert.verify_for_save(self.arc, game, prefix.transitions, receipt, prefix.observations,
                                 lambda: (_ for _ in ()).throw(RuntimeError('replay failed')))
        with patch.object(cert, 'capture_verification_identity', side_effect=('a', 'b')):
            actual, witness = cert.verify_for_save(self.arc, game, prefix.transitions, receipt, prefix.observations, fixtures._Engine)
        self.assertEqual(actual, receipt)
        self.assertIsNone(witness)
        with self.assertRaises(ValueError):
            cert.publish_verified_save(self.arc, run, deepcopy(receipt), expected_model_id=self.model)
        with patch.object(cert, 'capture_verification_identity', side_effect=ModuleNotFoundError('SDK missing')):
            actual, witness = cert.verify_for_save(self.arc, game, prefix.transitions, receipt, prefix.observations, fixtures._Engine)
        self.assertEqual(actual, receipt)
        self.assertIsNone(witness)

    def test_metadata_directory_paths_and_certificate_terminal_fail_closed(self):
        from asterion.applications.prime.p7 import solution_certificates as cert
        run = self.save()
        self.certify(run)
        descriptor = cert._source_identity(run, descriptor=True)
        for path in ('/private', '../outside'):
            with self.subTest(path=path):
                invalid = deepcopy(descriptor)
                invalid['directories'].append([path, []])
                self.assertFalse(cert._metadata_matches(self.runs, invalid))
        root = self.runs / 'solution-certificates'
        pointer_path = cert._pointer(root, self.game, self.model)
        pointer = json.loads(pointer_path.read_text())
        record = json.loads((root / 'revisions' / (pointer['winner']['certificate'] + '.json')).read_text())
        record['terminal_reason'] = 'game-won'
        token = cert._digest(record)
        (root / 'revisions' / (token + '.json')).write_text(json.dumps(record))
        pointer['winner']['certificate'] = token
        pointer_path.write_text(json.dumps(pointer))
        with self.assertRaises(cert.SolutionCertificateError):
            cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)

    def test_registry_metadata_is_portable_and_sdk_ignores_install_records(self):
        from types import SimpleNamespace
        from asterion.applications.prime.p7 import solution_certificates as cert
        run = self.save()
        descriptor = cert._source_identity(run, descriptor=True)
        self.assertTrue(cert._metadata_matches(self.runs, descriptor))
        for item in descriptor['files']:
            self.assertEqual(set(item), {'path', 'size', 'mtime_ns', 'small_sha256'})
            if item['small_sha256'] is not None:
                # Reinstallation/copy timestamps do not alter metadata contents.
                item['mtime_ns'] = 1
        self.assertTrue(cert._metadata_matches(self.runs, descriptor))
        self.sdk.stop()
        package = self.root / 'installed-sdk'
        for name in ('arc_agi/engine.py', 'arcengine/engine.py', 'sdk.dist-info/METADATA',
                     'sdk.dist-info/RECORD', 'sdk.dist-info/direct_url.json'):
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('stable code' if name.endswith('engine.py') else 'stable metadata')
        files = [Path(name) for name in ('arc_agi/engine.py', 'arcengine/engine.py',
                 'sdk.dist-info/METADATA', 'sdk.dist-info/RECORD', 'sdk.dist-info/direct_url.json')]
        def installed(name):
            return SimpleNamespace(version=cert.SDK[name], files=files,
                                   locate_file=lambda item: package / item)
        with patch.object(cert, 'distribution', side_effect=installed):
            before = cert._sdk_identity()
            (package / 'sdk.dist-info/RECORD').write_text('guest relocation record')
            (package / 'sdk.dist-info/direct_url.json').write_text('guest wheel path')
            self.assertEqual(before, cert._sdk_identity())
            (package / 'arcengine/engine.py').write_text('changed SDK code')
            self.assertNotEqual(before, cert._sdk_identity())
