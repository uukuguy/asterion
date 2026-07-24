from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.pi import PiRuntimeClient


SUCCESS_SCRIPT = r'''
import json
import sys

request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({
    "type": "message_update",
    "assistantMessageEvent": {"type": "text_delta", "delta": "Pudding Lane"}
}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

INVALID_JSON_SCRIPT = r'''
import sys
sys.stdin.readline()
print("SECRET-NOT-JSON", flush=True)
'''

EARLY_EOF_SCRIPT = r'''
import json
import sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
'''

SLOW_SCRIPT = r'''
import sys
import time
sys.stdin.readline()
time.sleep(5)
'''


class MutableSignal:
    def __init__(self) -> None:
        self.cancelled = False


class PiRuntimeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_translates_one_pi_rpc_run_to_normalized_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SUCCESS_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read", "shell"),
            )

            events = [
                event
                async for event in client.run(
                    RunRequest(
                        run_id="pi-run-1",
                        input_text="Read the corpus",
                        requested_capabilities=("filesystem.read", "shell"),
                    )
                )
            ]

        self.assertEqual(client.manifest.runtime_id, "pi.reference")
        self.assertEqual(
            tuple(event.type for event in events),
            ("run.started", "text.delta", "artifact.created", "run.completed"),
        )
        self.assertEqual(events[-1].payload["status"], "completed")

    async def test_capability_mismatch_fails_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=("missing-secret-command",),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            with self.assertRaises(ProtocolError) as raised:
                _ = [
                    event
                    async for event in client.run(
                        RunRequest(
                            run_id="capability-mismatch",
                            input_text="SECRET-INPUT",
                            requested_capabilities=("shell",),
                        )
                    )
                ]
        self.assertNotIn("SECRET", str(raised.exception))

    async def test_invalid_json_and_early_eof_are_redacted(self) -> None:
        for script in (INVALID_JSON_SCRIPT, EARLY_EOF_SCRIPT):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temp_dir:
                client = PiRuntimeClient(
                    command=(sys.executable, "-u", "-c", script),
                    cwd=Path(temp_dir),
                    capabilities=("filesystem.read",),
                )
                with self.assertRaises(ProtocolError) as raised:
                    _ = [
                        event
                        async for event in client.run(
                            RunRequest(
                                run_id="invalid-stream",
                                input_text="SECRET-INPUT",
                                requested_capabilities=("filesystem.read",),
                            )
                        )
                    ]
                self.assertNotIn("SECRET", str(raised.exception))

    async def test_cancellation_aborts_and_reaps_a_slow_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            signal = MutableSignal()

            async def cancel() -> None:
                await asyncio.sleep(0.05)
                signal.cancelled = True

            cancel_task = asyncio.create_task(cancel())
            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="cancelled-run",
                            input_text="Read the corpus",
                            requested_capabilities=("filesystem.read",),
                        ),
                        signal,
                    ),
                    timeout=1,
                )
            await cancel_task

    async def test_rejects_a_second_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            first_signal = MutableSignal()
            first = asyncio.create_task(
                _collect(
                    client,
                    RunRequest(
                        run_id="first-run",
                        input_text="Read the corpus",
                        requested_capabilities=("filesystem.read",),
                    ),
                    first_signal,
                )
            )
            await asyncio.sleep(0.05)
            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="second-run",
                            input_text="Read the corpus",
                            requested_capabilities=("filesystem.read",),
                        ),
                        MutableSignal(),
                    ),
                    timeout=0.5,
                )
            first_signal.cancelled = True
            with self.assertRaises(ProtocolError):
                await first

    async def test_request_deadline_terminates_and_reaps_the_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="deadline-run",
                            input_text="Read the corpus",
                            requested_capabilities=("filesystem.read",),
                            deadline_ms=50,
                        ),
                        MutableSignal(),
                    ),
                    timeout=1,
                )


async def _collect(
    client: PiRuntimeClient,
    request: RunRequest,
    signal: MutableSignal,
):
    return [event async for event in client.run(request, signal=signal)]


if __name__ == "__main__":
    unittest.main()
