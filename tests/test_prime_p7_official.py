"""No-network official Competition adapter contract."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import official
from asterion.applications.prime.p7.game import ArcGameContract
from asterion.applications.prime.p7.operator import P7RuntimeSelection


class FakeEnvironment:
    def __init__(self, game_id, card_id):
        self.environment_info = NS(game_id=game_id)
        self.scorecard_id = card_id
        self.base_url = official.OFFICIAL_BASE_URL
        self._guid = "private-guid"
        self.reset_count = 0
        self.actions = []
        self.observation_space = self.reset()

    def reset(self):
        self.reset_count += 1
        return NS(guid=self._guid, game_id=self.environment_info.game_id,
                  frame=[[[1]]], available_actions=[1, 6], levels_completed=0,
                  win_levels=2, state=NS(value="NOT_FINISHED"))

    def step(self, action, data):
        self.actions.append((action, data))
        return self.observation_space


class FakeSDK:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.operation_mode = "COMPETITION"
        self.arc_base_url = official.OFFICIAL_BASE_URL
        self.games = [NS(game_id="ls20-9607627b", baseline_actions=[400, 376]),
                      NS(game_id="tu93-0768757b", baseline_actions=None)]
        self.calls = []
        self.environment = None
        self.close_result = NS(card_id="private-card")

    def get_environments(self):
        self.calls.append("catalog")
        return self.games

    def create_scorecard(self):
        self.calls.append("open")
        return "private-card"

    def make(self, game_id, **kwargs):
        self.calls.append(("make", game_id, kwargs))
        self.environment = FakeEnvironment(game_id, kwargs["scorecard_id"])
        return self.environment

    def close_scorecard(self, card_id):
        self.calls.append(("close", card_id))
        return self.close_result


class TestOfficialAdapter(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict("os.environ", {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.sdk = None

    def factory(self, **kwargs):
        self.sdk = FakeSDK(**kwargs)
        return self.sdk

    def prepare(self, factory=None, **kwargs):
        session = official.prepare_session(api_key="sentinel-secret",
            evidence_root=Path(self.directory.name), model_host_ready=True,
            sdk_factory=factory or self.factory, **kwargs)
        self.addCleanup(session.dispose)
        return session

    def test_read_only_preflight_seals_caps_and_empty_metadata_root(self):
        session = self.prepare()
        self.assertEqual(self.sdk.calls, ["catalog"])
        self.assertEqual(session.preflight.game_ids, ("ls20-9607627b", "tu93-0768757b"))
        self.assertEqual(tuple(p.action_cap for p in session.preflight.games), (1552, 1000))
        self.assertEqual(session.preflight.total_action_cap, 2552)
        self.assertEqual(session.preflight.total_model_callback_cap, 256)
        self.assertEqual(session.preflight.total_deadline_seconds, 7200)
        for policy in session.preflight.games:
            runtime = P7RuntimeSelection.fixed(
                ArcGameContract(policy.game_id, 1, action_cap=policy.action_cap)
            )
            self.assertEqual(policy.model_callback_cap, runtime.max_callbacks)
            self.assertEqual(policy.deadline_seconds, runtime.deadline_ms // 1000)
        self.assertEqual(list(Path(self.sdk.kwargs["environments_dir"]).iterdir()), [])
        self.assertNotIn("sentinel-secret", repr(session))
        self.assertNotIn("sentinel-secret", repr(session.preflight))

    def test_catalog_rejects_empty_malformed_duplicate(self):
        for games in ([], [NS(game_id="ls20", baseline_actions=None)],
                      [NS(game_id="ls20-9607627b", baseline_actions=None)] * 2):
            with self.subTest(games=games):
                def factory(**kwargs):
                    sdk = self.factory(**kwargs)
                    sdk.games = games
                    return sdk
                with self.assertRaises(official.OfficialError):
                    self.prepare(factory)
                self.assertEqual(self.sdk.calls, ["catalog"])

    def test_missing_host_key_and_inherited_override_fail_before_factory(self):
        for kwargs in ({"api_key": ""}, {"model_host_ready": False}):
            with self.subTest(kwargs=kwargs):
                args = dict(api_key="secret", evidence_root=Path(self.directory.name),
                            model_host_ready=True, sdk_factory=self.factory)
                args.update(kwargs)
                with self.assertRaises(official.OfficialError):
                    official.prepare_session(**args)
                self.assertIsNone(self.sdk)
        with patch.dict("os.environ", {"ARC_BASE_URL": "https://sentinel-secret.invalid"}):
            with self.assertRaises(official.OfficialError):
                self.prepare()
            self.assertIsNone(self.sdk)

    def test_one_card_one_make_no_initial_reset_and_coordinate_action(self):
        session = self.prepare()
        self.assertEqual(session.open(), "private-card")
        with self.assertRaises(official.OfficialError):
            session.open()
        engine = session.make("ls20-9607627b")
        self.assertEqual(engine.win_levels, 2)
        self.assertEqual(self.sdk.environment.reset_count, 1)
        engine.step("ACTION6", {"x": 2, "y": 3})
        engine.step("RESET")
        self.assertEqual(self.sdk.environment.actions, [("ACTION6", {"x": 2, "y": 3}), ("RESET", {})])
        self.assertEqual(self.sdk.environment.reset_count, 1)
        with self.assertRaises(official.OfficialError):
            session.make("ls20-9607627b")
        session.make("tu93-0768757b")
        self.assertIs(session.close(), self.sdk.close_result)
        self.assertTrue(session.normal_close_confirmed)
        self.assertFalse(session.aborted)
        self.assertEqual(session.unattempted_game_ids, ())
        with self.assertRaises(official.OfficialError):
            session.close()
        with self.assertRaises(official.OfficialError):
            engine.step("ACTION1")
        self.assertEqual(self.sdk.calls.count("open"), 1)
        self.assertEqual(self.sdk.calls.count(("close", "private-card")), 1)

    def test_wrong_wrapper_identity_rejects_without_replacement(self):
        for field in ("game_id", "card_id", "guid", "win_levels"):
            with self.subTest(field=field):
                session = self.prepare()
                session.open()
                make = self.sdk.make
                def mismatched(*args, **kwargs):
                    env = make(*args, **kwargs)
                    if field == "game_id":
                        env.environment_info.game_id = "ls20-deadbeef"
                    elif field == "card_id":
                        env.scorecard_id = "wrong"
                    elif field == "guid":
                        env.observation_space.guid = "wrong"
                    else:
                        env.observation_space.win_levels = 0
                    return env
                self.sdk.make = mismatched
                with self.assertRaises(official.OfficialError):
                    session.make("ls20-9607627b")
                with self.assertRaises(official.OfficialError):
                    session.make("ls20-9607627b")
                self.assertEqual(len([c for c in self.sdk.calls if isinstance(c, tuple) and c[0] == "make"]), 1)
                session.abort_close()

    def test_unknown_game_fails_before_make(self):
        session = self.prepare()
        session.open()
        with self.assertRaises(official.OfficialError):
            session.make("ls20-changed")
        self.assertEqual(self.sdk.calls, ["catalog", "open"])
        session.abort_close()

    def test_selected_session_makes_only_selected_games(self):
        session = self.prepare(selected_game_ids=("ls20-9607627b",))
        self.assertEqual(session.selected_game_ids, ("ls20-9607627b",))
        session.open()
        session.make("ls20-9607627b")
        with self.assertRaises(official.OfficialError):
            session.make("tu93-0768757b")
        session.close()
        self.assertEqual(session.unattempted_game_ids, ())
        self.assertEqual(session.catalog_unselected_game_ids, ("tu93-0768757b",))

    def test_selected_ids_must_be_nonempty_exact_and_unique(self):
        for selected in ((), ("unknown-12345678",), ("ls20-9607627b", "ls20-9607627b")):
            with self.subTest(selected=selected), self.assertRaises(official.OfficialError):
                self.prepare(selected_game_ids=selected)

    def test_uncertain_make_is_not_retryable_or_receipt_eligible(self):
        session = self.prepare(selected_game_ids=("ls20-9607627b",))
        session.open()
        def uncertain(*args, **kwargs):
            raise RuntimeError("transport lost after remote make")
        self.sdk.make = uncertain
        with self.assertRaises(official.OfficialError):
            session.make("ls20-9607627b")
        self.assertTrue(session.recovery_required)
        self.assertEqual(session.unattempted_game_ids, ())
        with self.assertRaises(official.OfficialError):
            session.make("ls20-9607627b")
        session.abort_close()

    def test_close_failure_is_one_attempt_and_safe(self):
        session = self.prepare()
        session.open()
        session.make("ls20-9607627b")
        session.make("tu93-0768757b")
        self.sdk.close_result = NS(card_id="wrong-private-card")
        with self.assertRaisesRegex(official.OfficialError, "recovery required"):
            session.close()
        self.assertTrue(session.recovery_required)
        session.dispose()
        session.dispose()
        self.assertEqual(self.sdk.calls.count(("close", "private-card")), 1)

    def test_dispose_closes_open_card_once(self):
        session = self.prepare()
        session.open()
        session.dispose()
        session.dispose()
        self.assertEqual(self.sdk.calls.count(("close", "private-card")), 1)

    def test_normal_close_rejects_unattempted_games_without_remote_close(self):
        for attempted in ((), ("ls20-9607627b",)):
            with self.subTest(attempted=attempted):
                session = self.prepare()
                session.open()
                for game_id in attempted:
                    session.make(game_id)
                with self.assertRaisesRegex(official.OfficialError, "official games unattempted"):
                    session.close()
                self.assertNotIn(("close", "private-card"), self.sdk.calls)
                self.assertFalse(session.normal_close_confirmed)
                self.assertIsNone(session.closure_result)
                for game_id in session.unattempted_game_ids:
                    session.make(game_id)
                session.close()
                self.assertTrue(session.normal_close_confirmed)

    def test_abort_close_records_missing_games_and_never_normal_result(self):
        session = self.prepare()
        session.open()
        session.make("ls20-9607627b")
        self.assertIs(session.abort_close(), self.sdk.close_result)
        self.assertTrue(session.aborted)
        self.assertEqual(session.unattempted_game_ids, ("tu93-0768757b",))
        self.assertIsNone(session.closure_result)
        self.assertIs(session.abort_result, self.sdk.close_result)
        self.assertFalse(session.normal_close_confirmed)
        with self.assertRaises(official.OfficialError):
            session.abort_close()
        with self.assertRaises(official.OfficialError):
            session.close()
        session.dispose()
        self.assertEqual(self.sdk.calls.count(("close", "private-card")), 1)

    def test_dispose_always_uses_abort_even_after_all_make_attempts(self):
        for attempted in ((), ("ls20-9607627b",), ("ls20-9607627b", "tu93-0768757b")):
            with self.subTest(attempted=attempted):
                session = self.prepare()
                session.open()
                for game_id in attempted:
                    session.make(game_id)
                session.dispose()
                self.assertTrue(session.aborted)
                self.assertEqual(session.unattempted_game_ids,
                                 tuple(game for game in session.preflight.game_ids if game not in attempted))
                self.assertFalse(session.normal_close_confirmed)
                self.assertIsNone(session.closure_result)
                self.assertIs(session.abort_result, self.sdk.close_result)
                self.assertEqual(self.sdk.calls.count(("close", "private-card")), 1)

    def test_failed_abort_retains_missing_games_and_requires_recovery(self):
        session = self.prepare()
        session.open()
        self.sdk.close_result = None
        with self.assertRaisesRegex(official.OfficialError, "recovery required"):
            session.abort_close()
        self.assertTrue(session.aborted)
        self.assertTrue(session.recovery_required)
        self.assertEqual(session.unattempted_game_ids, session.preflight.game_ids)
        self.assertIsNone(session.abort_result)
        self.assertIsNone(session.closure_result)
        session.dispose()
        self.assertEqual(self.sdk.calls.count(("close", "private-card")), 1)

    def test_sdk_exception_is_redacted(self):
        def broken(**kwargs):
            raise RuntimeError("sentinel-secret private-guid raw-frame")
        with self.assertRaises(official.OfficialError) as raised:
            self.prepare(broken)
        self.assertEqual(str(raised.exception), "official preflight unavailable")

    def test_preflight_convenience_disposes_metadata_directory(self):
        result = official.preflight(api_key="secret", evidence_root=Path(self.directory.name),
            model_host_ready=True, sdk_factory=self.factory)
        self.assertEqual(result.game_count, 2)
        self.assertEqual(self.sdk.calls, ["catalog"])
        self.assertFalse(Path(self.sdk.kwargs["environments_dir"]).exists())

    def test_invalid_baselines_fall_back_and_large_baseline_is_capped(self):
        for baseline, expected in ((None, 1000), ([], 1000), ([False], 1000),
                                   ([-1], 1000), ([3000], 5000)):
            with self.subTest(baseline=baseline):
                def factory(**kwargs):
                    sdk = self.factory(**kwargs)
                    sdk.games = [NS(game_id="ls20-9607627b", baseline_actions=baseline)]
                    return sdk
                session = self.prepare(factory)
                self.assertEqual(session.preflight.games[0].action_cap, expected)

    def test_effective_sdk_configuration_rejected_before_catalog(self):
        for field, value in (("operation_mode", "OFFLINE"), ("arc_base_url", "https://wrong.invalid")):
            with self.subTest(field=field):
                def factory(**kwargs):
                    sdk = self.factory(**kwargs)
                    setattr(sdk, field, value)
                    return sdk
                with self.assertRaises(official.OfficialError):
                    self.prepare(factory)
                self.assertEqual(self.sdk.calls, [])

    def test_initial_observation_and_baseline_level_count_must_agree(self):
        session = self.prepare()
        session.open()
        make = self.sdk.make
        def wrong_count(*args, **kwargs):
            env = make(*args, **kwargs)
            env.observation_space.win_levels = 3
            return env
        self.sdk.make = wrong_count
        with self.assertRaises(official.OfficialError):
            session.make("ls20-9607627b")

    def test_invalid_coordinates_are_rejected_before_dispatch(self):
        session = self.prepare()
        session.open()
        engine = session.make("ls20-9607627b")
        for data in ({"x": 64, "y": 0}, {"x": True, "y": 0}, {"x": 0}, {"x": 0, "y": 0, "z": 1}):
            with self.subTest(data=data), self.assertRaises(official.OfficialError):
                engine.step("ACTION6", data)
        self.assertEqual(self.sdk.environment.actions, [])

    def test_changed_mode_blocks_action(self):
        session = self.prepare()
        session.open()
        engine = session.make("ls20-9607627b")
        self.sdk.operation_mode = "OFFLINE"
        with self.assertRaises(official.OfficialError):
            engine.step("ACTION1")
        self.assertEqual(self.sdk.environment.actions, [])
        session.dispose()


if __name__ == "__main__":
    unittest.main()
