from __future__ import annotations

import unittest

from asterion.applications.prime.p7.mechanism_model import (
    MechanismRule,
    MechanismSpec,
    history_prefix_digest,
    validate_mechanism,
)
from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.verified_history import ArcHistoryRecord
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

    def test_search_rejects_certificate_when_world_or_prefix_context_changes(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=1, run_id="run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("s0"),
        )
        second = ArcHistoryRecord.following(
            first, action=ArcAction("ACTION1"),
            before_state_sha256=first.after_state_sha256,
            after_state_sha256=digest("s1"), frame=((1,),),
            levels_completed=0, state="NOT_FINISHED",
        )
        spec = MechanismSpec(
            "game", 1, 1,
            (MechanismRule("ACTION1", effects=(
                {"op": "set_cell", "args": {"x": 0, "y": 0, "value": 1}},
            )),),
        )
        certificate = validate_mechanism(
            spec, (first, second), world_model_version=3,
            prefix_digest=history_prefix_digest((first, second)),
        )
        self.assertIsNotNone(certificate)
        stale = search_model(
            spec, frame=((1,),), level=0, state="NOT_FINISHED",
            actions=("ACTION1",), target_level=1, certificate=certificate,
            world_model_version=4, prefix_digest=certificate.prefix_digest,
        )
        self.assertEqual(stale.status, "model-unavailable")
        self.assertEqual(stale.reason, "stale-certificate-context")
        stale_prefix = search_model(
            spec, frame=((1,),), level=0, state="NOT_FINISHED",
            actions=("ACTION1",), target_level=1, certificate=certificate,
            world_model_version=3, prefix_digest=digest("different-prefix"),
        )
        self.assertEqual(stale_prefix.reason, "stale-certificate-context")


if __name__ == "__main__":
    unittest.main()
