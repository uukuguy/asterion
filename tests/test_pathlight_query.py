from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from asterion.pathlight import (
    EvaluationRecord,
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
    write_workflow_observation_bundle,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _opaque_id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


TRACE_A = _opaque_id(1)
TRACE_B = _opaque_id(2)


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
        metric_contract_sha256=_digest("contract"),
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
        catalog = PathlightCatalog.build((self.bundle_b, self.bundle_a), ())

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
        catalog = PathlightCatalog.build((self.bundle_a,), (self.evaluation_a,))

        with self.assertRaises(TypeError):
            catalog.show_trace(TRACE_A)["trace_id"] = TRACE_B  # type: ignore[index]
        with self.assertRaises(TypeError):
            catalog.show_trace(TRACE_A)["events"][0]["attributes"][
                "missing_evidence"
            ] = False  # type: ignore[index]
        with self.assertRaises(TypeError):
            catalog.list_traces()[0]["event_count"] = 0  # type: ignore[index]
        with self.assertRaises(TypeError):
            catalog.query_metrics()[0]["status"] = "missing"  # type: ignore[index]

    def test_trace_filters_use_only_validated_public_values(self) -> None:
        catalog = PathlightCatalog.build((self.bundle_a, self.bundle_b), ())

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
            (), (self.evaluation_b, self.missing_evaluation, self.evaluation_a)
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

    def test_catalog_rejects_duplicate_trace_or_evaluation_identity(self) -> None:
        with self.assertRaises(PathlightError):
            PathlightCatalog.build((self.bundle_a, self.bundle_a), ())
        with self.assertRaises(PathlightError):
            PathlightCatalog.build((), (self.evaluation_a, self.evaluation_a))

    def test_catalog_rejects_unknown_identity_and_malformed_queries_without_type_errors(
        self,
    ) -> None:
        catalog = PathlightCatalog.build((self.bundle_a,), (self.evaluation_a,))

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
        catalog = PathlightCatalog.build((self.bundle_a,), ())
        tampered_filter = TraceFilter()
        object.__setattr__(tampered_filter, "status", [])
        invalid_bundle = WorkflowObservationBundle((), [], "0" * 64)  # type: ignore[arg-type]

        with self.assertRaises(PathlightError):
            catalog.list_traces(tampered_filter)
        with self.assertRaises(PathlightError):
            PathlightCatalog.build((invalid_bundle,), ())


if __name__ == "__main__":
    unittest.main()
