import unittest

from asterion.applications.prime.p7.world_model import (
    EvidenceRef,
    WorldModelStore,
)


class WorldModelTests(unittest.TestCase):
    def setUp(self):
        self.ev = EvidenceRef(frame_id="frame-1", source_run="run-1")

    def test_rejects_malformed_identity_layers_values_and_evidence(self):
        for args in (("", 1, 2), ("bad id", 1, 2), ("game", -1, 2), ("game", 1, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                WorldModelStore(*args)
        store = WorldModelStore("game", 1, 2)
        with self.assertRaises(ValueError):
            store.record_hypothesis("unknown", "x", 1, level=0, evidence=self.ev)
        with self.assertRaises((TypeError, ValueError)):
            store.record_hypothesis("mechanics", "x", {1: "bad"}, level=0, evidence=self.ev)
        with self.assertRaises((TypeError, ValueError)):
            store.record_hypothesis("mechanics", "x", {"x": object()}, level=0, evidence=self.ev)
        with self.assertRaises(ValueError):
            store.record_hypothesis("mechanics", "x", 1, level=0, evidence=[])

    def test_hypothesis_is_detached_capped_and_confirm_requires_match(self):
        store = WorldModelStore("game", 1, 2)
        original = {"nested": [1]}
        fact = store.record_hypothesis("mechanics", "move", original, level=0, evidence=self.ev)
        original["nested"].append(2)
        self.assertEqual(fact.value, {"nested": [1]})
        with self.assertRaises(ValueError):
            store.record_hypothesis("mechanics", "move", 1, level=0, evidence=self.ev)
        with self.assertRaises(ValueError):
            store.confirm("mechanics", "move", observed_value=2, evidence=self.ev)
        self.assertEqual(store.confirm("mechanics", "move", evidence=self.ev).status, "confirmed")
        self.assertIn("move", store.mechanics)

    def test_refresh_keeps_mechanics_and_removes_only_old_level_local_facts(self):
        store = WorldModelStore("game", 1, 3)
        store.record_hypothesis("mechanics", "rules", "x", level=0, evidence=self.ev)
        store.confirm("mechanics", "rules", evidence=self.ev)
        store.record_hypothesis("entities", "player", {"x": 1}, level=0, evidence=self.ev)
        store.confirm("entities", "player", evidence=self.ev)
        store.record_hypothesis("relations", "door", "open", level=1, evidence=self.ev)
        store.confirm("relations", "door", evidence=self.ev)
        refreshed = store.refresh_level(1)
        self.assertIn("rules", refreshed.mechanics)
        self.assertNotIn("player", refreshed.entities)
        self.assertIn("door", refreshed.relations)

    def test_conflict_returns_branch_without_mutating_parent_or_confirmed_fact(self):
        store = WorldModelStore("game", 1, 2)
        store.record_hypothesis("entities", "player", {"x": 1}, level=0, evidence=self.ev)
        store.confirm("entities", "player", evidence=self.ev)
        parent = store.snapshot
        child = store.conflict("entities", "player", observed_value={"x": 2}, evidence=self.ev)
        self.assertEqual(parent.conflicts, ())
        self.assertEqual(parent.entities["player"].value, {"x": 1})
        self.assertEqual(child.entities["player"].status, "confirmed")
        self.assertEqual(len(child.conflicts), 1)
        self.assertEqual(child.conflicts[0].value, {"x": 2})

    def test_projection_is_sorted_detached_redacted_and_bounded(self):
        store = WorldModelStore("game", 1, 2)
        store.record_hypothesis("mechanics", "x", {"a": 1}, level=0, evidence=self.ev)
        projection = store.projection()
        self.assertNotIn("x", projection["confirmed"]["mechanics"])
        projection["hypotheses"]["mechanics:x"]["value"]["a"] = 9
        self.assertEqual(store.snapshot.hypotheses["mechanics:x"].value["a"], 1)
        with self.assertRaises(ValueError):
            store.projection(10)
        self.assertNotIn("run-1", repr(projection))


if __name__ == "__main__":
    unittest.main()
