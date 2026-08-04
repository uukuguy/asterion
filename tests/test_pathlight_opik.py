from __future__ import annotations

import hashlib
import json
import unittest
from typing import cast

from asterion.pathlight.diagnosis import DiagnosisBundle, Finding, Proposal
from asterion.pathlight.evaluation import (
    EVALUATION_BUNDLE_SCHEMA,
    EvaluationBundle,
    EvaluationRecord,
    MetricContract,
)
from asterion.pathlight.experiment import (
    CaseTrial,
    DatasetSnapshot,
    EvaluatorContract,
    ExperimentBundle,
    ExperimentPlan,
    Variant,
)
from asterion.pathlight.optimization import (
    Decision,
    OptimizationBundle,
    OptimizationCriteria,
    OptimizationTrial,
    TrialHistory,
)
from asterion.pathlight.opik import map_opik_exports
import asterion.pathlight.opik as opik
from asterion.pathlight.protocol import (
    PathlightError,
    TraceEvent,
    TraceGraph,
    trace_graph_from_mapping,
)
from tests.test_pathlight_cli import (
    PRIVATE_PER_CALL_SENTINELS,
    PRIVATE_PROVIDER_REQUEST_SENTINELS,
    PUBLIC_PROVIDER_REQUEST_FIELDS,
    _per_call_missing_evidence_fixture,
    _verified_provider_request_fixture,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _opaque(value: int) -> str:
    return f"00000000-0000-4000-8000-{value:012x}"


def _fixture() -> tuple[
    TraceGraph, ExperimentBundle, EvaluationBundle, DiagnosisBundle
]:
    trace = TraceGraph.build(
        _opaque(1),
        (
            TraceEvent.start(
                _opaque(1),
                _opaque(2),
                None,
                1,
                "task",
                attributes={"component_id": _digest("component")},
                timestamp_ns=10,
            ),
            TraceEvent.start(
                _opaque(1),
                _opaque(3),
                _opaque(2),
                2,
                "tool-call",
                attributes={"content_sha256": _digest("SENTINEL_PRIVATE_TOOL_BODY")},
                timestamp_ns=20,
            ),
            TraceEvent.complete(
                _opaque(1),
                _opaque(3),
                3,
                kind="tool-call",
                attributes={"duration_ns": 10},
                timestamp_ns=30,
            ),
            TraceEvent.complete(
                _opaque(1),
                _opaque(2),
                4,
                attributes={"duration_ns": 30},
                timestamp_ns=40,
            ),
        ),
    )
    metric = MetricContract("ndcg-at-10", "ratio", True, "1.0.0")
    dataset = DatasetSnapshot(
        _digest("dataset-contract"), _digest("dataset"), 10, "1.0.0"
    )
    evaluator = EvaluatorContract(
        metric.metric_contract_sha256,
        "rule",
        _digest("evaluator"),
        _digest("input"),
        _digest("output"),
        _digest("failure"),
        "1.0.0",
    )
    variant = Variant(
        *(
            _digest(value)
            for value in (
                "assembly",
                "packages",
                "implementation",
                "runtime",
                "SENTINEL_PRIVATE_MODEL_NAME",
                "tools",
                "SENTINEL_PRIVATE_PROMPT",
                "policy",
                "change",
            )
        )
    )
    plan = ExperimentPlan(
        dataset.dataset_snapshot_sha256,
        _digest("scope"),
        variant.variant_sha256,
        (),
        _digest("assignment"),
        (evaluator.evaluator_contract_sha256,),
        _digest("budget"),
        _digest("stop"),
        _digest("authorization"),
    )
    trace_sha256 = trace.to_mapping()["trace_sha256"]
    assert isinstance(trace_sha256, str)
    evaluation = EvaluationRecord(
        trace_sha256,
        metric.metric_contract_sha256,
        dataset.dataset_snapshot_sha256,
        plan.scope_sha256,
        750_000,
        10,
        10,
        "observed",
    )
    trial = CaseTrial(
        plan.experiment_plan_sha256,
        _digest("case"),
        variant.variant_sha256,
        trace_sha256,
        (evaluation.evaluation_sha256,),
        "observed",
        (),
    )
    experiment = ExperimentBundle.build(
        datasets=(dataset,),
        evaluators=(evaluator,),
        variants=(variant,),
        plans=(plan,),
        trials=(trial,),
        evaluations=(evaluation,),
    )
    evaluation_document = {
        "schema": EVALUATION_BUNDLE_SCHEMA,
        "metric_contracts": [metric.to_mapping()],
        "evaluations": [evaluation.to_mapping()],
    }
    evaluations = EvaluationBundle(
        (metric,),
        (evaluation,),
        hashlib.sha256(
            json.dumps(
                evaluation_document, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    )
    observed = Finding(
        "observed",
        experiment.bundle_sha256,
        (evaluation.evaluation_sha256,),
        (),
        "confirmed",
        _digest("observed-code"),
    )
    finding = Finding(
        "hypothesis",
        experiment.bundle_sha256,
        (observed.finding_sha256,),
        (),
        "medium",
        _digest("finding-code"),
    )
    proposal = Proposal(
        finding.finding_sha256,
        _digest("proposal-change"),
        plan.scope_sha256,
        _digest("success"),
        _digest("proposal-stop"),
        _digest("proposal-budget"),
    )
    diagnosis = DiagnosisBundle.build(
        experiment_bundle_sha256s=(experiment.bundle_sha256,),
        evaluation_sha256s=(evaluation.evaluation_sha256,),
        findings=(observed, finding),
        proposals=(proposal,),
    )
    return trace, experiment, evaluations, diagnosis


def _optimization_fixture() -> tuple[
    tuple[TraceGraph, ...],
    ExperimentBundle,
    EvaluationBundle,
    DiagnosisBundle,
    OptimizationBundle,
]:
    traces = tuple(
        TraceGraph.build(
            _opaque(index),
            (
                TraceEvent.start(
                    _opaque(index), _opaque(index + 10), None, 1, "task", timestamp_ns=1
                ),
                TraceEvent.complete(
                    _opaque(index), _opaque(index + 10), 2, timestamp_ns=2
                ),
            ),
        )
        for index in (100, 200)
    )
    baseline_trace, candidate_trace = traces
    metric = MetricContract("ndcg-at-10", "ratio", True, "1.0.0")
    dataset = DatasetSnapshot(_digest("dataset-contract"), _digest("dataset"), 1, "1.0.0")
    evaluator = EvaluatorContract(
        metric.metric_contract_sha256,
        "rule",
        _digest("implementation"),
        _digest("input"),
        _digest("output"),
        _digest("failure"),
        "1.0.0",
    )
    baseline = Variant(*(_digest(f"baseline-{index}") for index in range(9)))
    candidate = Variant(*(_digest(f"candidate-{index}") for index in range(9)))
    plan = ExperimentPlan(
        dataset.dataset_snapshot_sha256,
        _digest("scope"),
        baseline.variant_sha256,
        (candidate.variant_sha256,),
        _digest("assignment"),
        (evaluator.evaluator_contract_sha256,),
        _digest("budget"),
        _digest("stop"),
        _digest("authorization"),
    )
    item = _digest("item")
    raw_trace_sha256s = tuple(
        trace.to_mapping()["trace_sha256"] for trace in traces
    )
    assert all(isinstance(value, str) for value in raw_trace_sha256s)
    trace_sha256s = cast(tuple[str, ...], raw_trace_sha256s)
    baseline_evaluation = EvaluationRecord(
        trace_sha256s[0], metric.metric_contract_sha256, dataset.dataset_snapshot_sha256,
        plan.scope_sha256, 400_000, 1, 1, "observed"
    )
    candidate_evaluation = EvaluationRecord(
        trace_sha256s[1], metric.metric_contract_sha256, dataset.dataset_snapshot_sha256,
        plan.scope_sha256, 500_000, 1, 1, "observed"
    )
    baseline_case = CaseTrial(
        plan.experiment_plan_sha256, item, baseline.variant_sha256, trace_sha256s[0],
        (baseline_evaluation.evaluation_sha256,), "observed", ()
    )
    candidate_case = CaseTrial(
        plan.experiment_plan_sha256, item, candidate.variant_sha256, trace_sha256s[1],
        (candidate_evaluation.evaluation_sha256,), "observed", ()
    )
    experiment = ExperimentBundle.build(
        datasets=(dataset,), evaluators=(evaluator,), variants=(baseline, candidate),
        plans=(plan,), trials=(baseline_case, candidate_case),
        evaluations=(baseline_evaluation, candidate_evaluation),
    )
    evaluations = tuple(sorted((baseline_evaluation, candidate_evaluation), key=lambda item: item.evaluation_sha256))
    evaluation_document = {
        "schema": EVALUATION_BUNDLE_SCHEMA,
        "metric_contracts": [metric.to_mapping()],
        "evaluations": [item.to_mapping() for item in evaluations],
    }
    evaluation_bundle = EvaluationBundle(
        (metric,), evaluations,
        hashlib.sha256(json.dumps(evaluation_document, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    )
    observed = Finding("observed", experiment.bundle_sha256, (baseline_evaluation.evaluation_sha256,), (), "confirmed", _digest("observed"))
    finding = Finding("hypothesis", experiment.bundle_sha256, (observed.finding_sha256,), (), "medium", _digest("finding"))
    proposal = Proposal(
        finding.finding_sha256, _digest("change"), plan.scope_sha256,
        _digest("proposal-success"), _digest("proposal-stop"), _digest("proposal-budget"),
    )
    diagnosis = DiagnosisBundle.build(
        experiment_bundle_sha256s=(experiment.bundle_sha256,),
        evaluation_sha256s=tuple(item.evaluation_sha256 for item in evaluations),
        findings=(observed, finding), proposals=(proposal,),
    )
    trials = (
        OptimizationTrial(plan.experiment_plan_sha256, baseline_case.case_trial_sha256, item, "baseline", baseline.variant_sha256, trace_sha256s[0], baseline_evaluation.evaluation_sha256, "completed", None, 100, 10, 20, 1_000),
        OptimizationTrial(plan.experiment_plan_sha256, candidate_case.case_trial_sha256, item, "candidate", candidate.variant_sha256, trace_sha256s[1], candidate_evaluation.evaluation_sha256, "completed", None, 120, 10, 20, 1_100),
    )
    history = TrialHistory.build(
        experiment_plan=plan, baseline_variant=baseline, candidate_variant=candidate,
        trials=trials, evaluations=evaluations, expected_dataset_item_sha256s=(item,),
    )
    decision = Decision.derive(
        proposal_sha256=proposal.proposal_sha256, finding_sha256=finding.finding_sha256,
        history=history, criteria=OptimizationCriteria(50_000, 250_000, 250_000),
        operator_approval_sha256=_digest("operator-approval"),
    )
    optimization = OptimizationBundle.build(
        experiment_bundle_sha256s=(experiment.bundle_sha256,),
        evaluation_bundle_sha256s=(evaluation_bundle.bundle_sha256,),
        diagnosis_bundle_sha256s=(diagnosis.bundle_sha256,),
        trace_sha256s=tuple(sorted(trace_sha256s)), trials=trials,
        histories=(history,), decisions=(decision,),
    )
    return traces, experiment, evaluation_bundle, diagnosis, optimization


class PathlightOpikMappingTests(unittest.TestCase):
    def test_mapping_links_safe_trace_experiment_trial_evaluation_and_proposal(
        self,
    ) -> None:
        trace, experiment, evaluations, diagnosis = _fixture()

        envelopes = map_opik_exports(
            traces=(trace,),
            experiments=(experiment,),
            evaluations=(evaluations,),
            diagnoses=(diagnosis,),
        )

        self.assertEqual(
            {item.event_kind for item in envelopes},
            {
                "trace.upsert",
                "span.upsert",
                "dataset.upsert",
                "experiment.upsert",
                "case-trial.upsert",
                "evaluation.upsert",
                "proposal.observe",
            },
        )
        self.assertEqual(
            tuple(item.envelope_sha256 for item in envelopes),
            tuple(sorted(item.envelope_sha256 for item in envelopes)),
        )
        encoded = json.dumps([item.to_mapping() for item in envelopes], sort_keys=True)
        for sentinel in (
            "SENTINEL_PRIVATE_TOOL_BODY",
            "SENTINEL_PRIVATE_MODEL_NAME",
            "SENTINEL_PRIVATE_PROMPT",
            "provider",
            "trace_id",
            "span_id",
        ):
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, encoded)

    def test_mapping_is_stable_and_deduplicates_evaluation_mirrors(self) -> None:
        trace, experiment, evaluations, diagnosis = _fixture()
        first = map_opik_exports(
            traces=(trace,),
            experiments=(experiment,),
            evaluations=(evaluations,),
            diagnoses=(diagnosis,),
        )
        second = map_opik_exports(
            traces=(trace,),
            experiments=(experiment,),
            evaluations=(evaluations,),
            diagnoses=(diagnosis,),
        )
        self.assertEqual(first, second)
        evaluation_ids = [
            item.local_object_sha256
            for item in first
            if item.event_kind == "evaluation.upsert"
        ]
        self.assertEqual(len(evaluation_ids), 1)

    def test_mapping_exports_closed_verified_request_metadata_without_private_values(
        self,
    ) -> None:
        batch, trace_mapping = _verified_provider_request_fixture()
        trace = trace_graph_from_mapping(trace_mapping)

        envelopes = map_opik_exports(traces=(trace,))

        model_spans = tuple(
            cast(dict[str, object], item.to_mapping()["payload"])
            for item in envelopes
            if item.event_kind == "span.upsert"
            and cast(dict[str, object], item.to_mapping()["payload"])["kind"]
            == "model-call"
            and "request_sha256"
            in cast(dict[str, object], item.to_mapping()["payload"])
        )
        self.assertEqual(len(model_spans), len(batch.provider_requests))
        requests_by_index = {
            request.request_index: request for request in batch.provider_requests
        }
        for payload in model_spans:
            request = requests_by_index[cast(int, payload["request_index"])]
            expected = {
                "request_sha256": request.payload_sha256,
                "request_shape_sha256": request.shape_sha256,
                "payload_bytes": request.payload_bytes,
                "field_count": request.field_count,
                "leaf_count": request.leaf_count,
                "text_characters": request.text_characters,
                "private_reference_sha256": request.private_reference_sha256,
            }
            for field in PUBLIC_PROVIDER_REQUEST_FIELDS:
                self.assertEqual(payload[field], expected[field])
            self.assertEqual(
                payload["missing_evidence_labels"], ["model-request-boundary"]
            )
        rendered = json.dumps(
            [item.to_mapping() for item in envelopes], sort_keys=True
        ).encode()
        self.assertNotIn(b'"model-request"', rendered)
        for sentinel in PRIVATE_PROVIDER_REQUEST_SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel.encode(), rendered)

    def test_mapping_localizes_per_call_evidence_gaps_without_private_values(
        self,
    ) -> None:
        batch, trace_mapping = _per_call_missing_evidence_fixture()
        trace = trace_graph_from_mapping(trace_mapping)

        envelopes = map_opik_exports(traces=(trace,))
        model_spans = tuple(
            cast(dict[str, object], item.to_mapping()["payload"])
            for item in envelopes
            if item.event_kind == "span.upsert"
            and cast(dict[str, object], item.to_mapping()["payload"])["kind"]
            == "model-call"
        )

        self.assertEqual(len(model_spans), 4)
        payloads_by_request = {
            payload["request_index"]: payload for payload in model_spans
        }
        self.assertEqual(
            {
                index: tuple(
                    cast(list[object], payload["missing_evidence_labels"])
                )
                for index, payload in payloads_by_request.items()
            },
            {
                1: ("model-request-boundary",),
                2: ("model-request-boundary",),
                3: (
                    "model-identity",
                    "model-request-boundary",
                    "model-response",
                    "token-usage",
                ),
                4: ("model-request-boundary",),
            },
        )
        request_only = payloads_by_request[3]
        self.assertEqual(
            request_only["request_sha256"], batch.provider_requests[2].payload_sha256
        )
        for field in (
            "model_id",
            "response_sha256",
            "response_length",
            "input_tokens",
            "output_tokens",
        ):
            self.assertNotIn(field, request_only)
        rendered = json.dumps(
            [item.to_mapping() for item in envelopes], sort_keys=True
        ).encode()
        for sentinel in PRIVATE_PER_CALL_SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel.encode(), rendered)

    def test_mapping_fails_closed_on_missing_diagnosis_or_trial_references(
        self,
    ) -> None:
        trace, experiment, evaluations, diagnosis = _fixture()
        with self.assertRaises(PathlightError):
            map_opik_exports(diagnoses=(diagnosis,))
        with self.assertRaises(PathlightError):
            map_opik_exports(experiments=(experiment,), evaluations=(evaluations,))
        self.assertTrue(trace.events)

    def test_mapping_rejects_unknown_mapping_version(self) -> None:
        trace, experiment, evaluations, diagnosis = _fixture()
        with self.assertRaises(PathlightError):
            map_opik_exports(
                traces=(trace,),
                experiments=(experiment,),
                evaluations=(evaluations,),
                diagnoses=(diagnosis,),
                mapping_version="2.0.0",
            )

    def test_mapping_emits_safe_history_and_decision_envelopes(self) -> None:
        traces, experiment, evaluations, diagnosis, optimization = _optimization_fixture()

        envelopes = map_opik_exports(
            traces=traces,
            experiments=(experiment,),
            evaluations=(evaluations,),
            diagnoses=(diagnosis,),
            optimizations=(optimization,),
        )

        payloads = {
            item.event_kind: cast(
                dict[str, object], item.to_mapping()["payload"]
            )
            for item in envelopes
            if item.event_kind in {"trial-history.upsert", "decision.observe"}
        }
        self.assertEqual(set(payloads), {"trial-history.upsert", "decision.observe"})
        self.assertEqual(
            set(payloads["trial-history.upsert"]),
            {
                "trial_history_sha256", "experiment_plan_sha256",
                "baseline_variant_sha256", "candidate_variant_sha256", "evidence_state",
                "success_criteria_sha256",
                "baseline_completed_count", "candidate_completed_count",
                "baseline_mean_microunits", "candidate_mean_microunits",
                "mean_gain_microunits", "baseline_agent_cost_microusd",
                "candidate_agent_cost_microusd", "cost_increase_microunits",
                "baseline_input_tokens", "candidate_input_tokens",
                "baseline_output_tokens", "candidate_output_tokens",
                "baseline_elapsed_ns", "candidate_elapsed_ns", "time_increase_microunits",
            },
        )
        self.assertEqual(
            set(payloads["decision.observe"]),
            {
                "decision_sha256", "trial_history_sha256", "proposal_sha256",
                "finding_sha256", "success_criteria_sha256",
                "operator_approval_sha256", "result", "reason",
            },
        )
        self.assertEqual(
            payloads["trial-history.upsert"]["success_criteria_sha256"],
            payloads["decision.observe"]["success_criteria_sha256"],
        )
        self.assertNotIn("SENTINEL", json.dumps([item.to_mapping() for item in envelopes]))

    def test_mapping_rejects_history_without_a_paired_decision(self) -> None:
        _, _, _, _, optimization = _optimization_fixture()
        incomplete = object.__new__(OptimizationBundle)
        object.__setattr__(incomplete, "histories", optimization.histories)
        object.__setattr__(incomplete, "decisions", ())

        with self.assertRaises(PathlightError):
            opik._optimization_envelopes(cast(OptimizationBundle, incomplete), "1.0.0")

    def test_mapping_rejects_missing_or_duplicate_optimization_closure(self) -> None:
        traces, experiment, evaluations, diagnosis, optimization = _optimization_fixture()
        with self.assertRaises(PathlightError):
            map_opik_exports(
                traces=traces, experiments=(experiment,), evaluations=(evaluations,),
                optimizations=(optimization,),
            )
        with self.assertRaises(PathlightError):
            map_opik_exports(
                traces=traces, experiments=(experiment,), evaluations=(evaluations,),
                diagnoses=(diagnosis,), optimizations=(optimization, optimization),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
