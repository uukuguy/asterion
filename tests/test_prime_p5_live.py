"""Provider-free behavior checks for the P5 live verification boundary."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from asterion.applications.prime.live_model import LiveModelReply, LiveModelUsage
from asterion.applications.prime.p5.receipt import seal
from asterion.agents.prime import application
from asterion.agents.prime.application import PrimeApplicationSpec, PrimeOperatorContext, prepare_prime_application
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.live_model import bounded_text_limits


def _prime(root):
    limits = bounded_text_limits()
    context = PrimeOperatorContext(
        executable=Path("/fake/node"), entry=Path("/fake/pi"), cwd=root.absolute(),
        provider="deepseek", model="deepseek-flash", effort="off", environment={},
        task_deadline=TaskDeadline(deadline_monotonic=time.monotonic() + 120,
                                   deadline_epoch=time.time() + 120),
    )
    return prepare_prime_application(
        PrimeApplicationSpec("prime.test.p5", "1.0.0", "text-only"), context, authorization=limits,
    )


def _owned_session(session, usage):
    prompt = session.prompt
    close = session.close
    reaped = False

    async def measured_prompt(text, *, signal):
        usage.prompts += 1
        try:
            reply = await prompt(text, signal=signal)
        except BaseException:
            usage.blocked = usage.unknown_effect = True
            raise
        usage.input_tokens += reply.usage.input_tokens
        usage.output_tokens += reply.usage.output_tokens
        return reply

    async def owned_close():
        nonlocal reaped
        if reaped:
            return
        try:
            await close()
        except BaseException:
            usage.blocked = True
            raise
        reaped = True

    session.prompt = measured_prompt
    session.close = owned_close
    return session


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
        return LiveModelReply(self.replies.pop(0), LiveModelUsage(12, 4, 9))

    async def close(self) -> None:
        self.closed = True


class P5LiveTests(unittest.TestCase):
    def test_entry_accepts_owner_without_session_factory(self):
        import inspect
        from asterion.applications.prime.p5 import live
        entry = live.run_live_verification
        self.assertNotIn("session_factory", inspect.signature(entry).parameters)
        self.assertIn("prime", inspect.signature(entry).parameters)

    def _invoke(self, root, session):
        from asterion.applications.prime.p5.live import run_live_verification
        prime = _prime(root.parent)
        view = prime.text_model(key="candidate", limits=bounded_text_limits())
        for forbidden in ("process", "open", "close"):
            self.assertFalse(hasattr(view, forbidden))
        with patch.object(application, "LiveModelSession", side_effect=lambda **m: _owned_session(session, m["usage"])):
            return asyncio.run(run_live_verification(prime=prime, private_root=root))

    def _run(self, replies: tuple[str, ...]):
        session = _Session(replies)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            result = self._invoke(root, session)
            self.assertTrue(root.joinpath("live-evidence.json").is_file())
            return result, session

    def test_candidate_failure_feedback_and_repair_with_fake_model(self) -> None:
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

    def test_incomplete_cleanup_prevents_success_evidence(self):
        from asterion.applications.prime.p5.live import P5LiveError
        class UnreapedSession(_Session):
            fail_close = True
            async def close(self):
                raise RuntimeError("PRIVATE-CLEANUP")
        session = UnreapedSession(('{"offset":2}',))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            with self.assertRaises(P5LiveError):
                self._invoke(root, session)
            self.assertFalse((root / "live-evidence.json").exists())

    def test_finalization_checks_cleanup_receipt_before_completed(self):
        from types import SimpleNamespace
        from asterion.applications.prime.p5 import operator
        class Owner:
            async def close(self):
                return SimpleNamespace(complete=False)
        host = operator._ComposedLoopHost(None, None, prime=Owner())
        host.receipt = SimpleNamespace(receipt_sha256="a" * 64)
        with self.assertRaises(operator.P5OperatorError):
            asyncio.run(host.wait_finalization(signal=None))

    def test_direct_execution_ignores_central_provider_composition(self):
        with (
            patch("asterion.applications.provider.compose_installed_provider", side_effect=AssertionError("central composition")),
            patch("asterion.applications.prime.inventory.prime_application_index", side_effect=AssertionError("central inventory")),
            patch("asterion.applications.prime.inventory.prime_release_application", side_effect=AssertionError("central lookup")),
        ):
            result, session = self._run(('{"offset":2}',))
        self.assertEqual(result.terminal_reason, "success")
        self.assertTrue(session.closed)

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
        from asterion.applications.prime.p5.live import P5LiveError

        session = _Session(('PRIVATE_SENTINEL {"offset":2}',))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P5LiveError) as caught:
                self._invoke(Path(tmp) / "private", session)
        self.assertTrue(session.closed)
        self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_model_cancellation_propagates_and_reaps_session(self) -> None:
        class CancellingSession(_Session):
            async def prompt(self, text: str, *, signal: object) -> LiveModelReply:
                raise asyncio.CancelledError()

        session = CancellingSession(())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(asyncio.CancelledError):
                self._invoke(Path(tmp) / "private", session)
        self.assertTrue(session.closed)

    def test_operator_private_base_keeps_evidence_across_runs(self) -> None:
        from asterion.applications.prime.p5 import live

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "persistent"
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(Path(tmp)),
                "ASTERION_PRIME_P5_PRIVATE_ROOT": str(base),
            }
            context = _prime(Path(tmp))._operator
            sessions: list[_Session] = []

            def make_session(**kwargs: object) -> _Session:
                session = _Session(('{"offset":2}',))
                sessions.append(session)
                return _owned_session(session, kwargs["usage"])

            with patch.object(live, "resolve_live_model_context", return_value=context), patch.object(
                application, "LiveModelSession", side_effect=make_session
            ):
                first = asyncio.run(live.run_operator_live(environment))
                second = asyncio.run(live.run_operator_live(environment))
            self.assertNotEqual(first.root_run_id, second.root_run_id)
            evidence = tuple(base.glob("*/live-evidence.json"))
            self.assertEqual(len(evidence), 2)
            self.assertTrue(all(session.closed for session in sessions))


if __name__ == "__main__":
    unittest.main()
