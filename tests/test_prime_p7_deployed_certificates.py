"""Explicit deployed verifier compatibility never changes certificate bytes."""

import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import solution_certificates as cert
from tests import test_prime_p7_solution_certificates as fixtures


class TestDeployedCertificates(unittest.TestCase):
    setUp = fixtures.TestP7SolutionCertificates.setUp
    save = fixtures.TestP7SolutionCertificates.save
    certify = fixtures.TestP7SolutionCertificates.certify

    def test_frozen_deployed_identity_reads_original_certificate_without_reissuing(self):
        reader = getattr(cert, "compatible_deployed_identities", None)
        self.assertTrue(callable(reader), "exact deployed verifier profiles are required")
        identities = reader(self.arc, self.game)
        self.assertEqual(len(identities), 4)
        self.assertEqual(identities[0], cert.compatible_legacy_identity(self.arc, self.game))
        for index, identity in enumerate(identities):
            with self.subTest(profile=index):
                self.runs = self.root / f"runs-{index}"
                run = self.save()
                with patch.object(cert, "capture_verification_identity", return_value=identity):
                    prefix = self.certify(run)
                root = self.runs / "solution-certificates"
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}
                with patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=AssertionError("SDK")):
                    self.assertEqual(cert.read_certified_roster(self.arc, self.runs, self.catalog,
                                                               expected_model_id=self.model), (prefix,))
                after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}
                self.assertEqual(before, after)
                with patch.object(cert, "_sdk_identity", return_value={"fixture-sdk": "b" * 64}):
                    with self.assertRaises(cert.SolutionCertificateError):
                        cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)

    def test_latest_deployed_profile_includes_shared_trace_verifier(self):
        from asterion.applications.prime.p7.legacy_verifier_profile import DEPLOYED_1D803298, DEPLOYED_3108995D

        for index, profile in enumerate((DEPLOYED_1D803298, DEPLOYED_3108995D), start=2):
            with self.subTest(profile=index):
                self.assertEqual(set(profile), set(cert._VERIFIERS) | {"trace.py"})
                expected = cert._digest({"game": cert.game_identity(self.arc, self.game),
                                         "sdk": cert._sdk_identity(), "verifier": profile,
                                         "format": cert._SCHEMA})
                self.assertEqual(cert.compatible_deployed_identities(self.arc, self.game)[index], expected)
