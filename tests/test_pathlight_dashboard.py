from __future__ import annotations

import copy
import json
import unittest

from asterion.pathlight import (
    DashboardSnapshot,
    PathlightError,
    TraceEvent,
    TraceGraph,
    validate_dashboard_snapshot,
)
from asterion.workflow_evidence.storage import WorkflowObservationBundle


TRACE_ID = "00000000-0000-4000-8000-000000000101"
ROOT_SPAN_ID = "00000000-0000-4000-8000-000000000102"


def _trace() -> dict[str, object]:
    return TraceGraph.build(
        TRACE_ID,
        (
            TraceEvent.start(
                TRACE_ID,
                ROOT_SPAN_ID,
                None,
                1,
                "task",
                timestamp_ns=1,
            ),
            TraceEvent.terminal(
                TRACE_ID,
                ROOT_SPAN_ID,
                2,
                "completed",
                kind="task",
                timestamp_ns=2,
            ),
        ),
    ).to_mapping()


def _workflow_bundle() -> WorkflowObservationBundle:
    # WorkflowObservationBundle validates projection digests at construction, so
    # use its normal persisted projection shape through the public writer/reader
    # in CLI integration tests.  Snapshot unit tests need only a validated trace;
    # the bundle digest values below are reconstructed by the helper constructor.
    from asterion.workflow_evidence.storage import (
        _canonical_digest,
        _projection_mapping,
    )

    bundle_sha256 = "1" * 64
    projection = _projection_mapping(bundle_sha256, (), (_trace(),))
    return WorkflowObservationBundle(
        records=(),
        pathlight_traces=(_trace(),),
        bundle_sha256=bundle_sha256,
        projection_sha256=_canonical_digest(projection),
    )


class PathlightDashboardSnapshotTests(unittest.TestCase):
    def test_snapshot_is_deterministic_and_marks_missing_flow(self) -> None:
        first = DashboardSnapshot.build(workflow_bundles=(_workflow_bundle(),))
        second = DashboardSnapshot.build(workflow_bundles=(_workflow_bundle(),))

        self.assertEqual(first, second)
        mapping = first.to_mapping()
        self.assertEqual(mapping["schema"], "asterion.pathlight-dashboard-snapshot/v1")
        self.assertEqual(mapping["summary"]["trace_count"], 1)
        self.assertEqual(mapping["summary"]["evidence_gap_count"], 1)
        self.assertEqual(mapping["flows"][0]["nodes"], [])
        self.assertTrue(mapping["flows"][0]["missing_evidence"])
        self.assertEqual(validate_dashboard_snapshot(mapping), first)

    def test_snapshot_rejects_empty_duplicate_and_tampered_inputs(self) -> None:
        with self.assertRaises(PathlightError):
            DashboardSnapshot.build()
        with self.assertRaises(PathlightError):
            DashboardSnapshot.build(
                workflow_bundles=(_workflow_bundle(), _workflow_bundle())
            )

        mapping = DashboardSnapshot.build(
            workflow_bundles=(_workflow_bundle(),)
        ).to_mapping()
        tampered = copy.deepcopy(mapping)
        tampered["summary"]["trace_count"] = 2
        with self.assertRaises(PathlightError):
            validate_dashboard_snapshot(tampered)

    def test_snapshot_contains_no_content_or_private_path_fields(self) -> None:
        rendered = json.dumps(
            DashboardSnapshot.build(
                workflow_bundles=(_workflow_bundle(),)
            ).to_mapping(),
            sort_keys=True,
        )
        for forbidden in (
            "prompt",
            "answer",
            "payload",
            "credential",
            "private_path",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
