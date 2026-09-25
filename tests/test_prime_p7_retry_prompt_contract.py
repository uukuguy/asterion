"""Focused fixed-prompt gate checks for P7 same-game retries."""

from __future__ import annotations

from pathlib import Path
import unittest

from asterion.applications.prime.p7.failed_attempts import (
    render_failed_attempt_advice,
    select_failed_attempt_advice,
)
from asterion.applications.prime.p7.prompt import (
    P7_SOLVE_PROMPT,
    build_p7_retry_prompt,
)
from asterion.capabilities.prime_arc_agi_3_solver.provider import (
    _valid_p7_input,
)


class TestP7RetryPromptContract(unittest.TestCase):
    def test_later_level_history_review_has_a_bounded_startup(self) -> None:
        prompt = " ".join(P7_SOLVE_PROMPT.split())
        self.assertIn("no more than three startup history calls", prompt)
        self.assertIn("one legal, falsifiable probe", prompt)
        self.assertIn("Further history may be inspected after that probe", prompt)

    def test_retry_guidance_preserves_evidence_scope(self) -> None:
        prompt = " ".join(build_p7_retry_prompt(P7_SOLVE_PROMPT, "checked facts").split())
        self.assertIn("A sealed partial run replays only its completed-level prefix", prompt)
        self.assertIn("A stall is an interrupted observation", prompt)
        self.assertIn("Before an optional RESET, identify why the current state cannot be recovered", prompt)

    def test_capability_checks_input_bounds_without_owning_prompt_text(self) -> None:
        self.assertTrue(_valid_p7_input(P7_SOLVE_PROMPT))
        self.assertTrue(_valid_p7_input("a different application-owned task"))
        for invalid in ("", "  ", "x" * 65537, "\ud800"):
            with self.subTest(invalid=invalid[:12]):
                self.assertFalse(_valid_p7_input(invalid))

    def test_sealed_same_game_retry_prompt_passes_gate(self) -> None:
        runs_root = Path(".asterion-private/prime-p7-live").resolve()
        if not runs_root.is_dir():
            self.skipTest("local P7 evidence is unavailable")
        advice = select_failed_attempt_advice(
            runs_root, game_id="bp35-0a0ad940", seed=0, target_level=1
        )
        if advice.source_count == 0:
            self.skipTest("local BP35 failures are unavailable")
        prompt = build_p7_retry_prompt(P7_SOLVE_PROMPT, render_failed_attempt_advice(advice))
        self.assertTrue(_valid_p7_input(prompt))
        self.assertIn("Checked observations from prior failed attempts", prompt)
        self.assertIn(advice.source_digest, prompt)


if __name__ == "__main__":
    unittest.main()
