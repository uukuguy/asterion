from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    BenchmarkRequest,
    DciBenchmarkError,
    _metric_contract_for_request,
    _paper_ir_assumption_label_for_request,
    _paper_selection_is_comparable,
    _prepare,
    _reusable_result,
    _validate_config_document,
    run_benchmark,
)
from asterion.capabilities.dci.implementation.config import DciRuntimeOptions, resolve_dci_paths
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig
from asterion.capabilities.dci.implementation.research.prompts import prompt_contract_sha256, resolve_prompt_contract
from asterion.capabilities.dci.implementation.research.experiment_profiles import resolve_experiment_profile
from asterion.capabilities.dci.implementation.evaluation.metrics import (
    MetricError,
    compute_ir_ndcg,
    ndcg_at_k_deduplicated,
    ndcg_at_k_upstream_list,
)


UPSTREAM_LIST_CONTRACT = "ndcg@10-binary-upstream-list/v1"
DEDUPLICATED_CONTRACT = "ndcg@10-binary-deduplicated/v1"


class _MetricFixtureClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "response", "id": "metric-1", "success": True},
            {"type": "agent_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "Relevant Documents\n1. a.txt\n2. a.txt",
                },
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "Relevant Documents\n1. a.txt\n2. a.txt"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


class DciMetricContractTests(unittest.TestCase):
    def test_source_specific_duplicate_behavior_uses_exact_float(self) -> None:
        cases = (
            (["a.txt"], {"a.txt"}, 1.0, 1.0),
            (["a.txt", "a.txt"], {"a.txt"}, 1.6309297535714575, 1.0),
            (
                ["a.txt", "a.txt", "b.txt"],
                {"a.txt", "b.txt"},
                1.3065735963827294,
                1.0,
            ),
        )

        for retrieved, gold, upstream_expected, safe_expected in cases:
            with self.subTest(retrieved=retrieved, gold=gold):
                self.assertAlmostEqual(
                    ndcg_at_k_upstream_list(retrieved, gold, 10), upstream_expected
                )
                self.assertAlmostEqual(
                    ndcg_at_k_deduplicated(retrieved, gold, 10), safe_expected
                )

    def test_dispatcher_excludes_query_before_both_contracts(self) -> None:
        final_text = "Relevant Documents\n1. query.txt\n2. a.txt\n3. a.txt"
        row = {"query_id": "query", "gold_docs": ["a.txt"]}

        self.assertAlmostEqual(
            compute_ir_ndcg(
                final_text,
                row,
                None,
                metric_contract=UPSTREAM_LIST_CONTRACT,
            ),
            1.6309297535714575,
        )
        self.assertEqual(
            compute_ir_ndcg(
                final_text,
                row,
                None,
                metric_contract=DEDUPLICATED_CONTRACT,
            ),
            1.0,
        )

    def test_empty_gold_and_unknown_contract_fail_closed(self) -> None:
        self.assertEqual(ndcg_at_k_upstream_list(["a.txt"], set(), 10), 0.0)
        self.assertEqual(ndcg_at_k_deduplicated(["a.txt"], set(), 10), 0.0)
        with self.assertRaisesRegex(MetricError, "contract"):
            compute_ir_ndcg(
                "Relevant Documents\n1. a.txt",
                {"query_id": "query", "gold_docs": ["a.txt"]},
                None,
                metric_contract="unknown/v1",
            )

    def test_benchmark_profile_selects_one_metric_contract_and_rejects_paper_ir(self) -> None:
        request = BenchmarkRequest(
            dataset=Path("/tmp/dataset.jsonl"),
            output_root=Path("/tmp/output"),
            cwd=Path("/tmp"),
            judge_config=JudgeConfig(),
            runtime_options=DciRuntimeOptions(provider="openai", model="gpt-5.4-nano"),
            mode="ir",
            profile="upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi",
        )
        self.assertEqual(_metric_contract_for_request(request), UPSTREAM_LIST_CONTRACT)
        with self.assertRaisesRegex(DciBenchmarkError, "metric contract"):
            _metric_contract_for_request(
                BenchmarkRequest(
                    dataset=request.dataset,
                    output_root=request.output_root,
                    cwd=request.cwd,
                    judge_config=request.judge_config,
                    runtime_options=request.runtime_options,
                    mode="ir",
                    profile="paper-reference/pi",
                )
            )

    def test_paper_ir_assumption_selects_only_declared_scorers(self) -> None:
        missing = BenchmarkRequest(
            dataset=Path("/tmp/dataset.jsonl"),
            output_root=Path("/tmp/output"),
            cwd=Path("/tmp"),
            judge_config=JudgeConfig(),
            runtime_options=DciRuntimeOptions(provider="openai", model="gpt-5.4-nano"),
            mode="ir",
            profile="paper-reference/pi",
        )
        with self.assertRaisesRegex(DciBenchmarkError, "metric contract"):
            _metric_contract_for_request(missing)

        upstream = BenchmarkRequest(
            dataset=missing.dataset,
            output_root=missing.output_root,
            cwd=missing.cwd,
            judge_config=missing.judge_config,
            runtime_options=missing.runtime_options,
            mode="ir",
            profile="paper-reference/pi",
            paper_ir_duplicate_handling="upstream-list",
        )
        self.assertEqual(
            _metric_contract_for_request(upstream), UPSTREAM_LIST_CONTRACT
        )
        for invalid in (
            BenchmarkRequest(
                dataset=missing.dataset,
                output_root=missing.output_root,
                cwd=missing.cwd,
                judge_config=missing.judge_config,
                runtime_options=missing.runtime_options,
                mode="qa",
                profile="paper-reference/pi",
                paper_ir_duplicate_handling="deduplicated",
            ),
            BenchmarkRequest(
                dataset=missing.dataset,
                output_root=missing.output_root,
                cwd=missing.cwd,
                judge_config=missing.judge_config,
                runtime_options=missing.runtime_options,
                mode="ir",
                profile="asterion-safe/pi",
                paper_ir_duplicate_handling="deduplicated",
            ),
            BenchmarkRequest(
                dataset=missing.dataset,
                output_root=missing.output_root,
                cwd=missing.cwd,
                judge_config=missing.judge_config,
                runtime_options=missing.runtime_options,
                mode="ir",
                profile="paper-reference/pi",
                paper_ir_duplicate_handling="unknown",
            ),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(DciBenchmarkError, "metric contract"):
                    _metric_contract_for_request(invalid)

    def test_paper_assumption_label_is_versioned_and_isolates_reuse(self) -> None:
        request = BenchmarkRequest(
            dataset=Path("/tmp/dataset.jsonl"),
            output_root=Path("/tmp/output"),
            cwd=Path("/tmp"),
            judge_config=JudgeConfig(),
            runtime_options=DciRuntimeOptions(provider="openai", model="gpt-5.4-nano"),
            mode="ir",
            profile="paper-reference/pi",
            paper_ir_duplicate_handling="deduplicated",
        )
        label = _paper_ir_assumption_label_for_request(request)
        self.assertEqual(
            label,
            "asterion.operator-assumption/paper-ir-duplicate-handling/deduplicated/v1",
        )
        item = {
            "row_fingerprint": "a" * 64,
            "identity": {
                "ranking_metric_contract": DEDUPLICATED_CONTRACT,
                "paper_ir_duplicate_handling_assumption": label,
            },
        }
        wrong_label_result = {
            "status": "completed",
            "row_fingerprint": "a" * 64,
            "ranking_metric_contract": DEDUPLICATED_CONTRACT,
            "paper_ir_duplicate_handling_assumption": (
                "asterion.operator-assumption/"
                "paper-ir-duplicate-handling/upstream-list/v1"
            ),
        }
        self.assertFalse(_reusable_result(wrong_label_result, item, "ir"))

    def test_paper_assumption_is_not_paper_report_comparable(self) -> None:
        self.assertFalse(
            _paper_selection_is_comparable(
                "asterion.operator-assumption/"
                "paper-ir-duplicate-handling/deduplicated/v1"
            )
        )
        self.assertTrue(_paper_selection_is_comparable(None))

    def test_ir_metric_contract_is_persisted_and_missing_evidence_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "ir.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "query",
                        "query": "question",
                        "gold_docs": ["a.txt"],
                    }
                )
                + "\n"
            )
            output_root = root / "output"
            output_root.mkdir()
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=output_root,
                cwd=root,
                judge_config=JudgeConfig(),
                runtime_options=DciRuntimeOptions(provider=None, model=None),
                mode="ir",
            )
            _rows, _output, config, items, _snapshots = _prepare(request)

        self.assertEqual(config["ranking_metric_contract"], DEDUPLICATED_CONTRACT)
        self.assertIsNone(config["paper_ir_duplicate_handling_assumption"])
        self.assertEqual(
            items[0]["identity"]["ranking_metric_contract"],
            DEDUPLICATED_CONTRACT,
        )
        _validate_config_document(config, expected_execution_class="non-paper")
        legacy = dict(config)
        legacy.pop("ranking_metric_contract")
        with self.assertRaisesRegex(DciBenchmarkError, "evidence is invalid"):
            _validate_config_document(legacy, expected_execution_class="non-paper")
        missing_assumption = dict(config)
        missing_assumption.pop("paper_ir_duplicate_handling_assumption")
        with self.assertRaisesRegex(DciBenchmarkError, "evidence is invalid"):
            _validate_config_document(
                missing_assumption, expected_execution_class="non-paper"
            )
        injected_assumption = dict(config)
        injected_assumption["paper_ir_duplicate_handling_assumption"] = (
            "asterion.operator-assumption/"
            "paper-ir-duplicate-handling/deduplicated/v1"
        )
        with self.assertRaisesRegex(DciBenchmarkError, "evidence is invalid"):
            _validate_config_document(
                injected_assumption, expected_execution_class="non-paper"
            )

    def test_ir_result_reuse_cannot_cross_metric_contracts(self) -> None:
        safe_item = {
            "row_fingerprint": "a" * 64,
            "identity": {
                "ranking_metric_contract": DEDUPLICATED_CONTRACT,
                "paper_ir_duplicate_handling_assumption": None,
            },
        }
        upstream_item = {
            "row_fingerprint": "a" * 64,
            "identity": {
                "ranking_metric_contract": UPSTREAM_LIST_CONTRACT,
                "paper_ir_duplicate_handling_assumption": None,
            },
        }
        result = {
            "status": "completed",
            "row_fingerprint": "a" * 64,
            "ranking_metric_contract": DEDUPLICATED_CONTRACT,
            "paper_ir_duplicate_handling_assumption": None,
        }

        self.assertTrue(_reusable_result(result, safe_item, "ir"))
        self.assertFalse(_reusable_result(result, upstream_item, "ir"))
        self.assertFalse(
            _reusable_result(
                {
                    "status": "completed",
                    "row_fingerprint": "a" * 64,
                    "ranking_metric_contract": DEDUPLICATED_CONTRACT,
                },
                {"row_fingerprint": "a" * 64, "identity": {
                    "ranking_metric_contract": DEDUPLICATED_CONTRACT,
                }},
                "ir",
            )
        )

    def test_profile_effective_metric_identity_preserves_source_semantics(self) -> None:
        safe = resolve_experiment_profile("asterion-safe/pi")
        upstream = resolve_experiment_profile(
            "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi"
        )
        paper = resolve_experiment_profile("paper-reference/pi")

        self.assertIn(DEDUPLICATED_CONTRACT, safe.metric_identities)
        self.assertIn(UPSTREAM_LIST_CONTRACT, upstream.metric_identities)
        self.assertIn("duplicate-handling-unreported", paper.metric_identities[1])

    def test_benchmark_passes_selected_contract_to_ir_scorer_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "ir.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "query",
                        "query": "question",
                        "gold_docs": ["a.txt"],
                    }
                )
                + "\n"
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "output",
                cwd=root,
                judge_config=JudgeConfig(),
                runtime_options=DciRuntimeOptions(provider=None, model=None),
                mode="ir",
                analysis=False,
                figures=False,
            )
            with patch("asterion.capabilities.dci.implementation.runtime.run.PiRpcClient", _MetricFixtureClient), patch(
                "asterion.capabilities.dci.implementation.evaluation.benchmark.compute_ir_ndcg", return_value=1.0
            ) as score:
                run_benchmark(request, paths=resolve_dci_paths(root))

            self.assertEqual(
                score.call_args.kwargs["metric_contract"], DEDUPLICATED_CONTRACT
            )
            summary = json.loads((request.output_root / "summary.json").read_text())
            self.assertEqual(
                summary["provenance"]["ranking_metric_contract"],
                DEDUPLICATED_CONTRACT,
            )

    def test_paper_assumption_scores_and_labels_actual_benchmark_metrics(self) -> None:
        safe_prompt = resolve_prompt_contract("asterion.dci.prompt/safe/v1")
        prompt_identity = prompt_contract_sha256(safe_prompt, "ir")
        cases = (
            ("upstream-list", UPSTREAM_LIST_CONTRACT, 1.6309297535714575),
            ("deduplicated", DEDUPLICATED_CONTRACT, 1.0),
        )
        for handling, contract, expected_score in cases:
            with self.subTest(handling=handling), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory).resolve()
                dataset = root / "ir.jsonl"
                corpus = root / "corpus"
                corpus.mkdir()
                dataset.write_text(
                    json.dumps(
                        {
                            "query_id": "query",
                            "query": "question",
                            "gold_docs": ["a.txt"],
                        }
                    )
                    + "\n"
                )
                request = BenchmarkRequest(
                    dataset=dataset,
                    output_root=root / "output",
                    cwd=root,
                    judge_config=JudgeConfig(),
                    runtime_options=DciRuntimeOptions(
                        provider="openai", model="gpt-5.4-nano"
                    ),
                    mode="ir",
                    profile="paper-reference/pi",
                    corpus=corpus,
                    analysis=False,
                    figures=False,
                    paper_ir_duplicate_handling=handling,
                )
                with patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.paper_scope_for_profile",
                    return_value=None,
                ), patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark._prompt_contract_for_request",
                    return_value=(safe_prompt, prompt_identity),
                ), patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark._has_selected_prompt_contract",
                    return_value=True,
                ), patch("asterion.capabilities.dci.implementation.runtime.run.PiRpcClient", _MetricFixtureClient):
                    run_benchmark(request, paths=resolve_dci_paths(root))

                summary = json.loads((request.output_root / "summary.json").read_text())
                label = (
                    "asterion.operator-assumption/"
                    f"paper-ir-duplicate-handling/{handling}/v1"
                )
                self.assertEqual(summary["ndcg_at_10"], expected_score)
                self.assertEqual(
                    summary["provenance"]["ranking_metric_contract"], contract
                )
                self.assertEqual(
                    summary["provenance"]["result_label"], label
                )


if __name__ == "__main__":
    unittest.main()
