from __future__ import annotations

import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from asterion.cli import main
from asterion.pathlight import (
    EvaluationRecord,
    MetricContract,
    TraceEvent,
    TraceGraph,
    write_evaluation_bundle,
)
from asterion.workflow_evidence import write_workflow_observation_bundle


TRACE_ID = "00000000-0000-4000-8000-000000000001"


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


class PathlightCliTests(unittest.TestCase):
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
