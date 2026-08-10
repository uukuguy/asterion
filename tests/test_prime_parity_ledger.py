from __future__ import annotations

import copy
import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.parity import (
    PARITY_LEDGER_FORMAT,
    ParityLedgerError,
    evaluate_parity_claim,
    validate_parity_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "prime-parity" / "v1"

EXPECTED_MANDATORY_BY_DOMAIN = {
    "ecosystem.capabilities": (
        "ecosystem.collision-diagnostics",
        "ecosystem.context-files",
        "ecosystem.custom-providers-models",
        "ecosystem.extension-state-commands",
        "ecosystem.extensions-lifecycle",
        "ecosystem.mcp",
        "ecosystem.packages",
        "ecosystem.prompt-templates",
        "ecosystem.skills",
        "ecosystem.tools",
    ),
    "harness.continual": (
        "harness.evidence-refinement",
        "harness.history-snapshots",
        "harness.memory-entries",
        "harness.prompt-entries",
        "harness.rollback",
        "harness.scope-isolation",
        "harness.skill-descriptions",
        "harness.subagent-specifications",
    ),
    "interfaces.operations": (
        "interface.acp",
        "interface.cli-interactive",
        "interface.export-share",
        "interface.headless-print",
        "interface.json-stream",
        "interface.rpc",
        "interface.sdk",
        "interface.tui-commands",
        "interface.tui-extension-ui",
        "operation.auth",
        "operation.controlled-update-restart",
        "operation.doctor",
        "operation.model-selection",
        "operation.settings-keybindings",
        "operation.telemetry-usage",
    ),
    "operation.long-running": (
        "operation.autonomous-quality",
        "operation.detach-attach-replay",
        "operation.goals",
        "operation.heartbeat-agent",
        "operation.heartbeat-user",
        "operation.orphan-cleanup",
        "operation.resident-workers",
        "operation.restart-update-recovery",
        "operation.schedule-once-cron",
        "operation.worker-residency-eviction",
    ),
    "rlm.programmatic": (
        "rlm.cancellation-teardown",
        "rlm.child-model",
        "rlm.environment",
        "rlm.generated-program",
        "rlm.messaging",
        "rlm.recovery",
        "rlm.recursion-depth",
        "rlm.registry-lifecycle",
        "rlm.usage-cost",
    ),
    "session.context": (
        "session.branch-summaries-labels",
        "session.compaction",
        "session.delivery",
        "session.fork-clone",
        "session.persistence-naming",
        "session.resume-delete",
        "session.rich-attachments",
        "session.tree-navigation",
        "session.usage-status",
    ),
}
EXPECTED_MANDATORY_FEATURE_IDS = tuple(
    sorted(
        feature_id
        for feature_ids in EXPECTED_MANDATORY_BY_DOMAIN.values()
        for feature_id in feature_ids
    )
)
EXPECTED_EXCLUDED_FEATURE_IDS = (
    "excluded.hidden-reasoning-identity",
    "excluded.tui-pixel-identity",
)
EXPECTED_IMPLEMENTED_PRIME_FEATURE_IDS = (
    "operation.detach-attach-replay",
    "operation.goals",
    "session.delivery",
)


def _fixture(name: str = "valid-ledger-minimal.json") -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _passing_ledger(*, boundary: str = "provider-free") -> dict[str, object]:
    value = _fixture()
    scenario = value["scenarios"]
    assert isinstance(scenario, list)
    assert isinstance(scenario[0], dict)
    scenario[0]["boundary"] = boundary
    feature = value["features"]
    assert isinstance(feature, list)
    assert isinstance(feature[0], dict)
    results = feature[0]["provider_results"]
    assert isinstance(results, list)
    assert isinstance(results[1], dict)
    results[1]["status"] = (
        "bounded-pass" if boundary == "bounded-provider" else "provider-free-pass"
    )
    results[1]["evidence_ids"] = ["evidence.session.persistence"]
    evidence_boundary = (
        "bounded-provider"
        if boundary == "bounded-provider"
        else boundary
    )
    value["evidence"] = [
        {
            "evidence_id": "evidence.session.persistence",
            "provider_id": "asterion.prime-gateway",
            "boundary": evidence_boundary,
            "status": "pass",
            "command_id": "prime-parity-session-persistence",
            "baseline_commit": "a18809e00ea30638584d87b3afea7285a9d7296c",
            "feature_ids": ["session.persistence-naming"],
            "scenario_ids": ["prime-parity.session.persistence-naming"],
        }
    ]
    return value


class _HostileMapping(dict[str, object]):
    def items(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("SENTINEL_SECRET")


class _HostileList(list[object]):
    def __iter__(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("SENTINEL_SECRET")


class TestPrimeParityLedger(unittest.TestCase):
    def test_format_identity_is_asterion_owned(self) -> None:
        self.assertEqual(PARITY_LEDGER_FORMAT, "asterion.parity-ledger/v1")

    def test_valid_ledger_is_canonical_and_recursively_immutable(self) -> None:
        source = _fixture()

        ledger = validate_parity_ledger(source)

        self.assertEqual(ledger["ledger_id"], "prime-agent-0.7.1")
        self.assertIsInstance(ledger["baseline"], Mapping)
        self.assertIsInstance(ledger["providers"], tuple)
        features = ledger["features"]
        self.assertIsInstance(features, tuple)
        assert isinstance(features, tuple)
        feature = features[0]
        self.assertIsInstance(feature, Mapping)
        assert isinstance(feature, Mapping)
        self.assertEqual(feature["feature_id"], "session.persistence-naming")
        prime_evidence = feature["prime_evidence"]
        self.assertIsInstance(prime_evidence, tuple)
        assert isinstance(prime_evidence, tuple)
        first_evidence = prime_evidence[0]
        assert isinstance(first_evidence, Mapping)
        self.assertIsInstance(first_evidence["anchors"], tuple)
        with self.assertRaises(TypeError):
            ledger["ledger_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            feature["description"] = "changed"  # type: ignore[index]
        source["ledger_id"] = "changed"
        self.assertEqual(ledger["ledger_id"], "prime-agent-0.7.1")

    def test_rejects_closed_secret_bearing_and_noncanonical_fixtures(self) -> None:
        for name in (
            "invalid-ledger-secret.json",
            "invalid-ledger-noncanonical.json",
        ):
            with self.subTest(name=name), self.assertRaises(ParityLedgerError):
                validate_parity_ledger(_fixture(name))

    def test_rejects_noncanonical_nested_arrays_and_references(self) -> None:
        cases: list[dict[str, object]] = []
        duplicate_anchor = _fixture()
        duplicate_anchor["features"][0]["prime_evidence"][0]["anchors"] = [  # type: ignore[index]
            "export class SessionManager",
            "export class SessionManager",
        ]
        cases.append(duplicate_anchor)
        missing_primary = _fixture()
        missing_primary["features"][0]["primary_scenario_id"] = "prime-parity.missing"  # type: ignore[index]
        cases.append(missing_primary)
        scenario_missing_feature = _fixture()
        scenario_missing_feature["scenarios"][0]["feature_ids"] = ["session.unknown"]  # type: ignore[index]
        cases.append(scenario_missing_feature)
        nondeterministic = _fixture()
        nondeterministic["scenarios"][0]["deterministic"] = False  # type: ignore[index]
        cases.append(nondeterministic)

        for value in cases:
            with self.subTest(value=value), self.assertRaises(ParityLedgerError):
                validate_parity_ledger(value)

    def test_primary_scenario_identity_is_derived_from_feature_identity(self) -> None:
        value = _fixture()
        mismatched_id = "prime-parity.session.resume-delete"
        value["features"][0]["primary_scenario_id"] = mismatched_id  # type: ignore[index]
        value["scenarios"][0]["scenario_id"] = mismatched_id  # type: ignore[index]

        with self.assertRaises(ParityLedgerError):
            validate_parity_ledger(value)

    def test_errors_never_render_fixture_values(self) -> None:
        value = _fixture()
        value["credentials"] = "SENTINEL_SECRET"

        with self.assertRaises(ParityLedgerError) as raised:
            validate_parity_ledger(value)

        rendered = str(raised.exception)
        self.assertNotIn("SENTINEL_SECRET", rendered)
        self.assertNotIn("credentials", rendered)

    def test_hostile_container_subclasses_are_rejected_without_invocation(self) -> None:
        hostile_root = _HostileMapping(_fixture())
        hostile_nested = _fixture()
        hostile_nested["providers"] = _HostileList(
            ["asterion.native", "asterion.prime-gateway"]
        )

        for name, value in (("root", hostile_root), ("nested", hostile_nested)):
            with self.subTest(name=name), self.assertRaises(
                ParityLedgerError
            ) as raised:
                validate_parity_ledger(value)
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_missing_and_implemented_results_block_the_claim(self) -> None:
        for status in ("missing", "implemented"):
            value = _fixture()
            value["features"][0]["provider_results"][1]["status"] = status  # type: ignore[index]

            report = evaluate_parity_claim(
                validate_parity_ledger(value),
                provider_id="asterion.prime-gateway",
            )

            with self.subTest(status=status):
                self.assertFalse(report.eligible)
                self.assertEqual(
                    report.blocking_feature_ids,
                    ("session.persistence-naming",),
                )
                self.assertEqual(report.passed_feature_ids, ())

    def test_provider_free_evidence_cannot_satisfy_bounded_scenario(self) -> None:
        value = _passing_ledger(boundary="bounded-provider")
        value["features"][0]["provider_results"][1]["status"] = "provider-free-pass"  # type: ignore[index]
        value["evidence"][0]["boundary"] = "provider-free"  # type: ignore[index]

        with self.assertRaises(ParityLedgerError):
            validate_parity_ledger(value)

    def test_passing_evidence_must_cover_provider_feature_scenario_and_baseline(self) -> None:
        mutations = (
            ("provider_id", "asterion.native"),
            ("feature_ids", ["session.unknown"]),
            ("scenario_ids", ["prime-parity.unknown"]),
            ("baseline_commit", "b" * 40),
            ("status", "failed"),
            ("status", "not-run"),
        )
        for field, replacement in mutations:
            value = _passing_ledger()
            value["evidence"][0][field] = replacement  # type: ignore[index]
            with self.subTest(field=field), self.assertRaises(ParityLedgerError):
                validate_parity_ledger(value)

    def test_passing_result_rejects_an_absent_evidence_identity(self) -> None:
        value = _passing_ledger()
        value["features"][0]["provider_results"][1]["evidence_ids"] = [  # type: ignore[index]
            "evidence.unknown"
        ]

        with self.assertRaises(ParityLedgerError):
            validate_parity_ledger(value)

    def test_valid_passing_evidence_makes_exact_provider_eligible(self) -> None:
        ledger = validate_parity_ledger(_passing_ledger())

        report = evaluate_parity_claim(
            ledger,
            provider_id="asterion.prime-gateway",
        )

        self.assertTrue(report.eligible)
        self.assertEqual(report.passed_feature_ids, ("session.persistence-naming",))
        self.assertEqual(report.blocking_feature_ids, ())
        self.assertEqual(report.excluded_feature_ids, ())
        self.assertEqual(report.reason_codes, ())

    def test_unknown_provider_fails_closed(self) -> None:
        report = evaluate_parity_claim(
            validate_parity_ledger(_passing_ledger()),
            provider_id="asterion.unknown",
        )

        self.assertFalse(report.eligible)
        self.assertEqual(
            report.blocking_feature_ids,
            ("session.persistence-naming",),
        )
        self.assertEqual(report.reason_codes, ("provider-unknown",))

    def test_exclusions_require_reason_and_cannot_have_provider_results(self) -> None:
        base = _fixture()
        excluded = {
            "feature_id": "excluded.tui-pixel-identity",
            "domain_id": "excluded.nonfunctional",
            "disposition": "excluded",
            "description": "Pixel identity is outside functional parity.",
            "prime_evidence": [
                {
                    "path": "packages/coding-agent/src/modes/interactive/interactive-mode.ts",
                    "anchors": ["export class InteractiveMode"],
                }
            ],
            "compatibility_impacts": [],
            "exclusion_reason_code": "nonfunctional-pixel-identity",
        }
        base["features"] = [excluded, *base["features"]]  # type: ignore[list-item]
        validated = validate_parity_ledger(base)
        report = evaluate_parity_claim(
            validated,
            provider_id="asterion.prime-gateway",
        )
        self.assertEqual(
            report.excluded_feature_ids,
            ("excluded.tui-pixel-identity",),
        )

        cases = []
        without_reason = copy.deepcopy(base)
        without_reason["features"][0].pop("exclusion_reason_code")  # type: ignore[index]
        cases.append(without_reason)
        with_results = copy.deepcopy(base)
        with_results["features"][0]["provider_results"] = []  # type: ignore[index]
        cases.append(with_results)
        unknown_exclusion = copy.deepcopy(base)
        unknown_exclusion["features"][0]["feature_id"] = "excluded.functional-gap"  # type: ignore[index]
        cases.append(unknown_exclusion)
        wrong_reason = copy.deepcopy(base)
        wrong_reason["features"][0]["exclusion_reason_code"] = "unapproved-reason"  # type: ignore[index]
        cases.append(wrong_reason)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ParityLedgerError):
                validate_parity_ledger(value)

    def test_ledger_cannot_claim_parity_from_exclusions_alone(self) -> None:
        value = _fixture()
        value["features"] = [
            {
                "feature_id": "excluded.tui-pixel-identity",
                "domain_id": "excluded.nonfunctional",
                "disposition": "excluded",
                "description": "Pixel identity is outside functional parity.",
                "prime_evidence": [
                    {
                        "path": "packages/coding-agent/src/modes/interactive/interactive-mode.ts",
                        "anchors": ["export class InteractiveMode"],
                    }
                ],
                "compatibility_impacts": [],
                "exclusion_reason_code": "nonfunctional-pixel-identity",
            }
        ]
        value["scenarios"] = []

        with self.assertRaises(ParityLedgerError):
            validate_parity_ledger(value)

    def test_exhaustive_prime_inventory_is_exact_closed_and_honest(self) -> None:
        source = _fixture("prime-agent-0.7.1.json")
        ledger = validate_parity_ledger(source)
        features = ledger["features"]
        scenarios = ledger["scenarios"]
        assert isinstance(features, tuple)
        assert isinstance(scenarios, tuple)
        feature_by_id = {
            str(feature["feature_id"]): feature
            for feature in features
            if isinstance(feature, Mapping)
        }
        mandatory = tuple(
            feature_id
            for feature_id, feature in feature_by_id.items()
            if feature["disposition"] == "mandatory"
        )
        excluded = tuple(
            feature_id
            for feature_id, feature in feature_by_id.items()
            if feature["disposition"] == "excluded"
        )

        self.assertEqual(len(feature_by_id), 63)
        self.assertEqual(mandatory, EXPECTED_MANDATORY_FEATURE_IDS)
        self.assertEqual(excluded, EXPECTED_EXCLUDED_FEATURE_IDS)
        self.assertEqual(len(scenarios), 61)
        self.assertEqual(
            tuple(str(scenario["scenario_id"]) for scenario in scenarios),
            tuple(f"prime-parity.{feature_id}" for feature_id in mandatory),
        )
        for domain_id, expected in EXPECTED_MANDATORY_BY_DOMAIN.items():
            with self.subTest(domain_id=domain_id):
                self.assertEqual(
                    tuple(
                        feature_id
                        for feature_id in mandatory
                        if feature_by_id[feature_id]["domain_id"] == domain_id
                    ),
                    expected,
                )

        implemented_prime: list[str] = []
        for feature_id in mandatory:
            feature = feature_by_id[feature_id]
            results = feature["provider_results"]
            assert isinstance(results, tuple)
            result_by_provider = {
                str(result["provider_id"]): result
                for result in results
                if isinstance(result, Mapping)
            }
            self.assertEqual(result_by_provider["asterion.native"]["status"], "missing")
            prime_status = result_by_provider["asterion.prime-gateway"]["status"]
            if prime_status == "implemented":
                implemented_prime.append(feature_id)
            else:
                self.assertEqual(prime_status, "missing")
        self.assertEqual(tuple(implemented_prime), EXPECTED_IMPLEMENTED_PRIME_FEATURE_IDS)

        index = json.loads(
            (FIXTURES / "feature-index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(index),
            {"format", "ledger_id", "feature_ids"},
        )
        self.assertEqual(index["format"], "asterion.parity-feature-index/v1")
        self.assertEqual(index["ledger_id"], "prime-agent-0.7.1")
        self.assertEqual(
            tuple(index["feature_ids"]),
            tuple(
                sorted(
                    (*EXPECTED_EXCLUDED_FEATURE_IDS, *EXPECTED_MANDATORY_FEATURE_IDS)
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
