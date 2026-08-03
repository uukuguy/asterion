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
from asterion.pathlight.dashboard_server import (
    DashboardApplication,
    validate_dashboard_bind,
)


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


class PathlightDashboardApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = DashboardSnapshot.build(workflow_bundles=(_workflow_bundle(),))

    def test_api_is_read_only_safe_and_same_origin(self) -> None:
        app = DashboardApplication(self.snapshot)
        response = app.response("GET", "/api/pathlight/v1/snapshot")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.media_type, "application/json; charset=utf-8")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertEqual(json.loads(response.body), self.snapshot.to_mapping())
        self.assertEqual(app.response("POST", "/api/pathlight/v1/snapshot").status, 405)

    def test_api_routes_exact_trace_flow_and_head(self) -> None:
        app = DashboardApplication(self.snapshot)
        routes = {
            "/api/pathlight/v1/summary": dict(self.snapshot.summary),
            "/api/pathlight/v1/traces": self.snapshot.to_mapping()["traces"],
            f"/api/pathlight/v1/traces/{TRACE_ID}": self.snapshot.to_mapping()[
                "traces"
            ][0],
            f"/api/pathlight/v1/traces/{TRACE_ID}/flow": self.snapshot.to_mapping()[
                "flows"
            ][0],
            "/api/pathlight/v1/evaluations": [],
            "/api/pathlight/v1/experiments": [],
            "/api/pathlight/v1/diagnoses": [],
        }
        for target, expected in routes.items():
            with self.subTest(target=target):
                response = app.response("GET", target)
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.body), expected)
                head = app.response("HEAD", target)
                self.assertEqual(head.status, 200)
                self.assertEqual(head.body, b"")
                self.assertEqual(
                    head.headers["Content-Length"], str(len(response.body))
                )

    def test_api_rejects_unknown_or_malformed_targets_with_fixed_errors(self) -> None:
        app = DashboardApplication(self.snapshot)
        responses = (
            app.response("GET", "/api/pathlight/v1/traces/unknown"),
            app.response("GET", "/api/pathlight/v1/../snapshot"),
            app.response("GET", "/api/pathlight/v1/snapshot?secret=value"),
            app.response("OPTIONS", "/api/pathlight/v1/snapshot"),
        )
        self.assertEqual(
            [response.status for response in responses], [404, 404, 404, 405]
        )
        rendered = b"".join(response.body for response in responses)
        self.assertNotIn(b"unknown", rendered)
        self.assertNotIn(b"secret", rendered)

    def test_non_loopback_or_invalid_port_is_rejected(self) -> None:
        for host, port in (
            ("0.0.0.0", 8123),
            ("192.0.2.1", 8123),
            ("127.0.0.1", -1),
            ("127.0.0.1", 65536),
            ("127.0.0.1", True),
        ):
            with self.subTest(host=host, port=port), self.assertRaises(PathlightError):
                validate_dashboard_bind(host, port)
        self.assertEqual(validate_dashboard_bind("127.0.0.1", 0), ("127.0.0.1", 0))
        self.assertEqual(validate_dashboard_bind("::1", 8123), ("::1", 8123))
        self.assertEqual(
            validate_dashboard_bind("localhost", 8123), ("localhost", 8123)
        )


if __name__ == "__main__":
    unittest.main()
