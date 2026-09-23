"""P7 operator game selection rejects mismatched local assets before execution."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest


_GAMES = {
    "ls20-9607627b": [22, 123, 73, 84, 96, 192, 186],
    "tu93-0768757b": [19, 16, 34, 42, 123, 80, 14, 23, 111],
}


class TestP7GameSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.arc_root = Path(self.temporary.name)
        for game_id, baselines in _GAMES.items():
            stem, version = game_id.split("-", 1)
            game_root = self.arc_root / "environment_files" / stem / version
            game_root.mkdir(parents=True)
            (game_root / f"{stem}.py").write_text("# game fixture\n")
            (game_root / "metadata.json").write_text(
                json.dumps({"game_id": game_id, "baseline_actions": baselines})
            )

    def test_default_and_explicit_tu93_preserve_exact_identity(self) -> None:
        from asterion.applications.prime.p7.game import resolve_game_selection

        old = resolve_game_selection({}, self.arc_root)
        new = resolve_game_selection(
            {
                "ASTERION_PRIME_P7_GAME_ID": "tu93-0768757b",
                "ASTERION_PRIME_P7_SEED": "17",
            },
            self.arc_root,
        )
        self.assertEqual((old.game_id, old.seed, old.win_levels), ("ls20-9607627b", 0, 7))
        self.assertEqual((new.game_id, new.seed, new.win_levels), ("tu93-0768757b", 17, 9))
        self.assertEqual(new.baseline_actions[0], 19)

    def test_unknown_game_or_malformed_seed_is_rejected(self) -> None:
        from asterion.applications.prime.p7.game import (
            P7GameSelectionError,
            resolve_game_selection,
        )

        for environment in (
            {"ASTERION_PRIME_P7_GAME_ID": "ft09-0d8bbf25"},
            {"ASTERION_PRIME_P7_GAME_ID": "../tu93-0768757b"},
            {"ASTERION_PRIME_P7_SEED": "-1"},
            {"ASTERION_PRIME_P7_SEED": "1.0"},
            {"ASTERION_PRIME_P7_SEED": "2147483648"},
        ):
            with self.subTest(environment=environment), self.assertRaisesRegex(
                P7GameSelectionError, "P7 game selection is unavailable"
            ):
                resolve_game_selection(environment, self.arc_root)

    def test_missing_or_changed_game_data_is_rejected(self) -> None:
        from asterion.applications.prime.p7.game import (
            P7GameSelectionError,
            resolve_game_selection,
        )

        game_root = self.arc_root / "environment_files" / "tu93" / "0768757b"
        environment = {"ASTERION_PRIME_P7_GAME_ID": "tu93-0768757b"}
        (game_root / "tu93.py").unlink()
        with self.assertRaises(P7GameSelectionError):
            resolve_game_selection(environment, self.arc_root)
        (game_root / "tu93.py").write_text("# game fixture\n")
        (game_root / "metadata.json").write_text(
            json.dumps({"game_id": "tu93-0768757b", "baseline_actions": [19]})
        )
        with self.assertRaises(P7GameSelectionError):
            resolve_game_selection(environment, self.arc_root)
