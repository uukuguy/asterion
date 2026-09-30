"""Native P7 broker boundary tests; no legacy gateway is involved."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import unittest


class _Engine:
    def __init__(
        self,
        *,
        level_after: int | None = None,
        second_level_after: int | None = None,
        raises_on: int | None = None,
        game_id: str = "ls20-9607627b",
        seed: int = 0,
        win_levels: int = 7,
        remove_second_after_first: bool = False,
        game_over_after: int | None = None,
    ) -> None:
        self.level_after = level_after
        self.second_level_after = second_level_after
        self.raises_on = raises_on
        self.game_id = game_id
        self.seed = seed
        self.win_levels = win_levels
        self.remove_second_after_first = remove_second_after_first
        self.game_over_after = game_over_after
        self.calls: list[str] = []
        self.levels_completed = 0
        self.observe_calls = 0

    def observe(self) -> dict[str, object]:
        self.observe_calls += 1
        available = ["ACTION1", "ACTION2", "ACTION3"]
        if self.remove_second_after_first and self.calls:
            available.remove("ACTION2")
        return {
            "available_actions": available,
            "frame": [[[len(self.calls) % 10, 1]]],
            "levels_completed": self.levels_completed,
            "state": "GAME_OVER" if self.game_over_after == len(self.calls) else "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        if self.raises_on == len(self.calls):
            raise RuntimeError("engine interrupted after dispatch")
        if self.level_after == len(self.calls) or self.second_level_after == len(self.calls):
            self.levels_completed += 1
        return self.observe()


class _ResetEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self, *, reset_loses_level: bool = False, reset_stays_dead: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, int]]] = []
        self.levels_completed = 0
        self.state = "NOT_FINISHED"
        self.reset_loses_level = reset_loses_level
        self.reset_stays_dead = reset_stays_dead

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[len(self.calls)]]],
            "levels_completed": self.levels_completed,
            "state": self.state,
            "win_levels": 7,
        }

    def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
        self.calls.append((action, data or {}))
        if action == "RESET":
            self.state = "GAME_OVER" if self.reset_stays_dead else "NOT_FINISHED"
            if self.reset_loses_level:
                self.levels_completed = 0
        elif self.levels_completed == 0:
            self.levels_completed = 1
        elif action == "ACTION1" and len(self.calls) == 2:
            self.state = "GAME_OVER"
        elif action == "ACTION1":
            self.levels_completed = 2
        return self.observe()


class _FullGameEngine(_Engine):
    def __init__(self, *, final_state: str = "WIN", actions_per_level: int = 1) -> None:
        super().__init__()
        self.final_state = final_state
        self.actions_per_level = actions_per_level

    def observe(self) -> dict[str, object]:
        value = super().observe()
        if self.levels_completed == 7:
            value["state"] = self.final_state
        return value

    def step(self, action: str) -> dict[str, object]:
        self.calls.append(action)
        self.levels_completed = len(self.calls) // self.actions_per_level
        return self.observe()


class _HistoryEngine(_Engine):
    def observe(self) -> dict[str, object]:
        value = super().observe()
        value["available_actions"] = ["ACTION1"]
        value["frame"] = [[[len(self.calls)]]]
        return value


class _ModelEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self) -> None:
        self.levels_completed = 0

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1"],
            "frame": [[[0]]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": 2,
        }

    def step(self, action: str) -> dict[str, object]:
        if action != "ACTION1":
            raise RuntimeError("unexpected action")
        self.levels_completed += 1
        return self.observe()


class _LevelClickEngine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 2

    def __init__(self) -> None:
        self.levels_completed = 0

    def observe(self) -> dict[str, object]:
        size = 16
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[0 for _ in range(size)] for _ in range(size)]],
            "levels_completed": self.levels_completed,
            "state": "NOT_FINISHED",
            "win_levels": self.win_levels,
        }

    def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
        if action != "ACTION6":
            raise RuntimeError(action)
        self.levels_completed = 1
        return self.observe()


class _SettledNoEffectEngine(_Engine):
    """The engine's state digest changes while the settled grid stays put."""

    def observe(self) -> dict[str, object]:
        value = super().observe()
        value["frame"] = [[[7]]]
        return value


def _broker(*, level_after: int | None = None, raises_on: int | None = None):
    from asterion.applications.prime.p7.broker import ArcBroker

    engine = _Engine(level_after=level_after, raises_on=raises_on)
    return ArcBroker(engine=engine), engine


class TestNativeP7Broker(unittest.TestCase):
    def test_model_search_does_not_reuse_prior_level_click_coordinates(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker

        engine = _LevelClickEngine()
        game = P7GameSelection(
            engine.game_id, engine.seed, target_level=2,
            _metadata_baseline_actions=(1, 1), _metadata_win_levels=2,
        )
        broker = ArcBroker(engine=engine, game=game)
        broker.bind_history("level-click-search")
        broker.act((ArcAction("ACTION6", (("x", 9), ("y", 9))),))

        actions = broker._model_search_actions()

        self.assertNotIn(
            {"name": "ACTION6", "data": {"x": 9, "y": 9}},
            actions,
        )
    def test_action_effects_and_candidates_are_learned_without_dispatching(self) -> None:
        broker, engine = _broker()
        broker.bind_history("run-effects")
        broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
        }])
        self.assertEqual(len(broker.action_effects()), 1)
        self.assertEqual(broker.action_effects()[0]["outcome"], "changed")
        self.assertEqual(len(broker.mechanism_candidates()), 1)
        self.assertEqual(broker.probe_plan()["status"], "no-discriminating-probe")
        self.assertEqual(engine.calls, ["ACTION1"])

    def test_world_model_and_transition_model_are_updated_after_bound_transition(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.world_model import WorldModelStore

        engine = _Engine()
        world = WorldModelStore(engine.game_id, engine.seed, engine.win_levels)
        broker = ArcBroker(engine=engine, world_model=world)
        broker.bind_history("run-1")
        result = broker.act_checked([
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}},
        ])
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["retrodiction"]["status"], "observed")
        self.assertIsNotNone(broker.world_model())
        self.assertIsNotNone(broker.transition_model())
        self.assertEqual(len(broker.world_evidence()), 1)
        projection = broker.playbook_projection()
        projection["mutated"] = True
        self.assertNotIn("mutated", broker.playbook_projection())

    def test_model_search_requires_a_retrodicted_mechanism_certificate(self) -> None:
        broker, _ = _broker()
        broker.bind_history("run-search-gate")

        result = broker.model_search()

        self.assertEqual(result["status"], "model-unavailable")
        self.assertEqual(result["reason"], "no-planner-certificate")

    def test_model_search_returns_plan_only_after_probe_is_retrodicted(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.world_model import WorldModelStore

        engine = _ModelEngine()
        game = P7GameSelection(
            engine.game_id,
            engine.seed,
            target_level=2,
            _metadata_baseline_actions=(1, 1),
            _metadata_win_levels=2,
        )
        world = WorldModelStore(engine.game_id, engine.seed, 2)
        broker = ArcBroker(engine=engine, game=game, world_model=world)
        broker.bind_history("run-search-certified")
        mechanism = {
            "schema": "asterion.prime.p7-mechanism/v1",
            "game_id": engine.game_id,
            "seed": engine.seed,
            "win_levels": 2,
            "revision": 1,
            "rules": [{
                "action": "ACTION1",
                "guards": [],
                "effects": [{"op": "increment_level", "args": {"value": 1}}],
            }],
        }
        broker.record_hypothesis(
            "mechanics", "controls", {
                "mechanism": mechanism,
                "probe": {
                    "action": {"name": "ACTION1", "data": {}},
                    "expect": {"levels_completed": 1},
                },
                "dependencies": [],
            },
        )
        broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"levels_completed": 1},
        }])

        result = broker.model_search()

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["plan"][0]["expect"]["levels_completed"], 2)

    def test_checked_no_effect_returns_the_current_action_hint(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-no-effect-hint")

        result = broker.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 7}},
        }])

        self.assertEqual(result["stop_reason"], "observation-no-change")
        self.assertEqual(result["no_effect_hint"]["action"], "ACTION1")
        self.assertIsNone(result["no_effect_hint"]["position"])

    def test_initial_frame_generates_bounded_visual_hypotheses(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.world_model import WorldModelStore

        engine = _Engine()
        world = WorldModelStore(engine.game_id, engine.seed, engine.win_levels)
        broker = ArcBroker(engine=engine, world_model=world)
        broker.bind_history("run-visual")

        snapshot = broker.world_model()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertGreater(snapshot.version, 0)
        self.assertGreater(len(snapshot.hypotheses), 0)
        self.assertEqual(len(snapshot.mechanics), 0)
        self.assertEqual(len(snapshot.entities), 0)
        self.assertTrue(all(fact.status == "hypothesis" for fact in snapshot.hypotheses.values()))
        projection = snapshot.projection()
        hypotheses = json.loads(json.dumps(projection))["hypotheses"]
        self.assertIn("candidate_roles", hypotheses["entities:visual.level.0.palette"]["value"]["colors"][0])

    def test_load_playbook_rehydrates_current_level_visual_hypotheses(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.playbook import CheckedFact, PlaybookKey, PlaybookSnapshot
        from asterion.applications.prime.p7.world_model import WorldModelStore

        engine = _Engine()
        world = WorldModelStore(engine.game_id, engine.seed, engine.win_levels)
        broker = ArcBroker(engine=engine, world_model=world)
        fact = CheckedFact(
            "entities",
            "visual.level.0.component.7.0",
            {"min_x": 1, "max_x": 1, "min_y": 2, "max_y": 2},
            0,
            ("a" * 16,),
        )
        broker.load_playbook(PlaybookSnapshot(
            PlaybookKey(engine.game_id, engine.seed, engine.win_levels),
            visual_hypotheses=(fact,),
        ))

        snapshot = broker.world_model()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertIn("entities:visual.level.0.component.7.0", snapshot.hypotheses)

    def test_visual_hypothesis_promotes_only_after_changed_cell_evidence(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.world_model import WorldModelStore

        engine = _Engine()
        world = WorldModelStore(engine.game_id, engine.seed, engine.win_levels)
        broker = ArcBroker(engine=engine, world_model=world)
        broker.bind_history("run-visual-promotion")
        world.record_hypothesis(
            "entities", "visual.component.test",
            {"source": "visual-regularity", "color": 0, "min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0},
            level=0,
            evidence=world.snapshot.hypotheses["entities:visual.level.0.palette"].evidence[0],
        )

        with self.assertRaises(ArcBrokerError):
            broker.promote_hypothesis("visual.component.test", "changed_cell_in_bounds")

        checked_result = broker.act_checked([
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}},
        ])
        self.assertIn("visual.component.test", checked_result["feedback"][0]["promotion_candidates"])
        result = broker.promote_hypothesis("visual.component.test", "changed_cell_in_bounds")
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(broker.world_model().entities["visual.component.test"].status, "confirmed")

        with self.assertRaises(ArcBrokerError):
            broker.promote_hypothesis("visual.component.test", "changed_cell_in_bounds")

    def test_retrodiction_conflict_exposes_machine_readable_reason(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.transition_model import ActionExpectation

        engine = _HistoryEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-conflict")
        expectation = ActionExpectation(
            action="ACTION1", data=(),
            prior_state_sha256="sha256:" + "1" * 64,
            after_state_sha256="sha256:" + "2" * 64,
            after_frame_sha256="sha256:" + "3" * 64,
            changed_cells=(), levels_completed=0, state="NOT_FINISHED",
        )
        result = broker.act_checked(
            [{"action": {"name": "ACTION1", "data": {}}, "expect": {"frame_sha256": "sha256:" + "4" * 64}}],
            replay_expectations=(expectation,),
        )
        self.assertEqual(result["stop_reason"], "route-expectation-mismatch")
        status = broker.retrodiction_status()
        self.assertEqual(status["status"], "conflict")
        self.assertIn("route-before-state", status["reasons"])

    def test_mechanism_probe_promotes_only_after_matching_transition(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.world_model import WorldModelStore

        engine = _Engine()
        broker = ArcBroker(
            engine=engine,
            world_model=WorldModelStore(engine.game_id, engine.seed, engine.win_levels),
        )
        broker.bind_history("run-1")
        mechanism = {
            "schema": "asterion.prime.p7-mechanism/v1",
            "game_id": engine.game_id,
            "seed": 0,
            "win_levels": 7,
            "revision": 0,
            "rules": [{
                "action": "ACTION1",
                "guards": [{"op": "state_is", "args": {"value": "NOT_FINISHED"}}, {"op": "cell_equals", "args": {"x": 0, "y": 0, "value": 0}}],
                "effects": [{"op": "set_cell", "args": {"x": 0, "y": 0, "value": 1}}],
            }],
        }
        broker.record_hypothesis("mechanics", "move", {
            "mechanism": mechanism,
            "probe": {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}},
            "dependencies": [],
        })
        result = broker.act_checked([{"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}}])
        self.assertEqual(result["retrodiction"]["status"], "verified")
        self.assertEqual(broker.world_model().mechanics["move"].status, "confirmed")

    def test_retry_guard_stops_checked_batch_on_settled_no_effect(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        result = broker.act_checked([
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 7}}},
            {"action": {"name": "ACTION2", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 7}}},
        ])
        self.assertEqual(result["stop_reason"], "observation-no-change")
        self.assertEqual((result["applied_count"], result["unexecuted_count"]), (1, 1))
        self.assertEqual(engine.calls, ["ACTION1"])

    def test_retry_guard_blocks_raw_action_after_three_prior_no_effects(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        # Three successive no-effect actions trigger the guard at runtime.
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        with self.assertRaisesRegex(ArcBrokerError, "^REPLAN_REQUIRED$"):
            broker.act(("ACTION1",))
        self.assertEqual(engine.calls, ["ACTION1"] * 3)
        self.assertEqual(len(broker.journal), 3)

    def test_retry_guard_allows_checked_single_distinguishing_probe(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        result = broker.act_checked([
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"frame_sha256": "sha256:" + "0" * 64}},
        ])
        self.assertEqual(result["stop_reason"], "prediction-mismatch")
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(engine.calls, ["ACTION1"])

    def test_retry_guard_does_not_allow_probe_that_matches_current_frame(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        # Bind history before dispatch; reach the guard threshold by
        # repetition, then a checked probe matching the current frame must
        # be rejected.
        broker.bind_history("run-1")
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        result = broker.act_checked([
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 7}}},
        ])
        self.assertEqual(result["stop_reason"], "REPLAN_REQUIRED")
        self.assertEqual(engine.calls, ["ACTION1"] * 3)

    def test_retry_guard_preserves_next_level_seed_after_prefix_advance(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _Engine(level_after=1)
        broker = ArcBroker(
            engine=engine,
            game=P7GameSelection("ls20-9607627b", 0, 2),
        )
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        # After level advance, the guard counts reset and history is sealed;
        # a third ACTION1 on the new level should not raise REPLAN_REQUIRED
        # because the runtime counter for (1, ACTION1) is still below 3.
        broker.act(("ACTION1",))
        self.assertEqual(engine.calls, ["ACTION1"] * 3)

    def test_retry_guard_is_disabled_by_default(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.act(("ACTION1",) * 4)
        self.assertEqual(engine.calls, ["ACTION1"] * 4)
    def test_bound_history_records_stable_frames_and_distinct_hashes(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.score import digest

        broker = ArcBroker(engine=_HistoryEngine(), game=P7GameSelection("ls20-9607627b", 0, 2))
        broker.bind_history("run-1")
        broker.act(("ACTION1",))
        page = broker.history(0, 32)
        self.assertEqual([row["sequence"] for row in page], [0, 1])
        self.assertEqual(broker.frame_at(0), [[0]])
        self.assertEqual(broker.frame_at(1), [[1]])
        self.assertEqual(page[1]["before_state_sha256"], broker.journal[0].before_sha256)
        self.assertEqual(page[1]["after_state_sha256"], broker.journal[0].after_sha256)
        self.assertEqual(page[1]["after_frame_sha256"], digest(((1,),)))
        self.assertNotEqual(page[1]["after_frame_sha256"], page[1]["after_state_sha256"])
        page[1]["changed_cells"].append((0, 0, 0, 9))
        self.assertEqual(broker.history(0, 32)[1]["changed_cells"], [(0, 0, 0, 1)])

    def test_history_binding_and_page_failures_are_safe(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        broker = ArcBroker(engine=_HistoryEngine())
        for call in (lambda: broker.history(0, 1), lambda: broker.frame_at(0),
                     lambda: broker.act_checked([])):
            with self.subTest(call=call), self.assertRaisesRegex(ArcBrokerError, "^unavailable$"):
                call()
        for run_id in ("", "é", 3):
            with self.subTest(run_id=run_id), self.assertRaisesRegex(ArcBrokerError, "^unavailable$"):
                broker.bind_history(run_id)
        broker.bind_history("run-1")
        with self.assertRaisesRegex(ArcBrokerError, "^unavailable$"):
            broker.bind_history("run-2")
        for call in (lambda: broker.history(True, 1), lambda: broker.history(0, 33),
                     lambda: broker.frame_at(1), lambda: broker.frame_at(False)):
            with self.subTest(call=call), self.assertRaisesRegex(ArcBrokerError, "^unavailable$"):
                call()

    def test_checked_plan_stops_on_first_mismatch_without_tail_dispatch(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _HistoryEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        plan = [
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 9}}},
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 2}}},
        ]
        result = broker.act_checked(plan)
        self.assertEqual((result["applied_count"], result["unexecuted_count"]), (1, 1))
        self.assertEqual(result["stop_reason"], "prediction-mismatch")
        self.assertEqual(engine.calls, ["ACTION1"])
        self.assertEqual(len(broker.journal), 1)
        self.assertEqual(result["batch"].applied_count, 1)
        self.assertEqual(result["mismatch"], {"cell": {"x": 0, "y": 0, "value": 9}})

    def test_checked_plan_stops_at_level_game_over_and_cap(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        plan = [{"action": {"name": "ACTION1", "data": {}}, "expect": {"levels_completed": 1}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"state": "WIN"}}]
        advanced = ArcBroker(engine=_Engine(level_after=1), game=P7GameSelection("ls20-9607627b", 0, 2))
        advanced.bind_history("run-1")
        self.assertEqual(advanced.act_checked(plan)["stop_reason"], "level-advanced")
        self.assertEqual(len(advanced.journal), 1)
        failed = ArcBroker(engine=_Engine(game_over_after=1))
        failed.bind_history("run-2")
        game_over_plan = [{"action": {"name": "ACTION1", "data": {}}, "expect": {"state": "GAME_OVER"}}] * 2
        self.assertEqual(failed.act_checked(game_over_plan)["stop_reason"], "game-over")
        self.assertEqual(len(failed.journal), 1)
        capped = ArcBroker(engine=_HistoryEngine(), game=P7GameSelection("ls20-9607627b", 0, 2, action_cap_override=1))
        capped.bind_history("run-3")
        cap_plan = [{"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}}] * 2
        self.assertEqual(capped.act_checked(cap_plan)["stop_reason"], "action-cap")
        self.assertEqual(len(capped.journal), 1)

    def test_checked_plan_prechecks_entire_shape_before_dispatch(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        engine = _HistoryEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        plan = [{"action": {"name": "ACTION1", "data": {}}, "expect": {"state": "WIN"}},
                {"action": {"name": "ACTION2", "data": {}}, "expect": {"state": "NOT_FINISHED"}}]
        with self.assertRaisesRegex(ArcBrokerError, "^unavailable$"):
            broker.act_checked(plan)
        self.assertEqual(engine.calls, [])

    def test_checked_plan_reports_unavailable_action_without_dispatch(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _HistoryEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        result = broker.act_checked([
            {"action": {"name": "ACTION2", "data": {}}, "expect": {"state": "WIN"}},
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"state": "WIN"}},
        ])
        self.assertEqual((result["stop_reason"], result["applied_count"], result["unexecuted_count"]),
                         ("action-unavailable", 0, 2))
        self.assertEqual(engine.calls, [])

    def test_checked_reset_stops_before_predicted_tail(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        broker.bind_history("run-1")
        broker.act(("ACTION1",))
        broker.act(("ACTION1",))
        result = broker.act_checked([
            {"action": {"name": "RESET", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 3}}},
            {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 4}}},
        ])
        self.assertEqual((result["stop_reason"], result["applied_count"], result["unexecuted_count"]),
                         ("reset-applied", 1, 1))
        self.assertEqual([name for name, _ in engine.calls], ["ACTION1", "ACTION1", "RESET"])
        self.assertEqual(len(broker.journal), 3)

    def test_history_cannot_bind_after_failed_first_dispatch(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        broker = ArcBroker(engine=_Engine(raises_on=1))
        with self.assertRaisesRegex(ArcBrokerError, "^uncertain$"):
            broker.act(("ACTION1",))
        self.assertEqual(broker.journal, ())
        with self.assertRaisesRegex(ArcBrokerError, "^unavailable$"):
            broker.bind_history("run-1")

    def test_oversized_history_page_is_bounded_without_losing_records(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        class LargeHistoryEngine(_HistoryEngine):
            def observe(self) -> dict[str, object]:
                value = super().observe()
                value["frame"] = [[[len(self.calls) % 2] * 9 for _ in range(9)]]
                return value

        broker = ArcBroker(engine=LargeHistoryEngine())
        broker.bind_history("run-1")
        for _ in range(32):
            broker.act(("ACTION1",))
        page = broker.history(0, 32)
        self.assertGreaterEqual(len(page), 1)
        self.assertLess(len(page), 32)
        self.assertLessEqual(len(__import__("json").dumps(page, separators=(",", ":")).encode()), 16384)
        self.assertEqual(broker.history(32, 1)[0]["sequence"], 32)


    def test_full_game_requires_win_and_dynamic_cap(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 7)
        self.assertEqual(sum(game.baseline_actions), 776)
        self.assertEqual(game.action_cap, 1552)
        for state, reason in (("WIN", "game-won"), ("NOT_FINISHED", "game-incomplete")):
            with self.subTest(state=state):
                broker = ArcBroker(engine=_FullGameEngine(final_state=state, actions_per_level=100), game=game)
                for _ in range(7):
                    broker.act(("ACTION1",) * 100)
                self.assertEqual(broker.seal().primitive_actions, 700)
                self.assertEqual(broker.seal().terminal_reason, reason)
                self.assertEqual(broker.terminal_snapshot().observation.state, state)

    def test_full_game_cap_bounds_and_legacy_partial_cap(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection

        for baseline, cap in (((1,), 1000), ((3000,), 5000)):
            with self.subTest(baseline=baseline):
                game = P7GameSelection("new-v1", 0, 1, baseline, 1)
                self.assertEqual(game.action_cap, cap)
        self.assertEqual(P7GameSelection("ls20-9607627b", 0, 2).action_cap, 500)

    def test_sweep_budget_seals_with_human_baseline_reason(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 2, action_cap_override=2)
        engine = _Engine()
        broker = ArcBroker(engine=engine, game=game)
        result = broker.act(("ACTION1", "ACTION1"))
        self.assertEqual(result.applied_count, 2)
        receipt = broker.seal()
        self.assertEqual(receipt.primitive_actions, 2)
        self.assertEqual(receipt.terminal_reason, "human-baseline")
        self.assertEqual(engine.calls, ["ACTION1", "ACTION1"])

    def test_initial_game_over_is_rejected_before_any_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        engine = _ResetEngine()
        engine.state = "GAME_OVER"
        with self.assertRaises(ArcBrokerError):
            ArcBroker(engine=engine)
        self.assertEqual(engine.calls, [])

    def test_level_advance_with_game_over_is_not_falsely_resettable(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        class Engine(_ResetEngine):
            def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
                super().step(action, data)
                if self.levels_completed == 1:
                    self.state = "GAME_OVER"
                return self.observe()

        engine = Engine()
        game = P7GameSelection(engine.game_id, 0, 2)
        broker = ArcBroker(engine=engine, game=game)
        broker.act(("ACTION1",))
        self.assertEqual(broker.seal().terminal_reason, "game-over")
        with self.assertRaisesRegex(ArcBrokerError, "closed"):
            broker.act(("RESET",))
        self.assertEqual(broker.replay(Engine).levels_completed, 1)

    def test_target_second_level_keeps_broker_open_after_first_transition(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 2)
        engine = _Engine(level_after=2, second_level_after=4)
        broker = ArcBroker(engine=engine, game=game)

        first = broker.act(("ACTION1", "ACTION1", "ACTION1"))
        self.assertEqual(first.applied_count, 2)
        self.assertEqual(broker.status().levels_completed, 1)
        self.assertEqual(broker.status().terminal_reason, "active")
        self.assertEqual(engine.calls, ["ACTION1", "ACTION1"])
        with self.assertRaises(ArcBrokerError):
            broker.seal()

        second = broker.act(("ACTION1", "ACTION1", "ACTION1"))
        self.assertEqual(second.applied_count, 2)
        self.assertEqual(broker.seal().levels_completed, 2)
        self.assertEqual(broker.seal().terminal_reason, "level-completed")
        self.assertEqual(engine.calls, ["ACTION1"] * 4)

    def test_batch_stops_at_first_level_transition(self) -> None:
        broker, engine = _broker(level_after=2)

        result = broker.act(("ACTION1", "ACTION2", "ACTION3"))

        self.assertEqual(result.applied_count, 2)
        self.assertEqual(result.levels_completed, 1)
        self.assertEqual(engine.calls, ["ACTION1", "ACTION2"])
        self.assertEqual(tuple(item.sequence for item in result.transitions), (1, 2))

    def test_action_observe_and_status_after_transition_are_rejected(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, _ = _broker(level_after=1)
        broker.act(("ACTION1",))
        for call in (lambda: broker.act(("ACTION1",)), broker.observe, broker.status):
            with self.subTest(call=call), self.assertRaisesRegex(ArcBrokerError, "closed"):
                call()

    def test_game_over_records_the_action_and_requires_reset(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        engine = _Engine(game_over_after=2)
        from asterion.applications.prime.p7.broker import ArcBroker

        broker = ArcBroker(engine=engine)
        result = broker.act(("ACTION1", "ACTION2", "ACTION3"))

        self.assertEqual(result.applied_count, 2)
        self.assertEqual(engine.calls, ["ACTION1", "ACTION2"])
        self.assertEqual(broker.observe().state, "GAME_OVER")
        self.assertEqual(broker.status().primitive_actions, 2)
        self.assertEqual(broker.status().terminal_reason, "reset-required")
        with self.assertRaisesRegex(ArcBrokerError, "unavailable"):
            broker.act(("ACTION1",))

    def test_same_engine_resets_failed_second_level_and_counts_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        broker.act(("ACTION1",))
        broker.act(("ACTION1", "ACTION1"))
        self.assertEqual(broker.status().terminal_reason, "reset-required")
        result = broker.act(("RESET", "ACTION1"))
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(broker.observe().state, "NOT_FINISHED")
        self.assertEqual(broker.status().levels_completed, 1)
        broker.act(("ACTION1",))
        self.assertEqual(broker.seal().primitive_actions, 4)
        self.assertEqual(broker.seal().levels_completed, 2)
        self.assertEqual([call[0] for call in engine.calls], ["ACTION1", "ACTION1", "RESET", "ACTION1"])

    def test_reset_requires_gameplay_in_current_level_and_preserves_progress(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))
        broker.act(("ACTION1",))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))
        broker.act(("ACTION1",))
        broker.act(("RESET",))
        with self.assertRaises(ArcBrokerError):
            broker.act(("RESET",))

        for kwargs in ({"reset_loses_level": True}, {"reset_stays_dead": True}):
            with self.subTest(kwargs=kwargs):
                bad = _ResetEngine(**kwargs)
                test_broker = ArcBroker(engine=bad, game=P7GameSelection(bad.game_id, 0, 2))
                test_broker.act(("ACTION1",))
                test_broker.act(("ACTION1",))
                with self.assertRaises(ArcBrokerError):
                    test_broker.act(("RESET",))

    def test_proactive_reset_stops_batch_and_keeps_level(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        broker.act(("ACTION1",))
        broker.act((ArcAction("ACTION6", (("x", 1), ("y", 2))),))
        result = broker.act(("RESET", "ACTION1"))
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(broker.status().levels_completed, 1)
        self.assertEqual(broker.status().terminal_reason, "active")
        self.assertEqual(engine.calls[-1], ("RESET", {}))

    def test_action6_requires_exact_coordinates_and_journals_them(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        for data in ((), (("x", True), ("y", 1)), (("x", -1), ("y", 1)), (("x", 64), ("y", 1)), (("y", 1), ("x", 2)), (("x", 1), ("y", 2), ("z", 3))):
            with self.subTest(data=data):
                engine = _ResetEngine()
                broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
                with self.assertRaises(ArcBrokerError):
                    broker.act((ArcAction("ACTION6", data),))
                self.assertEqual(engine.calls, [])
        engine = _ResetEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        action = ArcAction("ACTION6", (("x", 0), ("y", 63)))
        broker.act((action,))
        self.assertEqual(engine.calls, [("ACTION6", {"x": 0, "y": 63})])
        self.assertEqual(broker.journal[0].data, action.data)
        with self.assertRaises(FrozenInstanceError):
            action.name = "ACTION1"  # type: ignore[misc]

    def test_terminal_snapshot_is_rejected_while_active(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, _ = _broker()
        with self.assertRaisesRegex(ArcBrokerError, "unavailable"):
            broker.terminal_snapshot()

    def test_malformed_unavailable_or_oversized_batch_never_dispatches(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError, P7_ACTION_CAP

        for actions in (("ACTION8",), ("ACTION1", 1), ("ACTION1",) * (P7_ACTION_CAP + 1)):
            with self.subTest(actions=actions):
                broker, engine = _broker()
                with self.assertRaises(ArcBrokerError):
                    broker.act(actions)  # type: ignore[arg-type]
                self.assertEqual(engine.calls, [])

    def test_action_cap_closes_at_500_and_receipt_has_no_frame_content(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError, P7_ACTION_CAP

        broker, engine = _broker()
        result = broker.act(("ACTION1",) * P7_ACTION_CAP)
        receipt = broker.seal()
        self.assertEqual(result.applied_count, P7_ACTION_CAP)
        self.assertEqual(len(engine.calls), P7_ACTION_CAP)
        self.assertEqual(receipt.primitive_actions, P7_ACTION_CAP)
        self.assertEqual(receipt.terminal_reason, "action-cap")
        self.assertNotIn("frame", repr(receipt))
        with self.assertRaisesRegex(ArcBrokerError, "closed"):
            broker.act(("ACTION1",))

    def test_engine_exception_after_dispatch_closes_as_uncertain(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, engine = _broker(raises_on=1)
        with self.assertRaisesRegex(ArcBrokerError, "uncertain"):
            broker.act(("ACTION1",))
        self.assertEqual(engine.calls, ["ACTION1"])
        self.assertEqual(broker.seal().terminal_reason, "engine-uncertain")

    def test_observation_is_an_immutable_snapshot(self) -> None:
        broker, engine = _broker()
        observed = broker.observe()
        with self.assertRaises(FrozenInstanceError):
            observed.state = "FORGED"  # type: ignore[misc]
        engine.step("ACTION1")
        self.assertEqual(observed.frame, (((0, 1),),))

    def test_identity_mismatch_is_rejected_before_observation(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError

        engine = _Engine(game_id="other-game")
        with self.assertRaises(ArcBrokerError):
            ArcBroker(engine=engine)
        self.assertEqual(engine.observe_calls, 0)

    def test_tu93_selection_seals_exact_identity_and_nine_level_count(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("tu93-0768757b", 0)
        engine = _Engine(game_id=game.game_id, seed=game.seed, win_levels=9, level_after=1)
        broker = ArcBroker(engine=engine, game=game)
        broker.act(("ACTION1",))
        receipt = broker.seal()
        self.assertEqual((receipt.game_id, receipt.seed), (game.game_id, game.seed))
        self.assertEqual(
            broker.replay(
                lambda: _Engine(
                    game_id=game.game_id, seed=game.seed, win_levels=9, level_after=1
                )
            ),
            receipt,
        )

    def test_tu93_rejects_wrong_level_count_before_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection

        engine = _Engine(game_id="tu93-0768757b", win_levels=7)
        with self.assertRaises(ArcBrokerError):
            ArcBroker(engine=engine, game=P7GameSelection("tu93-0768757b", 0))
        self.assertEqual(engine.calls, [])

    def test_later_action_loses_authority_when_first_changes_availability(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBrokerError

        broker, engine = _broker()
        engine.remove_second_after_first = True
        with self.assertRaisesRegex(ArcBrokerError, "unavailable"):
            broker.act(("ACTION1", "ACTION2"))
        self.assertEqual(engine.calls, ["ACTION1"])
        self.assertEqual(broker.seal().terminal_reason, "action-unavailable")
        with self.assertRaisesRegex(ArcBrokerError, "closed"):
            broker.status()


class TestRetrodictTrialTracking(unittest.TestCase):
    """Retrodict: broker tracks (level, action, position) tuples the model has
    tried, with counts, so the model can avoid repeating probes."""

    def test_tried_actions_records_direction_actions_with_no_position(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        broker.act(("ACTION1",))
        broker.act(("ACTION2",))
        broker.act(("ACTION1",))  # repeat same action
        tried = broker.tried_actions()
        # Two distinct (action, level) tuples: ACTION1 and ACTION2
        self.assertEqual(len(tried), 2)
        action1 = next(e for e in tried if e["action"] == "ACTION1")
        self.assertEqual(action1["count"], 2)
        self.assertIsNone(action1["position"])

    def test_tried_actions_filters_by_level(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        # At level 0
        broker.act(("ACTION1",))
        # Stay on level 0 (engine.levels_completed never advances for settled engine)
        l0 = broker.tried_actions(level=0)
        l_all = broker.tried_actions()
        self.assertEqual(len(l0), 1)
        self.assertEqual(len(l_all), 1)
        self.assertEqual(l0[0]["level"], 0)

    def test_last_outcome_summary_counts_attempts_and_no_effect(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker

        engine = _SettledNoEffectEngine()
        broker = ArcBroker(engine=engine)
        broker.bind_history("run-1")
        for _ in range(3):
            broker.act(("ACTION1",))
        summary = broker.last_outcome_summary()
        self.assertEqual(summary["attempts"]["ACTION1"], 3)
        self.assertEqual(summary["no_effect"]["ACTION1"], 3)

    def test_checked_click_reuse_from_replayed_prefix_requires_current_level_evidence(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction, ArcBroker
        from asterion.applications.prime.p7.game import ArcGameContract

        class _TwoLevelClickEngine:
            game_id = "ls20-9607627b"
            seed = 0
            win_levels = 2

            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, int]]] = []
                self.levels_completed = 0

            def observe(self) -> dict[str, object]:
                return {
                    "available_actions": ["ACTION6"],
                    "frame": [[[len(self.calls)]]],
                    "levels_completed": self.levels_completed,
                    "state": "NOT_FINISHED",
                    "win_levels": self.win_levels,
                }

            def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
                self.calls.append((action, data or {}))
                if len(self.calls) == 3:
                    self.levels_completed = 1
                return self.observe()

        engine = _TwoLevelClickEngine()
        broker = ArcBroker(
            engine=engine,
            game=ArcGameContract(engine.game_id, engine.win_levels, action_cap=1000),
        )
        broker.bind_history("run-prefix-reuse")
        for _ in range(3):
            broker.act((ArcAction("ACTION6", (("x", 61), ("y", 33))),))

        result = broker.act_checked([
            {
                "action": {"name": "ACTION6", "data": {"x": 61, "y": 33}},
                "expect": {"levels_completed": 2},
            },
        ])
        self.assertEqual(result["stop_reason"], "prefix-action-reuse")
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(len(engine.calls), 3)
        self.assertEqual(result["invalid_action"], "ACTION6")


class TestP7ToolRegistry(unittest.TestCase):
    """P7ToolRegistry renders an application-level tool section for the
    solve prompt; build_solve_prompt applies it without contaminating
    the base prompt template."""

    def test_render_section_empty_when_no_tools(self) -> None:
        from asterion.applications.prime.p7.broker import P7ToolRegistry

        reg = P7ToolRegistry()
        self.assertEqual(reg.render_section(), "")

    def test_register_and_render(self) -> None:
        from asterion.applications.prime.p7.broker import P7ToolRegistry, Tool

        reg = P7ToolRegistry()
        reg.register(Tool(
            name="tried_actions",
            description="Enumerate tried (level, action, position) tuples.",
            signature="p7_client.tried_actions(level=None)",
            category="retrodict",
        ))
        section = reg.render_section()
        self.assertIn("Tool reference", section)
        self.assertIn("p7_client.tried_actions(level=None)", section)
        self.assertIn("Enumerate tried", section)
        self.assertNotIn("retrodict", section)  # category is internal, not rendered

    def test_register_replaces_existing(self) -> None:
        from asterion.applications.prime.p7.broker import P7ToolRegistry, Tool

        reg = P7ToolRegistry()
        reg.register(Tool(
            name="x", description="v1", signature="x()", category="c",
        ))
        reg.register(Tool(
            name="x", description="v2", signature="x()", category="c",
        ))
        self.assertIn("v2", reg.render_section())
        self.assertNotIn("v1", reg.render_section())

    def test_build_solve_prompt_with_registry(self) -> None:
        from asterion.applications.prime.p7.broker import P7ToolRegistry, Tool
        from asterion.applications.prime.p7.prompt import (
            P7_SOLVE_PROMPT, build_solve_prompt,
        )

        reg = P7ToolRegistry()
        reg.register(Tool(
            name="alpha", description="First tool.",
            signature="alpha()", category="x",
        ))
        rendered = build_solve_prompt(reg)
        self.assertIn(P7_SOLVE_PROMPT, rendered)
        self.assertIn("alpha()", rendered)
        self.assertIn("First tool.", rendered)

    def test_build_solve_prompt_without_registry_equals_base(self) -> None:
        from asterion.applications.prime.p7.prompt import (
            P7_SOLVE_PROMPT, build_solve_prompt,
        )

        self.assertEqual(build_solve_prompt(None), P7_SOLVE_PROMPT)
        self.assertEqual(build_solve_prompt(P7ToolRegistry_shim()), P7_SOLVE_PROMPT)


class P7ToolRegistry_shim:
    def render_section(self) -> str:
        return ""


class TestP7MechanismModel(unittest.TestCase):
    def test_declarative_cell_rule_predicts_and_certifies_full_history(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction
        from asterion.applications.prime.p7.mechanism_model import (
            MechanismRule,
            MechanismSpec,
            ModelCertificate,
            validate_mechanism,
        )
        from asterion.applications.prime.p7.score import digest
        from asterion.applications.prime.p7.verified_history import ArcHistoryRecord

        initial = ArcHistoryRecord.initial(
            game_id="game",
            seed=1,
            run_id="run",
            frame=((0,),),
            levels_completed=0,
            state="NOT_FINISHED",
            after_state_sha256=digest("before"),
        )
        record = ArcHistoryRecord.following(
            initial,
            action=ArcAction("ACTION1"),
            before_state_sha256=initial.after_state_sha256,
            after_state_sha256=digest("after"),
            frame=((1,),),
            levels_completed=0,
            state="NOT_FINISHED",
        )
        spec = MechanismSpec(
            game_id="game",
            seed=1,
            win_levels=2,
            rules=(
                MechanismRule(
                    action="ACTION1",
                    guards=(
                        ("state_is", "NOT_FINISHED"),
                        ("level_is", 0),
                        ("cell_equals", {"x": 0, "y": 0, "value": 0}),
                    ),
                    effects=(("set_cell", {"x": 0, "y": 0, "value": 1}),),
                ),
            ),
        )

        prediction = spec.predict(
            frame=((0,),),
            action=ArcAction("ACTION1"),
            level=0,
            state="NOT_FINISHED",
        )
        self.assertEqual(prediction.status, "predicted")
        self.assertEqual(prediction.frame, ((1,),))
        certificate = validate_mechanism(spec, (initial, record))
        self.assertIsInstance(certificate, ModelCertificate)
        self.assertEqual(certificate.coverage, "mechanism-retrodicted")

    def test_entity_guard_is_used_during_history_certificate(self) -> None:
        from asterion.applications.prime.p7.broker import ArcAction
        from asterion.applications.prime.p7.mechanism_model import (
            MechanismRule,
            MechanismSpec,
            validate_mechanism,
        )
        from asterion.applications.prime.p7.score import digest
        from asterion.applications.prime.p7.verified_history import ArcHistoryRecord

        initial = ArcHistoryRecord.initial(
            game_id="game", seed=1, run_id="run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("before"),
        )
        record = ArcHistoryRecord.following(
            initial, action=ArcAction("ACTION1"),
            before_state_sha256=initial.after_state_sha256,
            after_state_sha256=digest("after"), frame=((0,),),
            levels_completed=1, state="NOT_FINISHED",
        )
        spec = MechanismSpec(
            game_id="game", seed=1, win_levels=2,
            rules=(MechanismRule(
                "ACTION1",
                guards=(("entity_attr_equals", {"entity": "door", "attr": "open", "value": True}),),
                effects=(("increment_level", {"value": 1}),),
            ),),
        )

        certificate = validate_mechanism(spec, (initial, record), entities={"door": {"open": True}})

        self.assertIsNotNone(certificate)

    def test_mechanism_rules_are_canonical_bounded_and_reject_code_like_effects(self) -> None:
        from asterion.applications.prime.p7.mechanism_model import MechanismRule, MechanismSpec

        rule = MechanismRule(
            action="ACTION1",
            guards=(("cell_in_bounds", {"x": 0, "y": 0}),),
            effects=(("toggle_cell", {"x": 0, "y": 0, "values": (0, 1)}),),
        )
        spec = MechanismSpec("game", 1, 2, (rule,))
        self.assertEqual(spec.to_json(), spec.to_json())
        with self.assertRaises(ValueError):
            MechanismRule("ACTION1", (("eval", "1 + 1"),), ())
        with self.assertRaises(ValueError):
            MechanismSpec("game", 1, 2, tuple(rule for _ in range(129)))

    def test_mechanism_preserves_empty_and_pair_shaped_arrays(self) -> None:
        from asterion.applications.prime.p7.mechanism_model import MechanismRule, MechanismSpec

        rule = MechanismRule(
            action="ACTION1",
            effects=(
                ("translate_cells", {"dx": 0, "dy": 0, "cells": []}),
            ),
        )
        spec = MechanismSpec("game", 1, 2, (rule,))
        prediction = spec.predict(frame=((1,),), action="ACTION1", level=0, state="NOT_FINISHED")
        self.assertEqual(prediction.status, "predicted")
        self.assertEqual(prediction.frame, ((1,),))
        self.assertEqual(spec.to_mapping()["rules"][0]["effects"][0]["args"]["cells"], [])

    def test_empty_spec_is_unknown_and_direct_certificate_is_not_eligible(self) -> None:
        from asterion.applications.prime.p7.mechanism_model import MechanismSpec, ModelCertificate

        spec = MechanismSpec("game", 1, 2, ())
        self.assertEqual(
            spec.predict(frame=((0,),), action="ACTION1", level=0, state="NOT_FINISHED").status,
            "unknown",
        )
        certificate = ModelCertificate(
            "game", 1, 2, 0, "sha256:" + "0" * 64, 2, 0, 1,
        )
        self.assertFalse(certificate.planner_eligible)
