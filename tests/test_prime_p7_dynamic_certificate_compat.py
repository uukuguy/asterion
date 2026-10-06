"""Static compatibility admits only the exact deployed verifier profile."""
import unittest
from unittest.mock import patch
from tests import test_prime_p7_solution_certificates as fixtures


class TestDynamicCertificateCompatibility(unittest.TestCase):
    def test_old_certificate_remains_immutable_and_reads_without_sdk(self):
        from asterion.applications.prime.p7 import solution_certificates as cert, solutions
        fixture = fixtures.TestP7SolutionCertificates()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        run = fixture.save()
        old_identity = cert.compatible_legacy_identity(fixture.arc, fixture.game)
        # Issue a fixture under the exact previous verifier identity, then
        # restore current code identity before testing the static admission.
        with patch.object(cert, 'capture_verification_identity', return_value=old_identity):
            expected = fixture.certify(run)
        original = {p.name: p.read_bytes() for p in (fixture.runs / 'solution-certificates' / 'revisions').iterdir()}
        with patch.object(cert, 'replay_arc_run', side_effect=AssertionError('SDK forbidden')), \
             patch.object(solutions, '_fresh_engine', side_effect=AssertionError('SDK forbidden')):
            actual = cert.read_certified_roster(fixture.arc, fixture.runs, fixture.catalog,
                                              expected_model_id=fixture.model)
            self.assertEqual(actual, (expected,))
            with patch.object(cert, '_sdk_identity', return_value={'changed-sdk': '0' * 64}):
                with self.assertRaises(cert.SolutionCertificateError):
                    cert.read_certified_roster(fixture.arc, fixture.runs, fixture.catalog,
                                               expected_model_id=fixture.model)
            game = fixture.arc / 'environment_files' / 'ls20' / '9607627b' / 'ls20.py'
            previous = game.read_bytes()
            game.write_bytes(b'# changed exact game')
            with self.assertRaises(cert.SolutionCertificateError):
                cert.read_certified_roster(fixture.arc, fixture.runs, fixture.catalog,
                                           expected_model_id=fixture.model)
            game.write_bytes(previous)
            summary = run / 'summary.json'
            summary.write_bytes(summary.read_bytes() + b'\n')
            with self.assertRaises(cert.SolutionCertificateError):
                cert.read_certified_roster(fixture.arc, fixture.runs, fixture.catalog,
                                           expected_model_id=fixture.model)
        self.assertEqual(original, {p.name: p.read_bytes() for p in (fixture.runs / 'solution-certificates' / 'revisions').iterdir()})
