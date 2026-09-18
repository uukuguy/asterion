"""Native P4 package, application metadata, and self-provider tests.

The witness-gated publication in :func:`create_provider` (Phase 6, Task 17)
is intentionally NOT asserted here; P4 stays unpublished in the public
selector until ``make asterion-prime-p4-run`` exits 0.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from asterion.applications.first_party_packages import (
    PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,
    builtin_capability_registrations,
)
from asterion.applications.prime import (
    create_prime_long_session_continuity_provider,
    prime_long_session_continuity_application,
)
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = (
    ROOT / "src/asterion/applications/prime/assemblies/prime-long-session-continuity.json"
)
PACKAGE = (
    ROOT
    / "src/asterion/capabilities/prime_long_session_continuity_native/payload/capability-package.json"
)
CAPABILITY = (
    ROOT
    / "src/asterion/capabilities/prime_long_session_continuity_native/payload/capabilities/prime-long-session-continuity.json"
)
P4_HOST_CAPABILITIES = (
    "prime.continuity-store",
    "prime.p4-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)


class TestAsterionPrimeP4Provider(unittest.TestCase):
    def test_p4_package_is_explicitly_registered(self) -> None:
        source = BuiltinCapabilitySource(builtin_capability_registrations())
        candidates = tuple(source.discover_metadata())
        matching = tuple(
            candidate
            for candidate in candidates
            if candidate.package_ref
            == PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE
        )
        self.assertEqual(len(matching), 1)
        self.assertEqual(
            source.load_provider(matching[0]).package_ref, matching[0].package_ref
        )

    def test_p4_capability_payload_matches(self) -> None:
        text = CAPABILITY.read_text(encoding="utf-8")
        self.assertIn("prime.long-session-continuity", text)
        self.assertIn('"version":"1.0.0"', text)
        self.assertIn(
            "application/vnd.asterion.prime.p4-native-receipt+json", text
        )

    def test_p4_package_payload_matches(self) -> None:
        text = PACKAGE.read_text(encoding="utf-8")
        self.assertIn("prime-long-session-continuity-native", text)
        self.assertIn('"version":"1.0.0"', text)

    def test_p4_assembly_has_required_host_capabilities(self) -> None:
        data = json.loads(ASSEMBLY.read_text(encoding="utf-8"))
        self.assertEqual(data["application_id"], "prime.long-session-continuity")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["runtime_id"], "asterion.prime")
        self.assertEqual(tuple(data["host_capabilities"]), P4_HOST_CAPABILITIES)

    def test_p4_provider_factory_returns_self_provider(self) -> None:
        provider = create_prime_long_session_continuity_provider()
        self.assertEqual(len(provider.applications), 1)
        record = provider.applications[0]
        self.assertEqual(record.application_id, "prime.long-session-continuity")
        self.assertEqual(record.version, "1.0.0")
        self.assertEqual(record.runtime_ids, ("asterion.prime",))
        self.assertEqual(
            record.capability_packages,
            (PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,),
        )

    def test_p4_application_record_helper(self) -> None:
        record = prime_long_session_continuity_application()
        self.assertEqual(record.application_id, "prime.long-session-continuity")
        self.assertEqual(record.version, "1.0.0")

    def test_p4_is_published_to_public_selector(self) -> None:
        """Phase 6 Task 17: published together with its installed-route
        cross-generation continuity witness (sealed receipt
        ``6b5a173d16d1d1a5382456284a7bbde1b0516120f13c1e9e4572e5f367757a0d``
        from ``make asterion-prime-p4-run``).
        """
        import tomllib

        pyproject = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        index = pyproject["project"]["entry-points"]["asterion.application_index"]
        self.assertEqual(
            index["prime.long-session-continuity__1.0.0"],
            "asterion.applications.prime:create_provider",
        )


if __name__ == "__main__":
    unittest.main()