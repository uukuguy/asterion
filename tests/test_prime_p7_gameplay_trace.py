"""Scoreless gameplay trace seals and accessor identity."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import ArcGameContract
from asterion.applications.prime.p7.gameplay_trace import PrimeGameplayTrace
from asterion.applications.prime.runtime_binding import _p7_gameplay_terminal


class _WinningEngine:
    game_id = "zz99-abcdef12"
    seed = 0

    def __init__(self) -> None:
        self.won = False

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": [] if self.won else ["ACTION1"],
            "frame": [[[1]]],
            "levels_completed": 1 if self.won else 0,
            "state": "WIN" if self.won else "NOT_FINISHED",
            "win_levels": 1,
        }

    def step(self, action: str) -> dict[str, object]:
        self.won = action == "ACTION1"
        return self.observe()


class _ResetRequiredEngine:
    game_id = "zz99-abcdef12"
    seed = 0

    def __init__(self) -> None:
        self.state = "NOT_FINISHED"

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1"],
            "frame": [[[1]]],
            "levels_completed": 0,
            "state": self.state,
            "win_levels": 2,
        }

    def step(self, action: str) -> dict[str, object]:
        del action
        self.state = "GAME_OVER"
        return self.observe()


class TestPrimeP7GameplayTrace(unittest.TestCase):
    def test_reset_required_keeps_official_runtime_open_and_cannot_issue_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(
                engine=_ResetRequiredEngine(),
                game=ArcGameContract("zz99-abcdef12", win_levels=2),
            )
            trace = PrimeGameplayTrace(broker, recorder, "guid-zz99")
            broker.act(("ACTION1",))
            self.assertEqual(broker.status().terminal_reason, "reset-required")
            self.assertFalse(_p7_gameplay_terminal(broker))
            with self.assertRaisesRegex(RuntimeError, "evidence is unavailable"):
                trace.expected_evidence_sha256(run_id="official-run")

    def test_valid_digest_round_trips_after_trace_seal(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = PrimeTraceRecorder(root)
            engine = _WinningEngine()
            broker = ArcBroker(
                engine=engine,
                game=ArcGameContract("zz99-abcdef12", win_levels=1),
            )
            trace = PrimeGameplayTrace(broker, recorder, "guid-zz99")
            broker.act(("ACTION1",))
            digest = trace.expected_evidence_sha256(run_id="official-run")
            evidence = trace.get_evidence(
                run_id="official-run", evidence_sha256=digest
            )
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(evidence.trace_sha256, r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(evidence.evidence_sha256, digest)
            self.assertEqual(evidence.sdk_state, "WIN")
