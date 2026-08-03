from __future__ import annotations

import hashlib
import json
import unittest

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
from asterion.pathlight.opik import map_opik_exports
from asterion.pathlight.protocol import (
    PathlightError,
    TraceEvent,
    TraceGraph,
    trace_graph_from_mapping,
)
from tests.test_pathlight_cli import (
    PRIVATE_PROVIDER_REQUEST_SENTINELS,
    PUBLIC_PROVIDER_REQUEST_FIELDS,
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
            item.to_mapping()["payload"]
            for item in envelopes
            if item.event_kind == "span.upsert"
            and item.to_mapping()["payload"]["kind"] == "model-call"
            and "request_sha256" in item.to_mapping()["payload"]
        )
        self.assertEqual(len(model_spans), len(batch.provider_requests))
        requests_by_index = {
            request.request_index: request for request in batch.provider_requests
        }
        for payload in model_spans:
            request = requests_by_index[payload["request_index"]]
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
