from __future__ import annotations

import unittest

from asterion.applications.prime.p7.mechanism_model import MechanismRule, MechanismSpec
from asterion.applications.prime.p7.model_search import search_model


class TestP7ModelSearch(unittest.TestCase):
    def _spec(self, *rules: MechanismRule) -> MechanismSpec:
        return MechanismSpec("ls20-9607627b", 0, 7, tuple(rules))

    def test_search_finds_verified_rule_path_and_emits_checked_expectations(self) -> None:
        spec = self._spec(
            MechanismRule(
                "ACTION1",
                effects=(
                    {"op": "set_state", "args": {"value": "WIN"}},
                ),
            )
        )

        result = search_model(
            spec,
            frame=((0,),),
            level=0,
            state="NOT_FINISHED",
            actions=("ACTION1",),
            target_level=1,
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.expanded_nodes, 1)
        self.assertEqual(len(result.plan), 1)
        self.assertEqual(result.plan[0].action, {"name": "ACTION1", "data": {}})
        self.assertEqual(result.plan[0].expect["state"], "WIN")
        self.assertTrue(result.plan[0].expect["frame_sha256"].startswith("sha256:"))
        self.assertEqual(result.start["state"], "NOT_FINISHED")

    def test_search_does_not_invent_unmodeled_actions(self) -> None:
        spec = self._spec(
            MechanismRule(
                "ACTION2",
                effects=(
                    {"op": "set_state", "args": {"value": "WIN"}},
                ),
            )
        )

        result = search_model(
            spec,
            frame=((0,),),
            level=0,
            state="NOT_FINISHED",
            actions=("ACTION1",),
            target_level=1,
        )

        self.assertEqual(result.status, "no-plan")
        self.assertEqual(result.plan, ())
        self.assertEqual(result.expanded_nodes, 1)

    def test_search_reports_budget_without_claiming_failure(self) -> None:
        spec = self._spec(
            MechanismRule(
                "ACTION1",
                effects=(
                    {"op": "toggle_cell", "args": {"x": 0, "y": 0, "values": [0, 1]}},
                ),
            )
        )

        result = search_model(
            spec,
            frame=((0,),),
            level=0,
            state="NOT_FINISHED",
            actions=("ACTION1",),
            target_level=1,
            max_nodes=1,
            max_depth=8,
        )

        self.assertEqual(result.status, "budget-exhausted")
        self.assertEqual(result.plan, ())
        self.assertEqual(result.expanded_nodes, 1)


if __name__ == "__main__":
    unittest.main()
