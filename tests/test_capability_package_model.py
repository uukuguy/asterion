from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_packages import (
    SOURCE_KINDS,
    BenchmarkTaskBinding,
    CapabilityPackageCandidate,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    CapabilityPackageSource,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)


class CapabilityPackageModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package_ref = CapabilityPackageRef("example.package", "1.0.0")
        self.manifest = CapabilityPackageManifest(
            package_ref=self.package_ref,
            capabilities=(),
            benchmark_suites=(),
            resources=(),
        )

    def test_candidate_is_frozen_slotted_and_copies_only_safe_metadata(
        self,
    ) -> None:
        metadata = {
            "distribution_version": 7,
            "private_locator": "/operator/private/package",
            "distribution_name": "example-distribution",
            "provider_factory": "private.module:create_provider",
        }

        candidate = CapabilityPackageCandidate(
            package_ref=self.package_ref,
            source_id="example.source",
            source_kind="python-distribution",
            payload_sha256=None,
            metadata=metadata,
        )
        metadata["distribution_name"] = "changed-distribution"

        self.assertEqual(
            dict(candidate.metadata),
            {
                "distribution_name": "example-distribution",
                "distribution_version": "7",
            },
        )
        self.assertFalse(hasattr(candidate, "__dict__"))
        with self.assertRaises(TypeError):
            candidate.metadata["distribution_name"] = "changed"  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            candidate.source_kind = "builtin"  # type: ignore[misc]

    def test_candidate_repr_omits_locators_and_factory_names(self) -> None:
        locator = "/operator/private/package"
        factory = "private.module:create_provider"

        candidate = CapabilityPackageCandidate(
            package_ref=self.package_ref,
            source_id="example.source",
            source_kind="local-directory",
            payload_sha256="a" * 64,
            metadata={
                "locator": locator,
                "provider_factory": factory,
                "distribution_name": "safe-name",
            },
        )

        representation = repr(candidate)
        self.assertNotIn(locator, representation)
        self.assertNotIn(factory, representation)
        self.assertNotIn("locator", representation)
        self.assertNotIn("provider_factory", representation)
        self.assertIn("safe-name", representation)

    def test_candidate_accepts_only_reserved_source_kinds(self) -> None:
        self.assertEqual(
            SOURCE_KINDS,
            (
                "archive",
                "builtin",
                "local-directory",
                "python-distribution",
                "registry",
            ),
        )
        for source_kind in SOURCE_KINDS:
            with self.subTest(source_kind=source_kind):
                candidate = CapabilityPackageCandidate(
                    package_ref=self.package_ref,
                    source_id="example.source",
                    source_kind=source_kind,
                    payload_sha256=None,
                    metadata={},
                )
                self.assertEqual(candidate.source_kind, source_kind)

        with self.assertRaisesRegex(
            ValueError,
            "^capability package source kind is invalid$",
        ):
            CapabilityPackageCandidate(
                package_ref=self.package_ref,
                source_id="example.source",
                source_kind="unknown-source",
                payload_sha256=None,
                metadata={},
            )

    def test_payload_and_installed_values_are_frozen_and_slotted(self) -> None:
        payload = PortableCapabilityPayload(
            manifest=self.manifest,
            payload_sha256="a" * 64,
            resource_root=Path("/portable/package"),
        )
        capability_binding = CapabilityImplementationBinding(
            CapabilityRef("example.capability", "1.0.0"),
            object(),  # type: ignore[arg-type]
        )
        benchmark_binding = BenchmarkTaskBinding(
            owner_package=self.package_ref,
            binding_id="example.task",
            implementation=object(),
        )
        installed = InstalledCapabilityPackage(
            package_ref=self.package_ref,
            payload_sha256="a" * 64,
            source_id="example.source",
            source_kind="builtin",
            catalog_roots=(Path("/portable/package/catalog"),),
            benchmark_suite_paths=(Path("/portable/package/suite.json"),),
            implementations=(capability_binding,),
            benchmark_bindings=(benchmark_binding,),
        )

        self.assertFalse(hasattr(payload, "__dict__"))
        self.assertFalse(hasattr(benchmark_binding, "__dict__"))
        self.assertFalse(hasattr(installed, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            payload.payload_sha256 = "b" * 64  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            benchmark_binding.binding_id = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            installed.catalog_roots = ()  # type: ignore[misc]

    def test_opaque_benchmark_implementation_is_redacted_from_repr(self) -> None:
        class SecretImplementation:
            def __repr__(self) -> str:
                return "SECRET-BENCHMARK-IMPLEMENTATION"

        binding = BenchmarkTaskBinding(
            owner_package=self.package_ref,
            binding_id="example.task",
            implementation=SecretImplementation(),
        )

        self.assertNotIn("SECRET-BENCHMARK-IMPLEMENTATION", repr(binding))
        self.assertNotIn("implementation", repr(binding))

    def test_source_protocol_exposes_only_metadata_and_loading_operations(
        self,
    ) -> None:
        self.assertEqual(
            {
                name
                for name, value in vars(CapabilityPackageSource).items()
                if callable(value) and not name.startswith("_")
            },
            {
                "discover_metadata",
                "open_payload",
                "validate_source_identity",
                "load_provider",
            },
        )


if __name__ == "__main__":
    unittest.main()
