from __future__ import annotations

import copy
import unittest
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.operational_parity_testing import (
    PRIME_OPERATION_COMMAND_ID,
    PRIME_OPERATION_FEATURES,
    PrimeOperationalParityError,
    build_prime_operational_observations,
    register_prime_operational_scenarios,
)
from tests.test_prime_operational_auth import (
    _LEDGER_ASSERTIONS,
    _real_prime_receipt,
    _zero_effect_counts,
)
from tools.check_prime_parity import load_prime_parity_ledger


_EXPECTED_FEATURES = MappingProxyType(
    {
        "auth": ("operation.auth",),
        "model-selection": ("operation.model-selection",),
        "settings-keybindings": ("operation.settings-keybindings",),
        "telemetry-usage": ("operation.telemetry-usage",),
        "doctor": ("operation.doctor",),
        "controlled-update-restart": (
            "operation.controlled-update-restart",
        ),
    }
)


def _valid_receipts() -> Mapping[str, Mapping[str, object]]:
    return MappingProxyType(
        {package: _real_prime_receipt(package) for package in PRIME_OPERATION_FEATURES}
    )


def _fresh_receipts() -> Mapping[str, Mapping[str, object]]:
    cache_clear = getattr(_real_prime_receipt, "cache_clear")
    cache_clear()
    return _valid_receipts()


def _mutated_receipts(
    package: str, updates: Mapping[str, object]
) -> Mapping[str, Mapping[str, object]]:
    receipts = {
        name: copy.deepcopy(dict(receipt))
        for name, receipt in _valid_receipts().items()
    }
    receipts[package].update(updates)
    return MappingProxyType(receipts)


def _mutated_nested_receipts(
    package: str,
    key: str,
    updates: Mapping[str, object] | object,
) -> Mapping[str, Mapping[str, object]]:
    receipts = {
        name: copy.deepcopy(dict(receipt))
        for name, receipt in _valid_receipts().items()
    }
    receipts[package][key] = updates
    return MappingProxyType(receipts)


class TestPrimeOperationalParity(unittest.TestCase):
    def test_feature_mapping_is_closed_and_operation_only(self) -> None:
        self.assertEqual(PRIME_OPERATION_FEATURES, _EXPECTED_FEATURES)
        with self.assertRaises(TypeError):
            PRIME_OPERATION_FEATURES["auth"] = ("operation.changed",)  # type: ignore[index]

    def test_atomic_reducer_rejects_missing_extra_or_dirty_receipts(self) -> None:
        valid = _valid_receipts()
        five = MappingProxyType(
            {name: receipt for name, receipt in valid.items() if name != "doctor"}
        )
        seven = MappingProxyType({**dict(valid), "extra": valid["auth"]})
        dirty_effects = dict(_zero_effect_counts())
        dirty_effects["network_requests"] = 1
        cases = (
            five,
            seven,
            _mutated_nested_receipts("auth", "effect_counts", dirty_effects),
            _mutated_receipts("doctor", {"source_commit": "0" * 40}),
            _mutated_receipts("doctor", {"built_anchor_digests": []}),
        )
        for receipts in cases:
            with self.subTest(keys=tuple(receipts)), self.assertRaises(
                PrimeOperationalParityError
            ):
                build_prime_operational_observations(receipts)

    def test_reducer_rejects_noncanonical_or_incomplete_receipt_evidence(self) -> None:
        valid = _valid_receipts()
        dirty_assertions = list(_LEDGER_ASSERTIONS)
        dirty_assertions.remove("identity-stable")
        cases = (
            _mutated_nested_receipts(
                "auth",
                "feature_ids",
                ["operation.auth", "operation.telemetry-usage"],
            ),
            _mutated_nested_receipts("auth", "assertion_ids", dirty_assertions),
            _mutated_nested_receipts("auth", "fault_ids", []),
            _mutated_receipts("auth", {"status": "uncertain"}),
            _mutated_receipts("auth", {"redaction_status": "failed"}),
            _mutated_receipts("auth", {"node_runtime": "v21.7.0"}),
            _mutated_nested_receipts(
                "controlled-update-restart",
                "scenario_counts",
                {
                    **cast(
                        Mapping[str, object],
                        valid["controlled-update-restart"]["scenario_counts"],
                    ),
                    "reconcile_calls": 0,
                },
            ),
            _mutated_nested_receipts(
                "controlled-update-restart",
                "restart",
                [
                    "artifact-prime-1",
                    "prime-daemon-1",
                    "asterion.agent-runtime/v1",
                    "checkpoint-prime-1",
                    "a" * 64,
                    "uncertain",
                ],
            ),
            _mutated_receipts("settings-keybindings", {"SENTINEL_BODY": "leaked"}),
        )
        for receipts in cases:
            with self.subTest(receipts=repr(receipts)[:80]), self.assertRaises(
                PrimeOperationalParityError
            ):
                build_prime_operational_observations(receipts)

    def test_reducer_promotes_exactly_six_prime_gateway_observations(self) -> None:
        observations = build_prime_operational_observations(_valid_receipts())

        self.assertEqual(len(observations), 6)
        self.assertEqual(
            tuple(observation.scenario_id for observation in observations),
            tuple(
                sorted(
                    f"prime-parity.{feature_ids[0]}"
                    for feature_ids in PRIME_OPERATION_FEATURES.values()
                )
            ),
        )
        for observation in observations:
            with self.subTest(scenario_id=observation.scenario_id):
                self.assertEqual(observation.status, "PASS")
                self.assertEqual(observation.provider_operations, 0)
                self.assertEqual(observation.effect_counts, _zero_effect_counts())
                self.assertNotIn("SENTINEL_", repr(observation))

    def test_real_receipt_regeneration_matches_committed_ledger_evidence(self) -> None:
        ledger = load_prime_parity_ledger()
        evidence_records = cast(Sequence[Mapping[str, object]], ledger["evidence"])
        features = cast(Sequence[Mapping[str, object]], ledger["features"])
        evidence_by_id = {
            str(evidence["evidence_id"]): evidence
            for evidence in evidence_records
            if evidence["command_id"] == PRIME_OPERATION_COMMAND_ID
        }
        prime_result_by_feature = {
            str(feature["feature_id"]): result
            for feature in features
            if "provider_results" in feature
            for result in cast(Sequence[Mapping[str, object]], feature["provider_results"])
            if result["provider_id"] == "asterion.prime-gateway"
            and result["status"] == "provider-free-pass"
        }

        first = build_prime_operational_observations(_fresh_receipts())
        second = build_prime_operational_observations(_fresh_receipts())

        self.assertEqual(
            tuple(observation.evidence_id for observation in first),
            tuple(observation.evidence_id for observation in second),
        )
        self.assertEqual(
            tuple(observation.serialized_observations for observation in first),
            tuple(observation.serialized_observations for observation in second),
        )
        for observation in first:
            with self.subTest(feature_id=observation.feature_id):
                expected_evidence = {
                    "evidence_id": observation.evidence_id,
                    "provider_id": "asterion.prime-gateway",
                    "boundary": "real-prime-provider-free",
                    "status": "pass",
                    "command_id": PRIME_OPERATION_COMMAND_ID,
                    "baseline_commit": observation.source_commit,
                    "feature_ids": (observation.feature_id,),
                    "scenario_ids": (observation.scenario_id,),
                }
                self.assertEqual(evidence_by_id[observation.evidence_id], expected_evidence)
                self.assertEqual(
                    prime_result_by_feature[observation.feature_id]["evidence_ids"],
                    (observation.evidence_id,),
                )

    def test_registration_is_atomic_and_ledger_bound(self) -> None:
        ledger = load_prime_parity_ledger()
        registry = ParityScenarioRegistry(
            ledger, provider_id="asterion.prime-gateway"
        )
        observations = build_prime_operational_observations(_valid_receipts())

        register_prime_operational_scenarios(
            registry, observations, provider_factory=object
        )

        self.assertEqual(
            tuple(
                scenario_id
                for scenario_id in registry.registered_scenario_ids
                if scenario_id.startswith("prime-parity.operation.")
            ),
            tuple(observation.scenario_id for observation in observations),
        )
        with self.assertRaises(PrimeOperationalParityError):
            register_prime_operational_scenarios(
                registry, observations, provider_factory=object
            )


if __name__ == "__main__":
    unittest.main()
