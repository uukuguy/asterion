from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcResult, PiRpcSession


_FAKE_REUSABLE_PI = r"""
import json
import os
import sys
import time

def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    request_type = request["type"]
    if request_type == "prompt":
        message = request["message"]
        response_id = "wrong" if message == "mismatch" else request["id"]
        emit({"type": "response", "id": response_id, "success": True})
        emit({"type": "agent_start", "pid": os.getpid()})
        if message == "blocking":
            abort = json.loads(sys.stdin.readline())
            with open(sys.argv[1], "w", encoding="utf-8") as marker:
                marker.write(json.dumps(abort, separators=(",", ":")))
            time.sleep(60)
        emit({
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": message},
        })
        emit({"type": "agent_settled"})
    elif request_type == "compact":
        emit({"type": "compaction_start"})
        emit({"type": "compaction_end"})
        emit({
            "type": "response",
            "id": request["id"],
            "command": "compact",
            "success": True,
        })
    elif request_type == "abort":
        break
    else:
        raise AssertionError(request_type)
"""


@dataclass
class MutableSignal:
    cancelled: bool = False


class NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


class CallbackFailure(BaseException):
    pass


class PiRpcReusableTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_temporary)
        self.work = Path(self.temporary.name).resolve()
        self.fake_rpc = self.work / "fake_reusable_pi.py"
        self.fake_rpc.write_text(_FAKE_REUSABLE_PI, encoding="utf-8")
        self.abort_marker = self.work / "abort.json"
        self.events = []

    async def _cleanup_temporary(self) -> None:
        self.temporary.cleanup()

    def make_session(self, *, deadline_seconds: float = 2.0) -> PiRpcSession:
        return PiRpcSession(
            PiRpcConfig(
                (sys.executable, "-u", str(self.fake_rpc), str(self.abort_marker)),
                self.work,
                {},
                deadline_seconds=deadline_seconds,
            )
        )

    async def test_prompt_compact_prompt_reuses_one_process(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        assert rpc.process is not None
        pid = rpc.process.pid

        first = await rpc.prompt(
            "stage-one", signal=NeverCancelled(), on_event=self.events.append
        )
        compact = await rpc.compact(
            signal=NeverCancelled(), on_event=self.events.append
        )
        second = await rpc.prompt(
            "stage-two", signal=NeverCancelled(), on_event=self.events.append
        )

        assert rpc.process is not None
        self.assertEqual(rpc.process.pid, pid)
        self.assertEqual(
            [event.sequence for event in self.events],
            list(range(1, len(self.events) + 1)),
        )
        self.assertEqual(
            (first.request_id, compact.request_id, second.request_id),
            ("py-1", "py-2", "py-3"),
        )
        self.assertEqual(first.final_text, "stage-one")
        self.assertEqual(second.final_text, "stage-two")
        self.assertEqual(compact.rpc_type, "compact")
        self.assertEqual(
            [event.type for event in compact.events],
            ["compaction_start", "compaction_end", "response"],
        )

        await rpc.close()
        self.assertIsNone(rpc.process)

    async def test_session_deadline_is_absolute_and_prewrite_timeout_is_recoverable(
        self,
    ) -> None:
        rpc = self.make_session(deadline_seconds=1.0)
        now = [100.0]
        with patch(
            "asterion.runtimes.pi_rpc.time",
            SimpleNamespace(monotonic=lambda: now[0]),
        ):
            await rpc.open(signal=NeverCancelled())
            self.addAsyncCleanup(rpc.close)
            first = await rpc.prompt(
                "first", signal=NeverCancelled(), on_event=lambda _event: None
            )
            now[0] = 101.0
            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)
            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                await rpc.prompt(
                    "second", signal=NeverCancelled(), on_event=lambda _event: None
                )

        self.assertEqual(first.request_id, "py-1")

    async def test_inflight_prompt_does_not_rebase_the_session_deadline(self) -> None:
        rpc = self.make_session(deadline_seconds=1.0)
        now = [100.0]
        with patch(
            "asterion.runtimes.pi_rpc.time",
            SimpleNamespace(monotonic=lambda: now[0]),
        ):
            await rpc.open(signal=NeverCancelled())
            self.addAsyncCleanup(rpc.close)
            now[0] = 100.75

            def exhaust_deadline(event) -> None:
                if event.type == "agent_start":
                    now[0] = 101.0

            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                await rpc.prompt(
                    "late", signal=NeverCancelled(), on_event=exhaust_deadline
                )

        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_cancellation_after_dispatch_poisons_until_close(self) -> None:
        rpc = self.make_session()
        signal = MutableSignal()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def cancel_after_dispatch(event) -> None:
            if event.type == "agent_start":
                signal.cancelled = True

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await rpc.prompt("blocking", signal=signal, on_event=cancel_after_dispatch)
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.prompt(
                "never-sent", signal=NeverCancelled(), on_event=lambda _event: None
            )
        abort = json.loads(self.abort_marker.read_text(encoding="utf-8"))
        self.assertEqual(abort["type"], "abort")

        await rpc.close()
        self.assertIsNone(rpc.process)

    async def test_concurrent_command_is_rejected_without_dispatch(self) -> None:
        rpc = self.make_session()
        signal = MutableSignal()
        started = asyncio.Event()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        first = asyncio.create_task(
            rpc.prompt(
                "blocking",
                signal=signal,
                on_event=lambda event: (
                    started.set() if event.type == "agent_start" else None
                ),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        with self.assertRaisesRegex(RuntimeError, "active command"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)
        signal.cancelled = True
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await first

    async def test_response_identity_failure_poisons_session(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        with self.assertRaisesRegex(RuntimeError, "response did not match"):
            await rpc.prompt(
                "mismatch", signal=NeverCancelled(), on_event=lambda _event: None
            )
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_callback_base_exception_after_dispatch_poisons_session(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def fail_callback(_event) -> None:
            raise CallbackFailure("callback failed")

        with self.assertRaisesRegex(CallbackFailure, "callback failed"):
            await rpc.prompt(
                "callback", signal=NeverCancelled(), on_event=fail_callback
            )
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_close_is_idempotent_and_stops_once(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        with patch.object(rpc, "stop", wraps=rpc.stop) as stop:
            await rpc.close()
            await rpc.close()
        self.assertEqual(stop.call_count, 1)
        self.assertIsNone(rpc.process)

    async def test_legacy_run_remains_one_shot_and_hides_request_identity(self) -> None:
        rpc = self.make_session()
        result = await rpc.run(
            "legacy", signal=NeverCancelled(), on_event=self.events.append
        )

        self.assertIs(type(result), PiRpcResult)
        self.assertEqual(result.final_text, "legacy")
        self.assertIsNone(result.request_id)
        self.assertEqual([event.sequence for event in result.events], [1, 2, 3, 4])
        self.assertIsNone(rpc.process)


if __name__ == "__main__":
    unittest.main()
