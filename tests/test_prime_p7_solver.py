"""Application research and sequential broker boundaries, provider free."""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.score import canonical_bytes
from asterion.applications.prime.p7.solver import Solver
from tests.test_prime_p7_native_broker import _Engine


class _Kernel:
    generation = 1

    def __init__(self):
        self.exports = {}

    def export(self, name, value, kind="json"):
        eid = digest(
            {"name": name, "kind": kind, "value": value, "source_call_id": "cell-1"}
        )
        self.exports[eid] = SimpleNamespace(
            export_id=eid,
            name=name,
            kind=kind,
            value=copy.deepcopy(value),
            source_call_id="cell-1",
        )
        return eid

    def read_export(self, eid):
        return self.exports[eid]


class _Control:
    def __init__(self):
        self.state = "running"

    def poll(self, *args):
        return self.snapshot()

    def snapshot(self):
        return {"state": self.state}

    def action_allowed(self):
        return self.state == "running"

    def enter(self, operation):
        return self.action_allowed()

    def leave(self, operation):
        pass


def draft(source_ids=()):
    return {
        "worldmap": {
            "description_zh": "移动模型，目标待验证。",
            "state_summary": "位于起点",
            "rules": ["ACTION1 改变位置"],
            "unknowns": ["目标未知"],
            "competing_hypotheses": [],
        },
        "task": {
            "goal": "移动",
            "obstacles": [],
            "question": "移动规律？",
            "next_operation": "probe",
            "public_basis": "当前真实观察",
        },
        "model": {
            "source_export_ids": list(source_ids),
            "coverage": "局部",
            "assumptions": [],
        },
        "reports": [],
        "evidence_sequences": [0],
        "correction": {"changed": [], "retained": []},
    }


class P7SolverFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = _Engine()
        self.broker = ArcBroker(engine=self.engine)
        self.broker.bind_history("run-1")
        self.kernel, self.control, self.events = _Kernel(), _Control(), []
        self.solver = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=Path(self.directory.name),
            run_id="run-1",
            attempt_id="attempt-1",
            event_sink=lambda kind, payload: self.events.append((kind, payload)),
        )

    def plan(self, values=(1, 2, 3)):
        context = self.solver.current_context()
        return {
            "plan_id": "plan-1",
            "start": context["observation_ref"],
            "workspace_revision": context["workspace_revision"],
            "goal": "移动",
            "purpose": "probe",
            "assumptions": [],
            "steps": [
                {
                    "action": {"name": "ACTION1", "data": {}},
                    "expect": {
                        "cells": [{"x": 0, "y": 0, "value": value}],
                        "levels_completed": 0,
                    },
                }
                for value in values
            ],
        }


class TestP7Solver(P7SolverFixture):
    def test_mismatch_stops_suffix_and_duplicate_is_idempotent(self):
        plan = self.plan((1, 9, 3))
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(result["stop_reason"], "prediction-mismatch")
        self.assertEqual(len(result["unexecuted_steps"]), 1)
        self.assertEqual(result["feedback"][-1]["counterexample_sequence"], 2)
        self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertEqual(len(self.engine.calls), 2)
        plan["goal"] = "different"
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")

    def test_all_predictions_validate_before_first_action(self):
        plan = self.plan()
        plan["steps"][2]["expect"]["cells"][0]["x"] = 99
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        self.assertEqual(self.engine.calls, [])

    def test_stale_start_and_revision_fail_before_action(self):
        for field in ("start", "workspace_revision"):
            with self.subTest(field=field):
                plan = self.plan()
                if field == "start":
                    plan["start"]["sequence"] = 8
                else:
                    plan[field] = "revision-other"
                self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        self.assertEqual(self.engine.calls, [])

    def test_pause_and_level_advance_stop_suffix(self):
        original = self.broker.act_checked

        def action(plan):
            result = original(plan)
            self.control.state = "pause_requested"
            return result

        self.broker.act_checked = action
        result = self.solver.execute_plan(self.plan())
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["stop_reason"], "pause_requested")

    def test_multiple_cells_compare_host_evidence(self):
        plan = self.plan((1, 2))
        plan["steps"][0]["expect"]["cells"].append({"x": 1, "y": 0, "value": 9})
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["feedback"][0]["mismatch_kind"], "state")

    def test_unknown_dispatched_result_is_distinct_from_unexecuted_suffix(self):
        self.engine.raises_on = 2
        plan = self.plan()
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["uncertain_step_index"], 1)
        self.assertEqual(len(result["unexecuted_steps"]), 1)
        self.assertEqual(result["stop_reason"], "environment-result-unknown")
        self.assertIsNone(result["feedback"][-1]["actual"])
        self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertEqual(len(self.engine.calls), 2)
        other = self.plan()
        other["plan_id"] = "must-not-retry-unknown"
        self.assertEqual(self.solver.execute_plan(other)["status"], "rejected")

    def test_level_advance_stops_remaining_steps(self):
        self.engine.level_after = 1
        plan = self.plan()
        plan["steps"][0]["expect"]["levels_completed"] = 1
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["stop_reason"], "level-advanced")

    def test_public_calculation_events_pair_by_host_call_id(self):
        payload = {
            "call_id": "one",
            "generation": "generation-1",
            "execution_status": "ok",
            "elapsed_ms": 1,
        }
        self.solver.kernel_event("cell_started", payload)
        self.solver.kernel_event("cell_finished", payload)
        self.solver.kernel_event("cell_started", {**payload, "call_id": "two"})
        rows = [p for kind, p in self.events if kind == "compute_task"]
        self.assertEqual(rows[0]["task_id"], rows[1]["task_id"])
        self.assertNotEqual(rows[1]["task_id"], rows[2]["task_id"])

    def test_animation_projection_preserves_authoritative_ref_and_fits_actor_bridge(
        self,
    ):
        original = self.engine.observe

        def animated():
            value = original()
            value["frame"] = [
                [[len(self.engine.calls)] * 64 for _ in range(64)] for _ in range(24)
            ]
            return value

        self.engine.observe = animated
        self.broker = ArcBroker(engine=self.engine)
        self.broker.bind_history("animation-run")
        solver = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=Path(self.directory.name),
            run_id="animation-run",
            attempt_id="animation-attempt",
            event_sink=lambda *args: None,
        )
        context = solver.current_context()
        self.assertEqual(len(context["observation"]["frame"]), 1)
        self.assertEqual(
            context["observation_ref"]["observation_sha256"],
            digest(self.broker.observation_state().to_projection()),
        )
        self.assertLess(len(canonical_bytes(context)), 64 * 1024)

    def test_large_plan_feedback_preserves_suffix_and_marks_projection_omissions(self):
        plan = self.plan(tuple(range(1, 21)))
        cells = [{"x": x, "y": y, "value": 1} for y in range(2) for x in range(64)]
        for step in plan["steps"]:
            step["expect"]["cells"] = copy.deepcopy(cells)
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(len(result["unexecuted_steps"]), 19)
        self.assertTrue(result["projection_truncated"])
        self.assertEqual(result["unexecuted_steps"][0]["expect_cells_omitted"], 120)
        self.assertLess(len(canonical_bytes(result)), 64 * 1024)

    def test_final_win_keeps_terminal_events_with_valid_last_level(self):
        from tests.test_prime_p7_native_broker import _FullGameEngine
        from asterion.applications.prime.p7.game import P7GameSelection

        self.broker = ArcBroker(
            engine=_FullGameEngine(), game=P7GameSelection("ls20-9607627b", 0, 7)
        )
        self.broker.bind_history("final-run")
        solver = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=Path(self.directory.name),
            run_id="final-run",
            attempt_id="final-attempt",
            event_sink=lambda kind, payload: self.events.append((kind, payload)),
        )
        for level in range(1, 8):
            context = solver.current_context()
            result = solver.execute_plan(
                {
                    "plan_id": "level-" + str(level),
                    "start": context["observation_ref"],
                    "workspace_revision": context["workspace_revision"],
                    "goal": "推进",
                    "purpose": "advance",
                    "assumptions": [],
                    "steps": [
                        {
                            "action": {"name": "ACTION1", "data": {}},
                            "expect": {"levels_completed": level},
                        }
                    ],
                }
            )
        self.assertEqual(result["stop_reason"], "win")
        self.assertEqual(result["observation_ref"]["level"], 7)
        self.assertEqual(self.events[-1][1]["level"], 7)

    def test_kernel_recovery_requires_fresh_publication(self):
        plan = self.plan((1,))
        self.solver.kernel_recovered()
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        eid = self.kernel.export("draft", draft())
        published = self.solver.workspace(
            {
                "op": "publish",
                "base_revision": self.solver.current_context()["workspace_revision"],
                "draft_export_id": eid,
            }
        )
        self.assertEqual(published["status"], "published")
        self.assertEqual(self.solver.execute_plan(self.plan((1,)))["applied_count"], 1)
