"""Bounded component coverage metadata for the pure hypothetical rollout."""

import unittest

from asterion.applications.prime.p7.rollout import evaluate_candidates, replay_cases, rollout


ACTION = {"name": "ACTION1", "data": {}}
FATAL = {
    "id": "declared-risk", "type": "conditional_fatal",
    "condition": "actor declared condition", "evidence": "actor declared evidence",
}


class TestPrimeP7RolloutGaps(unittest.TestCase):
    @staticmethod
    def model(**overrides):
        return {
            "transition": lambda state, action: {"tick": state["tick"] + 1},
            "terminal": lambda state: None,
            "settled": lambda state: True,
            "risk_check": lambda before, after, action: [],
            **overrides,
        }

    def run_model(self, *, initial=None, actions=None, **overrides):
        return rollout(
            {"tick": 0} if initial is None else initial,
            [ACTION] if actions is None else actions, **self.model(**overrides),
        )

    def assert_gap(self, result, kind, reason, phase="input", index=0, tick=1):
        self.assertIn({
            "kind": kind, "reason": reason, "phase": phase,
            "action_index": index, "tick": tick,
        }, result["risk"]["coverage"].get("gaps", []))

    def test_unknown_envelope_records_declared_category_without_semantic_inference(self):
        for category in (None, "input_unmodeled", "state_unmodeled", "contact_unmodeled", "view_boundary"):
            with self.subTest(category=category):
                envelope = {"findings": [], "coverage": "unknown", "reason": "private actor object narrative"}
                if category is not None:
                    envelope["gap_kind"] = category
                result = self.run_model(risk_check=lambda before, after, action: envelope)
                self.assertEqual(result["outcome"], "settled")
                self.assert_gap(result, category or "risk_unmodeled", "risk_coverage_unknown")
                self.assertEqual(result["risk"]["coverage"]["errors"], [{
                    "tick": 1, "reason": "risk_coverage_unknown",
                    "model_reason": envelope["reason"],
                }])
                self.assertNotIn(envelope["reason"], str(result["risk"]["coverage"]["gaps"]))

    def test_invalid_category_preserves_fatal_findings(self):
        for category in ("engine_fact", "model_unavailable", [], None):
            with self.subTest(category=category):
                result = self.run_model(risk_check=lambda before, after, action: {
                    "findings": [FATAL], "coverage": "unknown", "reason": "actor explanation",
                    "gap_kind": category,
                })
                self.assertEqual(result["risk"]["status"], "conditional_fatal")
                self.assert_gap(result, "risk_unmodeled", "risk_check_invalid")
                self.assertEqual(result["risk"]["coverage"]["evaluated_ticks"], 0)

    def test_checker_absence_failure_and_invalid_result_keep_error_compatibility(self):
        def broken(before, after, action):
            raise RuntimeError("private exception message")

        for checker, kind, reason in (
            (None, "risk_unmodeled", "risk_check_missing"),
            (broken, "computation_failure", "risk_check_exception:RuntimeError"),
            (lambda before, after, action: {}, "risk_unmodeled", "risk_check_invalid"),
        ):
            with self.subTest(reason=reason):
                result = self.run_model(risk_check=checker)
                self.assert_gap(result, kind, reason)
                self.assertNotIn("private exception message", str(result))
                if checker is None:
                    self.assertEqual(result["risk"]["coverage"]["errors"], [])

    def test_non_json_checker_payload_keeps_independently_valid_fatal_findings(self):
        for payload in (
            [FATAL, object()],
            {"findings": [FATAL], "coverage": "unknown", "reason": "actor claim", "gap_kind": object()},
        ):
            with self.subTest(payload=payload):
                result = self.run_model(risk_check=lambda before, after, action: payload)
                self.assertEqual(result["risk"]["status"], "conditional_fatal")
                self.assertEqual(result["risk"]["findings"], [FATAL])
                self.assertEqual(result["risk"]["coverage"]["unassessed_ticks"], 1)

    def test_invalid_and_failed_classifiers_do_not_lose_component_location(self):
        def broken(state):
            raise RuntimeError("private callback state")
        for callback in ("terminal", "settled", "collision"):
            for classifier, kind, suffix in (
                (lambda state: 7, "contact_unmodeled" if callback == "collision" else "state_unmodeled", "invalid"),
                (broken, "computation_failure", "exception:RuntimeError"),
            ):
                with self.subTest(callback=callback, suffix=suffix):
                    def delayed(state):
                        if state["tick"] == 2:
                            return classifier(state)
                        return None if callback == "terminal" else False
                    result = self.run_model(settled=lambda state: False, **{callback: delayed}) if callback != "settled" else self.run_model(settled=delayed)
                    self.assert_gap(result, kind, callback + "_" + suffix, "automatic", 0, 2)

    def test_classification_boundaries_record_initial_input_and_automatic_positions(self):
        for callback, kind, reason in (
            ("terminal", "state_unmodeled", "terminal_unknown"),
            ("settled", "state_unmodeled", "settled_unknown"),
            ("collision", "contact_unmodeled", "collision_unknown"),
        ):
            for target_tick, phase, index in ((0, "initial", None), (1, "input", 0), (2, "automatic", 0)):
                with self.subTest(callback=callback, target_tick=target_tick):
                    overrides = {"settled": lambda state: False}
                    def classify(state):
                        if state["tick"] == target_tick:
                            return "unknown" if callback == "terminal" else None
                        return None if callback == "terminal" else False
                    overrides[callback] = classify
                    result = self.run_model(actions=[] if target_tick == 0 else [ACTION], **overrides)
                    self.assert_gap(result, kind, reason, phase, index, target_tick)

    def test_unknown_classifier_preserves_unassessed_without_checker(self):
        result = self.run_model(terminal=lambda state: "unknown" if state["tick"] else None, risk_check=None)
        self.assert_gap(result, "state_unmodeled", "terminal_unknown")
        self.assert_gap(result, "risk_unmodeled", "risk_check_missing")

    def test_exceptions_invalid_states_and_limits_locate_the_stopped_tick(self):
        def broken_transition(state, action):
            if action is None:
                raise ValueError("private state details")
            return {"tick": 1}
        for transition, kind, reason in (
            (broken_transition, "computation_failure", "transition_exception:ValueError"),
            (lambda state, action: {"tick": 1} if action else object(), "computation_failure", "invalid_transition_state"),
            (lambda state, action: state, "continuation_limit", "state_cycle"),
            (lambda state, action: {"tick": state["tick"] + 1}, "continuation_limit", "tick_limit"),
        ):
            with self.subTest(reason=reason):
                result = self.run_model(transition=transition, settled=lambda state: False, max_ticks_per_action=2)
                self.assert_gap(result, kind, reason, "automatic", 0, 2)
                self.assertEqual(result["reason"], reason)

    def test_invalid_initial_and_unsupported_suffix_do_not_add_fake_states(self):
        result = self.run_model(initial=object())
        self.assert_gap(result, "computation_failure", "invalid_initial_state", "initial", None, 0)
        self.assertEqual(result["states"], [])
        suffix = {"name": "ACTION7", "data": {}}
        result = self.run_model(actions=[ACTION, suffix], supported_actions=["ACTION1"])
        self.assert_gap(result, "input_unmodeled", "unsupported_action", "input", 1, 1)
        self.assertEqual(result["states"], [{"tick": 0}, {"tick": 1}])
        undeclared = self.run_model(supported_actions=None)
        self.assert_gap(undeclared, "input_unmodeled", "action_coverage_undeclared", "initial", None, 0)

    def test_gaps_are_bounded_while_raw_trace_and_counts_are_complete(self):
        result = self.run_model(
            settled=lambda state: state["tick"] == 40,
            risk_check=lambda before, after, action: {
                "findings": [], "coverage": "unknown", "reason": "actor uncertainty",
            }, max_ticks_per_action=40,
        )
        coverage = result["risk"]["coverage"]
        self.assertEqual(len(coverage.get("gaps", [])), 32)
        self.assertEqual(coverage.get("gaps_omitted"), 8)
        self.assertEqual(len(result["states"]), 41)
        self.assertEqual(coverage["unassessed_ticks"], 40)
        self.assertEqual(len(coverage["errors"]), 40)

    def test_candidate_aggregate_keeps_bounded_gaps_and_local_positions(self):
        result = evaluate_candidates(
            {"tick": 0}, [[ACTION]] * 40, **self.model(risk_check=None),
        )
        coverage = result["risk"]["coverage"]
        self.assertEqual(len(coverage.get("gaps", [])), 32)
        self.assertEqual(coverage.get("gaps_omitted"), 8)
        self.assertTrue(all(gap["tick"] == 1 and gap["action_index"] == 0 for gap in coverage["gaps"]))

    def test_replay_gaps_explain_missing_state_and_unexecuted_initial_terminal(self):
        for state, kind, reason, phase, index in (
            (None, "state_unmodeled", "missing_initial_state", "initial", None),
            ({"terminal": "dead"}, "input_unmodeled", "initial_terminal_no_transition", "input", 0),
        ):
            with self.subTest(reason=reason):
                result = replay_cases([
                    {"sequence": 1, "initial_state": state, "actions": [ACTION], "expected_outcome": "dead"},
                ], **self.model(terminal=lambda state: state.get("terminal")))
                self.assert_gap(result["backtests"][0]["rollout"], kind, reason, phase, index, 0)

    def test_covered_legacy_and_envelope_have_no_gaps(self):
        for checker in (
            lambda before, after, action: [],
            lambda before, after, action: {"findings": [], "coverage": "covered", "reason": "declared", "gap_kind": "view_boundary"},
        ):
            with self.subTest(checker=checker):
                result = self.run_model(risk_check=checker)
                self.assertEqual(result["risk"]["coverage"].get("gaps"), [])
                self.assertEqual(result["risk"]["status"], "no_identified_fatal")


if __name__ == "__main__":
    unittest.main()
