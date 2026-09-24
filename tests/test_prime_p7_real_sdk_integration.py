"""P7 lifecycle smoke test against the real ARC-AGI 0.9.9 SDK.

The SDK is optional in the repository environment, so the test is skipped when
it is not installed.  When run with ``uv run --with arc-agi==0.9.9`` every HTTP
boundary is replaced with deterministic responses; no ARC account or network
access is required.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.metadata
import unittest
from unittest import mock

from asterion.applications.prime.p7 import official
from asterion.applications.prime.p7.official import OfficialError, prepare_session
from asterion.applications.prime.p7.official_result import validate_closed_scorecard


try:
    _ARC_AGI_VERSION = importlib.metadata.version("arc-agi")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - environment dependent
    _ARC_AGI_VERSION = None


class _Response:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


@unittest.skipUnless(_ARC_AGI_VERSION == "0.9.9", "requires arc-agi==0.9.9")
class TestP7RealSdkIntegration(unittest.TestCase):
    def test_selected_partial_close_uses_real_sdk_without_network(self) -> None:
        """A normal partial close validates all observed skipped-row shapes."""
        game_id = "ls20-9607627b"
        skipped_id = "tu93-0768757b"
        placeholder = {
            "id": skipped_id,
            "runs": [{"id": None, "guid": "guid-skipped-fixture", "score": 0.0,
                      "state": "NOT_FINISHED", "completed": False,
                      "levels_completed": 0, "actions": 0, "resets": 0}],
        }
        for skipped_row in (None, {"id": skipped_id, "runs": []}, placeholder):
            with self.subTest(skipped_row=skipped_row):
                self._assert_selected_partial_close(game_id, skipped_id, skipped_row)

        for field, value in (("actions", 1), ("levels_completed", 1),
                             ("score", 1.0), ("resets", 1)):
            with self.subTest(invalid_placeholder=field):
                run = dict(placeholder["runs"][0])
                run[field] = value
                self._assert_selected_partial_close(
                    game_id, skipped_id, {"id": skipped_id, "runs": [run]},
                    expect_valid=False,
                )

    def _assert_selected_partial_close(
        self, game_id: str, skipped_id: str, skipped_row: object,
        *, expect_valid: bool = True,
    ) -> None:
        requests_seen: list[tuple[str, str, object]] = []

        def get(url: str, **kwargs: object) -> _Response:
            requests_seen.append(("GET", url, kwargs.get("json")))
            if url.endswith("/api/games"):
                return _Response([
                    {"game_id": game_id, "title": "selected fixture",
                     "baseline_actions": [2, 3]},
                    {"game_id": skipped_id, "title": "skipped fixture",
                     "baseline_actions": [2, 3]},
                ])
            if url.endswith(f"/api/games/{game_id[:4]}"):
                return _Response({
                    "game_id": game_id,
                    "title": "fixture",
                    "baseline_actions": [2, 3],
                })
            raise AssertionError(f"unexpected GET: {url}")

        def post(self: object, url: str, **kwargs: object) -> _Response:
            payload = kwargs.get("json")
            requests_seen.append(("POST", url, payload))
            if url.endswith("/api/scorecard/open"):
                return _Response({"card_id": "card-sdk-fixture"})
            if url.endswith("/api/cmd/RESET"):
                return _Response({
                    "game_id": game_id,
                    "frame": [[[0]]],
                    "state": "NOT_FINISHED",
                    "levels_completed": 0,
                    "win_levels": 2,
                    "guid": "guid-sdk-fixture",
                    "available_actions": [1],
                })
            if url.endswith("/api/scorecard/close"):
                environments = [{
                    "id": game_id,
                    "runs": [{
                        "id": None,
                        "guid": "guid-sdk-fixture",
                        "score": 3.571428571428571,
                        "state": "NOT_FINISHED",
                        "completed": False,
                        "levels_completed": 1,
                        "actions": 20,
                    }],
                }]
                if skipped_row is not None:
                    environments.append(skipped_row)
                return _Response({
                    "card_id": "card-sdk-fixture",
                    "competition_mode": True,
                    "score": 1.7857142857142856,
                    "environments": environments,
                })
            raise AssertionError(f"unexpected POST: {url}")

        with TemporaryDirectory() as directory, \
                mock.patch("requests.sessions.Session.request",
                           side_effect=AssertionError("unexpected HTTP request")), \
                mock.patch("requests.get", side_effect=get), \
                mock.patch("requests.sessions.Session.post", new=post):
            with prepare_session(
                api_key="fixture-api-key",
                evidence_root=Path(directory),
                model_host_ready=True,
                sdk_factory=official.official_sdk_factory,
                selected_game_ids=(game_id,),
            ) as session:
                self.assertEqual(session.preflight.game_ids, (game_id, skipped_id))
                self.assertEqual(session.selected_game_ids, (game_id,))
                self.assertEqual(session.open(), "card-sdk-fixture")
                engine = session.make(game_id)
                observation = engine.observe()
                self.assertEqual(engine.game_id, game_id)
                self.assertEqual(observation["state"], "NOT_FINISHED")
                self.assertEqual(observation["available_actions"], [1])
                self.assertEqual(observation["frame"], [[[0]]])
                self.assertEqual(observation["win_levels"], 2)
                closed = session.close()
                self.assertEqual(closed.card_id, "card-sdk-fixture")
                self.assertEqual(closed.environments[0].runs[0].levels_completed, 1)
                self.assertEqual(closed.environments[0].runs[0].state.name, "NOT_FINISHED")
                if not expect_valid:
                    with self.assertRaisesRegex(OfficialError, "official result unverified"):
                        validate_closed_scorecard(session)
                    return
                receipt = validate_closed_scorecard(session)
                self.assertEqual(receipt.to_dict(), {
                    "schema": "asterion.prime.p7-official-receipt/v1",
                    "mode": "official",
                    "status": "closed-confirmed",
                    "card_id": "card-sdk-fixture",
                    "scorecard_url": "https://arcprize.org/scorecards/card-sdk-fixture",
                    "overall_score": 1.7857142857142856,
                    "catalog_count": 2,
                    "selected_count": 1,
                    "played_runs": 1,
                    "skipped_count": 1,
                    "games_attempted": 1,
                    "games_completed": 0,
                    "games": [{
                        "game_id": game_id,
                        "score": 3.571428571428571,
                        "state": "NOT_FINISHED",
                        "completed": False,
                        "levels_completed": 1,
                        "actions": 20,
                    }],
                    "closure_digest": receipt.closure_digest,
                })

        self.assertEqual([method for method, _, _ in requests_seen], [
            "GET", "POST", "GET", "POST", "POST",
        ])
        self.assertEqual(requests_seen[0][1], f"{official.OFFICIAL_BASE_URL}/api/games")
        self.assertEqual(requests_seen[1][1], f"{official.OFFICIAL_BASE_URL}/api/scorecard/open")
        self.assertEqual(requests_seen[2][1], f"{official.OFFICIAL_BASE_URL}/api/games/{game_id[:4]}")
        self.assertEqual(requests_seen[3][1], f"{official.OFFICIAL_BASE_URL}/api/cmd/RESET")
        self.assertEqual(requests_seen[4][1], f"{official.OFFICIAL_BASE_URL}/api/scorecard/close")


if __name__ == "__main__":
    unittest.main()
