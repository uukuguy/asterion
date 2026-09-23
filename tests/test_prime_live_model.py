"""Bounded application-owned Pi model session, using a local JSONL producer."""

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import tempfile
import unittest

from asterion.applications.prime.live_model import LiveModelError, LiveModelSession


_PRODUCER = r"""
import json, sys, time
def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req["type"] == "abort":
        break
    if req["type"] != "prompt":
        continue
    mode = req["message"]
    emit({"type": "response", "id": req["id"], "success": True})
    emit({"type": "agent_start"})
    if mode == "block":
        time.sleep(30)
    emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "private answer"}})
    usage = {"input": 1000, "output": 500}
    if mode == "missing-usage":
        del usage["input"]
    if mode == "over-tokens":
        usage["output"] = 1_000_000
    if mode == "over-cost":
        usage["input"] = 12_000
        usage["output"] = 6_000
    if mode == "over-output":
        emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "x" * 40_000}})
    emit({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "usage": usage}})
    emit({"type": "agent_end", "messages": []})
    emit({"type": "agent_settled"})
"""


class _NeverCancelled:
    cancelled = False


class _Cancel:
    cancelled = False


class TestLiveModelSession(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        script = Path(self.temp.name) / "producer.py"
        script.write_text(_PRODUCER)
        self.session = LiveModelSession(
            command=(sys.executable, "-I", str(script)),
            environment={},
            cwd=Path(self.temp.name),
        )

    async def _cleanup(self):
        await self.session.close()
        self.temp.cleanup()

    async def test_private_answer_and_immutable_actual_usage(self):
        await self.session.open(signal=_NeverCancelled())
        reply = await self.session.prompt("hello", signal=_NeverCancelled())
        self.assertEqual(reply.text, "private answer")
        self.assertEqual(reply.usage.input_tokens, 1000)
        self.assertEqual(reply.usage.output_tokens, 500)
        self.assertEqual(reply.usage.cost_micros, 280)
        with self.assertRaises(FrozenInstanceError):
            reply.usage.input_tokens = 99
        self.assertNotIn("private answer", repr(reply))

    async def test_missing_usage_fails_closed_and_reaps(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError) as caught:
            await self.session.prompt("missing-usage", signal=_NeverCancelled())
        self.assertNotIn("private", repr(caught.exception))
        self.assertIsNotNone(process.poll())

    async def test_token_limit_fails_closed(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError):
            await self.session.prompt("over-tokens", signal=_NeverCancelled())
        self.assertIsNotNone(process.poll())

    async def test_cost_limit_fails_closed(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError):
            await self.session.prompt("over-cost", signal=_NeverCancelled())
        self.assertIsNotNone(process.poll())

    async def test_output_limit_fails_closed(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError):
            await self.session.prompt("over-output", signal=_NeverCancelled())
        self.assertIsNotNone(process.poll())

    async def test_prompt_count_limit_fails_closed(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        for _ in range(4):
            await self.session.prompt("hello", signal=_NeverCancelled())
        with self.assertRaises(LiveModelError):
            await self.session.prompt("hello", signal=_NeverCancelled())
        self.assertIsNotNone(process.poll())

    async def test_cancel_active_prompt_closes_child(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        task = asyncio.create_task(
            self.session.prompt("block", signal=_NeverCancelled())
        )
        await asyncio.sleep(0.1)
        task.cancel("SECRET-CANCEL")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(process.poll())

    async def test_input_limit_rejects_before_child_prompt(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError):
            await self.session.prompt("x" * 100_000, signal=_NeverCancelled())
        self.assertIsNotNone(process.poll())
