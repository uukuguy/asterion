"""P6 live candidate path with an in-memory model session, no provider call."""

import tempfile
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from asterion.applications.prime.live_model import (
    LiveModelLaunch,
    LiveModelReply,
    LiveModelUsage,
)
from asterion.applications.prime.p6.live import run_live_candidate, run_operator_live


class _Session:
    def __init__(self, answer: str):
        self.answer = answer
        self.prompts: list[str] = []
        self.closed = False

    async def open(self, *, signal):
        return None

    async def prompt(self, text: str, *, signal):
        self.prompts.append(text)
        return LiveModelReply(self.answer, LiveModelUsage(1000, 500, 280))

    async def close(self):
        self.closed = True


class TestP6Live(unittest.IsolatedAsyncioTestCase):
    async def test_model_candidate_is_admitted_evaluated_and_promoted(self):
        session = _Session('{"multiplier":3,"offset":1}')
        with tempfile.TemporaryDirectory() as temporary:
            result = await run_live_candidate(
                session_factory=lambda: session,
                root_run_id="p6-live-one",
                private_root=Path(temporary),
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.terminal_outcome, "preserved")
            self.assertEqual(result.rollback_invocation_count, 0)
            self.assertNotEqual(
                result.candidate_revision_digest, result.baseline_snapshot_digest
            )
            self.assertEqual(len(session.prompts), 1)
            self.assertNotIn("-3", session.prompts[0], "holdout inputs reached model")
            self.assertTrue(session.closed)

            self.assertTrue((Path(temporary) / "candidate.json").is_file())
            self.assertTrue((Path(temporary) / "holdout-evidence.json").is_file())
            self.assertNotIn("multiplier", repr(result))

    async def test_invalid_candidate_fails_before_admission_and_closes(self):
        session = _Session("PRIVATE invalid candidate")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(Exception) as caught:
                await run_live_candidate(
                    session_factory=lambda: session,
                    root_run_id="p6-live-invalid",
                    private_root=Path(temporary),
                )
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertTrue(session.closed)
            self.assertFalse((Path(temporary) / "candidate.json").exists())

    async def test_non_improving_candidate_rolls_back(self):
        session = _Session('{"multiplier":2,"offset":0}')
        with tempfile.TemporaryDirectory() as temporary:
            result = await run_live_candidate(
                session_factory=lambda: session,
                root_run_id="p6-live-regressed",
                private_root=Path(temporary),
            )
            self.assertEqual(result.terminal_outcome, "rolled-back")
            self.assertEqual(result.rollback_invocation_count, 1)
            self.assertTrue(session.closed)


class TestP6LiveOperator(unittest.TestCase):
    def test_two_operator_runs_use_distinct_private_children_and_safe_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            launch = LiveModelLaunch(("node", "pi"), {}, root)
            output = io.StringIO()
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(root),
                "ASTERION_PRIME_P6_PRIVATE_ROOT": str(private),
            }
            with (
                patch(
                    "asterion.applications.prime.p6.live.resolve_live_model_launch",
                    return_value=launch,
                ),
                patch(
                    "asterion.applications.prime.p6.live.LiveModelSession",
                    side_effect=lambda **_kwargs: _Session(
                        '{"multiplier":3,"offset":1}'
                    ),
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(run_operator_live(environment), 0)
                self.assertEqual(run_operator_live(environment), 0)
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(
                [record["status"] for record in records], ["completed", "completed"]
            )
            self.assertEqual(len(list(private.glob("*/candidate.json"))), 2)
            self.assertNotIn("multiplier", output.getvalue())

    def test_operator_preflight_failure_has_generic_public_result(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                run_operator_live({"DEEPSEEK_API_KEY": "PRIVATE-CREDENTIAL"}), 2
            )
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "failed", "reason": "p6-live-unavailable"},
        )
