"""Explicit deployed verifier compatibility never changes certificate bytes."""

import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import solution_certificates as cert
from tests import test_prime_p7_solution_certificates as fixtures
from tests import test_prime_p7_solutions as replay_fixtures


class TestDeployedCertificates(unittest.TestCase):
    setUp = fixtures.TestP7SolutionCertificates.setUp
    save = fixtures.TestP7SolutionCertificates.save
    certify = fixtures.TestP7SolutionCertificates.certify

    def test_frozen_deployed_identity_reads_original_certificate_without_reissuing(self):
        reader = getattr(cert, "compatible_deployed_identities", None)
        self.assertTrue(callable(reader), "exact deployed verifier profiles are required")
        identities = reader(self.arc, self.game)
        self.assertEqual(len(identities), 6)
        self.assertEqual(identities[0], cert.compatible_legacy_identity(self.arc, self.game))
        for index, identity in enumerate(identities):
            with self.subTest(profile=index):
                self.runs = self.root / f"runs-{index}"
                run = self.save()
                with patch.object(cert, "capture_verification_identity", return_value=identity):
                    prefix = self.certify(run)
                root = self.runs / "solution-certificates"
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}
                with (patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=AssertionError("SDK")),
                      patch.object(cert, "replay_arc_run", side_effect=AssertionError("SDK"))):
                    self.assertEqual(cert.read_certified_roster(self.arc, self.runs, self.catalog,
                                                               expected_model_id=self.model), (prefix,))
                after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}
                self.assertEqual(before, after)
                with patch.object(cert, "_sdk_identity", return_value={"fixture-sdk": "b" * 64}):
                    with self.assertRaises(cert.SolutionCertificateError):
                        cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)
                with patch.object(cert, "game_identity", return_value={"changed-game": "c" * 64}):
                    with self.assertRaises(cert.SolutionCertificateError):
                        cert.read_certified_roster(self.arc, self.runs, self.catalog, expected_model_id=self.model)

    def test_0d_and_2a_profile_is_exact_and_cannot_publish_a_new_save(self):
        from asterion.applications.prime.p7 import legacy_verifier_profile, solutions

        profile = getattr(legacy_verifier_profile, "DEPLOYED_0D8F52BC", None)
        self.assertIsNotNone(profile, "the exact deployed 0d/2a profile is required")
        self.assertEqual(set(profile), set(cert._VERIFIERS) | {"trace.py"})
        # Independently generated from all 16 exact 0d git blobs; 2a is identical.
        self.assertEqual(cert._digest(profile),
                         "31e3281517342161f08a5b0fdadb97a608b00c74fdad42e0ea7fc213c15e76d8")
        old_identity = cert._digest({"game": cert.game_identity(self.arc, self.game),
                                     "sdk": cert._sdk_identity(), "verifier": profile,
                                     "format": cert._SCHEMA})
        self.assertEqual(cert.compatible_deployed_identities(self.arc, self.game)[4], old_identity)
        self.assertNotEqual(cert.capture_verification_identity(self.arc, self.game), old_identity)
        run = self.save()
        prefix, receipt, game = solutions._read_one(
            self.arc, run, self.game, 0, None, self.model, strict_model=True)
        with patch.object(cert, "capture_verification_identity", return_value=old_identity):
            _, witness = cert.verify_for_save(
                self.arc, game, prefix.transitions, receipt, prefix.observations,
                replay_fixtures._Engine)
        before = {str(path.relative_to(run)): path.read_bytes()
                  for path in run.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(ValueError, "witness stale"):
            cert.publish_verified_save(self.arc, run, witness, expected_model_id=self.model)
        self.assertFalse((self.runs / "solution-certificates").exists())
        self.assertEqual(before, {str(path.relative_to(run)): path.read_bytes()
                                 for path in run.rglob("*") if path.is_file()})

    def test_latest_deployed_profile_includes_shared_trace_verifier(self):
        from asterion.applications.prime.p7.legacy_verifier_profile import DEPLOYED_1D803298, DEPLOYED_3108995D

        for index, profile in enumerate((DEPLOYED_1D803298, DEPLOYED_3108995D), start=2):
            with self.subTest(profile=index):
                self.assertEqual(set(profile), set(cert._VERIFIERS) | {"trace.py"})
                expected = cert._digest({"game": cert.game_identity(self.arc, self.game),
                                         "sdk": cert._sdk_identity(), "verifier": profile,
                                         "format": cert._SCHEMA})
                self.assertEqual(cert.compatible_deployed_identities(self.arc, self.game)[index], expected)

    def test_b5_profile_is_exact_and_cannot_issue_new_witnesses(self):
        from asterion.applications.prime.p7 import legacy_verifier_profile, solutions

        profile = getattr(legacy_verifier_profile, "DEPLOYED_B5C24693", None)
        self.assertIsNotNone(profile, "the exact deployed d406/b5 profile is required")
        self.assertEqual(set(profile), set(cert._VERIFIERS) | {"trace.py"})
        # Computed from the immutable b5 worktree and independently matched
        # against the same commit's git blobs, including its profile file.
        self.assertEqual(cert._digest(profile),
                         "aca6b7a3f74038f3e424049bacfb9ec2fe4172f38e725b033b77d98456abc45a")
        identity = cert._digest({"game": cert.game_identity(self.arc, self.game),
                                "sdk": cert._sdk_identity(), "verifier": profile,
                                "format": cert._SCHEMA})
        self.assertEqual(cert.compatible_deployed_identities(self.arc, self.game)[5], identity)
        run = self.save()
        prefix, receipt, game = solutions._read_one(
            self.arc, run, self.game, 0, None, self.model, strict_model=True)
        with patch.object(cert, "capture_verification_identity", return_value=identity):
            _, witness = cert.verify_for_save(self.arc, game, prefix.transitions, receipt,
                                              prefix.observations, replay_fixtures._Engine)
        with self.assertRaisesRegex(ValueError, "witness stale"):
            cert.publish_verified_save(self.arc, run, witness, expected_model_id=self.model)
        self.assertFalse((self.runs / "solution-certificates").exists())
