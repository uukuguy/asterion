"""Local synthetic checks for model-relative continuous consequences."""

import copy
import importlib
import inspect
import unittest

try:
    rollout_module = importlib.import_module("asterion.applications.prime.p7.rollout")
except ModuleNotFoundError:
    rollout_module = None


ACTION = {"name": "ACTION1", "data": {}}


class TestPrimeP7Rollout(unittest.TestCase):
    def setUp(self):
        self.api = getattr(rollout_module, "rollout", None)
        self.assertTrue(callable(self.api), "continuous rollout API is missing")

    @staticmethod
    def terminal(state):
        return state.get("terminal")

    def run_model(self, transition, *, initial=None, actions=None, **kwargs):
        return self.api(
            {"tick": 0} if initial is None else initial,
            [ACTION] if actions is None else actions,
            transition=transition,
            terminal=self.terminal,
            settled=lambda state: state.get("settled", False),
            **kwargs,
        )

    def test_single_input_continues_without_input_until_delayed_death(self):
        calls = []

        def transition(state, action):
            calls.append(action)
            state["tick"] += 1
            if state["tick"] == 3:
                state.update(terminal="dead", settled=True)
            return state

        result = self.run_model(transition, actions=[ACTION, ACTION])
        self.assertEqual(result["outcome"], "dead")
        self.assertEqual(calls, [ACTION, None, None])
        self.assertEqual(result["ticks"], 3)
        self.assertEqual([s["tick"] for s in result["states"]], [0, 1, 2, 3])
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["action_index"], 0)
        self.assertEqual(result["execution_authority"], "none")

    def test_unchanged_input_tick_can_start_later_autonomous_motion(self):
        result = self.api(
            {"tick": 0}, [ACTION],
            transition=lambda state, action: (
                state if action is not None else {"tick": state["tick"] + 1}
            ),
            terminal=lambda state: "dead" if state["tick"] >= 2 else None,
            settled=lambda state: False,
        )
        self.assertEqual(result["outcome"], "dead")
        self.assertEqual(result["ticks"], 3)
        self.assertEqual([s["tick"] for s in result["states"]], [0, 0, 1, 2])

    def test_settled_collision_and_goal_are_distinct(self):
        for outcome in ("settled", "collision", "goal"):
            with self.subTest(outcome=outcome):
                result = self.run_model(
                    lambda state, action: {
                        "tick": 1,
                        "settled": outcome == "settled",
                        "collision": outcome == "collision",
                        "terminal": "goal" if outcome == "goal" else None,
                    },
                    collision=lambda state: state.get("collision", False),
                )
                self.assertEqual(result["outcome"], outcome)

    def test_multiple_settled_actions_have_separate_tick_bounds(self):
        result = self.run_model(
            lambda state, action: {"tick": state["tick"] + 1, "settled": True},
            actions=[ACTION, ACTION],
            max_ticks_per_action=1,
        )
        self.assertEqual(result["outcome"], "settled")
        self.assertEqual(result["ticks"], 2)
        self.assertEqual([s["ticks"] for s in result["segments"]], [1, 1])

    def test_collision_preserves_unexpanded_suffix(self):
        result = self.run_model(
            lambda state, action: {"tick": 1, "collision": True},
            actions=[ACTION, ACTION], collision=lambda state: state["collision"],
        )
        self.assertEqual(result["outcome"], "collision")
        self.assertEqual(result["evaluated_actions"], 1)
        self.assertEqual(result["actions"], [ACTION, ACTION])

    def test_initial_terminal_does_not_execute_and_tick_bound_is_positive_integer(self):
        def must_not_execute(state, action):
            self.fail("terminal initial state must not execute")

        result = self.run_model(must_not_execute, initial={"terminal": "dead"})
        self.assertEqual(result["outcome"], "dead")
        self.assertEqual(result["ticks"], 0)
        self.assertEqual(result["evaluated_actions"], 0)
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.run_model(must_not_execute, max_ticks_per_action=limit)

    def test_unknown_decision_cycle_exception_and_tick_limit(self):
        cases = [
            (lambda state, action: {"terminal": "unknown"}, "terminal_unknown"),
            (lambda state, action: state, "state_cycle"),
            (lambda state, action: {"tick": state["tick"] + 1}, "tick_limit"),
        ]
        for transition, reason in cases:
            with self.subTest(reason=reason):
                result = self.run_model(transition, max_ticks_per_action=2)
                self.assertEqual(result["outcome"], "unknown")
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["limit"], 2)

        def broken(state, action):
            raise RuntimeError("private model contents")

        result = self.run_model(broken)
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["reason"], "transition_exception:RuntimeError")
        result = self.api(
            {}, [ACTION], transition=lambda state, action: {"changed": True},
            terminal=self.terminal, settled=lambda state: None,
        )
        self.assertEqual(result["reason"], "settled_unknown")

    def test_full_state_prevents_false_position_cycle(self):
        result = self.run_model(
            lambda state, action: {"tick": state["tick"] + 1, "position": 0},
            max_ticks_per_action=3,
        )
        self.assertEqual(result["reason"], "tick_limit")
        self.assertEqual(result["ticks"], 3)

    def test_callbacks_cannot_mutate_inputs_or_retained_states(self):
        initial = {"tick": 0, "nested": {"value": 1}}
        actions = [{"name": "ACTION1", "data": {"value": 1}}]
        saved = copy.deepcopy((initial, actions))

        def transition(state, action):
            state["nested"]["value"] = 2
            action["data"]["value"] = 2
            return {"tick": 1, "settled": True}

        def terminal(state):
            state.clear()
            return None

        result = self.api(
            initial, actions, transition=transition,
            terminal=terminal, settled=lambda state: state.get("settled", False),
        )
        self.assertEqual((initial, actions), saved)
        self.assertEqual(result["states"][0], initial)
        self.assertEqual(result["outcome"], "settled")

    def test_replay_cases_retains_counterexamples_and_unknown(self):
        cases = [
            {"sequence": 1, "initial_state": {}, "actions": [ACTION],
             "expected_outcome": "dead"},
            {"sequence": 2, "initial_state": {}, "actions": [ACTION],
             "expected_outcome": "goal"},
        ]
        result = rollout_module.replay_cases(
            cases,
            transition=lambda state, action: {"settled": True},
            terminal=self.terminal, settled=lambda state: True,
        )
        self.assertEqual(result["status"], "counterexample")
        self.assertEqual(len(result["backtests"]), 2)
        self.assertEqual(result["predictions"][0], {
            "sequence": 1, "expect": {"state": "NOT_FINISHED"},
        })
        unknown = rollout_module.replay_cases(
            cases, transition=lambda state, action: {"terminal": "unknown"},
            terminal=self.terminal, settled=lambda state: False,
        )
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(len(unknown["backtests"]), 2)
        self.assertEqual(unknown["predictions"], [])

    def test_replay_without_real_initial_state_is_unknown(self):
        result = rollout_module.replay_cases(
            [{"sequence": 1, "initial_state": None, "actions": [ACTION],
              "expected_outcome": "dead"}],
            transition=lambda state, action: {"terminal": "dead"},
            terminal=self.terminal, settled=lambda state: False,
        )
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["backtests"][0]["predicted_outcome"], "unknown")
        self.assertEqual(result["backtests"][0]["rollout"]["reason"], "missing_initial_state")
        self.assertEqual(result["predictions"], [])

    def test_terminal_initial_state_does_not_certify_replayed_action(self):
        for outcome in ("dead", "goal"):
            with self.subTest(outcome=outcome):
                result = rollout_module.replay_cases(
                    [{"sequence": 1, "initial_state": {"terminal": outcome},
                      "actions": [ACTION], "expected_outcome": outcome}],
                    transition=lambda state, action: state,
                    terminal=self.terminal, settled=lambda state: False,
                )
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["predictions"], [])
                backtest = result["backtests"][0]
                self.assertEqual(backtest["predicted_outcome"], "unknown")
                self.assertEqual(backtest["rollout"]["evaluated_actions"], 0)
                self.assertEqual(
                    backtest["rollout"]["reason"], "initial_terminal_no_transition",
                )

    def test_candidates_exclude_only_predicted_death_and_degrade_invalid_model(self):
        candidates = [
            [{"name": "ACTION1", "data": {"terminal": "dead"}}],
            [{"name": "ACTION1", "data": {"terminal": "unknown"}}],
            [{"name": "ACTION1", "data": {"terminal": "goal"}}],
        ]
        kwargs = dict(
            transition=lambda state, action: action["data"],
            terminal=self.terminal, settled=lambda state: False,
        )
        result = rollout_module.evaluate_candidates({}, candidates, **kwargs)
        self.assertEqual(result["predicted_dead"], [0])
        self.assertEqual(result["unknown"], [1])
        self.assertEqual(result["remaining"], [1, 2])
        degraded = rollout_module.evaluate_candidates(
            {}, candidates, backtest={"status": "counterexample"}, **kwargs,
        )
        self.assertEqual(degraded["predicted_dead"], [])
        self.assertEqual(degraded["unknown"], [0, 1, 2])
        self.assertEqual(degraded["remaining"], [0, 1, 2])
        self.assertEqual(degraded["evaluations"][0]["outcome"], "unknown")
        self.assertEqual(degraded["evaluations"][0]["rollout"]["outcome"], "dead")


class TestPrimeP7RolloutRisk(unittest.TestCase):
    def setUp(self):
        self.assertIn("risk_check", inspect.signature(rollout_module.rollout).parameters)

    @staticmethod
    def finding():
        return {
            "id": "pursuer-contact", "type": "conditional_fatal",
            "condition": {"when": "pursuer reaches resting actor"},
            "evidence": {"source": "declared synthetic mechanics"},
        }

    @staticmethod
    def model():
        return {
            "transition": lambda state, action: {"tick": state["tick"] + 1},
            "terminal": lambda state: None,
            "settled": lambda state: True,
        }

    def test_conditional_fatal_is_checked_before_accepting_settlement(self):
        order = []
        kwargs = self.model()
        kwargs["settled"] = lambda state: order.append("settled") or True

        def risk_check(before, after, action):
            order.append("risk")
            return [self.finding()]

        result = rollout_module.rollout(
            {"tick": 0}, [ACTION], risk_check=risk_check, **kwargs,
        )
        self.assertEqual(order, ["risk", "settled"])
        self.assertEqual(result["outcome"], "settled")
        self.assertEqual(result["risk"]["status"], "conditional_fatal")
        self.assertEqual(result["risk"]["findings"], [self.finding()])

    def test_default_exception_and_invalid_checker_are_unassessed(self):
        def broken(before, after, action):
            raise ValueError("private checker payload")

        for checker in (None, broken, lambda before, after, action: [{"safe": True}]):
            with self.subTest(checker=checker):
                result = rollout_module.rollout(
                    {"tick": 0}, [ACTION], risk_check=checker, **self.model(),
                )
                risk = result["risk"]
                self.assertEqual(result["outcome"], "settled")
                self.assertEqual(risk["status"], "unassessed")
                self.assertEqual(risk["coverage"]["unassessed_ticks"], 1)
                self.assertNotIn("private checker payload", str(risk))

    def test_empty_findings_are_scoped_coverage_and_unknown_remains_partial(self):
        kwargs = self.model()
        kwargs["risk_check"] = lambda before, after, action: []
        complete = rollout_module.rollout({"tick": 0}, [ACTION], **kwargs)
        self.assertEqual(complete["risk"]["status"], "no_identified_fatal")
        self.assertEqual(complete["risk"]["coverage"]["evaluated_ticks"], 1)
        self.assertFalse(complete["risk"]["coverage"]["partial"])
        self.assertNotIn("safe", complete["risk"])
        kwargs["settled"] = lambda state: False
        partial = rollout_module.rollout(
            {"tick": 0}, [ACTION], max_ticks_per_action=1, **kwargs,
        )
        self.assertEqual(partial["risk"]["status"], "unassessed")
        self.assertTrue(partial["risk"]["coverage"]["partial"])

    def test_raw_death_warning_survives_unchecked_backtest(self):
        kwargs = self.model()
        kwargs["terminal"] = lambda state: "dead" if state["tick"] else None
        result = rollout_module.evaluate_candidates(
            {"tick": 0}, [[ACTION]], backtest={"status": "counterexample"},
            risk_check=lambda before, after, action: [], **kwargs,
        )
        evaluation = result["evaluations"][0]
        self.assertEqual(evaluation["outcome"], "unknown")
        self.assertEqual(evaluation["risk"]["status"], "predicted_death")
        self.assertEqual(evaluation["risk"]["findings"][0]["type"], "predicted_death")
        self.assertEqual(evaluation["model_confidence"]["backtest_status"], "counterexample")
        self.assertEqual(result["risk"]["status"], "predicted_death")
        self.assertEqual(result["remaining"], [0])

    def test_aggregate_findings_keep_candidate_provenance(self):
        finding = self.finding()
        result = rollout_module.evaluate_candidates(
            {"tick": 0}, [[ACTION], [ACTION]],
            risk_check=lambda before, after, action: [finding], **self.model(),
        )
        self.assertEqual([item["evidence"] for item in result["risk"]["findings"]], [
            {"candidate_index": 0, "evidence": finding["evidence"]},
            {"candidate_index": 1, "evidence": finding["evidence"]},
        ])
        self.assertEqual(result["evaluations"][0]["risk"]["findings"], [finding])

    def test_findings_survive_later_checker_failure(self):
        kwargs = self.model()
        kwargs["settled"] = lambda state: state["tick"] == 2

        def checker(before, after, action):
            if action is None:
                raise RuntimeError("model detail")
            return [self.finding()]

        result = rollout_module.rollout(
            {"tick": 0}, [ACTION], risk_check=checker, **kwargs,
        )
        self.assertEqual(result["risk"]["status"], "conditional_fatal")
        self.assertEqual(result["risk"]["findings"], [self.finding()])
        self.assertEqual(result["risk"]["coverage"]["evaluated_ticks"], 1)
        self.assertEqual(result["risk"]["coverage"]["unassessed_ticks"], 1)
        self.assertEqual(result["risk"]["coverage"]["errors"], [
            {"tick": 2, "reason": "risk_check_exception:RuntimeError"},
        ])

    def test_checker_inputs_and_returned_findings_are_copied(self):
        initial = {"tick": 0}
        actions = copy.deepcopy([ACTION])
        finding = self.finding()

        def checker(before, after, action):
            before.clear()
            after.clear()
            action["data"]["mutated"] = True
            return [finding]

        result = rollout_module.rollout(
            initial, actions, risk_check=checker, **self.model(),
        )
        finding["condition"].clear()
        self.assertEqual(initial, {"tick": 0})
        self.assertEqual(actions, [ACTION])
        self.assertEqual(result["states"], [{"tick": 0}, {"tick": 1}])
        self.assertEqual(result["risk"]["findings"], [self.finding()])


class TestPrimeP7RolloutCoverage(unittest.TestCase):
    @staticmethod
    def model():
        return {
            "transition": lambda state, action: {"settled": True},
            "terminal": lambda state: state.get("terminal"),
            "settled": lambda state: state.get("settled", False),
            "risk_check": lambda before, after, action: [],
        }

    @staticmethod
    def declared(actions):
        # Exercise the former silent fallback as well as the new declaration.
        if "supported_actions" in inspect.signature(rollout_module.rollout).parameters:
            return {"supported_actions": actions}
        return {}

    def test_unsupported_action_cannot_be_a_silently_settled_noop(self):
        calls = []
        kwargs = self.model()
        kwargs["transition"] = lambda state, action: calls.append(action) or {"settled": True}
        action = {"name": "ACTION7", "data": {}}
        result = rollout_module.rollout(
            {}, [action], **self.declared(["ACTION1"]), **kwargs,
        )
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["reason"], "unsupported_action")
        self.assertEqual(result["risk"]["status"], "unassessed")
        self.assertEqual(result["risk"]["coverage"]["action_coverage"], "unsupported")
        self.assertEqual(calls, [])
        self.assertEqual(result["evaluated_actions"], 0)
        self.assertEqual(result["states"], [{}])
        self.assertEqual(result["actions"], [action])

    def test_undeclared_actions_remain_unassessed_without_losing_raw_death(self):
        kwargs = self.model()
        result = rollout_module.rollout({}, [ACTION], **self.declared(None), **kwargs)
        self.assertEqual(result["risk"]["status"], "unassessed")
        self.assertEqual(result["outcome"], "settled")
        self.assertEqual(result["risk"]["coverage"]["action_coverage"], "undeclared")
        self.assertTrue(result["risk"]["coverage"]["partial"])
        self.assertEqual(result["ticks"], 1)
        kwargs["transition"] = lambda state, action: {"terminal": "dead"}
        dead = rollout_module.rollout({}, [ACTION], **self.declared(None), **kwargs)
        self.assertEqual(dead["outcome"], "dead")
        self.assertEqual(dead["risk"]["status"], "predicted_death")

    def test_unknown_contact_coverage_is_independent_of_settled_dynamics(self):
        kwargs = self.model()
        kwargs["risk_check"] = lambda before, after, action: {
            "findings": [], "coverage": "unknown",
            "reason": "contact consequence not modeled",
        }
        result = rollout_module.rollout({}, [ACTION], **kwargs)
        self.assertEqual(result["outcome"], "settled")
        self.assertEqual(result["risk"]["status"], "unassessed")
        self.assertEqual(result["risk"]["coverage"]["errors"], [{
            "tick": 1, "reason": "risk_coverage_unknown",
            "model_reason": "contact consequence not modeled",
        }])
        self.assertEqual(result["risk"]["coverage"]["evaluated_ticks"], 0)
        self.assertTrue(result["risk"]["coverage"]["partial"])

    def test_covered_envelope_preserves_full_trace_and_legacy_omission(self):
        kwargs = self.model()
        legacy = rollout_module.rollout({}, [ACTION], **kwargs)
        self.assertEqual(legacy["risk"]["status"], "no_identified_fatal")
        kwargs["risk_check"] = lambda before, after, action: {
            "findings": [], "coverage": "covered", "reason": "declared local scope",
        }
        result = rollout_module.rollout(
            {}, [ACTION], supported_actions=("ACTION1",), **kwargs,
        )
        self.assertEqual(result["risk"]["status"], "no_identified_fatal")
        self.assertEqual(result["states"], [{}, {"settled": True}])
        self.assertFalse(result["risk"]["coverage"]["partial"])

    def test_unknown_or_invalid_envelope_does_not_erase_fatal_findings(self):
        finding = TestPrimeP7RolloutRisk.finding()
        for coverage in ("unknown", "invalid"):
            with self.subTest(coverage=coverage):
                kwargs = self.model()
                kwargs["risk_check"] = lambda before, after, action: {
                    "findings": [finding], "coverage": coverage,
                    "reason": "unmodeled contact",
                }
                result = rollout_module.rollout({}, [ACTION], **kwargs)
                self.assertEqual(result["risk"]["status"], "conditional_fatal")
                self.assertEqual(result["risk"]["findings"], [finding])
                self.assertTrue(result["risk"]["coverage"]["partial"])

    def test_candidate_and_replay_forward_action_coverage(self):
        action = {"name": "ACTION7", "data": {}}
        result = rollout_module.evaluate_candidates(
            {}, [[ACTION], [action]], supported_actions=["ACTION1"], **self.model(),
        )
        self.assertEqual(result["unknown"], [1])
        self.assertEqual(result["remaining"], [0, 1])
        self.assertEqual(result["risk"]["coverage"]["action_coverage"], "unsupported")
        replay = rollout_module.replay_cases(
            [{"sequence": 26, "initial_state": {}, "actions": [action],
              "expected_outcome": "dead"}],
            supported_actions=["ACTION1"], **self.model(),
        )
        self.assertEqual(replay["status"], "unknown")
        self.assertEqual(replay["predictions"], [])

    def test_unsupported_suffix_preserves_prefix_fatal_finding(self):
        kwargs = self.model()
        finding = TestPrimeP7RolloutRisk.finding()
        kwargs["risk_check"] = lambda before, after, action: [finding]
        result = rollout_module.rollout(
            {}, [ACTION, {"name": "ACTION7", "data": {}}],
            supported_actions=["ACTION1"], **kwargs,
        )
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["evaluated_actions"], 1)
        self.assertEqual(result["ticks"], 1)
        self.assertEqual(result["risk"]["status"], "conditional_fatal")
        self.assertEqual(result["risk"]["findings"], [finding])


if __name__ == "__main__":
    unittest.main()
