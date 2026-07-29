from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from asterion.benchmarks.model import (
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedCapability,
)
from asterion.benchmarks.resolution import (
    BenchmarkResolutionError,
    resolve_benchmark_suite,
    resolve_benchmark_tasks,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    InstalledCapabilityPackage,
)


FIXTURES = Path(__file__).parent / "fixtures" / "benchmarks"
VALID_SUITE = FIXTURES / "valid-suite.json"
OTHER_SUITE = FIXTURES / "invalid-binding-suite.json"
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
OTHER_PACKAGE_REF = CapabilityPackageRef("other.package", "1.0.0")
SUITE_REF = BenchmarkSuiteRef("example.suite", "1.0.0")
OTHER_SUITE_REF = BenchmarkSuiteRef("example.other", "1.0.0")
ALPHA_REF = CapabilityRef("example.alpha", "1.0.0")
BETA_REF = CapabilityRef("example.beta", "1.0.0")
GAMMA_REF = CapabilityRef("example.gamma", "1.0.0")


class BenchmarkResolutionTests(unittest.TestCase):
    def test_resolves_valid_exact_suite_from_installed_package(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            suite = resolve_benchmark_suite(
                SUITE_REF,
                (installed_package(suite_dir),),
            )

        self.assertEqual(suite.suite_ref, SUITE_REF)
        self.assertEqual(suite.owner_package, PACKAGE_REF)
        self.assertEqual(
            tuple(task.task_id for task in suite.tasks),
            ("example.alpha", "example.beta"),
        )

    def test_rejects_missing_duplicate_owner_mismatch_and_invalid_suite_files(
        self,
    ) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            duplicate_dir = copy_fixture_suite(VALID_SUITE)
            wrong_owner_dir = copy_fixture_suite(
                VALID_SUITE,
                owner_package={
                    "package_id": OTHER_PACKAGE_REF.package_id,
                    "version": OTHER_PACKAGE_REF.version,
                },
            )
            invalid_dir = copy_fixture_suite(
                VALID_SUITE,
                protocol="asterion.benchmark-suite/v1",
                note="SECRET-SUITE-BODY",
            )
            invalid_file = invalid_dir / "valid-suite.json"
            value = json.loads(invalid_file.read_text())
            value["tasks"][0]["prompt"] = "SECRET-SUITE-BODY"
            invalid_file.write_text(json.dumps(value), encoding="utf-8")

            cases = (
                (
                    "missing suite",
                    SUITE_REF,
                    (installed_package(Path(tempfile.mkdtemp())),),
                    (),
                ),
                (
                    "duplicate exact suite",
                    SUITE_REF,
                    (installed_package(suite_dir), installed_package(duplicate_dir)),
                    (),
                ),
                (
                    "owner mismatch",
                    SUITE_REF,
                    (installed_package(wrong_owner_dir),),
                    (OTHER_PACKAGE_REF.package_id,),
                ),
                (
                    "invalid suite file",
                    SUITE_REF,
                    (installed_package(invalid_dir),),
                    ("SECRET-SUITE-BODY", str(invalid_file)),
                ),
            )
            for label, suite_ref, packages, sentinels in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkResolutionError) as context:
                        resolve_benchmark_suite(suite_ref, packages)
                    rendered = repr(context.exception)
                    for sentinel in sentinels:
                        self.assertNotIn(sentinel, rendered)

    def test_resolves_tasks_in_suite_order_independent_of_input_enumeration(
        self,
    ) -> None:
        with fixture_payload(VALID_SUITE, OTHER_SUITE) as suite_dir:
            suite = resolve_benchmark_suite(
                SUITE_REF,
                (installed_package(suite_dir),),
            )
            gamma_spy = SpyBenchmarkImplementation()
            package = installed_package(
                suite_dir,
                benchmark_bindings=(
                    binding("example.gamma", GAMMA_REF, implementation=gamma_spy),
                    binding("example.beta", BETA_REF),
                    binding("example.alpha", ALPHA_REF),
                ),
            )

            tasks = resolve_benchmark_tasks(
                suite,
                (
                    resolved_capability(BETA_REF),
                    resolved_capability(ALPHA_REF),
                    resolved_capability(GAMMA_REF),
                ),
                (package,),
            )

        self.assertEqual(tuple(task.ordinal for task in tasks), (1, 2))
        self.assertEqual(
            tuple(task.task.task_id for task in tasks),
            ("example.alpha", "example.beta"),
        )
        self.assertEqual(
            tuple(task.binding.binding_id for task in tasks),
            ("example.alpha", "example.beta"),
        )
        self.assertFalse(gamma_spy.called)

    def test_rejects_unselected_or_ambiguous_capabilities(self) -> None:
        suite = valid_suite_manifest()
        cases = (
            ("missing capability", (resolved_capability(ALPHA_REF),)),
            ("unselected capability", (resolved_capability(GAMMA_REF),)),
            (
                "duplicate capability",
                (
                    resolved_capability(ALPHA_REF),
                    resolved_capability(ALPHA_REF),
                    resolved_capability(BETA_REF),
                ),
            ),
        )
        for label, capabilities in cases:
            with self.subTest(label):
                with self.assertRaises(BenchmarkResolutionError):
                    resolve_benchmark_tasks(
                        suite,
                        capabilities,
                        (
                            installed_package(
                                FIXTURES,
                                benchmark_bindings=(
                                    binding("example.alpha", ALPHA_REF),
                                    binding("example.beta", BETA_REF),
                                ),
                            ),
                        ),
                    )

    def test_rejects_missing_duplicate_wrong_package_and_unknown_bindings(
        self,
    ) -> None:
        suite = valid_suite_manifest()
        with fixture_payload(VALID_SUITE) as suite_dir:
            cases = (
                (
                    "missing binding",
                    (
                        binding("example.alpha", ALPHA_REF),
                    ),
                ),
                (
                    "duplicate binding",
                    (
                        binding("example.alpha", ALPHA_REF),
                        binding("example.alpha", ALPHA_REF),
                        binding("example.beta", BETA_REF),
                    ),
                ),
                (
                    "wrong package binding",
                    (
                        binding("example.alpha", ALPHA_REF),
                        binding(
                            "example.beta",
                            BETA_REF,
                            owner_package=OTHER_PACKAGE_REF,
                        ),
                    ),
                ),
                (
                    "unknown extra binding",
                    (
                        binding("example.alpha", ALPHA_REF),
                        binding("example.beta", BETA_REF),
                        binding("example.unknown", ALPHA_REF),
                    ),
                ),
            )
            for label, bindings in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkResolutionError):
                        resolve_benchmark_tasks(
                            suite,
                            (resolved_capability(ALPHA_REF), resolved_capability(BETA_REF)),
                            (installed_package(suite_dir, benchmark_bindings=bindings),),
                        )

    def test_does_not_touch_provider_process_output_or_host_spies(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            spy = SpyBenchmarkImplementation()
            suite = resolve_benchmark_suite(
                SUITE_REF,
                (installed_package(suite_dir),),
            )
            resolve_benchmark_tasks(
                suite,
                (resolved_capability(ALPHA_REF), resolved_capability(BETA_REF)),
                (
                    installed_package(
                        suite_dir,
                        benchmark_bindings=(
                            binding("example.alpha", ALPHA_REF, implementation=spy),
                            binding("example.beta", BETA_REF),
                        ),
                    ),
                ),
            )

        self.assertFalse(spy.called)
        self.assertEqual(spy.forbidden_touches, ())


def valid_suite_manifest() -> BenchmarkSuiteManifest:
    with fixture_payload(VALID_SUITE) as suite_dir:
        return resolve_benchmark_suite(SUITE_REF, (installed_package(suite_dir),))


def resolved_capability(ref: CapabilityRef) -> ResolvedCapability:
    return ResolvedCapability(
        ref=ref,
        manifest={"capability_id": ref.capability_id, "version": ref.version},
    )


def binding(
    binding_id: str,
    capability_ref: CapabilityRef,
    *,
    owner_package: CapabilityPackageRef = PACKAGE_REF,
    implementation: object | None = None,
) -> BenchmarkTaskBinding:
    del capability_ref
    return BenchmarkTaskBinding(
        owner_package=owner_package,
        binding_id=binding_id,
        implementation=implementation if implementation is not None else SpyBenchmarkImplementation(),
    )


def installed_package(
    suite_dir: Path,
    *,
    package_ref: CapabilityPackageRef = PACKAGE_REF,
    benchmark_bindings: tuple[BenchmarkTaskBinding, ...] | None = None,
) -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256="a" * 64,
        source_id=f"{package_ref.package_id}.local-directory",
        source_kind="local-directory",
        catalog_roots=(),
        benchmark_suite_paths=(suite_dir,),
        implementations=(),
        benchmark_bindings=benchmark_bindings
        if benchmark_bindings is not None
        else (
            binding("example.alpha", ALPHA_REF, owner_package=package_ref),
            binding("example.beta", BETA_REF, owner_package=package_ref),
        ),
    )


class fixture_payload:
    def __init__(self, *suite_files: Path) -> None:
        self._suite_files = suite_files
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        self._temporary_directory = tempfile.TemporaryDirectory()
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


def copy_fixture_suite(suite_file: Path, **overrides: object) -> Path:
    target = tempfile.mkdtemp()
    suite_dir = Path(target) / "benchmark-suites"
    suite_dir.mkdir()
    value = json.loads(suite_file.read_text())
    value.update(overrides)
    (suite_dir / suite_file.name).write_text(json.dumps(value), encoding="utf-8")
    return suite_dir


class SpyBenchmarkImplementation:
    def __init__(self) -> None:
        self.called = False
        self.forbidden_touches: tuple[str, ...] = ()

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        del request
        self.called = True
        raise AssertionError("SECRET-IMPLEMENTATION-CALLED")

    def provider(self) -> None:
        self.forbidden_touches += ("provider",)
        raise AssertionError("SECRET-PROVIDER-TOUCHED")

    def process(self) -> None:
        self.forbidden_touches += ("process",)
        raise AssertionError("SECRET-PROCESS-TOUCHED")

    def output_directory(self) -> None:
        self.forbidden_touches += ("output",)
        raise AssertionError("SECRET-OUTPUT-TOUCHED")

    def host_services(self) -> None:
        self.forbidden_touches += ("host",)
        raise AssertionError("SECRET-HOST-TOUCHED")


if __name__ == "__main__":
    unittest.main()
