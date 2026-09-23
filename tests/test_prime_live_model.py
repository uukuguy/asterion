"""Bounded application-owned Pi model session, using a local JSONL producer."""

import asyncio
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import asterion

from asterion.applications.prime.live_model import (
    LiveModelError,
    LiveModelSession,
    resolve_live_model_launch,
)


_PRODUCER = r"""
import json, sys, time
def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req["type"] == "abort":
        break
    if req["type"] == "get_state":
        emit({"type": "response", "id": req["id"], "command": "get_state", "success": True,
              "data": {"model": {"provider": "deepseek", "id": "deepseek-v4-flash", "maxTokens": 512}}})
        continue
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
    if mode == "cached":
        usage = {"input": 100, "output": 100, "cacheRead": 2000, "cacheWrite": 100}
    if mode == "bad-cache":
        usage = {"input": 100, "output": 100, "cacheRead": -1}
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

    async def test_provider_output_cap_is_installed_in_private_model_config(self):
        config_root = Path(self.session._rpc.config.environment["PI_CODING_AGENT_DIR"])
        model_config = json.loads((config_root / "models.json").read_text())
        self.assertEqual(
            model_config["providers"]["deepseek"]["modelOverrides"][
                "deepseek-v4-flash"
            ]["maxTokens"],
            512,
        )
        self.assertNotIn("SECRET", (config_root / "models.json").read_text())
        await self.session.close()
        self.assertFalse(config_root.exists())

    async def test_model_cap_mismatch_rejected_before_prompt(self):
        script = Path(self.temp.name) / "bad-producer.py"
        script.write_text(_PRODUCER.replace('"maxTokens": 512', '"maxTokens": 2048'))
        other = LiveModelSession(
            command=(sys.executable, "-I", str(script)),
            environment={},
            cwd=Path(self.temp.name),
        )
        try:
            with self.assertRaises(LiveModelError):
                await other.open(signal=_NeverCancelled())
            self.assertIsNone(other.process)
        finally:
            await other.close()

    async def test_missing_usage_fails_closed_and_reaps(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError) as caught:
            await self.session.prompt("missing-usage", signal=_NeverCancelled())
        self.assertNotIn("private", repr(caught.exception))
        self.assertIsNotNone(process.poll())

    async def test_cached_prompt_tokens_count_toward_usage_and_cost(self):
        await self.session.open(signal=_NeverCancelled())
        reply = await self.session.prompt("cached", signal=_NeverCancelled())
        self.assertEqual(reply.usage.input_tokens, 2200)
        self.assertEqual(reply.usage.output_tokens, 100)
        self.assertEqual(reply.usage.cost_micros, 336)

    async def test_invalid_cache_usage_fails_closed(self):
        await self.session.open(signal=_NeverCancelled())
        process = self.session.process
        with self.assertRaises(LiveModelError):
            await self.session.prompt("bad-cache", signal=_NeverCancelled())
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


class TestResolveLiveModelLaunch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "operator"
        self.root.mkdir()
        node = self.root / "node"
        pi = self.root / "pi.mjs"
        node.write_text("node")
        pi.write_text("pi")
        node.chmod(0o700)
        pi.chmod(0o700)
        (self.root / ".env").write_text(
            "DEEPSEEK_API_KEY=from-file\nPI_CODING_AGENT_DIR=/private/unsafe\n"
        )
        installed = self.root.parent / "venv/site-packages/asterion/__init__.py"
        installed.parent.mkdir(parents=True)
        installed.write_text("")
        self.installed = installed
        self.environment = {
            "ASTERION_PRIME_NODE": str(node),
            "ASTERION_PRIME_PI_ENTRY": str(pi),
            "PATH": "/usr/bin",
        }

    def test_fixed_no_tool_launch_and_redacted_immutable_environment(self):
        with patch.object(asterion, "__file__", str(self.installed)):
            launch = resolve_live_model_launch(self.root, self.environment)
        self.assertEqual(launch.cwd, self.root.resolve())
        self.assertEqual(
            launch.command[:2],
            (
                str((self.root / "node").resolve()),
                str((self.root / "pi.mjs").resolve()),
            ),
        )
        for option in (
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-session",
        ):
            self.assertIn(option, launch.command)
        self.assertEqual(
            launch.command[-4:],
            ("--provider", "deepseek", "--model", "deepseek-v4-flash"),
        )
        self.assertEqual(launch.environment["DEEPSEEK_API_KEY"], "from-file")
        self.assertNotIn("PI_CODING_AGENT_DIR", launch.environment)
        self.assertNotIn("from-file", repr(launch))
        with self.assertRaises(TypeError):
            launch.environment["DEEPSEEK_API_KEY"] = "mutated"

    def test_environment_credential_overrides_dotenv(self):
        with patch.object(asterion, "__file__", str(self.installed)):
            launch = resolve_live_model_launch(
                self.root, {**self.environment, "DEEPSEEK_API_KEY": "from-env"}
            )
        self.assertEqual(launch.environment["DEEPSEEK_API_KEY"], "from-env")

    def test_source_checkout_is_rejected(self):
        with patch.object(
            asterion, "__file__", str(self.root / "src/asterion/__init__.py")
        ):
            with self.assertRaises(LiveModelError):
                resolve_live_model_launch(self.root, self.environment)

    def test_missing_credential_and_non_executable_entry_are_rejected(self):
        (self.root / ".env").write_text("DEEPSEEK_API_KEY=\n")
        with patch.object(asterion, "__file__", str(self.installed)):
            with self.assertRaises(LiveModelError):
                resolve_live_model_launch(self.root, self.environment)
            (self.root / ".env").write_text("DEEPSEEK_API_KEY=secret\n")
            (self.root / "pi.mjs").chmod(0o600)
            with self.assertRaises(LiveModelError):
                resolve_live_model_launch(self.root, self.environment)
