from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession, build_rpc_session


_PRODUCER = r'''
import json
import sys
import time

mode, marker = sys.argv[1:]
def emit(payload):
    print(json.dumps(payload), flush=True)

for line in sys.stdin:
    request = json.loads(line)
    with open(marker, "a", encoding="utf-8") as output:
        output.write(json.dumps(request) + "\n")
    if request["type"] == "get_state":
        if mode == "timeout":
            time.sleep(60)
        elif mode == "invalid-json":
            print("{PRIVATE-BODY", flush=True)
        else:
            model = {"provider": "test-provider", "id": "test/model-v1"}
            response = {"type": "response", "id": request["id"],
                        "command": "get_state", "success": True,
                        "data": {"model": model, "private": "PRIVATE-BODY"}}
            if mode == "provider-mismatch":
                model["provider"] = "PRIVATE-PROVIDER"
            elif mode == "model-mismatch":
                model["id"] = "PRIVATE-MODEL"
            elif mode == "missing-model":
                response["data"] = {"private": "PRIVATE-BODY"}
            elif mode == "wrong-id":
                response["id"] = "PRIVATE-ID"
            elif mode == "wrong-command":
                response["command"] = "PRIVATE-COMMAND"
            elif mode == "failed":
                response["success"] = False
                response["error"] = "PRIVATE-BODY"
            elif mode == "malformed-model":
                response["data"]["model"] = "PRIVATE-BODY"
            emit(response)
    elif request["type"] == "prompt":
        emit({"type": "response", "id": request["id"], "success": True})
        emit({"type": "message_update", "assistantMessageEvent": {
            "type": "text_delta", "delta": "done"}})
        emit({"type": "agent_settled"})
    elif request["type"] == "abort":
        break
'''


class NeverCancelled:
    cancelled = False


class TestPiRpcModelIdentity(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.producer = self.root / "producer.py"
        self.producer.write_text(_PRODUCER, encoding="utf-8")
        self.marker = self.root / "requests.jsonl"
        self.children: list[subprocess.Popen[bytes]] = []

    def config(self, mode="matching", **options) -> PiRpcConfig:
        return PiRpcConfig(
            (sys.executable, "-u", str(self.producer), mode, str(self.marker)),
            self.root, {}, deadline_seconds=options.pop("deadline_seconds", 1.0),
            **options,
        )

    def session(self, mode="matching", *, checked=True, **options) -> PiRpcSession:
        if checked:
            options.update(expected_provider="test-provider", expected_model="test/model-v1")
        def spawn(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            self.children.append(process)
            return process
        rpc = PiRpcSession(self.config(mode, **options), _popen=spawn)
        self.addAsyncCleanup(rpc.close)
        return rpc

    def requests(self) -> list[dict]:
        if not self.marker.exists():
            return []
        return [json.loads(line) for line in self.marker.read_text().splitlines()]

    def assert_reaped(self, rpc: PiRpcSession) -> None:
        self.assertIsNone(rpc.process)
        self.assertTrue(self.children)
        self.assertTrue(all(process.poll() is not None for process in self.children))

    def test_expected_identity_is_optional_paired_and_safe(self) -> None:
        self.assertIsNone(self.config().expected_provider)
        self.assertIsNone(self.config().expected_model)
        for provider, model in (
            ("test-provider", None), (None, "test/model-v1"),
            ("", "model"), ("provider", ""),
            ("provider\nPRIVATE", "model"), ("provider", "model\x00PRIVATE"),
            (False, "model"), ("provider", 42), (" provider", "model"),
        ):
            with self.subTest(provider=provider, model=model):
                with self.assertRaisesRegex(ValueError, "expected model identity is invalid"):
                    self.config(expected_provider=provider, expected_model=model)

    def test_builder_forwards_expected_identity(self) -> None:
        rpc = build_rpc_session(
            command=(sys.executable,), cwd=self.root, environment={}, deadline_seconds=1,
            expected_provider="test-provider", expected_model="test/model-v1",
        )
        self.assertEqual(rpc.config.expected_provider, "test-provider")
        self.assertEqual(rpc.config.expected_model, "test/model-v1")

    async def test_matching_identity_is_checked_before_run_prompt(self) -> None:
        for compact_events in (False, True):
            with self.subTest(compact_events=compact_events):
                self.marker.unlink(missing_ok=True)
                rpc = self.session(compact_events=compact_events)
                result = await rpc.run("PRIVATE-PROMPT", signal=NeverCancelled(), on_event=lambda _: None)
                self.assertEqual(result.final_text, "done")
                self.assertEqual([request["type"] for request in self.requests()], ["get_state", "prompt"])
                self.assertNotIn("PRIVATE-BODY", repr(result.events))
                self.assertEqual([event.sequence for event in result.events], list(range(1, len(result.events) + 1)))
                self.assert_reaped(rpc)

    async def test_every_open_checks_the_new_child(self) -> None:
        rpc = self.session()
        for _ in range(2):
            await rpc.open(signal=NeverCancelled())
            await rpc.prompt("PRIVATE-PROMPT", signal=NeverCancelled(), on_event=lambda _: None)
            await rpc.close()
        self.assertEqual([request["type"] for request in self.requests()], ["get_state", "prompt", "get_state", "prompt"])
        self.assert_reaped(rpc)

    async def test_mismatch_or_malformed_state_rejects_before_prompt(self) -> None:
        for mode in ("provider-mismatch", "model-mismatch", "missing-model", "wrong-id",
                     "wrong-command", "failed", "malformed-model", "invalid-json"):
            for entry in ("run", "open", "start"):
                with self.subTest(mode=mode, entry=entry):
                    self.marker.unlink(missing_ok=True)
                    rpc = self.session(mode)
                    with self.assertRaisesRegex(RuntimeError, "Pi RPC model identity") as raised:
                        if entry == "run":
                            await rpc.run("PRIVATE-PROMPT", signal=NeverCancelled(), on_event=lambda _: None)
                        elif entry == "open":
                            await rpc.open(signal=NeverCancelled())
                        else:
                            rpc.start()
                    self.assertNotIn("PRIVATE", str(raised.exception))
                    self.assertEqual([request["type"] for request in self.requests()], ["get_state"])
                    self.assert_reaped(rpc)

    async def test_state_timeout_is_bounded_and_reaps_child(self) -> None:
        rpc = self.session("timeout", deadline_seconds=0.1)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "Pi RPC model identity"):
            await rpc.open(signal=NeverCancelled())
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual([request["type"] for request in self.requests()], ["get_state"])
        self.assert_reaped(rpc)

    async def test_state_timeout_remains_finite_without_session_deadline(self) -> None:
        rpc = self.session("timeout", deadline_seconds=None)
        with patch("asterion.runtimes.pi_rpc._MODEL_IDENTITY_TIMEOUT_SECONDS", 0.1):
            with self.assertRaisesRegex(RuntimeError, "Pi RPC model identity"):
                await rpc.open(signal=NeverCancelled())
        self.assertEqual([request["type"] for request in self.requests()], ["get_state"])
        self.assert_reaped(rpc)

    async def test_cancelled_startup_reaps_child_before_returning(self) -> None:
        rpc = self.session("timeout", deadline_seconds=None)
        pending = asyncio.create_task(rpc.open(signal=NeverCancelled()))
        for _ in range(100):
            if self.requests():
                break
            await asyncio.sleep(0.01)
        self.assertEqual([request["type"] for request in self.requests()], ["get_state"])
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 1.5)
        self.assert_reaped(rpc)

    async def test_no_expected_identity_preserves_prompt_only_transport(self) -> None:
        rpc = self.session(checked=False)
        result = await rpc.run("PRIVATE-PROMPT", signal=NeverCancelled(), on_event=lambda _: None)
        self.assertEqual(result.final_text, "done")
        self.assertEqual([request["type"] for request in self.requests()], ["prompt"])
        self.assert_reaped(rpc)


if __name__ == "__main__":
    unittest.main()
