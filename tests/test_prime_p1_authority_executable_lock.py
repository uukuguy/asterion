"""Boundary tests for the promoted Prime P1 authority executable catalog."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_resources import (
    PrimeP1AuthorityResourceError,
)


class TestPrimeP1AuthorityExecutableLock(unittest.TestCase):
    def test_empty_production_catalog_fails_closed(self) -> None:
        from asterion.applications.prime_agent.operator.authority_executable_lock import (
            ImagePlatformDescriptor,
            resolve_promoted_authority_executable_lock,
        )

        with self.assertRaises(PrimeP1AuthorityResourceError):
            resolve_promoted_authority_executable_lock(
                ImagePlatformDescriptor("linux", "arm64", None)
            )

    def test_exact_injected_linux_target_is_selected_without_host_inspection(self) -> None:
        import asterion.applications.prime_agent.operator.authority_executable_lock as module

        target = module.ImagePlatformDescriptor("linux", "arm64", None)
        lock = module.AuthorityExecutableLock(target, "elf", 1, "a" * 64)
        with patch.object(module, "PRIME_P1_PROMOTED_AUTHORITY_EXECUTABLE_CATALOG", (lock,)):
            self.assertIs(module.resolve_promoted_authority_executable_lock(target), lock)

    def test_malformed_lock_records_are_rejected(self) -> None:
        import asterion.applications.prime_agent.operator.authority_executable_lock as module

        target = module.ImagePlatformDescriptor("linux", "arm64", None)
        invalid = (
            module.AuthorityExecutableLock(target, "ELF", 1, "a" * 64),
            module.AuthorityExecutableLock(target, "elf", 0, "a" * 64),
            module.AuthorityExecutableLock(target, "elf", 1, "A" * 64),
        )
        for lock in invalid:
            with self.subTest(lock=lock):
                with patch.object(module, "PRIME_P1_PROMOTED_AUTHORITY_EXECUTABLE_CATALOG", (lock,)):
                    with self.assertRaises(PrimeP1AuthorityResourceError):
                        module.resolve_promoted_authority_executable_lock(target)

    def test_admitted_identity_contributes_only_selected_digest_until_closed(self) -> None:
        import asterion.applications.prime_agent.operator.authority_executable_lock as module

        admitted = module.AdmittedPrimeP1AuthorityExecutable(
            module.AuthorityExecutableLock(
                module.ImagePlatformDescriptor("linux", "arm64", None),
                "elf",
                1,
                "a" * 64,
            ),
            _token=module._TOKEN,
        )
        self.assertEqual(
            admitted._resource_set_contribution(),
            b"authority-executable\0"
            + (6).to_bytes(4, "big")
            + b"sha256"
            + (32).to_bytes(8, "big")
            + bytes.fromhex("a" * 64),
        )
        admitted.close()
        admitted.close()
        with self.assertRaises(ValueError):
            admitted._resource_set_contribution()
