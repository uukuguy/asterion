"""Synthetic end-to-end checks for semantic P7 experience learning."""

from __future__ import annotations

import tempfile
import unittest

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.mechanism_model import MechanismSpec
from asterion.applications.prime.p7.playbook import PlaybookKey, load_playbook, save_playbook
from asterion.applications.prime.p7.world_model import WorldModelStore
from asterion.applications.prime.p7.experience_induction import (
    ActionEffect,
    EffectMotion,
    ExperienceInducer,
)


class _LearningEngine:
    """A small real transition source: ACTION1 moves a token; ACTION2 advances."""

    game_id = "synthetic-learning"
    seed = 1
    win_levels = 2

    def __init__(self, *, contradict_probe: bool = False) -> None:
        self.position = 1
        self.levels_completed = 0
        self.contradict_probe = contradict_probe
        self.calls: list[str] = []

    def observe(self) -> dict[str, object]:
        frame = [0] * 8
        frame[self.position] = 7
        return {
            "available_actions": ["ACTION1", "ACTION2"],
            "frame": [[frame]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        if action == "ACTION1":
            if self.contradict_probe and len(self.calls) == 3:
                self.position = min(7, self.position + 2)
            else:
                self.position = min(7, self.position + 1)
        elif action == "ACTION2":
            self.levels_completed += 1
        else:
            raise RuntimeError(action)
        return self.observe()


def _game() -> P7GameSelection:
    return P7GameSelection(
        _LearningEngine.game_id,
        _LearningEngine.seed,
        target_level=1,
        _metadata_baseline_actions=(1, 1),
        _metadata_win_levels=2,
    )


def _world() -> WorldModelStore:
    return WorldModelStore(_LearningEngine.game_id, _LearningEngine.seed, 2)


def _move_expectation(x: int) -> dict[str, object]:
    return {
        "action": {"name": "ACTION1", "data": {}},
        "expect": {"cell": {"x": x, "y": 0, "value": 7}},
    }


class ExperienceLearningTests(unittest.TestCase):
    def test_translation_candidate_survives_bounded_edge_delta_variation(self) -> None:
        def effect(sequence: int, count: int) -> ActionEffect:
            return ActionEffect(
                game_id="edge-motion",
                seed=0,
                run_id="edge-motion-run",
                sequence=sequence,
                level=0,
                levels_completed=0,
                state="NOT_FINISHED",
                action="ACTION2",
                data=(),
                before_state_sha256=f"state-{sequence}",
                after_state_sha256=f"state-after-{sequence}",
                before_frame_sha256=f"frame-{sequence}",
                after_frame_sha256=f"frame-after-{sequence}",
                changed_cell_count=count + 1,
                changed_cells=(),
                changed_cells_omitted=count + 1,
                outcome="changed",
                components=(),
                motions=(EffectMotion(9, 12, ((0, 0), (1, 0)), 0, 4, count),),
                motion_complete=True,
            )

        inducer = ExperienceInducer(win_levels=1)
        inducer.observe(effect(1, 160))
        inducer.observe(effect(2, 161))
        candidates = inducer.candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "hypothesis")
        self.assertEqual(candidates[0].support_count, 2)

    def _collect_two_effects(self, *, contradict_probe: bool = False) -> tuple[ArcBroker, _LearningEngine]:
        engine = _LearningEngine(contradict_probe=contradict_probe)
        broker = ArcBroker(engine=engine, game=_game(), world_model=_world())
        broker.bind_history("synthetic-learning-run")
        broker.act_checked([_move_expectation(2)])
        broker.act_checked([_move_expectation(3)])
        candidates = broker.mechanism_candidates()
        self.assertEqual(len(candidates), 2)
        self.assertTrue(any(item.get("compiled_mechanism") for item in candidates))
        return broker, engine

    def test_effect_candidate_probe_certificate_search_and_playbook_reload(self) -> None:
        broker, engine = self._collect_two_effects()
        candidate = next(
            item for item in broker.mechanism_candidates()
            if item.get("compiled_mechanism") and item["key"] != "experience.induced.bundle"
        )
        mechanism = dict(candidate["compiled_mechanism"])
        mechanism["revision"] = 1
        mechanism["rules"] = [
            *mechanism["rules"],
            {
                "action": "ACTION2",
                "guards": [{"op": "level_is", "args": {"value": 0}}],
                "effects": [{"op": "increment_level", "args": {"value": 1}}],
            },
        ]
        self.assertIsInstance(MechanismSpec.from_mapping(mechanism), MechanismSpec)

        broker.record_hypothesis(
            "mechanics",
            "synthetic-controls",
            {
                "mechanism": mechanism,
                "probe": _move_expectation(4),
                "dependencies": [],
            },
        )
        self.assertEqual(broker.simulator_status()["status"], "hypothesis")
        probe_result = broker.act_checked([_move_expectation(4)])
        self.assertEqual(probe_result["stop_reason"], "matched")
        self.assertEqual(broker.simulator_status()["status"], "verified")
        self.assertTrue(broker.retrodiction_status()["planner"]["eligible"])

        search = broker.model_search()
        self.assertEqual(search["status"], "found")
        self.assertEqual(search["plan"][0]["action"]["name"], "ACTION2")
        self.assertEqual(search["plan"][0]["expect"]["levels_completed"], 1)

        checked = broker.act_checked(search["plan"])
        self.assertEqual(checked["stop_reason"], "level-advanced")
        self.assertEqual(checked["observation"].levels_completed, 1)
        snapshot = broker.export_playbook(successful=True)
        self.assertTrue(any(f.key == "synthetic-controls" for f in snapshot.confirmed_facts))

        with tempfile.TemporaryDirectory() as directory:
            from pathlib import Path

            root = Path(directory)
            save_playbook(root, snapshot)
            reloaded = load_playbook(root, PlaybookKey(_LearningEngine.game_id, 1, 2))
            self.assertIsNotNone(reloaded)
            fresh_engine = _LearningEngine()
            fresh = ArcBroker(engine=fresh_engine, game=_game(), world_model=_world())
            fresh.bind_history("synthetic-learning-reload")
            fresh.load_playbook(reloaded)
            self.assertFalse(fresh.simulator_status()["confirmed_model"])
            fresh.act_checked([_move_expectation(2)])
            fresh.act_checked([_move_expectation(3)])
            self.assertTrue(fresh.simulator_status()["confirmed_model"])
            self.assertTrue(fresh.retrodiction_status()["planner"]["eligible"])

        self.assertEqual(engine.calls, ["ACTION1", "ACTION1", "ACTION1", "ACTION2"])

    def test_contradictory_probe_invalidates_the_candidate_certificate(self) -> None:
        broker, _engine = self._collect_two_effects(contradict_probe=True)
        candidate = next(
            item for item in broker.mechanism_candidates()
            if item.get("compiled_mechanism") and item["key"] != "experience.induced.bundle"
        )
        mechanism = dict(candidate["compiled_mechanism"])
        mechanism["revision"] = 1
        broker.record_hypothesis(
            "mechanics",
            "synthetic-controls",
            {
                "mechanism": mechanism,
                "probe": _move_expectation(4),
                "dependencies": [],
            },
        )
        result = broker.act_checked([_move_expectation(4)])
        self.assertEqual(result["stop_reason"], "model-conflict")
        self.assertFalse(broker.simulator_status()["confirmed_model"])
        self.assertEqual(broker.retrodiction_status()["planner"]["eligible"], False)


if __name__ == "__main__":
    unittest.main()
