from __future__ import annotations

import json
import operator
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    CapabilityExecutionResult,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    run_capability_conformance,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capabilities.builtin import create_controlled_code_package


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "extensions" / "minimal" / "payload"


class ExplodingImplementation:
    called = False

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        type(self).called = True
        raise AssertionError("SECRET-EXECUTION-CALLED")

    def __repr__(self) -> str:
        return "<SECRET-IMPLEMENTATION /private/provider.py>"


class HostileInstalled:
    def __getattribute__(self, name: str) -> object:
        if name == "package_ref":
            raise RuntimeError("SECRET-PROVIDER-BODY")
        return super().__getattribute__(name)


class InterruptingInstalled:
    def __getattribute__(self, name: str) -> object:
        if name == "package_ref":
            raise KeyboardInterrupt("SECRET-INTERRUPT")
        return super().__getattribute__(name)


def copy_payload(target: Path) -> Path:
    target = target.parent.resolve() / target.name
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def installed_package(payload_root: Path, **overrides: object) -> InstalledCapabilityPackage:
    payload_sha256 = cast(str | None, overrides.pop("payload_sha256", None))
    if payload_sha256 is None:
        payload_sha256 = open_portable_payload(payload_root).payload_sha256
    package_ref = cast(
        CapabilityPackageRef,
        overrides.pop("package_ref", CapabilityPackageRef("example.package", "1.0.0")),
    )
    implementations = cast(object, overrides.pop("implementations", ()))
    benchmark_bindings = cast(
        object,
        overrides.pop(
            "benchmark_bindings",
            (
                BenchmarkTaskBinding(
                    owner_package=package_ref,
                    binding_id="example.task",
                    implementation=ExplodingImplementation(),
                ),
            ),
        ),
    )
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256=payload_sha256,
        source_id=cast(str, overrides.pop("source_id", "example.package.local-directory")),
        source_kind=cast(str, overrides.pop("source_kind", "local-directory")),
        catalog_roots=cast(
            Any,
            overrides.pop("catalog_roots", (payload_root / "capabilities",)),
        ),
        benchmark_suite_paths=cast(
            Any,
            overrides.pop("benchmark_suite_paths", (payload_root / "benchmark-suites",)),
        ),
        implementations=cast(Any, implementations),
        benchmark_bindings=cast(Any, benchmark_bindings),
    )


class CapabilityConformanceTests(unittest.TestCase):
    def test_builtin_controlled_code_package_passes_public_conformance(self) -> None:
        result = run_capability_conformance(create_controlled_code_package())

        self.assertTrue(result.passed, result.errors)

    def test_accepts_valid_provider_without_calling_opaque_implementations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = copy_payload(Path(temp_dir) / "payload")
            package = installed_package(
                payload_root,
                implementations=(
                    (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
                ),
            )

            result = run_capability_conformance(package)

        self.assertTrue(result.passed)
        self.assertEqual(result.errors, ())
        self.assertFalse(ExplodingImplementation.called)
        with self.assertRaises(AttributeError):
            cast(Any, result).passed = False
        with self.assertRaises(TypeError):
            operator.setitem(cast(Any, result.errors), 0, "changed")

    def test_reports_deterministic_safe_aggregate_for_identity_and_digest_failures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = copy_payload(Path(temp_dir) / "payload")
            package = installed_package(
                payload_root,
                package_ref=CapabilityPackageRef("other.package", "1.0.0"),
                payload_sha256="f" * 64,
                source_kind="python-distribution",
            )

            first = run_capability_conformance(package)
            second = run_capability_conformance(package)

        self.assertFalse(first.passed)
        self.assertEqual(first, second)
        self.assertEqual(
            first.errors,
            (
                "package identity does not match payload",
                "payload digest does not match payload",
            ),
        )
        rendered = repr(first)
        self.assertNotIn(str(payload_root), rendered)
        self.assertNotIn("/private", rendered)
        self.assertNotIn("SECRET", rendered)

    def test_rejects_missing_duplicate_and_unknown_executable_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = copy_payload(Path(temp_dir) / "payload")
            cases = {
                "missing": (),
                "duplicate": (
                    (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
                    (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
                ),
                "unknown": (
                    (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
                    (CapabilityRef("example.unknown", "1.0.0"), ExplodingImplementation()),
                ),
            }

            results = {
                name: run_capability_conformance(
                    installed_package(payload_root, implementations=bindings)
                )
                for name, bindings in cases.items()
            }

        self.assertEqual(results["missing"].errors, ("implementation binding is missing",))
        self.assertEqual(results["duplicate"].errors, ("implementation binding is duplicated",))
        self.assertEqual(results["unknown"].errors, ("implementation binding is unknown",))
        self.assertFalse(ExplodingImplementation.called)

    def test_rejects_incomplete_duplicate_and_wrong_owner_benchmark_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = copy_payload(Path(temp_dir) / "payload")
            cases = {
                "missing": (),
                "duplicate": (
                    BenchmarkTaskBinding(
                        CapabilityPackageRef("example.package", "1.0.0"),
                        "example.task",
                        ExplodingImplementation(),
                    ),
                    BenchmarkTaskBinding(
                        CapabilityPackageRef("example.package", "1.0.0"),
                        "example.task",
                        ExplodingImplementation(),
                    ),
                ),
                "wrong-owner": (
                    BenchmarkTaskBinding(
                        CapabilityPackageRef("other.package", "1.0.0"),
                        "example.task",
                        ExplodingImplementation(),
                    ),
                ),
            }

            results = {
                name: run_capability_conformance(
                    installed_package(
                        payload_root,
                        implementations=(
                            (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
                        ),
                        benchmark_bindings=bindings,
                    )
                )
                for name, bindings in cases.items()
            }

        self.assertEqual(results["missing"].errors, ("benchmark binding is missing",))
        self.assertEqual(results["duplicate"].errors, ("benchmark binding is duplicated",))
        self.assertEqual(
            results["wrong-owner"].errors,
            ("benchmark binding owner is invalid",),
        )

    def test_rejects_bodyless_conformance_vectors_and_manifest_closure_failures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = copy_payload(Path(temp_dir) / "payload")
            payload_sha256 = open_portable_payload(payload_root).payload_sha256
            vector = payload_root / "conformance" / "externalization.json"
            vector.write_text(
                json.dumps(
                    {
                        "case_ids": ["SECRET-CASE"],
                        "profile_id": "/private/profile",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            package = installed_package(
                payload_root,
                payload_sha256=payload_sha256,
                implementations=(
                    (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
                ),
            )

            result = run_capability_conformance(package)

        self.assertFalse(result.passed)
        self.assertIn("payload closure is invalid", result.errors)
        self.assertNotIn("SECRET-CASE", repr(result))
        self.assertNotIn("/private/profile", repr(result))

    def test_body_free_error_preserves_base_exception(self) -> None:
        result = run_capability_conformance(HostileInstalled())

        self.assertFalse(result.passed)
        self.assertEqual(result.errors, ("installed package value is invalid",))
        self.assertNotIn("SECRET-PROVIDER-BODY", repr(result))
        with self.assertRaises(KeyboardInterrupt):
            run_capability_conformance(InterruptingInstalled())


if __name__ == "__main__":
    unittest.main()
