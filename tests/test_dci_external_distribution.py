from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests/fixtures/extensions/dci_distribution"
DCI_PAYLOAD = PROJECT / "src/asterion/capabilities/dci/payload"
PACKAGE_SELECTOR = "dci@1.0.0"
PROVIDER_MODULE = "asterion_dci_extension.provider"


class DciExternalDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.root = Path(cls._temporary.name).resolve()
        cls.clean_cwd = cls.root / "clean-cwd"
        cls.clean_cwd.mkdir()
        cls.wheel_dir = cls.root / "wheels"
        cls.wheel_dir.mkdir()
        cls.venv = cls.root / "venv"
        cls.import_count = cls.root / "provider-import-count.txt"

        if not FIXTURE.is_dir():
            raise AssertionError("dci_distribution fixture is missing")

        cls.fixture_source = cls.root / "dci_distribution_source"
        shutil.copytree(
            FIXTURE,
            cls.fixture_source,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        from asterion.capability_sdk.author import copy_portable_payload

        copy_portable_payload(DCI_PAYLOAD, cls.fixture_source / "payload")
        cls._build_wheel(PROJECT)
        cls._build_wheel(cls.fixture_source)
        subprocess.run(
            [sys.executable, "-m", "venv", str(cls.venv)],
            check=True,
            capture_output=True,
            text=True,
        )
        wheels = tuple(sorted(cls.wheel_dir.glob("*.whl")))
        subprocess.run(
            [
                str(cls.venv / "bin/python"),
                "-m",
                "pip",
                "install",
                "--no-deps",
                *map(str, wheels),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _build_wheel(cls, source: Path) -> None:
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(cls.wheel_dir),
                str(source),
            ],
            cwd=cls.clean_cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_distribution_metadata_payload_conformance_and_smoke_in_clean_environment(
        self,
    ) -> None:
        output = self._run_clean_script(
            """
            import asyncio
            import hashlib
            import json
            import os
            import sys
            from dataclasses import dataclass
            from pathlib import Path

            from asterion.applications.selection import ApplicationSelector
            from asterion.benchmarks.evidence import (
                BenchmarkProgressEvent,
                BenchmarkRunResult,
                BenchmarkTaskResult,
            )
            from asterion.benchmarks.execution import BenchmarkRunner
            from asterion.benchmarks.model import (
                BenchmarkPlan,
                BenchmarkTaskInvocation,
                PlannedBenchmarkTask,
                ResolvedBenchmarkPlan,
                ResolvedBenchmarkTask,
            )
            from asterion.capability_packages.protocol import (
                CapabilityPackageRef,
                CapabilitySourceLock,
                CapabilitySourceLockEntry,
            )
            from asterion.capability_packages.resolution import (
                CapabilitySourceResolutionError,
                load_installed_capability_packages,
            )
            from asterion.capability_packages.sources.distribution import (
                DistributionCapabilityPackageSource,
                DistributionCapabilitySourceError,
            )
            from asterion.capability_sdk import (
                CapabilityExecutionResult,
                CapabilityInvocation,
                run_capability_conformance,
            )
            from asterion.capabilities.catalog import CatalogEntry, CapabilityRef
            from asterion.capabilities.execution import validate_capability_result
            from asterion.capabilities.protocol import validate_capability_manifest
            from asterion.capability_packages.payload import open_portable_payload
            from asterion.capability_packages.sources.local import (
                LocalDirectoryCapabilityPackageSource,
            )
            from asterion.capability_packages.protocol import CapabilitySourceDeclaration

            PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
            PROVIDER_MODULE = "asterion_dci_extension.provider"
            EXPECTED_SUITES = ("dci.all@1.0.0", "dci.github@1.0.0", "dci.paper-main@1.0.0")
            EXPECTED_CAPABILITIES = (
                "dci.analysis@1.0.0",
                "dci.benchmark@1.0.0",
                "dci.evaluation@1.0.0",
                "dci.export@1.0.0",
                "dci.research@1.0.0",
                "policy.local-corpus@1.0.0",
                "protocol.observability@1.0.0",
            )

            class _SyntheticRuntime:
                @property
                def manifest(self):
                    return None

                async def run(self, request, *, signal=None):
                    del request, signal
                    if False:
                        yield None

            class _Cancellation:
                @property
                def cancelled(self):
                    return False

            class _Evidence:
                def initialize(self, plan):
                    self.plan = plan

                def start_task(self, task):
                    self.task = task

                def append_progress(self, event):
                    self.event = event

                def finish_task(self, result):
                    self.task_result = result

                def finish_run(self, result):
                    self.run_result = result

                def compatible_completed_tasks(self, plan):
                    return frozenset()

            class _Executor:
                def execute(self, invocation, *, cancellation, on_progress):
                    assert cancellation.cancelled is False
                    on_progress(
                        BenchmarkProgressEvent(
                            task_id=invocation.task_id,
                            sequence=1,
                            phase="executing",
                            completed_cases=1,
                            total_cases=1,
                            content_digest=None,
                            private_payload=None,
                        )
                    )
                    return BenchmarkTaskResult(
                        task_id=invocation.task_id,
                        status="completed",
                        completed_cases=1,
                        content_digests=(
                            hashlib.sha256(invocation.task_id.encode()).hexdigest(),
                        ),
                        private_payload=None,
                    )

            def _provider_import_count():
                path = Path(os.environ["ASTERION_DCI_EXTENSION_IMPORT_COUNT_FILE"])
                if not path.exists():
                    return 0
                raw = path.read_text(encoding="utf-8").strip()
                return int(raw or "0")

            repo = Path(os.environ["ASTERION_REPO_ROOT"]).resolve()
            assert Path.cwd() != repo
            assert str(repo) not in sys.path
            assert all(Path(item).resolve() != repo for item in sys.path if item)

            class _forbid_provider_import:
                def __enter__(self):
                    os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = "1"
                def __exit__(self, exc_type, exc, tb):
                    os.environ.pop("ASTERION_TEST_FORBID_PROVIDER_IMPORT", None)

            class _without_provider_distribution:
                def __enter__(self):
                    self.original = list(sys.path)
                    sys.path[:] = [item for item in sys.path if "site-packages" not in item]
                def __exit__(self, exc_type, exc, tb):
                    sys.path[:] = self.original

            from asterion.capability_packages.protocol import validate_benchmark_suite_manifest

            source = DistributionCapabilityPackageSource()
            with _forbid_provider_import():
                candidates = source.discover_metadata()
            dci = [candidate for candidate in candidates if candidate.package_ref == PACKAGE_REF]
            assert len(dci) == 1, dci
            candidate = dci[0]
            assert candidate.source_kind == "python-distribution"
            assert candidate.source_id == "python-distribution.asterion-dci-extension.1-0-0.dci.1.0.0.sha-67d0e96707b8"
            assert PROVIDER_MODULE not in sys.modules
            assert _provider_import_count() == 0

            with _forbid_provider_import():
                payload = source.open_payload(candidate)
            assert payload.manifest.package_ref == PACKAGE_REF
            assert tuple(ref.selector for ref in payload.manifest.benchmark_suites) == EXPECTED_SUITES
            assert tuple(ref.selector for ref in payload.manifest.capabilities) == EXPECTED_CAPABILITIES
            expected = open_portable_payload(Path(os.environ["ASTERION_DCI_PAYLOAD_COPY"]))
            assert payload.payload_sha256 == expected.payload_sha256
            assert PROVIDER_MODULE not in sys.modules
            assert _provider_import_count() == 0

            lock = CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=PACKAGE_REF,
                        payload_sha256=payload.payload_sha256,
                        source_id=candidate.source_id,
                    ),
                )
            )
            for bad_lock in (
                CapabilitySourceLock(
                    entries=(
                        CapabilitySourceLockEntry(
                            package_ref=PACKAGE_REF,
                            payload_sha256=payload.payload_sha256,
                            source_id="dci.other-distribution",
                        ),
                    )
                ),
                CapabilitySourceLock(
                    entries=(
                        CapabilitySourceLockEntry(
                            package_ref=PACKAGE_REF,
                            payload_sha256="0" * 64,
                            source_id=candidate.source_id,
                        ),
                    )
                ),
                CapabilitySourceLock(
                    entries=(
                        CapabilitySourceLockEntry(
                            package_ref=CapabilityPackageRef("other.package", "1.0.0"),
                            payload_sha256=payload.payload_sha256,
                            source_id=candidate.source_id,
                        ),
                    )
                ),
            ):
                try:
                    load_installed_capability_packages((PACKAGE_REF,), (source,), bad_lock)
                except CapabilitySourceResolutionError:
                    assert _provider_import_count() == 0
                else:
                    raise AssertionError("invalid source lock was not rejected")

            installed = load_installed_capability_packages((PACKAGE_REF,), (source,), lock)[0]
            assert installed.package_ref == PACKAGE_REF
            assert installed.payload_sha256 == payload.payload_sha256
            assert installed.source_id == candidate.source_id
            assert installed.source_kind == "python-distribution"
            assert _provider_import_count() == 1
            run_capability_conformance(installed)

            implementation = {
                binding.capability_ref: binding.implementation
                for binding in installed.implementations
            }[CapabilityRef("dci.research", "1.0.0")]
            manifest = validate_capability_manifest(
                json.loads((installed.catalog_roots[0] / "dci-research.json").read_text(encoding="utf-8"))
            )
            invocation = CapabilityInvocation(
                capability_ref=CapabilityRef("dci.research", "1.0.0"),
                manifest=manifest,
                run_id="synthetic-run",
                input_text="synthetic",
                upstream_artifacts=(),
                runtime=_SyntheticRuntime(),
                host_services={"synthetic": object()},
                signal=_Cancellation(),
            )
            result = asyncio.run(implementation.execute(invocation))
            assert isinstance(result, CapabilityExecutionResult)
            validate_capability_result(manifest, result)

            suite = next(
                item
                for item in (
                    json.loads(path.read_text(encoding="utf-8"))
                    for path in installed.benchmark_suite_paths
                )
                if item["suite_id"] == "dci.github"
            )
            github_suite = validate_benchmark_suite_manifest(suite)
            capability_manifest = json.loads((installed.catalog_roots[0] / "dci-benchmark.json").read_text(encoding="utf-8"))
            planned = tuple(
                PlannedBenchmarkTask(
                    ordinal=index,
                    task=task,
                    capability=CatalogEntry(
                        ref=task.capability,
                        source=installed.catalog_roots[0] / "dci-benchmark.json",
                        manifest=capability_manifest,
                    ),
                )
                for index, task in enumerate(github_suite.tasks, start=1)
            )
            plan = BenchmarkPlan(
                run_id="synthetic-benchmark",
                application_ref=ApplicationSelector("synthetic.app", "1.0.0"),
                suite=github_suite,
                tasks=planned,
                case_limit=1,
                package_locks=(lock,),
            )
            resolved = ResolvedBenchmarkPlan(
                plan,
                tuple(
                    ResolvedBenchmarkTask(
                        planned=task,
                        binding=next(
                            item
                            for item in installed.benchmark_bindings
                            if item.binding_id == task.task.binding_id
                        ),
                    )
                    for task in planned
                ),
            )
            run_result = BenchmarkRunner().run(
                resolved,
                executor=_Executor(),
                evidence=_Evidence(),
                cancellation=_Cancellation(),
            )
            assert isinstance(run_result, BenchmarkRunResult)
            assert run_result.status == "completed"
            assert run_result.completed_task_ids == tuple(task.task.task_id for task in planned)

            with _without_provider_distribution():
                try:
                    load_installed_capability_packages((PACKAGE_REF,), (DistributionCapabilityPackageSource(),))
                except (CapabilitySourceResolutionError, DistributionCapabilitySourceError) as error:
                    assert "capability source is unavailable" in str(error) or "installed capability distribution" in str(error)
                else:
                    raise AssertionError("missing extension was not rejected")

            local_source = LocalDirectoryCapabilityPackageSource(
                CapabilitySourceDeclaration(
                    source_id="dci.local",
                    kind="local-directory",
                    package_ref=PACKAGE_REF,
                    payload_sha256=payload.payload_sha256,
                    locator={"root": os.environ["ASTERION_DCI_LOCAL_COPY"]},
                    provider_factory={"module": "example.provider", "name": "create_provider"},
                )
            )
            try:
                load_installed_capability_packages((PACKAGE_REF,), (source, local_source))
            except CapabilitySourceResolutionError as error:
                assert str(error) == "capability source is unavailable or ambiguous"
            else:
                raise AssertionError("ambiguous DCI sources were not rejected")

            print(json.dumps({
                "candidate": candidate.source_id,
                "digest": installed.payload_sha256,
                "imports": _provider_import_count(),
                "suite_count": len(installed.benchmark_suite_paths),
                "implementation_count": len(installed.implementations),
                "benchmark_binding_count": len(installed.benchmark_bindings),
            }, sort_keys=True))

            """
        )
        details = json.loads(output)
        self.assertTrue(details["candidate"].startswith("python-distribution."))
        self.assertEqual(details["imports"], 1)
        self.assertEqual(details["suite_count"], 3)
        self.assertEqual(details["implementation_count"], 6)
        self.assertEqual(details["benchmark_binding_count"], 15)

    def test_fixture_declares_only_capability_package_entry_point(self) -> None:
        pyproject = tomllib.loads(
            (FIXTURE / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(
            pyproject["project"]["entry-points"],
            {
                "asterion.capability_packages": {
                    PACKAGE_SELECTOR: (
                        "asterion_dci_extension.provider:create_provider"
                    ),
                },
            },
        )
        self.assertNotIn("scripts", pyproject["project"])

    def test_fixture_provider_imports_only_public_asterion_sdk(self) -> None:
        source = (FIXTURE / "src/asterion_dci_extension/provider.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        violations = []
        for node in ast.walk(tree):
            modules = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = (node.module,)
            violations.extend(
                module
                for module in modules
                if (module == "asterion" or module.startswith("asterion."))
                and module != "asterion.capability_sdk"
            )

        self.assertEqual(violations, [])
        self.assertNotIn("asterion.capabilities.dci", source)
        self.assertNotIn("asterion._", source)

    def _run_clean_script(self, source: str) -> str:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        environment.update(
            {
                "ASTERION_DCI_EXTENSION_IMPORT_COUNT_FILE": str(self.import_count),
                "ASTERION_DCI_LOCAL_COPY": str(self.fixture_source),
                "ASTERION_DCI_PAYLOAD_COPY": str(self.fixture_source / "payload"),
                "ASTERION_REPO_ROOT": str(PROJECT),
                "PYTHONNOUSERSITE": "1",
            }
        )
        completed = subprocess.run(
            [str(self.venv / "bin/python"), "-c", textwrap.dedent(source)],
            cwd=self.clean_cwd,
            env=environment,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.fail(
                "clean environment script failed\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
