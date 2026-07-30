"""Formal installed benchmark host owned by the DCI product."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from asterion.applications.dci_agent_lite.benchmark_authorization import (
    DciBenchmarkExecutionAuthorization,
    DciBenchmarkExecutionAuthorizer,
)
from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
)
from asterion.applications.dci_agent_lite.operator_config import DciOperatorConfig
from asterion.benchmarks import (
    ApplicationRef,
    BenchmarkExecutionAuthorization,
    BenchmarkRunner,
    BenchmarkTaskExecutor,
    BenchmarkPlanRequest,
    BenchmarkRunResult,
    InstalledBenchmarkResolution,
    ResolvedBenchmarkPlan,
    create_benchmark_plan,
    LocalPrivateBenchmarkEvidenceStore,
    resolve_installed_benchmark,
)
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    CapabilityPackageCandidate,
    CapabilitySourceLock,
    InstalledCapabilityPackage,
    resolve_capability_source,
)
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    create_benchmark_bindings,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
    create_local_fixture_operator_inputs,
)
from asterion.applications.dci_agent_lite.benchmark_executor import (
    LocalDciBenchmarkExecutor,
    RealDciBenchmarkExecutor,
)
from asterion.capabilities.dci.implementation.config import (
    resolve_dci_paths,
    resolve_dci_runtime_options,
)
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig
from asterion.runtime.host import CancellationSignal


class DciBenchmarkHostError(ValueError):
    """Raised when DCI host lifecycle or selected provider state is invalid."""


@dataclass(frozen=True, slots=True)
class _DciResolvedSelection:
    resolution: InstalledBenchmarkResolution = field(repr=False)
    source_lock_path: Path = field(repr=False)


@dataclass(frozen=True, slots=True)
class DciLoadedBenchmarkProviders:
    packages: tuple[InstalledCapabilityPackage, ...] = field(repr=False)
    authorization: DciBenchmarkExecutionAuthorization = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "packages", tuple(self.packages))


class DciBenchmarkHost:
    """Translate one exact DCI instance into generic benchmark host phases."""

    def __init__(
        self,
        *,
        instance: DciBenchmarkInstance,
        operator_config: DciOperatorConfig | None,
        package_sources: Sequence[CapabilityPackageSource] | None = None,
        cancellation: CancellationSignal | None = None,
        executor_factory: (
            Callable[[DciBenchmarkInstance], BenchmarkTaskExecutor] | None
        ) = None,
    ) -> None:
        if (
            not isinstance(instance, DciBenchmarkInstance)
            or operator_config is not None
            and not isinstance(operator_config, DciOperatorConfig)
        ):
            _fail()
        self._instance = instance
        self._operator_config = operator_config
        self._package_sources = (
            None if package_sources is None else tuple(package_sources)
        )
        self._authorizer = DciBenchmarkExecutionAuthorizer(instance)
        self._draft_plan: ResolvedBenchmarkPlan | None = None
        self._cancellation = _NeverCancelled() if cancellation is None else cancellation
        self._executor_factory = executor_factory

    def discover_metadata(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object:
        self._validate_refs(application_ref, suite_ref)
        return application_ref, suite_ref

    def resolve_source_lock(self, source_lock: Path | None) -> object:
        if not isinstance(source_lock, Path):
            _fail()
        return source_lock

    def open_selected_payloads(
        self,
        metadata: object,
        source_lock: object,
    ) -> object:
        if metadata != (
            self._instance.application_ref,
            self._instance.suite_ref,
        ) or not isinstance(source_lock, Path):
            _fail()
        return _DciResolvedSelection(
            resolution=resolve_installed_benchmark(
                application_ref=self._instance.application_ref,
                source_lock_path=source_lock,
                package_sources=self._package_sources,
            ),
            source_lock_path=source_lock,
        )

    def resolve_application(
        self,
        payloads: object,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object:
        self._validate_refs(application_ref, suite_ref)
        if not isinstance(payloads, _DciResolvedSelection):
            _fail()
        return payloads

    def create_plan(
        self,
        resolved: object,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int | None,
        execute: bool,
        authorization: BenchmarkExecutionAuthorization | None,
        resume_run_id: str | None,
    ) -> ResolvedBenchmarkPlan:
        try:
            self._validate_refs(application_ref, suite_ref)
            if not isinstance(resolved, _DciResolvedSelection):
                _fail()
            if execute:
                if (
                    type(authorization) is not DciBenchmarkExecutionAuthorization
                    or resume_run_id != authorization.resume_run_id
                ):
                    _fail()
                plan = create_benchmark_plan(
                    BenchmarkPlanRequest(
                        application_ref=application_ref,
                        suite_ref=suite_ref,
                        case_limit=case_limit,
                        execute=True,
                        authorization=authorization,
                    ),
                    resolved.resolution.application,
                    resolved.resolution.packages,
                    authorizer=self._authorizer,
                )
                if (
                    self._draft_plan is None
                    or plan.case_limit != self._draft_plan.case_limit
                    or plan.tasks != self._draft_plan.tasks
                    or plan.package_locks != self._draft_plan.package_locks
                ):
                    _fail()
                return plan
            if authorization is not None or resume_run_id is not None:
                _fail()
            plan = create_benchmark_plan(
                BenchmarkPlanRequest(
                    application_ref=application_ref,
                    suite_ref=suite_ref,
                    case_limit=case_limit,
                    execute=False,
                ),
                resolved.resolution.application,
                resolved.resolution.packages,
            )
            self._draft_plan = plan
            return plan
        except DciBenchmarkHostError:
            raise
        except Exception:
            _fail()

    def authorize_execution(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int | None,
        evidence_root: Path,
        resume_run_id: str | None,
    ) -> BenchmarkExecutionAuthorization:
        self._validate_refs(application_ref, suite_ref)
        draft = self._draft_plan
        if (
            draft is None
            or case_limit != draft.case_limit
            or not isinstance(evidence_root, Path)
            or not evidence_root.is_absolute()
        ):
            _fail()
        return self._authorizer.issue(
            case_limit=draft.case_limit,
            package_locks=draft.package_locks,
            evidence_root=evidence_root,
            resume_run_id=resume_run_id,
        )

    def load_selected_providers(
        self,
        payloads: object,
        authorization: BenchmarkExecutionAuthorization,
    ) -> object:
        try:
            if not isinstance(payloads, _DciResolvedSelection):
                _fail()
            draft = self._draft_plan
            if draft is None:
                _fail()
            inputs = self._operator_inputs(authorization)
            claim = self._authorizer.authorize_provider_loading(
                authorization,
                package_locks=draft.package_locks,
            )
            packages = tuple(
                self._load_package(package, inputs=inputs)
                for package in payloads.resolution.packages
            )
            return DciLoadedBenchmarkProviders(
                packages=packages,
                authorization=claim,
            )
        except DciBenchmarkHostError:
            raise
        except Exception:
            _fail()

    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        providers: object,
        *,
        evidence_root: Path,
    ) -> BenchmarkRunResult:
        try:
            if (
                not isinstance(plan, ResolvedBenchmarkPlan)
                or not isinstance(providers, DciLoadedBenchmarkProviders)
                or not isinstance(evidence_root, Path)
                or not evidence_root.is_absolute()
                or plan.application_ref != self._instance.application_ref
                or plan.suite.suite_ref != self._instance.suite_ref
                or tuple(
                    lock
                    for package in providers.packages
                    for lock in (
                        CapabilitySourceLock(
                            entries=(
                                next(
                                    entry
                                    for source_lock in plan.package_locks
                                    for entry in source_lock.entries
                                    if entry.package_ref == package.package_ref
                                ),
                            )
                        ),
                    )
                )
                != plan.package_locks
            ):
                _fail()
            self._authorizer.authorize_run(
                providers.authorization,
                run_id=plan.run_id,
                evidence_root=evidence_root,
            )
            executor = (
                self._executor_factory(self._instance)
                if self._executor_factory is not None
                else self._default_executor()
            )
            runner = BenchmarkRunner(
                output_directory_factory=lambda selected_plan, task: (
                    evidence_root / "outputs" / selected_plan.run_id / task.task.task_id
                )
            )
            selected_binding_ids = frozenset(
                task.task.binding_id for task in plan.tasks
            )
            return runner.run(
                plan,
                implementations=tuple(
                    binding
                    for package in providers.packages
                    for binding in package.benchmark_bindings
                    if binding.binding_id in selected_binding_ids
                ),
                executor=executor,
                evidence=LocalPrivateBenchmarkEvidenceStore(evidence_root),
                cancellation=self._cancellation,
            )
        except DciBenchmarkHostError:
            raise
        except Exception:
            _fail()

    def _default_executor(self) -> BenchmarkTaskExecutor:
        if self._instance.executor_profile == "local-fixture":
            return LocalDciBenchmarkExecutor()
        if self._instance.executor_profile == "real-agent-judge":
            config = self._operator_config
            if config is None:
                _fail()
            environment = config.benchmark_inputs.private_environment
            return RealDciBenchmarkExecutor(
                paths=resolve_dci_paths(
                    config.repo_root,
                    environment=environment,
                ),
                runtime_options=resolve_dci_runtime_options(
                    {
                        "runtime": "pi",
                        "provider": "openai-codex",
                        "model": "gpt-5.6-luna",
                        "tools": "read,bash",
                        "runtime_context_level": "level3",
                    },
                    environment=environment,
                ),
                judge_config=JudgeConfig.from_environment(environment),
                experiment_profile="asterion-safe/pi",
                max_turns=100,
            )
        _fail()

    def _operator_inputs(
        self,
        authorization: object,
    ) -> DciBenchmarkOperatorInputs:
        if type(authorization) is not DciBenchmarkExecutionAuthorization:
            _fail()
        if self._instance.executor_profile == "local-fixture":
            return create_local_fixture_operator_inputs(authorization.evidence_root)
        if self._operator_config is None:
            _fail()
        return self._operator_config.benchmark_inputs

    def _load_package(
        self,
        metadata_package: InstalledCapabilityPackage,
        *,
        inputs: DciBenchmarkOperatorInputs,
    ) -> InstalledCapabilityPackage:
        records: list[
            tuple[
                CapabilityPackageSource,
                CapabilityPackageCandidate,
                CapabilityPackageCandidate,
            ]
        ] = []
        for source in self._sources():
            for original in source.discover_metadata():
                if original.package_ref != metadata_package.package_ref:
                    continue
                payload = source.open_payload(original)
                source.validate_source_identity(original, payload)
                records.append(
                    (
                        source,
                        original,
                        CapabilityPackageCandidate(
                            package_ref=original.package_ref,
                            source_id=original.source_id,
                            source_kind=original.source_kind,
                            payload_sha256=payload.payload_sha256,
                            metadata=original.metadata,
                        ),
                    )
                )
        selected = resolve_capability_source(
            metadata_package.package_ref,
            tuple(record[2] for record in records),
            CapabilitySourceLock(entries=self._draft_plan.package_locks[0].entries)
            if self._draft_plan is not None
            else None,
        )
        matches = tuple(
            (source, original)
            for source, original, normalized in records
            if normalized == selected
        )
        if len(matches) != 1:
            _fail()
        source, original = matches[0]
        installed = source.load_provider(original)
        if (
            not isinstance(installed, InstalledCapabilityPackage)
            or installed.package_ref != metadata_package.package_ref
            or installed.payload_sha256 != metadata_package.payload_sha256
            or installed.source_id != metadata_package.source_id
            or installed.source_kind != metadata_package.source_kind
        ):
            _fail()
        return InstalledCapabilityPackage(
            package_ref=installed.package_ref,
            payload_sha256=installed.payload_sha256,
            source_id=installed.source_id,
            source_kind=installed.source_kind,
            catalog_roots=installed.catalog_roots,
            benchmark_suite_paths=installed.benchmark_suite_paths,
            implementations=installed.implementations,
            benchmark_bindings=create_benchmark_bindings(
                operator_inputs=inputs,
            ),
        )

    def _sources(self) -> tuple[CapabilityPackageSource, ...]:
        values = self._package_sources
        sources = (
            (BuiltinCapabilitySource(), DistributionCapabilityPackageSource())
            if values is None
            else values
        )
        if not sources:
            _fail()
        return sources

    def _validate_refs(
        self,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> None:
        if (
            application_ref != self._instance.application_ref
            or suite_ref != self._instance.suite_ref
        ):
            _fail()


def _fail() -> NoReturn:
    raise DciBenchmarkHostError("DCI benchmark host is invalid") from None


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


__all__ = (
    "DciBenchmarkHost",
    "DciBenchmarkHostError",
    "DciLoadedBenchmarkProviders",
)
