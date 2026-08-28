from __future__ import annotations

import asyncio
from functools import cache
import json
import subprocess
import unittest
from pathlib import Path

from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.client_parity_testing import (
    PRIME_CLIENT_SCENARIO_IDS,
    PrimeClientParityError,
    build_prime_client_observations,
    register_prime_client_scenarios,
)


_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json"
)
_PROJECT = Path(__file__).resolve().parents[1]


@cache
def _real_receipt_json() -> tuple[str, ...]:
    return tuple(
        subprocess.run(
                (
                    "node",
                    str(
                        _PROJECT
                        / "tests/fixtures/prime_gateway/v1/real-prime-clients.mjs"
                    ),
                    "--package",
                    package,
                    "--resource-root",
                    str(_PROJECT / "packages/typescript/prime-gateway/resources"),
                    "--prime-root",
                    str(_PROJECT / "3th-party/prime-agent"),
                ),
                cwd=_PROJECT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        for package in ("core", "protocols", "interactive", "export-share")
    )


def _real_receipts() -> list[dict[str, object]]:
    return [json.loads(value) for value in _real_receipt_json()]


class TestPrimeClientParity(unittest.TestCase):
    def test_four_receipts_cover_exact_nine_without_provider_work(self) -> None:
        observations = build_prime_client_observations(_real_receipts())

        self.assertEqual(
            tuple(item.scenario_id for item in observations),
            PRIME_CLIENT_SCENARIO_IDS,
        )
        self.assertEqual(len(observations), 9)
        self.assertTrue(all(item.provider_operations == 0 for item in observations))
        self.assertTrue(all(item.credential_reads == 0 for item in observations))
        self.assertTrue(all(item.private_reads == 0 for item in observations))
        self.assertTrue(all(item.unauthorized_uploads == 0 for item in observations))

    def test_wrong_identity_count_or_extra_key_rejects_atomically(self) -> None:
        cases: list[list[dict[str, object]]] = []
        for index, key, value in (
            (0, "source_commit", "b" * 40),
            (1, "feature_count", 3),
            (2, "provider_operations", True),
            (3, "unauthorized_uploads", 1),
            (0, "extra", "value"),
            (1, "feature_ids", ["interface.rpc", "interface.acp"]),
            (2, "scenario_evidence", []),
            (3, "stream_digest", "SENTINEL_PRIVATE_VALUE"),
        ):
            receipts = _real_receipts()
            receipts[index][key] = value
            cases.append(receipts)

        for receipts in cases:
            with self.subTest(receipts=receipts), self.assertRaises(
                PrimeClientParityError
            ):
                build_prime_client_observations(receipts)

    def test_registers_exact_provider_free_runners(self) -> None:
        registry = ParityScenarioRegistry(
            json.loads(_FIXTURE.read_text(encoding="utf-8")),
            provider_id="asterion.prime-gateway",
        )
        register_prime_client_scenarios(
            registry,
            build_prime_client_observations(_real_receipts()),
            provider_factory=lambda: object(),
        )

        report = asyncio.run(registry.run(PRIME_CLIENT_SCENARIO_IDS))

        self.assertEqual(report.blocking_scenario_ids, ())
        self.assertEqual(report.passed_scenario_ids, PRIME_CLIENT_SCENARIO_IDS)

    def test_registration_is_atomic_on_later_sdk_boundary_mismatch(self) -> None:
        ledger = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        for scenario in ledger["scenarios"]:
            if scenario["scenario_id"] == "prime-parity.interface.sdk":
                scenario["boundary"] = "provider-free"
        registry = ParityScenarioRegistry(
            ledger,
            provider_id="asterion.prime-gateway",
        )

        with self.assertRaises(PrimeClientParityError):
            register_prime_client_scenarios(
                registry,
                build_prime_client_observations(_real_receipts()),
                provider_factory=lambda: object(),
            )

        self.assertEqual(registry.registered_scenario_ids, ())
