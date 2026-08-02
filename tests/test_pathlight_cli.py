from __future__ import annotations

import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import TypeVar
from unittest.mock import patch

from asterion.cli import main
from asterion.pathlight import (
    EvaluationRecord,
    MetricContract,
    TraceEvent,
    TraceGraph,
    write_evaluation_bundle,
)
from asterion.pathlight.experiment import (
    CaseTrial,
    DatasetSnapshot,
    EvaluatorContract,
    ExperimentBundle,
    ExperimentPlan,
    Variant,
    write_experiment_bundle,
)
from asterion.workflow_evidence import write_workflow_observation_bundle


TRACE_ID = "00000000-0000-4000-8000-000000000001"
_T = TypeVar("_T")


class FailIfLoadedEntryPoint:
    def load(self) -> object:
        raise AssertionError("application provider entry point was loaded")


def _trace() -> dict[str, object]:
    root = "00000000-0000-4000-8000-000000000002"
    return TraceGraph.build(
        TRACE_ID,
        (
            TraceEvent.start(TRACE_ID, root, None, 1, "task", timestamp_ns=1),
            TraceEvent.terminal(
                TRACE_ID, root, 2, "completed", timestamp_ns=2, attributes={"duration_ns": 1}
            ),
        ),
    ).to_mapping()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ordered(values: tuple[_T, ...], *, reverse: bool) -> tuple[_T, ...]:
    return tuple(reversed(values)) if reverse else values


def _evaluation(value_microunits: int) -> tuple[MetricContract, EvaluationRecord]:
    contract = MetricContract("accuracy", "ratio", True, "1.0.0")
    return contract, EvaluationRecord(
        trace_sha256=_digest("trace"),
        metric_contract_sha256=contract.metric_contract_sha256,
        dataset_snapshot_sha256=_digest("dataset"),
        scope_sha256=_digest("scope"),
        value_microunits=value_microunits,
        selected_count=1,
        total_count=1,
        status="observed",
    )


def _experiment_bundle(*, reverse: bool = False) -> ExperimentBundle:
    dataset = DatasetSnapshot(_digest("dataset-contract"), _digest("dataset"), 1, "1.0.0")
    evaluator = EvaluatorContract(
        _digest("metric"), "rule", _digest("implementation"), _digest("input"),
        _digest("output"), _digest("failure"), "1.0.0",
    )
    baseline = Variant(
        *(
            _digest(name)
            for name in (
                "assembly",
                "packages",
                "implementation",
                "runtime",
                "model",
                "tools",
                "prompt",
                "policy",
                "baseline-change",
            )
        )
    )
    candidate = Variant(
        *(
            _digest(name)
            for name in (
                "candidate-assembly",
                "candidate-packages",
                "candidate-implementation",
                "candidate-runtime",
                "candidate-model",
                "candidate-tools",
                "candidate-prompt",
                "candidate-policy",
                "candidate-change",
            )
        )
    )
    plan = ExperimentPlan(
        dataset.dataset_snapshot_sha256,
        _digest("scope"),
        baseline.variant_sha256,
        (candidate.variant_sha256,),
        _digest("assignment"), (evaluator.evaluator_contract_sha256,), _digest("budget"),
        _digest("stop"),
    )
    baseline_evaluation = EvaluationRecord(
        _digest("baseline-trace"),
        evaluator.metric_contract_sha256,
        dataset.dataset_snapshot_sha256,
        plan.scope_sha256,
        1,
        1,
        1,
        "recovered",
    )
    candidate_evaluation = EvaluationRecord(
        _digest("candidate-trace"),
        evaluator.metric_contract_sha256,
        dataset.dataset_snapshot_sha256,
        plan.scope_sha256,
        2,
        1,
        1,
        "recovered",
    )
    baseline_trial = CaseTrial(
        plan.experiment_plan_sha256,
        _digest("baseline-case"),
        baseline.variant_sha256,
        baseline_evaluation.trace_sha256,
        (baseline_evaluation.evaluation_sha256,),
        "recovered",
        (),
    )
    candidate_trial = CaseTrial(
        plan.experiment_plan_sha256,
        _digest("candidate-case"),
        candidate.variant_sha256,
        candidate_evaluation.trace_sha256,
        (candidate_evaluation.evaluation_sha256,),
        "recovered",
        (),
    )

    return ExperimentBundle.build(
        datasets=_ordered((dataset,), reverse=reverse),
        evaluators=_ordered((evaluator,), reverse=reverse),
        variants=_ordered((baseline, candidate), reverse=reverse),
        plans=_ordered((plan,), reverse=reverse),
        trials=_ordered((baseline_trial, candidate_trial), reverse=reverse),
        evaluations=_ordered(
            (baseline_evaluation, candidate_evaluation), reverse=reverse
        ),
    )


class PathlightCliTests(unittest.TestCase):
    def test_experiment_show_and_trials_are_provider_free_canonical_json(self) -> None:
        bundle = _experiment_bundle()
        reversed_bundle = _experiment_bundle(reverse=True)
        self.assertEqual(reversed_bundle, bundle)
        plan = bundle.plans[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outputs: list[tuple[str, str]] = []
            for name, source in (("forward", bundle), ("reversed", reversed_bundle)):
                source_root = root / name
                source_root.mkdir()
                path = source_root / "pathlight-experiment.json"
                write_experiment_bundle(source, path)
                command_outputs: list[str] = []
                for command in ("show", "trials"):
                    stdout = io.StringIO()
                    arguments = [
                        "pathlight",
                        "experiment",
                        command,
                        "--experiment-file",
                        str(path),
                        "--experiment-sha256",
                        plan.experiment_plan_sha256,
                    ]
                    if command == "trials":
                        arguments.extend(("--evidence-state", "recovered"))
                    code = main(
                        arguments,
                        entry_points=(FailIfLoadedEntryPoint(),),
                        stdout=stdout,
                    )
                    self.assertEqual(code, 0)
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(
                        stdout.getvalue(),
                        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                    )
                    command_outputs.append(stdout.getvalue())
                outputs.append((command_outputs[0], command_outputs[1]))

        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(
            json.loads(outputs[0][0])["experiment_plan_sha256"],
            plan.experiment_plan_sha256,
        )
        self.assertEqual(len(json.loads(outputs[0][1])), 2)

    def test_experiment_cli_redacts_private_values_in_invalid_requests(self) -> None:
        stderr = io.StringIO()

        code = main(
            [
                "pathlight", "experiment", "show", "--experiment-file",
                "SENTINEL_PRIVATE_PATH_AND_PROMPT", "--experiment-sha256", "invalid",
            ],
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")
        self.assertNotIn("SENTINEL_PRIVATE_PATH_AND_PROMPT", stderr.getvalue())

    def test_experiment_cli_normalizes_hostile_reader_exceptions(self) -> None:
        stderr = io.StringIO()
        with patch(
            "asterion.cli_pathlight.read_experiment_bundle",
            side_effect=RuntimeError("SENTINEL_PRIVATE_HOSTILE_EXCEPTION"),
        ):
            code = main(
                [
                    "pathlight", "experiment", "show", "--experiment-file",
                    "/private/pathlight-experiment.json", "--experiment-sha256", "0" * 64,
                ],
                stderr=stderr,
            )

        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")
        self.assertNotIn("SENTINEL_PRIVATE_HOSTILE_EXCEPTION", stderr.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-experiment.json"
            path.write_text("[" * 2_000 + "]" * 2_000, encoding="utf-8")
            path.chmod(0o600)
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = main(
                [
                    "pathlight",
                    "experiment",
                    "show",
                    "--experiment-file",
                    str(path),
                    "--experiment-sha256",
                    "0" * 64,
                ],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")

    def test_pathlight_routes_without_loading_application_providers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(bundle, (), pathlight_traces=(_trace(),))
            stdout = io.StringIO()

            code = main(
                ["pathlight", "trace", "list", "--evidence-file", str(bundle)],
                entry_points=(FailIfLoadedEntryPoint(),),
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())[0]["trace_id"], TRACE_ID)

    def test_cli_never_echoes_path_or_private_input_on_error(self) -> None:
        stderr = io.StringIO()

        code = main(
            [
                "pathlight",
                "trace",
                "show",
                "--evidence-file",
                "SENTINEL_PRIVATE_PATH",
                "--trace-id",
                TRACE_ID,
            ],
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")
        self.assertNotIn("SENTINEL_PRIVATE_PATH", stderr.getvalue())

    def test_trace_show_and_tail_emit_canonical_snapshot_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(bundle, (), pathlight_traces=(_trace(),))
            for arguments, expected in (
                (
                    ["trace", "show", "--evidence-file", str(bundle), "--trace-id", TRACE_ID],
                    TRACE_ID,
                ),
                (
                    [
                        "trace",
                        "tail",
                        "--evidence-file",
                        str(bundle),
                        "--trace-id",
                        TRACE_ID,
                        "--after-sequence",
                        "1",
                    ],
                    2,
                ),
            ):
                with self.subTest(arguments=arguments):
                    stdout = io.StringIO()
                    code = main(["pathlight", *arguments], stdout=stdout)
                    self.assertEqual(code, 0)
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(
                        payload["trace_id"] if isinstance(payload, dict) else payload[0]["sequence"],
                        expected,
                    )
                    self.assertEqual(stdout.getvalue(), json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    def test_metric_query_and_exact_evaluation_comparison_are_provider_free(self) -> None:
        first_contract, baseline = _evaluation(100)
        second_contract, candidate = _evaluation(125)
        self.assertEqual(first_contract, second_contract)
        with tempfile.TemporaryDirectory() as directory:
            evaluations = Path(directory).resolve() / "pathlight-evaluations.json"
            write_evaluation_bundle(evaluations, (baseline, candidate), (first_contract,))
            stdout = io.StringIO()
            code = main(
                [
                    "pathlight",
                    "metrics",
                    "query",
                    "--evaluation-file",
                    str(evaluations),
                    "--metric-name",
                    "accuracy",
                ],
                stdout=stdout,
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())[0]["metric_name"], "accuracy")
            stdout = io.StringIO()
            code = main(
                [
                    "pathlight",
                    "evaluate",
                    "compare",
                    "--evaluation-file",
                    str(evaluations),
                    "--baseline",
                    baseline.evaluation_sha256,
                    "--candidate",
                    candidate.evaluation_sha256,
                ],
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["delta_microunits"], 25)

    def test_metric_query_deduplicates_shared_contract_across_evaluation_files(self) -> None:
        contract, first = _evaluation(100)
        _, second = _evaluation(125)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            first_path = first_root / "pathlight-evaluations.json"
            second_path = second_root / "pathlight-evaluations.json"
            write_evaluation_bundle(first_path, (first,), (contract,))
            write_evaluation_bundle(second_path, (second,), (contract,))
            stdout = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "metrics",
                    "query",
                    "--evaluation-file",
                    str(first_path),
                    "--evaluation-file",
                    str(second_path),
                ],
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            [row["evaluation_sha256"] for row in json.loads(stdout.getvalue())],
            sorted((first.evaluation_sha256, second.evaluation_sha256)),
        )

    def test_compare_deduplicates_shared_contract_across_evaluation_files(self) -> None:
        contract, baseline = _evaluation(100)
        _, candidate = _evaluation(125)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            baseline_root = root / "baseline"
            candidate_root = root / "candidate"
            baseline_root.mkdir()
            candidate_root.mkdir()
            baseline_path = baseline_root / "pathlight-evaluations.json"
            candidate_path = candidate_root / "pathlight-evaluations.json"
            write_evaluation_bundle(baseline_path, (baseline,), (contract,))
            write_evaluation_bundle(candidate_path, (candidate,), (contract,))
            stdout = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "evaluate",
                    "compare",
                    "--evaluation-file",
                    str(baseline_path),
                    "--evaluation-file",
                    str(candidate_path),
                    "--baseline",
                    baseline.evaluation_sha256,
                    "--candidate",
                    candidate.evaluation_sha256,
                ],
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["delta_microunits"], 25)

    def test_cli_requires_absolute_canonical_regular_filenames(self) -> None:
        stderr = io.StringIO()

        code = main(
            ["pathlight", "trace", "list", "--evidence-file", "relative.json"],
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")


if __name__ == "__main__":
    unittest.main()
