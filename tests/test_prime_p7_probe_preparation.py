"""Current actor probes distinguish preparation from stale prefix replay."""

from pathlib import Path

from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
from asterion.applications.prime.p7.game import ArcGameContract
from asterion.applications.prime.p7.solver import Solver
from tests.test_prime_p7_solver import P7SolverFixture


class _SelectionEngine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 2

    def __init__(self):
        self.calls = []
        self.selection_changes = False
        self.pixel = 0

    def observe(self):
        return {
            "available_actions": ["ACTION6"],
            "frame": [[[0, self.pixel]]],
            "levels_completed": int(len(self.calls) >= 2),
            "state": "NOT_FINISHED",
            "win_levels": 2,
        }

    def step(self, action, data=None):
        self.calls.append((action, data))
        if len(self.calls) >= 4 or (len(self.calls) == 3 and self.selection_changes):
            self.pixel = 1
        return self.observe()


class TestProbePreparation(P7SolverFixture):
    def setUp(self):
        super().setUp()
        self.engine = _SelectionEngine()
        self.broker = ArcBroker(engine=self.engine, game=ArcGameContract(self.engine.game_id, 2))
        self.broker.bind_history("run-1")
        for _ in range(2):
            self.broker.act((ArcAction("ACTION6", (("x", 1), ("y", 1))),))
        self.solver = Solver(
            broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id="run-1",
            attempt_id="attempt-1", event_sink=lambda k, p: self.events.append((k, p)),
        )
        self.revise()

    def click_plan(self, *, purpose="probe", change=True):
        context = self.solver.current_context()
        return {
            "plan_id": "current-probe", "start": context["observation_ref"],
            "workspace_revision": context["workspace_revision"],
            "goal": "Select the current object and test its transition",
            "purpose": purpose, "assumptions": [],
            "steps": [
                {"action": {"name": "ACTION6", "data": {"x": 1, "y": 1}},
                 "expect": {"cells": [{"x": 0, "y": 0, "value": 0}]}},
                {"action": {"name": "ACTION6", "data": {"x": 2, "y": 2}},
                 "expect": {"cells": [{"x": 1, "y": 0, "value": int(change)}]}},
            ],
        }

    def test_current_probe_can_select_without_a_fabricated_pixel_change(self):
        result = self.solver.execute_plan(self.click_plan())
        self.assertEqual(result["stop_reason"], "matched")
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(len(self.engine.calls), 4)

    def test_advance_or_nondistinguishing_probe_keeps_prefix_guard(self):
        for purpose, change in [("advance", True), ("probe", False)]:
            with self.subTest(purpose=purpose, change=change):
                plan = self.click_plan(purpose=purpose, change=change)
                plan["plan_id"] = purpose + str(change)
                result = self.solver.execute_plan(plan)
                self.assertEqual(result["stop_reason"], "prefix-action-reuse")
                self.assertEqual(result["applied_count"], 0)
        self.assertEqual(len(self.engine.calls), 2)

    def test_any_distinguishing_predicted_cell_grounds_reused_click(self):
        self.engine.selection_changes = True
        plan = self.click_plan()
        plan["steps"] = [plan["steps"][0]]
        plan["steps"][0]["expect"]["cells"].append({"x": 1, "y": 0, "value": 1})
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["stop_reason"], "matched")
        self.assertEqual(result["applied_count"], 1)

    def test_stale_current_reference_cannot_authorize_preparation(self):
        plan = self.click_plan()
        plan["start"]["sequence"] -= 1
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        self.assertEqual(len(self.engine.calls), 2)

    def test_broker_rejects_stale_or_nondistinguishing_preparation(self):
        plan = self.click_plan()
        native = self.solver._validate_plan(plan, self.solver.current_context())
        reference = plan["start"]
        grounding = self.solver._probe_preparation(plan, native, 0, reference)
        for field, value in [("run_id", "other-run"), ("level", 1),
                             ("sequence", 0), ("observation_sha256", "sha256:" + "a" * 64),
                             ("next_prediction", native[0])]:
            with self.subTest(field=field):
                changed = {**grounding, field: value}
                result = self.broker.act_checked([native[0]], probe_preparation=changed)
                self.assertEqual(result["stop_reason"], "prefix-action-reuse")
                self.assertEqual(result["applied_count"], 0)
        self.assertEqual(len(self.engine.calls), 2)
