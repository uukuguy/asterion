from __future__ import annotations

import operator
import unittest
from pathlib import Path
from typing import Any, cast

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityInvocation,
)
from asterion.capability_packages.model import (
    SOURCE_KINDS,
    BenchmarkTaskBinding,
    CapabilityPackageCandidate,
    CapabilityPackageModelError,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    ResourceIdentity,
)
from asterion.capability_packages.sources.base import CapabilityPackageSource


class SentinelImplementation:
    async def execute(
        self,
        invocation: CapabilityInvocation,
    ) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(events=(), artifacts=())

    def __repr__(self) -> str:
        return "<SECRET-FACTORY locator=/private/provider>"


class CandidateTests(unittest.TestCase):
    def test_candidate_is_frozen_and_metadata_is_an_immutable_safe_snapshot(self) -> None:
        metadata = {
            "factory": "SECRET_FACTORY",
            "distribution_version": 1,
            "distribution_name": "acme-secret",
            "private_locator": "/private/source",
        }
        candidate = CapabilityPackageCandidate(
            package_ref=CapabilityPackageRef("example.package", "1.0.0"),
            source_id="example.source",
            source_kind="python-distribution",
            payload_sha256="a" * 64,
            metadata=metadata,
        )
        metadata["distribution_name"] = "changed"

        self.assertEqual(
            candidate.metadata,
            {
                "distribution_name": "acme-secret",
                "distribution_version": "1",
            },
        )
        self.assertEqual(tuple(candidate.metadata), ("distribution_name", "distribution_version"))
        with self.assertRaises(TypeError):
            operator.setitem(cast(dict[str, str], candidate.metadata), "x", "y")
        with self.assertRaises(AttributeError):
            setattr(candidate, "source_kind", "builtin")

    def test_candidate_rejects_unknown_source_kind_with_body_free_error(self) -> None:
        with self.assertRaises(CapabilityPackageModelError) as raised:
            CapabilityPackageCandidate(
                package_ref=CapabilityPackageRef("example.package", "1.0.0"),
                source_id="example.source",
                source_kind="remote-registry://SECRET",
                payload_sha256=None,
                metadata={"distribution_name": "SECRET"},
            )

        message = str(raised.exception)
        self.assertNotIn("remote-registry://SECRET", message)
        self.assertNotIn("SECRET", message)

    def test_candidate_repr_is_body_free_but_registry_is_reserved_internally(self) -> None:
        self.assertEqual(
            SOURCE_KINDS,
            ("archive", "builtin", "local-directory", "python-distribution", "registry"),
        )
        candidate = CapabilityPackageCandidate(
            package_ref=CapabilityPackageRef("example.package", "1.0.0"),
            source_id="example.source",
            source_kind="registry",
            payload_sha256=None,
            metadata={
                "distribution_name": "SECRET-DIST",
                "distribution_version": "9.9.9",
                "locator": "/private/registry",
                "factory": "secret.module:create",
            },
        )

        rendered = repr(candidate)
        self.assertIn("example.package", rendered)
        self.assertIn("registry", rendered)
        self.assertNotIn("SECRET-DIST", rendered)
        self.assertNotIn("9.9.9", rendered)
        self.assertNotIn("/private/registry", rendered)
        self.assertNotIn("secret.module:create", rendered)


class PackageValueTests(unittest.TestCase):
    def test_payload_and_installed_package_hide_private_roots_and_implementations(self) -> None:
        manifest = CapabilityPackageManifest(
            package_ref=CapabilityPackageRef("example.package", "1.0.0"),
            capabilities=(CapabilityRef("example.capability", "1.0.0"),),
            benchmark_suites=(BenchmarkSuiteRef("example.suite", "1.0.0"),),
            resources=(
                ResourceIdentity(
                    "example.resource",
                    "application/json",
                    "b" * 64,
                ),
            ),
        )
        implementation = SentinelImplementation()
        payload = PortableCapabilityPayload(
            manifest=manifest,
            payload_sha256="c" * 64,
            resource_root=Path("/private/operator/payload"),
        )
        installed = InstalledCapabilityPackage(
            package_ref=manifest.package_ref,
            payload_sha256=payload.payload_sha256,
            source_id="example.source",
            source_kind="local-directory",
            catalog_roots=cast(Any, [Path("/private/catalog")]),
            benchmark_suite_paths=cast(Any, [Path("/private/suites")]),
            implementations=cast(Any, [
                CapabilityImplementationBinding(
                    CapabilityRef("example.capability", "1.0.0"),
                    implementation,
                )
            ]),
            benchmark_bindings=cast(Any, [
                BenchmarkTaskBinding(
                    owner_package=manifest.package_ref,
                    binding_id="example.binding",
                    implementation=implementation,
                )
            ]),
        )

        self.assertEqual(installed.catalog_roots, (Path("/private/catalog"),))
        self.assertEqual(installed.benchmark_suite_paths, (Path("/private/suites"),))
        with self.assertRaises(AttributeError):
            setattr(payload, "resource_root", Path("/changed"))
        with self.assertRaises(AttributeError):
            setattr(installed, "catalog_roots", ())
        for rendered in (repr(payload), repr(installed), repr(installed.benchmark_bindings[0])):
            self.assertNotIn("/private/operator/payload", rendered)
            self.assertNotIn("/private/catalog", rendered)
            self.assertNotIn("/private/suites", rendered)
            self.assertNotIn("SECRET-FACTORY", rendered)
            self.assertNotIn("/private/provider", rendered)

    def test_installed_package_defensively_copies_collections(self) -> None:
        roots = [Path("/private/catalog")]
        suites = [Path("/private/suites")]
        implementations = [
            CapabilityImplementationBinding(
                CapabilityRef("example.capability", "1.0.0"),
                SentinelImplementation(),
            )
        ]
        benchmark_bindings = [
            BenchmarkTaskBinding(
                CapabilityPackageRef("example.package", "1.0.0"),
                "example.binding",
                SentinelImplementation(),
            )
        ]
        installed = InstalledCapabilityPackage(
            package_ref=CapabilityPackageRef("example.package", "1.0.0"),
            payload_sha256="d" * 64,
            source_id="example.source",
            source_kind="builtin",
            catalog_roots=cast(Any, roots),
            benchmark_suite_paths=cast(Any, suites),
            implementations=cast(Any, implementations),
            benchmark_bindings=cast(Any, benchmark_bindings),
        )
        roots.append(Path("/changed"))
        suites.append(Path("/changed"))
        implementations.clear()
        benchmark_bindings.clear()

        self.assertEqual(installed.catalog_roots, (Path("/private/catalog"),))
        self.assertEqual(installed.benchmark_suite_paths, (Path("/private/suites"),))
        self.assertEqual(len(installed.implementations), 1)
        self.assertEqual(len(installed.benchmark_bindings), 1)


class SourceProtocolTests(unittest.TestCase):
    def test_source_protocol_declares_metadata_payload_identity_and_provider_boundaries(self) -> None:
        public_methods = {
            name
            for name, value in CapabilityPackageSource.__dict__.items()
            if not name.startswith("_") and callable(value)
        }

        self.assertEqual(
            public_methods,
            {
                "discover_metadata",
                "open_payload",
                "validate_source_identity",
                "load_provider",
            },
        )


if __name__ == "__main__":
    unittest.main()
