from __future__ import annotations

import shutil
import tempfile
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import overload

from asterion.applications import InstalledApplication, InstalledAssembly
from asterion.assembly.protocol import AssemblyPlan
from asterion.benchmarks.model import BenchmarkTaskInvocation, BenchmarkTaskRequest
from asterion.benchmarks.planning import (
    BenchmarkExecutionAuthorization,
    BenchmarkPlanningError,
    create_benchmark_plan,
    execute_benchmark_plan,
    render_public_benchmark_plan,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.composition import CapabilityComposition
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    InstalledCapabilityPackage,
)


FIXTURES = Path(__file__).parent / "fixtures" / "benchmarks"
VALID_SUITE = FIXTURES / "valid-suite.json"
APPLICATION_ID = "example.application"
APPLICATION_VERSION = "1.0.0"
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
OTHER_PACKAGE_REF = CapabilityPackageRef("other.package", "1.0.0")
SUITE_REF = BenchmarkSuiteRef("example.suite", "1.0.0")
ALPHA_REF = CapabilityRef("example.alpha", "1.0.0")
BETA_REF = CapabilityRef("example.beta", "1.0.0")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class BenchmarkPlanningTests(unittest.TestCase):
    def test_creates_plan_from_installed_application_without_execution_side_effects(
        self,
    ) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            alpha = SpyBenchmarkImplementation()
            beta = SpyBenchmarkImplementation()
            application = installed_application(
                installed_packages=(
                    other_package(),
                    benchmark_package(suite_dir, alpha=alpha, beta=beta),
                ),
            )

            plan = create_benchmark_plan(
                application,
                SUITE_REF,
                run_id="run-001",
            )

        self.assertEqual(plan.run_id, "run-001")
        self.assertEqual(plan.application_ref.selector, "example.application@1.0.0")
        self.assertEqual(plan.case_limit, 10)
        self.assertEqual(
            tuple(task.capability.ref for task in plan.tasks),
            (ALPHA_REF, BETA_REF),
        )
        self.assertEqual(
            tuple(entry.package_ref for entry in plan.package_locks[0].entries),
            (PACKAGE_REF, OTHER_PACKAGE_REF),
        )
        self.assertFalse(alpha.called)
        self.assertFalse(beta.called)
        rendered = render_public_benchmark_plan(plan)
        self.assertNotIn(b"SECRET", rendered)
        self.assertNotIn(str(suite_dir).encode(), rendered)

    def test_render_is_deterministic_across_package_order_and_absolute_roots(
        self,
    ) -> None:
        with fixture_payload(VALID_SUITE) as first_dir:
            first = create_benchmark_plan(
                installed_application(
                    installed_packages=(
                        other_package(),
                        benchmark_package(first_dir),
                    ),
                ),
                SUITE_REF,
                run_id="run-001",
            )
        with fixture_payload(VALID_SUITE) as second_dir:
            second = create_benchmark_plan(
                installed_application(
                    installed_packages=(
                        benchmark_package(second_dir),
                        other_package(),
                    ),
                ),
                SUITE_REF,
                run_id="run-001",
            )

        self.assertEqual(
            render_public_benchmark_plan(first),
            render_public_benchmark_plan(second),
        )

    def test_rejects_invalid_case_limits_against_suite_default(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            application = installed_application(
                installed_packages=(benchmark_package(suite_dir), other_package()),
            )
            for case_limit in (0, -1, 11):
                with self.subTest(case_limit=case_limit):
                    with self.assertRaises(BenchmarkPlanningError):
                        create_benchmark_plan(
                            application,
                            SUITE_REF,
                            run_id="run-001",
                            case_limit=case_limit,
                        )

    def test_rejects_application_closure_mismatches_body_free(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            cases = (
                (
                    "missing package",
                    installed_application(
                        capability_packages=(PACKAGE_REF, OTHER_PACKAGE_REF),
                        installed_packages=(benchmark_package(suite_dir),),
                    ),
                ),
                (
                    "assembly packages",
                    installed_application(
                        assembly_package_refs=(PACKAGE_REF,),
                        installed_packages=(
                            benchmark_package(suite_dir),
                            other_package(),
                        ),
                    ),
                ),
                (
                    "missing capability",
                    installed_application(
                        capability_refs=(ALPHA_REF,),
                        capability_manifests=(capability_manifest(ALPHA_REF),),
                        installed_packages=(
                            benchmark_package(suite_dir),
                            other_package(),
                        ),
                    ),
                ),
                (
                    "hostile",
                    hostile_application("SECRET-HOSTILE-APPLICATION"),
                ),
            )
            for label, application in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkPlanningError) as context:
                        create_benchmark_plan(
                            application,
                            SUITE_REF,
                            run_id="run-001",
                        )
                    self.assertIsNone(context.exception.__cause__)
                    self.assertTrue(context.exception.__suppress_context__)
                    self.assertNotIn("SECRET", repr(context.exception))

    def test_execution_requires_fresh_exact_host_authorization(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            alpha = SpyBenchmarkImplementation()
            beta = SpyBenchmarkImplementation()
            plan = create_benchmark_plan(
                installed_application(
                    installed_packages=(
                        benchmark_package(suite_dir, alpha=alpha, beta=beta),
                        other_package(),
                    ),
                ),
                SUITE_REF,
                run_id="run-001",
                case_limit=3,
            )

        authorization = BenchmarkExecutionAuthorization(
            application_ref=plan.application_ref,
            suite_ref=plan.suite.suite_ref,
            run_id=plan.run_id,
            case_limit=plan.case_limit,
            nonce="nonce-001",
            expires_at=NOW + timedelta(minutes=5),
        )

        invocations = execute_benchmark_plan(
            plan,
            authorization,
            output_directory=Path("/private/SECRET-output"),
            now=NOW,
        )

        self.assertEqual(tuple(invocation.task_id for invocation in invocations), ("example.alpha", "example.beta"))
        self.assertEqual(alpha.requests[0].run_id, "run-001")
        self.assertEqual(alpha.requests[0].case_limit, 3)
        self.assertEqual(str(alpha.requests[0].output_directory), "/private/SECRET-output")
        with self.assertRaises(BenchmarkPlanningError):
            execute_benchmark_plan(
                plan,
                authorization,
                output_directory=Path("/private/SECRET-output"),
                now=NOW,
            )

        rejected = (
            BenchmarkExecutionAuthorization(
                application_ref=plan.application_ref,
                suite_ref=plan.suite.suite_ref,
                run_id="run-002",
                case_limit=plan.case_limit,
                nonce="nonce-002",
                expires_at=NOW + timedelta(minutes=5),
            ),
            BenchmarkExecutionAuthorization(
                application_ref=plan.application_ref,
                suite_ref=plan.suite.suite_ref,
                run_id=plan.run_id,
                case_limit=plan.case_limit,
                nonce="nonce-003",
                expires_at=NOW - timedelta(seconds=1),
            ),
        )
        for invalid in rejected:
            with self.subTest(nonce=invalid.nonce):
                with self.assertRaises(BenchmarkPlanningError) as context:
                    execute_benchmark_plan(
                        plan,
                        invalid,
                        output_directory=Path("/private/SECRET-output"),
                        now=NOW,
                    )
                self.assertNotIn("SECRET", repr(context.exception))


def installed_application(
    *,
    capability_packages: tuple[CapabilityPackageRef, ...] = (
        PACKAGE_REF,
        OTHER_PACKAGE_REF,
    ),
    assembly_package_refs: tuple[CapabilityPackageRef, ...] = (
        PACKAGE_REF,
        OTHER_PACKAGE_REF,
    ),
    capability_refs: tuple[CapabilityRef, ...] = (ALPHA_REF, BETA_REF),
    capability_manifests: tuple[dict[str, object], ...] | None = None,
    installed_packages: tuple[InstalledCapabilityPackage, ...],
) -> InstalledApplication:
    plan = AssemblyPlan(
        application_id=APPLICATION_ID,
        version=APPLICATION_VERSION,
        runtime_id="python",
        capability_package_refs=assembly_package_refs,
        capability_refs=capability_refs,
        capability_manifests=capability_manifests
        if capability_manifests is not None
        else (capability_manifest(ALPHA_REF), capability_manifest(BETA_REF)),
        composition=CapabilityComposition(
            capability_ids=tuple(ref.capability_id for ref in capability_refs),
            provided_capabilities=(),
            emitted_events=(),
            produced_artifacts=(),
        ),
        runtime_capabilities=(),
        host_capabilities=(),
        host_events=(),
        host_artifacts=(),
    )
    return InstalledApplication(
        application_id=APPLICATION_ID,
        version=APPLICATION_VERSION,
        assembly_paths=(Path("/private/SECRET-assembly.json"),),
        capability_packages=capability_packages,
        runtime_ids=("python",),
        installed_packages=installed_packages,
        assemblies=(InstalledAssembly(runtime_id="python", path=Path("/private/SECRET-assembly.json"), plan=plan),),
    )


def capability_manifest(ref: CapabilityRef) -> dict[str, object]:
    return {
        "capability_id": ref.capability_id,
        "version": ref.version,
        "kind": "capability",
        "prompt": "SECRET-PROMPT-BODY",
    }


def benchmark_package(
    suite_dir: Path,
    *,
    alpha: SpyBenchmarkImplementation | None = None,
    beta: SpyBenchmarkImplementation | None = None,
) -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256="a" * 64,
        source_id="example.package.local-directory",
        source_kind="local-directory",
        catalog_roots=(),
        benchmark_suite_paths=(suite_dir,),
        implementations=(),
        benchmark_bindings=(
            binding("example.alpha", alpha),
            binding("example.beta", beta),
        ),
    )


def other_package() -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=OTHER_PACKAGE_REF,
        payload_sha256="b" * 64,
        source_id="other.package.local-directory",
        source_kind="local-directory",
        catalog_roots=(),
        benchmark_suite_paths=(),
        implementations=(),
        benchmark_bindings=(),
    )


def binding(
    binding_id: str,
    implementation: SpyBenchmarkImplementation | None,
) -> BenchmarkTaskBinding:
    return BenchmarkTaskBinding(
        owner_package=PACKAGE_REF,
        binding_id=binding_id,
        implementation=implementation if implementation is not None else SpyBenchmarkImplementation(),
    )


def hostile_application(secret: str) -> InstalledApplication:
    application = object.__new__(InstalledApplication)
    object.__setattr__(application, "application_id", APPLICATION_ID)
    object.__setattr__(application, "version", APPLICATION_VERSION)
    object.__setattr__(application, "capability_packages", HostileSequence(secret))
    object.__setattr__(application, "installed_packages", ())
    object.__setattr__(application, "assemblies", ())
    return application


class fixture_payload:
    def __init__(self, *suite_files: Path) -> None:
        self._suite_files = suite_files
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        self._temporary_directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        suite_dir = Path(self._temporary_directory.name) / "benchmark-suites"
        suite_dir.mkdir()
        for suite_file in self._suite_files:
            shutil.copy2(suite_file, suite_dir / suite_file.name)
        return suite_dir

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        assert self._temporary_directory is not None
        self._temporary_directory.cleanup()


class SpyBenchmarkImplementation:
    def __init__(self) -> None:
        self.called = False
        self.requests: list[BenchmarkTaskRequest] = []

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        self.called = True
        self.requests.append(request)
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=request.task_id,
            public_arguments=("case-limit", str(request.case_limit)),
            private_payload={"secret": "SECRET-PRIVATE-PAYLOAD"},
        )

    def __repr__(self) -> str:
        return "SECRET-IMPLEMENTATION"


class HostileSequence(Sequence[CapabilityPackageRef]):
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def __len__(self) -> int:
        raise RuntimeError(self.secret)

    @overload
    def __getitem__(self, index: int) -> CapabilityPackageRef: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[CapabilityPackageRef]: ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> CapabilityPackageRef | Sequence[CapabilityPackageRef]:
        del index
        raise RuntimeError(self.secret)

    def __iter__(self):
        raise RuntimeError(self.secret)

if __name__ == "__main__":
    unittest.main()
