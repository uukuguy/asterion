from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.capabilities.builtin import create_controlled_code_package
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_packages.model import (
    BenchmarkTaskBinding,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_sdk import run_capability_conformance


PROJECT = Path(__file__).resolve().parents[1]
BUILTIN_PAYLOAD = (
    PROJECT / "src/asterion/capabilities/controlled_code/payload"
)


class _NeverExecute:
    async def execute(self, invocation):
        del invocation
        raise AssertionError("conformance executed a capability")


class CapabilityConformanceTests(unittest.TestCase):
    def test_valid_package_passes_without_provider_or_runtime_execution(self) -> None:
        installed = create_controlled_code_package()
        guarded = replace(
            installed,
            implementations=tuple(
                CapabilityImplementationBinding(
                    binding.capability_ref,
                    _NeverExecute(),
                )
                for binding in installed.implementations
            ),
        )

        self.assertIsNone(run_capability_conformance(guarded))

    def test_rejects_identity_binding_and_immutability_failures(self) -> None:
        installed = create_controlled_code_package()
        cases = {
            "package": replace(
                installed,
                package_ref=CapabilityPackageRef("other.package", "1.0.0"),
            ),
            "payload": replace(installed, payload_sha256="0" * 64),
            "mutable implementations": replace(
                installed,
                implementations=list(installed.implementations),  # type: ignore[arg-type]
            ),
            "missing implementation": replace(
                installed,
                implementations=installed.implementations[:-1],
            ),
            "duplicate implementation": replace(
                installed,
                implementations=(
                    *installed.implementations,
                    installed.implementations[0],
                ),
            ),
            "unknown implementation": replace(
                installed,
                implementations=(
                    *installed.implementations,
                    CapabilityImplementationBinding(
                        CapabilityRef("unknown.capability", "1.0.0"),
                        _NeverExecute(),
                    ),
                ),
            ),
        }
        for label, value in cases.items():
            with (
                self.subTest(case=label),
                self.assertRaisesRegex(
                    ValueError,
                    "^capability package conformance failed$",
                ),
            ):
                run_capability_conformance(value)

    def test_rejects_manifest_closure_and_fixture_vector_failures_body_free(
        self,
    ) -> None:
        sentinel = "SECRET-CONFORMANCE-BODY"
        with tempfile.TemporaryDirectory() as directory:
            payload_root = Path(directory).resolve() / sentinel
            shutil.copytree(BUILTIN_PAYLOAD, payload_root)
            profile_path = payload_root / "conformance/profile.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["case_ids"] = [*profile["case_ids"], sentinel]
            profile_path.write_text(
                json.dumps(profile, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            payload = open_portable_payload(payload_root)
            installed = _installed_for(payload_root, payload.payload_sha256)

            with self.assertRaises(ValueError) as raised:
                run_capability_conformance(installed)

        self.assertEqual(
            str(raised.exception),
            "capability package conformance failed",
        )
        self.assertNotIn(sentinel, repr(raised.exception))

    def test_rejects_benchmark_binding_incompleteness(self) -> None:
        fixture = PROJECT / "tests/fixtures/extensions/minimal/payload"
        installed = _minimal_installed(fixture)

        with self.assertRaisesRegex(
            ValueError,
            "^capability package conformance failed$",
        ):
            run_capability_conformance(
                replace(installed, benchmark_bindings=())
            )

    def test_valid_fixture_vectors_and_benchmark_bindings_pass(self) -> None:
        fixture = PROJECT / "tests/fixtures/extensions/minimal/payload"

        self.assertIsNone(run_capability_conformance(_minimal_installed(fixture)))

    def test_rejects_non_executable_capability_implementation(self) -> None:
        installed = create_controlled_code_package()
        invalid = replace(
            installed,
            implementations=(
                CapabilityImplementationBinding(
                    installed.implementations[0].capability_ref,
                    object(),  # type: ignore[arg-type]
                ),
                *installed.implementations[1:],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "^capability package conformance failed$",
        ):
            run_capability_conformance(invalid)

    def test_rejects_benchmark_task_outside_package_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory).resolve() / "payload"
            shutil.copytree(
                PROJECT / "tests/fixtures/extensions/minimal/payload",
                fixture,
            )
            suite_path = fixture / "benchmark-suites/example-benchmark.json"
            suite = json.loads(suite_path.read_text(encoding="utf-8"))
            suite["tasks"][0]["capability"]["capability_id"] = (
                "outside.package"
            )
            suite_path.write_text(
                json.dumps(suite, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            installed = _minimal_installed(fixture)

            with self.assertRaisesRegex(
                ValueError,
                "^capability package conformance failed$",
            ):
                run_capability_conformance(installed)


def _installed_for(
    payload_root: Path,
    payload_sha256: str,
) -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=CapabilityPackageRef("controlled-code", "1.0.0"),
        payload_sha256=payload_sha256,
        source_id="builtin.controlled-code.1.0.0",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=tuple(
            CapabilityImplementationBinding(ref, _NeverExecute())
            for ref in (
                CapabilityRef("evaluation.code-quality", "1.0.0"),
                CapabilityRef("observability.execution-audit", "1.0.0"),
                CapabilityRef("workflow.code-quality", "1.0.0"),
            )
        ),
        benchmark_bindings=(),
    )


def _minimal_installed(payload_root: Path) -> InstalledCapabilityPackage:
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=payload.manifest.package_ref,
        payload_sha256=payload.payload_sha256,
        source_id="example.local",
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(
            payload_root / "benchmark-suites/example-benchmark.json",
        ),
        implementations=(
            CapabilityImplementationBinding(
                CapabilityRef("example.research", "1.0.0"),
                _NeverExecute(),
            ),
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=payload.manifest.package_ref,
                binding_id="example.binding",
                implementation=object(),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
