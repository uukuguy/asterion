"""No-network execution of a locally verified prefix on one official engine."""

from __future__ import annotations

import unittest

from asterion.applications.prime.p7.broker import ArcTransition, _observation_digest, _snapshot_observation
from asterion.applications.prime.p7.official_replay import OfficialReplayError, execute_saved_prefix


def _digest(value: dict[str, object]) -> str:
    return _observation_digest(_snapshot_observation(value, win_levels=2))


class _Engine:
    game_id = "ls20-9607627b"
    seed = 0
    win_levels = 2

    def __init__(self, *, initial: dict[str, object] | None = None, fail_action: bool = False,
                 observations: tuple[dict[str, object], ...] | None = None) -> None:
        self._observations = observations or (
            initial or {"available_actions": ["ACTION6"], "frame": [[[0]]], "levels_completed": 0,
                        "state": "NOT_FINISHED", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[1]]], "levels_completed": 0,
             "state": "NOT_FINISHED", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[2]]], "levels_completed": 1,
             "state": "NOT_FINISHED", "win_levels": 2},
        )
        self._index = 0
        self.fail_action = fail_action
        self.actions: list[tuple[str, dict[str, int] | None]] = []
        self.reset_calls = 0

    def observe(self) -> dict[str, object]:
        return self._observations[self._index]

    def step(self, action: str, data: dict[str, int] | None = None) -> dict[str, object]:
        self.actions.append((action, data))
        if self.fail_action:
            raise RuntimeError("transport-private-detail")
        self._index += 1
        return self.observe()

    def reset(self) -> None:
        self.reset_calls += 1
        raise AssertionError("saved replay must never reset an official game")


class TestOfficialSavedReplay(unittest.TestCase):
    def _prefix(self):
        from asterion.applications.prime.p7.solutions import VerifiedPrefix

        before = _Engine().observe()
        click_after = _Engine()._observations[1]
        action_after = _Engine()._observations[2]
        return VerifiedPrefix(
            game_id="ls20-9607627b", seed=0, win_levels=2, levels_completed=1,
            transitions=(
                ArcTransition(1, "ACTION6", _digest(before), _digest(click_after), 0, (("x", 12), ("y", 34))),
                ArcTransition(2, "ACTION1", _digest(click_after), _digest(action_after), 1),
            ),
            source_run_id="private-source-run", replay_sha256="sha256:" + "a" * 64,
        )

    def test_dispatches_verified_action6_once_without_reset(self) -> None:
        engine = _Engine()

        self.assertIsNone(execute_saved_prefix(engine, self._prefix()))

        self.assertEqual(engine.actions, [("ACTION6", {"x": 12, "y": 34}), ("ACTION1", None)])
        self.assertEqual(engine.reset_calls, 0)

    def test_initial_digest_or_exact_identity_mismatch_stops_before_action(self) -> None:
        prefix = self._prefix()
        altered = _Engine(initial={"available_actions": ["ACTION6"], "frame": [[[9]]], "levels_completed": 0,
                                   "state": "NOT_FINISHED", "win_levels": 2})
        for engine in (altered, type("WrongEngine", (_Engine,), {"game_id": "ls20-deadbeef"})()):
            with self.subTest(engine=type(engine).__name__):
                with self.assertRaisesRegex(OfficialReplayError, "official saved replay unavailable"):
                    execute_saved_prefix(engine, prefix)
                self.assertEqual(engine.actions, [])

    def test_uncertain_action_is_not_retried_and_private_error_is_redacted(self) -> None:
        engine = _Engine(fail_action=True)

        with self.assertRaisesRegex(OfficialReplayError, "official saved replay unavailable") as error:
            execute_saved_prefix(engine, self._prefix())

        self.assertEqual(len(engine.actions), 1)
        self.assertNotIn("transport-private-detail", str(error.exception))

    def test_after_digest_and_completed_level_contract_mismatch_stops_subsequent_actions(self) -> None:
        prefix = self._prefix()
        bad_transition = ArcTransition(
            1, prefix.transitions[0].action, prefix.transitions[0].before_sha256,
            "sha256:" + "b" * 64, 0, prefix.transitions[0].data,
        )
        bad_prefix = type(prefix)(
            game_id=prefix.game_id, seed=prefix.seed, win_levels=prefix.win_levels,
            levels_completed=prefix.levels_completed, transitions=(bad_transition, *prefix.transitions[1:]),
            source_run_id=prefix.source_run_id, replay_sha256=prefix.replay_sha256,
        )
        engine = _Engine()

        with self.assertRaisesRegex(OfficialReplayError, "official saved replay unavailable"):
            execute_saved_prefix(engine, bad_prefix)

        self.assertEqual(len(engine.actions), 1)

    def test_replays_level_retry_reset_after_an_ordinary_action(self) -> None:
        from asterion.applications.prime.p7.solutions import VerifiedPrefix

        states = (
            {"available_actions": ["ACTION1"], "frame": [[[0]]], "levels_completed": 0,
             "state": "NOT_FINISHED", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[1]]], "levels_completed": 0,
             "state": "NOT_FINISHED", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[0]]], "levels_completed": 0,
             "state": "NOT_FINISHED", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[2]]], "levels_completed": 1,
             "state": "NOT_FINISHED", "win_levels": 2},
        )
        prefix = VerifiedPrefix(
            game_id="ls20-9607627b", seed=0, win_levels=2, levels_completed=1,
            transitions=tuple(
                ArcTransition(sequence, action, _digest(states[sequence - 1]), _digest(states[sequence]), levels)
                for sequence, (action, levels) in enumerate((("ACTION1", 0), ("RESET", 0), ("ACTION1", 1)), 1)
            ),
            source_run_id="private-source-run", replay_sha256="sha256:" + "a" * 64,
        )
        engine = _Engine(observations=states)

        execute_saved_prefix(engine, prefix)

        self.assertEqual(engine.actions, [("ACTION1", None), ("RESET", None), ("ACTION1", None)])
        self.assertEqual(engine.reset_calls, 0)

    def test_rejects_reset_before_an_ordinary_action_in_the_level(self) -> None:
        prefix = self._prefix()
        reset = ArcTransition(1, "RESET", prefix.transitions[0].before_sha256,
                              prefix.transitions[0].after_sha256, 0)
        invalid = type(prefix)(
            game_id=prefix.game_id, seed=prefix.seed, win_levels=prefix.win_levels,
            levels_completed=prefix.levels_completed, transitions=(reset, *prefix.transitions[1:]),
            source_run_id=prefix.source_run_id, replay_sha256=prefix.replay_sha256,
        )
        engine = _Engine()

        with self.assertRaisesRegex(OfficialReplayError, "official saved replay unavailable"):
            execute_saved_prefix(engine, invalid)

        self.assertEqual(engine.actions, [])

    def test_rejects_ordinary_action_after_game_over_even_if_advertised(self) -> None:
        from asterion.applications.prime.p7.solutions import VerifiedPrefix

        states = (
            {"available_actions": ["ACTION1"], "frame": [[[0]]], "levels_completed": 0,
             "state": "NOT_FINISHED", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[1]]], "levels_completed": 0,
             "state": "GAME_OVER", "win_levels": 2},
            {"available_actions": ["ACTION1"], "frame": [[[2]]], "levels_completed": 1,
             "state": "NOT_FINISHED", "win_levels": 2},
        )
        prefix = VerifiedPrefix(
            game_id="ls20-9607627b", seed=0, win_levels=2, levels_completed=1,
            transitions=(
                ArcTransition(1, "ACTION1", _digest(states[0]), _digest(states[1]), 0),
                ArcTransition(2, "ACTION1", _digest(states[1]), _digest(states[2]), 1),
            ),
            source_run_id="private-source-run", replay_sha256="sha256:" + "a" * 64,
        )
        engine = _Engine(observations=states)

        with self.assertRaisesRegex(OfficialReplayError, "official saved replay unavailable"):
            execute_saved_prefix(engine, prefix)

        self.assertEqual(engine.actions, [("ACTION1", None)])


if __name__ == "__main__":
    unittest.main()
