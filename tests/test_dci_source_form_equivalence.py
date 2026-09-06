from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from collections.abc import Iterator

from asterion.benchmarks import (
    ApplicationRef,
    BenchmarkRunResult,
    BenchmarkTaskResult,
    ResolvedBenchmarkPlan,
    ResolvedCapability,
    public_plan_dict,
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
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
)
from asterion.capability_sdk import (
    materialize_portable_payload,
    open_portable_payload,
    run_capability_conformance,
)


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests" / "fixtures" / "extensions" / "dci_distribution"
DCI_PAYLOAD = PROJECT / "src" / "asterion" / "capabilities" / "dci" / "payload"
PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")


@contextmanager
def _importable(path: Path) -> Iterator[None]:
    original = tuple(sys.path)
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        sys.path[:] = list(original)


def _with_digest(
    source,
    candidate: CapabilityPackageCandidate,
) -> CapabilityPackageCandidate:
    payload = source.open_payload(candidate)
    return CapabilityPackageCandidate(
        package_ref=candidate.package_ref,
        source_id=candidate.source_id,
        source_kind=candidate.source_kind,
        payload_sha256=payload.payload_sha256,
        metadata=candidate.metadata,
    )


def _lock(candidate: CapabilityPackageCandidate) -> CapabilitySourceLock:
    assert candidate.payload_sha256 is not None
    return CapabilitySourceLock(
        (
            CapabilitySourceLockEntry(
                package_ref=candidate.package_ref,
                source_id=candidate.source_id,
                payload_sha256=candidate.payload_sha256,
            ),
        )
    )


def _payload_bytes(package) -> tuple[dict[str, bytes], dict[str, bytes]]:
    root = package.catalog_roots[0].parent
    capabilities = {
        path.name: path.read_bytes()
        for path in sorted((root / "capabilities").glob("*.json"))
    }
    suites = {
        path.name: path.read_bytes()
        for path in sorted((root / "benchmark-suites").glob("*.json"))
    }
    return capabilities, suites


def _public_plan(package) -> dict[str, object]:
    catalog = discover_capabilities(package.catalog_roots)
    capabilities = tuple(
        ResolvedCapability(entry.ref, entry.manifest) for entry in catalog.entries
    )
    suite = resolve_benchmark_suite(
        BenchmarkSuiteRef("dci.github", "1.0.0"),
        (package,),
    )
    tasks = resolve_benchmark_tasks(suite, capabilities, (package,))
    plan = ResolvedBenchmarkPlan(
        run_id="source-equivalence",
        application_ref=ApplicationRef("dci.source-equivalence", "1.0.0"),
        suite=suite,
        tasks=tasks,
        case_limit=1,
        package_locks=(),
    )
    return public_plan_dict(plan)


def _snapshot(package) -> dict[str, object]:
    payload = open_portable_payload(package.catalog_roots[0].parent)
    conformance = run_capability_conformance(package)
    task = BenchmarkTaskResult(
        task_id="bcplus.level3",
        status="completed",
        case_count=1,
    )
    run = BenchmarkRunResult(status="completed", tasks=(task,))
    capabilities, suites = _payload_bytes(package)
    return {
        "package_ref": package.package_ref,
        "payload_sha256": package.payload_sha256,
        "capability_refs": payload.manifest.capabilities,
        "capability_bytes": capabilities,
        "suite_refs": payload.manifest.benchmark_suites,
        "suite_bytes": suites,
        "resource_digests": tuple(
            (item.resource_id, item.sha256) for item in payload.manifest.resources
        ),
        "implementation_refs": tuple(
            binding.capability_ref for binding in package.implementations
        ),
        "benchmark_binding_ids": tuple(
            binding.binding_id for binding in package.benchmark_bindings
        ),
        "conformance": (conformance.passed, conformance.errors),
        "plan": _public_plan(package),
        "task_result": task,
        "run_result": run,
    }


class DciSourceFormEquivalenceTests(unittest.TestCase):
    def test_builtin_external_and_local_forms_are_exactly_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = root / "fixture"
            shutil.copytree(FIXTURE, fixture)
            materialize_portable_payload(DCI_PAYLOAD, fixture / "payload")
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            subprocess.run(
                (
                    "uv",
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(wheelhouse),
                    str(fixture),
                ),
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wheel = next(wheelhouse.glob("*.whl"))
            target = root / "target"
            subprocess.run(
                (
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    sys.executable,
                    "--no-deps",
                    "--target",
                    str(target),
                    str(wheel),
                ),
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            builtin_source = BuiltinCapabilitySource(builtin_capability_registrations())
            builtin_candidate = _with_digest(
                builtin_source,
                next(
                    item
                    for item in builtin_source.discover_metadata()
                    if item.package_ref == PACKAGE_REF
                ),
            )

            external_source = DistributionCapabilityPackageSource(
                metadata.distributions(path=[str(target)])
            )
            external_candidate = external_source.discover_metadata()[0]

            local_root = root / "local"
            local_root.mkdir()
            materialize_portable_payload(DCI_PAYLOAD, local_root / "payload")
            (local_root / "provider.py").write_text(
                "from pathlib import Path\n"
                "from asterion.capabilities.dci.provider import create_dci_package\n"
                "def create_provider():\n"
                "    return create_dci_package(\n"
                "        payload_root=Path(__file__).parent / 'payload',\n"
                "        source_id='dci.local-copy',\n"
                "        source_kind='local-directory',\n"
                "    )\n",
                encoding="utf-8",
            )
            local_source = LocalDirectoryCapabilityPackageSource(
                (
                    CapabilitySourceDeclaration(
                        source_id="dci.local-copy",
                        kind="local-directory",
                        package_ref=PACKAGE_REF,
                        payload_sha256=builtin_candidate.payload_sha256,
                        private_locator={
                            "root": local_root,
                            "payload_root": "payload",
                            "module_path": "provider.py",
                            "factory_name": "create_provider",
                        },
                    ),
                )
            )
            local_candidate = local_source.discover_metadata()[0]

            candidates = (
                builtin_candidate,
                external_candidate,
                local_candidate,
            )
            for candidate in candidates:
                with self.subTest(source_id=candidate.source_id):
                    self.assertIs(
                        resolve_capability_source(
                            PACKAGE_REF,
                            candidates,
                            _lock(candidate),
                        ),
                        candidate,
                    )
            with self.assertRaises(CapabilitySourceResolutionError) as ambiguous:
                resolve_capability_source(PACKAGE_REF, candidates, None)
            self.assertEqual(str(ambiguous.exception), "capability source is ambiguous")

            builtin = builtin_source.load_provider(builtin_candidate)
            with _importable(target):
                external = external_source.load_provider(external_candidate)
            local = local_source.load_provider(local_candidate)

            expected = _snapshot(builtin)
            for form, snapshot in (
                ("external", _snapshot(external)),
                ("local", _snapshot(local)),
            ):
                for field, value in expected.items():
                    with self.subTest(form=form, field=field):
                        self.assertEqual(snapshot[field], value)


if __name__ == "__main__":
    unittest.main()
