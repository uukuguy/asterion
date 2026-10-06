"""Saved historical actions have a bounded replay allowance of their own."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
from asterion.applications.prime.p7 import solutions
from tests import test_prime_p7_solutions as saved_tests


class _LongPrefixEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self):
        self.calls = 0

    def observe(self):
        return {"available_actions": ["ACTION1"], "frame": [[[self.calls % 16]]],
                "levels_completed": int(self.calls >= 501),
                "state": "NOT_FINISHED", "win_levels": 7}

    def step(self, action, data=None):
        self.calls += 1
        return self.observe()


class TestPrefixReplayBudget(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.arc = saved_tests.TestP7SavedSolutions._arc_root(self.root)
        self.run = self.root / "runs" / "long-prefix"
        self.game = P7GameSelection("ls20-9607627b", 0, 1, action_cap_override=501)
        broker = ArcBroker(engine=_LongPrefixEngine(), game=self.game)
        for _ in range(501):
            broker.act(("ACTION1",))
        receipt = broker.seal()
        trace = self.run / "trace"
        trace.mkdir(parents=True)
        recorder = PrimeTraceRecorder(trace)
        for item in broker.journal:
            recorder.append("arc.action", P7_TRACE_IDENTITIES, {
                "sequence": item.sequence, "action": item.action,
                "before_sha256": item.before_sha256, "after_sha256": item.after_sha256,
                "levels_completed": item.levels_completed,
            })
        evidence = {"game_id": self.game.game_id, "seed": 0, "win_levels": 7,
                    "primitive_actions": 501, "levels_completed": 1,
                    "terminal_reason": receipt.terminal_reason,
                    "replay_sha256": receipt.replay_sha256}
        recorder.append("arc.run.completed", P7_TRACE_IDENTITIES, evidence)
        recorder.seal()
        session = self.run / "recordings" / "session"
        session.mkdir(parents=True)
        rows = [{"data": {"game_id": self.game.game_id, "win_levels": 7,
                          "action_input": {"id": "RESET", "data": {}}}}]
        rows += [{"data": {"game_id": self.game.game_id, "win_levels": 7,
                           "action_input": {"id": "ACTION1", "data": {}}}}] * 501
        (session / "fixture.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.summary = {"schema": "asterion.prime.p7-live-private-summary/v1",
                        "run_id": self.run.name, "broker": evidence,
                        "receipt": {"completed_level_count": 1, "primitive_action_count": 501},
                        "sealed_trace": True, "replay_verified": True, "cleanup_complete": True,
                        "completed_prefix": None, "failure": None}
        (self.run / "summary.json").write_text(json.dumps(self.summary))

    def test_exact_saved_prefix_above_default_cap_replays_without_new_authority(self):
        original = (self.run / "summary.json").read_bytes()
        with patch.object(solutions, "_fresh_engine", side_effect=lambda *_: _LongPrefixEngine()):
            prefix = solutions.load_exact_prefix(self.arc, self.run.parent, self.run.name,
                                                 self.game.game_id, 0)
        self.assertIsNotNone(prefix)
        self.assertEqual((prefix.levels_completed, len(prefix.transitions)), (1, 501))
        self.assertEqual(self.game.target_level, 1)
        self.assertEqual(P7GameSelection(self.game.game_id, 0, 2).action_cap, 500)
        self.assertEqual((self.run / "summary.json").read_bytes(), original)

    def test_replay_cap_comes_from_exact_actions_not_mutable_experiment_budget(self):
        self.summary["experiment"] = {"action_cap": 999999}
        (self.run / "summary.json").write_text(json.dumps(self.summary))
        evidence = solutions._read_one(self.arc, self.run, self.game.game_id, 0, None)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence[2].action_cap, 501)
        self.assertEqual(evidence[2].target_level, 1)

    def test_unverified_or_wrong_identity_stays_rejected(self):
        self.summary["replay_verified"] = False
        (self.run / "summary.json").write_text(json.dumps(self.summary))
        self.assertIsNone(solutions._read_one(self.arc, self.run, self.game.game_id, 0, None))
        self.assertIsNone(solutions._read_one(self.arc, self.run, "tu93-0768757b", 0, None))
