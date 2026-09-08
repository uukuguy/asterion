from __future__ import annotations

import asyncio
import gc
import os
import tempfile
import unittest
import weakref
from collections.abc import Callable, Mapping
from pathlib import Path

from asterion.agents.prime.session import (
    ASTERION_PRIME_LIMITS,
    AsterionPrimeSession,
)
from asterion.agents.prime.tools import (
    PrimeToolCall,
    PrimeToolLedger,
    PrimeToolResult,
)
from asterion.runtime.host import RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream
from asterion.runtimes.pi_extensions import PiExtensionBinding, PiExtensionLease
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcEvent, PiRpcResult


class FakeSignal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class FakePiRpcSession:
    def __init__(
        self,
        config: PiRpcConfig,
        events: tuple[PiRpcEvent, ...],
        *,
        final_text: str = "",
        failure: BaseException | None = None,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.config = config
        self.events = events
        self.final_text = final_text
        self.failure = failure
        self.entered = entered
        self.release = release
        self.calls = 0

    async def run(
        self,
        prompt: str,
        *,
        signal: object,
        on_event: Callable[[PiRpcEvent], None],
    ) -> PiRpcResult:
        del prompt, signal
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        for event in self.events:
            on_event(event)
        if self.failure is not None:
            raise self.failure
        return PiRpcResult(self.final_text, self.events, b"")


class HostileMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("PRIVATE-MAPPING-VALUE")

    def __iter__(self):
        raise RuntimeError("PRIVATE-MAPPING-KEY")

    def __len__(self) -> int:
        return 1


def native_events(*values: tuple[str, Mapping[str, object]]) -> tuple[PiRpcEvent, ...]:
    return tuple(
        PiRpcEvent(sequence=index, type=event_type, payload=payload)
        for index, (event_type, payload) in enumerate(values, start=1)
    )


SUCCESS_EVENTS = native_events(
    ("response", {"id": "py-1", "success": True}),
    ("agent_start", {}),
    ("turn_start", {}),
    (
        "message_update",
        {"assistantMessageEvent": {"type": "text_delta", "delta": "solved"}},
    ),
    (
        "message_end",
        {
            "message": {
                "role": "assistant",
                "usage": {"input": 3, "output": 2},
            }
        },
    ),
    ("agent_settled", {}),
)


class SessionFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        extension = self.root / "prime_ipython.mjs"
        extension.write_text(
            "export default function extension() {}\n", encoding="utf-8"
        )
        self.binding = PiExtensionBinding(
            extension_id="prime.ipython",
            path=extension,
            capabilities=("prime.tool.ipython",),
            inherited_fds=(),
            environment={},
        )

    def make(
        self,
        events: tuple[PiRpcEvent, ...] = SUCCESS_EVENTS,
        *,
        final_text: str = "",
        failure: BaseException | None = None,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> tuple[AsterionPrimeSession, FakePiRpcSession, PiExtensionLease]:
        lease = self.binding.preflight()
        config = PiRpcConfig(
            command=("pi", "--mode", "rpc", *lease.command_args()),
            cwd=self.root,
            environment=dict(lease.environment),
            deadline_seconds=ASTERION_PRIME_LIMITS.deadline_ms / 1000,
            inherited_fds=lease.inherited_fds,
        )
        rpc = FakePiRpcSession(
            config,
            events,
            final_text=final_text,
            failure=failure,
            entered=entered,
            release=release,
        )
        session = AsterionPrimeSession(
            rpc_session=rpc,  # type: ignore[arg-type]
            extension_binding=self.binding,
            extension_lease=lease,
            limits=ASTERION_PRIME_LIMITS,
        )
        return session, rpc, lease

    def close(self) -> None:
        self.temporary.cleanup()


async def collect(
    session: AsterionPrimeSession,
    run_id: str = "prime-run-1",
    *,
    signal: FakeSignal | None = None,
    deadline_ms: int | None = None,
) -> list[RunEvent]:
    return [
        event
        async for event in session.run(
            RunRequest(
                run_id=run_id,
                input_text="solve level one",
                requested_capabilities=(
                    "prime.arc-agi-3-solving",
                    "prime.tool.ipython",
                ),
                deadline_ms=deadline_ms,
            ),
            signal=signal,
        )
    ]


class TestPrimeToolLedger(unittest.TestCase):
    def test_matches_each_call_and_result_once_and_snapshots_values(self) -> None:
        arguments = {"code": ["print(1)"]}
        content = ({"type": "text", "text": "ok"},)
        ledger = PrimeToolLedger(max_callbacks=2)

        ledger.record_call(PrimeToolCall("call-1", "ipython", arguments))
        ledger.record_result(PrimeToolResult("call-1", "ok", content))
        arguments["code"].append("changed")  # type: ignore[union-attr]
        content[0]["text"] = "changed"

        ledger.seal()
        self.assertEqual(ledger.callback_count, 1)
        with self.assertRaises(TypeError):
            ledger.calls[0].arguments["new"] = "value"  # type: ignore[index]
        self.assertEqual(ledger.calls[0].arguments["code"], ("print(1)",))
        self.assertEqual(ledger.results[0].content[0]["text"], "ok")

    def test_rejects_duplicate_unmatched_and_uncertain_results(self) -> None:
        ledger = PrimeToolLedger(max_callbacks=2)
        call = PrimeToolCall("call-1", "ipython", {"code": "1+1"})
        ledger.record_call(call)
        with self.assertRaisesRegex(ProtocolError, "duplicate tool call"):
            ledger.record_call(call)
        with self.assertRaisesRegex(ProtocolError, "tool result"):
            ledger.record_result(PrimeToolResult("other", "ok", ()))

        ledger.record_result(PrimeToolResult("call-1", "uncertain", ()))
        with self.assertRaisesRegex(ProtocolError, "uncertain tool effect"):
            ledger.seal()
        with self.assertRaisesRegex(ProtocolError, "duplicate tool result"):
            ledger.record_result(PrimeToolResult("call-1", "ok", ()))

    def test_malformed_private_values_are_normalized_without_exception_context(
        self,
    ) -> None:
        constructors = (
            lambda: PrimeToolCall("call-1", "ipython", HostileMapping()),
            lambda: PrimeToolResult("call-1", "ok", (HostileMapping(),)),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(ProtocolError) as caught:
                    constructor()
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertIsNone(caught.exception.__context__)


class TestAsterionPrimeSession(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = SessionFixture()
        self.addCleanup(self.fixture.close)

    def test_session_emits_one_valid_terminal_and_closes_lease(self) -> None:
        session, rpc, lease = self.fixture.make(final_text="solved")

        events = asyncio.run(collect(session))

        validate_event_stream([event.to_mapping() for event in events])
        self.assertEqual(
            [event.type for event in events],
            [
                "run.started",
                "usage.reported",
                "run.completed",
            ],
        )
        self.assertEqual(events[-1].payload, {"status": "completed"})
        self.assertNotIn("solved", repr(events))
        self.assertEqual(rpc.calls, 1)
        self.assertTrue(lease.closed)

    def test_abandoned_unstarted_session_closes_owned_lease(self) -> None:
        session, _rpc, lease = self.fixture.make()
        descriptor = lease.inherited_fds[0]
        reference = weakref.ref(session)

        del session
        gc.collect()

        self.assertIsNone(reference())
        self.assertTrue(lease.closed)
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_explicitly_closed_session_cannot_run(self) -> None:
        session, rpc, lease = self.fixture.make()
        session.close()

        with self.assertRaisesRegex(ProtocolError, "lease is unavailable"):
            asyncio.run(collect(session))

        self.assertEqual(rpc.calls, 0)
        self.assertTrue(lease.closed)

    def test_maps_only_exact_native_tool_events(self) -> None:
        events = native_events(
            ("response", {"id": "py-1", "success": True}),
            ("agent_start", {}),
            ("turn_start", {}),
            (
                "tool_execution_start",
                {
                    "toolCallId": "call-1",
                    "toolName": "ipython",
                    "args": {"code": "1+1"},
                },
            ),
            (
                "tool_execution_end",
                {
                    "toolCallId": "call-1",
                    "result": [{"type": "text", "text": "2"}],
                    "isError": False,
                },
            ),
            ("agent_settled", {}),
        )
        session, _rpc, _lease = self.fixture.make(events)

        public = asyncio.run(collect(session))

        validate_event_stream([event.to_mapping() for event in public])
        self.assertEqual(
            [event.type for event in public],
            ["run.started", "tool.call", "tool.result", "run.completed"],
        )
        self.assertEqual(public[1].payload["name"], "ipython")
        self.assertEqual(public[1].payload["arguments"], {})
        self.assertEqual(public[2].payload["is_error"], False)
        self.assertIsNone(public[2].payload["output"])
        self.assertNotIn("1+1", repr(public))
        self.assertNotIn('"2"', repr(public))

    def test_tool_call_result_ids_must_match(self) -> None:
        events = native_events(
            ("response", {"id": "py-1", "success": True}),
            (
                "tool_execution_end",
                {"toolCallId": "call-1", "result": [], "isError": False},
            ),
        )
        session, _rpc, lease = self.fixture.make(events)

        with self.assertRaisesRegex(ProtocolError, "tool result"):
            asyncio.run(collect(session))
        self.assertTrue(lease.closed)

    def test_unmatched_and_uncertain_effects_refuse_successful_seal(self) -> None:
        cases = {
            "unmatched": native_events(
                (
                    "tool_execution_start",
                    {
                        "toolCallId": "call-1",
                        "toolName": "ipython",
                        "args": {"code": "1+1"},
                    },
                ),
                ("agent_settled", {}),
            ),
            "uncertain": native_events(
                (
                    "tool_execution_start",
                    {
                        "toolCallId": "call-1",
                        "toolName": "ipython",
                        "args": {"code": "1+1"},
                    },
                ),
                (
                    "tool_execution_end",
                    {
                        "toolCallId": "call-1",
                        "result": [],
                        "isError": False,
                        "effect": "uncertain",
                    },
                ),
                ("agent_settled", {}),
            ),
        }
        for label, events in cases.items():
            with self.subTest(label=label):
                fixture = SessionFixture()
                try:
                    session, _rpc, _lease = fixture.make(events)
                    with self.assertRaisesRegex(
                        ProtocolError, "unmatched tool call|uncertain tool effect"
                    ):
                        asyncio.run(collect(session))
                finally:
                    fixture.close()

    def test_model_callback_cap_is_exactly_128(self) -> None:
        events = native_events(
            *(("turn_start", {}) for _ in range(129)),
            ("agent_settled", {}),
        )
        session, _rpc, _lease = self.fixture.make(events)

        with self.assertRaisesRegex(ProtocolError, "model callback limit"):
            asyncio.run(collect(session))

    def test_tool_callback_cap_is_fixed(self) -> None:
        values: list[tuple[str, Mapping[str, object]]] = []
        for index in range(ASTERION_PRIME_LIMITS.tool_callbacks + 1):
            values.append(
                (
                    "tool_execution_start",
                    {
                        "toolCallId": f"call-{index}",
                        "toolName": "ipython",
                        "args": {},
                    },
                )
            )
        session, _rpc, _lease = self.fixture.make(native_events(*values))

        with self.assertRaisesRegex(ProtocolError, "tool callback limit"):
            asyncio.run(collect(session))

    def test_cancelled_request_has_one_content_free_terminal(self) -> None:
        session, rpc, lease = self.fixture.make()

        events = asyncio.run(collect(session, signal=FakeSignal(True)))

        validate_event_stream([event.to_mapping() for event in events])
        self.assertEqual(
            [event.type for event in events], ["run.started", "run.completed"]
        )
        self.assertEqual(events[-1].payload, {"status": "cancelled"})
        self.assertEqual(rpc.calls, 0)
        self.assertTrue(lease.closed)

    def test_transport_deadline_is_a_generic_terminal_failure(self) -> None:
        session, _rpc, lease = self.fixture.make(
            (), failure=RuntimeError("PRIVATE DEADLINE PAYLOAD")
        )

        events = asyncio.run(collect(session))

        validate_event_stream([event.to_mapping() for event in events])
        self.assertEqual(
            [event.type for event in events], ["run.started", "run.failed"]
        )
        self.assertEqual(
            events[-1].payload,
            {
                "code": "asterion_prime_failed",
                "message": "Asterion-prime execution failed.",
            },
        )
        self.assertNotIn("PRIVATE", repr(events))
        self.assertTrue(lease.closed)

    def test_rejects_non_fixed_request_and_transport_deadlines(self) -> None:
        session, rpc, lease = self.fixture.make()
        with self.assertRaisesRegex(ProtocolError, "fixed deadline"):
            asyncio.run(collect(session, deadline_ms=1))
        self.assertEqual(rpc.calls, 0)
        self.assertTrue(lease.closed)

        fixture = SessionFixture()
        try:
            lease = fixture.binding.preflight()
            config = PiRpcConfig(
                command=("pi", *lease.command_args()),
                cwd=fixture.root,
                environment=dict(lease.environment),
                deadline_seconds=1,
                inherited_fds=lease.inherited_fds,
            )
            with self.assertRaisesRegex(ProtocolError, "launch material"):
                AsterionPrimeSession(
                    rpc_session=FakePiRpcSession(config, ()),  # type: ignore[arg-type]
                    extension_binding=fixture.binding,
                    extension_lease=lease,
                    limits=ASTERION_PRIME_LIMITS,
                )
            self.assertTrue(lease.closed)
        finally:
            fixture.close()

    def test_rejects_duplicate_native_terminal_and_malformed_private_payload(
        self,
    ) -> None:
        cases = {
            "duplicate terminal": native_events(
                ("agent_settled", {}), ("agent_settled", {})
            ),
            "malformed private": native_events(
                (
                    "tool_execution_start",
                    {"toolCallId": "PRIVATE-CALL-ID", "args": {"secret": "PRIVATE"}},
                )
            ),
        }
        for label, events in cases.items():
            with self.subTest(label=label):
                fixture = SessionFixture()
                try:
                    session, _rpc, _lease = fixture.make(events)
                    with self.assertRaises(ProtocolError) as caught:
                        asyncio.run(collect(session))
                    self.assertNotIn("PRIVATE", str(caught.exception))
                finally:
                    fixture.close()

    def test_rejects_one_active_request_and_reused_run_id(self) -> None:
        async def exercise_active() -> None:
            entered = asyncio.Event()
            release = asyncio.Event()
            session, _rpc, _lease = self.fixture.make(entered=entered, release=release)
            first = asyncio.create_task(collect(session, "prime-run-active"))
            await entered.wait()
            with self.assertRaisesRegex(ProtocolError, "active request"):
                await collect(session, "prime-run-other")
            release.set()
            await first

        asyncio.run(exercise_active())

        fixture = SessionFixture()
        try:
            session, _rpc, _lease = fixture.make()
            asyncio.run(collect(session, "prime-run-reused"))
            with self.assertRaisesRegex(ProtocolError, "run_id was already used"):
                asyncio.run(collect(session, "prime-run-reused"))
        finally:
            fixture.close()

    def test_binding_lease_and_rpc_launch_material_must_match(self) -> None:
        mismatches = (
            "binding",
            "command",
            "environment",
            "extra environment",
            "descriptors",
        )
        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch):
                fixture = SessionFixture()
                other = SessionFixture()
                try:
                    lease = fixture.binding.preflight()
                    binding = (
                        other.binding if mismatch == "binding" else fixture.binding
                    )
                    command = ("pi", *lease.command_args())
                    environment = dict(lease.environment)
                    descriptors = lease.inherited_fds
                    if mismatch == "command":
                        command = ("pi",)
                    elif mismatch == "environment":
                        environment.pop("ASTERION_PI_EXTENSION_SOURCE_SHA256")
                    elif mismatch == "extra environment":
                        environment["PRIVATE_PROVIDER_SECRET"] = "PRIVATE-VALUE"
                    elif mismatch == "descriptors":
                        descriptors = ()
                    config = PiRpcConfig(
                        command=command,
                        cwd=fixture.root,
                        environment=environment,
                        deadline_seconds=ASTERION_PRIME_LIMITS.deadline_ms / 1000,
                        inherited_fds=descriptors,
                    )
                    with self.assertRaisesRegex(ProtocolError, "launch material"):
                        AsterionPrimeSession(
                            rpc_session=FakePiRpcSession(config, ()),  # type: ignore[arg-type]
                            extension_binding=binding,
                            extension_lease=lease,
                            limits=ASTERION_PRIME_LIMITS,
                        )
                    self.assertTrue(lease.closed)
                finally:
                    fixture.close()
                    other.close()


if __name__ == "__main__":
    unittest.main()
