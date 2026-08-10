from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from asterion.control.parity import validate_parity_ledger
from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
    ParityScenarioResult,
    ParityScenarioRunner,
)
from asterion.control.providers.prime.parity_testing import (
    PHASE1_PRIME_SCENARIO_IDS,
    PROVEN_PHASE1_PARITY_SCENARIO_IDS,
    register_proven_phase1_prime_subset,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime-parity"
    / "v1"
    / "prime-agent-0.7.1.json"
)
PROVIDER_ID = "asterion.prime-gateway"
SCENARIO_ID = "prime-parity.session.delivery"
FEATURE_IDS = ("session.delivery",)
BOUNDARY = "real-prime-provider-free"


def _ledger():
    return validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8")))


class _Clock:
    def __init__(self, *, deterministic: bool = True) -> None:
        self.deterministic = deterministic

    def now_ms(self) -> int:
        return 1_786_291_200_000


class _PrivateFixtureStore:
    def __init__(self) -> None:
        self.model_credential_reads = 0

    def read_model_credential(self) -> str:
        self.model_credential_reads += 1
        return "SENTINEL_SECRET"


class _FaultInjector:
    deterministic = True

    def inject(self, fault_id: str) -> None:
        del fault_id


@dataclass(frozen=True)
class _Phase1Result:
    scenario_id: str
    evidence_id: str
    status: str = "PASS"
    outcome: str = "proven-effect-succeeded"
    provider_operations: int = 0
    pathlight_control_events: tuple[str, ...] = ()
    pathlight_gaps: tuple[str, ...] = ()
    serialized_observations: str = "public-safe"


def _phase1_results() -> tuple[_Phase1Result, ...]:
    events = {
        "prime-loop-application": (
            "goal.updated",
            "session.completed",
            "session.created",
        ),
        "prime-loop-detach-attach": (
            "session.created",
            "session.recovery-required",
            "session.running",
        ),
    }
    return tuple(
        _Phase1Result(
            scenario_id=scenario_id,
            evidence_id="evidence.phase1."
            + hashlib.sha256(f"public-safe-{scenario_id}".encode()).hexdigest(),
            pathlight_control_events=events.get(scenario_id, ()),
            serialized_observations=f"public-safe-{scenario_id}",
        )
        for scenario_id in PHASE1_PRIME_SCENARIO_IDS
    )


async def _passing_executor(
    provider_factory, clock, private_fixture_store, fault_injector
) -> ParityScenarioResult:
    provider_factory()
    clock.now_ms()
    fault_injector.inject("none")
    self_store = private_fixture_store
    assert isinstance(self_store, _PrivateFixtureStore)
    return ParityScenarioResult(
        scenario_id=SCENARIO_ID,
        provider_id=PROVIDER_ID,
        status="pass",
        evidence_id="evidence.session-delivery",
        reason_code="verified",
    )


def _runner(
    *,
    scenario_id: str = SCENARIO_ID,
    provider_id: str = PROVIDER_ID,
    boundary: str = BOUNDARY,
    feature_ids: tuple[str, ...] = FEATURE_IDS,
    clock: _Clock | None = None,
    private_fixture_store: _PrivateFixtureStore | None = None,
    executor=_passing_executor,
) -> ParityScenarioRunner:
    return ParityScenarioRunner(
        scenario_id=scenario_id,
        provider_id=provider_id,
        boundary=boundary,
        feature_ids=feature_ids,
        provider_factory=lambda: object(),
        clock=clock or _Clock(),
        private_fixture_store=private_fixture_store or _PrivateFixtureStore(),
        fault_injector=_FaultInjector(),
        executor=executor,
    )


class TestPrimeParityConformance(unittest.TestCase):
    def test_registry_keys_are_exactly_the_ledger_scenarios(self) -> None:
        ledger = _ledger()
        scenarios = ledger["scenarios"]
        assert isinstance(scenarios, tuple)

        registry = ParityScenarioRegistry(ledger, provider_id=PROVIDER_ID)

        self.assertEqual(
            registry.scenario_ids,
            tuple(str(scenario["scenario_id"]) for scenario in scenarios),
        )
        self.assertEqual(len(registry.scenario_ids), 61)
        self.assertEqual(registry.registered_scenario_ids, ())

    def test_missing_implementations_are_results_and_never_skipped_passes(
        self,
    ) -> None:
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)

        report = asyncio.run(registry.run((SCENARIO_ID,)))

        self.assertEqual(report.provider_id, PROVIDER_ID)
        self.assertEqual(len(report.results), 1)
        result = report.results[0]
        self.assertEqual(result.status, "missing")
        self.assertIsNone(result.evidence_id)
        self.assertEqual(result.reason_code, "scenario-unimplemented")
        self.assertEqual(report.passed_scenario_ids, ())
        self.assertEqual(report.blocking_scenario_ids, (SCENARIO_ID,))

    def test_registered_runner_produces_only_its_exact_result(self) -> None:
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
        registry.register(SCENARIO_ID, _runner())

        report = asyncio.run(registry.run((SCENARIO_ID,)))

        self.assertEqual(registry.registered_scenario_ids, (SCENARIO_ID,))
        self.assertEqual(report.passed_scenario_ids, (SCENARIO_ID,))
        self.assertEqual(report.blocking_scenario_ids, ())
        self.assertEqual(report.results[0].evidence_id, "evidence.session-delivery")

    def test_registration_rejects_unknown_duplicate_and_contract_mismatch(
        self,
    ) -> None:
        cases = (
            ("unknown", "prime-parity.session.unknown", _runner()),
            (
                "identity",
                SCENARIO_ID,
                _runner(scenario_id="prime-parity.operation.goals"),
            ),
            ("provider", SCENARIO_ID, _runner(provider_id="asterion.native")),
            ("boundary", SCENARIO_ID, _runner(boundary="bounded-provider")),
            (
                "coverage",
                SCENARIO_ID,
                _runner(feature_ids=("operation.goals",)),
            ),
            ("clock", SCENARIO_ID, _runner(clock=_Clock(deterministic=False))),
        )
        for name, scenario_id, runner in cases:
            registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
            with self.subTest(name=name), self.assertRaises(
                ParityScenarioRegistryError
            ):
                registry.register(scenario_id, runner)

        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
        registry.register(SCENARIO_ID, _runner())
        with self.assertRaises(ParityScenarioRegistryError):
            registry.register(SCENARIO_ID, _runner())

    def test_provider_free_registration_rejects_prior_model_credential_access(
        self,
    ) -> None:
        private_store = _PrivateFixtureStore()
        self.assertEqual(private_store.read_model_credential(), "SENTINEL_SECRET")
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)

        with self.assertRaises(ParityScenarioRegistryError) as raised:
            registry.register(
                SCENARIO_ID,
                _runner(private_fixture_store=private_store),
            )

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_provider_free_runtime_credential_access_overrides_fake_pass(self) -> None:
        private_store = _PrivateFixtureStore()

        async def credential_executor(
            provider_factory, clock, private_fixture_store, fault_injector
        ) -> ParityScenarioResult:
            del provider_factory, clock, fault_injector
            self.assertEqual(
                private_fixture_store.read_model_credential(), "SENTINEL_SECRET"
            )
            return ParityScenarioResult(
                scenario_id=SCENARIO_ID,
                provider_id=PROVIDER_ID,
                status="pass",
                evidence_id="evidence.fake-pass",
                reason_code="verified",
            )

        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
        registry.register(
            SCENARIO_ID,
            _runner(
                private_fixture_store=private_store,
                executor=credential_executor,
            ),
        )

        report = asyncio.run(registry.run((SCENARIO_ID,)))

        self.assertEqual(report.results[0].status, "failed")
        self.assertIsNone(report.results[0].evidence_id)
        self.assertEqual(
            report.results[0].reason_code,
            "provider-credential-access-forbidden",
        )
        self.assertNotIn("SENTINEL_SECRET", repr(report))

    def test_runner_failure_and_invalid_result_are_fixed_redacted_failures(
        self,
    ) -> None:
        async def raising_executor(*resources) -> ParityScenarioResult:
            del resources
            raise RuntimeError("SENTINEL_SECRET")

        async def mismatched_executor(*resources) -> ParityScenarioResult:
            del resources
            return ParityScenarioResult(
                scenario_id="prime-parity.operation.goals",
                provider_id=PROVIDER_ID,
                status="pass",
                evidence_id="evidence.invalid",
                reason_code="verified",
            )

        for name, executor, expected_reason in (
            ("raises", raising_executor, "scenario-execution-failed"),
            ("mismatch", mismatched_executor, "scenario-result-invalid"),
        ):
            registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
            registry.register(SCENARIO_ID, _runner(executor=executor))
            report = asyncio.run(registry.run((SCENARIO_ID,)))
            with self.subTest(name=name):
                self.assertEqual(report.results[0].status, "failed")
                self.assertEqual(report.results[0].reason_code, expected_reason)
                self.assertNotIn("SENTINEL_SECRET", repr(report))

    def test_phase1_adapter_registers_only_full_primary_scenario_coverage(
        self,
    ) -> None:
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)

        register_proven_phase1_prime_subset(
            registry,
            _phase1_results(),
            provider_factory=lambda: object(),
        )
        report = asyncio.run(
            registry.run(PROVEN_PHASE1_PARITY_SCENARIO_IDS)
        )

        self.assertEqual(
            registry.registered_scenario_ids,
            PROVEN_PHASE1_PARITY_SCENARIO_IDS,
        )
        self.assertEqual(
            report.passed_scenario_ids,
            PROVEN_PHASE1_PARITY_SCENARIO_IDS,
        )
        self.assertNotIn("prime-parity.rlm.messaging", registry.registered_scenario_ids)
        self.assertNotIn(
            "prime-parity.rlm.cancellation-teardown",
            registry.registered_scenario_ids,
        )

    def test_phase1_adapter_is_atomic_and_rejects_weaker_evidence(self) -> None:
        mutations = []
        base = _phase1_results()
        mutations.append(base[:-1])
        mutations.append(
            (
                replace(base[0], provider_operations=1),
                *base[1:],
            )
        )
        mutations.append(
            (
                replace(base[0], serialized_observations="SENTINEL_TOKEN"),
                *base[1:],
            )
        )
        mutations.append(
            (
                replace(base[0], evidence_id="evidence.phase1.forged"),
                *base[1:],
            )
        )
        detach_index = PHASE1_PRIME_SCENARIO_IDS.index("prime-loop-detach-attach")
        mutations.append(
            tuple(
                replace(item, pathlight_control_events=())
                if index == detach_index
                else item
                for index, item in enumerate(base)
            )
        )

        for results in mutations:
            registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
            with self.subTest(size=len(results)), self.assertRaises(
                ParityScenarioRegistryError
            ):
                register_proven_phase1_prime_subset(
                    registry,
                    results,
                    provider_factory=lambda: object(),
                )
            self.assertEqual(registry.registered_scenario_ids, ())


if __name__ == "__main__":
    unittest.main()
