from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from asterion.capability_sdk import (
    CapabilityAuthorError,
    materialize_portable_payload,
)


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests" / "fixtures" / "extensions" / "dci_distribution"
DCI_PAYLOAD = PROJECT / "src" / "asterion" / "capabilities" / "dci" / "payload"
PROVIDER = FIXTURE / "src" / "asterion_dci_extension" / "provider.py"


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class DciExternalDistributionTests(unittest.TestCase):
    def test_author_helper_never_overwrites_or_discloses_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            destination = root / "payload"
            destination.mkdir()
            sentinel = destination / "sentinel"
            sentinel.write_text("preserve", encoding="utf-8")

            with self.assertRaises(CapabilityAuthorError) as existing:
                materialize_portable_payload(DCI_PAYLOAD, destination)
            with self.assertRaises(CapabilityAuthorError) as missing:
                materialize_portable_payload(
                    root / "SECRET-missing",
                    root / "other",
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(
                str(existing.exception),
                "capability payload materialization is invalid",
            )
            self.assertEqual(
                str(missing.exception),
                "capability payload materialization is invalid",
            )
            self.assertNotIn("SECRET", repr(missing.exception))

    def test_fixture_provider_imports_only_the_public_sdk(self) -> None:
        tree = ast.parse(PROVIDER.read_text(encoding="utf-8"), filename=str(PROVIDER))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        self.assertIn("asterion.capability_sdk", imports)
        self.assertFalse(
            {
                name
                for name in imports
                if name.startswith("asterion.")
                and name != "asterion.capability_sdk"
            }
        )
        self.assertNotIn("asterion.capabilities.dci", PROVIDER.read_text())

    def test_materialized_payload_and_installed_distribution_pass_clean_smoke(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = root / "fixture"
            shutil.copytree(FIXTURE, fixture)
            materialized = materialize_portable_payload(
                DCI_PAYLOAD,
                fixture / "payload",
            )
            local_root = root / "local-copy"
            local_root.mkdir()
            materialize_portable_payload(DCI_PAYLOAD, local_root / "payload")
            (local_root / "provider.py").write_text(
                "def create_provider():\n    raise AssertionError('must not load')\n",
                encoding="utf-8",
            )
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()

            for project in (PROJECT, fixture):
                built = _run(
                    (
                        "uv",
                        "build",
                        "--wheel",
                        "--out-dir",
                        str(wheelhouse),
                        str(project),
                    ),
                    cwd=root,
                )
                self.assertEqual(built.returncode, 0, built.stderr)

            asterion_wheel = tuple(wheelhouse.glob("asterion-0.1.0-*.whl"))
            extension_wheel = tuple(
                wheelhouse.glob("asterion_dci_extension-1.0.0-*.whl")
            )
            self.assertEqual(len(asterion_wheel), 1)
            self.assertEqual(len(extension_wheel), 1)

            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            virtual = root / "venv"
            created = _run(("uv", "venv", "--seed", str(virtual)), cwd=root)
            self.assertEqual(created.returncode, 0, created.stderr)
            installed = _run(
                (
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(virtual / "bin" / "python"),
                    "--no-deps",
                    str(asterion_wheel[0]),
                    str(extension_wheel[0]),
                ),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            probe = _run(
                (
                    str(virtual / "bin" / "python"),
                    "-I",
                    "-c",
                    _CLEAN_SMOKE,
                    str(PROJECT),
                    materialized.payload_sha256,
                    str(local_root),
                ),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(
                json.loads(probe.stdout),
                {
                    "capabilities": 7,
                    "conformance": True,
                    "payload_sha256": materialized.payload_sha256,
                    "provider_imported_during_discovery": False,
                    "source_id": "dci.python-distribution",
                    "suites": 4,
                    "task_count": 12,
                },
            )


_CLEAN_SMOKE = r"""
import asyncio
import json
import os
import sys
import tempfile
from importlib import metadata
from pathlib import Path

from asterion.benchmarks import (
    ApplicationRef,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedCapability,
    resolve_benchmark_suite,
    resolve_benchmark_tasks,
)
from asterion.capabilities.catalog import discover_capabilities
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    CapabilityPackageCandidate,
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    resolve_capability_source,
)
from asterion.capability_packages.resolution import CapabilitySourceResolutionError
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
)
from asterion.capability_sdk import CapabilityInvocation, run_capability_conformance

repository = Path(sys.argv[1]).resolve()
assert all(Path(value or ".").resolve() != repository for value in sys.path)
expected_digest = sys.argv[2]
local_root = Path(sys.argv[3]).resolve()
package_ref = CapabilityPackageRef("dci", "1.0.0")
source = DistributionCapabilityPackageSource()
os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = "1"
candidates = source.discover_metadata()
imported_during_discovery = "asterion_dci_extension.provider" in sys.modules
candidate = next(item for item in candidates if item.package_ref == package_ref)
lock = CapabilitySourceLock((
    CapabilitySourceLockEntry(
        package_ref=package_ref,
        source_id=candidate.source_id,
        payload_sha256=candidate.payload_sha256,
    ),
))
selected = resolve_capability_source(package_ref, candidates, lock)
payload = source.open_payload(selected)
assert payload.payload_sha256 == expected_digest
os.environ.pop("ASTERION_TEST_FORBID_PROVIDER_IMPORT")
installed = source.load_provider(selected)
assert "asterion_dci_extension.provider" in sys.modules
conformance = run_capability_conformance(installed)
assert conformance.passed, conformance.errors

without_extension = DistributionCapabilityPackageSource(tuple(
    distribution
    for distribution in metadata.distributions()
    if distribution.metadata["Name"] != "asterion-dci-extension"
))
try:
    resolve_capability_source(
        package_ref,
        without_extension.discover_metadata(),
        None,
    )
except CapabilitySourceResolutionError as error:
    assert str(error) == "capability source is unavailable"
else:
    raise AssertionError("missing external package did not fail")

local_source = LocalDirectoryCapabilityPackageSource((
    CapabilitySourceDeclaration(
        source_id="dci.local-copy",
        kind="local-directory",
        package_ref=package_ref,
        payload_sha256=payload.payload_sha256,
        private_locator={
            "root": local_root,
            "payload_root": "payload",
            "module_path": "provider.py",
            "factory_name": "create_provider",
        },
    ),
))
local_copy = local_source.discover_metadata()[0]
assert local_copy == CapabilityPackageCandidate(
    package_ref=package_ref,
    source_id="dci.local-copy",
    source_kind="local-directory",
    payload_sha256=payload.payload_sha256,
    metadata={},
)
try:
    resolve_capability_source(package_ref, (selected, local_copy), None)
except CapabilitySourceResolutionError as error:
    assert str(error) == "capability source is ambiguous"
else:
    raise AssertionError("ambiguous external package did not fail")

catalog = discover_capabilities(installed.catalog_roots)
capabilities = tuple(
    ResolvedCapability(entry.ref, entry.manifest)
    for entry in catalog.entries
)
suite = resolve_benchmark_suite(BenchmarkSuiteRef("dci.github", "1.0.0"), (installed,))
tasks = resolve_benchmark_tasks(suite, capabilities, (installed,))
plan = ResolvedBenchmarkPlan(
    run_id="external-smoke",
    application_ref=ApplicationRef("dci.external-smoke", "1.0.0"),
    suite=suite,
    tasks=tasks,
    case_limit=1,
    package_locks=(lock,),
)
binding = next(
    item for item in installed.benchmark_bindings
    if item.binding_id == plan.tasks[0].task.binding_id
)
with tempfile.TemporaryDirectory() as temporary:
    invocation = binding.implementation.build_invocation(
        BenchmarkTaskRequest(
            run_id=plan.run_id,
            suite_ref=plan.suite.suite_ref,
            task_id=plan.tasks[0].task.task_id,
            case_limit=1,
            output_directory=Path(temporary),
        )
    )
assert invocation.task_id == plan.tasks[0].task.task_id

research = next(
    item for item in installed.implementations
    if item.capability_ref.capability_id == "dci.research"
)
manifest = next(
    entry.manifest for entry in catalog.entries
    if entry.ref == research.capability_ref
)
result = asyncio.run(research.implementation.execute(
    CapabilityInvocation(
        capability_ref=research.capability_ref,
        manifest=manifest,
        run_id="external-smoke",
        input_text="synthetic",
        upstream_artifacts=(),
        runtime=object(),
        host_services={"synthetic": object()},
    )
))
assert result.events[0]["type"] == "research.completed"
assert result.artifacts[0]["media_type"] == "application/vnd.dci.research+json"

print(json.dumps({
    "capabilities": len(payload.manifest.capabilities),
    "conformance": conformance.passed,
    "payload_sha256": payload.payload_sha256,
    "provider_imported_during_discovery": imported_during_discovery,
    "source_id": selected.source_id,
    "suites": len(payload.manifest.benchmark_suites),
    "task_count": len(plan.tasks),
}, sort_keys=True))
"""


if __name__ == "__main__":
    unittest.main()
