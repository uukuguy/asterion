from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections.abc import ItemsView, Iterator, Mapping
from pathlib import Path
from typing import cast

from asterion.pathlight import (
    EvaluationRecord,
    MetricContract,
    MetricFilter,
    PathlightCatalog,
    PathlightError,
    TraceEvent,
    TraceFilter,
    TraceGraph,
)
from asterion.workflow_evidence import (
    WorkflowObservationBundle,
    read_workflow_observation_bundle,
    validate_workflow_observation_bundle,
    write_workflow_observation_bundle,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _opaque_id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


TRACE_A = _opaque_id(1)
TRACE_B = _opaque_id(2)
SENTINEL_MAPPING_ERROR = "SENTINEL_PRIVATE_MAPPING_ERROR"
METRIC_CONTRACT = MetricContract("accuracy", "ratio", True, "1.0.0")


class _HostileMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        del key
        raise RuntimeError(SENTINEL_MAPPING_ERROR)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError(SENTINEL_MAPPING_ERROR)

    def __len__(self) -> int:
        raise RuntimeError(SENTINEL_MAPPING_ERROR)

    def items(self) -> ItemsView[str, object]:
        raise RuntimeError(SENTINEL_MAPPING_ERROR)


def _trace(trace_id: str, *, status: str, component: str) -> dict[str, object]:
    root = _opaque_id(100 if trace_id == TRACE_A else 200)
    child = _opaque_id(101 if trace_id == TRACE_A else 201)
    return TraceGraph.build(
        trace_id,
        (
            TraceEvent.start(
                trace_id,
                root,
                None,
                1,
                "task",
                attributes={"assembly_sha256": component},
                timestamp_ns=10,
            ),
            TraceEvent.start(
                trace_id,
                child,
                root,
                2,
                "runtime",
                attributes={"missing_evidence": True},
                timestamp_ns=20,
            ),
            TraceEvent.complete(
                trace_id,
                child,
                3,
                kind="runtime",
                timestamp_ns=30,
                attributes={"duration_ns": 10},
            ),
            TraceEvent.terminal(
                trace_id,
                root,
                4,
                status,
                timestamp_ns=40,
                attributes={"duration_ns": 30},
            ),
        ),
    ).to_mapping()


def _bundle(*traces: dict[str, object]):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory).resolve() / "workflow-evidence.json"
        write_workflow_observation_bundle(path, (), pathlight_traces=traces)
        return read_workflow_observation_bundle(path)


def _evaluation(
    *, trace: str, value: int | None, status: str = "observed"
) -> EvaluationRecord:
    return EvaluationRecord(
        trace_sha256=_digest(trace),
        metric_contract_sha256=METRIC_CONTRACT.metric_contract_sha256,
        dataset_snapshot_sha256=_digest("dataset"),
        scope_sha256=_digest("scope"),
        value_microunits=value,
        selected_count=2,
        total_count=3,
        status=status,  # type: ignore[arg-type]
    )


class PathlightQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.component_a = _digest("component-a")
        self.component_b = _digest("component-b")
        self.bundle_a = _bundle(
            _trace(TRACE_A, status="completed", component=self.component_a)
        )
        self.bundle_b = _bundle(
            _trace(TRACE_B, status="failed", component=self.component_b)
        )
        self.evaluation_a = _evaluation(trace="trace-a", value=100)
        self.evaluation_b = _evaluation(trace="trace-b", value=125)
        self.missing_evaluation = _evaluation(
            trace="trace-c", value=None, status="missing"
        )

    def test_list_show_and_tail_are_deterministic_and_safe(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_b, self.bundle_a), (), ())

        summaries = catalog.list_traces()

        self.assertEqual([row["trace_id"] for row in summaries], [TRACE_A, TRACE_B])
        self.assertEqual(
            [
                event["sequence"]
                for event in catalog.tail_trace(TRACE_A, after_sequence=1)
            ],
            [2, 3, 4],
        )
        rendered = json.dumps(catalog.show_trace(TRACE_A), sort_keys=True)
        self.assertNotIn("SENTINEL_PRIVATE", rendered)
        self.assertEqual(summaries[0]["event_count"], 4)
        self.assertEqual(summaries[0]["span_count"], 2)
        self.assertEqual(summaries[0]["missing_evidence_count"], 1)
        self.assertEqual(summaries[0]["component_sha256s"], (self.component_a,))

    def test_catalog_projections_are_deeply_immutable(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_a,), (self.evaluation_a,), (METRIC_CONTRACT,))
        trace = catalog.show_trace(TRACE_A)
        events = trace["events"]
        assert isinstance(trace, dict)
        assert isinstance(events, tuple)
        event = events[0]
        assert isinstance(event, dict)
        attributes = event["attributes"]
        summary = catalog.list_traces()[0]
        metric = catalog.query_metrics()[0]
        assert isinstance(attributes, dict)
        assert isinstance(summary, dict)
        assert isinstance(metric, dict)

        with self.assertRaises(TypeError):
            trace["trace_id"] = TRACE_B
        with self.assertRaises(TypeError):
            attributes["missing_evidence"] = False
        with self.assertRaises(TypeError):
            summary["event_count"] = 0
        with self.assertRaises(TypeError):
            metric["status"] = "missing"

    def test_return_value_mutation_cannot_change_catalog_internal_state(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_a,), (self.evaluation_a,), (METRIC_CONTRACT,))
        original_trace_sha256 = catalog.show_trace(TRACE_A)["trace_sha256"]
        returned_trace = catalog.show_trace(TRACE_A)
        returned_events = returned_trace["events"]
        returned_metric = catalog.query_metrics()[0]
        assert isinstance(returned_trace, dict)
        assert isinstance(returned_events, tuple)
        returned_event = returned_events[1]
        assert isinstance(returned_event, dict)
        returned_attributes = returned_event["attributes"]
        assert isinstance(returned_attributes, dict)
        assert isinstance(returned_metric, dict)

        dict.__setitem__(returned_trace, "trace_sha256", "0" * 64)
        dict.__setitem__(returned_attributes, "missing_evidence", False)
        dict.__setitem__(returned_metric, "status", "missing")

        next_trace = catalog.show_trace(TRACE_A)
        next_events = next_trace["events"]
        assert isinstance(next_events, tuple)
        next_event = next_events[1]
        assert isinstance(next_event, Mapping)
        next_attributes = next_event["attributes"]
        assert isinstance(next_attributes, Mapping)
        self.assertEqual(next_trace["trace_sha256"], original_trace_sha256)
        self.assertIs(next_attributes["missing_evidence"], True)
        self.assertEqual(catalog.query_metrics()[0]["status"], "observed")

    def test_direct_catalog_construction_validates_and_copies_inputs(self) -> None:
        trace = self.bundle_a.pathlight_traces[0]
        catalog = PathlightCatalog(
            {TRACE_A: trace},
            {self.evaluation_a.evaluation_sha256: self.evaluation_a},
            {METRIC_CONTRACT.metric_contract_sha256: METRIC_CONTRACT},
        )
        source_events = trace["events"]

        self.assertEqual(
            catalog.show_trace(TRACE_A)["trace_sha256"], trace["trace_sha256"]
        )
        self.assertEqual(
            catalog.query_metrics()[0]["evaluation_sha256"],
            self.evaluation_a.evaluation_sha256,
        )
        self.assertIsNot(catalog.show_trace(TRACE_A)["events"], source_events)
        with self.assertRaises(PathlightError):
            PathlightCatalog(
                {TRACE_A: {"sentinel": "SENTINEL_PRIVATE"}},
                {},
                {},
            )
        with self.assertRaises(PathlightError):
            PathlightCatalog(
                {},
                {self.evaluation_a.evaluation_sha256: {"sentinel": "SENTINEL_PRIVATE"}},
                {},
            )

    def test_catalog_revalidates_internal_digests_before_every_read(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_a,), (self.evaluation_a,), (METRIC_CONTRACT,))
        internal_trace = catalog._traces[TRACE_A]
        internal_evaluation = catalog._evaluations[self.evaluation_a.evaluation_sha256]
        dict.__setitem__(internal_trace, "trace_sha256", "0" * 64)  # type: ignore[arg-type]
        dict.__setitem__(internal_evaluation, "evaluation_sha256", "0" * 64)  # type: ignore[arg-type]

        for read in (
            lambda: catalog.show_trace(TRACE_A),
            lambda: catalog.tail_trace(TRACE_A),
            catalog.list_traces,
            catalog.query_metrics,
            lambda: catalog.compare_evaluation_ids(
                self.evaluation_a.evaluation_sha256,
                self.evaluation_a.evaluation_sha256,
            ),
        ):
            with self.subTest(read=read), self.assertRaises(PathlightError):
                read()

    def test_catalog_normalizes_hostile_mapping_failures_without_leaking_text(
        self,
    ) -> None:
        hostile = _HostileMapping()
        hostile_traces = cast(Mapping[str, Mapping[str, object]], hostile)
        hostile_evaluations = cast(
            Mapping[str, Mapping[str, object] | EvaluationRecord], hostile
        )
        calls = (
            lambda: PathlightCatalog(hostile_traces, {}, {}),
            lambda: PathlightCatalog({}, hostile_evaluations, {}),
            lambda: PathlightCatalog({TRACE_A: hostile}, {}, {}),
            lambda: PathlightCatalog(
                {}, {self.evaluation_a.evaluation_sha256: hostile}, {}
            ),
        )

        for call in calls:
            with self.subTest(call=call), self.assertRaises(PathlightError) as raised:
                call()
            self.assertNotIn(SENTINEL_MAPPING_ERROR, str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)

    def test_trace_filters_use_only_validated_public_values(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_a, self.bundle_b), (), ())

        self.assertEqual(
            [
                row["trace_id"]
                for row in catalog.list_traces(TraceFilter(status="failed"))
            ],
            [TRACE_B],
        )
        self.assertEqual(
            [
                row["trace_id"]
                for row in catalog.list_traces(TraceFilter(kind="runtime"))
            ],
            [TRACE_A, TRACE_B],
        )
        self.assertEqual(
            [
                row["trace_id"]
                for row in catalog.list_traces(
                    TraceFilter(component_sha256=self.component_a)
                )
            ],
            [TRACE_A],
        )

    def test_metric_query_and_comparison_use_exact_evaluation_ids(self) -> None:
        catalog = PathlightCatalog.build(
            (),
            (self.evaluation_b, self.missing_evaluation, self.evaluation_a),
            (METRIC_CONTRACT,),
        )

        self.assertEqual(
            [row["evaluation_sha256"] for row in catalog.query_metrics()],
            sorted(
                (
                    self.evaluation_a.evaluation_sha256,
                    self.evaluation_b.evaluation_sha256,
                    self.missing_evaluation.evaluation_sha256,
                )
            ),
        )
        self.assertEqual(
            [
                row["evaluation_sha256"]
                for row in catalog.query_metrics(MetricFilter(status="missing"))
            ],
            [self.missing_evaluation.evaluation_sha256],
        )
        comparison = catalog.compare_evaluation_ids(
            self.evaluation_a.evaluation_sha256, self.evaluation_b.evaluation_sha256
        )
        self.assertEqual(comparison["status"], "comparable")
        self.assertEqual(comparison["delta_microunits"], 25)
        self.assertEqual(json.loads(json.dumps(comparison))["reasons"], [])

    def test_metric_filter_requires_allowlisted_exact_metric_name(self) -> None:
        self.assertEqual(MetricFilter(metric_name="accuracy").metric_name, "accuracy")
        with self.assertRaises(PathlightError):
            MetricFilter(metric_name="SENTINEL_PRIVATE_METRIC")

    def test_catalog_rejects_duplicate_trace_or_evaluation_identity(self) -> None:
        with self.assertRaises(PathlightError):
            PathlightCatalog.build((self.bundle_a, self.bundle_a), (), ())
        with self.assertRaises(PathlightError):
            PathlightCatalog.build(
                (), (self.evaluation_a, self.evaluation_a), (METRIC_CONTRACT,)
            )

    def test_catalog_deduplicates_identical_metric_contract_identities(self) -> None:
        duplicate = MetricContract("accuracy", "ratio", True, "1.0.0")

        catalog = PathlightCatalog.build(
            (), (self.evaluation_a,), (METRIC_CONTRACT, duplicate)
        )

        self.assertEqual(
            catalog.query_metrics()[0]["metric_name"], METRIC_CONTRACT.metric_name
        )

    def test_catalog_rejects_tampered_contract_with_conflicting_digest(self) -> None:
        conflicting = MetricContract("accuracy", "ratio", True, "1.0.0")
        object.__setattr__(conflicting, "metric_name", "coverage")

        with self.assertRaises(PathlightError):
            PathlightCatalog.build(
                (), (self.evaluation_a,), (METRIC_CONTRACT, conflicting)
            )

    def test_catalog_rejects_unknown_identity_and_malformed_queries_without_type_errors(
        self,
    ) -> None:
        catalog = PathlightCatalog.build((self.bundle_a,), (self.evaluation_a,), (METRIC_CONTRACT,))

        for call in (
            lambda: catalog.show_trace("not-a-trace-id"),
            lambda: catalog.tail_trace(TRACE_A, after_sequence=True),
            lambda: catalog.tail_trace(TRACE_A, after_sequence=-1),
            lambda: catalog.list_traces(None),  # type: ignore[arg-type]
            lambda: catalog.list_traces(TraceFilter(status=[])),  # type: ignore[arg-type]
            lambda: catalog.list_traces(TraceFilter(kind="private-kind")),
            lambda: catalog.list_traces(TraceFilter(component_sha256="not-a-digest")),
            lambda: catalog.query_metrics(None),  # type: ignore[arg-type]
            lambda: catalog.query_metrics(MetricFilter(status={})),  # type: ignore[arg-type]
            lambda: catalog.query_metrics(MetricFilter(trace_sha256="not-a-digest")),
            lambda: catalog.compare_evaluation_ids(
                "not-a-digest", self.evaluation_a.evaluation_sha256
            ),
            lambda: catalog.compare_evaluation_ids(
                "0" * 64, self.evaluation_a.evaluation_sha256
            ),
        ):
            with self.subTest(call=call), self.assertRaises(PathlightError):
                call()

    def test_catalog_normalizes_tampered_typed_inputs_to_pathlight_errors(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_a,), (), ())
        tampered_filter = TraceFilter()
        object.__setattr__(tampered_filter, "status", [])
        invalid_bundle = object.__new__(WorkflowObservationBundle)
        object.__setattr__(invalid_bundle, "records", ())
        object.__setattr__(invalid_bundle, "pathlight_traces", ())
        object.__setattr__(invalid_bundle, "bundle_sha256", "0" * 64)
        object.__setattr__(invalid_bundle, "projection_sha256", "0" * 64)

        with self.assertRaises(PathlightError):
            catalog.list_traces(tampered_filter)
        with self.assertRaises(PathlightError):
            PathlightCatalog.build((invalid_bundle,), (), ())

    def test_build_authenticates_bundle_projection_before_consuming_traces(
        self,
    ) -> None:
        validate_workflow_observation_bundle(self.bundle_a)
        forged = object.__new__(WorkflowObservationBundle)
        for field_name in ("records", "pathlight_traces", "bundle_sha256"):
            object.__setattr__(forged, field_name, getattr(self.bundle_a, field_name))
        object.__setattr__(forged, "projection_sha256", "0" * 64)

        with self.assertRaises(PathlightError):
            PathlightCatalog.build((forged,), (), ())


if __name__ == "__main__":
    unittest.main()
