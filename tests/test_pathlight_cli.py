from __future__ import annotations

import io
import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import TypeVar
from unittest.mock import patch

from asterion.cli import main
from asterion.pathlight import (
    DiagnosisBundle,
    EvaluationRecord,
    ExternalObservation,
    Finding,
    MetricContract,
    ModelCallObservation,
    Proposal,
    ProviderRequestObservation,
    RuntimeObservationBatch,
    TraceEvent,
    TraceGraph,
    write_diagnosis_bundle,
    write_evaluation_bundle,
    write_optimization_bundle,
)
from asterion.pathlight._private_file import write_private_file
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
from asterion.runtime.host import RunEvent
import asterion.workflow_evidence as workflow_evidence
from tests.test_pathlight_flow import _rich_trace
from tests.test_workflow_evidence_runtime import (
    TRACE_ID as VERIFIED_TRACE_ID,
    _native_events,
    _per_call_missing_evidence_batch,
    _request,
    _verified_provider_request_batch,
)
from tests.test_pathlight_optimization import _optimization_bundle


TRACE_ID = "00000000-0000-4000-8000-000000000001"
_T = TypeVar("_T")

PUBLIC_PROVIDER_REQUEST_FIELDS = (
    "request_sha256",
    "request_shape_sha256",
    "payload_bytes",
    "field_count",
    "leaf_count",
    "text_characters",
    "private_reference_sha256",
)
PRIVATE_PROVIDER_REQUEST_SENTINELS = (
    "SENTINEL_RAW_PROVIDER_PAYLOAD",
    "SENTINEL_RAW_PAYLOAD_KEY",
    "SENTINEL_RAW_PAYLOAD_VALUE",
    "SENTINEL_PRIVATE_PROVIDER_IDENTITY",
    "SENTINEL_PRIVATE_MODEL_IDENTITY",
    "SENTINEL_PRIVATE_CONFIG_IDENTITY",
    "987654321",
    "/private/SENTINEL_PROVIDER_REQUEST_CAPTURE",
)
PRIVATE_PER_CALL_SENTINELS = (
    *PRIVATE_PROVIDER_REQUEST_SENTINELS,
    "SENTINEL_PRIVATE_PROMPT",
    "SENTINEL_PRIVATE_ANSWER",
    "SENTINEL_PRIVATE_TOOL_BODY",
    "SENTINEL_NATIVE_INPUT",
    "SENTINEL_NATIVE_ARGUMENT",
    "SENTINEL_NATIVE_RESULT",
    "private.native.tool",
    "pi.reference",
)


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
                TRACE_ID,
                root,
                2,
                "completed",
                timestamp_ns=2,
                attributes={"duration_ns": 1},
            ),
        ),
    ).to_mapping()


def _write_offline_workflow_bundle(
    root: Path,
    trace: dict[str, object],
) -> Path:
    canonical = root / "workflow-evidence.json"
    write_workflow_observation_bundle(canonical, (), pathlight_traces=(trace,))
    offline = root / "workflow-evidence.provider-calls.offline.json"
    canonical.rename(offline)
    return offline


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ordered(values: tuple[_T, ...], *, reverse: bool) -> tuple[_T, ...]:
    return tuple(reversed(values)) if reverse else values


def _verified_provider_request_fixture() -> tuple[
    RuntimeObservationBatch, dict[str, object]
]:
    raw_payload = {
        "SENTINEL_RAW_PAYLOAD_KEY": "SENTINEL_RAW_PAYLOAD_VALUE",
        "provider": "SENTINEL_PRIVATE_PROVIDER_IDENTITY",
        "model": "SENTINEL_PRIVATE_MODEL_IDENTITY",
        "config": "SENTINEL_PRIVATE_CONFIG_IDENTITY",
        "raw": "SENTINEL_RAW_PROVIDER_PAYLOAD",
    }
    payload_json = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"))
    payload_sha256 = _digest(payload_json)
    private_path = "/private/SENTINEL_PROVIDER_REQUEST_CAPTURE"
    private_fd = 987654321
    inferred = _verified_provider_request_batch()
    model_calls = tuple(
        ModelCallObservation(
            request_index=call.request_index,
            frame_sha256=call.frame_sha256,
            model_sha256=_digest(raw_payload["model"]),
            request_sha256=payload_sha256,
            response_sha256=call.response_sha256,
            response_length=call.response_length,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            status=call.status,
            boundary_observed=False,
        )
        for call in inferred.model_calls
    )
    provider_requests = tuple(
        ProviderRequestObservation.build(
            request_index=call.request_index,
            payload_sha256=payload_sha256,
            payload_bytes=len(payload_json.encode("utf-8")),
            shape_sha256=_digest(
                "object:config,model,provider,raw,SENTINEL_RAW_PAYLOAD_KEY"
            ),
            field_count=len(raw_payload),
            leaf_count=len(raw_payload),
            text_characters=sum(len(value) for value in raw_payload.values()),
            private_reference_sha256=_digest(
                f"{private_path}:{private_fd}:{call.request_index}"
            ),
            segments=inferred.provider_requests[call.request_index - 1].segments,
        )
        for call in model_calls
    )
    batch = RuntimeObservationBatch.build(
        run_sha256=inferred.run_sha256,
        frames=inferred.frames,
        model_calls=model_calls,
        tools=inferred.tools,
        provider_requests=provider_requests,
        missing_evidence=("model-request-boundary",),
    )
    events = tuple(
        RunEvent("native-run", sequence, event_type, payload).to_mapping()
        for sequence, (event_type, payload) in enumerate(_native_events(), start=1)
    )
    projected = workflow_evidence.project_completed_runtime_evidence(
        request=_request(),
        event_observations=tuple(
            (event, index * 10 + 2, index * 10 + 3)
            for index, event in enumerate(events)
        ),
        native_observation=batch,
        runtime_id="pi.reference",
        trace_id=VERIFIED_TRACE_ID,
        invocation_started_ns=1,
        invocation_ended_ns=len(events) * 10 + 4,
    )
    return batch, json.loads(json.dumps(projected.trace, default=dict))


def _per_call_missing_evidence_fixture() -> tuple[
    RuntimeObservationBatch, dict[str, object]
]:
    raw_payload = {
        "SENTINEL_RAW_PAYLOAD_KEY": "SENTINEL_RAW_PAYLOAD_VALUE",
        "provider": "SENTINEL_PRIVATE_PROVIDER_IDENTITY",
        "model": "SENTINEL_PRIVATE_MODEL_IDENTITY",
        "config": "SENTINEL_PRIVATE_CONFIG_IDENTITY",
        "prompt": "SENTINEL_PRIVATE_PROMPT",
        "answer": "SENTINEL_PRIVATE_ANSWER",
        "tool_body": "SENTINEL_PRIVATE_TOOL_BODY",
        "raw": "SENTINEL_RAW_PROVIDER_PAYLOAD",
    }
    payload_json = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"))
    payload_sha256 = _digest(payload_json)
    private_path = "/private/SENTINEL_PROVIDER_REQUEST_CAPTURE"
    private_fd = 987654321
    inferred = _per_call_missing_evidence_batch()
    model_calls = tuple(
        ModelCallObservation(
            request_index=call.request_index,
            frame_sha256=call.frame_sha256,
            model_sha256=(
                None
                if call.model_sha256 is None
                else _digest(raw_payload["model"])
            ),
            request_sha256=payload_sha256,
            response_sha256=call.response_sha256,
            response_length=call.response_length,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            status=call.status,
            boundary_observed=False,
        )
        for call in inferred.model_calls
    )
    provider_requests = tuple(
        ProviderRequestObservation.build(
            request_index=call.request_index,
            payload_sha256=payload_sha256,
            payload_bytes=len(payload_json.encode("utf-8")),
            shape_sha256=_digest(
                "object:answer,config,model,prompt,provider,raw,"
                "SENTINEL_RAW_PAYLOAD_KEY,tool_body"
            ),
            field_count=len(raw_payload),
            leaf_count=len(raw_payload),
            text_characters=sum(len(value) for value in raw_payload.values()),
            private_reference_sha256=_digest(
                f"{private_path}:{private_fd}:{call.request_index}"
            ),
            segments=inferred.frames[0].segments,
        )
        for call in model_calls
    )
    batch = RuntimeObservationBatch.build(
        run_sha256=inferred.run_sha256,
        frames=inferred.frames,
        model_calls=model_calls,
        tools=inferred.tools,
        provider_requests=provider_requests,
        missing_evidence=inferred.missing_evidence,
    )
    events = tuple(
        RunEvent("native-run", sequence, event_type, payload).to_mapping()
        for sequence, (event_type, payload) in enumerate(_native_events(), start=1)
    )
    projected = workflow_evidence.project_completed_runtime_evidence(
        request=_request(),
        event_observations=tuple(
            (event, index * 10 + 2, index * 10 + 3)
            for index, event in enumerate(events)
        ),
        native_observation=batch,
        runtime_id="pi.reference",
        trace_id=VERIFIED_TRACE_ID,
        invocation_started_ns=1,
        invocation_ended_ns=len(events) * 10 + 4,
    )
    return batch, json.loads(json.dumps(projected.trace, default=dict))


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
    dataset = DatasetSnapshot(
        _digest("dataset-contract"), _digest("dataset"), 1, "1.0.0"
    )
    evaluator = EvaluatorContract(
        _digest("metric"),
        "rule",
        _digest("implementation"),
        _digest("input"),
        _digest("output"),
        _digest("failure"),
        "1.0.0",
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
        _digest("assignment"),
        (evaluator.evaluator_contract_sha256,),
        _digest("budget"),
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
    def test_trace_show_and_flow_accept_exact_offline_companion(self) -> None:
        _, trace = _verified_provider_request_fixture()
        with tempfile.TemporaryDirectory() as directory:
            bundle = _write_offline_workflow_bundle(
                Path(directory).resolve(), trace
            )
            outputs: list[str] = []
            for arguments in (
                ["trace", "show", "--trace-id", VERIFIED_TRACE_ID],
                ["trace", "flow", "--trace-id", VERIFIED_TRACE_ID],
            ):
                with self.subTest(arguments=arguments):
                    stdout = io.StringIO()
                    code = main(
                        [
                            "pathlight",
                            *arguments,
                            "--evidence-file",
                            str(bundle),
                        ],
                        entry_points=(FailIfLoadedEntryPoint(),),
                        stdout=stdout,
                    )
                    self.assertEqual(code, 0)
                    outputs.append(stdout.getvalue())

        for output in outputs:
            for sentinel in PRIVATE_PROVIDER_REQUEST_SENTINELS:
                with self.subTest(sentinel=sentinel):
                    self.assertNotIn(sentinel, output)

    def test_dashboard_accepts_exact_offline_companion(self) -> None:
        _, trace = _verified_provider_request_fixture()
        with tempfile.TemporaryDirectory() as directory:
            bundle = _write_offline_workflow_bundle(
                Path(directory).resolve(), trace
            )
            with patch("asterion.cli_pathlight.serve_dashboard") as serve:
                code = main(
                    [
                        "pathlight",
                        "dashboard",
                        "--evidence-file",
                        str(bundle),
                    ],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=io.StringIO(),
                )

        self.assertEqual(code, 0)
        rendered = json.dumps(serve.call_args.args[0].to_mapping(), sort_keys=True)
        for sentinel in PRIVATE_PROVIDER_REQUEST_SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, rendered)

    def test_opik_export_accepts_exact_offline_companion(self) -> None:
        _, trace = _verified_provider_request_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundle = _write_offline_workflow_bundle(root, trace)
            queue = root / "queue"
            queue.mkdir(mode=0o700)
            stdout = io.StringIO()
            code = main(
                [
                    "pathlight",
                    "export",
                    "opik",
                    "--evidence-file",
                    str(bundle),
                    "--queue-root",
                    str(queue),
                ],
                entry_points=(FailIfLoadedEntryPoint(),),
                stdout=stdout,
            )
            self.assertEqual(code, 0)
            rendered = stdout.getvalue() + next(queue.iterdir()).read_text()
            for sentinel in PRIVATE_PROVIDER_REQUEST_SENTINELS:
                with self.subTest(sentinel=sentinel):
                    self.assertNotIn(sentinel, rendered)

    def test_public_read_surfaces_reject_offline_companion_near_misses(self) -> None:
        _, trace = _verified_provider_request_fixture()
        for basename in (
            "renamed-offline.json",
            "workflow-evidence.provider-calls.offline.json.bak",
            "other.json",
        ):
            with (
                self.subTest(basename=basename),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory).resolve()
                offline = _write_offline_workflow_bundle(root, trace)
                candidate = root / basename
                candidate.write_bytes(offline.read_bytes())

                trace_error = io.StringIO()
                trace_code = main(
                    [
                        "pathlight",
                        "trace",
                        "show",
                        "--evidence-file",
                        str(candidate),
                        "--trace-id",
                        VERIFIED_TRACE_ID,
                    ],
                    stderr=trace_error,
                )
                self.assertEqual(trace_code, 2)
                self.assertEqual(
                    trace_error.getvalue(), "asterion pathlight: request is invalid\n"
                )

                dashboard_error = io.StringIO()
                with patch("asterion.cli_pathlight.serve_dashboard") as serve:
                    dashboard_code = main(
                        [
                            "pathlight",
                            "dashboard",
                            "--evidence-file",
                            str(candidate),
                        ],
                        stderr=dashboard_error,
                    )
                self.assertEqual(dashboard_code, 2)
                self.assertEqual(
                    dashboard_error.getvalue(),
                    "asterion pathlight: request is invalid\n",
                )
                serve.assert_not_called()

                queue = root / "queue"
                queue.mkdir(mode=0o700)
                opik_error = io.StringIO()
                opik_code = main(
                    [
                        "pathlight",
                        "export",
                        "opik",
                        "--evidence-file",
                        str(candidate),
                        "--queue-root",
                        str(queue),
                    ],
                    stderr=opik_error,
                )
                self.assertEqual(opik_code, 2)
                self.assertEqual(
                    opik_error.getvalue(), "asterion pathlight: request is invalid\n"
                )
                self.assertEqual(tuple(queue.iterdir()), ())

    def test_dashboard_cli_validates_inputs_and_serves_without_provider(self) -> None:
        contract, evaluation = _evaluation(750_000)
        with tempfile.TemporaryDirectory() as directory:
            evaluations = Path(directory).resolve() / "pathlight-evaluations.json"
            write_evaluation_bundle(evaluations, (evaluation,), (contract,))
            stdout = io.StringIO()
            with patch("asterion.cli_pathlight.serve_dashboard") as serve:
                code = main(
                    [
                        "pathlight",
                        "dashboard",
                        "--evaluation-file",
                        str(evaluations),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8765",
                    ],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=stdout,
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "stopped")
            snapshot = serve.call_args.args[0]
            self.assertEqual(snapshot.summary["evaluation_count"], 1)
            self.assertEqual(serve.call_args.kwargs["host"], "127.0.0.1")
            self.assertEqual(serve.call_args.kwargs["port"], 8765)
            self.assertFalse(serve.call_args.kwargs["open_browser"])
            self.assertTrue(callable(serve.call_args.kwargs["on_ready"]))

    def test_dashboard_cli_opens_browser_only_when_explicit(self) -> None:
        contract, evaluation = _evaluation(1)
        with tempfile.TemporaryDirectory() as directory:
            evaluations = Path(directory).resolve() / "pathlight-evaluations.json"
            write_evaluation_bundle(evaluations, (evaluation,), (contract,))
            with patch("asterion.cli_pathlight.serve_dashboard") as serve:
                code = main(
                    [
                        "pathlight",
                        "dashboard",
                        "--evaluation-file",
                        str(evaluations),
                        "--open",
                    ],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=io.StringIO(),
                )

        self.assertEqual(code, 0)
        self.assertTrue(serve.call_args.kwargs["open_browser"])

    def test_dashboard_cli_rejects_empty_relative_tampered_and_nonloopback_inputs(
        self,
    ) -> None:
        cases = (
            ["pathlight", "dashboard"],
            [
                "pathlight",
                "dashboard",
                "--evaluation-file",
                "relative/pathlight-evaluations.json",
            ],
            [
                "pathlight",
                "dashboard",
                "--evaluation-file",
                "/private/pathlight-evaluations.json",
                "--host",
                "0.0.0.0",
            ],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                stderr = io.StringIO()
                with patch("asterion.cli_pathlight.serve_dashboard") as serve:
                    code = main(arguments, stderr=stderr)
                self.assertEqual(code, 2)
                self.assertEqual(
                    stderr.getvalue(), "asterion pathlight: request is invalid\n"
                )
                serve.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve() / "pathlight-evaluations.json"
            source.write_text("{}")
            os.chmod(source, 0o600)
            stderr = io.StringIO()
            with patch("asterion.cli_pathlight.serve_dashboard") as serve:
                code = main(
                    [
                        "pathlight",
                        "dashboard",
                        "--evaluation-file",
                        str(source),
                    ],
                    stderr=stderr,
                )
            self.assertEqual(code, 2)
            self.assertEqual(
                stderr.getvalue(), "asterion pathlight: request is invalid\n"
            )
            serve.assert_not_called()

    def test_opik_export_and_inspect_are_offline_private_and_idempotent(self) -> None:
        contract, evaluation = _evaluation(750_000)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evaluations = root / "pathlight-evaluations.json"
            write_evaluation_bundle(evaluations, (evaluation,), (contract,))
            queue = root / "queue"
            queue.mkdir(mode=0o700)
            outputs = []
            for _ in range(2):
                stdout = io.StringIO()
                code = main(
                    [
                        "pathlight",
                        "export",
                        "opik",
                        "--evaluation-file",
                        str(evaluations),
                        "--queue-root",
                        str(queue),
                    ],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=stdout,
                )
                self.assertEqual(code, 0)
                outputs.append(json.loads(stdout.getvalue()))

            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0]["network_operation_count"], 0)
            self.assertEqual(outputs[0]["envelope_count"], 1)
            batches = tuple(queue.glob("batch-*.json"))
            self.assertEqual(len(batches), 1)
            self.assertEqual(stat.S_IMODE(batches[0].stat().st_mode), 0o600)

            inspected = io.StringIO()
            code = main(
                [
                    "pathlight",
                    "export",
                    "inspect",
                    "--batch-file",
                    str(batches[0]),
                ],
                entry_points=(FailIfLoadedEntryPoint(),),
                stdout=inspected,
            )
            self.assertEqual(code, 0)
            payload = json.loads(inspected.getvalue())
            self.assertEqual(payload["batch_sha256"], outputs[0]["batch_sha256"])
            self.assertEqual(
                payload["envelopes"][0]["payload"]["value_microunits"],
                750_000,
            )

    def test_opik_export_rejects_unsafe_queue_without_loading_provider(self) -> None:
        contract, evaluation = _evaluation(1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evaluations = root / "pathlight-evaluations.json"
            write_evaluation_bundle(evaluations, (evaluation,), (contract,))
            queue = root / "queue"
            queue.mkdir(mode=0o755)
            stderr = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "export",
                    "opik",
                    "--evaluation-file",
                    str(evaluations),
                    "--queue-root",
                    str(queue),
                ],
                entry_points=(FailIfLoadedEntryPoint(),),
                stderr=stderr,
            )

            self.assertEqual(code, 2)
            self.assertEqual(
                stderr.getvalue(), "asterion pathlight: request is invalid\n"
            )
            self.assertEqual(tuple(queue.iterdir()), ())

    def test_opik_observation_import_creates_only_nonexecuting_candidate(self) -> None:
        observation = ExternalObservation(
            "opik",
            _digest("connector"),
            "1.0.0",
            _digest("subject"),
            _digest("external-event"),
            "optimization-suggestion",
            {
                "change_sha256": _digest("change"),
                "scope_sha256": _digest("scope"),
                "success_criteria_sha256": _digest("success"),
                "stop_criteria_sha256": _digest("stop"),
                "budget_sha256": _digest("budget"),
                "status": "proposed",
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "pathlight-external-observation.json"
            write_private_file(
                source,
                json.dumps(
                    observation.to_mapping(), sort_keys=True, separators=(",", ":")
                ).encode(),
            )
            output = root / "imported"
            output.mkdir(mode=0o700)
            stdout = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "import",
                    "opik-observation",
                    "--observation-file",
                    str(source),
                    "--output-root",
                    str(output),
                ],
                entry_points=(FailIfLoadedEntryPoint(),),
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["execution_authorized"])
            self.assertEqual(result["network_operation_count"], 0)
            files = tuple(sorted(output.iterdir()))
            self.assertEqual(len(files), 2)
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
            )
            candidate = json.loads(
                next(
                    path for path in files if "proposal-candidate" in path.name
                ).read_text()
            )
            self.assertFalse(candidate["execution_authorized"])

    def test_diagnosis_show_and_proposal_list_are_provider_free_canonical_json(
        self,
    ) -> None:
        observed = Finding(
            "observed",
            _digest("subject"),
            (_digest("evaluation"),),
            (),
            "confirmed",
            _digest("observed"),
        )
        hypothesis = Finding(
            "hypothesis",
            _digest("subject"),
            (observed.finding_sha256,),
            (),
            "medium",
            _digest("hypothesis"),
        )
        proposal = Proposal(
            hypothesis.finding_sha256,
            _digest("change"),
            _digest("scope"),
            _digest("success"),
            _digest("stop"),
            _digest("budget"),
        )
        bundle = DiagnosisBundle.build(
            experiment_bundle_sha256s=(_digest("experiment"),),
            evaluation_sha256s=(_digest("evaluation"),),
            findings=(observed, hypothesis),
            proposals=(proposal,),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-diagnosis.json"
            write_diagnosis_bundle(bundle, path)
            outputs: list[str] = []
            for command in (("diagnosis", "show"), ("proposal", "list")):
                stdout = io.StringIO()
                code = main(
                    ["pathlight", *command, "--diagnosis-file", str(path)],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=stdout,
                )
                self.assertEqual(code, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(
                    stdout.getvalue(),
                    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                )
                outputs.append(stdout.getvalue())

        self.assertEqual(json.loads(outputs[0])["bundle_sha256"], bundle.bundle_sha256)
        self.assertEqual(
            json.loads(outputs[1])[0]["proposal_sha256"], proposal.proposal_sha256
        )

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
                        json.dumps(payload, sort_keys=True, separators=(",", ":"))
                        + "\n",
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
                "pathlight",
                "experiment",
                "show",
                "--experiment-file",
                "SENTINEL_PRIVATE_PATH_AND_PROMPT",
                "--experiment-sha256",
                "invalid",
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
                    "pathlight",
                    "experiment",
                    "show",
                    "--experiment-file",
                    "/private/pathlight-experiment.json",
                    "--experiment-sha256",
                    "0" * 64,
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
                    [
                        "trace",
                        "show",
                        "--evidence-file",
                        str(bundle),
                        "--trace-id",
                        TRACE_ID,
                    ],
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
                        payload["trace_id"]
                        if isinstance(payload, dict)
                        else payload[0]["sequence"],
                        expected,
                    )
                    self.assertEqual(
                        stdout.getvalue(),
                        json.dumps(payload, sort_keys=True, separators=(",", ":"))
                        + "\n",
                    )

    def test_trace_flow_is_provider_free_and_emits_canonical_mainline_json(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(
                bundle, (), pathlight_traces=(_rich_trace(),)
            )
            stdout = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "trace",
                    "flow",
                    "--evidence-file",
                    str(bundle),
                    "--trace-id",
                    "00000000-0000-4000-8000-000000000101",
                ],
                entry_points=(FailIfLoadedEntryPoint(),),
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            [item["kind"] for item in payload],
            ["context-frame", "model-call", "tool-call", "context-frame", "model-call"],
        )
        self.assertEqual(
            stdout.getvalue(),
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        )

    def test_trace_surfaces_expose_verified_request_structure_without_private_values(
        self,
    ) -> None:
        batch, trace = _verified_provider_request_fixture()
        self.assertEqual(batch.missing_evidence, ("model-request-boundary",))
        self.assertNotIn("model-request", batch.missing_evidence)
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(bundle, (), pathlight_traces=(trace,))
            outputs: dict[str, object] = {}
            for name, arguments in (
                ("list", ["trace", "list"]),
                (
                    "show",
                    ["trace", "show", "--trace-id", VERIFIED_TRACE_ID],
                ),
                (
                    "tail",
                    [
                        "trace",
                        "tail",
                        "--trace-id",
                        VERIFIED_TRACE_ID,
                        "--after-sequence",
                        "0",
                    ],
                ),
                (
                    "flow",
                    ["trace", "flow", "--trace-id", VERIFIED_TRACE_ID],
                ),
            ):
                stdout = io.StringIO()
                code = main(
                    ["pathlight", *arguments, "--evidence-file", str(bundle)],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=stdout,
                )
                self.assertEqual(code, 0)
                outputs[name] = json.loads(stdout.getvalue())

        listed = outputs["list"]
        assert isinstance(listed, list)
        self.assertEqual(listed[0]["trace_id"], VERIFIED_TRACE_ID)
        self.assertGreater(listed[0]["missing_evidence_count"], 0)
        self.assertNotIn("request_shape_sha256", listed[0])
        expected_requests = tuple(
            {
                "request_sha256": request.payload_sha256,
                "request_shape_sha256": request.shape_sha256,
                "payload_bytes": request.payload_bytes,
                "field_count": request.field_count,
                "leaf_count": request.leaf_count,
                "text_characters": request.text_characters,
                "private_reference_sha256": request.private_reference_sha256,
            }
            for request in batch.provider_requests
        )
        for surface in ("show", "tail", "flow"):
            rendered = json.dumps(outputs[surface], sort_keys=True)
            for expected in expected_requests:
                with self.subTest(surface=surface, request=expected["request_sha256"]):
                    for key, value in expected.items():
                        self.assertIn(json.dumps(key), rendered)
                        self.assertIn(json.dumps(value), rendered)
            self.assertIn("model-request-boundary", rendered)
            self.assertNotIn('"model-request"', rendered)
        all_public_bytes = json.dumps(outputs, sort_keys=True).encode("utf-8")
        for sentinel in PRIVATE_PROVIDER_REQUEST_SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel.encode("utf-8"), all_public_bytes)

    def test_trace_show_and_flow_localize_per_call_evidence_gaps(self) -> None:
        batch, trace = _per_call_missing_evidence_fixture()
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(bundle, (), pathlight_traces=(trace,))
            outputs: dict[str, object] = {}
            for name, arguments in (
                ("show", ["trace", "show", "--trace-id", VERIFIED_TRACE_ID]),
                ("flow", ["trace", "flow", "--trace-id", VERIFIED_TRACE_ID]),
            ):
                stdout = io.StringIO()
                code = main(
                    ["pathlight", *arguments, "--evidence-file", str(bundle)],
                    entry_points=(FailIfLoadedEntryPoint(),),
                    stdout=stdout,
                )
                self.assertEqual(code, 0)
                outputs[name] = json.loads(stdout.getvalue())

        expected_labels = {
            1: ("model-request-boundary",),
            2: ("model-request-boundary",),
            3: (
                "model-identity",
                "model-request-boundary",
                "model-response",
                "token-usage",
            ),
            4: ("model-request-boundary",),
        }
        model_events = [
            event
            for event in outputs["show"]["events"]
            if event["kind"] == "model-call" and event["status"] == "started"
        ]
        model_nodes = [
            node for node in outputs["flow"] if node["kind"] == "model-call"
        ]
        self.assertEqual(len(model_events), 4)
        self.assertEqual(len(model_nodes), 4)
        for surface, items in (("show", model_events), ("flow", model_nodes)):
            attributes_by_request = {
                item["attributes"]["request_index"]: item["attributes"]
                for item in items
            }
            self.assertEqual(
                {
                    index: tuple(attributes["missing_evidence_labels"])
                    for index, attributes in attributes_by_request.items()
                },
                expected_labels,
            )
            request_only = attributes_by_request[3]
            provider_request = batch.provider_requests[2]
            self.assertEqual(
                request_only["request_sha256"], provider_request.payload_sha256
            )
            self.assertEqual(
                request_only["request_shape_sha256"], provider_request.shape_sha256
            )
            for field in (
                "model_id",
                "response_sha256",
                "response_length",
                "input_tokens",
                "output_tokens",
            ):
                with self.subTest(surface=surface, field=field):
                    self.assertNotIn(field, request_only)
        rendered = json.dumps(outputs, sort_keys=True).encode()
        for sentinel in PRIVATE_PER_CALL_SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel.encode(), rendered)

    def test_trace_flow_rejects_nonprivate_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve() / "workflow-evidence.json"
            write_workflow_observation_bundle(
                bundle, (), pathlight_traces=(_rich_trace(),)
            )
            os.chmod(bundle, 0o640)
            stderr = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "trace",
                    "flow",
                    "--evidence-file",
                    str(bundle),
                    "--trace-id",
                    "00000000-0000-4000-8000-000000000101",
                ],
                stderr=stderr,
            )

        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")

    def test_metric_query_and_exact_evaluation_comparison_are_provider_free(
        self,
    ) -> None:
        first_contract, baseline = _evaluation(100)
        second_contract, candidate = _evaluation(125)
        self.assertEqual(first_contract, second_contract)
        with tempfile.TemporaryDirectory() as directory:
            evaluations = Path(directory).resolve() / "pathlight-evaluations.json"
            write_evaluation_bundle(
                evaluations, (baseline, candidate), (first_contract,)
            )
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
            self.assertEqual(
                json.loads(stdout.getvalue())[0]["metric_name"], "accuracy"
            )
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

    def test_metric_query_deduplicates_shared_contract_across_evaluation_files(
        self,
    ) -> None:
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


class TestPathlightOptimizationCli(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.file = self.root / "pathlight-optimization.json"
        self.bundle, _ = _optimization_bundle()
        write_optimization_bundle(self.file, self.bundle)
        self.history = self.bundle.histories[0].trial_history_sha256
        self.decision = self.bundle.decisions[0].decision_sha256
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_optimization_commands_are_provider_free_canonical_json(self) -> None:
        with patch("asterion.cli_pathlight._provider_should_not_load", create=True) as provider:
            for argv in (
                ["optimization", "history", "--optimization-file", str(self.file), "--history", self.history],
                ["optimization", "decision", "--optimization-file", str(self.file), "--decision", self.decision],
                ["optimization", "trials", "--optimization-file", str(self.file), "--history", self.history, "--variant-role", "candidate"],
            ):
                with self.subTest(argv=argv):
                    self.stdout.seek(0)
                    self.stdout.truncate(0)
                    self.assertEqual(main(["pathlight", *argv], stdout=self.stdout, stderr=self.stderr), 0)
                    payload = json.loads(self.stdout.getvalue())
                    self.assertEqual(
                        self.stdout.getvalue(),
                        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                    )
                    self.assertNotIn("SENTINEL", self.stdout.getvalue())
            provider.assert_not_called()

    def test_optimization_rejects_noncanonical_or_invalid_queries(self) -> None:
        wrong_name = self.root / "optimization.json"
        requests = (
            ["optimization", "history", "--optimization-file", str(wrong_name), "--history", self.history],
            ["optimization", "history", "--optimization-file", "pathlight-optimization.json", "--history", self.history],
            ["optimization", "history", "--optimization-file", str(self.file), "--history", "0" * 64],
            ["optimization", "trials", "--optimization-file", str(self.file), "--history", self.history, "--variant-role", "unknown"],
            ["optimization", "decision", "--optimization-file", str(self.file), "--decision", self.decision, "--extra"],
        )
        for argv in requests:
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                self.assertEqual(main(["pathlight", *argv], stderr=stderr), 2)
                self.assertEqual(stderr.getvalue(), "asterion pathlight: request is invalid\n")


if __name__ == "__main__":
    unittest.main()
