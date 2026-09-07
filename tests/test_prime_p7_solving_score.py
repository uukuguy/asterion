from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


class FakeResult:
    def __init__(self, score: float) -> None:
        self.score = score


class FakeCalculator:
    instances: list["FakeCalculator"] = []

    def __init__(self) -> None:
        self.levels: list[tuple[int, bool, int, int, str | None]] = []
        self.instances.append(self)

    def add_level(
        self,
        level_index: int,
        completed: bool,
        actions_taken: int,
        baseline_actions: int,
        game_id: str | None = None,
    ) -> None:
        self.levels.append(
            (level_index, completed, actions_taken, baseline_actions, game_id)
        )

    def to_score(self) -> FakeResult:
        total_weight = sum(item[0] for item in self.levels)
        score = 0.0
        completed_weight = 0
        for index, completed, actions, baseline, _ in self.levels:
            if completed:
                score += min((baseline / actions) ** 2 * 100, 115.0) * index
                completed_weight += index
        return FakeResult(
            min(score / total_weight, completed_weight / total_weight * 100)
        )


class TestP7SolvingScore(unittest.TestCase):
    def test_official_partial_score_uses_all_seven_pinned_levels(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_score import (
            P7_SOLVING_ARC_AGI_WHEEL_SHA256,
            P7_SOLVING_BASELINE_ACTIONS,
            official_p7_partial_score,
        )

        self.assertEqual(P7_SOLVING_BASELINE_ACTIONS, (22, 123, 73, 84, 96, 192, 186))
        for actions, expected in ((1, "3.571429"), (22, "3.571429"), (44, "0.892857")):
            with self.subTest(actions=actions):
                FakeCalculator.instances.clear()
                modules = {
                    "arc_agi": types.ModuleType("arc_agi"),
                    "arc_agi.scorecard": types.SimpleNamespace(
                        EnvironmentScoreCalculator=FakeCalculator
                    ),
                }
                with patch.dict(sys.modules, modules):
                    value = official_p7_partial_score(
                        actions,
                        arc_agi_wheel_sha256=P7_SOLVING_ARC_AGI_WHEEL_SHA256,
                        baseline_actions=P7_SOLVING_BASELINE_ACTIONS,
                    )
                self.assertEqual(value, expected)
                self.assertEqual(
                    FakeCalculator.instances[0].levels,
                    [
                        (i, i == 1, actions if i == 1 else 0, baseline, "ls20-9607627b")
                        for i, baseline in enumerate(P7_SOLVING_BASELINE_ACTIONS, 1)
                    ],
                )

    def test_changed_score_identities_are_rejected(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_score import (
            P7SolvingScoreError,
            P7_SOLVING_ARC_AGI_WHEEL_SHA256,
            P7_SOLVING_BASELINE_ACTIONS,
            official_p7_partial_score,
        )

        cases = (
            {
                "arc_agi_wheel_sha256": "sha256:" + "0" * 64,
                "baseline_actions": P7_SOLVING_BASELINE_ACTIONS,
            },
            {
                "arc_agi_wheel_sha256": P7_SOLVING_ARC_AGI_WHEEL_SHA256,
                "baseline_actions": (23, *P7_SOLVING_BASELINE_ACTIONS[1:]),
            },
        )
        for kwargs in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(P7SolvingScoreError, "unavailable"),
            ):
                official_p7_partial_score(22, **kwargs)

    def test_nonfinite_and_out_of_range_calculator_values_are_rejected(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_score import (
            P7SolvingScoreError,
            official_p7_partial_score,
        )

        for value in (float("nan"), float("inf"), -0.1, 100.1):

            class Calculator(FakeCalculator):
                def to_score(self) -> FakeResult:
                    return FakeResult(value)

            with self.subTest(value=value), self.assertRaises(P7SolvingScoreError):
                modules = {
                    "arc_agi": types.ModuleType("arc_agi"),
                    "arc_agi.scorecard": types.SimpleNamespace(
                        EnvironmentScoreCalculator=Calculator
                    ),
                }
                with patch.dict(sys.modules, modules):
                    official_p7_partial_score(22)


if __name__ == "__main__":
    unittest.main()
