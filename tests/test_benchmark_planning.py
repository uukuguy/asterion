from __future__ import annotations

import shutil
import tempfile
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import overload
from unittest.mock import patch

import asterion.benchmarks as benchmarks
import asterion.benchmarks.planning as planning
from asterion.applications import InstalledApplication, InstalledAssembly
from asterion.assembly.protocol import AssemblyPlan
from asterion.benchmarks.model import ApplicationRef, BenchmarkTaskRequest
from asterion.benchmarks.planning import (
    BenchmarkExecutionAuthorization,
    BenchmarkPlanRequest,
    BenchmarkPlanningError,
    create_benchmark_plan,
    render_benchmark_plan,
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
APPLICATION_REF = ApplicationRef("example.application", "1.0.0")
OTHER_APPLICATION_REF = ApplicationRef("other.application", "1.0.0")
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
OTHER_PACKAGE_REF = CapabilityPackageRef("other.package", "1.0.0")
SUITE_REF = BenchmarkSuiteRef("example.suite", "1.0.0")
ALPHA_REF = CapabilityRef("example.alpha", "1.0.0")
BETA_REF = CapabilityRef("example.beta", "1.0.0")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class BenchmarkPlanningTests(unittest.TestCase):
    def test_plan_request_creates_body_free_plan_without_authority_or_side_effects(
        self,
    ) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            alpha = SpyBenchmarkImplementation()
            beta = SpyBenchmarkImplementation()
            application = installed_application()
            packages = (
                other_package(),
                benchmark_package(suite_dir, alpha=alpha, beta=beta),
            )
            request = BenchmarkPlanRequest(
                application_ref=APPLICATION_REF,
                suite_ref=SUITE_REF,
                case_limit=None,
                execute=False,
            )

            with patch.object(planning, "_new_run_id", return_value="run-plan-001") as run:
                plan = create_benchmark_plan(request, application, packages)

        run.assert_called_once_with()
        self.assertEqual(plan.run_id, "run-plan-001")
        self.assertEqual(plan.application_ref, APPLICATION_REF)
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
        rendered = render_benchmark_plan(plan)
        self.assertIsInstance(rendered, str)
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn(str(suite_dir), rendered)

    def test_render_is_deterministic_across_package_order_and_absolute_roots(
        self,
    ) -> None:
        request = BenchmarkPlanRequest(
            application_ref=APPLICATION_REF,
            suite_ref=SUITE_REF,
            case_limit=None,
            execute=False,
        )
        with fixture_payload(VALID_SUITE) as first_dir:
            with patch.object(planning, "_new_run_id", return_value="run-fixed"):
                first = create_benchmark_plan(
                    request,
                    installed_application(),
                    (other_package(), benchmark_package(first_dir)),
                )
        with fixture_payload(VALID_SUITE) as second_dir:
            with patch.object(planning, "_new_run_id", return_value="run-fixed"):
                second = create_benchmark_plan(
                    request,
                    installed_application(),
                    (benchmark_package(second_dir), other_package()),
                )

        self.assertEqual(
            render_benchmark_plan(first),
            render_benchmark_plan(second),
        )

    def test_plan_only_auth_does_not_grant_or_change_authority(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            authorization = issued_authorization(
                run_id="run-auth-001",
                case_limit=3,
            )
            request = BenchmarkPlanRequest(
                application_ref=APPLICATION_REF,
                suite_ref=SUITE_REF,
                case_limit=3,
                execute=False,
                authorization=authorization,
            )

            with patch.object(planning, "_new_run_id", return_value="run-plan-001"):
                plan = create_benchmark_plan(
                    request,
                    installed_application(),
                    (benchmark_package(suite_dir), other_package()),
                )

        self.assertEqual(plan.run_id, "run-plan-001")
        self.assertEqual(plan.case_limit, 3)
        self.assertNotIn("run-auth-001", render_benchmark_plan(plan))
        self.assertNotIn("nonce", repr(request))

    def test_execute_request_uses_exact_private_authorization_without_invocation(
        self,
    ) -> None:
        with self.assertRaisesRegex(TypeError, "host-issued"):
            BenchmarkExecutionAuthorization(
                application_ref=APPLICATION_REF,
                suite_ref=SUITE_REF,
                run_id="run-auth-001",
                case_limit=3,
                issued_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )

        with fixture_payload(VALID_SUITE) as suite_dir:
            alpha = SpyBenchmarkImplementation()
            beta = SpyBenchmarkImplementation()
            authorization = issued_authorization(
                run_id="run-auth-001",
                case_limit=3,
            )
            request = BenchmarkPlanRequest(
                application_ref=APPLICATION_REF,
                suite_ref=SUITE_REF,
                case_limit=3,
                execute=True,
                authorization=authorization,
            )

            with (
                patch.object(planning, "_utc_now", return_value=NOW),
                patch.object(
                    planning,
                    "_new_run_id",
                    side_effect=AssertionError("must not mint run id"),
                ),
            ):
                first = create_benchmark_plan(
                    request,
                    installed_application(),
                    (benchmark_package(suite_dir, alpha=alpha, beta=beta), other_package()),
                )
                second = create_benchmark_plan(
                    request,
                    installed_application(),
                    (other_package(), benchmark_package(suite_dir, alpha=alpha, beta=beta)),
                )

        self.assertEqual(first.run_id, "run-auth-001")
        self.assertEqual(second.run_id, "run-auth-001")
        self.assertFalse(alpha.called)
        self.assertFalse(beta.called)

    def test_rejects_invalid_or_stale_authorization_body_free(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            packages = (benchmark_package(suite_dir), other_package())
            cases = (
                (
                    "forged",
                    forged_authorization(run_id="run-auth-001", case_limit=3),
                    3,
                ),
                (
                    "future",
                    issued_authorization(
                        run_id="run-auth-002",
                        case_limit=3,
                        issued_at=NOW + timedelta(seconds=1),
                    ),
                    3,
                ),
                (
                    "expired",
                    issued_authorization(
                        run_id="run-auth-003",
                        case_limit=3,
                        expires_at=NOW - timedelta(seconds=1),
                    ),
                    3,
                ),
                (
                    "overlong",
                    issued_authorization(
                        run_id="run-auth-004",
                        case_limit=3,
                        expires_at=NOW + timedelta(hours=2),
                    ),
                    3,
                ),
                (
                    "case mismatch",
                    issued_authorization(run_id="run-auth-005", case_limit=4),
                    3,
                ),
            )
            for label, authorization, case_limit in cases:
                with self.subTest(label):
                    request = BenchmarkPlanRequest(
                        application_ref=APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=case_limit,
                        execute=True,
                        authorization=authorization,
                    )
                    with (
                        patch.object(planning, "_utc_now", return_value=NOW),
                        self.assertRaises(BenchmarkPlanningError) as context,
                    ):
                        create_benchmark_plan(request, installed_application(), packages)
                    self.assertIsNone(context.exception.__cause__)
                    self.assertTrue(context.exception.__suppress_context__)
                    self.assertNotIn("SECRET", repr(context.exception))

    def test_rejects_request_application_and_package_closure_mismatches(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            valid_packages = (benchmark_package(suite_dir), other_package())
            cases = (
                (
                    "application",
                    BenchmarkPlanRequest(
                        application_ref=OTHER_APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=None,
                        execute=False,
                    ),
                    installed_application(),
                    valid_packages,
                ),
                (
                    "missing explicit package",
                    BenchmarkPlanRequest(
                        application_ref=APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=None,
                        execute=False,
                    ),
                    installed_application(),
                    (benchmark_package(suite_dir),),
                ),
                (
                    "assembly package mismatch",
                    BenchmarkPlanRequest(
                        application_ref=APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=None,
                        execute=False,
                    ),
                    installed_application(assembly_package_refs=(PACKAGE_REF,)),
                    valid_packages,
                ),
                (
                    "missing capability",
                    BenchmarkPlanRequest(
                        application_ref=APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=None,
                        execute=False,
                    ),
                    installed_application(
                        capability_refs=(ALPHA_REF,),
                        capability_manifests=(capability_manifest(ALPHA_REF),),
                    ),
                    valid_packages,
                ),
                (
                    "hostile",
                    BenchmarkPlanRequest(
                        application_ref=APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=None,
                        execute=False,
                    ),
                    hostile_application("SECRET-HOSTILE-APPLICATION"),
                    valid_packages,
                ),
            )
            for label, request, application, packages in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkPlanningError) as context:
                        create_benchmark_plan(request, application, packages)
                    self.assertNotIn("SECRET", repr(context.exception))

    def test_rejects_case_limits_before_authorization_match(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            for case_limit in (0, -1, 11):
                with self.subTest(case_limit):
                    request = BenchmarkPlanRequest(
                        application_ref=APPLICATION_REF,
                        suite_ref=SUITE_REF,
                        case_limit=case_limit,
                        execute=True,
                        authorization=issued_authorization(
                            run_id="run-auth-001",
                            case_limit=3,
                        ),
                    )
                    with self.assertRaises(BenchmarkPlanningError):
                        create_benchmark_plan(
                            request,
                            installed_application(),
                            (benchmark_package(suite_dir), other_package()),
                        )

    def test_obsolete_execution_api_is_not_exported(self) -> None:
        self.assertFalse(hasattr(planning, "execute_benchmark_plan"))
        self.assertFalse(hasattr(benchmarks, "execute_benchmark_plan"))
        self.assertFalse(hasattr(planning, "render_public_benchmark_plan"))
        self.assertFalse(hasattr(benchmarks, "render_public_benchmark_plan"))


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
) -> InstalledApplication:
    plan = AssemblyPlan(
        application_id=APPLICATION_REF.application_id,
        version=APPLICATION_REF.version,
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
    application = InstalledApplication(
        application_id=APPLICATION_REF.application_id,
        version=APPLICATION_REF.version,
        assembly_paths=(Path("/private/SECRET-assembly.json"),),
        capability_packages=capability_packages,
        runtime_ids=("python",),
        installed_packages=(),
        assemblies=(
            InstalledAssembly(
                runtime_id="python",
                path=Path("/private/SECRET-assembly.json"),
                plan=plan,
            ),
        ),
    )
    object.__setattr__(
        application,
        "installed_packages",
        HostileSequence("SECRET-INSTALLED-PACKAGES"),
    )
    return application


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
        implementation=implementation
        if implementation is not None
        else SpyBenchmarkImplementation(),
    )


def issued_authorization(
    *,
    run_id: str,
    case_limit: int,
    issued_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=5),
) -> BenchmarkExecutionAuthorization:
    return planning._issue_benchmark_execution_authorization(
        application_ref=APPLICATION_REF,
        suite_ref=SUITE_REF,
        run_id=run_id,
        case_limit=case_limit,
        issued_at=issued_at,
        expires_at=expires_at,
        issuance_capability=planning._BENCHMARK_AUTHORIZATION_ISSUER,
    )


def forged_authorization(
    *,
    run_id: str,
    case_limit: int,
) -> BenchmarkExecutionAuthorization:
    authorization = object.__new__(BenchmarkExecutionAuthorization)
    object.__setattr__(authorization, "application_ref", APPLICATION_REF)
    object.__setattr__(authorization, "suite_ref", SUITE_REF)
    object.__setattr__(authorization, "run_id", run_id)
    object.__setattr__(authorization, "case_limit", case_limit)
    object.__setattr__(authorization, "issued_at", NOW)
    object.__setattr__(authorization, "expires_at", NOW + timedelta(minutes=5))
    object.__setattr__(authorization, "_issuance_capability", object())
    return authorization


def hostile_application(secret: str) -> InstalledApplication:
    application = object.__new__(InstalledApplication)
    object.__setattr__(application, "application_id", APPLICATION_REF.application_id)
    object.__setattr__(application, "version", APPLICATION_REF.version)
    object.__setattr__(application, "capability_packages", HostileSequence(secret))
    object.__setattr__(application, "runtime_ids", ("python",))
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

    def build_invocation(self, request: BenchmarkTaskRequest) -> object:
        self.called = True
        self.requests.append(request)
        raise AssertionError("SECRET-IMPLEMENTATION-CALLED")

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
