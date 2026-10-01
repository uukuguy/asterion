"""Synthetic end-to-end checks for semantic P7 experience learning."""

from __future__ import annotations

import tempfile
import json
import unittest

from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.mechanism_model import MechanismSpec
from asterion.applications.prime.p7.operator import _P7BrokerClient
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


class _CrossLevelMotionEngine:
    """One observed motion rule remains valid after each level transition."""

    game_id = "synthetic-cross-level-motion"
    seed = 0
    win_levels = 3

    def __init__(self) -> None:
        self.position = 1
        self.levels_completed = 0
        self.calls: list[str] = []

    def observe(self) -> dict[str, object]:
        row = [0] * 8
        row[self.position] = 7
        return {
            "available_actions": ["ACTION1"],
            "frame": [[row]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str) -> dict[str, object]:
        if action != "ACTION1":
            raise RuntimeError(action)
        self.calls.append(action)
        self.position += 1
        self.levels_completed += 1
        return self.observe()


class _AutoPromotionEngine:
    """Repeated motion plus a level transition supplies all model evidence."""

    game_id = "synthetic-auto-promotion"
    seed = 0
    win_levels = 2

    def __init__(self) -> None:
        self.position = 1
        self.levels_completed = 0
        self.calls: list[str] = []

    def observe(self) -> dict[str, object]:
        row = [0] * 8
        row[self.position] = 7
        return {
            "available_actions": ["ACTION1", "ACTION2"],
            "frame": [[row]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str) -> dict[str, object]:
        if action not in {"ACTION1", "ACTION2"}:
            raise RuntimeError(action)
        self.calls.append(action)
        if action == "ACTION1":
            self.position += 1
        else:
            self.levels_completed += 1
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
    def test_repeated_effects_auto_promote_evidence_scoped_model_for_search(self) -> None:
        engine = _AutoPromotionEngine()
        game = P7GameSelection(
            engine.game_id,
            engine.seed,
            target_level=2,
            _metadata_baseline_actions=(3, 1),
            _metadata_win_levels=engine.win_levels,
        )
        broker = ArcBroker(
            engine=engine,
            game=game,
            world_model=WorldModelStore(
                engine.game_id, engine.seed, engine.win_levels,
            ),
        )
        broker.bind_history("synthetic-auto-promotion-run")

        for expected_x in (2, 3):
            result = broker.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": expected_x, "y": 0, "value": 7}},
            }])
            self.assertEqual(result["stop_reason"], "matched")

        transition = broker.act_checked([{
            "action": {"name": "ACTION2", "data": {}},
            "expect": {"levels_completed": 1},
        }])
        self.assertEqual(transition["stop_reason"], "level-advanced")
        status = broker.simulator_status()
        self.assertTrue(status["confirmed_model"])
        self.assertEqual(status["status"], "verified")
        self.assertEqual(broker.retrodiction_status()["planner"]["eligible"], True)
        self.assertEqual(
            broker.experience_diagnostics()["probes_submitted"],
            0,
        )

        snapshot = broker.export_playbook(successful=False)
        warm_engine = _AutoPromotionEngine()
        warm_game = P7GameSelection(
            warm_engine.game_id,
            warm_engine.seed,
            target_level=1,
            _metadata_baseline_actions=(3, 1),
            _metadata_win_levels=warm_engine.win_levels,
        )
        warm = ArcBroker(
            engine=warm_engine,
            game=warm_game,
            world_model=WorldModelStore(
                warm_engine.game_id, warm_engine.seed, warm_engine.win_levels,
            ),
        )
        warm.bind_history("synthetic-auto-promotion-warm")
        warm.load_playbook(snapshot)
        self.assertTrue(warm.simulator_status()["confirmed_model"])
        calls_before_search = tuple(warm_engine.calls)
        search = warm.model_search()
        self.assertEqual(search["status"], "found")
        self.assertEqual(search["plan"][0]["action"], {"name": "ACTION2", "data": {}})
        self.assertEqual(tuple(warm_engine.calls), calls_before_search)
        stale_context = dict(search["context"])
        stale_context["prefix_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ArcBrokerError):
            warm.act_checked({"plan": search["plan"], "context": stale_context})
        completed = warm.act_checked({"plan": search["plan"], "context": search["context"]})
        self.assertEqual(completed["stop_reason"], "level-advanced")
        self.assertTrue(completed["plan_context_used"])
        self.assertEqual(completed["observation"].levels_completed, 1)
        self.assertEqual(warm_engine.calls, ["ACTION2"])

    def test_induced_cross_level_model_promotes_and_searches_without_manual_rules(self) -> None:
        engine = _CrossLevelMotionEngine()
        game = P7GameSelection(
            engine.game_id,
            engine.seed,
            target_level=3,
            _metadata_baseline_actions=(1, 1, 1),
            _metadata_win_levels=engine.win_levels,
        )
        broker = ArcBroker(
            engine=engine,
            game=game,
            world_model=WorldModelStore(
                engine.game_id, engine.seed, engine.win_levels,
            ),
        )
        broker.bind_history("synthetic-cross-level-run")

        first = broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"levels_completed": 1},
        }])
        self.assertEqual(first["stop_reason"], "level-advanced")

        prior = next(
            item for item in broker.mechanism_candidates()
            if item.get("scope") == "cross-level-prior"
        )
        payload = prior["record_hypothesis"]
        self.assertEqual(payload["value"]["mechanism"]["rules"][0]["guards"], [])
        self.assertEqual(
            payload["value"]["probe"]["action"],
            {"name": "ACTION1", "data": {}},
        )

        broker.record_hypothesis(
            payload["layer"],
            payload["key"],
            payload["value"],
        )
        second = broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": payload["value"]["probe"]["expect"],
        }])
        self.assertEqual(second["stop_reason"], "level-advanced")
        self.assertTrue(broker.simulator_status()["confirmed_model"])
        self.assertTrue(broker.retrodiction_status()["planner"]["eligible"])
        self.assertIn(
            payload["key"],
            broker.world_model().mechanics,
        )

        calls_before_search = tuple(engine.calls)
        search = broker.model_search()
        self.assertEqual(search["status"], "found")
        self.assertEqual(search["plan"][0]["action"], {"name": "ACTION1", "data": {}})
        self.assertEqual(search["plan"][0]["expect"]["levels_completed"], 3)
        self.assertEqual(tuple(engine.calls), calls_before_search)

        completed = broker.act_checked(search["plan"])
        self.assertEqual(completed["stop_reason"], "level-advanced")
        self.assertEqual(completed["observation"].levels_completed, 3)
        self.assertEqual(engine.calls, ["ACTION1", "ACTION1", "ACTION1"])

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
        # The broker may already have auto-promoted the repeated observed
        # motion before this optional explicit probe is submitted.
        self.assertEqual(broker.simulator_status()["status"], "verified")
        probe_result = broker.act_checked([_move_expectation(4)])
        self.assertEqual(probe_result["stop_reason"], "matched")
        hint = broker.learning_hint()
        self.assertEqual(hint["recommendation"], "use_verified_model")
        automatic_plan = hint["verified_model_plan"]
        self.assertEqual(automatic_plan["status"], "found")
        self.assertTrue(automatic_plan["plan"])
        self.assertIn("context", automatic_plan)
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
            self.assertTrue(fresh.simulator_status()["confirmed_model"])
            self.assertTrue(fresh.retrodiction_status()["planner"]["eligible"])
            warm_search = fresh.model_search()
            self.assertEqual(warm_search["status"], "found")
            self.assertEqual(fresh_engine.calls, [])
            warm_result = fresh.act_checked(warm_search["plan"])
            self.assertEqual(warm_result["observation"].levels_completed, 1)

        self.assertEqual(engine.calls, ["ACTION1", "ACTION1", "ACTION1", "ACTION2"])

    def test_experience_diagnostics_separate_learning_from_execution(self) -> None:
        broker, _engine = self._collect_two_effects()
        before = broker.experience_diagnostics()
        self.assertEqual(before["effects_count"], 2)
        self.assertGreaterEqual(before["candidate_count"], 1)
        self.assertEqual(before["probes_submitted"], 0)
        self.assertEqual(before["model_search_calls"], 0)
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
        broker.record_hypothesis(
            "mechanics", "diagnostics-model",
            {"mechanism": mechanism, "probe": _move_expectation(4), "dependencies": []},
        )
        pending = broker.experience_diagnostics()
        self.assertEqual(pending["probes_submitted"], 1)
        self.assertTrue(pending["probe_pending"])
        broker.act_checked([_move_expectation(4)])
        search = broker.model_search()
        self.assertEqual(search["status"], "found")
        after = broker.experience_diagnostics()
        self.assertEqual(after["probes_submitted"], 1)
        self.assertFalse(after["probe_pending"])
        self.assertEqual(after["model_search_calls"], 1)
        self.assertEqual(after["model_search_found"], 1)
        self.assertTrue(after["planner_eligible"])

    def test_candidate_exposes_a_valid_record_hypothesis_payload(self) -> None:
        broker, engine = self._collect_two_effects()
        candidate = next(
            item for item in broker.mechanism_candidates()
            if item.get("compiled_mechanism") and item["key"] != "experience.induced.bundle"
        )
        payload = candidate.get("record_hypothesis")
        self.assertIsInstance(payload, dict)
        self.assertEqual(set(payload), {"layer", "key", "value"})
        self.assertEqual(payload["layer"], "mechanics")
        self.assertIsInstance(payload["key"], str)
        self.assertRegex(payload["key"], r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
        value = payload["value"]
        self.assertIsInstance(value, dict)
        self.assertEqual(set(value), {"mechanism", "probe", "dependencies"})
        self.assertEqual(value["mechanism"], candidate["compiled_mechanism"])
        self.assertEqual(value["dependencies"], [])

        result = broker.record_hypothesis(payload["layer"], payload["key"], value)
        self.assertEqual(result["status"], "hypothesis")
        probe = value["probe"]
        checked = broker.act_checked([probe])
        self.assertEqual(checked["stop_reason"], "matched")
        self.assertEqual(engine.calls, ["ACTION1", "ACTION1", "ACTION1"])

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

    def test_large_candidate_submission_survives_model_tool_projection(self) -> None:
        class LargeTokenEngine(_LearningEngine):
            def observe(self):
                observation = super().observe()
                frame = [[0] * 64 for _ in range(16)]
                for y in range(4, 15):
                    for x in range(self.position, self.position + 18):
                        frame[y][x] = 7
                observation["frame"] = [frame]
                return observation

        engine = LargeTokenEngine()
        broker = ArcBroker(engine=engine, game=_game(), world_model=_world())
        broker.bind_history("large-submission")
        for x in (19, 20):
            broker.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": x, "y": 4, "value": 7}},
            }])
        self.assertGreater(len(json.dumps(broker.mechanism_candidates(), separators=(",", ":")).encode()), 8192)
        client = _P7BrokerClient(broker, None)
        candidates = client.mechanism_candidates()
        self.assertLessEqual(len(json.dumps(candidates, separators=(",", ":")).encode()), 8192)
        payloads = [row["record_hypothesis"] for row in candidates if "record_hypothesis" in row]
        self.assertTrue(payloads)
        payload = payloads[0]
        self.assertEqual(client.record_hypothesis(**payload)["status"], "hypothesis")
        self.assertEqual(broker.act_checked([payload["value"]["probe"]])["stop_reason"], "matched")
        self.assertTrue(broker.simulator_status()["confirmed_model"])
        self.assertEqual(len(engine.calls), 3)

    def test_previous_level_motion_is_exposed_as_current_level_probe_prior(self) -> None:
        source = ArcBroker(engine=_LearningEngine(), game=_game(), world_model=_world())
        source.bind_history("cross-level-source")
        source.act_checked([_move_expectation(2)])
        source.act_checked([_move_expectation(3)])
        snapshot = source.export_playbook(successful=False)

        fresh = ArcBroker(engine=_LearningEngine(), game=_game(), world_model=_world())
        fresh.bind_history("cross-level-target")
        fresh.load_playbook(snapshot)
        advanced = fresh.act_checked([{
            "action": {"name": "ACTION2", "data": {}},
            "expect": {"levels_completed": 1},
        }])
        self.assertEqual(advanced["stop_reason"], "level-advanced")
        prior = [
            item for item in fresh.mechanism_candidates()
            if item.get("scope") == "cross-level-prior"
        ]
        self.assertTrue(prior)
        self.assertTrue(any(item.get("record_hypothesis") for item in prior))
        self.assertEqual(fresh.learning_hint().get("cross_level_candidate_count"), len(prior))


if __name__ == "__main__":
    unittest.main()
