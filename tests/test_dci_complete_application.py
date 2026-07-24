from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from asterion.assembly.protocol import resolve_assembly
from asterion.adapters.claude_code import ClaudeCodeProtocolAdapter
from asterion.applications.dci_agent_lite.provider import create_provider
from asterion.cli import main
from asterion.capabilities.dci_research.complete import (
    DciCompleteAnalysisImplementation,
    DciCompleteBenchmarkImplementation,
    DciCompleteEvaluationImplementation,
    DciCompleteExportImplementation,
    DciCompleteResearchImplementation,
    INPUT_PROTOCOL,
    complete_application_identity,
)
from asterion.packages.execution import InProcessArtifactPayload, project_public_value
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.dci.services import (
    create_answer_judge_service_factory,
    create_local_corpus_service_factory,
)
from asterion.dci.provenance import (
    DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
    dci_complete_implementation_identity,
)
from tests.test_application_discovery import FakeEntryPoint
from asterion.dci.dual_runtime_verification import (
    DciDualRuntimeVerificationError,
    audit_restricted_claude_application,
    audit_restricted_pi_application,
    build_restricted_claude_record,
    verify_restricted_claude_binding,
    write_private_report,
)
from asterion.packages.catalog import PackageRef
from asterion.packages.catalog import discover_packages
from asterion.packages.execution import PackageExecutionError, PackageInvocation
from asterion.runner.composed import run_composed_application
from asterion.runner.application import ApplicationRunError
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.runtime.working_directory import ProcessWorkingDirectory


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
MANIFESTS = SOURCE / "capabilities/dci_research/manifests"
ASSEMBLIES = SOURCE / "applications/dci_agent_lite/assemblies"

STAGES = (
    "dci.research",
    "dci.evaluation",
    "dci.benchmark",
    "dci.analysis",
    "dci.export",
)
ORDER = (
    "policy.local-corpus",
    *STAGES,
)
EVENTS = (
    "research.completed",
    "evaluation.completed",
    "benchmark.completed",
    "analysis.completed",
    "export.completed",
)
ARTIFACTS = (
    "application/vnd.dci.research+json",
    "application/vnd.dci.verdict+json",
    "application/vnd.dci.benchmark+json",
    "application/vnd.dci.analysis+json",
    "application/vnd.dci.export+json",
)


class _CorpusService:
    root = PROJECT
    directory_path = PROJECT
    identity_sha256 = "a" * 64

    @contextmanager
    def open_process_working_directory(self):
        yield ProcessWorkingDirectory(
            identity_path=PROJECT,
            cwd=str(PROJECT),
            pass_fds=(),
        )


class _JudgeService:
    _default_public_identity = {
        "schema": "asterion.dci.answer-judge-identity/v1",
        "adapter_id": "dci.openai-compatible",
        "config_sha256": "c" * 64,
        "request_shape_sha256": "d" * 64,
        "prompt_contract_sha256": "e" * 64,
    }

    def __init__(
        self,
        public_identity: dict[str, object] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._identity = (
            dict(self._default_public_identity)
            if public_identity is None
            else dict(public_identity)
        )

    @property
    def public_identity(self):
        return dict(self._identity)

    async def judge(
        self,
        *,
        question: str,
        gold_answer: str,
        predicted_answer: str,
        signal: object | None,
    ):
        self.calls.append(
            {
                "question": question,
                "gold_answer": gold_answer,
                "predicted_answer": predicted_answer,
                "signal": signal,
            }
        )
        return {
            "is_correct": True,
            "judge_request_fingerprint": "b" * 64,
        }


def _host_services(judge: object | None = None) -> dict[str, object]:
    return {
        "corpus.local-root": _CorpusService(),
        "evaluation.answer-judge": _JudgeService() if judge is None else judge,
    }


def plan(runtime_id: str):
    suffix = "claude" if runtime_id == "claude-code.reference" else "pi"
    assembly = json.loads(
        (ASSEMBLIES / f"dci-complete-application-{suffix}.json").read_text()
    )
    return resolve_assembly(
        assembly,
        catalog=discover_packages((MANIFESTS,)),
        runtime_manifest=RuntimeManifest(
            runtime_id=runtime_id,
            capabilities=("filesystem.read",),
        ).to_mapping(),
    )


class DciCompleteApplicationContractTests(unittest.TestCase):
    def test_transitive_identity_closure_matches_complete_assembly_packages(
        self,
    ) -> None:
        self.assertEqual(
            {
                name
                for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
                if "/manifests/" not in name
            },
            {
                "applications/dci_agent_lite/assemblies/dci-complete-application-claude.json",
                "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
                "capabilities/dci_research/complete.py",
                "capabilities/dci_research/implementation.py",
                "dci/analysis.py",
                "dci/benchmark.py",
                "dci/bridge.py",
                "dci/evaluation.py",
                "dci/judge.py",
                "dci/provenance.py",
                "dci/run.py",
                "dci/services.py",
            },
        )
        assembly_package_ids: set[str] | None = None
        for assembly_path in sorted(
            ASSEMBLIES.glob("dci-complete-application-*.json")
        ):
            assembly = json.loads(assembly_path.read_text())
            current = {
                f"{item['package_id']}@{item['version']}"
                for item in assembly["packages"]
            }
            if assembly_package_ids is None:
                assembly_package_ids = current
            else:
                self.assertEqual(current, assembly_package_ids)
        assert assembly_package_ids is not None

        manifest_refs = set()
        manifest_resources = {
            name
            for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
            if name.startswith("capabilities/dci_research/manifests/")
        }
        for resource_name in manifest_resources:
            manifest = json.loads(SOURCE.joinpath(resource_name).read_text())
            manifest_refs.add(f"{manifest['package_id']}@{manifest['version']}")

        self.assertEqual(manifest_refs, assembly_package_ids)
        self.assertEqual(
            tuple(sorted(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)),
            DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
        )
        self.assertEqual(
            len(set(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)),
            len(DCI_COMPLETE_IMPLEMENTATION_RESOURCES),
        )

    def test_transitive_identity_changes_for_every_resource_and_ignores_order(
        self,
    ) -> None:
        resources = {
            name: f"fixture:{name}".encode()
            for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
        }

        def read(name: str) -> bytes:
            return resources[name]

        baseline = dci_complete_implementation_identity(
            resource_reader=read,
            resource_names=DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
        )
        reversed_identity = dci_complete_implementation_identity(
            resource_reader=read,
            resource_names=tuple(reversed(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)),
        )
        self.assertEqual(baseline, reversed_identity)

        for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES:
            with self.subTest(resource=name):
                mutated = dict(resources)
                mutated[name] += b"\x00"
                self.assertNotEqual(
                    baseline,
                    dci_complete_implementation_identity(
                        resource_reader=mutated.__getitem__,
                        resource_names=DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
                    ),
                )

    def test_transitive_identity_rejects_incomplete_ambiguous_or_unsafe_closure(
        self,
    ) -> None:
        resources = {
            name: name.encode() for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
        }
        invalid_names = (
            DCI_COMPLETE_IMPLEMENTATION_RESOURCES[:-1],
            DCI_COMPLETE_IMPLEMENTATION_RESOURCES
            + (DCI_COMPLETE_IMPLEMENTATION_RESOURCES[-1],),
            DCI_COMPLETE_IMPLEMENTATION_RESOURCES + ("dci/../judge.py",),
            (*DCI_COMPLETE_IMPLEMENTATION_RESOURCES[:-1], ["dci/judge.py"]),
        )
        for names in invalid_names:
            with self.subTest(names=names), self.assertRaisesRegex(
                ValueError, "^DCI implementation resource closure is invalid$"
            ):
                dci_complete_implementation_identity(
                    resource_reader=resources.__getitem__,
                    resource_names=names,
                )

        def missing(_name: str) -> bytes:
            raise FileNotFoundError("/SENTINEL_PRIVATE/source.py")

        with self.assertRaises(ValueError) as raised:
            dci_complete_implementation_identity(
                resource_reader=missing,
                resource_names=DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
            )
        self.assertEqual(
            str(raised.exception),
            "DCI implementation resource closure is unavailable",
        )
        self.assertNotIn("SENTINEL", str(raised.exception))

        with self.assertRaisesRegex(
            ValueError, "^DCI implementation resource closure is unavailable$"
        ):
            dci_complete_implementation_identity(
                resource_reader=lambda _name: bytearray(b"not exact bytes"),
                resource_names=DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
            )

    def test_complete_identity_uses_the_centralized_transitive_closure(self) -> None:
        self.assertEqual(
            complete_application_identity(),
            dci_complete_implementation_identity(),
        )

    def test_dci_assemblies_do_not_declare_runtime_internal_host_evidence(self) -> None:
        for assembly_path in sorted(ASSEMBLIES.glob("dci-*.json")):
            with self.subTest(assembly=assembly_path.name):
                assembly = json.loads(assembly_path.read_text())
                self.assertEqual(assembly["host_events"], [])
                self.assertEqual(assembly["host_artifacts"], [])

    def test_only_complete_assemblies_declare_answer_judge(self) -> None:
        corpus_bound = {
            "dci-complete-application-claude.json",
            "dci-complete-application-pi.json",
            "dci-research-capability-claude.json",
            "dci-research-capability.json",
        }
        judge_bound = {
            "dci-complete-application-claude.json",
            "dci-complete-application-pi.json",
        }
        for assembly_path in sorted(ASSEMBLIES.glob("dci-*.json")):
            with self.subTest(assembly=assembly_path.name):
                assembly = json.loads(assembly_path.read_text())
                expected = (
                    ["corpus.local-root", "evaluation.answer-judge"]
                    if assembly_path.name in judge_bound
                    else ["corpus.local-root"]
                    if assembly_path.name in corpus_bound
                    else []
                )
                self.assertEqual(assembly["host_capabilities"], expected)

    def test_pi_and_claude_share_the_exact_five_stage_graph(self) -> None:
        pi = plan("pi.reference")
        claude = plan("claude-code.reference")

        self.assertEqual(pi.application_id, "dci.complete-application")
        self.assertEqual(claude.application_id, pi.application_id)
        self.assertEqual(pi.composition.package_ids, ORDER)
        self.assertEqual(claude.composition.package_ids, ORDER)
        self.assertEqual(
            tuple(
                manifest["package_id"]
                for manifest in pi.package_manifests
                if manifest["kind"] != "policy"
            ),
            STAGES,
        )
        self.assertEqual(pi.package_refs, claude.package_refs)

    def test_every_stage_declares_one_exact_event_and_artifact_edge(self) -> None:
        manifests = {
            manifest["package_id"]: manifest
            for manifest in plan("pi.reference").package_manifests
        }

        for index, package_id in enumerate(STAGES):
            with self.subTest(package_id=package_id):
                manifest = manifests[package_id]
                self.assertEqual(manifest["emits_events"], (EVENTS[index],))
                self.assertEqual(manifest["produces_artifacts"], (ARTIFACTS[index],))
                if index:
                    self.assertEqual(
                        manifest["consumes_events"], (EVENTS[index - 1],)
                    )
                    self.assertEqual(
                        manifest["consumes_artifacts"], (ARTIFACTS[index - 1],)
                    )

    def test_research_consumes_the_direct_request_without_host_evidence(self) -> None:
        manifest = json.loads((MANIFESTS / "dci-research.json").read_text())

        self.assertEqual(manifest["consumes_events"], [])
        self.assertEqual(manifest["consumes_artifacts"], [])

    def test_complete_graph_does_not_require_shell_web_or_subagents(self) -> None:
        for runtime_id in ("pi.reference", "claude-code.reference"):
            with self.subTest(runtime_id=runtime_id):
                resolved = plan(runtime_id)
                self.assertEqual(resolved.runtime_capabilities, ("filesystem.read",))
                required = {
                    capability
                    for manifest in resolved.package_manifests
                    for capability in manifest["requires_capabilities"]
                }
                self.assertNotIn("shell", required)
                self.assertFalse(
                    required
                    & {"network", "web.fetch", "web.search", "agent.subagent"}
                )


class DciCompleteApplicationBindingTests(unittest.TestCase):
    def test_provider_creation_is_metadata_only(self) -> None:
        provider_source = (
            SOURCE / "applications/dci_agent_lite/provider.py"
        ).read_text()
        with (
            patch(
                "asterion.dci.application_executor.EnvironmentDciRunExecutor.__init__",
                side_effect=AssertionError("executor construction"),
            ),
            patch.object(Path, "cwd", side_effect=AssertionError("cwd access")),
        ):
            provider = create_provider()

        self.assertEqual(provider.provider_id, "dci-agent-lite")
        for forbidden in (
            "EnvironmentDciRunExecutor",
            "native_executor",
            "os.environ",
            "Path.cwd",
        ):
            self.assertNotIn(forbidden, provider_source)

    def test_installed_provider_binds_every_executable_stage_exactly_once(self) -> None:
        application = next(
            application
            for application in create_provider().applications
            if application.application_id == "dci.complete-application"
        )
        self.assertEqual(application.runtime_ids, ("claude-code.reference", "pi.reference"))
        self.assertEqual(
            tuple(binding[0].package_id for binding in application.implementations),
            STAGES,
        )
        self.assertEqual(
            {path.name for path in application.assembly_paths},
            {
                "dci-complete-application-claude.json",
                "dci-complete-application-pi.json",
            },
        )

    def test_implementation_identity_is_stable_and_digest_shaped(self) -> None:
        identity = complete_application_identity()
        self.assertEqual(len(identity), 64)
        self.assertEqual(identity, complete_application_identity())

    def test_generic_cli_exposes_only_complete_public_artifact_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            corpus = root / "SENTINEL_PRIVATE_PATH"
            corpus.mkdir()
            runtime = _CompletedRuntime(
                "pi.reference", root / "private-run-output"
            )
            provider_entry = FakeEntryPoint(
                name="dci-agent-lite", factory=create_provider
            )
            host_entries = (
                FakeEntryPoint(
                    name="corpus.local-root",
                    group="asterion.host_services",
                    factory=create_local_corpus_service_factory,
                ),
                FakeEntryPoint(
                    name="evaluation.answer-judge",
                    group="asterion.host_services",
                    factory=create_answer_judge_service_factory,
                ),
            )
            registry = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="pi.reference",
                        capabilities=("filesystem.read",),
                        factory=lambda context: runtime,
                    ),
                    RuntimeFactoryBinding(
                        runtime_id="claude-code.reference",
                        capabilities=("filesystem.read",),
                        factory=lambda context: (_ for _ in ()).throw(
                            AssertionError("unselected runtime")
                        ),
                    ),
                )
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            async def answer_judge(**kwargs):
                self.assertEqual(kwargs["question"], "SENTINEL_QUESTION")
                self.assertEqual(kwargs["gold_answer"], "SENTINEL_GOLD")
                self.assertEqual(
                    kwargs["predicted_answer"], "PRIVATE ANSWER"
                )
                self.assertEqual(kwargs["config"].api_key, "SENTINEL_KEY")
                return {
                    "is_correct": True,
                    "judge_request_fingerprint": "f" * 64,
                }

            with (
                patch.dict(
                    "os.environ",
                    {
                        "DCI_EVAL_JUDGE_API_KEY": "SENTINEL_KEY",
                        "DCI_EVAL_JUDGE_API_KEY_ENV": "SENTINEL_KEY_SOURCE",
                        "DCI_EVAL_JUDGE_BASE_URL": (
                            "https://sentinel-endpoint.invalid/v1"
                        ),
                        "DCI_EVAL_JUDGE_MODEL": "SENTINEL_MODEL",
                        "DCI_EVAL_JUDGE_TIMEOUT_SECONDS": "17",
                        "DCI_EVAL_JUDGE_MAX_OUTPUT_TOKENS": "23",
                    },
                    clear=False,
                ),
                patch(
                    "asterion.dci.services.judge_answer_async",
                    answer_judge,
                ),
            ):
                code = main(
                    [
                        "run",
                        "--provider",
                        "dci-agent-lite",
                        "--runtime",
                        "pi.reference",
                        "--application",
                        "dci.complete-application@1.0.0",
                        "--host-option",
                        f"corpus.local-root:root={corpus}",
                        "--run-id",
                        "complete-cli",
                        "--input",
                        json.dumps(
                            {
                                "protocol": INPUT_PROTOCOL,
                                "question": "SENTINEL_QUESTION",
                                "gold_answer": "SENTINEL_GOLD",
                            }
                        ),
                    ],
                    entry_points=(provider_entry,),
                    host_service_entry_points=host_entries,
                    runtime_factories=registry,
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        research = payload["artifacts"][0]["value"]
        self.assertEqual(research["status"], "completed")
        self.assertEqual(
            research["stage_data"]["artifact_ids"], ["answer"]
        )
        rendered = stdout.getvalue() + stderr.getvalue()
        for sentinel in (
            "SENTINEL_QUESTION",
            "SENTINEL_GOLD",
            "PRIVATE ANSWER",
            "SENTINEL_KEY",
            "SENTINEL_KEY_SOURCE",
            "SENTINEL_PRIVATE_PATH",
            "sentinel-endpoint",
            "SENTINEL_MODEL",
        ):
            self.assertNotIn(sentinel, rendered)


class _UnusedPiRuntime:
    manifest = RuntimeManifest("pi.reference", ("filesystem.read",))

    async def run(
        self, request: RunRequest, *, signal: object | None = None
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        raise AssertionError("unused runtime was called")
        yield


class _CompletedRuntime:
    def __init__(self, runtime_id: str, output_dir: Path) -> None:
        capabilities = (
            ("claude.tool.glob", "claude.tool.grep", "filesystem.read")
            if runtime_id == "claude-code.reference"
            else ("filesystem.read", "shell")
        )
        self.manifest = RuntimeManifest(runtime_id, capabilities)
        self.output_dir = output_dir
        self.requests = []
        self.calls = 0

    async def run(self, request: RunRequest, *, signal=None):
        del signal
        self.calls += 1
        self.requests.append(request)
        self.output_dir.mkdir(mode=0o700)
        final_path = self.output_dir / "final.txt"
        final_path.write_text("PRIVATE ANSWER\n")
        final_path.chmod(0o600)
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": list(request.requested_capabilities)})
        yield RunEvent(request.run_id, 2, "artifact.created", {"artifact": {"artifact_id": "answer", "kind": "answer", "media_type": "text/plain", "uri": "final.txt"}})
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})

    def completed_run_dir(self, run_id: str) -> Path:
        del run_id
        return self.output_dir


class DciCompleteApplicationExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_requires_corpus_before_runtime_invocation(self) -> None:
        runtime = _CompletedRuntime("pi.reference", PROJECT / "unused-run")
        invocation = PackageInvocation(
            package_ref=PackageRef("dci.research", "1.0.0"),
            manifest=json.loads((MANIFESTS / "dci-research.json").read_text()),
            run_id="missing-corpus",
            input_text=json.dumps(
                {
                    "protocol": INPUT_PROTOCOL,
                    "question": "SECRET QUESTION",
                    "gold_answer": "SECRET GOLD",
                }
            ),
            upstream_artifacts=(),
            runtime=runtime,
            host_services={},
        )

        with self.assertRaises(PackageExecutionError) as raised:
            await DciCompleteResearchImplementation().execute(invocation)

        self.assertEqual(runtime.calls, 0)
        self.assertNotIn("SECRET", str(raised.exception))

    async def test_stage_rejects_wrong_upstream_schema_or_implementation(self) -> None:
        implementation = DciCompleteBenchmarkImplementation()
        for value in (
            {"schema": "wrong", "implementation_sha256": complete_application_identity(), "is_correct": True},
            {"schema": "asterion.dci.complete-application/v1", "implementation_sha256": "0" * 64, "is_correct": True},
        ):
            with self.subTest(value=value), self.assertRaises(PackageExecutionError):
                await implementation.execute(
                    PackageInvocation(
                        package_ref=PackageRef("dci.benchmark", "1.0.0"),
                        manifest={},
                        run_id="tampered-upstream",
                        input_text="",
                        upstream_artifacts=(
                            {
                                "artifact_id": "verdict",
                                "media_type": "application/vnd.dci.verdict+json",
                                "value": value,
                            },
                        ),
                        runtime=_UnusedPiRuntime(),
                        host_services={},
                    )
                )

    async def test_complete_preflight_requires_judge_before_runtime_invocation(
        self,
    ) -> None:
        runtime = _CompletedRuntime("pi.reference", PROJECT / "unused-run")
        with self.assertRaises(ApplicationRunError) as raised:
            await run_composed_application(
                plan("pi.reference"),
                implementations=(
                    (PackageRef("dci.research", "1.0.0"), DciCompleteResearchImplementation()),
                    (PackageRef("dci.evaluation", "1.0.0"), DciCompleteEvaluationImplementation()),
                    (PackageRef("dci.benchmark", "1.0.0"), DciCompleteBenchmarkImplementation()),
                    (PackageRef("dci.analysis", "1.0.0"), DciCompleteAnalysisImplementation()),
                    (PackageRef("dci.export", "1.0.0"), DciCompleteExportImplementation()),
                ),
                runtime=runtime,
                run_id="missing-judge",
                input_text=json.dumps(
                    {
                        "protocol": INPUT_PROTOCOL,
                        "question": "SENTINEL_QUESTION",
                        "gold_answer": "SENTINEL_GOLD",
                    }
                ),
                host_services={"corpus.local-root": _CorpusService()},
            )

        self.assertEqual(runtime.calls, 0)
        self.assertNotIn("SENTINEL", str(raised.exception))

    async def test_evaluation_cancels_inflight_judge_when_signal_changes(self) -> None:
        class Signal:
            cancelled = False

        signal = Signal()
        started = asyncio.Event()
        stopped = asyncio.Event()

        class Judge(_JudgeService):
            async def judge(self, **kwargs):
                judge_signal = kwargs["signal"]
                started.set()
                try:
                    while not judge_signal.cancelled:
                        await asyncio.sleep(0.01)
                    raise RuntimeError("cancelled")
                finally:
                    stopped.set()

        with tempfile.TemporaryDirectory() as directory:
            stage_data = InProcessArtifactPayload(
                private_value={
                    "question": "question",
                    "gold_answer": "gold",
                    "predicted_answer": "answer",
                    "output_dir": Path(directory),
                },
                public_projection={
                    "status": "completed",
                    "question_sha256": "a" * 64,
                    "gold_answer_sha256": "b" * 64,
                    "prediction_sha256": "c" * 64,
                    "evidence_sha256": "d" * 64,
                    "artifact_ids": ("answer",),
                },
            )
            implementation = DciCompleteEvaluationImplementation()
            invocation = PackageInvocation(
                package_ref=PackageRef("dci.evaluation", "1.0.0"),
                manifest={},
                run_id="cancel-evaluation",
                input_text="",
                upstream_artifacts=(
                    {
                        "artifact_id": "research",
                        "media_type": "application/vnd.dci.research+json",
                        "value": {
                            "schema": "asterion.dci.complete-application/v1",
                            "implementation_sha256": complete_application_identity(),
                            "stage_data": stage_data,
                        },
                    },
                ),
                runtime=_UnusedPiRuntime(),
                host_services=_host_services(Judge()),
                signal=signal,
            )
            task = asyncio.create_task(implementation.execute(invocation))
            await asyncio.wait_for(started.wait(), timeout=1)
            signal.cancelled = True

            with self.assertRaises(PackageExecutionError):
                await asyncio.wait_for(task, timeout=3)
            self.assertTrue(stopped.is_set())

    async def test_evaluation_binds_only_the_opaque_judge_identity(self) -> None:
        async def evaluate_with(identity: dict[str, object], directory: Path):
            directory.mkdir()
            stage_data = InProcessArtifactPayload(
                private_value={
                    "question": "SENTINEL_QUESTION",
                    "gold_answer": "SENTINEL_GOLD",
                    "predicted_answer": "SENTINEL_PREDICTION",
                    "output_dir": directory,
                },
                public_projection={
                    "status": "completed",
                    "question_sha256": "a" * 64,
                    "gold_answer_sha256": "b" * 64,
                    "prediction_sha256": "c" * 64,
                    "evidence_sha256": "d" * 64,
                    "artifact_ids": ("answer",),
                },
            )
            result = await DciCompleteEvaluationImplementation().execute(
                PackageInvocation(
                    package_ref=PackageRef("dci.evaluation", "1.0.0"),
                    manifest={},
                    run_id=directory.name,
                    input_text="",
                    upstream_artifacts=(
                        {
                            "artifact_id": "research",
                            "media_type": "application/vnd.dci.research+json",
                            "value": {
                                "schema": "asterion.dci.complete-application/v1",
                                "implementation_sha256": complete_application_identity(),
                                "stage_data": stage_data,
                            },
                        },
                    ),
                    runtime=_UnusedPiRuntime(),
                    host_services=_host_services(_JudgeService(identity)),
                )
            )
            return result.artifacts[0]["value"]["judge_identity_sha256"]

        baseline = {
            "schema": "asterion.dci.answer-judge-identity/v1",
            "adapter_id": "dci.openai-compatible",
            "config_sha256": "1" * 64,
            "request_shape_sha256": "2" * 64,
            "prompt_contract_sha256": "3" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = await evaluate_with(baseline, root / "first")
            repeated = await evaluate_with(
                dict(reversed(tuple(baseline.items()))), root / "repeated"
            )
            changed = await evaluate_with(
                {**baseline, "config_sha256": "4" * 64}, root / "changed"
            )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, changed)

    async def test_cancelled_judge_stops_all_later_stages(self) -> None:
        class Signal:
            cancelled = False

        class Judge(_JudgeService):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.stopped = asyncio.Event()

            async def judge(self, **kwargs):
                self.calls.append(kwargs)
                self.started.set()
                try:
                    while not kwargs["signal"].cancelled:
                        await asyncio.sleep(0.01)
                    raise RuntimeError("SENTINEL_JUDGE_FAILURE")
                finally:
                    self.stopped.set()

        class LaterStage:
            def __init__(self) -> None:
                self.calls = 0

            async def execute(self, invocation):
                del invocation
                self.calls += 1
                raise AssertionError("later stage ran")

        with tempfile.TemporaryDirectory() as directory:
            runtime = _CompletedRuntime(
                "pi.reference", Path(directory) / "cancelled-run"
            )
            signal = Signal()
            judge = Judge()
            later = [LaterStage(), LaterStage(), LaterStage()]
            task = asyncio.create_task(
                run_composed_application(
                    plan("pi.reference"),
                    implementations=(
                        (
                            PackageRef("dci.research", "1.0.0"),
                            DciCompleteResearchImplementation(),
                        ),
                        (
                            PackageRef("dci.evaluation", "1.0.0"),
                            DciCompleteEvaluationImplementation(),
                        ),
                        (PackageRef("dci.benchmark", "1.0.0"), later[0]),
                        (PackageRef("dci.analysis", "1.0.0"), later[1]),
                        (PackageRef("dci.export", "1.0.0"), later[2]),
                    ),
                    runtime=runtime,
                    run_id="cancelled-complete",
                    input_text=json.dumps(
                        {
                            "protocol": INPUT_PROTOCOL,
                            "question": "SENTINEL_QUESTION",
                            "gold_answer": "SENTINEL_GOLD",
                        }
                    ),
                    host_services=_host_services(judge),
                    signal=signal,
                )
            )
            await asyncio.wait_for(judge.started.wait(), timeout=1)
            signal.cancelled = True
            with self.assertRaises(ApplicationRunError) as raised:
                await asyncio.wait_for(task, timeout=3)

        self.assertTrue(judge.stopped.is_set())
        self.assertIs(judge.calls[0]["signal"], signal)
        self.assertEqual([implementation.calls for implementation in later], [0, 0, 0])
        self.assertNotIn("SENTINEL", str(raised.exception))

    async def test_claude_run_is_judged_and_exports_without_private_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _CompletedRuntime(
                "claude-code.reference", Path(directory) / "claude-run"
            )
            judge = _JudgeService()

            bindings = (
                (PackageRef("dci.research", "1.0.0"), DciCompleteResearchImplementation()),
                (PackageRef("dci.evaluation", "1.0.0"), DciCompleteEvaluationImplementation()),
                (PackageRef("dci.benchmark", "1.0.0"), DciCompleteBenchmarkImplementation()),
                (PackageRef("dci.analysis", "1.0.0"), DciCompleteAnalysisImplementation()),
                (PackageRef("dci.export", "1.0.0"), DciCompleteExportImplementation()),
            )
            result = await run_composed_application(
                plan("claude-code.reference"),
                implementations=bindings,
                runtime=runtime,
                run_id="claude-complete",
                input_text=json.dumps({"protocol": INPUT_PROTOCOL, "question": "PRIVATE QUESTION", "gold_answer": "PRIVATE GOLD"}),
                host_services=_host_services(judge),
            )

        self.assertEqual(
            runtime.requests[0].requested_capabilities, ("filesystem.read",)
        )
        self.assertEqual(judge.calls[0]["predicted_answer"], "PRIVATE ANSWER")
        self.assertEqual(tuple(event["type"] for event in result.events), EVENTS)
        self.assertNotIn("PRIVATE", repr(result))

    async def test_pi_run_uses_selected_runtime_and_exports_without_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _CompletedRuntime("pi.reference", Path(directory) / "pi-run")
            judge = _JudgeService()

            bindings = (
                (PackageRef("dci.research", "1.0.0"), DciCompleteResearchImplementation()),
                (PackageRef("dci.evaluation", "1.0.0"), DciCompleteEvaluationImplementation()),
                (PackageRef("dci.benchmark", "1.0.0"), DciCompleteBenchmarkImplementation()),
                (PackageRef("dci.analysis", "1.0.0"), DciCompleteAnalysisImplementation()),
                (PackageRef("dci.export", "1.0.0"), DciCompleteExportImplementation()),
            )
            with patch(
                "asterion.dci.application_executor.EnvironmentDciRunExecutor.run",
                side_effect=AssertionError("native bypass"),
            ):
                result = await run_composed_application(
                    plan("pi.reference"),
                    implementations=bindings,
                    runtime=runtime,
                    run_id="complete-run",
                    input_text=json.dumps(
                        {
                            "protocol": INPUT_PROTOCOL,
                            "question": "PRIVATE QUESTION",
                            "gold_answer": "PRIVATE GOLD",
                        }
                    ),
                    host_services=_host_services(judge),
                )

        self.assertEqual(runtime.calls, 1)
        self.assertEqual(runtime.requests[0].input_text, "PRIVATE QUESTION")
        self.assertEqual(
            runtime.requests[0].requested_capabilities, ("filesystem.read",)
        )
        self.assertEqual(judge.calls[0]["predicted_answer"], "PRIVATE ANSWER")
        self.assertEqual(tuple(event["type"] for event in result.events), EVENTS)
        self.assertEqual(tuple(item["media_type"] for item in result.artifacts), ARTIFACTS)
        self.assertEqual(
            {
                item["value"].get("implementation_sha256")
                for item in result.artifacts
            },
            {complete_application_identity()},
        )
        self.assertEqual(result.artifacts[-1]["value"]["total"], 1)
        self.assertNotIn("PRIVATE", repr(result))
        projected = project_public_value(result.__dict__)
        rendered = json.dumps(projected, sort_keys=True)
        self.assertNotIn("PRIVATE QUESTION", rendered)
        self.assertNotIn("PRIVATE GOLD", rendered)
        self.assertNotIn("PRIVATE ANSWER", rendered)


class DciRestrictedPiEvidenceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        run = root / "run"
        corpus = root / "corpus"
        (run / "protocol").mkdir(parents=True)
        corpus.mkdir()
        documents = {
            run / "state.json": {"status": "completed", "tools": "read,grep", "max_turns": 4},
            run / "protocol/attempt-0001.request.json": {"requested_capabilities": ["filesystem.read", "pi.tool.grep"]},
            run / "eval_result.json": {"is_correct": True, "judge_request_fingerprint": "a" * 64},
        }
        for path, value in documents.items():
            path.write_text(json.dumps(value))
            path.chmod(0o600)
        events = (
            {"type": "tool.call", "payload": {"name": "read", "arguments": {"path": "missing.txt"}}},
            {"type": "tool.call", "payload": {"name": "read", "arguments": {"path": "document.txt"}}},
            {"type": "tool.call", "payload": {"name": "grep", "arguments": {"path": "."}}},
            {"type": "tool.result", "payload": {"is_error": True}},
            {"type": "tool.result", "payload": {"is_error": True}},
        )
        event_path = run / "protocol/attempt-0001.events.jsonl"
        event_path.write_text("".join(json.dumps(event) + "\n" for event in events))
        event_path.chmod(0o600)
        return run, corpus

    def test_bounded_private_evidence_is_body_free_and_corpus_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, corpus = self._fixture(Path(directory))
            report = audit_restricted_pi_application(run_dir=run, corpus_dir=corpus)

        self.assertEqual(report["tools"], {"read": 2, "grep": 1})
        self.assertEqual(report["tool_error_count"], 2)
        self.assertTrue(report["corpus_contained"])
        self.assertNotIn("cobalt lantern", repr(report))

    def test_absolute_outside_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, corpus = self._fixture(Path(directory))
            path = run / "protocol/attempt-0001.events.jsonl"
            events = json.loads(path.read_text().splitlines()[0])
            events["payload"]["arguments"]["path"] = "/outside/answer.txt"
            path.write_text(json.dumps(events) + "\n")
            path.chmod(0o600)
            with self.assertRaises(DciDualRuntimeVerificationError):
                audit_restricted_pi_application(run_dir=run, corpus_dir=corpus)

class DciRestrictedClaudeEvidenceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        run = root / "run"
        corpus = root / "corpus"
        run.mkdir(mode=0o700)
        corpus.mkdir()
        documents = {
            "request.json": {"run_id": "fixture-run", "requested_capabilities": ["filesystem.read", "claude.tool.grep", "claude.tool.glob"]},
            "runtime-policy.json": {
                "runtime_cwd": str(corpus.resolve()),
                "agent_provider": "minimax", "agent_model": "fixture-model",
                "tools": ["Read", "Grep", "Glob"], "allowed_tools": ["Read", "Grep", "Glob"],
                "max_turns": 4, "permission_mode": "dontAsk", "strict_mcp": True,
                "mcp_servers": {}, "safe_mode": True, "no_session_persistence": True,
                "settings": {"sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False}},
            },
            "eval_result.json": {"is_correct": True, "judge_request_fingerprint": "c" * 64},
        }
        for name, value in documents.items():
            path = run / name
            path.write_text(json.dumps(value))
            path.chmod(0o600)
        raw_events = (
            {"type": "system", "subtype": "init", "tools": ["Glob", "Grep", "Read"], "cwd": str(corpus.resolve()), "model": "fixture-model", "claude_code_version": "fixture-version"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "call-1", "name": "Grep", "input": {"path": "."}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "cobalt lantern", "is_error": False}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "cobalt lantern"},
        )
        events = []
        adapter = ClaudeCodeProtocolAdapter(run_id="fixture-run", emit=events.append)
        for raw_event in raw_events:
            adapter.consume(raw_event)
        for name, value in {
            "events.jsonl": "".join(json.dumps(event) + "\n" for event in events),
            "raw-events.jsonl": "".join(json.dumps(event) + "\n" for event in raw_events),
            "final.txt": "cobalt lantern\n",
        }.items():
            path = run / name
            path.write_text(value)
            path.chmod(0o600)
        return run, corpus

    def test_private_evidence_is_body_free_and_corpus_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, corpus = self._fixture(Path(directory))
            report = audit_restricted_claude_application(run_dir=run, corpus_dir=corpus)
        self.assertEqual(report["tools"], {"Read": 0, "Grep": 1, "Glob": 0})
        self.assertEqual(report["agent_provider"], "minimax")
        self.assertEqual(report["agent_model"], "fixture-model")
        self.assertEqual(report["agent_operations"], 1)
        self.assertNotIn("cobalt lantern", repr(report))

    def test_arbitrary_raw_stream_cannot_certify_normalized_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, corpus = self._fixture(Path(directory))
            path = run / "raw-events.jsonl"
            path.write_text("private raw stream\n")
            path.chmod(0o600)
            with self.assertRaises(DciDualRuntimeVerificationError):
                audit_restricted_claude_application(run_dir=run, corpus_dir=corpus)

    def test_outside_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, corpus = self._fixture(Path(directory))
            path = run / "events.jsonl"
            events = [json.loads(line) for line in path.read_text().splitlines()]
            events[1]["payload"]["arguments"]["path"] = "/outside"
            path.write_text("".join(json.dumps(event) + "\n" for event in events))
            path.chmod(0o600)
            with self.assertRaises(DciDualRuntimeVerificationError):
                audit_restricted_claude_application(run_dir=run, corpus_dir=corpus)

    def test_policy_working_directory_must_equal_audited_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, corpus = self._fixture(Path(directory))
            path = run / "runtime-policy.json"
            policy = json.loads(path.read_text())
            policy["runtime_cwd"] = str(run.resolve())
            path.write_text(json.dumps(policy))
            path.chmod(0o600)
            with self.assertRaises(DciDualRuntimeVerificationError):
                audit_restricted_claude_application(run_dir=run, corpus_dir=corpus)

    def test_terminal_binding_rejects_tracked_digest_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, corpus = self._fixture(root)
            report = audit_restricted_claude_application(
                run_dir=run, corpus_dir=corpus
            )
            report_path = root / "report.json"
            report_sha256 = write_private_report(report_path, report)
            record = build_restricted_claude_record(
                report,
                report_sha256=report_sha256,
                source_commit="1" * 40,
                source_sha256="2" * 64,
            )
            record["report_sha256"] = "3" * 64
            record_path = root / "record.json"
            record_path.write_text(json.dumps(record))

            with self.assertRaises(DciDualRuntimeVerificationError):
                verify_restricted_claude_binding(
                    repo_root=PROJECT.parent,
                    run_dir=run,
                    corpus_dir=corpus,
                    report_path=report_path,
                    record_path=record_path,
                )

        self.assertEqual(
            record["schema"], "asterion.dci.climb-provider-evidence/v2"
        )
        self.assertEqual(record["agent_operations"], 1)
        self.assertEqual(record["agent_provider"], "minimax")
        self.assertEqual(record["agent_model"], "fixture-model")
        self.assertNotIn("cobalt lantern", repr(record))

if __name__ == "__main__":
    unittest.main()
