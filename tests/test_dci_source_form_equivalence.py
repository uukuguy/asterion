from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Mapping
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
    PlannedBenchmarkTask,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
)
from asterion.capabilities.catalog import CatalogEntry, CapabilityRef
from asterion.capabilities.execution import validate_capability_result
from asterion.capabilities.protocol import validate_capability_manifest
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    validate_benchmark_suite_manifest,
)
from asterion.capability_packages.resolution import load_installed_capability_packages
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilityPackageSource,
)
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
)
from asterion.capability_sdk import (
    CapabilityInvocation,
    copy_portable_payload,
    run_capability_conformance,
)


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests/fixtures/extensions/dci_distribution"
DCI_PAYLOAD = PROJECT / "src/asterion/capabilities/dci/payload"
EXTERNALIZATION = PROJECT / "src/asterion/capabilities/dci/conformance/externalization.json"
PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")


class DciSourceFormEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.root = Path(cls._temporary.name).resolve()
        cls.clean_cwd = cls.root / "clean-cwd"
        cls.clean_cwd.mkdir()
        cls.probe_root = cls.root / "probe"
        probe_tests = cls.probe_root / "tests"
        probe_tests.mkdir(parents=True)
        (probe_tests / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy2(
            Path(__file__),
            probe_tests / "test_dci_source_form_equivalence.py",
        )
        cls.wheel_dir = cls.root / "wheels"
        cls.wheel_dir.mkdir()
        cls.venv = cls.root / "venv"

        cls.local_source_root = cls.root / "local-dci"
        cls.local_source_root.mkdir()
        copy_portable_payload(DCI_PAYLOAD, cls.local_source_root / "payload")
        _write_local_provider(cls.local_source_root)

        cls.fixture_source = cls.root / "dci_distribution_source"
        shutil.copytree(
            FIXTURE,
            cls.fixture_source,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
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

    def test_installed_builtin_and_explicit_local_forms_are_equivalent(
        self,
    ) -> None:
        builtin = _jsonable(_load_source_fingerprint(BuiltinCapabilityPackageSource()))
        local = _jsonable(_load_source_fingerprint(_local_source(self.local_source_root)))
        distribution = self._distribution_fingerprint()

        self.assertEqual(
            {
                builtin["source"]["source_kind"],
                local["source"]["source_kind"],
                distribution["source"]["source_kind"],
            },
            {"builtin", "local-directory", "python-distribution"},
        )
        for fingerprint in (builtin, local, distribution):
            with self.subTest(source=fingerprint["source"]):
                self.assertEqual(
                    fingerprint["lock"]["source_id"],
                    fingerprint["source"]["source_id"],
                )
                self.assertEqual(
                    fingerprint["lock"]["payload_sha256"],
                    fingerprint["identity"]["payload_sha256"],
                )

        self.assertEqual(builtin["identity"], distribution["identity"])
        self.assertEqual(local["identity"], distribution["identity"])
        self.assertEqual(distribution["ambiguous_error"], "capability source is unavailable or ambiguous")

    def test_externalization_records_public_ids_and_digests_without_paths(
        self,
    ) -> None:
        payload = _load_source_fingerprint(BuiltinCapabilityPackageSource())
        document = json.loads(EXTERNALIZATION.read_text(encoding="utf-8"))

        self.assertEqual(
            set(document),
            {"case_digests", "case_ids", "profile"},
        )
        self.assertEqual(document["profile"], "minimal")
        self.assertEqual(
            tuple(document["case_ids"]),
            tuple(payload["identity"]["conformance_profile"]["case_ids"]),
        )
        self.assertEqual(
            document["case_digests"],
            payload["identity"]["conformance_results"],
        )
        serialized = json.dumps(document, sort_keys=True)
        self.assertNotIn(str(PROJECT), serialized)
        self.assertNotIn(str(DCI_PAYLOAD), serialized)
        self.assertNotIn("/", serialized)
        self.assertNotIn("\\", serialized)

    def _distribution_fingerprint(self) -> Mapping[str, object]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        environment.update(
            {
                "ASTERION_DCI_LOCAL_COPY": str(self.local_source_root),
                "ASTERION_REPO_ROOT": str(PROJECT),
                "PYTHONPATH": str(self.probe_root),
                "PYTHONNOUSERSITE": "1",
            }
        )
        completed = subprocess.run(
            [
                str(self.venv / "bin/python"),
                "-c",
                _DISTRIBUTION_SCRIPT,
            ],
            cwd=self.clean_cwd,
            env=environment,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.fail(
                "distribution equivalence script failed\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return json.loads(completed.stdout)


class _SyntheticRuntime:
    @property
    def manifest(self) -> None:
        return None

    async def run(self, request: object, *, signal: object = None) -> object:
        del request, signal
        if False:
            yield None


class _Cancellation:
    @property
    def cancelled(self) -> bool:
        return False


class _Evidence:
    def initialize(self, plan: ResolvedBenchmarkPlan) -> None:
        self.plan = plan

    def start_task(self, task: ResolvedBenchmarkTask) -> None:
        self.task = task

    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        self.event = event

    def finish_task(self, result: BenchmarkTaskResult) -> None:
        self.task_result = result

    def finish_run(self, result: BenchmarkRunResult) -> None:
        self.run_result = result

    def compatible_completed_tasks(
        self,
        plan: ResolvedBenchmarkPlan,
    ) -> frozenset[str]:
        del plan
        return frozenset()


class _Executor:
    def execute(
        self,
        invocation: object,
        *,
        cancellation: _Cancellation,
        on_progress: object,
    ) -> BenchmarkTaskResult:
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
            content_digests=(hashlib.sha256(invocation.task_id.encode()).hexdigest(),),
            private_payload=None,
        )


def _load_source_fingerprint(source: object) -> dict[str, object]:
    candidate = _dci_candidate(source)
    payload = source.open_payload(candidate)
    lock = CapabilitySourceLock(
        entries=(
            CapabilitySourceLockEntry(
                package_ref=PACKAGE_REF,
                payload_sha256=payload.payload_sha256,
                source_id=candidate.source_id,
            ),
        )
    )
    installed = load_installed_capability_packages((PACKAGE_REF,), (source,), lock)[0]
    run_capability_conformance(installed)
    identity = _identity(installed, lock)
    return {
        "source": {
            "source_id": installed.source_id,
            "source_kind": installed.source_kind,
        },
        "lock": {
            "source_id": lock.entries[0].source_id,
            "payload_sha256": lock.entries[0].payload_sha256,
        },
        "identity": identity,
    }


def _dci_candidate(source: object) -> object:
    candidates = tuple(
        candidate
        for candidate in source.discover_metadata()
        if candidate.package_ref == PACKAGE_REF
    )
    if len(candidates) != 1:
        raise AssertionError(f"expected one DCI candidate, got {candidates!r}")
    return candidates[0]


def _identity(installed: object, lock: CapabilitySourceLock) -> dict[str, object]:
    capability_documents = _capability_documents(installed.catalog_roots[0])
    suite_documents = _suite_documents(installed.benchmark_suite_paths)
    capability_result = _capability_result(installed, capability_documents)
    benchmark = _benchmark_result(installed, suite_documents, lock)
    return {
        "package_ref": installed.package_ref.selector,
        "payload_sha256": installed.payload_sha256,
        "capabilities": capability_documents,
        "benchmark_suites": suite_documents,
        "public_resource_digests": (),
        "implementation_binding_ids": tuple(
            binding.capability_ref.selector
            for binding in sorted(
                installed.implementations,
                key=lambda binding: binding.capability_ref,
            )
        ),
        "benchmark_binding_ids": tuple(
            binding.binding_id
            for binding in sorted(
                installed.benchmark_bindings,
                key=lambda binding: binding.binding_id,
            )
        ),
        "conformance_profile": _json(installed.catalog_roots[0].parent / "conformance/profile.json"),
        "conformance_results": _conformance_results(
            installed.catalog_roots[0].parent,
            installed.payload_sha256,
        ),
        "synthetic_capability_result": capability_result,
        "synthetic_resolved_plan": benchmark["plan"],
        "synthetic_task_results": benchmark["task_results"],
        "synthetic_run_result": benchmark["run_result"],
    }


def _capability_documents(root: Path) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in sorted(root.glob("*.json")):
        manifest = validate_capability_manifest(_json(path))
        ref = CapabilityRef(str(manifest["capability_id"]), str(manifest["version"]))
        rows.append((ref.selector, path.read_text(encoding="utf-8")))
    return tuple(rows)


def _suite_documents(paths: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in paths:
        suite = validate_benchmark_suite_manifest(_json(path))
        rows.append((suite.suite_ref.selector, path.read_text(encoding="utf-8")))
    return tuple(sorted(rows))


def _capability_result(
    installed: object,
    capability_documents: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    ref = CapabilityRef("protocol.observability", "1.0.0")
    implementations = {
        binding.capability_ref: binding.implementation
        for binding in installed.implementations
    }
    manifests = {
        selector: json.loads(raw)
        for selector, raw in capability_documents
    }
    manifest = validate_capability_manifest(manifests[ref.selector])
    result = asyncio.run(
        implementations[ref].execute(
            CapabilityInvocation(
                capability_ref=ref,
                manifest=manifest,
                run_id="synthetic-capability",
                input_text="synthetic",
                upstream_artifacts=(),
                runtime=_SyntheticRuntime(),
                host_services={},
                signal=_Cancellation(),
            )
        )
    )
    validate_capability_result(manifest, result)
    return {
        "events": _plain(result.events),
        "artifacts": _plain(result.artifacts),
    }


def _benchmark_result(
    installed: object,
    suite_documents: tuple[tuple[str, str], ...],
    lock: CapabilitySourceLock,
) -> dict[str, object]:
    suite = validate_benchmark_suite_manifest(
        json.loads(
            next(raw for selector, raw in suite_documents if selector == "dci.github@1.0.0")
        )
    )
    capability_manifest = _json(installed.catalog_roots[0] / "dci-benchmark.json")
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
        for index, task in enumerate(suite.tasks, start=1)
    )
    plan = BenchmarkPlan(
        run_id="synthetic-benchmark",
        application_ref=ApplicationSelector("synthetic.app", "1.0.0"),
        suite=suite,
        tasks=planned,
        case_limit=1,
        package_locks=(lock,),
    )
    bindings = {binding.binding_id: binding for binding in installed.benchmark_bindings}
    resolved = ResolvedBenchmarkPlan(
        plan,
        tuple(
            ResolvedBenchmarkTask(
                planned=task,
                binding=bindings[task.task.binding_id],
            )
            for task in planned
        ),
    )
    evidence = _Evidence()
    run_result = BenchmarkRunner().run(
        resolved,
        executor=_Executor(),
        evidence=evidence,
        cancellation=_Cancellation(),
    )
    return {
        "plan": {
            "run_id": resolved.plan.run_id,
            "suite_ref": resolved.plan.suite.suite_ref.selector,
            "case_limit": resolved.plan.case_limit,
            "tasks": tuple(
                (task.planned.task.task_id, task.binding.binding_id)
                for task in resolved.tasks
            ),
        },
        "task_results": tuple(
            (
                task_id,
                "completed",
                hashlib.sha256(task_id.encode()).hexdigest(),
            )
            for task_id in run_result.completed_task_ids
        ),
        "run_result": {
            "run_id": run_result.run_id,
            "status": run_result.status,
            "completed_task_ids": run_result.completed_task_ids,
            "content_digests": run_result.content_digests,
        },
    }


def _local_source(root: Path) -> LocalDirectoryCapabilityPackageSource:
    payload = __import__(
        "asterion.capability_packages.payload",
        fromlist=("open_portable_payload",),
    ).open_portable_payload(root / "payload")
    return LocalDirectoryCapabilityPackageSource(
        CapabilitySourceDeclaration(
            source_id="local.dci.explicit",
            kind="local-directory",
            package_ref=PACKAGE_REF,
            payload_sha256=payload.payload_sha256,
            locator={"root": str(root)},
            provider_factory={"module": "example.provider", "name": "create_provider"},
        )
    )


def _write_local_provider(root: Path) -> None:
    package = root / "example"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "provider.py").write_text(_LOCAL_PROVIDER, encoding="utf-8")


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _conformance_results(
    payload_root: Path,
    payload_sha256: str,
) -> dict[str, str]:
    profile = _json(payload_root / "conformance/profile.json")
    if tuple(profile["case_ids"]) != (
        "manifest-closure",
        "portable-identity",
    ):
        raise AssertionError("unexpected externalization conformance profile")
    return {
        "manifest-closure": _manifest_closure_sha256(payload_root),
        "portable-identity": payload_sha256,
    }


def _manifest_closure_sha256(payload_root: Path) -> str:
    paths = (
        payload_root / "capability-package.json",
        *sorted((payload_root / "capabilities").glob("*.json")),
        *sorted((payload_root / "benchmark-suites").glob("*.json")),
    )
    members = tuple(
        {
            "path": path.relative_to(payload_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    )
    canonical = json.dumps(
        members,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _jsonable(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True))


_LOCAL_PROVIDER = r'''
from __future__ import annotations

import json
from pathlib import Path

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "local.dci.explicit"
SOURCE_KIND = "local-directory"


class _SyntheticCapability:
    def __init__(self, capability_ref, manifest_path):
        self.capability_ref = capability_ref
        self.manifest_path = manifest_path

    async def execute(self, invocation):
        if invocation.capability_ref != self.capability_ref:
            raise ValueError("capability invocation identity is invalid")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        events = tuple(
            {"type": event_type, "payload": {"source": "synthetic"}}
            for event_type in manifest["emits_events"]
        )
        artifacts = tuple(
            {
                "artifact_id": f"synthetic-{index}",
                "media_type": media_type,
                "value": {"source": "synthetic"},
            }
            for index, media_type in enumerate(manifest["produces_artifacts"], start=1)
        )
        return CapabilityExecutionResult(events=events, artifacts=artifacts)


class _SyntheticBenchmarkTask:
    def __init__(self, binding_id):
        self.binding_id = binding_id

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=self.binding_id,
            public_arguments=("synthetic",),
            private_payload=None,
        )


def create_provider():
    root = Path(__file__).resolve().parents[1] / "payload"
    payload = open_portable_payload(root)
    implementations = []
    for path in sorted((root / "capabilities").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["kind"] in {
            "capability",
            "evaluation",
            "memory",
            "observability",
            "research",
            "workflow",
        }:
            ref = CapabilityRef(str(manifest["capability_id"]), str(manifest["version"]))
            implementations.append(
                CapabilityImplementationBinding(ref, _SyntheticCapability(ref, path))
            )
    benchmark_bindings = {}
    suite_paths = tuple(sorted((root / "benchmark-suites").glob("*.json")))
    for path in suite_paths:
        suite = json.loads(path.read_text(encoding="utf-8"))
        for task in suite["tasks"]:
            binding_id = str(task["binding_id"])
            benchmark_bindings[binding_id] = BenchmarkTaskBinding(
                owner_package=PACKAGE_REF,
                binding_id=binding_id,
                implementation=_SyntheticBenchmarkTask(binding_id),
            )
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=SOURCE_ID,
        source_kind=SOURCE_KIND,
        catalog_roots=((root / "capabilities").resolve(strict=True),),
        benchmark_suite_paths=suite_paths,
        implementations=tuple(implementations),
        benchmark_bindings=tuple(
            benchmark_bindings[key] for key in sorted(benchmark_bindings)
        ),
    )
'''


_DISTRIBUTION_SCRIPT = textwrap.dedent(
    r'''
    import importlib.resources
    import json
    import os
    import pathlib
    import sys

    import asterion

    from asterion.capability_packages.protocol import CapabilityPackageRef
    from asterion.capability_packages.resolution import (
        CapabilitySourceResolutionError,
        load_installed_capability_packages,
    )
    from asterion.capability_packages.sources.builtin import BuiltinCapabilityPackageSource
    from asterion.capability_packages.sources.distribution import DistributionCapabilityPackageSource
    from asterion.capability_packages.sources.local import LocalDirectoryCapabilityPackageSource
    from asterion.capability_packages.protocol import CapabilitySourceDeclaration
    from asterion.capability_packages.payload import open_portable_payload
    from tests.test_dci_source_form_equivalence import _load_source_fingerprint

    PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
    repo = pathlib.Path(os.environ["ASTERION_REPO_ROOT"]).resolve()
    repo_src = repo / "src"
    assert all(
        pathlib.Path(item).resolve() not in {repo, repo_src}
        for item in sys.path
        if item
    )
    for name, module in tuple(sys.modules.items()):
        if name == "asterion" or name.startswith("asterion."):
            module_file = getattr(module, "__file__", None)
            if module_file is not None:
                assert not pathlib.Path(module_file).resolve().is_relative_to(repo)
    package_root = pathlib.Path(
        str(importlib.resources.files("asterion"))
    ).resolve()
    assert not package_root.is_relative_to(repo)
    assert (
        package_root
        / "capabilities/dci/payload/capability-package.json"
    ).is_file()
    assert (
        package_root
        / "capabilities/dci/conformance/externalization.json"
    ).is_file()

    source = DistributionCapabilityPackageSource()
    result = _load_source_fingerprint(source)
    for name, module in tuple(sys.modules.items()):
        if name == "asterion" or name.startswith("asterion."):
            module_file = getattr(module, "__file__", None)
            if module_file is not None:
                assert not pathlib.Path(module_file).resolve().is_relative_to(repo)
    local_root = os.environ["ASTERION_DCI_LOCAL_COPY"]
    payload = open_portable_payload(__import__("pathlib").Path(local_root) / "payload")
    local_source = LocalDirectoryCapabilityPackageSource(
        CapabilitySourceDeclaration(
            source_id="local.dci.explicit",
            kind="local-directory",
            package_ref=PACKAGE_REF,
            payload_sha256=payload.payload_sha256,
            locator={"root": local_root},
            provider_factory={"module": "example.provider", "name": "create_provider"},
        )
    )
    try:
        load_installed_capability_packages(
            (PACKAGE_REF,),
            (source, BuiltinCapabilityPackageSource(), local_source),
            None,
        )
    except CapabilitySourceResolutionError as error:
        result["ambiguous_error"] = str(error)
    else:
        raise AssertionError("unlocked source resolution was not ambiguous")
    print(json.dumps(result, sort_keys=True))
    '''
)


if __name__ == "__main__":
    unittest.main()
