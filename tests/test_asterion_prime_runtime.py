from __future__ import annotations

import unittest
from unittest.mock import patch

from asterion.agents.prime.session import AsterionPrimeSession
from asterion.runtime.host import RunEvent
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[RunRequest, object]] = []

    async def run(self, request: RunRequest, *, signal: object = None):
        self.calls.append((request, signal))
        if False:
            yield None


class FakeSignal:
    cancelled = False


class TestAsterionPrimeRuntimeClient(unittest.IsolatedAsyncioTestCase):
    def test_manifest_has_exact_identity_and_sorted_capabilities(self) -> None:
        session = object.__new__(AsterionPrimeSession)
        client = AsterionPrimeRuntimeClient(session)

        self.assertEqual(client.manifest.runtime_id, "asterion.prime")
        self.assertEqual(
            client.manifest.capabilities,
            ("prime.arc-agi-3-solving", "prime.tool.ipython"),
        )

    async def test_run_delegates_the_immutable_request_and_signal(self) -> None:
        calls: list[tuple[RunRequest, object]] = []

        async def fake_run(
            _session: AsterionPrimeSession,
            request: RunRequest,
            *,
            signal: object = None,
        ):
            calls.append((request, signal))
            if False:
                yield RunEvent("unused", 1, "run.started", {"capabilities": []})

        session = object.__new__(AsterionPrimeSession)
        client = AsterionPrimeRuntimeClient(session)
        request = RunRequest(run_id="run-1", input_text="solve")
        signal = FakeSignal()

        with patch.object(AsterionPrimeSession, "run", fake_run):
            events = [event async for event in client.run(request, signal=signal)]

        self.assertEqual(events, [])
        self.assertEqual(calls, [(request, signal)])

    def test_rejects_unvalidated_session_lookalike(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "session is invalid"):
            AsterionPrimeRuntimeClient(FakeSession())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
