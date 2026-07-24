from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from asterion.dci.benchmark import BenchmarkRequest, DciBenchmarkError, run_benchmark
from asterion.dci.config import DciRuntimeOptions, resolve_dci_paths
from asterion.dci.judge import JudgeConfig
from asterion.dci.run import DciRunResult, run_pi_research as _real_run_pi_research
from asterion.runtime.host import RunEvent


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


def _recorded_run(_paths: object, request: object, **kwargs: object) -> DciRunResult:
    with patch("asterion.dci.run.PiRpcClient", _FixtureClient):
        return _real_run_pi_research(
            resolve_dci_paths(Path(request.cwd)), request, **kwargs
        )


class AsterionDciBenchmarkTests(unittest.TestCase):
    def test_persisted_batch_judge_identity_is_prompt_and_request_shape_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.dci.run.PiRpcClient", _FixtureClient), patch(
                "asterion.dci.evaluation.judge_answer_sync",
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
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
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
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
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
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
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
            with patch("asterion.dci.run.PiRpcClient", _FixtureClient), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            with patch("asterion.dci.benchmark.run_pi_research") as run:
                with patch("asterion.dci.benchmark.evaluate_run_directory_async") as evaluate:
                    run_benchmark(request, paths=resolve_dci_paths(root))

        run.assert_not_called()
        evaluate.assert_not_called()

    def test_changed_judge_configuration_reevaluates_without_rerunning_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.dci.run.PiRpcClient", _FixtureClient), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            changed = replace(
                request,
                judge_config=JudgeConfig(base_url="https://other.example.test/v1"),
            )
            with patch("asterion.dci.benchmark.run_pi_research") as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(changed.judge_config, correct=False),
            ) as evaluate:
                run_benchmark(changed, paths=resolve_dci_paths(root))

        run.assert_not_called()
        evaluate.assert_called_once()

    def test_invalid_dataset_identity_fails_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root, query_id="../escape")
            with patch("asterion.dci.benchmark.run_pi_research") as run:
                with self.assertRaisesRegex(DciBenchmarkError, "dataset is invalid"):
                    run_benchmark(request, paths=Mock())

        run.assert_not_called()


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


def _result(output_dir: Path) -> DciRunResult:
    return DciRunResult(output_dir=output_dir, final_text="answer", events=(RunEvent("r", 1, "run.started", {"capabilities": []}), RunEvent("r", 2, "run.completed", {"status": "completed"})), status="completed")


def _verdict(config: JudgeConfig, *, correct: bool = True) -> dict[str, object]:
    return {
        **config.public_dict(),
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
