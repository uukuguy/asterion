from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from asterion.benchmarks.evidence import BenchmarkRunResult, BenchmarkTaskResult
from asterion.benchmarks.cli import BenchmarkCliError
from asterion.benchmarks.model import ApplicationRef, ResolvedBenchmarkPlan
from asterion.benchmarks.planning import BenchmarkExecutionAuthorization
from asterion.capability_packages import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    CapabilityPackageRef,
)
from asterion.cli import main as asterion_main


class BenchmarkCliTests(unittest.TestCase):
    def test_plan_prints_public_plan_without_authority_or_evidence(self) -> None:
        host = RecordingBenchmarkHost()
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = asterion_main(
            [
                "benchmark",
                "plan",
                "--application",
                "example.application@1.0.0",
                "--suite",
                "example.suite@1.0.0",
                "--case-limit",
                "3",
            ],
            benchmark_host=host,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "application": "example.application@1.0.0",
                "case_limit": 3,
                "package_locks": [],
                "run_id": "run-plan-001",
                "suite": "example.suite@1.0.0",
                "tasks": [],
            },
        )
        self.assertEqual(
            host.calls,
            [
                "discover_metadata",
                "resolve_source_lock",
                "open_selected_payloads",
                "resolve_application",
                "create_plan",
            ],
        )
        self.assertEqual(host.evidence_roots, [])
        self.assertNotIn("SECRET", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_run_without_execute_rejects_before_host_load(self) -> None:
        host = RecordingBenchmarkHost()
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = asterion_main(
            [
                "benchmark",
                "run",
                "--application",
                "example.application@1.0.0",
                "--suite",
                "example.suite@1.0.0",
                "--capability-source-lock",
                "source.lock.json",
                "--evidence-root",
                "evidence",
            ],
            benchmark_host=host,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(host.calls, [])
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("benchmark execution requires --execute", stderr.getvalue())
        self.assertNotIn("SECRET", stderr.getvalue())

    def test_run_authorizes_before_selected_provider_load_and_executes(self) -> None:
        host = RecordingBenchmarkHost()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            evidence_root = Path(temp_dir) / "evidence"
            source_lock = Path(temp_dir) / "source.lock.json"
            source_lock.write_text("{}", encoding="utf-8")

            code = asterion_main(
                [
                    "benchmark",
                    "run",
                    "--application",
                    "example.application@1.0.0",
                    "--suite",
                    "example.suite@1.0.0",
                    "--case-limit",
                    "2",
                    "--capability-source-lock",
                    str(source_lock),
                    "--evidence-root",
                    str(evidence_root),
                    "--execute",
                ],
                benchmark_host=host,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(
            host.calls,
            [
                "discover_metadata",
                "resolve_source_lock",
                "open_selected_payloads",
                "resolve_application",
                "create_plan",
                "authorize_execution",
                "create_plan",
                "load_selected_providers",
                "run",
            ],
        )
        self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")
        self.assertEqual(stderr.getvalue(), "")

    def test_resume_requires_run_id_and_reuses_host_plan_path(self) -> None:
        host = RecordingBenchmarkHost()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            evidence_root = Path(temp_dir) / "evidence"
            source_lock = Path(temp_dir) / "source.lock.json"
            source_lock.write_text("{}", encoding="utf-8")

            code = asterion_main(
                [
                    "benchmark",
                    "resume",
                    "--application",
                    "example.application@1.0.0",
                    "--suite",
                    "example.suite@1.0.0",
                    "--run-id",
                    "run-auth-001",
                    "--capability-source-lock",
                    str(source_lock),
                    "--evidence-root",
                    str(evidence_root),
                    "--execute",
                ],
                benchmark_host=host,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(host.resume_run_ids, ["run-auth-001"])
        self.assertEqual(host.calls[-2:], ["load_selected_providers", "run"])
        self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")

    def test_cancelled_run_exits_nonzero_after_host_records_evidence(self) -> None:
        host = RecordingBenchmarkHost(
            run_result=BenchmarkRunResult(
                status="cancelled",
                tasks=(
                    BenchmarkTaskResult(
                        task_id="example.alpha",
                        status="cancelled",
                        case_count=1,
                    ),
                ),
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            evidence_root = Path(temp_dir) / "evidence"
            source_lock = Path(temp_dir) / "source.lock.json"
            source_lock.write_text("{}", encoding="utf-8")

            code = asterion_main(
                [
                    "benchmark",
                    "run",
                    "--application",
                    "example.application@1.0.0",
                    "--suite",
                    "example.suite@1.0.0",
                    "--capability-source-lock",
                    str(source_lock),
                    "--evidence-root",
                    str(evidence_root),
                    "--execute",
                ],
                benchmark_host=host,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 130)
        self.assertEqual(host.calls[-1], "run")
        self.assertEqual(host.evidence_roots, [evidence_root.resolve()])
        self.assertEqual(json.loads(stdout.getvalue())["status"], "cancelled")

    def test_forbidden_domain_flags_are_rejected(self) -> None:
        forbidden = (
            "--dataset",
            "--corpus",
            "--launcher",
            "--prompt",
            "--provider",
            "--amount",
        )
        for flag in forbidden:
            with self.subTest(flag):
                host = RecordingBenchmarkHost()
                stdout = io.StringIO()
                stderr = io.StringIO()
                code = asterion_main(
                    [
                        "benchmark",
                        "plan",
                        "--application",
                        "example.application@1.0.0",
                        "--suite",
                        "example.suite@1.0.0",
                        flag,
                        "SECRET-VALUE",
                    ],
                    benchmark_host=host,
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertEqual(host.calls, [])
                self.assertNotIn("SECRET-VALUE", stderr.getvalue())

    def test_exact_selector_and_source_errors_are_stable_and_redacted(self) -> None:
        cases = (
            (
                [
                    "benchmark",
                    "plan",
                    "--application",
                    "bad selector",
                    "--suite",
                    "example.suite@1.0.0",
                ],
                "benchmark application selector is invalid",
            ),
            (
                [
                    "benchmark",
                    "plan",
                    "--application",
                    "example.application@1.0.0",
                    "--suite",
                    "bad suite",
                ],
                "benchmark suite selector is invalid",
            ),
            (
                [
                    "benchmark",
                    "run",
                    "--application",
                    "example.application@1.0.0",
                    "--suite",
                    "example.suite@1.0.0",
                    "--execute",
                ],
                "benchmark source lock is required",
            ),
        )
        for argv, expected in cases:
            with self.subTest(expected):
                host = RecordingBenchmarkHost()
                stderr = io.StringIO()
                code = asterion_main(
                    argv,
                    benchmark_host=host,
                    stdout=io.StringIO(),
                    stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertIn(expected, stderr.getvalue())
                self.assertNotIn("SECRET", stderr.getvalue())

    def test_host_errors_and_invalid_plan_values_are_redacted(self) -> None:
        for host in (SecretFailingBenchmarkHost(), InvalidPlanBenchmarkHost()):
            with self.subTest(type(host).__name__):
                stderr = io.StringIO()
                code = asterion_main(
                    [
                        "benchmark",
                        "plan",
                        "--application",
                        "example.application@1.0.0",
                        "--suite",
                        "example.suite@1.0.0",
                    ],
                    benchmark_host=host,
                    stdout=io.StringIO(),
                    stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertNotIn("SECRET", stderr.getvalue())
                self.assertIn("benchmark host command failed", stderr.getvalue())

    def test_help_describes_bounded_defaults_and_external_authorization(self) -> None:
        stdout = io.StringIO()
        code = asterion_main(
            ["benchmark", "plan", "--help"],
            benchmark_host=RecordingBenchmarkHost(),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        help_text = stdout.getvalue()
        self.assertIn("bounded", help_text)
        self.assertIn("external authorization", help_text)
        self.assertIn("--case-limit", help_text)
        self.assertNotIn("--amount", help_text)
        self.assertNotIn("--provider", help_text)


class RecordingBenchmarkHost:
    def __init__(
        self,
        *,
        run_result: BenchmarkRunResult | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.evidence_roots: list[Path] = []
        self.resume_run_ids: list[str] = []
        self.run_result = run_result or BenchmarkRunResult(
            status="completed",
            tasks=(
                BenchmarkTaskResult(
                    task_id="example.alpha",
                    status="completed",
                    case_count=1,
                ),
            ),
        )

    def discover_metadata(
        self,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object:
        self.calls.append("discover_metadata")
        self.application_ref = application_ref
        self.suite_ref = suite_ref
        return object()

    def resolve_source_lock(self, source_lock: Path | None) -> object:
        self.calls.append("resolve_source_lock")
        self.source_lock = source_lock
        return object()

    def open_selected_payloads(self, metadata: object, source_lock: object) -> object:
        del metadata, source_lock
        self.calls.append("open_selected_payloads")
        return object()

    def resolve_application(
        self,
        payloads: object,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
    ) -> object:
        del payloads, application_ref, suite_ref
        self.calls.append("resolve_application")
        return object()

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
        del resolved, application_ref, suite_ref, authorization
        self.calls.append("create_plan")
        if resume_run_id is not None:
            self.resume_run_ids.append(resume_run_id)
        selected_case_limit = 10 if case_limit is None else case_limit
        return ResolvedBenchmarkPlan(
            run_id=resume_run_id or (
                "run-auth-001" if execute else "run-plan-001"
            ),
            application_ref=ApplicationRef("example.application", "1.0.0"),
            suite=BenchmarkSuiteManifest(
                suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
                owner_package=CapabilityPackageRef("example.package", "1.0.0"),
                tasks=(),
                artifact_media_types=("application/json",),
                default_case_limit=10,
                default_concurrency=1,
            ),
            tasks=(),
            case_limit=selected_case_limit,
            package_locks=(),
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
        del application_ref, suite_ref, case_limit, resume_run_id
        self.calls.append("authorize_execution")
        self.evidence_roots.append(evidence_root)
        return HostAuthorization()

    def load_selected_providers(self, payloads: object, authorization: object) -> object:
        del payloads, authorization
        self.calls.append("load_selected_providers")
        return object()

    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        providers: object,
        *,
        evidence_root: Path,
    ) -> BenchmarkRunResult:
        del plan, providers, evidence_root
        self.calls.append("run")
        return self.run_result


class HostAuthorization:
    pass


class SecretFailingBenchmarkHost(RecordingBenchmarkHost):
    def create_plan(self, *args: object, **kwargs: object) -> ResolvedBenchmarkPlan:
        del args, kwargs
        raise BenchmarkCliError("SECRET-/private/operator/path")


class InvalidPlanBenchmarkHost(RecordingBenchmarkHost):
    def create_plan(self, *args: object, **kwargs: object) -> ResolvedBenchmarkPlan:
        del args, kwargs
        raise TypeError("SECRET-invalid-plan")


if __name__ == "__main__":
    unittest.main()
