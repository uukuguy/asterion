"""Provider-free behavior checks for the P5 live verification boundary."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.live_model import LiveModelReply, LiveModelUsage
from asterion.applications.prime.p5.receipt import seal


class _Session:
    def __init__(self, replies: tuple[str, ...]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.opened = False
        self.closed = False

    async def open(self, *, signal: object) -> None:
        self.opened = True

    async def prompt(self, text: str, *, signal: object) -> LiveModelReply:
        self.prompts.append(text)
        return LiveModelReply(self.replies.pop(0), LiveModelUsage(12, 4, 3))

    async def close(self) -> None:
        self.closed = True


class P5LiveTests(unittest.TestCase):
    def _run(self, replies: tuple[str, ...]):
        from asterion.applications.prime.p5.live import run_live_verification

        session = _Session(replies)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            result = asyncio.run(
                run_live_verification(
                    session_factory=lambda role, cwd: session,
                    private_root=root,
                    command_sha256="a" * 64,
                    binding_sha256="b" * 64,
                )
            )
            self.assertTrue(root.joinpath("live-evidence.json").is_file())
            return result, session

    def test_real_candidate_failure_feedback_and_repair(self) -> None:
        result, session = self._run(('{"offset":1}', '{"offset":2}'))
        self.assertTrue(session.opened)
        self.assertTrue(session.closed)
        self.assertEqual(len(session.prompts), 2)
        self.assertIn("expected", session.prompts[1])
        self.assertEqual(result.terminal_reason, "success")
        self.assertEqual(
            (
                result.verify_step_count,
                result.failed_verify_count,
                result.repair_step_count,
            ),
            (2, 1, 1),
        )
        self.assertEqual(result.model_call_count, 2)
        self.assertEqual(
            result.joined_workspace_digest,
            sha256(b'{"offset":2}').hexdigest(),
        )
        self.assertNotIn("offset", repr(result))

    def test_correct_first_candidate_needs_no_fake_failure(self) -> None:
        result, session = self._run(('{"offset":2}',))
        self.assertEqual(
            (
                result.verify_step_count,
                result.failed_verify_count,
                result.repair_step_count,
            ),
            (1, 0, 0),
        )
        self.assertEqual(len(session.prompts), 1)

    def test_receipt_accepts_real_first_pass(self) -> None:
        receipt = seal(
            root_run_id="p5-root",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=1,
            repair_step_count=0,
            failed_verify_count=0,
            terminal_reason="success",
            joined_workspace_digest="a" * 64,
        )
        self.assertEqual(receipt.failed_verify_count, 0)

    def test_malformed_model_artifact_fails_closed_and_reaps_session(self) -> None:
        from asterion.applications.prime.p5.live import (
            P5LiveError,
            run_live_verification,
        )

        session = _Session(('PRIVATE_SENTINEL {"offset":2}',))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P5LiveError) as caught:
                asyncio.run(
                    run_live_verification(
                        session_factory=lambda role, cwd: session,
                        private_root=Path(tmp) / "private",
                        command_sha256="a" * 64,
                        binding_sha256="b" * 64,
                    )
                )
        self.assertTrue(session.closed)
        self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_model_cancellation_propagates_and_reaps_session(self) -> None:
        from asterion.applications.prime.p5.live import run_live_verification

        class CancellingSession(_Session):
            async def prompt(self, text: str, *, signal: object) -> LiveModelReply:
                raise asyncio.CancelledError()

        session = CancellingSession(())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(
                    run_live_verification(
                        session_factory=lambda role, cwd: session,
                        private_root=Path(tmp) / "private",
                        command_sha256="a" * 64,
                        binding_sha256="b" * 64,
                    )
                )
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
