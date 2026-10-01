from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.operator import _P7BrokerClient
from asterion.applications.prime.p7.ipython_host import p7_client_facade
from asterion.applications.prime.p7.playbook import (
    CheckedFact, PlaybookKey, PlaybookSnapshot, load_playbook, save_playbook,
)
from asterion.applications.prime.p7.world_model import WorldModelStore
from asterion.applications.prime.p7.experience_induction import ActionEffect, EffectHypothesis, EffectMotion


class _LearningEngine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 7

    def __init__(self) -> None:
        self.calls: list[str] = []

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION2"],
            "frame": [[[len(self.calls), 0]]],
            "levels_completed": 0,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        return self.observe()


class _TranslationEngine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 7

    def __init__(self) -> None:
        self.offset = 0

    def observe(self) -> dict[str, object]:
        row = [0, 0, 0, 0, 0, 0]
        row[self.offset] = 7
        return {
            "available_actions": ["ACTION1"],
            "frame": [[row]],
            "levels_completed": 0,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def step(self, action: str) -> dict[str, object]:
        if action != "ACTION1":
            raise AssertionError(action)
        self.offset += 1
        return self.observe()


class _TransitionTranslationEngine(_TranslationEngine):
    def __init__(self) -> None:
        super().__init__()
        self.level = 0

    def observe(self) -> dict[str, object]:
        observation = super().observe()
        observation["levels_completed"] = self.level
        return observation

    def step(self, action: str) -> dict[str, object]:
        observation = super().step(action)
        self.level = 1
        observation["levels_completed"] = self.level
        return observation


class ExperienceEndToEndTests(unittest.TestCase):
    def test_export_fit_keeps_recent_experience_under_playbook_cap(self) -> None:
        facts = tuple(
            CheckedFact(
                "mechanics",
                f"experience.effect.{index:03d}",
                {
                    "sequence": index,
                    "motion_complete": index % 2 == 0,
                    "details": ["x" * 1000] * 3,
                },
                0,
                (f"{index + 1:064x}",),
            )
            for index in range(120)
        )
        snapshot = PlaybookSnapshot(
            PlaybookKey("ls20-9607627b", 0, 7), effect_summaries=facts,
        )
        fitted = ArcBroker._fit_experience_playbook(snapshot)
        self.assertLessEqual(len(fitted.effect_summaries), 96)
        self.assertLessEqual(
            len(json.dumps(fitted.projection(max_bytes=256 * 1024), separators=(",", ":")).encode()),
            256 * 1024,
        )
        sequences = {item.value["sequence"] for item in fitted.effect_summaries}
        self.assertIn(119, sequences)

    def test_export_bounds_large_motion_detail_without_dropping_playbook(self) -> None:
        broker = ArcBroker(engine=_LearningEngine())
        broker.bind_history("large-motion-run")
        frame_digest = "sha256:" + "a" * 64
        broker._experience_inducer._effects.append(ActionEffect(
            game_id=_LearningEngine.game_id,
            seed=0,
            run_id="large-motion-run",
            sequence=1,
            level=0,
            levels_completed=0,
            state="NOT_FINISHED",
            action="ACTION1",
            data=(),
            before_state_sha256=frame_digest,
            after_state_sha256=frame_digest,
            before_frame_sha256=frame_digest,
            after_frame_sha256=frame_digest,
            changed_cell_count=300,
            changed_cells=(),
            changed_cells_omitted=300,
            outcome="changed",
            components=(),
            motions=(EffectMotion(
                7, 0, tuple((x, 0) for x in range(300)), 1, 0, 1,
            ),),
            motion_complete=True,
        ))
        long_key = "candidate-" + "x" * 2048
        broker._experience_inducer._candidates[long_key] = EffectHypothesis(
            key=long_key,
            game_id=_LearningEngine.game_id,
            seed=0,
            level=0,
            action_family="keyboard",
            action="ACTION1",
            data=(),
            signature="s" * 2048,
            status="hypothesis",
            evidence_sequences=(1,),
            conflict_sequences=(),
            template=None,
            win_levels=7,
        )

        snapshot = broker.export_playbook(successful=False)
        effect = snapshot.effect_summaries[0].value
        self.assertTrue(effect["details_omitted"])
        candidate = snapshot.candidate_summaries[0].value
        self.assertTrue(candidate["details_omitted"])
        self.assertTrue(candidate["key"].startswith("sha256:"))
        with tempfile.TemporaryDirectory() as directory:
            save_playbook(Path(directory), snapshot)
            loaded = load_playbook(Path(directory), snapshot.key)
            self.assertIsNotNone(loaded)

    def test_learning_hint_does_not_recommend_stale_level_candidates(self) -> None:
        source = ArcBroker(engine=_TranslationEngine())
        source.bind_history("learning-run")
        source.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 1, "y": 0, "value": 7}},
        }])
        snapshot = source.export_playbook(successful=False)

        broker = ArcBroker(engine=_TransitionTranslationEngine())
        broker.bind_history("level-one-run")
        broker.load_playbook(snapshot)
        broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"levels_completed": 1},
        }])
        hint = broker.learning_hint()

        self.assertEqual(hint["recommendation"], "inspect_candidate_and_probe")
        self.assertEqual(hint["compiled_candidates"], [])
        self.assertEqual(hint["current_candidate_count"], 0)
        self.assertGreater(hint.get("cross_level_candidate_count", 0), 0)
        self.assertGreater(hint["stale_candidate_count"], 0)
        self.assertTrue(hint["candidate_previews"])
        self.assertEqual(hint["candidate_previews"][0]["scope"], "cross-level-prior")

    def test_observation_surfaces_compiled_learning_hint_without_route_authority(self) -> None:
        broker = ArcBroker(engine=_TranslationEngine())
        broker.bind_history("learning-run")
        for expected_x in (1, 2):
            broker.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": expected_x, "y": 0, "value": 7}},
            }])
        hint = broker.learning_hint()
        self.assertEqual(hint["recommendation"], "inspect_candidate_and_probe")
        self.assertEqual(hint["execution_authority"], "none")
        self.assertTrue(hint["compiled_candidates"])
        self.assertLessEqual(len(json.dumps(hint).encode()), 1024)
        self.assertNotIn("plan", hint["compiled_candidates"][0])

        status = _P7BrokerClient(broker, None).status()
        self.assertEqual(status["learning_hint"]["recommendation"], "inspect_candidate_and_probe")
        # The bridge may truncate a large frame response.  The bounded hint
        # must therefore precede the frame-bearing fields in the wire mapping.
        observed = _P7BrokerClient(broker, None).observe()
        self.assertEqual(next(iter(observed)), "learning_hint")
        candidates = broker.mechanism_candidates()
        bundle = next(item for item in candidates if item["key"] == "experience.induced.bundle")
        self.assertEqual(candidates[0]["key"], "experience.induced.bundle")
        self.assertEqual(bundle["source"], "induced-bundle")
        self.assertNotIn("plan", bundle["compiled_mechanism"])

    def test_learning_evidence_survives_playbook_reload_without_planner_authority(self) -> None:
        engine = _LearningEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("learning-run")
        broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
        }])
        self.assertEqual(len(broker.action_effects()), 1)
        self.assertEqual(broker.simulator_status()["confirmed_model"], False)
        self.assertEqual(engine.calls, ["ACTION1"])
        snapshot = broker.export_playbook(successful=False)
        self.assertEqual(len(snapshot.effect_summaries), 1)
        self.assertEqual(len(snapshot.candidate_summaries), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_playbook(root, snapshot)
            loaded = load_playbook(root, snapshot.key)
            self.assertIsNotNone(loaded)
            engine2 = _LearningEngine()
            fresh = ArcBroker(engine=engine2)
            fresh.bind_history("new-run")
            fresh.load_playbook(loaded)
            persisted = fresh.mechanism_candidates()
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["status"], "hypothesis")
            self.assertEqual(fresh.simulator_status()["confirmed_model"], False)
            self.assertEqual(engine2.calls, [])

    def test_reloaded_same_level_candidate_is_a_reusable_probe_prior(self) -> None:
        source = ArcBroker(engine=_TranslationEngine())
        source.bind_history("learning-run")
        for expected_x in (1, 2):
            source.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": expected_x, "y": 0, "value": 7}},
            }])
        snapshot = source.export_playbook(successful=False)

        fresh = ArcBroker(
            engine=_TranslationEngine(),
            world_model=WorldModelStore(_TranslationEngine.game_id, 0, _TranslationEngine.win_levels),
        )
        fresh.bind_history("new-run")
        fresh.load_playbook(snapshot)

        hint = fresh.learning_hint()
        self.assertEqual(hint["current_candidate_count"], 1)
        self.assertEqual(hint["stale_candidate_count"], 0)
        self.assertEqual(hint["recommendation"], "inspect_candidate_and_probe")
        self.assertTrue(hint["compiled_candidates"])
        candidate = fresh.mechanism_candidates()[0]
        self.assertEqual(candidate["source"], "playbook")
        self.assertEqual(candidate["status"], "hypothesis")
        self.assertIn("compiled_mechanism", candidate)
        plan = fresh.probe_plan()
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["action"], {"name": "ACTION1", "data": {}})

    def test_reloaded_candidate_can_be_retro_verified_without_route_injection(self) -> None:
        source = ArcBroker(engine=_TranslationEngine())
        source.bind_history("learning-run")
        for expected_x in (1, 2):
            source.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": expected_x, "y": 0, "value": 7}},
            }])
        snapshot = source.export_playbook(successful=False)

        fresh = ArcBroker(
            engine=_TranslationEngine(),
            world_model=WorldModelStore(_TranslationEngine.game_id, 0, _TranslationEngine.win_levels),
        )
        fresh.bind_history("new-run")
        fresh.load_playbook(snapshot)
        candidate = fresh.mechanism_candidates()[0]
        mechanism = dict(candidate["compiled_mechanism"])
        mechanism["revision"] = 1
        fresh.record_hypothesis(
            "mechanics",
            "persisted-controls",
            {
                "mechanism": mechanism,
                "probe": {
                    "action": {"name": "ACTION1", "data": {}},
                    "expect": {"cell": {"x": 1, "y": 0, "value": 7}},
                },
                "dependencies": [],
            },
        )
        result = fresh.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 1, "y": 0, "value": 7}},
        }])
        self.assertEqual(result["stop_reason"], "matched")
        self.assertEqual(fresh.simulator_status()["status"], "verified")
        self.assertTrue(fresh.retrodiction_status()["planner"]["eligible"])

    def test_export_playbook_preserves_prior_experience_across_runs(self) -> None:
        source = ArcBroker(engine=_TranslationEngine())
        source.bind_history("learning-run-1")
        source.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 1, "y": 0, "value": 7}},
        }])
        first = source.export_playbook(successful=False)

        resumed = ArcBroker(engine=_TranslationEngine())
        resumed.bind_history("learning-run-2")
        resumed.load_playbook(first)
        resumed.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 1, "y": 0, "value": 7}},
        }])
        second = resumed.export_playbook(successful=False)

        self.assertGreaterEqual(len(second.effect_summaries), 2)
        self.assertGreaterEqual(len(second.candidate_summaries), 1)

    def test_ipython_facade_exposes_induction_queries(self) -> None:
        broker = ArcBroker(engine=_TranslationEngine())
        broker.bind_history("learning-run")
        facade = p7_client_facade(_P7BrokerClient(broker, None))
        self.assertIsInstance(facade.action_effects(), list)
        self.assertIsInstance(facade.mechanism_candidates(), list)
        self.assertIsInstance(facade.probe_plan(), dict)
        self.assertIsInstance(facade.simulator_status(), dict)


if __name__ == "__main__":
    unittest.main()
