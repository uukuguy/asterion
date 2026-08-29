"""Tests for the host-owned Prime daemon restart boundary."""

from __future__ import annotations

import asyncio
import json
import secrets
import tempfile
import unittest
from pathlib import Path

from asterion.control.providers.prime.process import (
    PrimeDaemonLifecycle,
    PrimeDaemonLifecycleServer,
    PRIME_DAEMON_LIFECYCLE_PROTOCOL,
    PrimeSidecarProcessError,
)


class TestPrimeDaemonLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_restart_runs_stop_before_start_and_serializes_callers(self) -> None:
        events: list[str] = []
        released = asyncio.Event()

        async def stop(_: str) -> None:
            events.append("stop")

        async def start(_: str) -> None:
            events.append("start")
            if events.count("start") == 1:
                await released.wait()

        lifecycle = PrimeDaemonLifecycle(stop=stop, start=start, timeout=1)
        first = asyncio.create_task(lifecycle.restart("active-1"))
        await asyncio.sleep(0)
        second = asyncio.create_task(lifecycle.restart("active-1"))
        released.set()
        await asyncio.gather(first, second)
        self.assertEqual(events, ["stop", "start", "stop", "start"])

    async def test_restart_converts_host_failure_to_safe_error(self) -> None:
        async def stop(_: str) -> None:
            raise OSError("private failure")

        async def start(_: str) -> None:
            self.fail("start must not run")

        lifecycle = PrimeDaemonLifecycle(stop=stop, start=start, timeout=1)
        with self.assertRaises(PrimeSidecarProcessError):
            await lifecycle.restart("active-1")

    async def test_private_server_restarts_only_the_bound_session(self) -> None:
        calls: list[str] = []

        async def stop(_: str) -> None:
            calls.append("stop")

        async def start(_: str) -> None:
            calls.append("start")

        lifecycle = PrimeDaemonLifecycle(stop=stop, start=start, timeout=1)
        with tempfile.TemporaryDirectory() as temporary:
            socket_path = Path(temporary) / "lifecycle.sock"
            token = secrets.token_hex(32)
            server = PrimeDaemonLifecycleServer(
                lifecycle=lifecycle,
                socket_path=socket_path,
                token=token,
                session_id="session-1",
            )
            await server.start()
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write((json.dumps({
                "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                "id": "restart-1",
                "type": "restart",
                "token": token,
                "session_id": "session-1",
                "active_session_id": "active-1",
            }) + "\n").encode())
            await writer.drain()
            response = json.loads((await reader.readline()).decode())
            writer.close()
            await writer.wait_closed()
            # Admission is deliberately separate from completion: the request
            # connection belongs to the predecessor daemon and may disappear
            # while Prime performs its prepared shutdown.  Completion is
            # published in the request-id-bound private receipt.
            self.assertEqual(response, {
                "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                "id": "restart-1",
                "type": "accepted",
            })
            receipt = socket_path.parent / ".asterion-lifecycle-restart-1.json"
            for _ in range(20):
                if receipt.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), {
                "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                "id": "restart-1",
                "type": "restarted",
            })
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(calls, ["stop", "start"])
            await server.close()
            self.assertFalse(socket_path.exists())
