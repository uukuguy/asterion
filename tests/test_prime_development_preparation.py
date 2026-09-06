from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asterion.applications.prime_agent.operator import (
    development_preparation as subject,
)


class TestPrimeDevelopmentPreparation(unittest.TestCase):
    def test_public_error_is_fixed(self) -> None:
        self.assertEqual(
            str(subject.PrimeDevelopmentPreparationError("private")),
            "Prime development preparation is unavailable",
        )

    def test_rejects_invalid_scenarios_without_io(self) -> None:
        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject.prepare_prime_development(Path.cwd(), ("p8",))

    def test_packaged_seccomp_has_locked_canonical_digest(self) -> None:
        lock = subject._lock()
        self.assertEqual(
            sha256(subject._bytes("prime-development-seccomp.json")).hexdigest(),
            lock["seccomp"]["canonical_sha256"],
        )

    def test_paths_are_private_and_canonical(self) -> None:
        with TemporaryDirectory() as temp:
            root = subject._root(Path(temp))
            self.assertEqual(
                root, Path(temp).resolve() / ".asterion-private" / "prime-development"
            )

    def test_production_catalogs_remain_empty(self) -> None:
        from asterion.applications.prime_agent.operator.image_input_lock import (
            PRIME_IPYTHON_IMAGE_INPUT_CATALOG,
        )
        from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
            PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG,
        )

        self.assertEqual(PRIME_IPYTHON_IMAGE_INPUT_CATALOG.locks, ())
        self.assertEqual(PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG.locks, ())
