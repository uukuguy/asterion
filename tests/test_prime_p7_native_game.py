"""P7 operator game selection rejects mismatched local assets before execution."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
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

    def test_intermediate_directory_symlink_cannot_escape_arc_root(self) -> None:
        from asterion.applications.prime.p7.game import (
            P7GameSelectionError,
            resolve_game_selection,
        )

        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        stem_root = self.arc_root / "environment_files" / "tu93"
        destination = Path(external.name) / "tu93"
        shutil.move(stem_root, destination)
        stem_root.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(P7GameSelectionError):
            resolve_game_selection(
                {"ASTERION_PRIME_P7_GAME_ID": "tu93-0768757b"}, self.arc_root
            )

    def test_first_level_score_uses_selected_game_baseline_and_level_weights(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.score import partial_game_score

        self.assertEqual(
            partial_game_score(19, P7GameSelection("tu93-0768757b", 0)), "2.222222"
        )
        self.assertEqual(
            partial_game_score(22, P7GameSelection("ls20-9607627b", 0)), "3.571429"
        )

    def test_public_receipt_uses_selected_identity(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _public_receipt

        value = _public_receipt(
            "unsuccessful", "p7-test", game=P7GameSelection("tu93-0768757b", 0)
        )
        self.assertEqual((value["game_id"], value["seed"]), ("tu93-0768757b", 0))

    def test_public_selection_digest_changes_with_seed(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _public_receipt

        receipt = {"receipt_sha256": "sha256:" + "a" * 64}
        replay = "sha256:" + "b" * 64
        values = [
            _public_receipt(
                "PASS",
                "p7-test",
                receipt=receipt,
                broker_replay_sha256=replay,
                game=P7GameSelection("tu93-0768757b", seed),
            )
            for seed in (0, 1)
        ]
        self.assertEqual(values[0]["receipt_sha256"], values[1]["receipt_sha256"])
        self.assertNotEqual(
            values[0]["selection_receipt_sha256"],
            values[1]["selection_receipt_sha256"],
        )

    def test_private_receipt_scores_tu93_first_level_with_its_baseline(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from tests.test_prime_p7_native_broker import _Engine

        game = P7GameSelection("tu93-0768757b", 0)
        broker = ArcBroker(
            engine=_Engine(game_id=game.game_id, win_levels=9, level_after=19), game=game
        )
        broker.act(("ACTION1",) * 19)
        (self.arc_root / "trace").mkdir()
        trace = P7PrivateTraceReceipt(
            broker, PrimeTraceRecorder(self.arc_root / "trace")
        )
        expected = trace.expected_receipt_sha256(run_id="p7-test")
        receipt = trace.get_receipt(run_id="p7-test", receipt_sha256=expected)
        self.assertEqual(receipt.partial_game_score, "2.222222")
        entries = [
            json.loads(line)
            for line in (self.arc_root / "trace" / "prime-trace.jsonl")
            .read_text()
            .splitlines()
        ]
        (completed,) = (entry for entry in entries if entry["kind"] == "arc.run.completed")
        self.assertEqual(
            (
                completed["payload"]["game_id"],
                completed["payload"]["seed"],
                completed["payload"]["win_levels"],
            ),
            ("tu93-0768757b", 0, 9),
        )
