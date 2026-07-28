"""Thin generic host command for bounded benchmark plans and runs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TextIO

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
)
from asterion.applications.provider import InstalledApplication
from asterion.applications.selection import (
    ApplicationSelector,
    parse_application_selector,
)
from asterion.assembly.protocol import validate_assembly_manifest
from asterion.benchmarks.evidence import (
    BenchmarkEvidenceStore,
    LocalPrivateBenchmarkEvidenceStore,
)
from asterion.benchmarks.execution import (
    BenchmarkRunner,
    BenchmarkTaskExecutor,
)
from asterion.benchmarks.planning import (
    BenchmarkPlanRequest,
    ResolvedApplicationMetadata,
    create_benchmark_plan,
    render_benchmark_plan,
)
from asterion.benchmarks.process import AuthorizedProcessTaskExecutor
from asterion.benchmarks.resolution import resolve_benchmark_execution
from asterion.capabilities.catalog import CapabilityRef, discover_capabilities
from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.protocol import (
    IDENTIFIER,
    SEMANTIC_VERSION,
    BenchmarkSuiteRef,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    validate_capability_source_lock,
)
from asterion.capability_packages.sources import CapabilityPackageSource
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilityPackageSource,
)
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.runtime.host import CancellationSignal


class BenchmarkCliError(RuntimeError):
    """Stable private-value-free benchmark host failure."""


@dataclass(frozen=True, slots=True)
class _SelectedPackageSource:
    source: CapabilityPackageSource
    candidate: CapabilityPackageCandidate
    payload: PortableCapabilityPayload


@dataclass(slots=True)
class _NeverCancelled:
    cancelled: bool = False


def add_benchmark_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the provider-neutral ``asterion benchmark`` command."""

    benchmark = subparsers.add_parser(
        "benchmark",
        help="plan or execute an exact bounded benchmark suite",
    )
    commands = benchmark.add_subparsers(
        dest="benchmark_command",
        required=True,
    )
    plan = commands.add_parser(
        "plan",
        help="print an exact provider-free plan",
        description=(
            "Print an exact provider-free benchmark plan. Omitted case limits "
            "use the suite's finite bounded default."
        ),
    )
    run = commands.add_parser(
        "run",
        help="execute a new externally authorized plan",
        description=(
            "Execute a bounded benchmark only with explicit external "
            "authorization."
        ),
    )
    resume = commands.add_parser(
        "resume",
        help="resume exact compatible evidence",
        description=(
            "Resume a bounded benchmark only with explicit external "
            "authorization and an exact run identity."
        ),
    )
    for command in (plan, run, resume):
        command.add_argument(
            "--application",
            required=True,
            metavar="ID@VERSION",
            help="exact application identity",
        )
        command.add_argument(
            "--suite",
            required=True,
            metavar="ID@VERSION",
            help="exact benchmark-suite identity",
        )
        command.add_argument(
            "--case-limit",
            type=int,
            metavar="N",
            help="positive finite case bound; defaults to the suite bound",
        )
        command.add_argument(
            "--capability-source-lock",
            action="append",
            default=[],
            metavar="PATH",
            help="exact operator-owned package source lock (repeatable)",
        )
        command.add_argument(
            "--evidence-root",
            default=".asterion/benchmark-evidence",
            metavar="PATH",
            help="private evidence root (unused by plan-only mode)",
        )
    for command in (run, resume):
        command.add_argument(
            "--execute",
            action="store_true",
            help="confirm explicit external execution authorization",
        )
    resume.add_argument(
        "--run-id",
        required=True,
        metavar="ID",
        help="exact prior run identity",
    )


def run_benchmark_command(
    args: argparse.Namespace,
    *,
    entry_points: Iterable[object] | None,
    capability_package_sources: Iterable[CapabilityPackageSource] | None,
    stdout: TextIO,
    stderr: TextIO,
    task_executor: BenchmarkTaskExecutor | None = None,
    cancellation: CancellationSignal | None = None,
    evidence_store_factory: (
        Callable[[Path], BenchmarkEvidenceStore] | None
    ) = None,
) -> int:
    """Run one parsed benchmark host command."""

    if args.benchmark_command in {"run", "resume"} and not args.execute:
        stderr.write("asterion benchmark: --execute is required\n")
        return 2
    try:
        application_ref = parse_application_selector(args.application)
        suite_ref = _parse_suite_ref(args.suite)
        application = _select_application_metadata(
            application_ref,
            entry_points=entry_points,
        )
        sources = (
            BuiltinCapabilityPackageSource(),
            DistributionCapabilityPackageSource(),
            *(
                ()
                if capability_package_sources is None
                else tuple(capability_package_sources)
            ),
        )
        locks = _load_source_locks(args.capability_source_lock)
        selected_sources, payloads, exact_lock = _select_package_payloads(
            application.capability_packages,
            sources,
            locks,
        )
        resolved_application = _resolve_application_metadata(
            application_ref,
            application,
            payloads,
            exact_lock,
        )
        plan = create_benchmark_plan(
            BenchmarkPlanRequest(
                application_ref=application_ref,
                suite_ref=suite_ref,
                case_limit=args.case_limit,
            ),
            resolved_application,
            payloads,
        )
        if args.benchmark_command == "resume":
            plan = replace(plan, run_id=args.run_id)
        stdout.write(render_benchmark_plan(plan))
        stdout.flush()
        if args.benchmark_command == "plan":
            return 0

        installed = _load_selected_providers(selected_sources)
        execution_plan = resolve_benchmark_execution(plan, installed)
        store_factory = (
            LocalPrivateBenchmarkEvidenceStore
            if evidence_store_factory is None
            else evidence_store_factory
        )
        evidence = store_factory(_absolute_path(args.evidence_root))
        executor = (
            AuthorizedProcessTaskExecutor()
            if task_executor is None
            else task_executor
        )
        signal = _NeverCancelled() if cancellation is None else cancellation
        result = BenchmarkRunner().run(
            execution_plan,
            executor=executor,
            evidence=evidence,
            cancellation=signal,
        )
        stdout.write(
            json.dumps(
                {
                    "completed_task_ids": list(result.completed_task_ids),
                    "content_digests": list(result.content_digests),
                    "run_id": result.run_id,
                    "status": result.status,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0 if result.status == "completed" else 1
    except BenchmarkCliError as error:
        stderr.write(f"asterion benchmark: {error}\n")
        return 2
    except KeyboardInterrupt:
        stderr.write("asterion benchmark: execution interrupted\n")
        return 130
    except Exception:
        stderr.write("asterion benchmark: command failed\n")
        return 2


def _parse_suite_ref(value: object) -> BenchmarkSuiteRef:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or value.count("@") != 1
    ):
        raise BenchmarkCliError("suite selection failed")
    suite_id, version = value.split("@", 1)
    if (
        IDENTIFIER.fullmatch(suite_id) is None
        or SEMANTIC_VERSION.fullmatch(version) is None
    ):
        raise BenchmarkCliError("suite selection failed")
    return BenchmarkSuiteRef(suite_id=suite_id, version=version)


def _select_application_metadata(
    selector: ApplicationSelector,
    *,
    entry_points: Iterable[object] | None,
) -> InstalledApplication:
    try:
        providers = tuple(
            load_application_provider(
                item.provider_id,
                entry_points=entry_points,
            )
            for item in list_application_providers(entry_points=entry_points)
        )
        matches = tuple(
            application
            for provider in providers
            for application in provider.applications
            if application.application_id == selector.application_id
            and application.version == selector.version
        )
    except Exception:
        raise BenchmarkCliError("application selection failed") from None
    if len(matches) != 1:
        raise BenchmarkCliError("application selection failed")
    return matches[0]


def _load_source_locks(values: Iterable[str]) -> tuple[CapabilitySourceLock, ...]:
    locks: list[CapabilitySourceLock] = []
    try:
        for value in values:
            path = Path(value)
            if path.is_symlink():
                raise ValueError
            document = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
            locks.append(validate_capability_source_lock(document))
    except Exception:
        raise BenchmarkCliError("capability source selection failed") from None
    entries = tuple(entry for lock in locks for entry in lock.entries)
    if len({entry.package_ref for entry in entries}) != len(entries):
        raise BenchmarkCliError("capability source selection failed")
    return tuple(locks)


def _select_package_payloads(
    package_refs: tuple[CapabilityPackageRef, ...],
    sources: tuple[CapabilityPackageSource, ...],
    locks: tuple[CapabilitySourceLock, ...],
) -> tuple[
    tuple[_SelectedPackageSource, ...],
    tuple[PortableCapabilityPayload, ...],
    CapabilitySourceLock,
]:
    locked_by_ref = {
        entry.package_ref: entry
        for lock in locks
        for entry in lock.entries
    }
    if any(package_ref not in package_refs for package_ref in locked_by_ref):
        raise BenchmarkCliError("capability source selection failed")
    discovered: list[
        tuple[CapabilityPackageSource, CapabilityPackageCandidate]
    ] = []
    try:
        for source in sources:
            candidates = source.discover_metadata()
            if (
                not isinstance(candidates, tuple)
                or any(
                    not isinstance(candidate, CapabilityPackageCandidate)
                    for candidate in candidates
                )
            ):
                raise ValueError
            discovered.extend((source, candidate) for candidate in candidates)
    except Exception:
        raise BenchmarkCliError("capability source selection failed") from None

    selected: list[_SelectedPackageSource] = []
    exact_entries: list[CapabilitySourceLockEntry] = []
    try:
        for package_ref in package_refs:
            matches = tuple(
                (source, candidate)
                for source, candidate in discovered
                if candidate.package_ref == package_ref
            )
            locked = locked_by_ref.get(package_ref)
            if locked is not None:
                matches = tuple(
                    (source, candidate)
                    for source, candidate in matches
                    if candidate.source_id == locked.source_id
                    and (
                        candidate.payload_sha256 is None
                        or candidate.payload_sha256
                        == locked.payload_sha256
                    )
                )
            if len(matches) != 1:
                raise ValueError
            source, candidate = matches[0]
            payload = source.open_payload(candidate)
            if (
                not isinstance(payload, PortableCapabilityPayload)
                or payload.manifest.package_ref != package_ref
                or (
                    candidate.payload_sha256 is not None
                    and candidate.payload_sha256 != payload.payload_sha256
                )
                or (
                    locked is not None
                    and locked.payload_sha256 != payload.payload_sha256
                )
            ):
                raise ValueError
            source.validate_source_identity(candidate, payload)
            selected.append(
                _SelectedPackageSource(
                    source=source,
                    candidate=candidate,
                    payload=payload,
                )
            )
            exact_entries.append(
                CapabilitySourceLockEntry(
                    package_ref=package_ref,
                    payload_sha256=payload.payload_sha256,
                    source_id=candidate.source_id,
                )
            )
    except Exception:
        raise BenchmarkCliError("capability source selection failed") from None
    return (
        tuple(selected),
        tuple(item.payload for item in selected),
        CapabilitySourceLock(entries=tuple(exact_entries)),
    )


def _resolve_application_metadata(
    application_ref: ApplicationSelector,
    application: InstalledApplication,
    payloads: tuple[PortableCapabilityPayload, ...],
    exact_lock: CapabilitySourceLock,
) -> ResolvedApplicationMetadata:
    try:
        assembly_capabilities = _application_capability_refs(application)
        roots = tuple(
            Path(
                str(payload.resource_root.joinpath("capabilities"))
            ).resolve(strict=True)
            for payload in payloads
        )
        catalog = discover_capabilities(roots)
        by_ref = {entry.ref: entry for entry in catalog.entries}
        capabilities = tuple(
            by_ref[capability_ref]
            for capability_ref in assembly_capabilities
        )
        if len(by_ref) != sum(
            len(payload.manifest.capabilities) for payload in payloads
        ):
            raise ValueError
        return ResolvedApplicationMetadata(
            application_ref=application_ref,
            capabilities=capabilities,
            package_locks=(exact_lock,),
        )
    except Exception:
        raise BenchmarkCliError("application selection failed") from None


def _application_capability_refs(
    application: InstalledApplication,
) -> tuple[CapabilityRef, ...]:
    closures: list[tuple[CapabilityRef, ...]] = []
    for path in application.assembly_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_assembly_manifest(document)
        if (
            document["application_id"] != application.application_id
            or document["version"] != application.version
        ):
            raise ValueError
        raw_capabilities = document["capabilities"]
        if not isinstance(raw_capabilities, list):
            raise ValueError
        closures.append(
            tuple(
                CapabilityRef(
                    capability["capability_id"],
                    capability["version"],
                )
                for capability in raw_capabilities
                if isinstance(capability, dict)
                and isinstance(capability.get("capability_id"), str)
                and isinstance(capability.get("version"), str)
            )
        )
    if not closures or any(closure != closures[0] for closure in closures):
        raise ValueError
    return closures[0]


def _load_selected_providers(
    selected: tuple[_SelectedPackageSource, ...],
) -> tuple[InstalledCapabilityPackage, ...]:
    installed: list[InstalledCapabilityPackage] = []
    try:
        for item in selected:
            package = item.source.load_provider(item.candidate)
            if (
                not isinstance(package, InstalledCapabilityPackage)
                or package.package_ref != item.candidate.package_ref
                or package.payload_sha256 != item.payload.payload_sha256
                or package.source_id != item.candidate.source_id
                or package.source_kind != item.candidate.source_kind
            ):
                raise ValueError
            installed.append(package)
    except Exception:
        raise BenchmarkCliError("provider selection failed") from None
    return tuple(installed)


def _absolute_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path
