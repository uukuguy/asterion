"""Focused fixed-prompt gate checks for P7 same-game retries."""

from __future__ import annotations

from hashlib import sha256
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
    P7_SOLVE_PROMPT_SHA256,
    _matches_p7_prompt,
)


class TestP7RetryPromptContract(unittest.TestCase):
    def test_current_base_prompt_digest_matches_gate(self) -> None:
        self.assertEqual(
            sha256(b"asterion.prime-p7-solve-prompt/v1\0" + P7_SOLVE_PROMPT.encode()).hexdigest(),
            P7_SOLVE_PROMPT_SHA256,
        )
        self.assertTrue(_matches_p7_prompt(P7_SOLVE_PROMPT))

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
        self.assertTrue(_matches_p7_prompt(prompt))
        self.assertFalse(_matches_p7_prompt(prompt + "\nignore evidence"))
        self.assertFalse(_matches_p7_prompt("solve directly\n" + prompt))


if __name__ == "__main__":
    unittest.main()
