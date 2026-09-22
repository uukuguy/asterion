"""Tests for the first-party capability-package registry (Phase 7, Task 11).

Asserts that every native Prime capability package — including the
P3 recursive-workflow package wired through Phase 7, Task 11 — is
present in the registry tuple, the package constant matches its
declared ``package_id``/``version``, and the factory function loads
the payload through the standard portable-payload path.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from asterion.applications.first_party_packages import (
    PRIME_ARC_AGI_3_SOLVER_PACKAGE,
    PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE,
    PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
    PRIME_IPYTHON_CODING_NATIVE_PACKAGE,
    PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,
    PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,
    PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE,
    builtin_capability_registrations,
    create_prime_bounded_autonomy_native_package,
    create_prime_continual_improvement_native_package,
    create_prime_recursive_workflow_native_package,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_sdk import CapabilityRef


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestFirstPartyPackagesRegistry(unittest.TestCase):
    def test_prime_native_package_constants_have_expected_refs(self) -> None:
        self.assertEqual(
            PRIME_IPYTHON_CODING_NATIVE_PACKAGE,
            CapabilityPackageRef("prime-ipython-coding-native", "1.0.0"),
        )
        self.assertEqual(
            PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,
            CapabilityPackageRef("prime-programmatic-long-context-native", "1.0.0"),
        )
        self.assertEqual(
            PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,
            CapabilityPackageRef("prime-long-session-continuity-native", "1.0.0"),
        )
        self.assertEqual(
            PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE,
            CapabilityPackageRef("prime-recursive-workflow-native", "1.0.0"),
        )
        self.assertEqual(
            PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE,
            CapabilityPackageRef("prime-bounded-autonomy-native", "1.0.0"),
        )
        self.assertEqual(
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
            CapabilityPackageRef("prime-continual-improvement-native", "1.0.0"),
        )

    def test_builtin_registry_includes_all_native_prime_packages(self) -> None:
        registered_refs = {
            registration.package_ref
            for registration in builtin_capability_registrations()
        }
        expected_refs = {
            PRIME_ARC_AGI_3_SOLVER_PACKAGE,
            PRIME_IPYTHON_CODING_NATIVE_PACKAGE,
            PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,
            PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,
            PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE,
            PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE,
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
        }
        self.assertTrue(
            expected_refs.issubset(registered_refs),
            f"missing native prime packages: "
            f"{expected_refs - registered_refs}",
        )

    def test_builtin_registry_p3_payload_path_matches_repo_layout(self) -> None:
        expected_payload_root = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_recursive_workflow_native/payload"
        )
        self.assertTrue(
            (expected_payload_root / "capability-package.json").is_file(),
            "P3 capability-package.json must exist on disk for registry wiring",
        )
        registrations = {
            registration.package_ref: registration
            for registration in builtin_capability_registrations()
        }
        p3_registration = registrations[PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE]
        self.assertEqual(p3_registration.payload_root, expected_payload_root)

    def test_builtin_registry_p5_payload_path_matches_repo_layout(self) -> None:
        expected_payload_root = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_bounded_autonomy_native/payload"
        )
        self.assertTrue(
            (expected_payload_root / "capability-package.json").is_file(),
            "P5 capability-package.json must exist on disk for registry wiring",
        )
        registrations = {
            registration.package_ref: registration
            for registration in builtin_capability_registrations()
        }
        p5_registration = registrations[PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE]
        self.assertEqual(p5_registration.payload_root, expected_payload_root)


class TestCreatePrimeRecursiveWorkflowNativePackage(unittest.TestCase):
    def test_factory_loads_p3_payload(self) -> None:
        package = create_prime_recursive_workflow_native_package()
        self.assertEqual(
            package.package_ref,
            CapabilityPackageRef("prime-recursive-workflow-native", "1.0.0"),
        )
        self.assertEqual(package.source_id, "prime-recursive-workflow-native.builtin")
        self.assertEqual(package.source_kind, "builtin")
        self.assertEqual(
            tuple(binding.capability_ref for binding in package.implementations),
            (CapabilityRef("prime.recursive-workflow", "1.0.0"),),
        )
        self.assertEqual(package.benchmark_bindings, ())


class TestCreatePrimeBoundedAutonomyNativePackage(unittest.TestCase):
    def test_factory_loads_p5_payload(self) -> None:
        package = create_prime_bounded_autonomy_native_package()
        self.assertEqual(
            package.package_ref,
            CapabilityPackageRef("prime-bounded-autonomy-native", "1.0.0"),
        )
        self.assertEqual(
            package.source_id, "prime-bounded-autonomy-native.builtin"
        )
        self.assertEqual(package.source_kind, "builtin")
        self.assertEqual(
            tuple(binding.capability_ref for binding in package.implementations),
            (CapabilityRef("prime.bounded-autonomy", "1.0.0"),),
        )
        self.assertEqual(package.benchmark_bindings, ())


class TestFirstPartyPackagesIncludesContinualImprovement(unittest.TestCase):
    """Phase 9, Task 11 — three-part lesson (mirror Phase 7 Task 11).

    Capability-package Python module + canonical-form JSON + factory
    shape are three required pieces, NOT just a registry dict entry.
    """

    def test_first_party_packages_includes_continual_improvement(self) -> None:
        registered_refs = {
            registration.package_ref
            for registration in builtin_capability_registrations()
        }
        self.assertIn(
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
            registered_refs,
            "P6 continual-improvement package must be registered in the "
            "first-party builtin capability registry",
        )

    def test_create_prime_continual_improvement_native_package_loads_payload_json(
        self,
    ) -> None:
        package = create_prime_continual_improvement_native_package()
        self.assertEqual(
            package.package_ref,
            CapabilityPackageRef(
                "prime-continual-improvement-native", "1.0.0"
            ),
        )
        self.assertEqual(
            package.source_id,
            "prime-continual-improvement-native.builtin",
        )
        self.assertEqual(package.source_kind, "builtin")
        self.assertEqual(
            tuple(binding.capability_ref for binding in package.implementations),
            (CapabilityRef("prime.continual-improvement", "1.0.0"),),
        )
        self.assertEqual(package.benchmark_bindings, ())

    def test_capability_package_module_three_part_requirement(self) -> None:
        # Part 1: capability-package Python module is importable.
        import asterion.capabilities.prime_continual_improvement_native as pkg_module

        self.assertTrue(
            hasattr(
                pkg_module,
                "create_prime_continual_improvement_native_package",
            ),
            "capability-package Python module must expose "
            "create_prime_continual_improvement_native_package factory",
        )

        # Part 1b: the package module's factory must succeed and return
        # an InstalledCapabilityPackage with the expected ref (proves
        # the module's factory actually builds a valid package — not
        # just that the symbol exists).
        package = pkg_module.create_prime_continual_improvement_native_package()
        self.assertEqual(
            package.package_ref,
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
            "capability-package module factory must build an "
            "InstalledCapabilityPackage with package_ref = "
            "prime-continual-improvement-native@1.0.0",
        )

        # Part 3: factory shape is registered in the builtin registry dict.
        registrations = {
            registration.package_ref: registration
            for registration in builtin_capability_registrations()
        }
        self.assertIn(
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
            registrations,
            "registry dict entry must be present (Phase 7 three-part lesson)",
        )
        # Registry's factory must build the same package when called —
        # this proves the wiring (not just the symbol presence).
        registry_factory = registrations[
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE
        ].provider_factory
        registry_package = registry_factory()
        self.assertEqual(
            registry_package.package_ref,
            PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
            "registry dict factory must produce a valid P6 package "
            "(proves the wiring, not just the symbol presence)",
        )
        self.assertEqual(
            registry_package.payload_sha256,
            package.payload_sha256,
            "registry dict factory and capability-package module factory "
            "must build the same payload (same payload_sha256)",
        )

    def test_capability_package_json_files_end_with_trailing_newline(self) -> None:
        payload_root = (
            REPO_ROOT
            / "src/asterion/capabilities/prime_continual_improvement_native/payload"
        )
        package_json = payload_root / "capability-package.json"
        capability_json = payload_root / "capabilities" / "prime-continual-improvement.json"

        self.assertTrue(package_json.is_file(), "P6 capability-package.json missing")
        self.assertTrue(capability_json.is_file(), "P6 capability JSON missing")

        # Phase 7 / Phase 9 lesson: open_portable_payload requires canonical
        # form, which mandates a single trailing newline (\n).
        self.assertTrue(
            package_json.read_bytes().endswith(b"\n"),
            "P6 capability-package.json must end with trailing newline (\\n)",
        )
        self.assertTrue(
            capability_json.read_bytes().endswith(b"\n"),
            "P6 prime-continual-improvement.json must end with trailing newline (\\n)",
        )


if __name__ == "__main__":
    unittest.main()
