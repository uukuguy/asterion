"""Static contracts for public Prime Make presets."""

from __future__ import annotations

import unittest
from pathlib import Path
import os
import subprocess
import tempfile


_P7_PRESET_TARGETS = (
    "asterion-prime-p7-solve asterion-prime-p7-cognition "
    "asterion-prime-p7-level-witness asterion-prime-p7-sweep-attempt"
)


def _recipe(makefile: str, target: str) -> str:
    """Return one target's recipe block, ending at the first blank line."""

    marker = f"{target}:\n"
    if marker not in makefile:
        raise AssertionError(f"preset {target} is missing")
    return makefile.split(marker, 1)[1].split("\n\n", 1)[0]


class TestPrimeMakePresets(unittest.TestCase):
    def test_p7_next_level_requires_explicit_game_and_uses_operator_driver(self) -> None:
        root = Path(__file__).resolve().parents[1]
        makefile = (root / "Makefile").read_text()
        recipe = _recipe(makefile, "asterion-prime-p7-next")
        self.assertIn("tools/run_prime_p7_next_level.py", recipe)
        self.assertIn("--guest-machine", recipe)
        self.assertIn("$(origin GAME)", recipe)
        self.assertNotIn("official", recipe)
        completed = subprocess.run(
            ["make", "--no-print-directory", "-n", "asterion-prime-p7-next", "GAME=lp85"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--game", completed.stdout)
        self.assertIn("ASTERION_PRIME_P7_NEXT_GAME", completed.stdout)

    def test_p7_targeted_ab_is_explicit_operator_only_preset(self) -> None:
        root = Path(__file__).resolve().parents[1]
        makefile = (root / "Makefile").read_text()
        recipe = _recipe(makefile, "asterion-prime-p7-targeted-ab")
        self.assertIn("tools/run_prime_p7_targeted_ab.py", recipe)
        self.assertIn("--operator-root", recipe)
        self.assertIn("--arc-root", recipe)
        self.assertIn("--game", recipe)
        self.assertIn("--guest-machine", recipe)
        self.assertNotIn("official", recipe)
        self.assertNotIn("second-round-campaign", recipe)
        completed = subprocess.run(
            ["make", "--no-print-directory", "-n", "asterion-prime-p7-targeted-ab",
             "GAME=lp85"], cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--game", completed.stdout)
        self.assertIn("ASTERION_PRIME_P7_AB_GAME", completed.stdout)

    def test_p7_game_selection_forwards_alias_or_exact_id(self) -> None:
        root = Path(__file__).resolve().parents[1]
        probe = "p7-game-probe:\n\t@printf '%s\\n' '$(ASTERION_PRIME_P7_GAME_ID)'\n"

        for game in ("ls20", "tu93", "ls20-9607627b"):
            with self.subTest(game=game):
                completed = subprocess.run(
                    [
                        "make",
                        "--no-print-directory",
                        "-s",
                        "-f",
                        "Makefile",
                        "-f",
                        "-",
                        "p7-game-probe",
                        f"GAME={game}",
                    ],
                    cwd=root,
                    text=True,
                    input=probe,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(completed.stdout.strip(), game)

    def test_p7_level_witness_forwards_explicit_level(self) -> None:
        root = Path(__file__).resolve().parents[1]
        probe = "p7-level-probe:\n\t@printf '%s\\n' '$(ASTERION_PRIME_P7_TARGET_LEVEL)'\n"

        for arguments, expected in (([], "1"), (["LEVEL=2"], "2")):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [
                        "make",
                        "--no-print-directory",
                        "-s",
                        "-f",
                        "Makefile",
                        "-f",
                        "-",
                        "p7-level-probe",
                        *arguments,
                    ],
                    cwd=root,
                    text=True,
                    input=probe,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(completed.stdout.strip(), expected)

    def test_p7_explicit_target_level_override_still_wins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        probe = "p7-target-override-probe:\n\t@printf '%s\\n' '$(ASTERION_PRIME_P7_TARGET_LEVEL)'\n"
        completed = subprocess.run(
            [
                "make",
                "--no-print-directory",
                "-s",
                "-f",
                "Makefile",
                "-f",
                "-",
                "p7-target-override-probe",
                "LEVEL=2",
                "ASTERION_PRIME_P7_TARGET_LEVEL=3",
            ],
            cwd=root,
            text=True,
            input=probe,
            capture_output=True,
            check=True,
        )
        self.assertEqual(completed.stdout.strip(), "3")

    def test_p7_normal_solve_accepts_explicit_level_in_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["make", "--no-print-directory", "-n", "asterion-prime-p7-solve", "GAME=ls20", "LEVEL=2"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("ASTERION_PRIME_P7_TARGET_LEVEL", completed.stdout)

    def test_p7_routes_target_level_when_explicit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for target, args in (
            ("asterion-prime-p7-solve", []),
            ("asterion-prime-p7-solve", ["LEVEL=2"]),
            ("asterion-prime-p7-level-witness", ["LEVEL=2"]),
        ):
            with self.subTest(target=target, args=args):
                completed = subprocess.run(
                    ["make", "--no-print-directory", "-n", target, "GAME=ls20", *args],
                    cwd=root, text=True, capture_output=True, check=True,
                )
                self.assertIn("ORBENV", completed.stdout)
                self.assertIn("tools/p7_guest_environment.txt", completed.stdout)

    def test_p7_guest_receives_configuration_selected_model_and_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        makefile = (root / "Makefile").read_text()
        recipe = _recipe(makefile, _P7_PRESET_TARGETS)
        contract = (root / "tools" / "p7_guest_environment.txt").read_text()
        self.assertIn("tools/p7_guest_environment.txt", recipe)
        self.assertIn('tr "\\\\n" ":"', recipe)
        self.assertIn('tr "\\\\n" " "', recipe)
        self.assertIn("ASTERION_PRIME_PROVIDER\n", contract)
        self.assertIn("ASTERION_PRIME_MODEL\n", contract)

    def test_make_model_selection_overrides_stale_terminal_export(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dotenv = {
            "ASTERION_PRIME_PROVIDER": "fixture-provider",
            "ASTERION_PRIME_MODEL": "fixture-model",
        }
        probe = "p7-model-probe:\n\t@printf '%s\\n' '$(ASTERION_PRIME_PROVIDER):$(ASTERION_PRIME_MODEL)'\n"
        with tempfile.TemporaryDirectory() as temporary:
            operator_root = Path(temporary)
            (operator_root / ".env").write_text(
                "\n".join(f"{key}={value}" for key, value in dotenv.items()) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                ["make", "--no-print-directory", "-s", "-f", str(root / "Makefile"),
                 "-f", "-", "p7-model-probe", "ASTERION_PRIME_PROVIDER=stale",
                 "ASTERION_PRIME_MODEL=gpt-6-sol"],
                cwd=operator_root, text=True, input=probe, capture_output=True, check=True,
            )
        self.assertEqual(
            completed.stdout.strip(),
            f"{dotenv['ASTERION_PRIME_PROVIDER']}:{dotenv['ASTERION_PRIME_MODEL']}",
        )

    def test_p7_history_variant_reaches_only_local_witness_and_sweep_guest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        makefile = (root / "Makefile").read_text()
        local = _recipe(makefile, _P7_PRESET_TARGETS)
        official = _recipe(makefile, "asterion-prime-p7-official-preflight asterion-prime-p7-official-submit asterion-prime-p7-official-live-eval")
        self.assertIn("tools/p7_guest_environment.txt", local)
        self.assertIn("ASTERION_PRIME_P7_HISTORY_VARIANT\n", (root / "tools" / "p7_guest_environment.txt").read_text())
        self.assertNotIn("ASTERION_PRIME_P7_HISTORY_VARIANT", official)

    def test_unknown_game_does_not_block_unrelated_make_targets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["make", "--no-print-directory", "-n", "help", "GAME=unknown"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("Asterion Prime ARC-AGI-3 solve", completed.stdout)

    def test_official_saved_submission_requires_explicit_game_before_build(self) -> None:
        root = Path(__file__).resolve().parents[1]
        missing = subprocess.run(
            ["make", "--no-print-directory", "-n", "asterion-prime-p7-official-submit"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("requires GAME", missing.stderr)
        selected = subprocess.run(
            ["make", "--no-print-directory", "-n", "asterion-prime-p7-official-submit", "GAME=ls20"],
            cwd=root, text=True, capture_output=True, check=True,
        )
        self.assertIn("saved-submit", selected.stdout)

    def test_official_recovery_uses_operator_root(self) -> None:
        root = Path(__file__).resolve().parents[1]
        operator_root = root / "operator-fixture"
        completed = subprocess.run(
            ["make", "--no-print-directory", "-n", "asterion-prime-p7-official-recover",
             "RUN=run-1", f"ASTERION_PRIME_OPERATOR_ROOT={operator_root}"],
            cwd=root, text=True, capture_output=True, check=True,
        )
        self.assertIn(
            f"{operator_root}/.asterion-private/prime-p7-official/"
            "$ASTERION_PRIME_P7_RECOVERY_RUN/official-recovery.json",
            completed.stdout,
        )

    def test_p7_invalid_witness_level_stops_before_wheel_build(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["make", "--no-print-directory", "-s", "asterion-prime-p7-level-witness", "LEVEL=zero"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("LEVEL must be a positive integer; got zero", completed.stderr)
        self.assertNotIn("Building wheel", completed.stdout)

    def test_p7_one_command_ignores_stale_shell_selection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        probe = (
            "p7-default-probe:\n"
            "\t@printf '%s\\n' '$(ASTERION_PRIME_P7_GAME_ID)' "
            "'$(ASTERION_PRIME_P7_SEED)' '$(ASTERION_PRIME_ARC_ROOT)'\n"
        )
        completed = subprocess.run(
            ["make", "--no-print-directory", "-s", "-f", "Makefile", "-f", "-", "p7-default-probe"],
            cwd=root,
            env={
                **os.environ,
                "ASTERION_PRIME_P7_GAME_ID": "ls20-9607627b",
                "ASTERION_PRIME_P7_SEED": "123",
                "ASTERION_PRIME_ARC_ROOT": "/unexpected/old/arc-root",
            },
            input=probe,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                "tu93",
                "0",
                str((root.parent / "external-prime" / "arc-agi-3").resolve()),
            ],
        )

    def test_p7_explicit_game_id_override_still_wins_over_alias(self) -> None:
        root = Path(__file__).resolve().parents[1]
        probe = "p7-override-probe:\n\t@printf '%s\\n' '$(ASTERION_PRIME_P7_GAME_ID)'\n"
        completed = subprocess.run(
            [
                "make",
                "--no-print-directory",
                "-s",
                "-f",
                "Makefile",
                "-f",
                "-",
                "p7-override-probe",
                "GAME=ls20",
                "ASTERION_PRIME_P7_GAME_ID=custom-123",
            ],
            cwd=root,
            text=True,
            input=probe,
            capture_output=True,
            check=True,
        )
        self.assertEqual(completed.stdout.strip(), "custom-123")

    def test_native_p1_builds_installed_wheel_in_shared_mount(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        recipe = _recipe(makefile, "asterion-prime-p1-run")
        for literal in (
            '$(CURDIR)/.asterion-prime-p1-wheel.XXXXXX',
            "trap",
            "build --wheel --out-dir",
            'orb -m "$(PRIME_ORB_MACHINE)"',
            "unset PYTHONPATH",
            "ASTERION_PRIME_OPERATOR_ROOT",
            "ASTERION_PRIME_NODE",
            "npm exec --offline --yes --package=node@22",
            "--isolated --with",
            '--with "ipython==9.17.1"',
            "python -I -m asterion.applications.prime.p1.operator",
        ):
            self.assertIn(literal, recipe)
        for option in (
            "--provider",
            "--model",
            "--cost",
            "--deadline",
            "PYTHONPATH=src",
            "ASTERION_PRIME_WORKER_PYTHON",
            "unset PYTHONPATH ASTERION_PRIME_NODE",
        ):
            self.assertNotIn(option, recipe)

    def test_native_p7_solves_from_an_installed_wheel(self) -> None:
        """The P7 preset is the P1 shape, with operator-owned ARC and Pi values.

        The preset must reach the installed route and nothing else: no source
        tree on ``PYTHONPATH``, no interpreter from outside the distribution,
        and no literal for the ARC checkout layout, which the operator supplies
        as a value.
        """

        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        self.assertNotIn("/Users/", makefile)
        recipe = _recipe(makefile, _P7_PRESET_TARGETS)
        for literal in (
            '$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX',
            "trap",
            "build --wheel --out-dir",
            'orb -m "$(PRIME_ORB_MACHINE)"',
            "unset PYTHONPATH",
            "ASTERION_PRIME_OPERATOR_ROOT",
            "ASTERION_PRIME_NODE",
            "ASTERION_PRIME_ARC_ROOT",
            "ASTERION_PRIME_PI_ENTRY",
            "npm exec --offline --yes --package=node@22",
            "--isolated --with",
            '--with "ipython==9.17.1"',
            "arc_agi-0.9.9-py3-none-any.whl",
            "arcengine-0.9.3-py3-none-any.whl",
            "python -I -m asterion.applications.prime.p7.operator",
        ):
            self.assertIn(literal, recipe)
        for option in (
            "--provider",
            "--model",
            "--cost",
            "--deadline",
            "PYTHONPATH=src",
            "ASTERION_PRIME_WORKER_PYTHON",
            "external-prime",
            "venv/bin/python",
            "unset PYTHONPATH ASTERION_PRIME_NODE",
        ):
            self.assertNotIn(option, recipe)


if __name__ == "__main__":
    unittest.main()
