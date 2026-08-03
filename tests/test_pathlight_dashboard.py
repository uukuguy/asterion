from __future__ import annotations

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from asterion.pathlight import (
    DashboardSnapshot,
    DiagnosisBundle,
    Finding,
    PathlightError,
    TraceEvent,
    TraceGraph,
    validate_dashboard_snapshot,
)
from asterion.workflow_evidence.storage import WorkflowObservationBundle
from asterion.pathlight.dashboard_server import (
    DashboardApplication,
    serve_dashboard,
    validate_dashboard_bind,
)
from tests.test_pathlight_cli import (
    PRIVATE_PROVIDER_REQUEST_SENTINELS,
    PUBLIC_PROVIDER_REQUEST_FIELDS,
    _verified_provider_request_fixture,
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


def _verified_request_workflow_bundle() -> WorkflowObservationBundle:
    _, trace = _verified_provider_request_fixture()
    from asterion.workflow_evidence.storage import (
        _canonical_digest,
        _projection_mapping,
    )

    bundle_sha256 = "2" * 64
    projection = _projection_mapping(bundle_sha256, (), (trace,))
    return WorkflowObservationBundle(
        records=(),
        pathlight_traces=(trace,),
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

    def test_snapshot_rejects_unresolved_diagnosis_lineage(self) -> None:
        def digest(value: str) -> str:
            return hashlib.sha256(value.encode()).hexdigest()

        evaluation_sha256 = digest("unresolved-evaluation")
        diagnosis = DiagnosisBundle.build(
            experiment_bundle_sha256s=(digest("unresolved-experiment"),),
            evaluation_sha256s=(evaluation_sha256,),
            findings=(
                Finding(
                    "observed",
                    digest("subject"),
                    (evaluation_sha256,),
                    (),
                    "confirmed",
                    digest("finding-code"),
                ),
            ),
            proposals=(),
        )

        with self.assertRaises(PathlightError):
            DashboardSnapshot.build(diagnosis_bundles=(diagnosis,))


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

    def test_packaged_interface_is_workflow_first_and_has_no_external_resources(
        self,
    ) -> None:
        app = DashboardApplication(self.snapshot)
        html_response = app.response("GET", "/")
        script_response = app.response("GET", "/app.js")
        style_response = app.response("GET", "/styles.css")

        self.assertEqual(html_response.status, 200)
        self.assertEqual(html_response.media_type, "text/html; charset=utf-8")
        self.assertEqual(script_response.media_type, "text/javascript; charset=utf-8")
        self.assertEqual(style_response.media_type, "text/css; charset=utf-8")
        html = html_response.body.decode()
        script = script_response.body.decode()
        style = style_response.body.decode()
        combined = html + script + style
        self.assertIn("Pathlight Dashboard", html)
        self.assertIn("ContextFrame", combined)
        self.assertIn("证据缺口", combined)
        self.assertIn("/api/pathlight/v1/snapshot", script)
        for forbidden in (
            "http://",
            "https://",
            "@import",
            "localStorage",
            "innerHTML",
            "eval(",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIn("prefers-reduced-motion", style)

    def test_snapshot_api_and_assets_show_safe_verified_request_metadata(self) -> None:
        batch, _ = _verified_provider_request_fixture()
        snapshot = DashboardSnapshot.build(
            workflow_bundles=(_verified_request_workflow_bundle(),)
        )
        app = DashboardApplication(snapshot)
        snapshot_mapping = snapshot.to_mapping()
        api_mapping = json.loads(app.response("GET", "/api/pathlight/v1/snapshot").body)
        assets = b"".join(
            app.response("GET", target).body
            for target in ("/", "/app.js", "/styles.css")
        )
        self.assertEqual(api_mapping, snapshot_mapping)
        self.assertIn(b"Object.entries(node.attributes)", assets)
        self.assertIn(b"Array.isArray(value)", assets)
        expected_values = tuple(
            value
            for request in batch.provider_requests
            for value in (
                request.payload_sha256,
                request.shape_sha256,
                request.payload_bytes,
                request.field_count,
                request.leaf_count,
                request.text_characters,
                request.private_reference_sha256,
            )
        )
        for name, public_mapping in (
            ("snapshot", snapshot_mapping),
            ("api", api_mapping),
        ):
            rendered = json.dumps(public_mapping, sort_keys=True)
            for field in PUBLIC_PROVIDER_REQUEST_FIELDS:
                with self.subTest(surface=name, field=field):
                    self.assertIn(json.dumps(field), rendered)
            for value in expected_values:
                with self.subTest(surface=name, value=value):
                    self.assertIn(json.dumps(value), rendered)
            self.assertIn("model-request-boundary", rendered)
            self.assertNotIn('"model-request"', rendered)
        public_bytes = json.dumps(snapshot_mapping, sort_keys=True).encode() + assets
        for sentinel in PRIVATE_PROVIDER_REQUEST_SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel.encode(), public_bytes)

    def test_static_assets_are_head_safe_and_unknown_assets_are_not_found(self) -> None:
        app = DashboardApplication(self.snapshot)
        for target in ("/", "/app.js", "/styles.css"):
            with self.subTest(target=target):
                get = app.response("GET", target)
                head = app.response("HEAD", target)
                self.assertEqual(head.status, 200)
                self.assertEqual(head.body, b"")
                self.assertEqual(head.headers["Content-Length"], str(len(get.body)))
        self.assertEqual(app.response("GET", "/favicon.ico").status, 404)

    def test_foreground_server_reports_bound_url_and_opens_browser_only_when_explicit(
        self,
    ) -> None:
        ready_urls: list[str] = []
        with (
            patch(
                "asterion.pathlight.dashboard_server.ThreadingHTTPServer"
            ) as server_type,
            patch("asterion.pathlight.dashboard_server.webbrowser.open") as browser,
        ):
            server_type.return_value.server_address = ("127.0.0.1", 4567)
            serve_dashboard(
                self.snapshot,
                host="127.0.0.1",
                port=0,
                on_ready=ready_urls.append,
            )
            handler = server_type.call_args.args[1]
            self.assertEqual(handler.version_string(handler), "Asterion-Pathlight")
            browser.assert_not_called()
            server_type.return_value.serve_forever.assert_called_once()
            server_type.return_value.server_close.assert_called_once()

        with (
            patch(
                "asterion.pathlight.dashboard_server.ThreadingHTTPServer"
            ) as server_type,
            patch("asterion.pathlight.dashboard_server.webbrowser.open") as browser,
        ):
            server_type.return_value.server_address = ("127.0.0.1", 4568)
            serve_dashboard(
                self.snapshot,
                host="127.0.0.1",
                port=0,
                open_browser=True,
            )
            browser.assert_called_once_with("http://127.0.0.1:4568/", new=2)

        self.assertEqual(ready_urls, ["http://127.0.0.1:4567/"])


if __name__ == "__main__":
    unittest.main()
