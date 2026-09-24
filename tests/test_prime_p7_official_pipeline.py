"""No-network official P7 pipeline across the real session and coordinator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from asterion.applications.prime.p7 import official
from asterion.applications.prime.p7.official import OfficialError, prepare_session
from asterion.applications.prime.p7.official_operator import OfficialInvocation, _submit
from asterion.applications.prime.p7.official_result import write_recovery_record


class FakeCompetitionEnvironment:
    """The SDK wrapper shape used by CompetitionEngine, with no implicit reset."""

    def __init__(self, game_id: str, card_id: str, guid: str) -> None:
        self.environment_info = NS(game_id=game_id)
        self.scorecard_id = card_id
        self.base_url = official.OFFICIAL_BASE_URL
        self._guid = guid
        self.reset_calls = 0
        self.actions: list[tuple[object, dict[str, int]]] = []
        self.observation_space = NS(
            guid=guid, game_id=game_id, frame=[[[1]]], available_actions=[1],
            levels_completed=0, win_levels=2, state=NS(value="NOT_FINISHED"),
        )

    def reset(self) -> None:
        self.reset_calls += 1
        raise AssertionError("official session must not add an initial RESET")

    def step(self, action: object, data: dict[str, int]) -> object:
        self.actions.append((action, data))
        return self.observation_space


class FakeCompetitionSDK:
    """Only official SDK response fields consumed by the adapter are represented."""

    def __init__(self, *, malformed_close: bool = False, **_kwargs: object) -> None:
        self.operation_mode = "COMPETITION"
        self.arc_base_url = official.OFFICIAL_BASE_URL
        self.games = [
            NS(game_id="ab12-12345678", baseline_actions=[10, 11]),
            NS(game_id="cd34-87654321", baseline_actions=None),
        ]
        self.malformed_close = malformed_close
        self.calls: list[object] = []
        self.environments: dict[str, FakeCompetitionEnvironment] = {}

    def get_environments(self) -> list[object]:
        self.calls.append("catalog")
        return self.games

    def create_scorecard(self) -> str:
        self.calls.append("create-scorecard")
        return "card-123"

    def make(self, game_id: str, **kwargs: object) -> FakeCompetitionEnvironment:
        self.calls.append(("make", game_id, kwargs))
        environment = FakeCompetitionEnvironment(game_id, str(kwargs["scorecard_id"]), f"guid-{game_id}")
        self.environments[game_id] = environment
        return environment

    def close_scorecard(self, card_id: str) -> object:
        self.calls.append(("close-scorecard", card_id))
        rows = []
        for game_id in ("ab12-12345678", "cd34-87654321"):
            # EnvironmentScoreList.id / .runs and EnvironmentScore fields match
            # arc_agi.scorecard's public model fields.
            state = "WIN" if game_id == "ab12-12345678" else "GAME_OVER"
            rows.append(NS(
                id=game_id,
                runs=[NS(
                    id=None, guid=f"guid-{game_id}", score=100.0 if state == "WIN" else 0.0,
                    state=NS(name=state), completed=(state == "WIN"),
                    levels_completed=2 if state == "WIN" else 0, actions=3,
                )],
            ))
        if self.malformed_close:
            rows.pop()
        return NS(card_id=card_id, competition_mode=True, score=50.0, environments=rows)


class TestOfficialPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.sdk: FakeCompetitionSDK | None = None

    def _session(self, *, malformed_close: bool = False):
        def factory(**kwargs: object) -> FakeCompetitionSDK:
            self.sdk = FakeCompetitionSDK(malformed_close=malformed_close, **kwargs)
            return self.sdk

        return prepare_session(
            api_key="private-arc-key", evidence_root=Path(self.directory.name),
            model_host_ready=True, sdk_factory=factory,
        )

    @staticmethod
    def _invocation(root: Path) -> OfficialInvocation:
        return OfficialInvocation(
            operator_root=root, environment={}, pi_base_command=("pi",),
            extension_path=root / "extension.mjs", api_key="private-arc-key",
        )

    def test_submit_closes_validated_multi_game_card_and_persists_private_receipt(self) -> None:
        evidence_root = Path(self.directory.name) / "evidence"
        evidence_root.mkdir(mode=0o700)
        observed: list[tuple[object, object, str]] = []

        async def fake_run_game(
            invocation: OfficialInvocation, application: object, root: Path,
            engine: object, game: object, run_id: str,
        ) -> None:
            observed.append((engine, game, run_id))
            self.assertEqual(root, evidence_root)
            self.assertEqual(getattr(engine, "game_id"), getattr(game, "game_id"))
            self.assertEqual(getattr(game, "mode"), "official")
            self.assertEqual(getattr(game, "seed"), 0)
            getattr(engine, "observe")()

        with (
            self._session() as session,
            mock.patch("asterion.applications.prime.p7.official_operator._resolve_gameplay_application", return_value=object()),
            mock.patch("asterion.applications.prime.p7.official_operator._run_game", new=mock.AsyncMock(side_effect=fake_run_game)),
        ):
            self.assertFalse((evidence_root / "official-receipt.json").exists())
            result = asyncio.run(_submit(self._invocation(evidence_root), session, evidence_root))

        assert self.sdk is not None
        receipt_path = evidence_root / "official-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(result, receipt)
        self.assertEqual(receipt["scorecard_url"], f"{official.OFFICIAL_BASE_URL}/scorecards/card-123")
        self.assertEqual([game["state"] for game in receipt["games"]], ["WIN", "GAME_OVER"])
        self.assertEqual(receipt["games_completed"], 1)
        self.assertEqual(len(observed), 2)
        self.assertEqual(tuple(getattr(game, "game_id") for _, game, _ in observed), session.preflight.game_ids)
        self.assertEqual(len({run_id for _, _, run_id in observed}), 2)
        self.assertEqual(self.sdk.calls.count("create-scorecard"), 1)
        self.assertEqual([call[1] for call in self.sdk.calls if isinstance(call, tuple) and call[0] == "make"], list(session.preflight.game_ids))
        self.assertEqual(self.sdk.calls.count(("close-scorecard", "card-123")), 1)
        self.assertTrue(all(environment.reset_calls == 0 for environment in self.sdk.environments.values()))
        self.assertEqual(session.guids, {game_id: f"guid-{game_id}" for game_id in session.preflight.game_ids})

    def test_missing_scorecard_row_writes_recovery_without_scorecard_url(self) -> None:
        evidence_root = Path(self.directory.name) / "recovery"
        evidence_root.mkdir(mode=0o700)

        with (
            self._session(malformed_close=True) as session,
            mock.patch("asterion.applications.prime.p7.official_operator._resolve_gameplay_application", return_value=object()),
            mock.patch("asterion.applications.prime.p7.official_operator._run_game", new=mock.AsyncMock()),
        ):
            with self.assertRaisesRegex(OfficialError, "official result unverified"):
                asyncio.run(_submit(self._invocation(evidence_root), session, evidence_root))
            recovery = write_recovery_record(session, evidence_root)

        payload = json.loads(recovery.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "recovery-required")
        self.assertEqual(payload["card_id"], "card-123")
        self.assertNotIn("scorecard_url", payload)
        self.assertFalse((evidence_root / "official-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
