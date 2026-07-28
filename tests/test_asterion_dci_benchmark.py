from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from importlib import resources
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import cast
from unittest.mock import Mock, patch

from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    BenchmarkResult,
    BenchmarkRequest,
    DciBenchmarkError,
    _fingerprint,
    _prepare,
    _validate_config_document,
    run_benchmark,
    validate_benchmark_metric_selection,
)
from asterion.capabilities.dci.implementation.evaluation.artifacts import DciConversationFeatures
from asterion.dci.cli import main as dci_main
from asterion.capabilities.dci.implementation.config import DciRuntimeOptions, resolve_dci_paths
from asterion.capabilities.dci.implementation.research.experiment_profiles import (
    ExperimentAuthorizationError,
    ExperimentProfile,
    FullExecutionAuthorization,
    _authorized_manifest_output_identity,
    authorize_full_execution,
    authorized_scope_output_root,
    consume_full_execution_authorization,
    experiment_profile_ids,
    experiment_profile_schema_sha256,
    experiment_profiles_sha256,
    reserve_full_execution_operation,
    resolve_experiment_profile,
)
from asterion.capabilities.dci.implementation.evaluation.judge import (
    UPSTREAM_JUDGE_CONTRACT,
    JudgeConfig,
    judge_prompt_contract_sha256,
    judge_request_shape_sha256,
)
from asterion.capabilities.dci.implementation.reproduction.paper_benchmarks import (
    DatasetInputBinding,
    canonical_sha256,
    published_scope_selected_ids,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.capabilities.dci.implementation.runtime.pi_rpc import FINAL_ANSWER_RECOVERY_PROMPT
from asterion.capabilities.dci.implementation.research.prompts import (
    PROMPT_CONTRACTS,
    PromptContractError,
    prompt_contract_sha256,
    resolve_prompt_contract,
)
from asterion.capabilities.dci.implementation.reproduction.provenance import (
    DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
    dci_complete_implementation_identity,
)
from asterion.capabilities.dci.implementation.reproduction.reproduction import load_run_manifest, validate_run_manifest
from asterion.capabilities.dci.implementation.runtime.run import DciRunResult, run_pi_research as _real_run_pi_research
from asterion.runtime.host import RunEvent


def _fixture_dataset_binding(
    scope_id: str,
    *,
    raw_content_sha256: str = "a" * 64,
    device: int = 1,
    inode: int = 2,
) -> DatasetInputBinding:
    benchmark = resolve_paper_benchmark(
        resolve_paper_experiment_scope(scope_id).dataset_id
    )
    return DatasetInputBinding(
        raw_content_sha256=raw_content_sha256,
        paper_benchmark_identity_sha256=benchmark.identity_sha256,
        device=device,
        inode=inode,
    )


def _dataset_binding_for_path(
    path: Path,
    scope_id: str,
) -> DatasetInputBinding:
    metadata = path.stat()
    return _fixture_dataset_binding(
        scope_id,
        raw_content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _authority_dataset_binding(
    authority: FullExecutionAuthorization,
    scope_id: str,
) -> DatasetInputBinding:
    index = authority.authorized_scope_ids.index(scope_id)
    return authority.dataset_input_bindings[index]


def _bounded_authorize_full_execution(
    *,
    profile: ExperimentProfile,
    scope_ids: tuple[str, ...],
    output_root: Path,
    max_agent_operations: int,
    max_judge_operations: int,
    max_cost_usd: float,
    max_agent_cost_per_operation_usd: float,
    max_judge_cost_per_operation_usd: float,
) -> FullExecutionAuthorization:
    query_ids = tuple((f"{scope_id}.fixture-q-1",) for scope_id in scope_ids)
    return authorize_full_execution(
        profile=profile,
        scope_ids=scope_ids,
        dataset_input_bindings=tuple(
            _fixture_dataset_binding(scope_id, inode=index)
            for index, scope_id in enumerate(scope_ids, 2)
        ),
        bounded_selected_ids_sha256=tuple(
            canonical_sha256(ids) for ids in query_ids
        ),
        selected_query_counts=tuple(len(ids) for ids in query_ids),
        planned_agent_operations=sum(len(ids) for ids in query_ids),
        planned_judge_operations=0,
        output_root=output_root,
        max_agent_operations=max_agent_operations,
        max_judge_operations=max_judge_operations,
        max_cost_usd=max_cost_usd,
        max_agent_cost_per_operation_usd=max_agent_cost_per_operation_usd,
        max_judge_cost_per_operation_usd=max_judge_cost_per_operation_usd,
        invocation_authorized=True,
    )


class _FixtureClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "answer"},
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "answer"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


class _CostedFixtureClient(_FixtureClient):
    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "doc.txt",
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "usage": {
                        "input": 1,
                        "output": 1,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "cost": {
                            "input": 0.0,
                            "output": 0.0,
                            "cacheRead": 0.0,
                            "cacheWrite": 0.0,
                            "total": 0.0,
                        },
                    },
                    "content": [{"type": "text", "text": "doc.txt"}],
                },
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "doc.txt"


def _recorded_run(_paths: object, request: object, **kwargs: object) -> DciRunResult:
    with patch("asterion.capabilities.dci.implementation.runtime.run.PiRpcClient", _FixtureClient):
        return _real_run_pi_research(
            resolve_dci_paths(Path(request.cwd)), request, **kwargs
        )


class AsterionDciBenchmarkTests(unittest.TestCase):
    def test_authorized_limit_one_emits_external_limited_selection(self) -> None:
        scope_id = "bright.robotics.main.full"
        query_id = "q-001"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": query_id,
                        "query": "private question",
                        "answer": "private answer",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            dataset_binding = _dataset_binding_for_path(dataset, scope_id)
            authority = authorize_full_execution(
                profile=resolve_experiment_profile("paper-reference/pi"),
                scope_ids=(scope_id,),
                dataset_input_bindings=(dataset_binding,),
                bounded_selected_ids_sha256=(canonical_sha256((query_id,)),),
                selected_query_counts=(1,),
                planned_agent_operations=1,
                planned_judge_operations=0,
                output_root=root / "private",
                max_agent_operations=1,
                max_judge_operations=1,
                max_cost_usd=1,
                max_agent_cost_per_operation_usd=1,
                max_judge_cost_per_operation_usd=1,
                invocation_authorized=True,
            )
            request = BenchmarkRequest(
                dataset=dataset,
                dataset_input_binding=dataset_binding,
                output_root=authorized_scope_output_root(authority, scope_id),
                cwd=root,
                judge_config=JudgeConfig(),
                runtime_options=DciRuntimeOptions(provider=None, model=None),
                limit=1,
                mode="qa",
                profile="paper-reference/pi",
                analysis=False,
                figures=False,
                full_execution_authorization=authority,
                experiment_scope_id=scope_id,
            )
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark._paper_scope_for_rows",
                return_value=scope_id,
            ):
                _rows, _output, config, _items, _snapshots = _prepare(request)

        expected = {
            "schema": "asterion.dci.selection/v1",
            "execution_class": "paper-bounded-authorized",
            "id": "limit-1",
            "paper_scope": scope_id,
            "selected_rows": 1,
            "full_dataset": False,
            "comparable": False,
            "authorization_profile": "paper-reference/pi",
            "selected_ids_sha256": canonical_sha256((query_id,)),
        }
        self.assertEqual(config["selection"], expected)
        _validate_config_document(
            config,
            expected_execution_class="paper-bounded-authorized",
        )

    def test_authorized_bounded_selection_is_body_free(self) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            dataset = root / "private-dataset.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-002",
                        "query": "SECRET question body",
                        "answer": "SECRET answer body",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            dataset_binding = _dataset_binding_for_path(dataset, scope_id)
            authority = authorize_full_execution(
                profile=resolve_experiment_profile("paper-reference/pi"),
                scope_ids=(scope_id,),
                dataset_input_bindings=(dataset_binding,),
                bounded_selected_ids_sha256=(canonical_sha256(("q-001",)),),
                selected_query_counts=(1,),
                planned_agent_operations=1,
                planned_judge_operations=0,
                output_root=root / "private-output-must-not-leak",
                max_agent_operations=1,
                max_judge_operations=1,
                max_cost_usd=1,
                max_agent_cost_per_operation_usd=1,
                max_judge_cost_per_operation_usd=1,
                invocation_authorized=True,
            )
            request = BenchmarkRequest(
                dataset=dataset,
                dataset_input_binding=dataset_binding,
                output_root=authorized_scope_output_root(authority, scope_id),
                cwd=root,
                judge_config=JudgeConfig(),
                runtime_options=DciRuntimeOptions(provider=None, model=None),
                limit=1,
                mode="qa",
                profile="paper-reference/pi",
                analysis=False,
                figures=False,
                full_execution_authorization=authority,
                experiment_scope_id=scope_id,
            )
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark._paper_scope_for_rows",
                return_value=scope_id,
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark._run_pi_async"
            ) as agent:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark authorization selection changed$",
                ) as raised:
                    run_benchmark(request, paths=resolve_dci_paths(root))
            agent.assert_not_called()
            rendered = str(raised.exception)
            self.assertNotIn("q-002", rendered)
            self.assertNotIn("SECRET", rendered)
            self.assertNotIn(str(root), rendered)

    def test_resolution_requires_complete_configuration_before_agent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            request = replace(
                _request(root),
                profile="asterion-safe/pi",
                corpus=corpus,
                resolution_registry=root / "registry.json",
                resolution_segment_characters=4096,
                conversation_features=DciConversationFeatures(
                    externalize_tool_results=True
                ),
            )
            with patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run:
                with self.assertRaisesRegex(DciBenchmarkError, "resolution configuration"):
                    run_benchmark(request, paths=Mock())

        run.assert_not_called()

    def test_resolution_configuration_binds_parameter_source_overlap_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            first = _resolution_request(root, overlap=0.5)
            _rows, _output, first_config, _items, _snapshots = _prepare(first)
            second = _resolution_request(root, overlap=0.75)
            _rows, _output, second_config, _items, _snapshots = _prepare(second)

        self.assertEqual(
            first_config["resolution"]["parameter_source"],
            "asterion-defined",
        )
        self.assertEqual(first_config["resolution"]["read_minimum_evidence_overlap"], 0.5)
        self.assertNotEqual(
            first_config["run_fingerprint"], second_config["run_fingerprint"]
        )

    def test_resolution_normalizes_integer_overlap_and_accepts_persisted_json_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            _rows, _output, config, _items, _snapshots = _prepare(
                _resolution_request(root, overlap=1)
            )

        self.assertEqual(config["resolution"]["read_minimum_evidence_overlap"], 1.0)
        persisted = json.loads(json.dumps(config))
        persisted["resolution"]["read_minimum_evidence_overlap"] = 1
        persisted["run_fingerprint"] = _fingerprint(
            {
                key: value
                for key, value in persisted.items()
                if key not in {"judge", "judge_configuration_fingerprint", "run_fingerprint", "batch_fingerprint"}
            }
        )
        batch_payload = dict(persisted)
        batch_payload.pop("batch_fingerprint")
        persisted["batch_fingerprint"] = _fingerprint(batch_payload)

        _validate_config_document(persisted, expected_execution_class="non-paper")

    def test_resolution_request_rejects_invalid_overlap_and_registry_types_before_agent_execution(self) -> None:
        base = BenchmarkRequest(
            dataset=Path("/tmp/dataset.jsonl"),
            output_root=Path("/tmp/output"),
            cwd=Path("/tmp"),
            judge_config=JudgeConfig(),
            runtime_options=DciRuntimeOptions(),
            resolution_registry=Path("/tmp/registry.json"),
            resolution_segment_characters=4096,
            resolution_read_minimum_evidence_overlap=0.5,
        )
        for changes in (
            {"resolution_read_minimum_evidence_overlap": True},
            {"resolution_read_minimum_evidence_overlap": 0},
            {"resolution_read_minimum_evidence_overlap": float("inf")},
            {"resolution_registry": "/tmp/registry.json"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(DciBenchmarkError, "resolution configuration"):
                    validate_benchmark_metric_selection(replace(base, **changes))

    def test_paper_resolution_records_operator_assumptions_and_is_not_comparable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = replace(
                _resolution_request(root, overlap=0.5),
                profile="paper-reference/pi",
                runtime_options=DciRuntimeOptions(
                    provider="openai", model="gpt-5.4-nano"
                ),
                limit=1,
            )
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.paper_scope_for_profile",
                return_value="fixture-scope",
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark._paper_scope_for_rows",
                return_value="fixture-scope",
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.resolve_paper_experiment_scope",
                return_value=Mock(dataset_id="fixture-dataset"),
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.resolve_paper_benchmark",
                return_value=Mock(dataset_id="fixture-dataset"),
            ):
                _rows, _output, config, _items, _snapshots = _prepare(request)

        self.assertEqual(
            config["resolution"]["operator_assumptions"],
            {
                "segment_characters": "asterion.operator-assumption/paper-resolution-segment-characters/v1",
                "read_minimum_evidence_overlap": "asterion.operator-assumption/paper-resolution-read-overlap/v1",
            },
        )
        self.assertFalse(config["selection"]["comparable"])

    def test_rehashed_resolution_configuration_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            _rows, _output, config, _items, _snapshots = _prepare(_request(root))

        forged = json.loads(json.dumps(config))
        forged["resolution"] = {"parameter_source": "forged"}
        forged["run_fingerprint"] = _fingerprint(
            {
                key: value
                for key, value in forged.items()
                if key not in {"judge", "judge_configuration_fingerprint", "run_fingerprint", "batch_fingerprint"}
            }
        )
        batch_payload = dict(forged)
        batch_payload.pop("batch_fingerprint")
        forged["batch_fingerprint"] = _fingerprint(batch_payload)

        with self.assertRaisesRegex(DciBenchmarkError, "configuration evidence"):
            _validate_config_document(forged, expected_execution_class="non-paper")

    def test_paper_resolution_requires_explicit_overlap_before_execution(self) -> None:
        request = BenchmarkRequest(
            dataset=Path("/tmp/dataset.jsonl"),
            output_root=Path("/tmp/output"),
            cwd=Path("/tmp"),
            judge_config=JudgeConfig(),
            runtime_options=DciRuntimeOptions(provider="openai", model="gpt-5.4-nano"),
            profile="paper-reference/pi",
            resolution_registry=Path("/tmp/registry.json"),
            resolution_segment_characters=4096,
        )

        with self.assertRaisesRegex(DciBenchmarkError, "resolution configuration"):
            validate_benchmark_metric_selection(request)

    def test_benchmark_cli_propagates_explicit_resolution_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            corpus = root / "corpus"
            corpus.mkdir()
            registry = root / "registry.json"
            registry.write_text("{}\n", encoding="utf-8")
            dataset.write_text(
                json.dumps({"query_id": "q-1", "query": "question", "answer": "answer"}) + "\n",
                encoding="utf-8",
            )
            captured: list[BenchmarkRequest] = []

            def capture(request: BenchmarkRequest, *, paths: object) -> BenchmarkResult:
                del paths
                captured.append(request)
                return BenchmarkResult(request.output_root, {"total": 1})

            with patch("asterion.dci.cli.run_benchmark", side_effect=capture), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ):
                stdout = __import__("io").StringIO()
                stderr = __import__("io").StringIO()
                code = dci_main(
                    [
                        "benchmark",
                        "--dataset", str(dataset),
                        "--output-root", str(root / "out"),
                        "--cwd", str(root),
                        "--corpus", str(corpus),
                        "--resolution-registry", str(registry),
                        "--resolution-segment-characters", "4096",
                        "--resolution-read-minimum-evidence-overlap", "0.75",
                    ],
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(captured[0].resolution_read_minimum_evidence_overlap, 0.75)

    def test_benchmark_cli_propagates_coordinator_output_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            corpus = root / "corpus"
            output = root / "out"
            corpus.mkdir()
            output.mkdir(mode=0o700)
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-1",
                        "query": "question",
                        "answer": "answer",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            metadata = output.stat()
            captured: list[BenchmarkRequest] = []

            def capture(
                request: BenchmarkRequest, *, paths: object
            ) -> BenchmarkResult:
                del paths
                captured.append(request)
                return BenchmarkResult(request.output_root, {"total": 1})

            with (
                patch.dict(
                    os.environ,
                    {
                        "ASTERION_DCI_EXPECTED_OUTPUT_DEVICE": str(
                            metadata.st_dev
                        ),
                        "ASTERION_DCI_EXPECTED_OUTPUT_INODE": str(
                            metadata.st_ino
                        ),
                    },
                ),
                patch(
                    "asterion.dci.cli.run_benchmark",
                    side_effect=capture,
                ),
                patch("asterion.dci.cli.validate_dci_run_request"),
            ):
                code = dci_main(
                    [
                        "benchmark",
                        "--dataset",
                        str(dataset),
                        "--output-root",
                        str(output),
                        "--cwd",
                        str(root),
                        "--corpus",
                        str(corpus),
                    ],
                    repo_root=root,
                    stdout=__import__("io").StringIO(),
                    stderr=__import__("io").StringIO(),
                )

        self.assertEqual(code, 0)
        self.assertEqual(
            captured[0].expected_output_root_identity,
            (metadata.st_dev, metadata.st_ino),
        )

    def test_ablation_propagates_its_exact_resolution_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            captured: list[BenchmarkRequest] = []

            def capture(request: BenchmarkRequest, *, paths: object) -> BenchmarkResult:
                del paths
                captured.append(request)
                return BenchmarkResult(request.output_root, {"total": 1})

            with patch("asterion.dci.cli.run_benchmark", side_effect=capture), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ):
                code = dci_main(
                    [
                        "benchmark",
                        "--ablation-row", "bounded.context.level0",
                        "--output-root", str(root / "out"),
                    ],
                    repo_root=root,
                    stdout=__import__("io").StringIO(),
                    stderr=__import__("io").StringIO(),
                )

        self.assertEqual(code, 0)
        self.assertEqual(captured[0].resolution_read_minimum_evidence_overlap, 0.5)

    def setUp(self) -> None:
        from asterion.capabilities.dci.implementation.research import experiment_profiles

        experiment_profiles._profiles.cache_clear()
        self.addCleanup(experiment_profiles._profiles.cache_clear)

    def test_prompt_contracts_match_source_family_golden_fixtures(self) -> None:
        fixture_root = Path(__file__).parent / "fixtures" / "dci_prompts"
        corpus = Path("/__dci_prompt_contract_corpus__")
        query = "__DCI_QUERY__"
        hint = "__DCI_CORPUS_HINT__"
        cases = (
            (
                "dci.paper-prompt/arxiv:2605.05242v1/v1",
                "paper-reference",
                "qa",
                "paper-qa.txt",
                "11466c7e3ce009558cfc23a3c2c6a4f7abb050164de9504e259c7da52fc331f5",
                lambda contract: contract.qa_builder(query, corpus),
            ),
            (
                "dci.upstream-github-prompt/271f37e71f053bf0c99c05ce6d2fb53b841d922e/v1",
                "upstream-github",
                "qa",
                "upstream-github-qa.txt",
                "e6b71b71aeb62fe43f097efe1a207ebe4ad0114d919460c574475e001823991e",
                lambda contract: contract.qa_builder(query, corpus),
            ),
            (
                "dci.upstream-github-prompt/271f37e71f053bf0c99c05ce6d2fb53b841d922e/v1",
                "upstream-github",
                "ir",
                "upstream-github-ir.txt",
                "24b6db054787487eec7286f6b20f416acbcafba8ba45cacc50d1dc4a4231a78c",
                lambda contract: contract.ir_builder(query, corpus, hint),
            ),
            (
                "asterion.dci.prompt/safe/v1",
                "asterion-safe",
                "qa",
                "asterion-safe-qa.txt",
                None,
                lambda contract: contract.qa_builder(query, corpus),
            ),
        )
        qa_hashes: set[str] = set()
        for contract_id, source_family, kind, fixture_name, body_sha256, build in cases:
            with self.subTest(contract=contract_id, kind=kind):
                contract = resolve_prompt_contract(contract_id)
                body = build(contract)
                fixture = (fixture_root / fixture_name).read_text(encoding="utf-8")
                self.assertEqual(contract.source_family, source_family)
                self.assertEqual(body, fixture)
                if body_sha256 is not None:
                    self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), body_sha256)
                self.assertEqual(
                    prompt_contract_sha256(contract, kind),
                    canonical_sha256(
                        {
                            "source_family": source_family,
                            "prompt_kind": kind,
                            "body": fixture,
                        }
                    ),
                )
                if kind == "qa":
                    qa_hashes.add(prompt_contract_sha256(contract, kind))
        self.assertEqual(len(qa_hashes), 3)

    def test_prompt_contract_selection_fails_closed_without_body_disclosure(self) -> None:
        query = "SENTINEL-PRIVATE-QUESTION"
        path = Path("/SENTINEL-PRIVATE-PATH")
        with self.assertRaises(PromptContractError) as raised:
            resolve_prompt_contract("unreported-contract")
        self.assertNotIn(query, str(raised.exception))
        self.assertNotIn(str(path), str(raised.exception))
        paper = resolve_prompt_contract("dci.paper-prompt/arxiv:2605.05242v1/v1")
        with self.assertRaises(PromptContractError) as raised:
            paper.ir_builder(query, path, None)
        self.assertNotIn(query, str(raised.exception))
        self.assertNotIn(str(path), str(raised.exception))
        self.assertEqual(
            set(PROMPT_CONTRACTS),
            {
                "asterion.dci.prompt/safe/v1",
                "dci.paper-prompt/arxiv:2605.05242v1/v1",
                "dci.upstream-github-prompt/271f37e71f053bf0c99c05ce6d2fb53b841d922e/v1",
            },
        )

    def test_benchmark_binds_the_profile_selected_prompt_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            base_request = _request(root)
            request = replace(
                base_request,
                profile="asterion-safe/pi",
                corpus=corpus,
                runtime_options=replace(
                    base_request.runtime_options,
                    runtime_context_level="level3",
                ),
            )
            _rows, _output, config, items, _snapshots = _prepare(request)

        contract = resolve_prompt_contract("asterion.dci.prompt/safe/v1")
        expected_sha256 = prompt_contract_sha256(contract, "qa")
        self.assertEqual(config["benchmark_prompt_contract"], contract.contract_id)
        self.assertEqual(config["benchmark_prompt_contract_sha256"], expected_sha256)
        self.assertEqual(items[0]["identity"]["benchmark_prompt_contract"], contract.contract_id)
        self.assertEqual(
            items[0]["identity"]["benchmark_prompt_contract_sha256"],
            expected_sha256,
        )
        self.assertEqual(
            config["runtime"]["context_policy_identity"]["source_family"],
            "asterion-safe",
        )
        self.assertEqual(
            config["runtime"]["context_policy_identity"]["context_contract"],
            "dci.asterion-safe-context/level3/v1",
        )
        self.assertEqual(
            items[0]["identity"]["runtime"]["context_policy_identity"],
            config["runtime"]["context_policy_identity"],
        )

    def test_benchmark_uses_minimax_invocation_identity_for_profile_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            request = replace(
                _request(root),
                profile="asterion-safe/claude-minimax",
                corpus=corpus,
                runtime_options=DciRuntimeOptions(
                    provider="minimax", model="MiniMax-M2.7"
                ),
            )
            _rows, _output, config, _items, _snapshots = _prepare(request)

        self.assertEqual(
            config["benchmark_prompt_contract"], "asterion.dci.prompt/safe/v1"
        )

    def test_benchmark_rejects_unreported_paper_ir_before_agent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-1",
                        "query": "SENTINEL-PRIVATE-QUESTION",
                        "gold_ids": ["doc.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider=None, model=None),
                profile="paper-reference/pi",
                corpus=corpus,
                mode="ir",
                limit=1,
            )
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.paper_scope_for_profile", return_value=None
            ), patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run:
                with self.assertRaisesRegex(DciBenchmarkError, "metric contract") as raised:
                    run_benchmark(request, paths=Mock())

        self.assertNotIn("SENTINEL-PRIVATE-QUESTION", str(raised.exception))
        self.assertNotIn(str(corpus), str(raised.exception))
        run.assert_not_called()

    def test_benchmark_cli_requires_and_propagates_paper_ir_assumption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            corpus = root / "corpus"
            corpus.mkdir()
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-1",
                        "query": "question",
                        "gold_ids": ["doc.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            captured: list[BenchmarkRequest] = []

            def capture(request: BenchmarkRequest, *, paths: object) -> BenchmarkResult:
                del paths
                captured.append(request)
                return BenchmarkResult(output_root=request.output_root, counts={"total": 1})

            benchmark_args = [
                "benchmark",
                "--dataset", str(dataset),
                "--output-root", str(root / "out"),
                "--cwd", str(root),
                "--corpus", str(corpus),
                "--mode", "ir",
                "--experiment-profile", "paper-reference/pi",
            ]
            with patch("asterion.dci.cli.run_benchmark", side_effect=capture), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ):
                stdout = __import__("io").StringIO()
                stderr = __import__("io").StringIO()
                code = dci_main(
                    [
                        *benchmark_args,
                        "--paper-ir-duplicate-handling", "deduplicated",
                    ],
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
            with patch("asterion.dci.cli.run_benchmark") as missing_run, patch(
                "asterion.dci.cli.validate_dci_run_request"
            ):
                missing_stdout = __import__("io").StringIO()
                missing_stderr = __import__("io").StringIO()
                missing_code = dci_main(
                    benchmark_args,
                    repo_root=root,
                    stdout=missing_stdout,
                    stderr=missing_stderr,
                )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(captured[0].profile, "paper-reference/pi")
        self.assertEqual(captured[0].paper_ir_duplicate_handling, "deduplicated")
        self.assertEqual(missing_code, 2)
        self.assertEqual(missing_stderr.getvalue(), "DCI benchmark failed\n")
        missing_run.assert_not_called()


    def test_benchmark_passes_only_the_selected_contract_recovery_to_runs(self) -> None:
        for profile_id, expected_recovery in (
            ("asterion-safe/pi", FINAL_ANSWER_RECOVERY_PROMPT),
            (
                "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi",
                None,
            ),
        ):
            with self.subTest(profile=profile_id), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory).resolve()
                corpus = root / "corpus"
                corpus.mkdir()
                request = replace(_request(root), profile=profile_id, corpus=corpus)
                captured: list[object] = []

                def recorded(paths: object, native_request: object, **kwargs: object) -> DciRunResult:
                    captured.append(native_request)
                    return _recorded_run(paths, native_request, **kwargs)

                with patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=recorded
                ), patch(
                    "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                    return_value=_verdict(request.judge_config),
                ):
                    run_benchmark(request, paths=Mock())

                self.assertEqual(len(captured), 1)
                self.assertEqual(
                    captured[0].final_answer_recovery,
                    expected_recovery,
                )

    def test_experiment_profiles_separate_three_provenance_families(self) -> None:
        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        self.assertEqual(
            experiment_profile_ids(),
            (
                "asterion-safe/pi",
                "asterion-safe/claude-subscription",
                "asterion-safe/claude-minimax",
                "paper-reference/pi",
                "paper-reference/claude-code",
                f"upstream-github/{commit}/pi",
            ),
        )
        paper = resolve_experiment_profile("paper-reference/pi")
        upstream = resolve_experiment_profile(f"upstream-github/{commit}/pi")
        safe = resolve_experiment_profile("asterion-safe/pi")

        self.assertEqual(paper.source_family, "paper-reference")
        self.assertEqual(paper.source_identity, "arxiv:2605.05242v1")
        self.assertIsNone(paper.compatible_config_key)
        self.assertEqual(
            dict(upstream.source_identity),
            {
                "repository": "DCI-Agent/DCI-Agent-Lite",
                "commit": commit,
            },
        )
        self.assertEqual(safe.source_family, "asterion-safe")
        self.assertEqual(
            safe.source_identity, dci_complete_implementation_identity()
        )
        self.assertEqual(
            {
                paper.implementation_sha256,
                upstream.implementation_sha256,
                safe.implementation_sha256,
            },
            {dci_complete_implementation_identity()},
        )
        self.assertNotEqual(paper.identity_sha256, upstream.identity_sha256)
        self.assertNotEqual(upstream.identity_sha256, safe.identity_sha256)
        self.assertNotEqual(paper.prompt_contract, upstream.prompt_contract)
        self.assertNotEqual(upstream.judge_contract, safe.judge_contract)
        self.assertNotEqual(paper.metric_contracts, safe.metric_contracts)
        self.assertNotEqual(paper.runtime_contract, safe.runtime_contract)
        self.assertNotEqual(paper.context_contract, upstream.context_contract)
        self.assertNotEqual(
            upstream.dataset_selection_contract,
            safe.dataset_selection_contract,
        )
        self.assertIsInstance(paper.paper_unreported_parameters, MappingProxyType)
        with self.assertRaises(TypeError):
            paper.paper_unreported_parameters["unknown"] = "paper-unreported"
        with self.assertRaises(TypeError):
            upstream.source_identity["commit"] = "0" * 40
        self.assertNotIn("prompt_body", json.dumps(paper.to_canonical_dict()))

    def test_profile_resources_use_resolved_non_recursive_implementation_binding(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.research import experiment_profiles

        package = resources.files("asterion.capabilities.dci.resources")
        schema = json.loads(
            package.joinpath("experiment-profile.schema.json").read_text()
        )
        payload = json.loads(
            package.joinpath("experiment-profiles.json").read_text()
        )
        raw_text = json.dumps(payload, sort_keys=True)

        self.assertEqual(
            experiment_profile_schema_sha256(),
            canonical_sha256(schema),
        )
        self.assertNotIn("implementation_sha256", raw_text)
        self.assertNotIn(dci_complete_implementation_identity(), raw_text)
        self.assertTrue(
            all(
                isinstance(item["implementation_contract"], str)
                for item in payload["profiles"]
            )
        )
        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        upstream = next(
            item
            for item in payload["profiles"]
            if item["profile_id"] == f"upstream-github/{commit}/pi"
        )
        self.assertEqual(
            upstream["judge"]["request_shape_sha256"],
            judge_request_shape_sha256(
                JudgeConfig(
                    base_url="https://api.openai.com/v1",
                    api="responses",
                    model="gpt-5.4-nano",
                    api_key_env="OPENAI_API_KEY",
                ),
                contract_id=UPSTREAM_JUDGE_CONTRACT,
            ),
        )
        self.assertEqual(
            upstream["judge"]["prompt_contract_sha256"],
            judge_prompt_contract_sha256(
                JudgeConfig(
                    base_url="https://api.openai.com/v1",
                    api="responses",
                    model="gpt-5.4-nano",
                    api_key_env="OPENAI_API_KEY",
                ),
                contract_id=UPSTREAM_JUDGE_CONTRACT,
            ),
        )
        expected_profiles_sha256 = canonical_sha256(
            {
                "schema": "dci.experiment-profiles/v1",
                "profiles": [
                    {
                        "profile_id": profile_id,
                        "identity_sha256": experiment_profiles._profiles()[
                            profile_id
                        ].identity_sha256,
                    }
                    for profile_id in experiment_profile_ids()
                ],
            }
        )
        self.assertEqual(experiment_profiles_sha256(), expected_profiles_sha256)

    def test_profile_identity_tracks_exact_implementation_resource_mutation(
        self,
    ) -> None:
        resources_by_name = {
            name: resources.files("asterion.capabilities.dci").joinpath(name).read_bytes()
            for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
        }
        baseline_implementation = dci_complete_implementation_identity(
            resource_reader=resources_by_name.__getitem__
        )
        profile_resource = "resources/experiment-profiles.json"
        resources_by_name[profile_resource] += b"\n"
        changed_implementation = dci_complete_implementation_identity(
            resource_reader=resources_by_name.__getitem__
        )
        self.assertNotEqual(baseline_implementation, changed_implementation)

        from asterion.capabilities.dci.implementation.research import experiment_profiles

        with patch.object(
            experiment_profiles,
            "dci_complete_implementation_identity",
            return_value=baseline_implementation,
        ):
            experiment_profiles._profiles.cache_clear()
            baseline_profile = resolve_experiment_profile("asterion-safe/pi")
        with patch.object(
            experiment_profiles,
            "dci_complete_implementation_identity",
            return_value=changed_implementation,
        ):
            experiment_profiles._profiles.cache_clear()
            changed_profile = resolve_experiment_profile("asterion-safe/pi")

        self.assertEqual(
            baseline_profile.implementation_sha256, baseline_implementation
        )
        self.assertEqual(
            changed_profile.implementation_sha256, changed_implementation
        )
        self.assertNotEqual(
            baseline_profile.identity_sha256, changed_profile.identity_sha256
        )

    def test_profile_contract_rejects_cross_family_and_unknown_semantics(
        self,
    ) -> None:
        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        mutations = (
            (
                "paper-mixed-github-prompt",
                "paper-reference/pi",
                lambda item: item.__setitem__(
                    "prompt_contract",
                    f"dci.upstream-github-prompt/{commit}/v1",
                ),
            ),
            (
                "paper-mixed-asterion-judge",
                "paper-reference/pi",
                lambda item: item.__setitem__(
                    "judge_contract",
                    "asterion.dci.answer-judge/strict-json/v1",
                ),
            ),
            (
                "paper-mixed-asterion-metric",
                "paper-reference/pi",
                lambda item: item.__setitem__(
                    "metric_contracts",
                    [
                        "asterion.dci.answer-correctness/strict-json/v1",
                        "ndcg@10-binary-deduplicated/v1",
                    ],
                ),
            ),
            (
                "upstream-noncanonical-commit",
                f"upstream-github/{commit}/pi",
                lambda item: item["source_identity"].__setitem__(
                    "commit", commit.upper()
                ),
            ),
            (
                "safe-published-target",
                "asterion-safe/pi",
                lambda item: item["comparison"].__setitem__(
                    "published_target", "DCI-Agent-Lite"
                ),
            ),
            (
                "unknown-paper-unreported-parameter",
                "paper-reference/pi",
                lambda item: item["paper_unreported_parameters"].__setitem__(
                    "unknown", "paper-unreported"
                ),
            ),
        )
        for label, profile_id, mutate in mutations:
            with self.subTest(label=label):
                self._assert_invalid_profile_mutation(profile_id, mutate)

    def test_current_default_alias_is_cli_only_and_never_enters_evidence(
        self,
    ) -> None:
        aliases = (
            ("current-default/pi", "asterion-safe/pi", ()),
            (
                "current-default/claude-subscription",
                "asterion-safe/claude-subscription",
                (),
            ),
            (
                "current-default/claude-minimax",
                "asterion-safe/claude-minimax",
                ("--provider", "minimax", "--model", "minimax-test"),
            ),
        )
        for alias, canonical, invocation in aliases:
            with self.subTest(alias=alias):
                with self.assertRaisesRegex(
                    ValueError, "^DCI experiment profile is invalid$"
                ):
                    resolve_experiment_profile(alias)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    stdout = __import__("io").StringIO()
                    stderr = __import__("io").StringIO()
                    code = dci_main(
                        [
                            "paper",
                            "reproduce",
                            "--profile",
                            alias,
                            "--output-root",
                            str(Path(temporary_directory) / "out"),
                            *invocation,
                        ],
                        stdout=stdout,
                        stderr=stderr,
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn(f"Profile: {canonical}", stdout.getvalue())
                self.assertNotIn("current-default", stdout.getvalue())

        from asterion.capabilities.dci.implementation.reproduction.verification import paper_product_contract

        canonical_evidence = json.dumps(
            paper_product_contract(), sort_keys=True
        )
        self.assertNotIn("current-default", canonical_evidence)
        self.assertIn("asterion-safe/pi", canonical_evidence)

    def test_authorized_reproduction_coordinator_dispatches_exact_child_roots(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scopes = (
            "bright.biology.main.full",
            "bright.earth-science.main.full",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            profile = resolve_experiment_profile("paper-reference/pi")
            authority = _bounded_authorize_full_execution(
                profile=profile,
                scope_ids=scopes,
                output_root=root / "authorized",
                max_agent_operations=10,
                max_judge_operations=1,
                max_cost_usd=5.0,
                max_agent_cost_per_operation_usd=0.1,
                max_judge_cost_per_operation_usd=0.1,
            )
            paths = resolve_dci_paths(root)
            items = []
            for scope in scopes:
                request = BenchmarkRequest(
                    dataset=root / f"{scope}.jsonl",
                    output_root=authorized_scope_output_root(authority, scope),
                    cwd=root,
                    judge_config=JudgeConfig(),
                    runtime_options=DciRuntimeOptions(
                        provider="openai", model="gpt-5.4-nano"
                    ),
                    mode="ir",
                    profile=profile.profile_id,
                    full_execution_authorization=authority,
                    experiment_scope_id=scope,
                    paper_ir_duplicate_handling="deduplicated",
                    dataset_input_binding=_authority_dataset_binding(
                        authority,
                        scope,
                    ),
                )
                items.append(
                    benchmark_module.AuthorizedBenchmarkExecution(
                        scope_id=scope,
                        request=request,
                        paths=paths,
                    )
                )
            calls: list[tuple[str, Path]] = []

            def run_spy(
                request: BenchmarkRequest, *, paths: object
            ) -> BenchmarkResult:
                del paths
                calls.append((request.experiment_scope_id or "", request.output_root))
                scope = request.experiment_scope_id or ""
                self.assertIsNotNone(request.dataset_input_binding)
                self.assertIs(
                    request.dataset_input_binding,
                    _authority_dataset_binding(authority, scope),
                )
                consume_full_execution_authorization(
                    request.full_execution_authorization,
                    scope,
                    cast(
                        DatasetInputBinding,
                        request.dataset_input_binding,
                    ),
                )
                return BenchmarkResult(request.output_root, {"total": 1})

            with (
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.run_benchmark",
                    side_effect=run_spy,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.compile_run_manifest",
                    return_value=Mock(identity_sha256="a" * 64),
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.write_run_manifest",
                    side_effect=lambda _root, _identity, scope, _manifest: (
                        hashlib.sha256(scope.encode()).hexdigest() + ".json"
                    ),
                ),
            ):
                result = benchmark_module.execute_authorized_reproduction(
                    authority=authority,
                    profile=profile,
                    scope_ids=scopes,
                    output_root=root / "authorized",
                    execution_items=tuple(items),
                )

        self.assertEqual(tuple(scope for scope, _root in calls), scopes)
        self.assertNotEqual(calls[0][1], calls[1][1])
        self.assertEqual(result["operation_counts"]["agent"], 0)
        self.assertEqual(result["operation_counts"]["judge"], 0)
        self.assertEqual(
            [item["scope_id"] for item in result["outputs"]],
            list(scopes),
        )
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn("fixture-q-1", rendered)
        self.assertNotIn("_issuance_token", rendered)

    def test_authorized_reproduction_compiles_each_manifest_before_next_scope(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scopes = (
            "bright.biology.main.full",
            "bright.earth-science.main.full",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            profile = resolve_experiment_profile("paper-reference/pi")
            authority = _bounded_authorize_full_execution(
                profile=profile,
                scope_ids=scopes,
                output_root=root / "authorized",
                max_agent_operations=10,
                max_judge_operations=1,
                max_cost_usd=5.0,
                max_agent_cost_per_operation_usd=0.1,
                max_judge_cost_per_operation_usd=0.1,
            )
            paths = resolve_dci_paths(root)
            items = tuple(
                benchmark_module.AuthorizedBenchmarkExecution(
                    scope_id=scope,
                    request=BenchmarkRequest(
                        dataset=root / f"{scope}.jsonl",
                        output_root=authorized_scope_output_root(authority, scope),
                        cwd=root,
                        judge_config=JudgeConfig(),
                        runtime_options=DciRuntimeOptions(
                            provider="openai", model="gpt-5.4-nano"
                        ),
                        mode="ir",
                        profile=profile.profile_id,
                        full_execution_authorization=authority,
                        experiment_scope_id=scope,
                        paper_ir_duplicate_handling="deduplicated",
                        dataset_input_binding=_authority_dataset_binding(
                            authority,
                            scope,
                        ),
                    ),
                    paths=paths,
                )
                for scope in scopes
            )
            events: list[tuple[str, str]] = []
            manifests = {
                scope: Mock(identity_sha256=hashlib.sha256(scope.encode()).hexdigest())
                for scope in scopes
            }
            scope_by_root = {
                item.request.output_root: item.scope_id for item in items
            }

            def run_spy(
                request: BenchmarkRequest, *, paths: object
            ) -> BenchmarkResult:
                del paths
                scope = request.experiment_scope_id or ""
                events.append(("run", scope))
                self.assertIsNotNone(request.dataset_input_binding)
                self.assertIs(
                    request.dataset_input_binding,
                    _authority_dataset_binding(authority, scope),
                )
                consume_full_execution_authorization(
                    request.full_execution_authorization,
                    scope,
                    cast(
                        DatasetInputBinding,
                        request.dataset_input_binding,
                    ),
                )
                return BenchmarkResult(request.output_root, {"total": 1})

            def compile_spy(
                output_root: Path, supplied_profile: ExperimentProfile
            ) -> object:
                self.assertIs(supplied_profile, profile)
                scope = scope_by_root[output_root]
                events.append(("compile", scope))
                return manifests[scope]

            def write_spy(
                manifest_root: Path,
                expected_identity: tuple[int, int],
                scope_id: str,
                manifest: object,
            ) -> str:
                metadata = manifest_root.stat()
                self.assertEqual(
                    expected_identity, (metadata.st_dev, metadata.st_ino)
                )
                self.assertIs(manifest, manifests[scope_id])
                events.append(("write", scope_id))
                return hashlib.sha256(scope_id.encode()).hexdigest() + ".json"

            with (
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.run_benchmark",
                    side_effect=run_spy,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.compile_run_manifest",
                    side_effect=compile_spy,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.write_run_manifest",
                    side_effect=write_spy,
                ),
            ):
                result = benchmark_module.execute_authorized_reproduction(
                    authority=authority,
                    profile=profile,
                    scope_ids=scopes,
                    output_root=root / "authorized",
                    execution_items=items,
                )

        self.assertEqual(
            events,
            [
                ("run", scopes[0]),
                ("compile", scopes[0]),
                ("write", scopes[0]),
                ("run", scopes[1]),
                ("compile", scopes[1]),
                ("write", scopes[1]),
            ],
        )
        for index, scope in enumerate(scopes):
            output = result["outputs"][index]
            self.assertEqual(
                set(output),
                {
                    "scope_id",
                    "output_root_device",
                    "output_root_inode",
                    "manifest_artifact",
                    "manifest_identity_sha256",
                },
            )
            self.assertEqual(output["scope_id"], scope)
            self.assertRegex(
                output["manifest_artifact"], r"^[0-9a-f]{64}\.json$"
            )
            self.assertRegex(
                output["manifest_identity_sha256"], r"^[0-9a-f]{64}$"
            )

    def test_authorized_reproduction_persists_real_compiled_manifest_from_local_fixture(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scope_id = "qa.nq.main.random50"
        source_ids = published_scope_selected_ids(scope_id)
        bounded_ids = source_ids[:1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "".join(
                    json.dumps(
                        {
                            "query_id": query_id,
                            "query": f"fixture question {index}",
                            "answer": "fixture answer",
                        },
                        sort_keys=True,
                    )
                    + "\n"
                    for index, query_id in enumerate(source_ids)
                ),
                encoding="utf-8",
            )
            corpus = root / "corpus"
            corpus.mkdir(mode=0o700)
            (corpus / "doc.txt").write_text(
                "local fixture evidence\n",
                encoding="utf-8",
            )
            profile = resolve_experiment_profile("paper-reference/pi")
            dataset_binding = _dataset_binding_for_path(dataset, scope_id)
            authority = authorize_full_execution(
                profile=profile,
                scope_ids=(scope_id,),
                dataset_input_bindings=(dataset_binding,),
                bounded_selected_ids_sha256=(canonical_sha256(bounded_ids),),
                selected_query_counts=(1,),
                planned_agent_operations=1,
                planned_judge_operations=1,
                output_root=root / "authorized",
                max_agent_operations=1,
                max_judge_operations=1,
                max_cost_usd=1,
                max_agent_cost_per_operation_usd=1,
                max_judge_cost_per_operation_usd=1,
                invocation_authorized=True,
            )
            judge_config = JudgeConfig(
                base_url=str(profile.judge["base_url"]),
                api=str(profile.judge["api"]),
                model=str(profile.judge["model"]),
                api_key_env=str(profile.judge["key_source"]),
            )
            request = BenchmarkRequest(
                dataset=dataset,
                dataset_input_binding=dataset_binding,
                output_root=authorized_scope_output_root(authority, scope_id),
                cwd=root,
                judge_config=judge_config,
                runtime_options=DciRuntimeOptions(
                    provider=profile.provider,
                    model=profile.model,
                ),
                limit=1,
                mode="qa",
                profile=profile.profile_id,
                corpus=corpus,
                analysis=False,
                figures=False,
                full_execution_authorization=authority,
                experiment_scope_id=scope_id,
            )
            item = benchmark_module.AuthorizedBenchmarkExecution(
                scope_id=scope_id,
                request=request,
                paths=resolve_dci_paths(root),
            )
            manifest_root, _device, _inode = _authorized_manifest_output_identity(
                authority
            )
            fixture_provider_calls: list[dict[str, object]] = []

            def fixture_provider(**kwargs: object) -> _CostedFixtureClient:
                fixture_provider_calls.append(dict(kwargs))
                return _CostedFixtureClient()

            with patch(
                "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
                side_effect=fixture_provider,
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ) as judge:
                result = benchmark_module.execute_authorized_reproduction(
                    authority=authority,
                    profile=profile,
                    scope_ids=(scope_id,),
                    output_root=root / "authorized",
                    execution_items=(item,),
                )

            outputs = cast(list[dict[str, object]], result["outputs"])
            output = outputs[0]
            manifest_artifact = cast(str, output["manifest_artifact"])
            manifest_path = manifest_root / manifest_artifact
            persisted = load_run_manifest(manifest_path)
            validate_run_manifest(persisted)
            manifest_mode = manifest_path.stat().st_mode & 0o777
            operation_counts = cast(dict[str, int], result["operation_counts"])

        self.assertEqual(len(fixture_provider_calls), 1)
        judge.assert_called_once()
        self.assertEqual(operation_counts["agent"], 1)
        self.assertEqual(operation_counts["judge"], 1)
        self.assertEqual(persisted.selection_id, "limit-1")
        self.assertEqual(persisted.selection_sha256, canonical_sha256(bounded_ids))
        self.assertEqual(persisted.aggregates.query_count, 1)
        self.assertEqual(
            persisted.identity_sha256,
            output["manifest_identity_sha256"],
        )
        self.assertEqual(manifest_mode, 0o600)

    def test_authorized_reproduction_manifest_root_replacement_fails_closed(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            profile = resolve_experiment_profile("paper-reference/pi")
            authority = _bounded_authorize_full_execution(
                profile=profile,
                scope_ids=(scope_id,),
                output_root=root / "authorized",
                max_agent_operations=1,
                max_judge_operations=1,
                max_cost_usd=1,
                max_agent_cost_per_operation_usd=1,
                max_judge_cost_per_operation_usd=1,
            )
            manifest_root, manifest_device, manifest_inode = (
                _authorized_manifest_output_identity(authority)
            )
            item = benchmark_module.AuthorizedBenchmarkExecution(
                scope_id=scope_id,
                request=BenchmarkRequest(
                    dataset=root / "dataset.jsonl",
                    output_root=authorized_scope_output_root(authority, scope_id),
                    cwd=root,
                    judge_config=JudgeConfig(),
                    runtime_options=DciRuntimeOptions(
                        provider=profile.provider,
                        model=profile.model,
                    ),
                    mode="ir",
                    profile=profile.profile_id,
                    full_execution_authorization=authority,
                    experiment_scope_id=scope_id,
                    paper_ir_duplicate_handling="deduplicated",
                ),
                paths=resolve_dci_paths(root),
            )

            def replace_manifest_root(
                request: BenchmarkRequest, *, paths: object
            ) -> BenchmarkResult:
                del paths
                consume_full_execution_authorization(
                    authority,
                    scope_id,
                    _authority_dataset_binding(authority, scope_id),
                )
                manifest_root.rename(root / "replaced-manifest-root")
                manifest_root.mkdir(mode=0o700)
                return BenchmarkResult(request.output_root, {"total": 1})

            def reject_replacement(
                supplied_root: Path,
                expected_identity: tuple[int, int],
                _scope_id: str,
                _manifest: object,
            ) -> str:
                self.assertEqual(supplied_root, manifest_root)
                self.assertEqual(
                    expected_identity,
                    (manifest_device, manifest_inode),
                )
                metadata = supplied_root.stat()
                self.assertNotEqual(
                    (metadata.st_dev, metadata.st_ino),
                    expected_identity,
                )
                raise ValueError("DCI reproduction manifest root identity changed")

            with (
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.run_benchmark",
                    side_effect=replace_manifest_root,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.compile_run_manifest",
                    return_value=Mock(identity_sha256="a" * 64),
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.write_run_manifest",
                    side_effect=reject_replacement,
                ) as writer,
                self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark manifest evidence failed$",
                ),
            ):
                benchmark_module.execute_authorized_reproduction(
                    authority=authority,
                    profile=profile,
                    scope_ids=(scope_id,),
                    output_root=root / "authorized",
                    execution_items=(item,),
                )

            writer.assert_called_once()
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "inactive|cancelled",
            ):
                reserve_full_execution_operation(authority, scope_id, "agent")

    def test_manifest_failure_cancels_authority_and_stops(self) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scopes = (
            "bright.biology.main.full",
            "bright.earth-science.main.full",
        )
        sentinels = (
            "fixture-private-query-id",
            "/private/sentinel/output",
            "SECRET prompt body",
        )
        for failure_phase in ("compiler", "writer"):
            with (
                self.subTest(failure_phase=failure_phase),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory).resolve()
                profile = resolve_experiment_profile("paper-reference/pi")
                authority = _bounded_authorize_full_execution(
                    profile=profile,
                    scope_ids=scopes,
                    output_root=root / "authorized",
                    max_agent_operations=10,
                    max_judge_operations=1,
                    max_cost_usd=5.0,
                    max_agent_cost_per_operation_usd=0.1,
                    max_judge_cost_per_operation_usd=0.1,
                )
                paths = resolve_dci_paths(root)
                items = tuple(
                    benchmark_module.AuthorizedBenchmarkExecution(
                        scope_id=scope,
                        request=BenchmarkRequest(
                            dataset=root / f"{scope}.jsonl",
                            output_root=authorized_scope_output_root(authority, scope),
                            cwd=root,
                            judge_config=JudgeConfig(),
                            runtime_options=DciRuntimeOptions(
                                provider="openai", model="gpt-5.4-nano"
                            ),
                            mode="ir",
                            profile=profile.profile_id,
                            full_execution_authorization=authority,
                            experiment_scope_id=scope,
                            paper_ir_duplicate_handling="deduplicated",
                            dataset_input_binding=_authority_dataset_binding(
                                authority,
                                scope,
                            ),
                        ),
                        paths=paths,
                    )
                    for scope in scopes
                )
                started: list[str] = []

                def run_spy(
                    request: BenchmarkRequest, *, paths: object
                ) -> BenchmarkResult:
                    del paths
                    scope = request.experiment_scope_id or ""
                    started.append(scope)
                    self.assertIsNotNone(request.dataset_input_binding)
                    self.assertIs(
                        request.dataset_input_binding,
                        _authority_dataset_binding(authority, scope),
                    )
                    consume_full_execution_authorization(
                        request.full_execution_authorization,
                        scope,
                        cast(
                            DatasetInputBinding,
                            request.dataset_input_binding,
                        ),
                    )
                    return BenchmarkResult(request.output_root, {"total": 1})

                unsafe_error = (
                    RuntimeError(" ".join(sentinels))
                    if failure_phase == "compiler"
                    else ValueError(" ".join(sentinels))
                )
                compile_side_effect: object = (
                    unsafe_error
                    if failure_phase == "compiler"
                    else Mock(identity_sha256="a" * 64)
                )
                write_side_effect: object = (
                    unsafe_error
                    if failure_phase == "writer"
                    else "a" * 64 + ".json"
                )
                with (
                    patch(
                        "asterion.capabilities.dci.implementation.evaluation.benchmark.run_benchmark",
                        side_effect=run_spy,
                    ),
                    patch(
                        "asterion.capabilities.dci.implementation.evaluation.benchmark.compile_run_manifest",
                        side_effect=compile_side_effect,
                    ),
                    patch(
                        "asterion.capabilities.dci.implementation.evaluation.benchmark.write_run_manifest",
                        side_effect=write_side_effect,
                    ),
                    self.assertRaises(DciBenchmarkError) as raised,
                ):
                    benchmark_module.execute_authorized_reproduction(
                        authority=authority,
                        profile=profile,
                        scope_ids=scopes,
                        output_root=root / "authorized",
                        execution_items=items,
                    )

                self.assertEqual(started, [scopes[0]])
                public_error = str(raised.exception)
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, public_error)
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "inactive|cancelled",
                ):
                    reserve_full_execution_operation(
                        authority, scopes[1], "agent"
                    )

    def test_authorized_reproduction_coordinator_rejects_mismatch_before_run(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scopes = ("bright.biology.main.full",)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            profile = resolve_experiment_profile("paper-reference/pi")
            authority = _bounded_authorize_full_execution(
                profile=profile,
                scope_ids=scopes,
                output_root=root / "authorized",
                max_agent_operations=10,
                max_judge_operations=1,
                max_cost_usd=5.0,
                max_agent_cost_per_operation_usd=0.1,
                max_judge_cost_per_operation_usd=0.1,
            )
            item = benchmark_module.AuthorizedBenchmarkExecution(
                scope_id=scopes[0],
                request=BenchmarkRequest(
                    dataset=root / "dataset.jsonl",
                    output_root=root / "wrong-root",
                    cwd=root,
                    judge_config=JudgeConfig(),
                    runtime_options=DciRuntimeOptions(
                        provider="openai", model="gpt-5.4-nano"
                    ),
                    mode="ir",
                    profile=profile.profile_id,
                    full_execution_authorization=authority,
                    experiment_scope_id=scopes[0],
                    paper_ir_duplicate_handling="deduplicated",
                ),
                paths=resolve_dci_paths(root),
            )
            with patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_benchmark") as run:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "authorization root changed",
                ):
                    benchmark_module.execute_authorized_reproduction(
                        authority=authority,
                        profile=profile,
                        scope_ids=scopes,
                        output_root=root / "authorized",
                        execution_items=(item,),
                    )
        run.assert_not_called()

    def test_authorized_reproduction_coordinator_cancels_on_initial_mismatch(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.evaluation import (
            benchmark as benchmark_module,
        )

        scopes = ("bright.biology.main.full",)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            profile = resolve_experiment_profile("paper-reference/pi")
            authority = _bounded_authorize_full_execution(
                profile=profile,
                scope_ids=scopes,
                output_root=root / "authorized",
                max_agent_operations=10,
                max_judge_operations=1,
                max_cost_usd=5.0,
                max_agent_cost_per_operation_usd=0.1,
                max_judge_cost_per_operation_usd=0.1,
            )
            item = benchmark_module.AuthorizedBenchmarkExecution(
                scope_id=scopes[0],
                request=BenchmarkRequest(
                    dataset=root / "dataset.jsonl",
                    output_root=root / "wrong-root",
                    cwd=root,
                    judge_config=JudgeConfig(),
                    runtime_options=DciRuntimeOptions(
                        provider="openai", model="gpt-5.4-nano"
                    ),
                    mode="ir",
                    profile=profile.profile_id,
                    full_execution_authorization=authority,
                    experiment_scope_id=scopes[0],
                    paper_ir_duplicate_handling="deduplicated",
                ),
                paths=resolve_dci_paths(root),
            )
            with self.assertRaisesRegex(
                DciBenchmarkError,
                "authorization root changed",
            ):
                benchmark_module.execute_authorized_reproduction(
                    authority=authority,
                    profile=profile,
                    scope_ids=scopes,
                    output_root=root / "authorized",
                    execution_items=(item,),
                )
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "inactive|cancelled",
            ):
                reserve_full_execution_operation(authority, scopes[0], "agent")

    def test_context_source_identity_requires_exact_family_and_contract(self) -> None:
        from asterion.capabilities.dci.implementation.research.context_profiles import (
            context_contract_for_source,
            context_policy_identity,
            context_source_identity,
            resolve_context_profile,
        )
        from asterion.capabilities.dci.implementation.research.context_extension import resolve_context_extension

        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        profile = resolve_context_profile("level3")
        contracts = {
            "paper-reference": "dci.paper-context/level3/v1",
            "upstream-github": (
                f"dci.upstream-github-context/{commit}/level3/v1"
            ),
            "asterion-safe": "dci.asterion-safe-context/level3/v1",
        }
        with resolve_context_extension() as extension:
            identities = {
                family: context_source_identity(contract, profile, extension)
                for family, contract in contracts.items()
            }
            generic_identity = context_policy_identity(profile, extension)

        paper_identity = identities["paper-reference"]
        upstream_identity = identities["upstream-github"]
        safe_identity = identities["asterion-safe"]
        for family, contract in contracts.items():
            with self.subTest(source_family=family):
                identity = identities[family]
                self.assertIsInstance(identity, MappingProxyType)
                self.assertEqual(identity["source_family"], family)
                self.assertEqual(identity["context_contract"], contract)
                self.assertEqual(identity["context_profile"], "level3")
                self.assertEqual(identity["extension_version"], extension.version)
                self.assertEqual(identity["extension_sha256"], extension.sha256)
                self.assertIsInstance(identity["profile"], MappingProxyType)
                self.assertEqual(identity["profile"]["profile"], "level3")
                self.assertNotIn("path", identity)
                self.assertNotIn("tool_body", identity)

        self.assertEqual(
            paper_identity["source_identity"],
            "arxiv:2605.05242v1",
        )
        self.assertEqual(
            paper_identity["parity_status"],
            "paper-reported-golden-verified",
        )
        self.assertNotIn(commit, repr(paper_identity))
        self.assertEqual(
            dict(upstream_identity["source_identity"]),
            {
                "repository": "DCI-Agent/DCI-Agent-Lite",
                "commit": commit,
            },
        )
        self.assertEqual(
            upstream_identity["parity_status"],
            "upstream-readme-qualitative-only",
        )
        self.assertNotIn("arxiv:2605.05242v1", repr(upstream_identity))
        self.assertEqual(
            safe_identity["source_identity"],
            "asterion.dci.complete-implementation/v1",
        )
        self.assertEqual(
            safe_identity["parity_status"],
            "asterion-golden-verified",
        )
        with self.assertRaises(TypeError):
            paper_identity["source_family"] = "asterion-safe"
        with self.assertRaises(TypeError):
            upstream_identity["source_identity"]["commit"] = "0" * 40

        self.assertEqual(
            generic_identity["schema"],
            "dci.context-policy-identity/v1",
        )
        self.assertEqual(generic_identity["profile"]["profile"], "level3")

        with resolve_context_extension() as extension:
            for level in ("level0", "level1", "level2", "level3", "level4"):
                level_profile = resolve_context_profile(level)
                for source_family in contracts:
                    with self.subTest(
                        source_family=source_family,
                        context_profile=level,
                    ):
                        contract = context_contract_for_source(
                            source_family,
                            level,
                        )
                        identity = context_source_identity(
                            contract,
                            level_profile,
                            extension,
                        )
                        self.assertEqual(
                            identity["source_family"],
                            source_family,
                        )
                        self.assertEqual(identity["context_profile"], level)

        invalid_contracts = (
            "dci.paper-context/level4/v1",
            "dci.paper-context/LEVEL3/v1",
            "dci.paper-context/level3",
            f"dci.upstream-github-context/{'f' * 40}/level3/v1",
            "dci.upstream-context/level3/v1",
            "dci.asterion-safe-context/level03/v1",
        )
        with resolve_context_extension() as extension:
            for contract in invalid_contracts:
                with self.subTest(invalid_contract=contract):
                    with self.assertRaisesRegex(
                        ValueError,
                        "DCI context source identity is invalid",
                    ):
                        context_source_identity(contract, profile, extension)
            with self.assertRaisesRegex(
                ValueError,
                "DCI context source identity is invalid",
            ):
                context_source_identity(
                    contracts["paper-reference"],
                    replace(profile, retained_turns=11),
                    extension,
                )
            for source_family, level in (
                ("paper", "level3"),
                ("paper-reference", "LEVEL3"),
                (None, "level3"),
            ):
                with self.subTest(
                    invalid_source_family=source_family,
                    invalid_level=level,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "DCI context source identity is invalid",
                    ):
                        context_contract_for_source(source_family, level)

    def test_experiment_context_contracts_match_profile_and_source_family(
        self,
    ) -> None:
        from asterion.capabilities.dci.implementation.research.context_extension import resolve_context_extension
        from asterion.capabilities.dci.implementation.research.context_profiles import (
            context_source_identity,
            resolve_context_profile,
        )

        with resolve_context_extension() as extension:
            for profile_id in experiment_profile_ids():
                experiment = (
                    resolve_experiment_profile(
                        profile_id,
                        invocation_provider="minimax",
                        invocation_model="MiniMax-M2.5",
                    )
                    if profile_id == "asterion-safe/claude-minimax"
                    else resolve_experiment_profile(profile_id)
                )
                context_profile = resolve_context_profile(
                    experiment.context_profile
                )
                with self.subTest(profile_id=profile_id):
                    identity = context_source_identity(
                        experiment.context_contract,
                        context_profile,
                        extension,
                    )
                    self.assertEqual(
                        identity["source_family"],
                        experiment.source_family,
                    )
                    self.assertEqual(
                        identity["context_profile"],
                        experiment.context_profile,
                    )

    def test_paper_product_contract_marks_resolution_parameters_as_asterion_defined(self) -> None:
        from asterion.capabilities.dci.implementation.reproduction.verification import paper_product_contract

        configuration = paper_product_contract()["analysis_configuration"]

        self.assertEqual(configuration["parameter_source"], "asterion-defined")
        self.assertEqual(
            configuration["read_minimum_evidence_overlap"],
            "required-unit-interval",
        )

    def _assert_invalid_profile_mutation(self, profile_id, mutate) -> None:
        from asterion.capabilities.dci.implementation.research import experiment_profiles

        package = resources.files("asterion.capabilities.dci.resources")
        payload = json.loads(
            package.joinpath("experiment-profiles.json").read_text()
        )
        schema = json.loads(
            package.joinpath("experiment-profile.schema.json").read_text()
        )
        item = next(
            item for item in payload["profiles"] if item["profile_id"] == profile_id
        )
        mutate(item)
        with patch.object(
            experiment_profiles,
            "_read_profile_resources",
            return_value=(payload, schema),
        ):
            experiment_profiles._profiles.cache_clear()
            with self.assertRaisesRegex(
                RuntimeError,
                "^DCI experiment profile contract is invalid$",
            ):
                experiment_profiles.experiment_profile_ids()

    def test_batch_evidence_exports_transitive_implementation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=_recorded_run
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=Mock())

            config = json.loads((request.output_root / "config.json").read_text())
            item = json.loads(
                (request.output_root / "q-1/item.json").read_text()
            )
            result = json.loads(
                (request.output_root / "q-1/result.json").read_text()
            )
            summary = json.loads(
                (request.output_root / "summary.json").read_text()
            )
            analysis = json.loads(
                (request.output_root / "analysis.json").read_text()
            )

        expected = dci_complete_implementation_identity()
        self.assertEqual(config["implementation_sha256"], expected)
        self.assertEqual(item["implementation_sha256"], expected)
        self.assertEqual(item["identity"]["implementation_sha256"], expected)
        self.assertEqual(result["implementation_sha256"], expected)
        self.assertEqual(summary["provenance"]["implementation_sha256"], expected)
        self.assertEqual(analysis["provenance"]["implementation_sha256"], expected)

    def test_changed_or_missing_implementation_identity_rejects_before_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            resources = {
                name: name.encode()
                for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
            }
            first_identity = dci_complete_implementation_identity(
                resource_reader=resources.__getitem__
            )
            resources["implementation/evaluation/artifacts.py"] += b"\x00"
            second_identity = dci_complete_implementation_identity(
                resource_reader=resources.__getitem__
            )
            self.assertNotEqual(first_identity, second_identity)
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=_recorded_run
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=Mock())

            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.dci_complete_implementation_identity",
                return_value=second_identity,
            ), patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "configuration is incompatible"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

            config_path = request.output_root / "config.json"
            config = json.loads(config_path.read_text())
            valid_config = dict(config)
            config.pop("implementation_sha256")
            config_path.write_text(json.dumps(config))
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "configuration evidence is invalid"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

            config_path.write_text(json.dumps(valid_config))
            item_path = request.output_root / "q-1/item.json"
            item = json.loads(item_path.read_text())
            valid_item = dict(item)
            item.pop("implementation_sha256")
            item_path.write_text(json.dumps(item))
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "item evidence is invalid"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

            item_path.write_text(json.dumps(valid_item))
            result_path = request.output_root / "q-1/result.json"
            result = json.loads(result_path.read_text())
            result.pop("implementation_sha256")
            result_path.write_text(json.dumps(result))
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "result evidence is invalid"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

    def test_persisted_batch_judge_identity_is_prompt_and_request_shape_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.capabilities.dci.implementation.runtime.run.PiRpcClient", _FixtureClient), patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))

            config = json.loads((request.output_root / "config.json").read_text())

        self.assertRegex(
            config["judge"]["request_shape_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            config["judge"]["prompt_contract_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_limit_slices_sorted_rows_and_rejects_zero(self) -> None:
        """Compatibility evidence name retained for the closed AF-220 climb case."""

        self.test_limit_slices_source_order_rows_and_rejects_zero()

    def test_batch_uses_its_runtime_options_for_every_native_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "\n".join(
                    (
                        json.dumps({"query_id": "q-2", "query": "two", "answer": "two"}),
                        json.dumps({"query_id": "q-1", "query": "one", "answer": "one"}),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider="openai", model="gpt-test"),
            )
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                    run_benchmark(request, paths=Mock())

        self.assertEqual([call.args[1].run_id for call in run.call_args_list], ["q-2", "q-1"])
        self.assertEqual(
            [(call.args[1].provider, call.args[1].model) for call in run.call_args_list],
            [("openai", "gpt-test"), ("openai", "gpt-test")],
        )

    def test_limit_slices_source_order_rows_and_rejects_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "\n".join(
                    (
                        json.dumps({"query_id": "q-2", "query": "two", "answer": "two"}),
                        json.dumps({"query_id": "q-1", "query": "one", "answer": "one"}),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider="openai", model="gpt-test"),
                limit=1,
            )
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                    result = run_benchmark(request, paths=Mock())

            self.assertEqual(result.counts["total"], 1)
            self.assertEqual(run.call_args.args[1].run_id, "q-2")

            invalid = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "invalid",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider="openai", model="gpt-test"),
                limit=0,
            )
            with self.assertRaisesRegex(DciBenchmarkError, "limit is invalid"):
                run_benchmark(invalid, paths=Mock())
    def test_batch_reuses_the_native_asterion_run_and_writes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                    result = run_benchmark(request, paths=Mock())

            self.assertEqual(run.call_count, 1)
            self.assertTrue((result.output_root / "summary.json").is_file())
            self.assertEqual(result.counts["correct"], 1)

    def test_existing_successful_result_skips_run_and_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.capabilities.dci.implementation.runtime.run.PiRpcClient", _FixtureClient), patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            with patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run:
                with patch("asterion.capabilities.dci.implementation.evaluation.benchmark.evaluate_run_directory_async") as evaluate:
                    result = run_benchmark(request, paths=resolve_dci_paths(root))
            evidence = json.loads(
                (result.output_root / "q-1" / "reproduction-evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            summary = json.loads(
                (result.output_root / "summary.json").read_text(encoding="utf-8")
            )

        run.assert_not_called()
        evaluate.assert_not_called()
        self.assertEqual(evidence["agent_operations"], 0)
        self.assertEqual(evidence["judge_operations"], 0)
        self.assertEqual(evidence["tokens"]["input"], 0)
        self.assertEqual(evidence["tokens"]["cached_input"], 0)
        self.assertEqual(evidence["tokens"]["output"], 0)
        self.assertEqual(evidence["cost_usd"], 0.0)
        self.assertEqual(summary["reproduction_totals"]["agent_operations"], 0)
        self.assertEqual(summary["reproduction_totals"]["judge_operations"], 0)

    def test_failed_judge_attempt_reports_current_judge_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research", side_effect=_recorded_run
            ), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.evaluate_run_directory_async",
                side_effect=RuntimeError("judge transport failed"),
            ) as evaluate:
                result = run_benchmark(request, paths=resolve_dci_paths(root))
            evidence = json.loads(
                (result.output_root / "q-1" / "reproduction-evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            summary = json.loads(
                (result.output_root / "summary.json").read_text(encoding="utf-8")
            )

        evaluate.assert_called_once()
        self.assertEqual(result.counts["failed"], 1)
        self.assertEqual(evidence["agent_operations"], 1)
        self.assertEqual(evidence["judge_operations"], 1)
        self.assertEqual(summary["reproduction_totals"]["judge_operations"], 1)

    def test_changed_judge_configuration_reevaluates_without_rerunning_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.capabilities.dci.implementation.runtime.run.PiRpcClient", _FixtureClient), patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            changed = replace(
                request,
                judge_config=JudgeConfig(base_url="https://other.example.test/v1"),
            )
            with patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run, patch(
                "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                return_value=_verdict(changed.judge_config, correct=False),
            ) as evaluate:
                run_benchmark(changed, paths=resolve_dci_paths(root))

        run.assert_not_called()
        evaluate.assert_called_once()

    def test_invalid_dataset_identity_fails_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root, query_id="../escape")
            with patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run:
                with self.assertRaisesRegex(DciBenchmarkError, "dataset is invalid"):
                    run_benchmark(request, paths=Mock())

        run.assert_not_called()

    def test_expected_output_identity_rejects_replacement_before_evidence_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            output_root = root / "out"
            output_root.mkdir(mode=0o700)
            metadata = output_root.stat()
            request = replace(
                _request(root),
                expected_output_root_identity=(
                    metadata.st_dev,
                    metadata.st_ino,
                ),
            )
            output_root.rename(root / "original-out")
            output_root.mkdir(mode=0o700)

            with (
                patch("asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research") as run,
                self.assertRaisesRegex(
                    DciBenchmarkError,
                    "output root identity changed",
                ),
            ):
                run_benchmark(request, paths=Mock())

            run.assert_not_called()
            self.assertEqual(tuple(output_root.iterdir()), ())


def _request(root: Path, *, query_id: str = "q-1") -> BenchmarkRequest:
    dataset = root / "dataset.jsonl"
    dataset.write_text(json.dumps({"query_id": query_id, "query": "question", "answer": "gold"}) + "\n")
    return BenchmarkRequest(
        dataset=dataset,
        output_root=root / "out",
        cwd=root,
        judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
        runtime_options=DciRuntimeOptions(provider=None, model=None),
    )


def _resolution_request(root: Path, *, overlap: float) -> BenchmarkRequest:
    corpus = root / "corpus"
    corpus.mkdir(exist_ok=True)
    document = corpus / "doc.txt"
    body = "gold text\n"
    document.write_text(body, encoding="utf-8")
    manifest = {
        "schema": "dci.gold-document-manifest/v1",
        "dataset_id": "fixture-dataset",
        "query_id": "q-1",
        "documents": [
            {
                "id": "doc.txt",
                "path": "doc.txt",
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "evidence_spans": [{"start": 0, "end": 9}],
            }
        ],
    }
    manifest_path = root / "gold-q-1.json"
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    registry_path = root / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "dci.gold-document-registry/v1",
                "dataset_id": "fixture-dataset",
                "manifests": [
                    {
                        "query_id": "q-1",
                        "path": manifest_path.name,
                        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return replace(
        _request(root),
        profile="asterion-safe/pi",
        corpus=corpus,
        resolution_registry=registry_path,
        resolution_segment_characters=4096,
        resolution_read_minimum_evidence_overlap=overlap,
        conversation_features=DciConversationFeatures(externalize_tool_results=True),
    )


def _result(output_dir: Path) -> DciRunResult:
    return DciRunResult(output_dir=output_dir, final_text="answer", events=(RunEvent("r", 1, "run.started", {"capabilities": []}), RunEvent("r", 2, "run.completed", {"status": "completed"})), status="completed")


def _verdict(config: JudgeConfig, *, correct: bool = True) -> dict[str, object]:
    return {
        **config.public_dict(),
        "judge_contract": "asterion.dci.answer-judge/strict-json/v1",
        "judged_at": "2026-07-14T00:00:00+00:00",
        "attempts": 1,
        "judge_request_fingerprint": "replaced-by-evaluator",
        "is_correct": correct,
        "normalized_prediction": "answer",
        "reason": "fixture",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "cost_estimate_usd": {
            "input_cost": 0.0,
            "cached_input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
        },
    }


if __name__ == "__main__":
    unittest.main()
