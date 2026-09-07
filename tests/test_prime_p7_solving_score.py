from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile


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
            P7SolvingScoreCalculator,
            P7_SOLVING_BASELINE_ACTIONS,
            official_p7_partial_score,
        )

        self.assertEqual(P7_SOLVING_BASELINE_ACTIONS, (22, 123, 73, 84, 96, 192, 186))
        for actions, expected in ((1, "3.571429"), (22, "3.571429"), (44, "0.892857")):
            with self.subTest(actions=actions):
                FakeCalculator.instances.clear()
                calculator = P7SolvingScoreCalculator._from_verified(
                    FakeCalculator, "sha256:" + "a" * 64
                )
                value = official_p7_partial_score(
                    actions,
                    calculator=calculator,
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
            P7SolvingScoreCalculator,
            P7SolvingScoreError,
            P7_SOLVING_BASELINE_ACTIONS,
            official_p7_partial_score,
        )

        calculator = P7SolvingScoreCalculator._from_verified(
            FakeCalculator, "sha256:" + "a" * 64
        )
        cases = (
            {"calculator": object(), "baseline_actions": P7_SOLVING_BASELINE_ACTIONS},
            {
                "calculator": calculator,
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
            P7SolvingScoreCalculator,
            P7SolvingScoreError,
            official_p7_partial_score,
        )

        for value in (float("nan"), float("inf"), -0.1, 100.1):

            class Calculator(FakeCalculator):
                def to_score(self) -> FakeResult:
                    return FakeResult(value)

            with self.subTest(value=value), self.assertRaises(P7SolvingScoreError):
                calculator = P7SolvingScoreCalculator._from_verified(
                    Calculator, "sha256:" + "a" * 64
                )
                official_p7_partial_score(22, calculator=calculator)

    def test_unbound_or_sys_path_injected_calculator_is_rejected(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_score import (
            P7SolvingScoreError,
            bind_p7_solving_score_calculator,
            official_p7_partial_score,
        )

        with self.assertRaises(P7SolvingScoreError):
            official_p7_partial_score(22)
        digest = "sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            injected = types.ModuleType("arc_agi")
            injected.__file__ = str(root / "arc_agi/__init__.py")
            injected_scorecard = types.ModuleType("arc_agi.scorecard")
            injected_scorecard.EnvironmentScoreCalculator = FakeCalculator
            with patch.dict(
                sys.modules,
                {"arc_agi": injected, "arc_agi.scorecard": injected_scorecard},
            ):
                with self.assertRaises(P7SolvingScoreError):
                    bind_p7_solving_score_calculator(
                        root, runtime_sha256=digest
                    )

            venv = root / "venv"
            site_packages = venv / "lib/python/site-packages"
            package = site_packages / "arc_agi"
            package.mkdir(parents=True)
            (venv / "bin").mkdir()
            (venv / "bin/python3").write_bytes(b"python")
            (package / "__init__.py").write_text("")
            scorecard = b"class EnvironmentScoreCalculator: pass\n"
            (package / "scorecard.py").write_bytes(scorecard)
            wheels = root / "wheels"
            wheels.mkdir()
            with zipfile.ZipFile(
                wheels / "arc_agi-0.9.9-py3-none-any.whl", "w"
            ) as archive:
                archive.writestr("arc_agi/scorecard.py", scorecard)
            attacker = root / "attacker/arc_agi"
            attacker.mkdir(parents=True)
            (attacker / "__init__.py").write_text("")
            with (
                patch(
                    "asterion.applications.prime_agent.operator.p7_runtime_lock.verify_p7_development_runtime",
                    return_value=types.SimpleNamespace(runtime_sha256=digest),
                ),
                patch.object(sys, "executable", str(venv / "bin/python3")),
                patch.object(sys, "prefix", str(venv)),
                patch(
                    "asterion.applications.prime_agent.operator.p7_solving_score.sysconfig.get_path",
                    return_value=str(site_packages),
                ),
                patch.object(sys, "path", [str(attacker.parent), str(site_packages)]),
                self.assertRaises(P7SolvingScoreError),
            ):
                bind_p7_solving_score_calculator(root, runtime_sha256=digest)


if __name__ == "__main__":
    unittest.main()
