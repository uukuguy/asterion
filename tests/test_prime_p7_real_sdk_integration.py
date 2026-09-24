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
from asterion.applications.prime.p7.official import prepare_session


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
    def test_prepare_open_make_close_uses_real_sdk_without_network(self) -> None:
        """The adapter's minimal lifecycle matches the installed SDK API."""
        game_id = "ab12-12345678"
        requests_seen: list[tuple[str, str, object]] = []

        def get(url: str, **kwargs: object) -> _Response:
            requests_seen.append(("GET", url, kwargs.get("json")))
            if url.endswith("/api/games"):
                return _Response([{
                    "game_id": game_id,
                    "title": "fixture",
                    "baseline_actions": [2],
                }])
            if url.endswith(f"/api/games/{game_id[:4]}"):
                return _Response({
                    "game_id": game_id,
                    "title": "fixture",
                    "baseline_actions": [2],
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
                    "win_levels": 1,
                    "guid": "guid-sdk-fixture",
                    "available_actions": [1],
                })
            if url.endswith("/api/scorecard/close"):
                return _Response({
                    "card_id": "card-sdk-fixture",
                    "competition_mode": True,
                    "score": 0.0,
                    "environments": [{"id": game_id, "runs": []}],
                })
            raise AssertionError(f"unexpected POST: {url}")

        with TemporaryDirectory() as directory, \
                mock.patch("requests.get", side_effect=get), \
                mock.patch("requests.sessions.Session.post", new=post):
            with prepare_session(
                api_key="fixture-api-key",
                evidence_root=Path(directory),
                model_host_ready=True,
                sdk_factory=official.official_sdk_factory,
            ) as session:
                self.assertEqual(session.preflight.game_ids, (game_id,))
                self.assertEqual(session.open(), "card-sdk-fixture")
                engine = session.make(game_id)
                observation = engine.observe()
                self.assertEqual(engine.game_id, game_id)
                self.assertEqual(observation["state"], "NOT_FINISHED")
                self.assertEqual(observation["available_actions"], [1])
                self.assertEqual(observation["frame"], [[[0]]])
                self.assertEqual(observation["win_levels"], 1)
                closed = session.close()
                self.assertEqual(closed.card_id, "card-sdk-fixture")

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
