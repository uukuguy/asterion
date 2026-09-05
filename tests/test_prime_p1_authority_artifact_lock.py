"""Tests for the packaged Prime P1 authority artifact admission boundary."""

from __future__ import annotations

import unittest
from unittest import mock

from asterion.applications.prime_agent.operator.authority_resources import (
    PrimeP1AuthorityResourceError,
)
from asterion.applications.prime_agent.operator.authority_artifact_lock import (
    admit_authority_artifact_lock,
)


MODULE = "asterion.applications.prime_agent.operator.authority_artifact_lock"


class TestPrimeP1AuthorityArtifactLock(unittest.TestCase):
    def test_admits_only_the_exact_packaged_authority_artifact_set(self) -> None:
        resource = admit_authority_artifact_lock()
        self.addCleanup(resource.close)
        self.assertEqual(repr(resource), "AdmittedPrimeP1AuthorityArtifacts(redacted)")

    def test_rejects_a_digest_or_regular_file_change_without_leaking_the_path(
        self,
    ) -> None:
        with mock.patch(
            f"{MODULE}._read_verified_artifact", side_effect=ValueError("sentinel/path")
        ):
            with self.assertRaises(PrimeP1AuthorityResourceError) as caught:
                admit_authority_artifact_lock()
        self.assertEqual(str(caught.exception), "prime P1 authority resource is unavailable")
        self.assertNotIn("sentinel", str(caught.exception))
