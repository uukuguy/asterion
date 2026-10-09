"""Literal screen assertions stop undispatched steps without predicting effects."""

import copy
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7 import prompt
from asterion.applications.prime.p7.score import canonical_bytes
from asterion.applications.prime.p7.solver import Solver
from tests.test_prime_p7_solver import P7SolverFixture


class TestP7ActionPreconditions(P7SolverFixture):
    def setUp(self):
        super().setUp()
        self.broker = ArcBroker(engine=self.engine, action_profile="autonomous")
        self.broker.bind_history("run-1")
        self.solver = Solver(
            broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id="run-1", attempt_id="attempt-1",
            event_sink=lambda kind, payload: self.events.append((kind, payload)),
            learner_profile="autonomous",
        )

    def step(self, before=None, expect=None):
        value = {"action": {"name": "ACTION1", "data": {}}}
        if before is not None:
            value["before"] = {"cells": [{"x": 0, "y": 0, "value": before}]}
        if expect is not None:
            value["expect"] = expect
        return value

    def submission(self, steps, name="plan-1", **options):
        return {"plan_id": name, "start": self.solver.current_context()["observation_ref"],
                "steps": steps, **options}

    def test_absent_before_preserves_unpredicted_execution(self):
        result = self.solver.execute_plan(self.submission([self.step()]))
        self.assertEqual(result["status"], "recorded")
        self.assertEqual((result["applied_count"], result["stop_reason"]), (1, "executed"))
        self.assertNotIn("precondition_feedback", result)

    def test_prompt_explains_optional_screen_assertions_and_separate_feedback(self):
        for text in (prompt.build_autonomous_prompt(), prompt.build_notes_prompt(), prompt.P7_SOLVE_PROMPT):
            with self.subTest(profile=text[:30]):
                self.assertIn("before:{cells:[{x,y,value}]}", text)
                self.assertIn("precondition_feedback", text)
                self.assertIn("模型坐标", text)
                self.assertIn("不保证动作后的安全", text)

    def test_initial_mismatch_returns_exact_observation_and_diff_without_cost(self):
        plan = self.submission([self.step(before=5), self.step()])
        initial_budget = self.solver.current_context()["budget"]
        original = copy.deepcopy(plan)
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual((result["applied_count"], result["stop_reason"]), (0, "precondition-mismatch"))
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(result["budget"]["primitive_actions"], initial_budget["primitive_actions"])
        self.assertEqual(result["feedback"], [])
        self.assertEqual(len(result["unexecuted_steps"]), 2)
        guard = result["precondition_feedback"][0]
        self.assertEqual((guard["step_index"], guard["status"]), (0, "mismatch"))
        self.assertEqual(guard["observation_ref"], plan["start"])
        self.assertEqual(guard["expected"], plan["steps"][0]["before"])
        self.assertEqual(guard["differences"], [{"field": "cell", "x": 0, "y": 0,
                                                  "expected": 5, "actual": 0}])
        self.assertNotIn("counterexample_sequence", guard)
        self.assertEqual(plan, original)

    def test_later_mismatch_uses_actual_settled_state_and_preserves_prefix(self):
        steps = [self.step(before=0), self.step(before=0), self.step()]
        result = self.solver.execute_plan(self.submission(steps, stop_on_mismatch=False))
        self.assertEqual(result["status"], "recorded")
        self.assertEqual((result["applied_count"], result["stop_reason"]), (1, "precondition-mismatch"))
        self.assertEqual(self.engine.calls, ["ACTION1"])
        self.assertEqual(result["budget"]["primitive_actions"], 1)
        self.assertEqual(len(result["feedback"]), 1)
        self.assertEqual(len(result["unexecuted_steps"]), 2)
        guards = result["precondition_feedback"]
        self.assertEqual([item["status"] for item in guards], ["matched", "mismatch"])
        self.assertEqual(guards[1]["observation_ref"], result["observation_ref"])
        self.assertEqual(guards[1]["differences"][0]["actual"], 1)

    def test_matching_guard_is_not_a_post_action_prediction(self):
        result = self.solver.execute_plan(self.submission([self.step(before=0)]))
        self.assertEqual(result["status"], "recorded")
        self.assertEqual((result["applied_count"], result["stop_reason"]), (1, "executed"))
        self.assertFalse(result["feedback"][0]["prediction_present"])
        self.assertEqual(result["feedback"][0]["mismatch_kind"], "unknown")
        self.assertEqual(result["precondition_feedback"][0]["status"], "matched")

    def test_screen_literals_reject_stale_mapping_then_match_changed_prefix(self):
        original_observe = self.engine.observe

        def observe():
            value = original_observe()
            value["frame"] = [[[5 if not self.engine.calls else 14, 1]]]
            return value

        self.engine.observe = observe
        self.broker = ArcBroker(engine=self.engine, action_profile="autonomous")
        self.broker.bind_history("run-1")
        self.solver.broker = self.broker
        stale = self.solver.execute_plan(self.submission([self.step(before=14)], name="stale-screen"))
        self.assertEqual((stale["applied_count"], stale["stop_reason"]), (0, "precondition-mismatch"))
        self.assertEqual(stale["precondition_feedback"][0]["differences"][0]["actual"], 5)
        self.assertEqual(self.engine.calls, [])
        matched = self.solver.execute_plan(self.submission([
            self.step(before=5), self.step(before=14)], name="settled-screen"))
        self.assertEqual((matched["applied_count"], matched["stop_reason"]), (2, "executed"))
        self.assertEqual([item["observation_ref"]["sequence"]
                          for item in matched["precondition_feedback"]], [0, 1])

    def test_maximal_valid_guards_keep_actor_projection_bounded(self):
        original_observe = self.engine.observe

        def observe():
            value = original_observe()
            value["frame"] = [[[0] * 64 for _ in range(2)]]
            return value

        self.engine.observe = observe
        self.broker = ArcBroker(engine=self.engine, action_profile="autonomous")
        self.broker.bind_history("run-1")
        self.solver.broker = self.broker
        step = self.step()
        step["before"] = {"cells": [{"x": x, "y": y, "value": 0}
                                     for y in range(2) for x in range(64)]}
        plan = self.submission([step] * 20)
        result = self.solver.execute_plan(plan)
        self.assertEqual((result["applied_count"], result["stop_reason"]), (20, "executed"))
        self.assertEqual(len(result["precondition_feedback"]), 20)
        self.assertLessEqual(len(canonical_bytes(result)), 60 * 1024)
        self.assertEqual(result["precondition_feedback"][0]["before_cells_omitted"], 120)
        self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertEqual(len(self.engine.calls), 20)

    def test_post_mismatch_policy_does_not_override_later_guard(self):
        result = self.solver.execute_plan(self.submission([
            self.step(before=0, expect={"cells": [{"x": 0, "y": 0, "value": 99}]}),
            self.step(before=0),
        ], stop_on_mismatch=False))
        self.assertEqual(result["status"], "recorded")
        self.assertEqual((result["applied_count"], result["stop_reason"]), (1, "precondition-mismatch"))
        self.assertEqual(result["feedback"][0]["counterexample_sequence"], 1)
        self.assertEqual(result["precondition_feedback"][-1]["differences"][0]["actual"], 1)

    def test_entire_guard_syntax_validates_before_first_action(self):
        cell = {"x": 0, "y": 0, "value": 0}
        for before in ({}, {"cells": []}, {"cells": [cell, cell]}, {"cells": [cell] * 129},
                       {"cells": [dict(cell, x=True)]}, {"cells": [dict(cell, value=256)]},
                       {"cells": [dict(cell, y=64)]}, {"cells": [dict(cell, extra=1)]},
                       {"cells": [cell], "state": "NOT_FINISHED"}, None, []):
            with self.subTest(before=before):
                tail = self.step()
                tail["before"] = before
                result = self.solver.execute_plan(self.submission([self.step(), tail]))
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(self.engine.calls, [])

    def test_plan_identity_includes_before_and_returns_cached_rejection(self):
        plan = self.submission([self.step(before=5)])
        first = self.solver.execute_plan(plan)
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(first["stop_reason"], "precondition-mismatch")
        self.assertEqual(self.solver.execute_plan(plan), first)
        changed = copy.deepcopy(plan)
        changed["steps"][0]["before"]["cells"][0]["value"] = 0
        self.assertEqual(self.solver.execute_plan(changed)["status"], "rejected")
        self.assertEqual(self.engine.calls, [])

    def test_pause_and_unknown_effect_controls_still_stop_suffix(self):
        self.control.state = "paused"
        paused = self.solver.execute_plan(self.submission([self.step(before=5)], name="paused"))
        self.assertEqual(paused["status"], "recorded")
        self.assertEqual((paused["applied_count"], paused["stop_reason"]), (0, "paused"))
        self.assertNotIn("precondition_feedback", paused)
        self.control.state = "running"
        self.engine.raises_on = 1
        unknown = self.solver.execute_plan(self.submission([
            self.step(before=0), self.step(before=1)], name="unknown"))
        self.assertEqual((unknown["applied_count"], unknown["stop_reason"]), (0, "environment-result-unknown"))
        self.assertEqual(len(unknown["precondition_feedback"]), 1)
        self.assertEqual(len(unknown["unexecuted_steps"]), 1)
        self.assertEqual(self.solver.execute_plan(self.submission([self.step(before=1)], name="after"))["status"], "rejected")

    def test_legacy_profile_accepts_optional_guard_after_revision(self):
        self.solver.learner_profile = "legacy"
        self.revise()
        plan = self.plan(values=(1,))
        plan["steps"][0]["before"] = {"cells": [{"x": 0, "y": 0, "value": 5}]}
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual((result["applied_count"], result["stop_reason"]), (0, "precondition-mismatch"))
        self.assertEqual(self.engine.calls, [])
