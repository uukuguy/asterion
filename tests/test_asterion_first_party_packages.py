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
    PRIME_IPYTHON_CODING_NATIVE_PACKAGE,
    PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,
    PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,
    PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE,
    builtin_capability_registrations,
    create_prime_bounded_autonomy_native_package,
    create_prime_recursive_workflow_native_package,
)
from asterion.capability_packages.protocol import CapabilityPackageRef


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
        self.assertEqual(package.implementations, ())
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
        self.assertEqual(package.implementations, ())
        self.assertEqual(package.benchmark_bindings, ())


if __name__ == "__main__":
    unittest.main()
