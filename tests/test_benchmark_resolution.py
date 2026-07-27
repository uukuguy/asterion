from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkPlan,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedCapability,
)
from asterion.benchmarks.resolution import (
    BenchmarkResolutionError,
    plan_benchmark_tasks,
    resolve_benchmark_execution,
    resolve_benchmark_suite,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)


_FIXTURES = Path(__file__).parent / "fixtures/benchmarks"
_OWNER = CapabilityPackageRef("example.benchmark-package", "1.0.0")
_OTHER_OWNER = CapabilityPackageRef("example.other-package", "1.0.0")
_SUITE_REF = BenchmarkSuiteRef("example.synthetic-suite", "1.0.0")
_INVALID_BINDING_SUITE_REF = BenchmarkSuiteRef(
    "example.invalid-binding-suite",
    "1.0.0",
)
_CAPABILITY_A = CapabilityRef("example.capability-a", "1.0.0")
_CAPABILITY_B = CapabilityRef("example.capability-b", "1.0.0")
_OTHER_CAPABILITY = CapabilityRef("example.other-capability", "1.0.0")


class _ActivationSpies:
    def __init__(self) -> None:
        self.provider = Mock(
            side_effect=AssertionError("provider activated during resolution")
        )
        self.process = Mock(
            side_effect=AssertionError("process activated during resolution")
        )
        self.output_directory = Mock(
            side_effect=AssertionError(
                "output directory activated during resolution"
            )
        )
        self.host_service = Mock(
            side_effect=AssertionError(
                "host service activated during resolution"
            )
        )

    def assert_not_called(self) -> None:
        self.provider.assert_not_called()
        self.process.assert_not_called()
        self.output_directory.assert_not_called()
        self.host_service.assert_not_called()


class _ForbiddenTaskImplementation:
    def __init__(self, activations: _ActivationSpies) -> None:
        self.activations = activations

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        del request
        self.activations.provider()
        self.activations.process()
        self.activations.output_directory()
        self.activations.host_service()
        raise AssertionError("task implementation returned during resolution")


class BenchmarkResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.owner_catalog = self.root / "owner-payload/capabilities"
        self.other_catalog = self.root / "other-payload/capabilities"
        self.capability_a = self._capability(
            _CAPABILITY_A,
            self.owner_catalog,
        )
        self.capability_b = self._capability(
            _CAPABILITY_B,
            self.owner_catalog,
        )
        self.other_capability = self._capability(
            _OTHER_CAPABILITY,
            self.other_catalog,
        )
        self.activations = _ActivationSpies()

    def _capability(
        self,
        ref: CapabilityRef,
        catalog_root: Path,
    ) -> ResolvedCapability:
        return ResolvedCapability(
            ref=ref,
            source=catalog_root / f"{ref.capability_id}.json",
            manifest={
                "capability_id": ref.capability_id,
                "version": ref.version,
            },
        )

    def _payload(
        self,
        fixture_names: Iterable[str] = ("valid-suite.json",),
        *,
        package_ref: CapabilityPackageRef = _OWNER,
        capability_refs: tuple[CapabilityRef, ...] = (
            _CAPABILITY_A,
            _CAPABILITY_B,
        ),
        suite_refs: tuple[BenchmarkSuiteRef, ...] = (_SUITE_REF,),
    ) -> PortableCapabilityPayload:
        root = self.root / f"payload-{len(tuple(self.root.iterdir()))}"
        suite_root = root / "benchmark-suites"
        suite_root.mkdir(parents=True)
        for index, fixture_name in enumerate(fixture_names):
            shutil.copyfile(
                _FIXTURES / fixture_name,
                suite_root / f"{index}-{fixture_name}",
            )
        return PortableCapabilityPayload(
            manifest=CapabilityPackageManifest(
                package_ref=package_ref,
                capabilities=capability_refs,
                benchmark_suites=suite_refs,
                resources=(),
            ),
            payload_sha256="a" * 64,
            resource_root=root,
        )

    def _binding(
        self,
        binding_id: str,
        *,
        owner: CapabilityPackageRef = _OWNER,
    ) -> BenchmarkTaskBinding:
        return BenchmarkTaskBinding(
            owner_package=owner,
            binding_id=binding_id,
            implementation=_ForbiddenTaskImplementation(self.activations),
        )

    def _package(
        self,
        bindings: Iterable[BenchmarkTaskBinding],
        *,
        package_ref: CapabilityPackageRef = _OWNER,
        catalog_root: Path | None = None,
    ) -> InstalledCapabilityPackage:
        return InstalledCapabilityPackage(
            package_ref=package_ref,
            payload_sha256="a" * 64,
            source_id=(
                "example.source"
                if package_ref == _OWNER
                else f"{package_ref.package_id}.source"
            ),
            source_kind="builtin",
            catalog_roots=(
                self.owner_catalog if catalog_root is None else catalog_root,
            ),
            benchmark_suite_paths=(),
            implementations=(),
            benchmark_bindings=tuple(bindings),
        )

    def _plan(
        self,
        *,
        capabilities: tuple[ResolvedCapability, ...] | None = None,
        suite_ref: BenchmarkSuiteRef = _SUITE_REF,
        fixture_name: str = "valid-suite.json",
    ) -> BenchmarkPlan:
        capability_values = (
            (self.capability_a, self.capability_b)
            if capabilities is None
            else capabilities
        )
        suite = resolve_benchmark_suite(
            suite_ref,
            (
                self._payload(
                    (fixture_name,),
                    capability_refs=tuple(
                        capability.ref for capability in capability_values
                    ),
                    suite_refs=(suite_ref,),
                ),
            ),
        )
        return BenchmarkPlan(
            run_id="run-001",
            application_ref=ApplicationRef(
                "example.application",
                "1.0.0",
            ),
            suite=suite,
            tasks=plan_benchmark_tasks(suite, capability_values),
            case_limit=2,
            package_locks=(
                CapabilitySourceLock(
                    entries=(
                        CapabilitySourceLockEntry(
                            package_ref=_OWNER,
                            payload_sha256="a" * 64,
                            source_id="example.source",
                        ),
                    )
                ),
            ),
        )

    def test_metadata_resolution_rejects_incomplete_or_ambiguous_closure(
        self,
    ) -> None:
        missing_ref = BenchmarkSuiteRef("example.missing-suite", "1.0.0")
        cases = {
            "missing suite": (
                missing_ref,
                (self._payload(),),
            ),
            "duplicate exact suite": (
                _SUITE_REF,
                (
                    self._payload(
                        ("valid-suite.json", "valid-suite.json"),
                    ),
                ),
            ),
            "suite owner package mismatch": (
                _SUITE_REF,
                (
                    self._payload(package_ref=_OTHER_OWNER),
                ),
            ),
            "missing capability": (
                _SUITE_REF,
                (
                    self._payload(capability_refs=(_CAPABILITY_A,)),
                ),
            ),
        }

        with (
            patch.object(
                Path,
                "mkdir",
                side_effect=AssertionError("output directory activated"),
            ) as mkdir_spy,
            patch.object(
                subprocess,
                "Popen",
                side_effect=AssertionError("process activated"),
            ) as process_spy,
        ):
            for name, (suite_ref, payloads) in cases.items():
                with (
                    self.subTest(name=name),
                    self.assertRaises(BenchmarkResolutionError),
                ):
                    resolve_benchmark_suite(suite_ref, payloads)

        mkdir_spy.assert_not_called()
        process_spy.assert_not_called()
        self.activations.assert_not_called()

    def test_planning_requires_every_task_capability_selected_by_application(
        self,
    ) -> None:
        suite = resolve_benchmark_suite(_SUITE_REF, (self._payload(),))
        cases = {
            "capability not selected by application": (
                self.capability_a,
            ),
            "wrong exact capability selected": (
                self.capability_a,
                self.other_capability,
            ),
            "duplicate selected capability": (
                self.capability_a,
                self.capability_a,
                self.capability_b,
            ),
        }

        for name, capabilities in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaises(BenchmarkResolutionError),
            ):
                plan_benchmark_tasks(suite, capabilities)

        self.activations.assert_not_called()

    def test_metadata_planning_is_canonical_across_input_enumeration(
        self,
    ) -> None:
        suite = resolve_benchmark_suite(_SUITE_REF, (self._payload(),))

        planned = plan_benchmark_tasks(
            suite,
            (self.capability_b, self.capability_a),
        )

        self.assertEqual(
            tuple(
                (task.ordinal, task.task.task_id, task.capability.ref)
                for task in planned
            ),
            (
                (1, "example.task-a", _CAPABILITY_A),
                (2, "example.task-b", _CAPABILITY_B),
            ),
        )
        self.activations.assert_not_called()

    def test_execution_resolution_rejects_nonexact_binding_closure(
        self,
    ) -> None:
        plan = self._plan()
        binding_a = self._binding("example.binding-a")
        binding_b = self._binding("example.binding-b")
        cases = {
            "missing binding": (
                self._package((binding_a,)),
            ),
            "duplicate binding in one package": (
                self._package((binding_a, binding_a, binding_b)),
            ),
            "binding supplied by wrong package": (
                self._package((binding_b,)),
                self._package(
                    (
                        self._binding(
                            "example.binding-a",
                            owner=_OTHER_OWNER,
                        ),
                    ),
                    package_ref=_OTHER_OWNER,
                    catalog_root=self.other_catalog,
                ),
            ),
            "binding owner mismatch": (
                self._package(
                    (
                        self._binding(
                            "example.binding-a",
                            owner=_OTHER_OWNER,
                        ),
                        binding_b,
                    )
                ),
            ),
            "unknown extra binding": (
                self._package(
                    (
                        binding_a,
                        binding_b,
                        self._binding("example.extra-binding"),
                    )
                ),
            ),
        }

        with (
            patch.object(
                Path,
                "mkdir",
                side_effect=AssertionError("output directory activated"),
            ) as mkdir_spy,
            patch.object(
                subprocess,
                "Popen",
                side_effect=AssertionError("process activated"),
            ) as process_spy,
        ):
            for name, packages in cases.items():
                with (
                    self.subTest(name=name),
                    self.assertRaises(BenchmarkResolutionError),
                ):
                    resolve_benchmark_execution(plan, packages)

        mkdir_spy.assert_not_called()
        process_spy.assert_not_called()
        self.activations.assert_not_called()

    def test_execution_requires_capabilities_from_suite_owner_package(
        self,
    ) -> None:
        plan = self._plan(
            capabilities=(
                self._capability(_CAPABILITY_A, self.other_catalog),
                self.capability_b,
            ),
        )
        package = self._package(
            (
                self._binding("example.binding-a"),
                self._binding("example.binding-b"),
            )
        )

        with self.assertRaises(BenchmarkResolutionError):
            resolve_benchmark_execution(plan, (package,))

        self.activations.assert_not_called()

    def test_execution_rejects_installed_identity_not_matching_plan_lock_before_binding_attachment(
        self,
    ) -> None:
        plan = self._plan()
        package = self._package(
            (
                self._binding("example.binding-a"),
                self._binding("example.binding-b"),
            )
        )
        cases = {
            "payload digest mismatch": replace(
                package,
                payload_sha256="b" * 64,
            ),
            "source identity mismatch": replace(
                package,
                source_id="example.changed-source",
            ),
        }

        for name, changed in cases.items():
            with (
                self.subTest(name=name),
                patch(
                    "asterion.benchmarks.resolution.ResolvedBenchmarkTask",
                    side_effect=AssertionError(
                        "binding attached before package identity rejection"
                    ),
                ) as binding_spy,
                self.assertRaises(BenchmarkResolutionError),
            ):
                resolve_benchmark_execution(plan, (changed,))
            binding_spy.assert_not_called()

        self.activations.assert_not_called()

    def test_invalid_binding_fixture_fails_before_implementation_activation(
        self,
    ) -> None:
        plan = self._plan(
            capabilities=(self.capability_a,),
            suite_ref=_INVALID_BINDING_SUITE_REF,
            fixture_name="invalid-binding-suite.json",
        )
        package = self._package(
            (self._binding("example.different-binding"),)
        )

        with self.assertRaises(BenchmarkResolutionError):
            resolve_benchmark_execution(plan, (package,))

        self.activations.assert_not_called()

    def test_valid_exact_suite_and_bindings_resolve_without_activation(
        self,
    ) -> None:
        plan = self._plan()
        package = self._package(
            (
                self._binding("example.binding-b"),
                self._binding("example.binding-a"),
            )
        )

        resolved = resolve_benchmark_execution(plan, (package,))

        self.assertIs(resolved.plan, plan)
        self.assertEqual(
            tuple(
                (
                    task.planned.ordinal,
                    task.planned.task.task_id,
                    task.binding.binding_id,
                )
                for task in resolved.tasks
            ),
            (
                (1, "example.task-a", "example.binding-a"),
                (2, "example.task-b", "example.binding-b"),
            ),
        )
        self.activations.assert_not_called()


if __name__ == "__main__":
    unittest.main()
