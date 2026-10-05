from asterion.applications.prime.p7.research_bridge import ResearchReadServer
from asterion.applications.prime.p7.solver import Solver
from asterion.applications.prime.p7.score import canonical_bytes
from tests.test_prime_p7_solver import P7SolverFixture, draft


class TestP7Research(P7SolverFixture):
    def test_semantic_revision_rejects_stale_scope_or_claimed_program_authority(self):
        self.revise()
        self.solver.execute_plan(self.plan((1,)))
        value = draft()
        request = {
            "op": "revise",
            "base_revision": self.solver.current_context()["workspace_revision"],
            **{
                key: value[key]
                for key in ("worldmap", "task", "evidence_sequences", "correction")
            },
        }
        request["evidence_sequences"] = [1]
        for mutate in (
            lambda candidate: candidate.update(base_revision="sha256:" + "a" * 64),
            lambda candidate: candidate.update(evidence_sequences=[0]),
            lambda candidate: candidate.update(model={"source_export_ids": []}),
            lambda candidate: candidate.update(reports=[]),
        ):
            with self.subTest(mutate=mutate):
                from copy import deepcopy

                candidate = deepcopy(request)
                mutate(candidate)
                previous = self.solver.current_context()["workspace_revision"]
                self.assertEqual(self.solver.workspace(candidate)["status"], "rejected")
                self.assertEqual(
                    self.solver.current_context()["workspace_revision"], previous
                )
        self.assertEqual(len(self.engine.calls), 1)

    def test_semantic_revision_preserves_historical_checked_report_without_rechecking(
        self,
    ):
        self.revise()
        self.solver.execute_plan(self.plan((1, 2)))
        report_id = self.kernel.export(
            "checked-report",
            {
                "predictions": [
                    {
                        "sequence": sequence,
                        "expect": {"cells": [{"x": 0, "y": 0, "value": sequence}]},
                    }
                    for sequence in (1, 2)
                ]
            },
        )
        value = draft()
        value["evidence_sequences"] = [0, 1, 2]
        value["reports"] = [
            {
                "kind": "dynamics",
                "export_id": report_id,
                "evidence_sequences": [1, 2],
                "claim_status": "reported",
            }
        ]
        eid = self.kernel.export("checked-draft", value)
        published = self.solver.workspace(
            {
                "op": "publish",
                "base_revision": self.solver.current_context()["workspace_revision"],
                "draft_export_id": eid,
            }
        )
        self.assertEqual(published["reports"][0]["claim_status"], "checked")

        def forbidden_verification(*args):
            self.fail("semantic revise must not certify reports")

        self.solver._verify_report = forbidden_verification
        revised = self.revise()
        self.assertEqual(revised["status"], "revised")
        self.assertEqual(revised["model"], published["model"])
        self.assertEqual(revised["reports"], published["reports"])
        self.assertEqual(revised["parent_revision"], published["workspace_revision"])

    def test_large_worldmap_and_focus_return_bounded_projections(self):
        value = draft()
        value["worldmap"]["description_zh"] = "研究" * 4000
        for key in ("rules", "unknowns", "competing_hypotheses"):
            value["worldmap"][key] = ["规则" * 300] * 32
        eid = self.kernel.export("large-draft", value)
        result = self.solver.workspace(
            {
                "op": "publish",
                "base_revision": self.solver.current_context()["workspace_revision"],
                "draft_export_id": eid,
            }
        )
        self.assertEqual(result["status"], "published")
        self.assertTrue(result["projection_truncated"])
        self.assertLess(len(canonical_bytes(result)), 64 * 1024)
        historical = self.solver.workspace(
            {"op": "read", "revision": result["workspace_revision"]}
        )
        self.assertLess(len(canonical_bytes(historical)), 64 * 1024)
        focused = {**value["task"], "obstacles": ["🙂" * 600] * 32}
        result = self.solver.workspace({"op": "focus", "task": focused})
        self.assertEqual(result["status"], "focused")
        self.assertTrue(result["projection_truncated"])
        self.assertLess(len(canonical_bytes(result)), 64 * 1024)
        self.assertEqual(len(self.solver._active_task["obstacles"]), 32)

    def test_publish_is_snapshot_and_reports_cannot_self_certify(self):
        report = self.kernel.export("report", {"matches": 2})
        value = draft()
        value["reports"] = [
            {
                "kind": "dynamics",
                "export_id": report,
                "evidence_sequences": [0],
                "claim_status": "checked",
            }
        ]
        eid = self.kernel.export("draft", value)
        previous = self.solver.current_context()["workspace_revision"]
        result = self.solver.workspace(
            {"op": "publish", "base_revision": previous, "draft_export_id": eid}
        )
        self.assertEqual(result["status"], "published")
        self.kernel.exports[eid].value["worldmap"]["description_zh"] = "changed"
        current = self.solver.current_context()
        self.assertEqual(
            current["worldmap"]["description_zh"], value["worldmap"]["description_zh"]
        )
        self.assertEqual(current["reports"][0]["claim_status"], "unknown")
        current["worldmap"]["rules"].append("mutate")
        self.assertNotIn("mutate", self.solver.current_context()["worldmap"]["rules"])
        self.assertEqual(
            self.solver.workspace({"op": "read", "revision": previous})["worldmap"][
                "rules"
            ],
            [],
        )
        self.assertEqual(
            self.solver.workspace(
                {"op": "publish", "base_revision": previous, "draft_export_id": eid}
            )["status"],
            "rejected",
        )

    def test_checkpoint_includes_only_explicit_admitted_exports(self):
        source = self.kernel.export("model_source", "def step(x): return x+1", "text")
        value = draft((source,))
        eid = self.kernel.export("draft", value)
        self.solver.workspace(
            {
                "op": "publish",
                "base_revision": self.solver.current_context()["workspace_revision"],
                "draft_export_id": eid,
            }
        )
        state = self.kernel.export("state", {"x": 0})
        request = {
            "op": "checkpoint",
            "revision": self.solver.current_context()["workspace_revision"],
            "state_export_id": state,
            "analyzed_through": 0,
        }
        self.assertEqual(self.solver.workspace(request)["status"], "checkpointed")
        self.assertEqual(self.solver.checkpoint()["source_export_ids"], [source])
        self.assertEqual(self.solver.artifact(state), {"x": 0})
        unknown = self.kernel.export("unadmitted", {"x": 9})
        with self.assertRaises(ValueError):
            self.solver.artifact(unknown)
        reopened = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=self.solver._workspace.root.parent,
            run_id="run-1",
            attempt_id="attempt-1",
            event_sink=lambda *args: None,
        )
        self.assertEqual(
            reopened.current_context()["workspace_revision"], request["revision"]
        )
        self.assertEqual(reopened.checkpoint()["source_export_ids"], [source])
        self.assertEqual(reopened.artifact(state), {"x": 0})
        self.assertTrue(reopened.current_context()["requires_calibration"])

    def test_read_wire_rejects_action_and_returns_copies(self):
        server = ResearchReadServer(
            context=self.solver.current_context,
            history=self.broker.history,
            frame=self.broker.frame_at,
            artifact=self.solver.artifact,
        )
        self.addCleanup(server.close)
        for method in ("act", "act_checked", "execute_plan", "publish", "eval"):
            with self.subTest(method=method):
                self.assertEqual(
                    server.dispatch({"method": method, "args": [{}]})["status"],
                    "rejected",
                )
        result = server.dispatch({"method": "frame", "args": [0]})
        result["value"][0][0] = 9
        self.assertEqual(self.broker.frame_at(0)[0][0], 0)
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(
            server.dispatch({"method": "frame", "args": [999]})["status"], "rejected"
        )
        module = {}
        exec(server.start(), module)
        self.assertEqual(module["context"]()["observation_ref"]["sequence"], 0)
        self.assertEqual(module["frame"](0), [[0, 1]])
        with self.assertRaises(ValueError):
            module["_read"]("act_checked", [{}])
        self.assertEqual(self.engine.calls, [])

    def test_program_reports_compare_two_real_transitions_and_find_first_counterexample(
        self,
    ):
        self.revise()
        self.solver.execute_plan(self.plan((1, 2)))
        cases = [
            ("dynamics", [1, 2], "checked", None),
            ("dynamics", [8, 9], "counterexample", 1),
            ("projection", [1, 9], "counterexample", 2),
            ("goal", [1, 2], "unknown", None),
        ]
        for index, (kind, values, status, counterexample) in enumerate(cases):
            with self.subTest(kind=kind, status=status):
                report = self.kernel.export(
                    "report-" + str(index),
                    {
                        "predictions": [
                            {
                                "sequence": seq,
                                "expect": {"cells": [{"x": 0, "y": 0, "value": value}]},
                            }
                            for seq, value in enumerate(values, 1)
                        ]
                    },
                )
                value = draft()
                value["evidence_sequences"] = [0, 1, 2]
                value["reports"] = [
                    {
                        "kind": kind,
                        "export_id": report,
                        "evidence_sequences": [1, 2],
                        "claim_status": "checked",
                    }
                ]
                eid = self.kernel.export("draft-" + str(index), value)
                result = self.solver.workspace(
                    {
                        "op": "publish",
                        "base_revision": self.solver.current_context()[
                            "workspace_revision"
                        ],
                        "draft_export_id": eid,
                    }
                )
                self.assertEqual(result["status"], "published")
                validation = result["reports"][0]["validation"]
                self.assertEqual(validation["status"], status)
                self.assertEqual(
                    validation["first_counterexample_sequence"], counterexample
                )
                if status == "checked":
                    self.assertEqual(validation["checked_count"], 2)
        self.assertEqual(self.broker.frame_at(1), [[1, 1]])
