"""Offline official closure contract tests using the SDK's field layout."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from asterion.applications.prime.p7.official import OfficialError
from asterion.applications.prime.p7.official_result import (
    validate_closed_scorecard, write_official_receipt, write_recovery_record,
)


def session():
    rows = [NS(id=game, runs=[NS(id=None, guid=f"guid-{game}", score=score,
                              state=state, completed=state == "WIN",
                              levels_completed=levels, actions=12)])
            for game, score, state, levels in
            [("aa-v1", 100.0, "WIN", 2), ("bb-v2", 0.0, "NOT_FINISHED", 0)]]
    return NS(card_id="card-123", normal_close_confirmed=True, aborted=False,
              recovery_required=False, unattempted_game_ids=(),
              preflight=NS(game_ids=("aa-v1", "bb-v2")),
              guids={r.id: r.runs[0].guid for r in rows},
              closure_result=NS(card_id="card-123", competition_mode=True,
                                score=50.0, environments=rows,
                                api_key="SECRET-SENTINEL", opaque="SECRET-SENTINEL"))


class TestOfficialResult(unittest.TestCase):
    def test_closed_card_preserves_honest_unsolved_score_and_redacts(self):
        current = session()
        receipt = validate_closed_scorecard(current)
        value = receipt.to_dict()
        self.assertEqual(receipt.overall_score, 50.0)
        self.assertEqual(receipt.games_completed, 1)
        self.assertEqual(value["mode"], "official")
        self.assertEqual(receipt.scorecard_url,
                         "https://three.arcprize.org/scorecards/card-123")
        self.assertNotIn("SECRET-SENTINEL", json.dumps(value))
        self.assertNotIn("guid-", json.dumps(value))
        current.closure_result.score = 0.0
        self.assertEqual(receipt.overall_score, 50.0)
        value["games"].clear()
        self.assertEqual(len(receipt.games), 2)

    def test_invalid_or_partial_closure_fails_closed(self):
        changes = [
            lambda s: setattr(s, "normal_close_confirmed", False),
            lambda s: setattr(s, "aborted", True),
            lambda s: setattr(s, "unattempted_game_ids", ("bb-v2",)),
            lambda s: setattr(s.closure_result, "card_id", "other"),
            lambda s: setattr(s, "card_id", "../SECRET-SENTINEL"),
            lambda s: setattr(s.closure_result, "competition_mode", False),
            lambda s: setattr(s.closure_result, "score", float("nan")),
            lambda s: setattr(s.closure_result, "environments", s.closure_result.environments[:1]),
            lambda s: s.closure_result.environments.append(s.closure_result.environments[0]),
            lambda s: s.closure_result.environments[0].runs.append(s.closure_result.environments[0].runs[0]),
            lambda s: setattr(s.closure_result.environments[0].runs[0], "guid", "other"),
            lambda s: setattr(s.closure_result.environments[0].runs[0], "completed", False),
            lambda s: setattr(s.closure_result.environments[0].runs[0], "levels_completed", -1),
            lambda s: setattr(s.closure_result.environments[0].runs[0], "score", True),
            lambda s: setattr(s.closure_result.environments[0].runs[0], "state", None),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                current = deepcopy(session())
                change(current)
                with self.assertRaisesRegex(OfficialError, "official result unverified"):
                    validate_closed_scorecard(current)

    def test_private_files_are_minimal_and_do_not_overwrite(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = session()
            receipt = validate_closed_scorecard(current)
            path = write_official_receipt(receipt, root)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), receipt.to_dict())
            with self.assertRaises(OfficialError):
                write_official_receipt(receipt, root)
            current.normal_close_confirmed = False
            current.recovery_required = True
            recovery = write_recovery_record(current, root)
            text = recovery.read_text()
            self.assertNotIn("SECRET-SENTINEL", text)
            self.assertNotIn("https://", text)
            self.assertEqual(json.loads(text)["status"], "recovery-required")
            self.assertEqual(recovery.stat().st_mode & 0o777, 0o600)
