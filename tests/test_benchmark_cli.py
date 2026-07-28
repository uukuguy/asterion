from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.benchmarks.evidence import BenchmarkTaskResult
from asterion.benchmarks.model import (
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
    CapabilityPackageCandidate,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.cli import _parser, main


_FIXTURE_SUITE = (
    Path(__file__).parent / "fixtures/benchmarks/valid-suite.json"
)
_APPLICATION = "example.application@1.0.0"
_SUITE = "example.synthetic-suite@1.0.0"
_OWNER = CapabilityPackageRef("example.benchmark-package", "1.0.0")
_CAPABILITY_A = CapabilityRef("example.capability-a", "1.0.0")
_CAPABILITY_B = CapabilityRef("example.capability-b", "1.0.0")


class _ExplodingEntryPoint:
    group = "asterion.applications"
    name = "private-provider"

    def __init__(self) -> None:
        self.loads = 0

    def load(self) -> object:
        self.loads += 1
        raise AssertionError("PRIVATE-PROVIDER-IMPORT")


class _ExplodingSource:
    def discover_metadata(self) -> tuple[object, ...]:
        raise AssertionError("PRIVATE-SOURCE-DISCOVERY")


class _ApplicationEntryPoint:
    group = "asterion.applications"

    def __init__(
        self,
        provider: InstalledApplicationProvider,
        *,
        name: str = "example.metadata",
    ) -> None:
        self.provider = provider
        self.name = name
        self.loads = 0

    def load(self):
        self.loads += 1
        return lambda: self.provider


class _TaskImplementation:
    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=request.task_id.replace(".task-", ".binding-"),
            public_arguments=("synthetic",),
            private_payload=request,
        )


class _CompletingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, invocation, *, cancellation, on_progress):
        del cancellation, on_progress
        self.calls.append(invocation.task_id)
        request = invocation.private_payload
        return BenchmarkTaskResult(
            task_id=invocation.task_id,
            status="completed",
            completed_cases=request.case_limit,
            content_digests=(),
            private_payload=None,
        )


class _InterruptingExecutor:
    def execute(self, invocation, *, cancellation, on_progress):
        del invocation, cancellation, on_progress
        raise KeyboardInterrupt


class _BenchmarkSource:
    def __init__(
        self,
        payload: PortableCapabilityPayload,
        package: InstalledCapabilityPackage,
        *,
        stdout: io.StringIO,
    ) -> None:
        self.payload = payload
        self.package = package
        self.stdout = stdout
        self.calls: list[str] = []

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        self.calls.append("discover")
        return (
            CapabilityPackageCandidate(
                package_ref=_OWNER,
                source_id="example.source",
                source_kind="builtin",
                payload_sha256="a" * 64,
                metadata={},
            ),
        )

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        self.calls.append("open-payload")
        self.assert_candidate(candidate)
        return self.payload

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        self.calls.append("validate-source")
        self.assert_candidate(candidate)
        if payload is not self.payload:
            raise AssertionError("PRIVATE-WRONG-PAYLOAD")

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        self.calls.append("load-provider")
        self.assert_candidate(candidate)
        if f'"application":"{_APPLICATION}"' not in self.stdout.getvalue():
            raise AssertionError("provider loaded before public plan")
        return self.package

    def assert_candidate(self, candidate: CapabilityPackageCandidate) -> None:
        if (
            candidate.package_ref != _OWNER
            or candidate.source_id != "example.source"
        ):
            raise AssertionError("PRIVATE-WRONG-CANDIDATE")


class BenchmarkCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _host_fixture(
        self,
        stdout: io.StringIO,
    ) -> tuple[_ApplicationEntryPoint, _BenchmarkSource]:
        payload_root = self.root / "payload"
        capability_root = payload_root / "capabilities"
        suite_root = payload_root / "benchmark-suites"
        capability_root.mkdir(parents=True)
        suite_root.mkdir()
        for name, ref in (
            ("a.json", _CAPABILITY_A),
            ("b.json", _CAPABILITY_B),
        ):
            (capability_root / name).write_text(
                json.dumps(
                    {
                        "protocol": "asterion.capability/v1",
                        "capability_id": ref.capability_id,
                        "version": ref.version,
                        "kind": "evaluation",
                        "requires_capabilities": [],
                        "provides_capabilities": [],
                        "requires_policies": [],
                        "consumes_events": [],
                        "emits_events": [],
                        "consumes_artifacts": [],
                        "produces_artifacts": [],
                    }
                ),
                encoding="utf-8",
            )
        suite_path = suite_root / "suite.json"
        shutil.copyfile(_FIXTURE_SUITE, suite_path)
        assembly_path = self.root / "assemblies/application.json"
        assembly_path.parent.mkdir()
        assembly_path.write_text(
            json.dumps(
                {
                    "protocol": "asterion.application-assembly/v1",
                    "application_id": "example.application",
                    "version": "1.0.0",
                    "runtime_id": "example.runtime",
                    "capability_packages": [
                        {
                            "package_id": _OWNER.package_id,
                            "version": _OWNER.version,
                        }
                    ],
                    "capabilities": [
                        {
                            "capability_id": ref.capability_id,
                            "version": ref.version,
                        }
                        for ref in (_CAPABILITY_A, _CAPABILITY_B)
                    ],
                    "host_capabilities": [],
                    "host_policies": [],
                    "host_events": [],
                    "host_artifacts": [],
                }
            ),
            encoding="utf-8",
        )
        provider = InstalledApplicationProvider(
            protocol=APPLICATION_PROVIDER_PROTOCOL,
            provider_id="example.metadata",
            resource_root=self.root,
            applications=(
                InstalledApplication(
                    application_id="example.application",
                    version="1.0.0",
                    assembly_paths=(assembly_path,),
                    capability_packages=(_OWNER,),
                    runtime_ids=("example.runtime",),
                ),
            ),
        )
        payload = PortableCapabilityPayload(
            manifest=CapabilityPackageManifest(
                package_ref=_OWNER,
                capabilities=(_CAPABILITY_A, _CAPABILITY_B),
                benchmark_suites=(
                    BenchmarkSuiteRef("example.synthetic-suite", "1.0.0"),
                ),
                resources=(),
            ),
            payload_sha256="a" * 64,
            resource_root=payload_root,
        )
        package = InstalledCapabilityPackage(
            package_ref=_OWNER,
            payload_sha256="a" * 64,
            source_id="example.source",
            source_kind="builtin",
            catalog_roots=(capability_root.resolve(strict=True),),
            benchmark_suite_paths=(suite_path.resolve(strict=True),),
            implementations=(),
            benchmark_bindings=(
                BenchmarkTaskBinding(
                    owner_package=_OWNER,
                    binding_id="example.binding-a",
                    implementation=_TaskImplementation(),
                ),
                BenchmarkTaskBinding(
                    owner_package=_OWNER,
                    binding_id="example.binding-b",
                    implementation=_TaskImplementation(),
                ),
            ),
        )
        return (
            _ApplicationEntryPoint(provider),
            _BenchmarkSource(payload, package, stdout=stdout),
        )

    def test_plan_help_is_available(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main(["benchmark", "plan", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("bounded", stdout.getvalue())

    def test_help_states_bounded_defaults_and_external_authorization(self) -> None:
        cases = (
            (["benchmark", "plan", "--help"], "finite bounded default"),
            (["benchmark", "run", "--help"], "external authorization"),
            (["benchmark", "resume", "--help"], "external authorization"),
        )
        for argv, expected in cases:
            with self.subTest(command=argv[1]):
                stdout = io.StringIO()
                with self.assertRaises(SystemExit) as raised:
                    with contextlib.redirect_stdout(stdout):
                        _parser().parse_args(argv)
                self.assertEqual(raised.exception.code, 0)
                self.assertIn(expected, stdout.getvalue())

    def test_commands_reject_domain_provider_cost_and_environment_arguments(
        self,
    ) -> None:
        forbidden = (
            "--dataset",
            "--corpus",
            "--launcher",
            "--prompt",
            "--provider",
            "--amount",
            "--cost",
            "--env-file",
        )
        base = [
            "benchmark",
            "plan",
            "--application",
            _APPLICATION,
            "--suite",
            _SUITE,
        ]
        for option in forbidden:
            with self.subTest(option=option):
                with self.assertRaises(SystemExit) as raised:
                    with contextlib.redirect_stderr(io.StringIO()):
                        _parser().parse_args([*base, option, "PRIVATE-VALUE"])
                self.assertEqual(raised.exception.code, 2)

    def test_run_and_resume_require_execute_before_provider_or_source_loading(
        self,
    ) -> None:
        for command in ("run", "resume"):
            with self.subTest(command=command):
                entry = _ExplodingEntryPoint()
                stdout = io.StringIO()
                stderr = io.StringIO()
                argv = [
                    "benchmark",
                    command,
                    "--application",
                    "example.application@1.0.0",
                    "--suite",
                    "example.synthetic-suite@1.0.0",
                    "--evidence-root",
                    str(self.root / f"{command}-evidence"),
                ]
                if command == "resume":
                    argv.extend(("--run-id", "benchmark-existing"))
                try:
                    code = main(
                        argv,
                        entry_points=(entry,),
                        capability_package_sources=(_ExplodingSource(),),
                        stdout=stdout,
                        stderr=stderr,
                    )
                except Exception as error:  # pragma: no cover - improves RED output
                    self.fail(
                        "benchmark authorization was not handled: "
                        f"{type(error)}"
                    )

                self.assertEqual(code, 2)
                self.assertEqual(entry.loads, 0)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(
                    stderr.getvalue(),
                    "asterion benchmark: --execute is required\n",
                )

    def test_plan_is_provider_free_and_creates_no_evidence(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        entry, source = self._host_fixture(stdout)
        evidence_root = self.root / "private-evidence"

        code = main(
            [
                "benchmark",
                "plan",
                "--application",
                _APPLICATION,
                "--suite",
                _SUITE,
                "--case-limit",
                "2",
                "--evidence-root",
                str(evidence_root),
            ],
            entry_points=(entry,),
            capability_package_sources=(source,),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["application"], _APPLICATION)
        self.assertEqual(plan["suite"], _SUITE)
        self.assertEqual(plan["case_limit"], 2)
        self.assertFalse(evidence_root.exists())
        self.assertEqual(
            source.calls,
            ["discover", "open-payload", "validate-source"],
        )
        self.assertNotIn("load-provider", source.calls)

    def test_application_ambiguity_is_stable_and_redacted(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        selected, source = self._host_fixture(stdout)
        adjacent_provider = replace(
            selected.provider,
            provider_id="other.metadata",
        )
        adjacent = _ApplicationEntryPoint(
            adjacent_provider,
            name="other.metadata",
        )

        code = main(
            [
                "benchmark",
                "plan",
                "--application",
                _APPLICATION,
                "--suite",
                _SUITE,
            ],
            entry_points=(selected, adjacent),
            capability_package_sources=(source,),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.getvalue(),
            "asterion benchmark: application selection failed\n",
        )
        self.assertNotIn(str(self.root), stderr.getvalue())
        self.assertEqual(source.calls, [])

    def test_source_and_suite_ambiguity_are_stable_and_redacted(self) -> None:
        base_root = self.root
        for ambiguity in ("source", "suite"):
            with self.subTest(ambiguity=ambiguity):
                self.root = base_root / ambiguity
                self.root.mkdir()
                stdout = io.StringIO()
                stderr = io.StringIO()
                entry, source = self._host_fixture(stdout)
                sources = (source, source) if ambiguity == "source" else (source,)
                if ambiguity == "suite":
                    shutil.copyfile(
                        _FIXTURE_SUITE,
                        self.root / "payload/benchmark-suites/duplicate.json",
                    )
                code = main(
                    [
                        "benchmark",
                        "plan",
                        "--application",
                        _APPLICATION,
                        "--suite",
                        _SUITE,
                    ],
                    entry_points=(entry,),
                    capability_package_sources=sources,
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertEqual(
                    stderr.getvalue(),
                    (
                        "asterion benchmark: capability source selection failed\n"
                        if ambiguity == "source"
                        else "asterion benchmark: command failed\n"
                    ),
                )
                self.assertNotIn(str(self.root), stderr.getvalue())
                self.assertNotIn("PRIVATE", stderr.getvalue())
                self.assertNotIn("load-provider", source.calls)

    def test_execute_loads_selected_provider_only_after_the_printed_plan(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        entry, source = self._host_fixture(stdout)
        evidence_root = self.root / "private-evidence"
        executor = _CompletingExecutor()

        code = main(
            [
                "benchmark",
                "run",
                "--application",
                _APPLICATION,
                "--suite",
                _SUITE,
                "--case-limit",
                "2",
                "--evidence-root",
                str(evidence_root),
                "--execute",
            ],
            entry_points=(entry,),
            capability_package_sources=(source,),
            benchmark_task_executor=executor,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        output = stdout.getvalue().splitlines()
        self.assertEqual(len(output), 2)
        self.assertEqual(json.loads(output[0])["application"], _APPLICATION)
        self.assertEqual(json.loads(output[1])["status"], "completed")
        self.assertEqual(
            source.calls,
            [
                "discover",
                "open-payload",
                "validate-source",
                "load-provider",
            ],
        )
        self.assertEqual(
            executor.calls,
            ["example.task-a", "example.task-b"],
        )
        self.assertTrue(
            (evidence_root / json.loads(output[0])["run_id"] / "evidence.json").is_file()
        )

    def test_interrupt_returns_nonzero_after_cancellation_is_recorded(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        entry, source = self._host_fixture(stdout)
        evidence_root = self.root / "private-evidence"

        code = main(
            [
                "benchmark",
                "run",
                "--application",
                _APPLICATION,
                "--suite",
                _SUITE,
                "--case-limit",
                "2",
                "--evidence-root",
                str(evidence_root),
                "--execute",
            ],
            entry_points=(entry,),
            capability_package_sources=(source,),
            benchmark_task_executor=_InterruptingExecutor(),
            stdout=stdout,
            stderr=stderr,
        )

        output = stdout.getvalue().splitlines()
        public_plan = json.loads(output[0])
        public_result = json.loads(output[1])
        evidence = json.loads(
            (
                evidence_root / public_plan["run_id"] / "evidence.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(code, 1)
        self.assertEqual(public_result["status"], "cancelled")
        self.assertEqual(evidence["status"], "cancelled")
        self.assertEqual(evidence["tasks"][0]["status"], "cancelled")
        self.assertNotIn("KeyboardInterrupt", stderr.getvalue())

    def test_resume_uses_exact_compatible_run_identity(self) -> None:
        first_stdout = io.StringIO()
        first_stderr = io.StringIO()
        entry, source = self._host_fixture(first_stdout)
        evidence_root = self.root / "private-evidence"
        executor = _CompletingExecutor()
        common = [
            "--application",
            _APPLICATION,
            "--suite",
            _SUITE,
            "--case-limit",
            "2",
            "--evidence-root",
            str(evidence_root),
            "--execute",
        ]

        first_code = main(
            ["benchmark", "run", *common],
            entry_points=(entry,),
            capability_package_sources=(source,),
            benchmark_task_executor=executor,
            stdout=first_stdout,
            stderr=first_stderr,
        )
        run_id = json.loads(first_stdout.getvalue().splitlines()[0])["run_id"]
        first_calls = tuple(executor.calls)
        resume_stdout = io.StringIO()
        source.stdout = resume_stdout
        resume_stderr = io.StringIO()

        resume_code = main(
            [
                "benchmark",
                "resume",
                *common,
                "--run-id",
                run_id,
            ],
            entry_points=(entry,),
            capability_package_sources=(source,),
            benchmark_task_executor=executor,
            stdout=resume_stdout,
            stderr=resume_stderr,
        )

        resumed = [
            json.loads(line) for line in resume_stdout.getvalue().splitlines()
        ]
        self.assertEqual(first_code, 0, first_stderr.getvalue())
        self.assertEqual(resume_code, 0, resume_stderr.getvalue())
        self.assertEqual(resumed[0]["run_id"], run_id)
        self.assertEqual(resumed[1]["status"], "completed")
        self.assertEqual(tuple(executor.calls), first_calls)


if __name__ == "__main__":
    unittest.main()
