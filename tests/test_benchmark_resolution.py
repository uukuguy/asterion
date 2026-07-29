from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import atexit
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import cast

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
TEMPORARY_ROOTS: list[Path] = []


def _cleanup_temporary_roots() -> None:
    for root in TEMPORARY_ROOTS:
        shutil.rmtree(root, ignore_errors=True)


atexit.register(_cleanup_temporary_roots)


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
                    (installed_package(empty_suite_dir()),),
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

    def test_rejects_duplicate_package_refs_and_any_duplicate_suite_ref(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            other_dir = copy_fixture_suite(OTHER_SUITE)
            other_package_dir = copy_fixture_suite(
                OTHER_SUITE,
                owner_package={
                    "package_id": OTHER_PACKAGE_REF.package_id,
                    "version": OTHER_PACKAGE_REF.version,
                },
            )
            third_package_ref = CapabilityPackageRef("third.package", "1.0.0")
            third_package_dir = copy_fixture_suite(
                OTHER_SUITE,
                owner_package={
                    "package_id": third_package_ref.package_id,
                    "version": third_package_ref.version,
                },
            )

            cases = (
                (
                    "duplicate package ref",
                    (
                        installed_package(suite_dir),
                        installed_package(other_dir),
                    ),
                ),
                (
                    "duplicate unselected suite ref across packages",
                    (
                        installed_package(suite_dir),
                        installed_package(
                            other_package_dir,
                            package_ref=OTHER_PACKAGE_REF,
                            benchmark_bindings=(),
                        ),
                        installed_package(
                            third_package_dir,
                            package_ref=third_package_ref,
                            benchmark_bindings=(),
                        ),
                    ),
                ),
                (
                    "duplicate suite ref in one package across roots",
                    (
                        installed_package(
                            suite_dir,
                            benchmark_suite_paths=(suite_dir, other_dir, other_dir),
                        ),
                    ),
                ),
            )
            for label, packages in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkResolutionError):
                        resolve_benchmark_suite(SUITE_REF, packages)

    def test_rejects_symlink_suite_roots_and_files(self) -> None:
        with fixture_payload(VALID_SUITE) as suite_dir:
            symlink_root = suite_dir.parent / "suite-root-link"
            symlink_file_dir = suite_dir.parent / "suite-file-link-root"
            symlink_file_dir.mkdir()
            try:
                os.symlink(suite_dir, symlink_root)
                os.symlink(VALID_SUITE, symlink_file_dir / "valid-suite.json")
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")

            cases = (
                ("symlink root", symlink_root),
                ("symlink file", symlink_file_dir),
            )
            for label, root in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkResolutionError):
                        resolve_benchmark_suite(
                            SUITE_REF,
                            (installed_package(root),),
                        )

    def test_rejects_invalid_utf8_and_oversized_suite_files_redacted(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            invalid_utf8_dir = Path(temp_dir) / "invalid-utf8"
            invalid_utf8_dir.mkdir()
            invalid_utf8_path = invalid_utf8_dir / "SECRET-UTF8.json"
            invalid_utf8_path.write_bytes(b"\xffSECRET-UTF8")

            oversized_dir = Path(temp_dir) / "oversized"
            oversized_dir.mkdir()
            oversized_path = oversized_dir / "SECRET-HUGE.json"
            oversized_path.write_bytes(
                VALID_SUITE.read_bytes() + (b" " * (1024 * 1024 + 1))
            )

            cases = (
                ("invalid utf8", invalid_utf8_dir, ("SECRET-UTF8",)),
                ("oversized suite", oversized_dir, ("SECRET-HUGE",)),
            )
            for label, root, sentinels in cases:
                with self.subTest(label):
                    with self.assertRaises(BenchmarkResolutionError) as context:
                        resolve_benchmark_suite(
                            SUITE_REF,
                            (installed_package(root),),
                        )
                    self.assertIsNone(context.exception.__cause__)
                    self.assertTrue(context.exception.__suppress_context__)
                    rendered = repr(context.exception)
                    for sentinel in sentinels:
                        self.assertNotIn(sentinel, rendered)

    def test_hostile_iterables_and_path_ops_are_redacted(self) -> None:
        cases = (
            (
                "package iterable",
                lambda: resolve_benchmark_suite(
                    SUITE_REF,
                    cast(Sequence[InstalledCapabilityPackage], HostilePackages()),
                ),
                ("SECRET-PACKAGE-ITER",),
            ),
            (
                "suite path operation",
                lambda: resolve_benchmark_suite(
                    SUITE_REF,
                    (hostile_installed_package(HostilePath("/private/SECRET-PATH")),),
                ),
                ("SECRET-PATH",),
            ),
        )
        for label, action, sentinels in cases:
            with self.subTest(label):
                with self.assertRaises(BenchmarkResolutionError) as context:
                    action()
                self.assertIsNone(context.exception.__cause__)
                self.assertTrue(context.exception.__suppress_context__)
                rendered = repr(context.exception)
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, rendered)

    def test_missing_fd_security_constants_import_but_public_api_fails_closed(
        self,
    ) -> None:
        script = """
import os
import sys
from pathlib import Path

mode, name = sys.argv[1:3]
if mode == "missing":
    if hasattr(os, name):
        delattr(os, name)
elif mode == "unsupported":
    setattr(os, name, frozenset())
else:
    raise AssertionError(f"unknown probe mode: {mode}")

from asterion.benchmarks.resolution import (
    BenchmarkResolutionError,
    resolve_benchmark_suite,
)
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    InstalledCapabilityPackage,
)

package = InstalledCapabilityPackage(
    package_ref=__import__("asterion.capability_packages", fromlist=["CapabilityPackageRef"]).CapabilityPackageRef("example.package", "1.0.0"),
    payload_sha256="a" * 64,
    source_id="example.package.local-directory",
    source_kind="local-directory",
    catalog_roots=(),
    benchmark_suite_paths=(Path("/private/SECRET-MISSING-FD-CONSTANT"),),
    implementations=(),
    benchmark_bindings=(),
)

try:
    resolve_benchmark_suite(BenchmarkSuiteRef("example.suite", "1.0.0"), (package,))
except BenchmarkResolutionError as error:
    rendered = repr(error)
    assert error.__cause__ is None
    assert error.__suppress_context__
    assert "SECRET-MISSING-FD-CONSTANT" not in rendered
    assert name not in rendered
else:
    raise AssertionError("resolver did not fail closed")
"""
        for mode, name in (
            ("missing", "O_DIRECTORY"),
            ("missing", "O_NOFOLLOW"),
            ("missing", "O_CLOEXEC"),
            ("unsupported", "supports_dir_fd"),
            ("unsupported", "supports_fd"),
            ("unsupported", "supports_follow_symlinks"),
        ):
            with self.subTest(name):
                result = subprocess.run(
                    [sys.executable, "-c", script, mode, name],
                    cwd=Path.cwd(),
                    env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )

    def test_resolves_tasks_in_suite_order_independent_of_input_enumeration(
        self,
    ) -> None:
        with fixture_payload(VALID_SUITE, OTHER_SUITE) as suite_dir:
            suite = resolve_benchmark_suite(
                SUITE_REF,
                (installed_package(suite_dir),),
            )
            package = installed_package(
                suite_dir,
                benchmark_bindings=(),
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
            tuple(task.task.binding_id for task in tasks),
            ("example.alpha", "example.beta"),
        )

    def test_rejects_forged_caller_suite_not_matching_installed_declaration(
        self,
    ) -> None:
        installed_suite = valid_suite_manifest()
        forged_suite = BenchmarkSuiteManifest(
            suite_ref=installed_suite.suite_ref,
            owner_package=installed_suite.owner_package,
            tasks=(installed_suite.tasks[0],),
            artifact_media_types=installed_suite.artifact_media_types,
            default_case_limit=installed_suite.default_case_limit,
            default_concurrency=installed_suite.default_concurrency,
        )
        with fixture_payload(VALID_SUITE) as suite_dir:
            with self.assertRaises(BenchmarkResolutionError):
                resolve_benchmark_tasks(
                    forged_suite,
                    (resolved_capability(ALPHA_REF), resolved_capability(BETA_REF)),
                    (
                        installed_package(
                            suite_dir,
                            benchmark_bindings=(
                                binding("example.alpha", ALPHA_REF),
                                binding("example.beta", BETA_REF),
                            ),
                        ),
                    ),
                )

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

    def test_task_resolution_does_not_require_or_inspect_live_bindings(
        self,
    ) -> None:
        suite = valid_suite_manifest()
        with fixture_payload(VALID_SUITE) as suite_dir:
            tasks = resolve_benchmark_tasks(
                suite,
                (resolved_capability(ALPHA_REF), resolved_capability(BETA_REF)),
                (installed_package(suite_dir, benchmark_bindings=()),),
            )

        self.assertEqual(
            tuple(task.task.binding_id for task in tasks),
            ("example.alpha", "example.beta"),
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
    benchmark_suite_paths: tuple[Path, ...] | None = None,
    benchmark_bindings: tuple[BenchmarkTaskBinding, ...] | None = None,
) -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256="a" * 64,
        source_id=f"{package_ref.package_id}.local-directory",
        source_kind="local-directory",
        catalog_roots=(),
        benchmark_suite_paths=benchmark_suite_paths
        if benchmark_suite_paths is not None
        else (suite_dir,),
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


def copy_fixture_suite(suite_file: Path, **overrides: object) -> Path:
    target = tempfile.mkdtemp(dir=Path.cwd())
    TEMPORARY_ROOTS.append(Path(target))
    suite_dir = Path(target) / "benchmark-suites"
    suite_dir.mkdir()
    value = json.loads(suite_file.read_text())
    value.update(overrides)
    (suite_dir / suite_file.name).write_text(json.dumps(value), encoding="utf-8")
    return suite_dir


def empty_suite_dir() -> Path:
    target = tempfile.mkdtemp(dir=Path.cwd())
    TEMPORARY_ROOTS.append(Path(target))
    suite_dir = Path(target) / "benchmark-suites"
    suite_dir.mkdir()
    return suite_dir


def hostile_installed_package(suite_root: Path) -> InstalledCapabilityPackage:
    package = object.__new__(InstalledCapabilityPackage)
    object.__setattr__(package, "package_ref", PACKAGE_REF)
    object.__setattr__(package, "payload_sha256", "a" * 64)
    object.__setattr__(package, "source_id", "example.package.local-directory")
    object.__setattr__(package, "source_kind", "local-directory")
    object.__setattr__(package, "catalog_roots", ())
    object.__setattr__(package, "benchmark_suite_paths", (suite_root,))
    object.__setattr__(package, "implementations", ())
    object.__setattr__(package, "benchmark_bindings", ())
    return package


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


class HostilePackages:
    def __iter__(self) -> object:
        raise RuntimeError("SECRET-PACKAGE-ITER")


class HostilePath(type(Path())):
    def iterdir(self) -> Generator[Path, None, None]:
        raise RuntimeError("SECRET-PATH-ITERDIR")

    def __fspath__(self) -> str:
        raise RuntimeError("SECRET-PATH-FSPATH")


if __name__ == "__main__":
    unittest.main()
