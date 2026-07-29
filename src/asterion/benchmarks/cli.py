"""Generic benchmark host command coordination."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable, NoReturn, Protocol, TextIO, TypeVar, runtime_checkable

from asterion.benchmarks.evidence import BenchmarkRunResult
from asterion.benchmarks.host import create_installed_benchmark_plan
from asterion.benchmarks.model import ApplicationRef, ResolvedBenchmarkPlan
from asterion.benchmarks.planning import (
    BenchmarkExecutionAuthorization,
    render_benchmark_plan,
)
from asterion.capability_packages import BenchmarkSuiteRef
from asterion.capability_packages.sources import CapabilityPackageSource


_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_T = TypeVar("_T")


class BenchmarkCliError(ValueError):
    """Raised when benchmark command input or host coordination fails."""


@runtime_checkable
class BenchmarkCommandHost(Protocol):
    """Host-owned benchmark boundary used by the generic CLI."""

    def discover_metadata(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object: ...

    def resolve_source_lock(self, source_lock: Path | None) -> object: ...

    def open_selected_payloads(self, metadata: object, source_lock: object) -> object: ...

    def resolve_application(
        self,
        payloads: object,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object: ...

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
    ) -> ResolvedBenchmarkPlan: ...

    def authorize_execution(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int | None,
        evidence_root: Path,
        resume_run_id: str | None,
    ) -> BenchmarkExecutionAuthorization: ...

    def load_selected_providers(
        self,
        payloads: object,
        authorization: BenchmarkExecutionAuthorization,
    ) -> object: ...

    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        providers: object,
        *,
        evidence_root: Path,
    ) -> BenchmarkRunResult: ...


def main(
    argv: Sequence[str],
    *,
    host: BenchmarkCommandHost | None = None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run ``asterion benchmark`` without product-specific CLI authority."""

    parser = _parser()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = parser.parse_args(list(argv))
        command = str(args.benchmark_command)
        application_ref = _parse_application_ref(args.application)
        suite_ref = _parse_suite_ref(args.suite)
        case_limit = _case_limit(args.case_limit)
        resume_run_id = _resume_run_id(command, getattr(args, "run_id", None))
        execute = bool(getattr(args, "execute", False))

        if command in {"run", "resume"}:
            if not execute:
                _fail("benchmark execution requires --execute")
        elif execute:
            _fail("benchmark execution is invalid")

        source_lock = _source_lock(args.capability_source_lock)
        evidence_root = _evidence_root(args.evidence_root)
        if command in {"run", "resume"}:
            if source_lock is None:
                _fail("benchmark source lock is required")
            if evidence_root is None:
                _fail("benchmark evidence root is required")

        command_host = _host(host)
        metadata = command_host.discover_metadata(
            application_ref=application_ref,
            suite_ref=suite_ref,
        )
        source_lock_value = command_host.resolve_source_lock(source_lock)
        payloads = command_host.open_selected_payloads(metadata, source_lock_value)
        resolved = command_host.resolve_application(
            payloads,
            application_ref=application_ref,
            suite_ref=suite_ref,
        )

        draft = _host_call(
            lambda: command_host.create_plan(
                resolved,
                application_ref=application_ref,
                suite_ref=suite_ref,
                case_limit=case_limit,
                execute=False,
                authorization=None,
                resume_run_id=None,
            )
        )
        _validate_plan(draft, application_ref, suite_ref)
        if not execute:
            stdout.write(render_benchmark_plan(draft) + "\n")
            return 0

        assert evidence_root is not None
        authorization = _host_call(
            lambda: command_host.authorize_execution(
                application_ref=application_ref,
                suite_ref=suite_ref,
                case_limit=draft.case_limit,
                evidence_root=evidence_root,
                resume_run_id=resume_run_id,
            )
        )
        plan = _host_call(
            lambda: command_host.create_plan(
                resolved,
                application_ref=application_ref,
                suite_ref=suite_ref,
                case_limit=draft.case_limit,
                execute=True,
                authorization=authorization,
                resume_run_id=resume_run_id,
            )
        )
        _validate_execution_plan(draft, plan, resume_run_id=resume_run_id)
        assert authorization is not None
        providers = _host_call(
            lambda: command_host.load_selected_providers(payloads, authorization)
        )
        result = _host_call(
            lambda: command_host.run(plan, providers, evidence_root=evidence_root)
        )
        stdout.write(_result_json(result) + "\n")
        if result.status == "cancelled":
            return 130
        return 0 if result.status == "completed" else 1
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    except BenchmarkCliError as error:
        stderr.write(f"asterion benchmark: {error}\n")
        return 2
    except KeyboardInterrupt:
        stderr.write("asterion benchmark: command interrupted\n")
        return 130
    except Exception:
        stderr.write("asterion benchmark: command failed\n")
        return 2


def add_benchmark_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the benchmark parser on a parent ``asterion`` parser."""

    benchmark = subparsers.add_parser(
        "benchmark",
        help="plan and run bounded benchmark suites with external authorization",
    )
    _add_benchmark_subcommands(benchmark)


def _parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(
        prog="asterion benchmark",
        description=(
            "Plan and run bounded benchmark suites. Execution requires explicit "
            "external authorization."
        ),
    )
    _add_benchmark_subcommands(parser)
    return parser


def _add_benchmark_subcommands(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="benchmark_command", required=True)
    plan = subparsers.add_parser(
        "plan",
        help="print a deterministic bounded plan without execution",
        description=(
            "Print a deterministic bounded benchmark plan. This does not create "
            "evidence and does not require external authorization."
        ),
    )
    _add_common_arguments(plan)
    run = subparsers.add_parser(
        "run",
        help="execute a bounded plan after external authorization",
        description=(
            "Run a bounded benchmark suite. Requires --execute, exact selectors, "
            "--capability-source-lock, --evidence-root, and external authorization."
        ),
    )
    _add_common_arguments(run)
    run.add_argument("--execute", action="store_true")
    resume = subparsers.add_parser(
        "resume",
        help="resume a bounded run after external authorization",
        description=(
            "Resume a bounded benchmark run. Requires --execute, --run-id, exact "
            "selectors, --capability-source-lock, --evidence-root, and external "
            "authorization."
        ),
    )
    _add_common_arguments(resume)
    resume.add_argument("--execute", action="store_true")
    resume.add_argument("--run-id", required=True)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--application", required=True, metavar="ID@VERSION")
    parser.add_argument("--suite", required=True, metavar="ID@VERSION")
    parser.add_argument(
        "--case-limit",
        type=int,
        help="bounded case count; defaults to the selected suite maximum",
    )
    parser.add_argument(
        "--capability-source-lock",
        help="exact capability source lock path",
    )
    parser.add_argument(
        "--evidence-root",
        help="private evidence root for authorized run and resume commands",
    )


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.print_usage()
        raise BenchmarkCliError("arguments are invalid")


class InstalledBenchmarkCommandHost:
    """Generic installed benchmark host with explicit package sources."""

    def __init__(
        self,
        *,
        package_sources: Sequence[CapabilityPackageSource] | None = None,
    ) -> None:
        self._package_sources = (
            None if package_sources is None else tuple(package_sources)
        )

    def discover_metadata(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object:
        return application_ref, suite_ref

    def resolve_source_lock(self, source_lock: Path | None) -> object:
        return source_lock

    def open_selected_payloads(self, metadata: object, source_lock: object) -> object:
        return metadata, source_lock

    def resolve_application(
        self,
        payloads: object,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object:
        return payloads, application_ref, suite_ref

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
        if execute or authorization is not None or resume_run_id is not None:
            _fail("benchmark execution authority is unavailable")
        if (
            not isinstance(resolved, tuple)
            or len(resolved) != 3
            or not isinstance(resolved[0], tuple)
            or len(resolved[0]) != 2
        ):
            _fail("benchmark host planning is invalid")
        payloads, selected_application, selected_suite = resolved
        _, source_lock = payloads
        if (
            selected_application != application_ref
            or selected_suite != suite_ref
            or source_lock is not None and not isinstance(source_lock, Path)
        ):
            _fail("benchmark host planning is invalid")
        return create_installed_benchmark_plan(
            application_ref=application_ref,
            suite_ref=suite_ref,
            case_limit=case_limit,
            source_lock_path=source_lock,
            package_sources=self._package_sources,
        )

    def authorize_execution(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int | None,
        evidence_root: Path,
        resume_run_id: str | None,
    ) -> BenchmarkExecutionAuthorization:
        del application_ref, suite_ref, case_limit, evidence_root, resume_run_id
        _fail("benchmark execution authority is unavailable")

    def load_selected_providers(
        self,
        payloads: object,
        authorization: BenchmarkExecutionAuthorization,
    ) -> object:
        del payloads, authorization
        _fail("benchmark execution authority is unavailable")

    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        providers: object,
        *,
        evidence_root: Path,
    ) -> BenchmarkRunResult:
        del plan, providers, evidence_root
        _fail("benchmark execution authority is unavailable")


def _host(host: BenchmarkCommandHost | None) -> BenchmarkCommandHost:
    if host is None:
        return InstalledBenchmarkCommandHost()
    if not isinstance(host, BenchmarkCommandHost):
        _fail("benchmark host is invalid")
    return host


def _parse_application_ref(value: str) -> ApplicationRef:
    selector = _split_selector(value, "benchmark application selector is invalid")
    try:
        return ApplicationRef(selector[0], selector[1])
    except ValueError:
        _fail("benchmark application selector is invalid")


def _parse_suite_ref(value: str) -> BenchmarkSuiteRef:
    selector = _split_selector(value, "benchmark suite selector is invalid")
    try:
        return BenchmarkSuiteRef(selector[0], selector[1])
    except ValueError:
        _fail("benchmark suite selector is invalid")


def _split_selector(value: str, message: str) -> tuple[str, str]:
    if type(value) is not str or value.strip() != value or value.count("@") != 1:
        _fail(message)
    left, right = value.split("@", 1)
    if not left or not right:
        _fail(message)
    return left, right


def _case_limit(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 1:
        _fail("benchmark case limit is invalid")
    return value


def _source_lock(value: str | None) -> Path | None:
    if value is None:
        return None
    path = _path(value, "benchmark source lock is invalid", strict=True)
    if path.is_symlink() or not path.is_file():
        _fail("benchmark source lock is invalid")
    return path


def _evidence_root(value: str | None) -> Path | None:
    if value is None:
        return None
    path = _path(value, "benchmark evidence root is invalid", strict=False)
    if path.is_symlink() or path.exists() and not path.is_dir():
        _fail("benchmark evidence root is invalid")
    return path


def _path(value: str, message: str, *, strict: bool) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail(message)
    try:
        path = Path(value).expanduser()
        if path.is_symlink():
            _fail(message)
        return path.resolve(strict=strict)
    except OSError:
        _fail(message)


def _resume_run_id(command: str, value: str | None) -> str | None:
    if command != "resume":
        return None
    if type(value) is not str or _RUN_ID.fullmatch(value) is None:
        _fail("benchmark run id is invalid")
    return value


def _result_json(result: BenchmarkRunResult) -> str:
    if not isinstance(result, BenchmarkRunResult):
        _fail("benchmark result is invalid")
    return json.dumps(
        {
            "status": result.status,
            "tasks": [
                {
                    "artifact_ids": list(task.artifact_ids),
                    "case_count": task.case_count,
                    "status": task.status,
                    "task_id": task.task_id,
                }
                for task in result.tasks
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _host_call(call: Callable[[], _T]) -> _T:
    try:
        return call()
    except KeyboardInterrupt:
        raise
    except Exception:
        _fail("benchmark host command failed")


def _validate_plan(
    plan: object,
    application_ref: ApplicationRef,
    suite_ref: BenchmarkSuiteRef,
) -> None:
    if (
        not isinstance(plan, ResolvedBenchmarkPlan)
        or plan.application_ref != application_ref
        or plan.suite.suite_ref != suite_ref
    ):
        _fail("benchmark plan is invalid")


def _validate_execution_plan(
    draft: ResolvedBenchmarkPlan,
    plan: object,
    *,
    resume_run_id: str | None,
) -> None:
    _validate_plan(plan, draft.application_ref, draft.suite.suite_ref)
    assert isinstance(plan, ResolvedBenchmarkPlan)
    if (
        plan.case_limit != draft.case_limit
        or plan.suite != draft.suite
        or plan.tasks != draft.tasks
        or plan.package_locks != draft.package_locks
        or resume_run_id is not None and plan.run_id != resume_run_id
    ):
        _fail("benchmark execution plan is invalid")


def _fail(message: str) -> NoReturn:
    raise BenchmarkCliError(message) from None


__all__ = (
    "BenchmarkCliError",
    "BenchmarkCommandHost",
    "InstalledBenchmarkCommandHost",
    "add_benchmark_parser",
    "main",
)
