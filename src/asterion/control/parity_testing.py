"""Provider-neutral registry for deterministic parity scenario implementations."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from asterion.control.parity import ParityLedgerError, validate_parity_ledger


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_PROVIDER_FREE_BOUNDARIES = frozenset(
    {"provider-free", "real-prime-provider-free"}
)
_RUNNER_STATUSES = frozenset({"pass", "failed", "external-limited"})


class ParityScenarioRegistryError(RuntimeError):
    """Raised with fixed messages when a scenario contract fails closed."""


class ParityClock(Protocol):
    @property
    def deterministic(self) -> bool:
        """Report whether time is fully controlled by the harness."""
        ...

    def now_ms(self) -> int:
        """Return deterministic scenario time in milliseconds."""
        ...


class ParityPrivateFixtureStore(Protocol):
    @property
    def model_credential_reads(self) -> int:
        """Return the monotonic count of model-credential access attempts."""
        ...


class ParityFaultInjector(Protocol):
    @property
    def deterministic(self) -> bool:
        """Report whether all injected faults are harness-controlled."""
        ...

    def inject(self, fault_id: str) -> None:
        """Inject one declared deterministic fault."""
        ...


ParityProviderFactory = Callable[[], object]


@dataclass(frozen=True)
class ParityScenarioResult:
    scenario_id: str
    provider_id: str
    status: str
    evidence_id: str | None
    reason_code: str


ParityScenarioExecutor = Callable[
    [
        ParityProviderFactory,
        ParityClock,
        ParityPrivateFixtureStore,
        ParityFaultInjector,
    ],
    Awaitable[ParityScenarioResult],
]


@dataclass(frozen=True, repr=False)
class ParityScenarioRunner:
    scenario_id: str
    provider_id: str
    boundary: str
    feature_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    fault_ids: tuple[str, ...]
    provider_factory: ParityProviderFactory
    clock: ParityClock
    private_fixture_store: ParityPrivateFixtureStore
    fault_injector: ParityFaultInjector
    executor: ParityScenarioExecutor


@dataclass(frozen=True)
class ParityScenarioReport:
    provider_id: str
    results: tuple[ParityScenarioResult, ...]

    @property
    def passed_scenario_ids(self) -> tuple[str, ...]:
        return tuple(
            result.scenario_id for result in self.results if result.status == "pass"
        )

    @property
    def blocking_scenario_ids(self) -> tuple[str, ...]:
        return tuple(
            result.scenario_id for result in self.results if result.status != "pass"
        )


class ParityScenarioRegistry:
    """Own every ledger scenario key while treating absent runners as missing."""

    def __init__(
        self,
        ledger: Mapping[str, object],
        *,
        provider_id: str,
    ) -> None:
        try:
            snapshot = validate_parity_ledger(ledger)
            providers = _string_sequence(snapshot.get("providers"))
            if provider_id not in providers:
                raise ParityScenarioRegistryError(
                    "parity scenario provider is invalid"
                )
            scenarios = _mapping_sequence(snapshot.get("scenarios"))
            self._scenario_contracts = {
                str(scenario["scenario_id"]): scenario for scenario in scenarios
            }
            self._runners: dict[str, ParityScenarioRunner | None] = {
                scenario_id: None for scenario_id in self._scenario_contracts
            }
            self._provider_id = provider_id
        except (KeyError, ParityLedgerError, ParityScenarioRegistryError):
            raise ParityScenarioRegistryError(
                "parity scenario registry is invalid"
            ) from None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(self._runners)

    @property
    def registered_scenario_ids(self) -> tuple[str, ...]:
        return tuple(
            scenario_id
            for scenario_id, runner in self._runners.items()
            if runner is not None
        )

    def register(self, scenario_id: str, runner: ParityScenarioRunner) -> None:
        """Register one exact implementation without invoking provider work."""

        try:
            self._validate_registration(scenario_id, runner, unavailable=set())
        except ParityScenarioRegistryError:
            raise
        except Exception:
            raise ParityScenarioRegistryError(
                "parity scenario registration is invalid"
            ) from None
        self._runners[scenario_id] = runner

    def register_many(
        self, registrations: Sequence[tuple[str, ParityScenarioRunner]]
    ) -> None:
        """Atomically register a closed runner set without provider work."""

        try:
            if type(registrations) not in {list, tuple}:
                raise ParityScenarioRegistryError(
                    "parity scenario registration is invalid"
                )
            items = tuple(registrations)
            unavailable: set[str] = set()
            for item in items:
                if type(item) is not tuple or len(item) != 2:
                    raise ParityScenarioRegistryError(
                        "parity scenario registration is invalid"
                    )
                scenario_id, runner = item
                self._validate_registration(scenario_id, runner, unavailable=unavailable)
                unavailable.add(scenario_id)
        except ParityScenarioRegistryError:
            raise
        except Exception:
            raise ParityScenarioRegistryError(
                "parity scenario registration is invalid"
            ) from None

        for scenario_id, runner in items:
            self._runners[scenario_id] = runner

    def _validate_registration(
        self,
        scenario_id: object,
        runner: object,
        *,
        unavailable: set[str],
    ) -> None:
        if (
            not isinstance(scenario_id, str)
            or scenario_id not in self._runners
            or scenario_id in unavailable
            or type(runner) is not ParityScenarioRunner
            or self._runners[scenario_id] is not None
            or runner.scenario_id != scenario_id
            or runner.provider_id != self._provider_id
        ):
            raise ParityScenarioRegistryError(
                "parity scenario registration is invalid"
            )
        contract = self._scenario_contracts[scenario_id]
        if (
            runner.boundary != contract.get("boundary")
            or runner.feature_ids != _string_sequence(contract.get("feature_ids"))
            or runner.assertion_ids != _string_sequence(contract.get("assertion_ids"))
            or runner.fault_ids != _string_sequence(contract.get("fault_ids"))
            or not callable(runner.provider_factory)
            or not callable(runner.executor)
            or runner.clock.deterministic is not True
            or runner.fault_injector.deterministic is not True
        ):
            raise ParityScenarioRegistryError(
                "parity scenario registration is invalid"
            )
        credential_reads = _credential_reads(runner.private_fixture_store)
        if runner.boundary in _PROVIDER_FREE_BOUNDARIES and credential_reads != 0:
            raise ParityScenarioRegistryError(
                "provider-free parity scenario accessed a model credential"
            )

    async def run(self, scenario_ids: Sequence[str]) -> ParityScenarioReport:
        """Run a canonical subset; every absent implementation remains blocking."""

        requested = _requested_scenarios(scenario_ids, known=self.scenario_ids)
        results: list[ParityScenarioResult] = []
        for scenario_id in requested:
            runner = self._runners[scenario_id]
            if runner is None:
                results.append(
                    _blocking_result(
                        scenario_id,
                        provider_id=self._provider_id,
                        status="missing",
                        reason_code="scenario-unimplemented",
                    )
                )
            else:
                results.append(await self._run_registered(runner))
        return ParityScenarioReport(
            provider_id=self._provider_id,
            results=tuple(results),
        )

    async def _run_registered(
        self, runner: ParityScenarioRunner
    ) -> ParityScenarioResult:
        try:
            credential_reads_before = _credential_reads(
                runner.private_fixture_store
            )
            if (
                runner.clock.deterministic is not True
                or runner.fault_injector.deterministic is not True
            ):
                return _blocking_result(
                    runner.scenario_id,
                    provider_id=self._provider_id,
                    status="failed",
                    reason_code="scenario-nondeterministic",
                )
        except Exception:
            return _blocking_result(
                runner.scenario_id,
                provider_id=self._provider_id,
                status="failed",
                reason_code="scenario-resource-invalid",
            )

        execution_failed = False
        result: object = None
        try:
            result = await runner.executor(
                runner.provider_factory,
                runner.clock,
                runner.private_fixture_store,
                runner.fault_injector,
            )
        except Exception:
            execution_failed = True

        try:
            credential_reads_after = _credential_reads(runner.private_fixture_store)
            if (
                runner.boundary in _PROVIDER_FREE_BOUNDARIES
                and credential_reads_after != credential_reads_before
            ):
                return _blocking_result(
                    runner.scenario_id,
                    provider_id=self._provider_id,
                    status="failed",
                    reason_code="provider-credential-access-forbidden",
                )
            if (
                credential_reads_after < credential_reads_before
                or runner.clock.deterministic is not True
                or runner.fault_injector.deterministic is not True
            ):
                return _blocking_result(
                    runner.scenario_id,
                    provider_id=self._provider_id,
                    status="failed",
                    reason_code="scenario-resource-invalid",
                )
        except Exception:
            return _blocking_result(
                runner.scenario_id,
                provider_id=self._provider_id,
                status="failed",
                reason_code="scenario-resource-invalid",
            )

        if execution_failed:
            return _blocking_result(
                runner.scenario_id,
                provider_id=self._provider_id,
                status="failed",
                reason_code="scenario-execution-failed",
            )
        if not _valid_runner_result(
            result,
            scenario_id=runner.scenario_id,
            provider_id=self._provider_id,
        ):
            return _blocking_result(
                runner.scenario_id,
                provider_id=self._provider_id,
                status="failed",
                reason_code="scenario-result-invalid",
            )
        assert isinstance(result, ParityScenarioResult)
        return result


def _valid_runner_result(
    value: object,
    *,
    scenario_id: str,
    provider_id: str,
) -> bool:
    if (
        type(value) is not ParityScenarioResult
        or value.scenario_id != scenario_id
        or value.provider_id != provider_id
        or value.status not in _RUNNER_STATUSES
        or _IDENTIFIER.fullmatch(value.reason_code) is None
    ):
        return False
    if value.status == "pass":
        return (
            isinstance(value.evidence_id, str)
            and _IDENTIFIER.fullmatch(value.evidence_id) is not None
        )
    return value.evidence_id is None or (
        isinstance(value.evidence_id, str)
        and _IDENTIFIER.fullmatch(value.evidence_id) is not None
    )


def _blocking_result(
    scenario_id: str,
    *,
    provider_id: str,
    status: str,
    reason_code: str,
) -> ParityScenarioResult:
    return ParityScenarioResult(
        scenario_id=scenario_id,
        provider_id=provider_id,
        status=status,
        evidence_id=None,
        reason_code=reason_code,
    )


def _credential_reads(store: ParityPrivateFixtureStore) -> int:
    value = store.model_credential_reads
    if type(value) is not int or value < 0:
        raise ParityScenarioRegistryError(
            "parity private fixture store is invalid"
        )
    return value


def _requested_scenarios(
    value: Sequence[str], *, known: tuple[str, ...]
) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise ParityScenarioRegistryError("parity scenario selection is invalid")
    requested = tuple(value)
    if (
        any(not isinstance(item, str) for item in requested)
        or requested != tuple(sorted(set(requested)))
        or any(item not in known for item in requested)
    ):
        raise ParityScenarioRegistryError("parity scenario selection is invalid")
    return requested


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if type(value) not in {list, tuple}:
        raise ParityScenarioRegistryError("parity scenarios are invalid")
    assert isinstance(value, Sequence)
    if any(not isinstance(item, Mapping) for item in value):
        raise ParityScenarioRegistryError("parity scenarios are invalid")
    return tuple(value)  # type: ignore[arg-type]


def _string_sequence(value: object) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise ParityScenarioRegistryError("parity identities are invalid")
    assert isinstance(value, Sequence)
    if any(not isinstance(item, str) for item in value):
        raise ParityScenarioRegistryError("parity identities are invalid")
    return tuple(value)  # type: ignore[return-value]
