from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p7.game_mechanics import (
    GameMechanism,
    GameMechanicsStore,
)


class GameMechanicsStoreTests(unittest.TestCase):
    def _store(self, root: Path) -> GameMechanicsStore:
        return GameMechanicsStore(root, game_id="sp80", seed=589, win_levels=6)

    def _evidence(self, level: int, action: str = "ACTION1") -> dict[str, object]:
        return {
            "frame_id": f"frame-{level}",
            "action_id": f"action-{level}",
            "source_run": "run-a",
            "level": level,
            "action": action,
        }

    def test_record_is_game_wide_and_confirm_binds_multiple_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            fact = store.record(
                "move_player",
                rules=[{"action": "ACTION1", "delta": [1, 0]}],
                conditions=[{"kind": "walkable", "subject": "player"}],
                effects=[{"kind": "translate", "subject": "player", "delta": [1, 0]}],
                scope="game",
                evidence=[self._evidence(0)],
            )
            self.assertIsInstance(fact, GameMechanism)
            self.assertEqual(fact.status, "hypothesis")
            self.assertEqual(fact.scope["kind"], "game")
            self.assertEqual(fact.bound_levels, ())

            confirmed = store.confirm(
                "move_player",
                evidence=[self._evidence(1), self._evidence(2)],
                levels=[0, 1, 2],
            )
            self.assertEqual(confirmed.status, "confirmed")
            self.assertEqual(confirmed.bound_levels, (0, 1, 2))
            self.assertEqual(confirmed.scope["kind"], "game")

            restored = GameMechanicsStore.load(root, game_id="sp80", seed=589, win_levels=6)
            loaded = restored.get("move_player")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, "confirmed")
            self.assertEqual(loaded.bound_levels, (0, 1, 2))

    def test_level_scope_does_not_claim_game_wide_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            fact = store.record(
                "goal_trigger",
                rules=[{"action": "ACTION5"}],
                conditions=[{"kind": "at_goal"}],
                effects=[{"kind": "advance_level"}],
                scope={"kind": "level", "levels": [2]},
                evidence=[self._evidence(2, "ACTION5")],
            )
            self.assertEqual(fact.scope, {"kind": "level", "levels": [2]})
            self.assertEqual(fact.bound_levels, (2,))
            confirmed = store.confirm("goal_trigger", evidence=[self._evidence(2, "ACTION5")])
            self.assertEqual(confirmed.bound_levels, (2,))
            self.assertEqual(confirmed.scope["kind"], "level")

    def test_observe_appends_cross_level_evidence_without_promoting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.record(
                "move",
                rules=[{"action": "ACTION1"}],
                conditions=[],
                effects=[{"kind": "translate"}],
                level=0,
                evidence=[self._evidence(0)],
            )
            observed = store.observe(
                "move", evidence=[self._evidence(1)], levels=[1]
            )
            self.assertEqual(observed.status, "hypothesis")
            self.assertEqual(observed.bound_levels, (0, 1))
            self.assertEqual(len(observed.evidence), 2)

    def test_conflict_preserves_evidence_and_cannot_be_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.record(
                "door",
                rules=[{"action": "ACTION2", "opens": True}],
                conditions=[{"kind": "near", "subject": "door"}],
                effects=[{"kind": "set_open", "subject": "door"}],
                evidence=[self._evidence(0, "ACTION2")],
            )
            conflicted = store.conflict(
                "door",
                observed={"opens": False},
                evidence=[self._evidence(1, "ACTION2")],
                reason="prediction-mismatch",
            )
            self.assertEqual(conflicted.status, "conflict")
            self.assertEqual(len(conflicted.conflicts), 1)
            self.assertEqual(conflicted.conflicts[0]["reason"], "prediction-mismatch")
            with self.assertRaises(ValueError):
                store.confirm("door", evidence=[self._evidence(1, "ACTION2")])

    def test_projection_is_advisory_and_detached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.record(
                "move",
                rules=[{"action": "ACTION1"}],
                conditions=[],
                effects=[{"kind": "translate"}],
                level=0,
                evidence=[self._evidence(0)],
            )
            projection = store.projection()
            self.assertEqual(projection["schema"], "asterion.prime.p7-game-mechanics/v1")
            self.assertEqual(projection["execution_authority"], "none")
            self.assertFalse(projection["mechanisms"][0]["planner_eligible"])
            projection["mechanisms"][0]["rules"][0]["action"] = "RESET"
            self.assertEqual(store.get("move").rules[0]["action"], "ACTION1")

    def test_load_rejects_wrong_identity_and_malformed_file_without_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            store.record(
                "move",
                rules=[], conditions=[], effects=[], evidence=[self._evidence(0)],
            )
            # Different exact game identities have isolated namespaces.
            other = GameMechanicsStore.load(root, game_id="other", seed=589, win_levels=6)
            self.assertEqual(other.projection()["mechanisms"], [])
            store.path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
            restored = GameMechanicsStore.load(root, game_id="sp80", seed=589, win_levels=6)
            self.assertEqual(restored.projection()["mechanisms"], [])

    def test_persistence_replace_is_atomic_and_failed_write_does_not_leave_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            with patch("asterion.applications.prime.p7.game_mechanics.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    store.record(
                        "move",
                        rules=[], conditions=[], effects=[], evidence=[self._evidence(0)],
                    )
            parent = root / ".asterion-private" / "prime-p7-live"
            self.assertFalse(any(path.name.startswith(".game-mechanics-") for path in parent.glob("*")))


if __name__ == "__main__":
    unittest.main()
