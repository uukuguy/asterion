from __future__ import annotations

import unittest
from unittest.mock import patch

from asterion.agents.prime.session import AsterionPrimeSession
from asterion.runtime.host import RunEvent
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient
from asterion.services.diagnostics import FailureDiagnostic


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
            ("prime.tool.ipython",),
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

    def test_accepts_narrow_private_run_protocol(self) -> None:
        session = FakeSession()
        diagnostic = FailureDiagnostic(
            "pi-diagnostic-1",
            "pi.prompt",
            "ProtocolError",
            "0" * 64,
            None,
            "pi-provider-execution",
        )
        session.last_diagnostic_id = diagnostic.diagnostic_id
        session.last_diagnostic = diagnostic
        client = AsterionPrimeRuntimeClient(session)
        self.assertEqual(client.manifest.runtime_id, "asterion.prime")
        self.assertEqual(client.last_diagnostic_id, diagnostic.diagnostic_id)
        self.assertIs(client.last_diagnostic, diagnostic)

    def test_rejects_absent_or_noncallable_run(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "session is invalid"):
            AsterionPrimeRuntimeClient(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()


class TestNumericTripMetadata(unittest.IsolatedAsyncioTestCase):
    async def test_callbacks_preserve_protocol_rejection_with_exact_metadata(self):
        from tests.test_asterion_prime_session import SessionFixture, collect, native_events
        from asterion.services.diagnostics import limit_diagnostic
        fixture = SessionFixture()
        try:
            for kind, events, observed, maximum in (
                ('prime-model-callback-limit', native_events(*(('turn_start', {}) for _ in range(129))), 129, 128),
                ('prime-tool-callback-limit', native_events(*(('tool_execution_start',
                    {'toolCallId': f'call-{index}', 'toolName': 'ipython', 'args': {}})
                    for index in range(501))), 501, 500),
            ):
                with self.subTest(kind=kind):
                    session, _, _ = fixture.make(events)
                    with self.assertRaises(ProtocolError) as caught:
                        await collect(session)
                    diagnostic = limit_diagnostic(caught.exception)
                    self.assertIsNotNone(diagnostic)
                    self.assertEqual((diagnostic.limit_code, diagnostic.observed, diagnostic.limit),
                                     (kind, observed, maximum))
        finally:
            fixture.close()

    def test_tool_ledger_preserves_existing_rejection(self):
        from asterion.agents.prime.tools import PrimeToolCall, PrimeToolLedger
        from asterion.services.diagnostics import limit_diagnostic
        ledger = PrimeToolLedger(max_callbacks=1)
        ledger.record_call(PrimeToolCall('first', 'ipython', {}))
        with self.assertRaisesRegex(ProtocolError, 'tool callback limit') as caught:
            ledger.record_call(PrimeToolCall('second', 'ipython', {}))
        diagnostic = limit_diagnostic(caught.exception)
        self.assertEqual((diagnostic.observed, diagnostic.limit), (2, 1))

    async def test_admission_deadline_records_elapsed_without_changing_terminal(self):
        import asyncio
        from tests.test_asterion_prime_session import SessionFixture
        from asterion.services.diagnostics import MemoryDiagnosticSink
        fixture = SessionFixture()
        sink = MemoryDiagnosticSink()
        async def admission(*_args):
            await asyncio.sleep(10)
            return True
        try:
            session, rpc, _ = fixture.make(round_admission=admission)
            session._kernel._diagnostics = sink
            request = RunRequest('deadline-op', 'PRIVATE-PROMPT', deadline_ms=1)
            events = []
            await session._kernel.invoke(request, None, lambda kind, payload: events.append((kind, payload)))
            self.assertEqual(events[-1][0], 'run.failed')
            self.assertEqual(rpc.calls, 0)
            record = next(iter(sink._records.values()))
            diagnostic = record.limit_diagnostic
            self.assertEqual((diagnostic.limit_code, diagnostic.limit, diagnostic.unit),
                             ('prime-deadline', 1, 'milliseconds'))
            self.assertGreaterEqual(diagnostic.observed, diagnostic.limit)
        finally:
            fixture.close()

    async def test_exhausted_settled_callback_bound_keeps_goal_terminal(self):
        from dataclasses import replace
        from tests.test_asterion_prime_session import SessionFixture, native_events
        from asterion.services.diagnostics import MemoryDiagnosticSink
        fixture = SessionFixture()
        try:
            session, rpc, _ = fixture.make(native_events(('turn_start', {}), ('agent_end', {})),
                                            completion_predicate=lambda: False)
            kernel = session._kernel
            kernel._limits = replace(kernel._limits, model_callbacks=1)
            sink = MemoryDiagnosticSink()
            kernel._diagnostics = sink
            events = []
            await kernel.invoke(RunRequest('callback-op', 'PRIVATE-PROMPT'), None,
                                lambda kind, payload: events.append((kind, payload)))
            self.assertEqual(events[-1][1]['code'], 'asterion_prime_goal_not_reached')
            self.assertEqual(rpc.calls, 1)
            diagnostic = next(iter(sink._records.values())).limit_diagnostic
            self.assertEqual((diagnostic.limit_code, diagnostic.observed, diagnostic.limit,
                              diagnostic.action), ('prime-model-callback-limit', 1, 1, 'stopped'))
        finally:
            fixture.close()
