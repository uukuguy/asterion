"""Native P2 package, application metadata, and selection tests."""

from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

from asterion.applications.discovery import select_application_provider_id
from asterion.applications.first_party_packages import (
    PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,
    builtin_capability_registrations,
)
from asterion.applications.prime import (
    create_prime_programmatic_long_context_provider,
)
from asterion.applications.provider import ApplicationProviderError
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = (
    ROOT / "src/asterion/applications/prime/assemblies/prime-programmatic-long-context.json"
)
PACKAGE = (
    ROOT
    / "src/asterion/capabilities/prime_programmatic_long_context_native/payload/capability-package.json"
)
CAPABILITY = (
    ROOT
    / "src/asterion/capabilities/prime_programmatic_long_context_native/payload/capabilities/prime-programmatic-long-context.json"
)
P2_HOST_CAPABILITIES = (
    "prime.ipython",
    "prime.p2-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)


class TestAsterionPrimeP2Provider(unittest.TestCase):
    def test_p2_package_is_explicitly_registered(self) -> None:
        source = BuiltinCapabilitySource(builtin_capability_registrations())
        candidates = tuple(source.discover_metadata())
        matching = tuple(
            candidate
            for candidate in candidates
            if candidate.package_ref
            == PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE
        )
        self.assertEqual(len(matching), 1)
        self.assertEqual(
            source.load_provider(matching[0]).package_ref, matching[0].package_ref
        )

    def test_p2_capability_payload_matches(self) -> None:
        text = CAPABILITY.read_text(encoding="utf-8")
        self.assertIn("prime.programmatic-long-context", text)
        self.assertIn("\"version\":\"1.0.0\"", text)
        self.assertIn(
            "application/vnd.asterion.prime.p2-native-receipt+json", text
        )

    def test_p2_package_payload_matches(self) -> None:
        text = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("prime-programmatic-long-context-native", text)
        self.assertIn("\"version\":\"1.0.0\"", text)

    def test_p2_assembly_has_required_host_capabilities(self) -> None:
        import json

        data = json.loads(ASSEMBLY.read_text(encoding="utf-8"))
        self.assertEqual(data["application_id"], "prime.programmatic-long-context")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["runtime_id"], "asterion.prime")
        self.assertEqual(tuple(data["host_capabilities"]), P2_HOST_CAPABILITIES)

    def test_p2_provider_factory_returns_self_provider(self) -> None:
        provider = create_prime_programmatic_long_context_provider()
        self.assertEqual(len(provider.applications), 1)
        record = provider.applications[0]
        self.assertEqual(record.application_id, "prime.programmatic-long-context")
        self.assertEqual(record.version, "1.0.0")
        self.assertEqual(record.runtime_ids, ("asterion.prime",))
        self.assertEqual(
            record.capability_packages,
            (PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,),
        )

    def test_p2_selector_is_omitted_from_public_index(self) -> None:
        """Task 4 of the Phase 5 plan — P2 returns to the index with its witness."""
        pyproject = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        index = pyproject["project"]["entry-points"]["asterion.application_index"]
        self.assertNotIn("prime.programmatic-long-context__1.0.0", index)

    def test_p2_selector_unmapped_until_witness(self) -> None:
        """Until P2 is published, resolution raises for the unmapped key."""
        with self.assertRaises(ApplicationProviderError):
            select_application_provider_id("prime.programmatic-long-context__1.0.0")


if __name__ == "__main__":
    unittest.main()