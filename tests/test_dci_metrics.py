from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from asterion.dci.benchmark import (
    BenchmarkRequest,
    DciBenchmarkError,
    _metric_contract_for_request,
    _prepare,
    _reusable_result,
    _validate_config_document,
    run_benchmark,
)
from asterion.dci.config import DciRuntimeOptions, resolve_dci_paths
from asterion.dci.judge import JudgeConfig
from asterion.dci.experiment_profiles import resolve_experiment_profile
from asterion.dci.metrics import (
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
        self.assertEqual(
            items[0]["identity"]["ranking_metric_contract"],
            DEDUPLICATED_CONTRACT,
        )
        _validate_config_document(config, expected_execution_class="non-paper")
        legacy = dict(config)
        legacy.pop("ranking_metric_contract")
        with self.assertRaisesRegex(DciBenchmarkError, "evidence is invalid"):
            _validate_config_document(legacy, expected_execution_class="non-paper")

    def test_ir_result_reuse_cannot_cross_metric_contracts(self) -> None:
        safe_item = {
            "row_fingerprint": "a" * 64,
            "identity": {"ranking_metric_contract": DEDUPLICATED_CONTRACT},
        }
        upstream_item = {
            "row_fingerprint": "a" * 64,
            "identity": {"ranking_metric_contract": UPSTREAM_LIST_CONTRACT},
        }
        result = {
            "status": "completed",
            "row_fingerprint": "a" * 64,
            "ranking_metric_contract": DEDUPLICATED_CONTRACT,
        }

        self.assertTrue(_reusable_result(result, safe_item, "ir"))
        self.assertFalse(_reusable_result(result, upstream_item, "ir"))

    def test_profile_effective_metric_identity_preserves_source_semantics(self) -> None:
        safe = resolve_experiment_profile("asterion-safe/pi")
        upstream = resolve_experiment_profile(
            "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi"
        )

        self.assertIn(DEDUPLICATED_CONTRACT, safe.metric_identities)
        self.assertIn(UPSTREAM_LIST_CONTRACT, upstream.metric_identities)

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
            with patch("asterion.dci.run.PiRpcClient", _MetricFixtureClient), patch(
                "asterion.dci.benchmark.compute_ir_ndcg", return_value=1.0
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


if __name__ == "__main__":
    unittest.main()
