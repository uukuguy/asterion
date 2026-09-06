"""Static contracts for public Prime Make presets."""

from __future__ import annotations

import unittest
from pathlib import Path


class TestPrimeMakePresets(unittest.TestCase):
    def test_public_presets_contain_uv_output_and_bind_the_orb_machine(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        targets = (
            ("p1", "prime-p2-run:"),
            ("p2", "prime-p3-run:"),
            ("p3", "prime-p4-run:"),
            ("p4", "prime-p5-run:"),
            ("p5", "prime-p6-run:"),
            ("p6", "prime-p7-run:"),
            ("p7", "prime-apps-preflight:"),
        )
        for scenario, next_target in targets:
            with self.subTest(scenario=scenario):
                recipe = makefile.split(f"prime-{scenario}-run:\n", 1)[1].split(
                    "\n" + next_target, 1
                )[0]
                self.assertIn('export PRIME_ORB_MACHINE="$(PRIME_ORB_MACHINE)"', recipe)
                invocations = recipe.split("/root/.local/bin/uv run ")[1:]
                self.assertEqual(len(invocations), 2)
                for invocation in invocations:
                    self.assertTrue(invocation.startswith("--quiet "))

        preflight = makefile.split("prime-apps-preflight:\n", 1)[1].split(
            "\ntest.prime-session-context-parity.provider-free:", 1
        )[0]
        self.assertIn('export PRIME_ORB_MACHINE="$(PRIME_ORB_MACHINE)"', preflight)
        self.assertIn("exec /root/.local/bin/uv run --quiet ", preflight)

    def test_p1_p3_and_p4_self_prepare_with_a_safe_progress_stream(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        cases = (
            (
                "p1",
                "prime-p2-run:",
                "IPython coding: preserve state across two cells and validate the generated solution",
                "prime.ipython-coding@1.0.0",
            ),
            (
                "p3",
                "prime-p4-run:",
                "Recursive workflow: coordinate two child roles and validate the combined result",
                "prime.recursive-workflow@1.0.0",
            ),
            (
                "p4",
                "prime-p5-run:",
                "Long session continuity: detach, reattach, and validate the preserved session",
                "prime.long-session-continuity@1.0.0",
            ),
        )
        for scenario, next_target, purpose, application in cases:
            with self.subTest(scenario=scenario):
                recipe = makefile.split(f"prime-{scenario}-run:\n", 1)[1].split(
                    "\n" + next_target, 1
                )[0]
                self.assertIn(f"[prime-{scenario}] {purpose}", recipe)
                self.assertEqual(
                    recipe.count('orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)"'),
                    1,
                )
                self.assertLess(
                    recipe.index(
                        f"tools/prepare_prime_development.py --scenario {scenario}"
                    ),
                    recipe.index("asterion run --progress"),
                )
                self.assertIn('--run-id "$$1"', recipe)
                self.assertIn(f"' prime-{scenario}-run \"$$run_id\"", recipe)
                self.assertIn("--status-stream stderr", recipe)
                for required in (
                    "--extra prime",
                    "--python /usr/bin/python3",
                    "--isolated",
                    "--provider prime-agent",
                    f"--application {application}",
                    "--runtime prime.agent",
                    "--input fixed-small-verification",
                ):
                    self.assertIn(required, recipe)

    def test_p2_self_prepares_then_runs_with_progress_in_one_orb_shell(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        recipe = makefile.split("prime-p2-run:\n", 1)[1].split("\nprime-p3-run:", 1)[0]
        self.assertIn(
            "[prime-p2] Programmatic long context: use the fixed corpus, execute one cell, and validate the answer",
            recipe,
        )
        self.assertEqual(recipe.count("orb -m \"$(PRIME_ORB_MACHINE)\" -u root -w \"$(CURDIR)\""), 1)
        self.assertLess(recipe.index("tools/prepare_prime_development.py --scenario p2"), recipe.index("asterion run --progress"))
        self.assertIn('--run-id "$$1"', recipe)
        self.assertIn("' prime-p2-run \"$$run_id\"", recipe)
        self.assertNotIn("export run_id", recipe)
        self.assertIn("--status-stream stderr", recipe)
        for required in (
            "--extra prime",
            "--python /usr/bin/python3",
            "--isolated",
            "--provider prime-agent",
            "--application prime.programmatic-long-context@1.0.0",
            "--runtime prime.agent",
            "--input fixed-small-verification",
        ):
            with self.subTest(required=required):
                self.assertIn(required, recipe)

    def test_p5_p6_and_p7_self_prepare_with_safe_progress(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        cases = (
            ("p5", "prime-p6-run:", "Bounded autonomy: diagnose, repair, and validate the fixed clamp task", "prime.bounded-autonomy@1.0.0"),
            ("p6", "prime-p7-run:", "Continual improvement: evaluate, refine, holdout-test, then activate or roll back", "prime.continual-improvement@1.0.0"),
            ("p7", "prime-apps-preflight:", "ARC-AGI-3: run one offline episode capped at four actions and replay its score", "prime.arc-agi-3@1.0.0"),
        )
        for scenario, next_target, purpose, application in cases:
            with self.subTest(scenario=scenario):
                recipe = makefile.split(f"prime-{scenario}-run:\n", 1)[1].split("\n" + next_target, 1)[0]
                self.assertIn(f"[prime-{scenario}] {purpose}", recipe)
                self.assertIn(
                    f"'[prime-{scenario}] {purpose}' >&2",
                    recipe,
                )
                self.assertEqual(recipe.count('orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)"'), 1)
                self.assertLess(recipe.index(f"tools/prepare_prime_development.py --scenario {scenario}"), recipe.index("asterion run --progress"))
                self.assertIn("--status-stream stderr", recipe)
                self.assertIn('--run-id "$$1"', recipe)
                self.assertIn(f"' prime-{scenario}-run \"$$run_id\"", recipe)
                for required in ("--extra prime", "--python /usr/bin/python3", "--isolated", "--provider prime-agent", f"--application {application}", "--runtime prime.agent", "--input fixed-small-verification"):
                    self.assertIn(required, recipe)

    def test_aggregate_preflight_uses_one_isolated_orb_context(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        recipe = makefile.split("prime-apps-preflight:\n", 1)[1].split(
            "\ntest.prime-session-context-parity.provider-free:", 1
        )[0]
        self.assertIn("orb -m \"$(PRIME_ORB_MACHINE)\" -u root -w \"$(CURDIR)\"", recipe)
        self.assertIn("--extra prime", recipe)
        self.assertIn("--python /usr/bin/python3", recipe)
        self.assertIn("--isolated", recipe)
        self.assertIn("tools/preflight_prime_apps.py", recipe)


if __name__ == "__main__":
    unittest.main()
