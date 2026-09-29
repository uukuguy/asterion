"""Exact-game, bounded private Playbook storage."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.playbook import (
    CheckedFact,
    CheckedRoute,
    PlaybookKey,
    PlaybookSnapshot,
    append_checked_route,
    branch_playbook,
    capture_completed_level,
    load_playbook,
    save_playbook,
)
from asterion.applications.prime.p7.transition_model import ActionExpectation
from asterion.applications.prime.p7.world_model import EvidenceRef, WorldModelStore


_HASH = "sha256:" + "a" * 64
_HASH2 = "sha256:" + "b" * 64


def _expectation() -> ActionExpectation:
    return ActionExpectation("ACTION1", (), _HASH, _HASH2, _HASH2, (), 1, "WIN")


class TestP7Playbook(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = PlaybookKey("game-1", 42, 3)
        self.snapshot = PlaybookSnapshot(self.key)

    def _path(self) -> Path:
        return self.root / ".asterion-private/prime-p7-live/playbooks/game-1-42-3.json"

    def test_missing_and_other_identity_are_unavailable(self) -> None:
        self.assertIsNone(load_playbook(self.root, self.key))
        save_playbook(self.root, self.snapshot)
        self.assertEqual(load_playbook(self.root, self.key), self.snapshot)
        self.assertIsNone(load_playbook(self.root, PlaybookKey("game-2", 42, 3)))
        self.assertIsNone(load_playbook(self.root, PlaybookKey("game-1", 43, 3)))
        self.assertIsNone(load_playbook(self.root, PlaybookKey("game-1", 42, 4)))
        self.assertEqual(self._path().stat().st_mode & 0o777, 0o600)

    def test_rejects_symlink_file_and_directory(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True)
        target = self.root / "target"
        target.write_text("keep")
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)
        with self.assertRaises(ValueError):
            save_playbook(self.root, self.snapshot)
        self.assertEqual(target.read_text(), "keep")
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(self.root)
        with self.assertRaises(ValueError):
            save_playbook(self.root, self.snapshot)

    def test_rejects_dangling_symlink_before_exists_check(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True)
        path.symlink_to(self.root / "missing")
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)

    def test_checked_fact_value_is_bounded_immutable_and_detached(self) -> None:
        raw = {"nested": ["safe"]}
        fact = CheckedFact("entities", "goal", raw, 0, ("a" * 64,))
        raw["nested"].append("mutated")
        view = fact.value
        view["nested"].append("caller")
        self.assertEqual(fact.value, {"nested": ["safe"]})
        with self.assertRaises(ValueError):
            CheckedFact("entities", "goal", {"x": object()}, 0, ("a" * 64,))
        with self.assertRaises(ValueError):
            CheckedFact("entities", "goal", {"x": "z" * 1025}, 0, ("a" * 64,))

    def test_rejects_unknown_nested_schema_and_malformed_expectation(self) -> None:
        save_playbook(self.root, self.snapshot)
        path = self._path()
        body = json.loads(path.read_text())
        body["key"]["extra"] = 1
        path.write_text(json.dumps(body))
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)
        body["key"].pop("extra")
        body["checked_model"]["checked_routes"] = [{"level": 0, "expectations": [{"action": "A", "data": None}], "evidence_digest": _HASH}]
        path.write_text(json.dumps(body))
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)
    def test_rejects_non_regular_file_and_malformed_schema(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True)
        path.mkdir()
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)
        path.rmdir()
        save_playbook(self.root, self.snapshot)
        body = json.loads(path.read_text())
        body["schema"] = "unknown"
        path.write_text(json.dumps(body))
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)
        body["schema"] = "asterion.prime.p7-playbook/v1"
        body["key"]["seed"] = 43
        path.write_text(json.dumps(body))
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)

    def test_atomic_replace_preserves_old_file_on_failure(self) -> None:
        save_playbook(self.root, self.snapshot)
        old = self._path().read_bytes()
        revised = branch_playbook(self.snapshot, "route-conflict")
        with patch("asterion.applications.prime.p7.playbook.os.replace", side_effect=OSError("fail")):
            with self.assertRaises(ValueError):
                save_playbook(self.root, revised)
        self.assertEqual(self._path().read_bytes(), old)
        self.assertEqual(list(self._path().parent.iterdir()), [self._path()])

    def test_rejects_oversized_json(self) -> None:
        save_playbook(self.root, self.snapshot)
        self._path().write_bytes(b" " * (256 * 1024 + 1))
        with self.assertRaises(ValueError):
            load_playbook(self.root, self.key)

    def test_checked_route_and_branch_are_isolated(self) -> None:
        route = CheckedRoute(0, (_expectation(),), _HASH)
        checked = append_checked_route(self.snapshot, route)
        branched = branch_playbook(checked, "prediction-conflict")
        self.assertEqual(self.snapshot.checked_routes, ())
        self.assertEqual(checked.checked_routes, (route,))
        self.assertEqual(checked.branch_reasons, ())
        self.assertEqual(branched.branch_reasons, ("prediction-conflict",))
        self.assertEqual(branched.checked_routes, checked.checked_routes)
        save_playbook(self.root, branched)
        self.assertEqual(load_playbook(self.root, self.key), branched)

    def test_metadata_is_unique_and_bounded(self) -> None:
        with self.assertRaises(ValueError):
            PlaybookSnapshot(self.key, branch_reasons=("same", "same"))
        with self.assertRaises(ValueError):
            PlaybookSnapshot(self.key, conflict_metadata=("x" * 1025,))

    def test_completed_level_captures_checked_facts_before_refresh(self) -> None:
        world = WorldModelStore("game-1", 42, 3)
        evidence = EvidenceRef(summary_hash="a" * 64)
        world.record_hypothesis("mechanics", "controls", {"ACTION1": "move"}, level=0, evidence=evidence)
        world.confirm("mechanics", "controls", evidence=evidence)
        world.record_hypothesis("entities", "goal", {"x": 2}, level=0, evidence=evidence)
        world.confirm("entities", "goal", evidence=evidence)
        captured = capture_completed_level(self.snapshot, world.snapshot, level=0)
        world.refresh_level(1)
        self.assertEqual(len(captured.level_memory), 1)
        self.assertEqual({fact.key for fact in captured.level_memory[0].checked_facts}, {"goal", "controls"})
        save_playbook(self.root, captured)
        self.assertEqual(load_playbook(self.root, self.key), captured)

    def test_completed_level_requires_current_in_range_level(self) -> None:
        world = WorldModelStore("game-1", 42, 3)
        with self.assertRaises(ValueError):
            capture_completed_level(self.snapshot, world.snapshot, level=3)
        with self.assertRaises(ValueError):
            capture_completed_level(self.snapshot, world.snapshot, level=1)

    def test_rejects_unchecked_facts_and_raw_evidence(self) -> None:
        world = WorldModelStore("game-1", 42, 3)
        evidence = EvidenceRef(frame_id="private-frame")
        fact = world.record_hypothesis("mechanics", "controls", "secret", level=0, evidence=evidence)
        with self.assertRaises(ValueError):
            save_playbook(self.root, replace(self.snapshot, confirmed_facts=(fact,)))
        confirmed = world.confirm("mechanics", "controls", evidence=evidence)
        with self.assertRaises(ValueError):
            save_playbook(self.root, replace(self.snapshot, confirmed_facts=(confirmed,)))


if __name__ == "__main__":
    unittest.main()
