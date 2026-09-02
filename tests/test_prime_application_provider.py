"""Installed Prime application discovery and provider-free preflight tests."""

from __future__ import annotations

from importlib import metadata
import unittest

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
    select_application_provider_id,
)
from asterion.applications.prime_agent.preflight import prime_preflight
from asterion.applications.prime_agent.provider import create_provider
from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerProfile,
)
from asterion.applications.prime_agent.source_lock import PrimeSourceLock


def _profile(**changes: object) -> PrimeRestrictedWorkerProfile:
    values: dict[str, object] = {
        "image_digest": "sha256:" + "a" * 64,
        "network_mode": "none",
        "workspace_mode": "disposable",
        "credential_mode": "absent",
        "max_runtime_seconds": 300,
        "max_output_bytes": 65536,
    }
    values.update(changes)
    return PrimeRestrictedWorkerProfile(**values)  # type: ignore[arg-type]


def _source_lock(**changes: object) -> PrimeSourceLock:
    values: dict[str, object] = {
        "commit": "b" * 40,
        "tree_sha256": "c" * 64,
        "package_lock_sha256": "d" * 64,
    }
    values.update(changes)
    return PrimeSourceLock(**values)  # type: ignore[arg-type]


class TestPrimeApplicationProvider(unittest.TestCase):
    def test_provider_declares_one_metadata_only_application(self) -> None:
        provider = create_provider()

        self.assertEqual(provider.provider_id, "prime-agent")
        self.assertEqual(
            [(item.application_id, item.version) for item in provider.applications],
            [("prime.capability-program", "1.0.0")],
        )

    def test_installed_entry_point_discovers_and_loads_prime_provider(self) -> None:
        entries = tuple(metadata.entry_points(group="asterion.applications"))

        self.assertIn(
            "prime-agent",
            [item.provider_id for item in list_application_providers(entry_points=entries)],
        )
        self.assertEqual(load_application_provider("prime-agent").provider_id, "prime-agent")
        self.assertEqual(
            select_application_provider_id("prime.capability-program@1.0.0"),
            "prime-agent",
        )

    def test_preflight_accepts_only_valid_injected_contracts(self) -> None:
        self.assertEqual(prime_preflight(_profile(), _source_lock()).status, "PASS")

    def test_preflight_returns_fixed_safe_failure_codes(self) -> None:
        cases = (
            (None, _source_lock(), "worker-unavailable"),
            (_profile(network_mode="host"), _source_lock(), "worker-invalid"),
            (_profile(), PrimeSourceLock("invalid", "c" * 64, "d" * 64), "source-invalid"),
        )

        for profile, source_lock, expected in cases:
            with self.subTest(expected=expected):
                result = prime_preflight(profile, source_lock)  # type: ignore[arg-type]
                self.assertEqual(result.status, expected)
                self.assertNotIn("sha256:", repr(result))


if __name__ == "__main__":
    unittest.main()
