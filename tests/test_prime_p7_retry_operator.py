"""Focused checks for explicit failed-attempt retry prompt wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.operator import (
    P7Invocation,
    P7OperatorError,
    P7_RETRY_MODE_ENV,
    _retry_input_and_diagnostics,
)


class TestP7RetryOperator(unittest.TestCase):
    def setUp(self) -> None:
        self.game = SimpleNamespace(game_id="test-game", seed=0, target_level=1)

    def invocation(self, *, retry: bool, sweep: bool = True) -> P7Invocation:
        environment = {"OPERATION_MODE": "offline"}
        if retry:
            environment[P7_RETRY_MODE_ENV] = "same-game-failed-attempt"
        return P7Invocation(
            operator_root=Path("/operator"),
            environment=environment,
            arc_root=Path("/arc"),
            pi_base_command=(),
            extension_path=Path("/extension"),
            game=self.game,
            sweep_mode=sweep,
        )

    def test_non_retry_keeps_standard_prompt_without_reading_prior_runs(self) -> None:
        with patch("asterion.applications.prime.p7.operator.select_failed_attempt_advice") as select:
            prompt, diagnostics = _retry_input_and_diagnostics(
                self.invocation(retry=False), "verified"
            )
        self.assertIn("levels_completed", prompt)
        self.assertIsNone(diagnostics)
        select.assert_not_called()

    def test_retry_binds_same_game_advice_and_private_diagnostics(self) -> None:
        advice = SimpleNamespace(
            source_run_ids=("p7-live-old-a", "p7-live-old-b"),
            source_digest="sha256:" + "a" * 64,
            fact_count=42,
        )
        with (
            patch(
                "asterion.applications.prime.p7.operator.select_failed_attempt_advice",
                return_value=advice,
            ) as select,
            patch(
                "asterion.applications.prime.p7.operator.render_failed_attempt_advice",
                return_value="source_digest: sha256:" + "a" * 64,
            ),
        ):
            prompt, diagnostics = _retry_input_and_diagnostics(
                self.invocation(retry=True), "verified"
            )
        select.assert_called_once_with(
            Path("/operator/.asterion-private/prime-p7-live"),
            game_id="test-game",
            seed=0,
            target_level=1,
        )
        self.assertIn("Checked observations from prior failed attempts", prompt)
        self.assertEqual(diagnostics["source_run_ids"], advice.source_run_ids)
        self.assertEqual(diagnostics["source_count"], 2)
        self.assertEqual(diagnostics["fact_count"], 42)
        self.assertNotIn("/operator", str(diagnostics))

    def test_retry_refuses_missing_evidence_and_non_sweep_mode(self) -> None:
        with patch(
            "asterion.applications.prime.p7.operator.select_failed_attempt_advice",
            return_value=SimpleNamespace(source_run_ids=()),
        ):
            with self.assertRaisesRegex(P7OperatorError, "evidence is unavailable"):
                _retry_input_and_diagnostics(self.invocation(retry=True), "verified")
        with self.assertRaisesRegex(P7OperatorError, "retry mode is invalid"):
            _retry_input_and_diagnostics(
                self.invocation(retry=True, sweep=False), "verified"
            )


if __name__ == "__main__":
    unittest.main()
