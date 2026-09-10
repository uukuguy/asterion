from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.backend import (
    PrimeBackendError,
    PrimePromptRequest,
    PrimeSessionBackend,
)
from asterion.agents.prime.execution import PrimeExecutionKernel
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.control.authority import RemainingBudget
from asterion.control.host import ControlCommand
from asterion.control.state import ControlState, reduce_control_event
from asterion.control.session_context import SessionContextCommand
from asterion.runtimes.pi_extensions import PiExtensionBinding
from asterion.runtimes.pi_rpc import (
    PiRpcCompactResult,
    PiRpcConfig,
    PiRpcEvent,
    PiRpcResult,
)
from tests.test_asterion_prime_context import LAUNCH, material, receive, send


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FakeReusablePi:
    def __init__(self, config: PiRpcConfig) -> None:
        self.config = config
        self.opens = self.closes = self.calls = self.sequence = 0
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.failure: Exception | None = None
        self.peer = None
        self.compacts = 0
        self.corrupt_compact = False
        self.acked = False
        self.acknowledged = asyncio.Event()
        self.compact_terminal_release = None
        self.lifecycle = object()
        self.dead = False
        self.pending_abort = None
        self.compact_persist_delay = 0
        self.compact_cancelled = False
        self.compact_native_overrides = {}

    def validate_lifecycle(self, *, opened):
        if self.dead or self.closes or bool(self.opens) != opened or self.pending_abort:
            raise ValueError("PRIVATE-LIFECYCLE")
        return self.lifecycle if opened else None

    def settle_rejected_compact(self, result):
        if result is not self.pending_abort:
            raise ValueError("PRIVATE-ABORT")
        self.pending_abort = None

    async def open(self, *, signal):
        self.opens += 1

    async def prompt(self, prompt, *, signal, on_event):
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure:
            raise self.failure
        events = []
        for kind, payload in (
            ("turn_start", {}),
            (
                "message_end",
                {"message": {"role": "assistant", "usage": {"input": 3, "output": 2}}},
            ),
            ("agent_end", {}),
        ):
            self.sequence += 1
            event = PiRpcEvent(self.sequence, kind, payload)
            events.append(event)
            on_event(event)
        return PiRpcResult("PRIVATE-ANSWER", tuple(events), b"")

    async def close(self):
        self.closes += 1

    async def compact(self, *, signal, on_event):
        self.compact_signal = signal
        self.compacts += 1
        arm = await receive(self.peer)
        proposal, persisted = material()
        for frame in (proposal, persisted):
            frame["command_nonce"] = arm["command_nonce"]
            frame["authority_sha256"] = arm["authority_sha256"]
        await send(self.peer, proposal)
        decision = await receive(self.peer)
        if decision["status"] == "approve":
            try:
                await asyncio.sleep(self.compact_persist_delay)
            except asyncio.CancelledError:
                self.compact_cancelled = True
                raise
            if self.corrupt_compact:
                persisted["summary_sha256"] = "0" * 64
            await send(self.peer, persisted)
            self.acked = (await receive(self.peer))["phase"] == "ack"
            self.acknowledged.set()
            if self.compact_terminal_release is not None:
                await self.compact_terminal_release.wait()
        body = {
            "summary": persisted["summary"],
            "firstKeptEntryId": persisted["first_kept_entry_id"],
            "tokensBefore": persisted["compaction_entry"]["tokensBefore"],
            "details": {},
            **self.compact_native_overrides,
        }
        approved = decision["status"] == "approve"
        end = {"reason": "manual", "aborted": not approved, "willRetry": False}
        response = {"id": "compact-rpc", "command": "compact", "success": approved}
        if approved:
            end["result"] = body
            response["data"] = body
        else:
            end["errorSeverity"] = "error"
            response["error"] = "PRIVATE-ARBITRARY-CANCEL"
        events = []
        for kind, payload in (
            ("compaction_start", {"reason": "manual"}),
            ("compaction_end", end),
            ("response", response),
        ):
            self.sequence += 1
            event = PiRpcEvent(self.sequence, kind, payload)
            events.append(event)
            on_event(event)
        result = PiRpcCompactResult(
            "compact-rpc",
            "compact",
            tuple(events),
            b"",
            "completed" if approved else "aborted",
        )
        if not approved:
            self.pending_abort = result
        return result


class FakeToolExecutor:
    identity_sha256 = "a" * 64

    def __init__(self):
        self.closed = False
        self.lifecycle = object()

    def validate_lifecycle(self):
        if self.closed:
            raise ValueError("PRIVATE-WORKER-CLOSED")
        return self.lifecycle

    async def close(self):
        self.closed = True


class TestPrimeBackend(unittest.IsolatedAsyncioTestCase):
    create_session = True

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        extension = self.root / "extension.mjs"
        extension.write_text("export default function extension() {}\n")
        binding = PiExtensionBinding(
            "prime.ipython", extension, ("prime.tool.ipython",), (), {}
        )
        self.lease = binding.preflight()
        limits = AsterionPrimeLimits(8, 4, 600000)
        config = PiRpcConfig(
            command=("pi", "--mode", "rpc", *self.lease.command_args()),
            cwd=self.root,
            environment=dict(self.lease.environment),
            inherited_fds=self.lease.inherited_fds,
            deadline_seconds=600,
        )
        self.rpc = FakeReusablePi(config)
        host, self.peer = socket.socketpair()
        self.peer.setblocking(False)
        self.rpc.peer = self.peer
        witness = PrimeContextWitnessSession(
            host, launch_nonce=LAUNCH, timeout_seconds=0.2, mark_uncertain=lambda: None
        )
        private = self.root / "private"
        private.mkdir(mode=0o700)
        self.identity = PrimeBackendIdentity(
            "session-1",
            1,
            "prime-applications",
            "example.coding",
            "1.0.0",
            "asterion.prime",
            digest(config.command),
            binding.binding_fingerprint,
            "a" * 64,
            "continuation-1",
            private_root_identity(private),
            digest(
                {**asdict(limits), "aggregate_tokens": 64000, "cost_micros": 500000}
            ),
        )
        self.store = FilePrimeSessionStore(private, self.identity)
        self.worker = FakeToolExecutor()
        self.backend = PrimeSessionBackend(
            identity=self.identity,
            store=self.store,
            rpc_session=self.rpc,
            extension_binding=binding,
            extension_lease=self.lease,
            approved_command=config.command,
            limits=limits,
            aggregate_tokens=64000,
            cost_micros=500000,
            model_price=ModelPrice(1000000, 1000000),
            witness=witness,
            tool_executor=self.worker,
            authority_id="authority-1",
        )
        self.backend.sync_authority_snapshot(
            RemainingBudget(64000, 64000, 0, 64000, 500000, 600000),
            authority_revision=1,
        )
        if self.create_session:
            await self.backend.accept_control(
                self.control(
                    "session.create",
                    "create-1",
                    {
                        "system_id": "example.coding",
                        "system_version": "1.0.0",
                        "goal_id": "goal-1",
                        "goal_ref": "goal-ref-1",
                    },
                )
            )

    async def asyncTearDown(self):
        await self.backend.close()
        self.peer.close()
        self.temp.cleanup()

    def request(self, command_id="prompt-1", text="PRIVATE-PROMPT"):
        return PrimePromptRequest(
            command_id, self.identity.session_id, self.identity.generation, text
        )

    async def test_persist_before_ack_duplicate_and_suffix(self):
        attachment = self.backend.attach(self.identity)
        receipt = await attachment.execute_prompt(self.request())
        self.assertTrue(self.store.has_record(receipt.record_id))
        self.assertEqual(await attachment.execute_prompt(self.request()), receipt)
        self.assertEqual(self.rpc.calls, 1)
        events = attachment.replay_events(0)
        self.assertEqual(
            tuple(e.cursor for e in events), tuple(range(1, len(events) + 1))
        )
        second = self.backend.attach(self.identity)
        self.assertEqual(second.replay_events(1), events[1:])
        await attachment.close()
        self.assertEqual(self.rpc.closes, 0)
        await second.execute_prompt(self.request("prompt-2"))
        self.assertEqual((self.rpc.opens, self.rpc.calls), (1, 2))
        self.assertEqual(self.backend.usage.aggregate_tokens, 10)
        self.assertIsInstance(self.backend.kernel, PrimeExecutionKernel)
        public = repr(
            (receipt, events, self.backend.snapshot(), attachment, self.backend)
        )
        for secret in ("PRIVATE-PROMPT", "PRIVATE-ANSWER", str(self.root)):
            self.assertNotIn(secret, public)

    async def test_divergent_duplicate_identity_generation_and_cursor_reject(self):
        await self.backend.execute_prompt(self.request())
        for request in (
            self.request(text="PRIVATE-DIVERGENT"),
            replace(self.request("prompt-2"), generation=2),
        ):
            with self.assertRaises(PrimeBackendError):
                await self.backend.execute_prompt(request)
        with self.assertRaises(PrimeBackendError):
            self.backend.attach(replace(self.identity, worker_identity_sha256="b" * 64))
        for cursor in (-1, True, self.backend.snapshot().cursor + 1):
            with self.subTest(cursor=cursor), self.assertRaises(PrimeBackendError):
                self.backend.replay_events(cursor)
        self.assertEqual(self.rpc.calls, 1)

    async def test_serialized_effects_and_detach_preserves_owner(self):
        self.rpc.release = asyncio.Event()
        first = asyncio.create_task(self.backend.execute_prompt(self.request()))
        await self.rpc.entered.wait()
        second = asyncio.create_task(
            self.backend.execute_prompt(self.request("prompt-2"))
        )
        await asyncio.sleep(0)
        self.assertEqual(self.rpc.calls, 1)
        self.assertEqual(self.backend.snapshot().phase, "effect-active")
        self.rpc.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.rpc.calls, 2)

    async def test_active_attachment_rejection_does_not_poison_live_effect(self):
        self.rpc.release = asyncio.Event()
        task = asyncio.create_task(self.backend.execute_prompt(self.request()))
        await self.rpc.entered.wait()
        before = self.store.position
        try:
            with self.assertRaises(PrimeBackendError):
                self.backend.attach(self.identity)
            self.assertEqual(self.backend.snapshot().phase, "effect-active")
            self.assertEqual(self.backend.snapshot().outstanding_effect, "prompt-1")
            self.assertEqual(self.store.position, before)
        finally:
            self.rpc.release.set()
            await task
        self.backend.attach(self.identity)

    async def test_uncertain_effect_fences_mutation(self):
        await self.backend.mark_uncertain("compact-1")
        with self.assertRaisesRegex(PrimeBackendError, "recovery required"):
            await self.backend.execute_prompt(self.request())
        self.assertEqual(self.rpc.calls, 0)
        self.assertEqual(self.backend.snapshot().outstanding_effect, "compact-1")
        self.assertEqual(
            self.backend.replay_events(0)[-1].type, "session.recovery-required"
        )

    async def test_failed_persistence_never_acknowledges_and_fences(self):
        original = self.store.append

        def fail_after_effect(record_id, kind, payload, *, expected_position):
            if kind == "prompt-completed":
                raise OSError("PRIVATE-PATH")
            return original(
                record_id, kind, payload, expected_position=expected_position
            )

        with patch.object(self.store, "append", fail_after_effect):
            with self.assertRaisesRegex(
                PrimeBackendError, "recovery required"
            ) as raised:
                await self.backend.execute_prompt(self.request())
        self.assertNotIn("PRIVATE-PATH", str(raised.exception))
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")
        self.assertEqual(
            self.store.recover_checkpoint().checkpoint.outstanding_effect, "prompt-1"
        )
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request())
        self.assertEqual(self.rpc.calls, 1)

    async def test_authority_snapshots_and_read_only_context(self):
        self.backend.sync_authority_snapshot(
            RemainingBudget(60000, 60000, 0, 60000, 400000, 500000),
            authority_revision=2,
        )
        self.assertEqual(self.backend.snapshot().authority_revision, 2)
        cmd = SessionContextCommand(
            "describe-1", "session-1", 1, 2, "describe-key", "session.describe", {}
        )
        receipt = await self.backend.execute_context(cmd)
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(receipt.reason_code, "context-count-unavailable")
        self.assertIsNone(receipt.payload["result"])
        self.assertEqual(self.rpc.calls, 0)
        with self.assertRaises(PrimeBackendError):
            self.backend.sync_authority_snapshot(
                RemainingBudget(1, 1, 0, 1, 1, 1), authority_revision=1
            )

    async def test_initial_write_failure_is_redacted_and_never_dispatches(self):
        with patch.object(
            self.store, "append", side_effect=OSError("PRIVATE-WRITE-ERROR")
        ):
            with self.assertRaises(PrimeBackendError) as raised:
                await self.backend.execute_prompt(self.request())
        self.assertNotIn("PRIVATE-WRITE-ERROR", str(raised.exception))
        self.assertEqual(self.rpc.calls, 0)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_attachment_generation_advances_without_changing_kernel(self):
        first = self.backend.attach(self.identity)
        await first.close()
        second = self.backend.attach(self.identity)
        self.assertEqual(second.generation, first.generation + 1)
        self.assertEqual(
            second.snapshot().identity.generation, self.identity.generation
        )

    async def test_worker_identity_drift_rejects_before_prompt(self):
        self.worker.identity_sha256 = "b" * 64
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request())
        self.assertEqual(self.rpc.calls, 0)

    async def test_missing_price_or_worker_rejects_before_dispatch(self):
        for attribute in ("_price", "_tool_executor"):
            with self.subTest(attribute=attribute):
                original = getattr(self.backend, attribute)
                setattr(self.backend, attribute, None)
                try:
                    with self.assertRaises(PrimeBackendError):
                        await self.backend.execute_prompt(self.request())
                finally:
                    setattr(self.backend, attribute, original)
        self.assertEqual(self.rpc.calls, 0)

    def test_invalid_private_prompt_is_redacted(self):
        for text in ("\ud800PRIVATE", "x" * (65536 + 1)):
            with self.subTest(size=len(text)), self.assertRaises(PrimeBackendError):
                self.request(text=text)

    async def test_unowned_durable_suffix_rejects_before_attachment_or_effect(self):
        await self.backend.execute_prompt(self.request())
        self.store.append(
            "rogue-record",
            "effect-started",
            {"command_id": "unowned"},
            expected_position=self.store.position,
        )
        with self.assertRaises(PrimeBackendError):
            self.backend.attach(self.identity)
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request("prompt-2"))
        self.assertEqual(self.rpc.calls, 1)

    def control(self, kind, command_id="control-1", payload=None):
        return ControlCommand(
            command_id,
            "session-1",
            1,
            kind,
            {"reason_code": "operator-request"} if payload is None else payload,
        )

    async def test_control_lifecycle_checkpoint_and_fence(self):
        create = self.control(
            "session.create",
            "create-1",
            {
                "system_id": "example.coding",
                "system_version": "1.0.0",
                "goal_id": "goal-1",
                "goal_ref": "goal-ref-1",
            },
        )
        await self.backend.accept_control(create)
        await self.backend.accept_control(create)
        self.assertEqual(len(self.backend.replay_events(0)), 2)
        await self.backend.accept_control(self.control("session.pause", "pause-1"))
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request())
        await self.backend.accept_control(self.control("session.resume", "resume-1"))
        await self.backend.execute_prompt(self.request())
        await self.backend.accept_control(
            self.control(
                "checkpoint.request", "checkpoint-1", {"checkpoint_id": "requested-1"}
            )
        )
        self.assertEqual(self.backend.replay_events(0)[-1].type, "checkpoint.created")
        await self.backend.mark_uncertain("unknown-1")
        with self.assertRaises(PrimeBackendError):
            await self.backend.accept_control(self.control("session.pause", "pause-2"))
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_divergent_cancel_cannot_mutate_before_digest_validation(self):
        await self.backend.accept_control(self.control("session.detach", "control-1"))
        with self.assertRaises(PrimeBackendError):
            await self.backend.accept_control(
                self.control("session.cancel", "control-1")
            )
        receipt = await self.backend.execute_prompt(self.request())
        self.assertEqual(receipt.status, "completed")

    async def test_control_create_requires_exact_application(self):
        command = self.control(
            "session.create",
            "create-1",
            {
                "system_id": "different.application",
                "system_version": "1.0.0",
                "goal_id": "goal-1",
                "goal_ref": "goal-ref-1",
            },
        )
        with self.assertRaises(PrimeBackendError):
            await self.backend.accept_control(command)
        self.assertEqual(len(self.backend.replay_events(0)), 2)

    async def test_all_lifecycle_events_pass_real_reducer(self):
        await self.backend.accept_control(self.control("session.pause", "pause-1"))
        await self.backend.accept_control(self.control("session.pause", "pause-2"))
        await self.backend.accept_control(self.control("session.resume", "resume-1"))
        await self.backend.accept_control(self.control("session.resume", "resume-2"))
        await self.backend.execute_prompt(self.request())
        await self.backend.accept_control(self.control("session.pause", "pause-3"))
        state = ControlState.empty("session-1", generation=1)
        for item in self.backend.replay_events():
            state = reduce_control_event(state, item.event)
        self.assertEqual(state.session_status, "paused")

    async def test_prompt_budget_dimensions_reject_before_dispatch(self):
        for index, budget in enumerate(
            (
                RemainingBudget(10, 0, 0, 10, 10, 1000),
                RemainingBudget(10, 10, 0, 0, 10, 1000),
                RemainingBudget(10, 10, 0, 10, 0, 1000),
            )
        ):
            with self.subTest(budget=budget):
                self.backend.sync_authority_snapshot(budget, authority_revision=1)
                before = self.store.position
                with self.assertRaises(PrimeBackendError):
                    await self.backend.execute_prompt(self.request(f"prompt-{index}"))
                self.assertEqual(self.store.position, before)
        self.assertEqual(self.rpc.calls, 0)

    async def test_synced_deadline_caps_active_prompt(self):
        self.backend.sync_authority_snapshot(
            RemainingBudget(10, 10, 0, 10, 10, 20), authority_revision=1
        )
        self.rpc.release = asyncio.Event()
        with self.assertRaises(PrimeBackendError):
            await asyncio.wait_for(self.backend.execute_prompt(self.request()), 0.2)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_resume_recovery_exception_is_fixed_and_fenced(self):
        await self.backend.execute_prompt(self.request())
        command = SessionContextCommand(
            "resume-check",
            "session-1",
            1,
            1,
            "resume-check",
            "session.continuation.resume",
            {"continuation_id": "continuation-1"},
        )
        with patch.object(
            self.store,
            "recover_checkpoint",
            side_effect=OSError("PRIVATE-RECOVERY-PATH"),
        ):
            with self.assertRaises(PrimeBackendError) as raised:
                await self.backend.execute_context(command)
        self.assertEqual(str(raised.exception), "Prime backend recovery required")
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_attach_checks_live_lease_worker_and_pi(self):
        await self.backend.execute_prompt(self.request())
        self.rpc.dead = True
        with self.assertRaises(PrimeBackendError):
            self.backend.attach(self.identity)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_closed_worker_rejects_clean_attachment(self):
        await self.worker.close()
        with self.assertRaises(PrimeBackendError):
            self.backend.attach(self.identity)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_replaced_worker_lifecycle_rejects_resume(self):
        await self.backend.execute_prompt(self.request())
        self.worker.lifecycle = object()
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_context(
                SessionContextCommand(
                    "resume-check",
                    "session-1",
                    1,
                    1,
                    "resume-check",
                    "session.continuation.resume",
                    {"continuation_id": "continuation-1"},
                )
            )
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_closed_lease_rejects_resume(self):
        await self.backend.execute_prompt(self.request())
        self.lease.close()
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_context(
                SessionContextCommand(
                    "resume-check",
                    "session-1",
                    1,
                    1,
                    "resume-check",
                    "session.continuation.resume",
                    {"continuation_id": "continuation-1"},
                )
            )
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_describe_only_reports_current_witnessed_projection(self):
        await self.backend.execute_prompt(self.request())
        compact = await self.backend.execute_context(self.compact_command())
        describe = SessionContextCommand(
            "describe-witness",
            "session-1",
            1,
            1,
            "describe-witness",
            "session.describe",
            {},
        )
        receipt = await self.backend.execute_context(describe)
        self.assertEqual(
            receipt.payload["result"]["context_tokens"],
            compact.payload["result"]["after_context_tokens"],
        )
        await self.backend.execute_prompt(self.request("prompt-2"))
        receipt = await self.backend.execute_context(
            replace(
                describe, command_id="describe-next", idempotency_key="describe-next"
            )
        )
        self.assertEqual(receipt.reason_code, "context-count-unavailable")
        self.assertIsNone(receipt.payload["result"])

    async def test_admitted_compact_can_consume_reserved_last_tokens(self):
        await self.backend.execute_prompt(self.request())
        self.backend.sync_authority_snapshot(
            RemainingBudget(0, 0, 0, 0, 0, 500000), authority_revision=1
        )
        receipt = await self.backend.execute_context(self.compact_command())
        self.assertEqual(receipt.status, "succeeded")

    async def test_cancellation_fences_and_cleanup_is_idempotent(self):
        self.rpc.release = asyncio.Event()
        task = asyncio.create_task(self.backend.execute_prompt(self.request()))
        await self.rpc.entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")
        cleanup = await self.backend.close()
        self.assertEqual(await self.backend.close(), cleanup)
        self.assertTrue(cleanup.complete)
        self.assertEqual(self.rpc.closes, 1)
        self.assertTrue(self.lease.closed)

    def compact_command(self, command_id="compact-1", tokens=16000):
        return SessionContextCommand(
            command_id,
            "session-1",
            1,
            1,
            command_id,
            "session.compact",
            {
                "continuation_id": "continuation-1",
                "instructions_ref": None,
                "budget": {
                    "controller_tokens": tokens,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": tokens,
                    "cost_micros": 125000,
                    "deadline_ms": 600000,
                },
            },
        )

    async def test_real_witness_compact_persists_then_resume_never_replays(self):
        await self.backend.execute_prompt(self.request())
        command = self.compact_command()
        compact = await self.backend.execute_context(command)
        self.assertEqual(compact.status, "succeeded")
        result = compact.payload["result"]
        self.assertLess(result["after_context_tokens"], result["before_context_tokens"])
        self.assertTrue(self.rpc.acked)
        self.assertEqual(result["usage"]["aggregate_tokens"], 16000)
        self.assertEqual(self.backend.usage.aggregate_tokens, 16005)
        attached = self.backend.attach(self.identity)
        resumed = await attached.execute_context(
            SessionContextCommand(
                "resume-1",
                "session-1",
                1,
                1,
                "resume-key",
                "session.continuation.resume",
                {"continuation_id": "continuation-1"},
            )
        )
        self.assertEqual(resumed.status, "succeeded")
        self.assertEqual(await attached.execute_context(command), compact)
        await attached.execute_prompt(self.request("prompt-2"))
        self.assertEqual((self.rpc.opens, self.rpc.calls, self.rpc.compacts), (1, 2, 1))
        recovered = self.store.recover_checkpoint()
        self.assertEqual(recovered.summary, b"checkpoint")

    async def test_checkpoint_keeps_effect_pending_until_native_terminal(self):
        await self.backend.execute_prompt(self.request())
        self.rpc.compact_terminal_release = asyncio.Event()
        task = asyncio.create_task(self.backend.execute_context(self.compact_command()))
        try:
            await self.rpc.acknowledged.wait()
            self.assertEqual(
                self.store.recover_checkpoint().checkpoint.outstanding_effect,
                "compact-1",
            )
        finally:
            self.rpc.compact_terminal_release.set()
            await task
        self.assertIsNone(self.store.recover_checkpoint().checkpoint.outstanding_effect)

    async def test_compact_deadline_covers_delayed_persisted_witness(self):
        await self.backend.execute_prompt(self.request())
        before = self.store.recover_checkpoint().checkpoint
        self.rpc.compact_persist_delay = 0.065
        command = self.compact_command()
        command = replace(
            command,
            payload={
                **command.payload,
                "budget": {**command.payload["budget"], "deadline_ms": 20},
            },
        )
        receipt = await self.backend.execute_context(command)
        self.assertEqual(receipt.status, "uncertain")
        self.assertTrue(self.rpc.compact_cancelled)
        self.assertTrue(self.rpc.compact_signal.cancelled)
        self.assertFalse(self.rpc.acked)
        self.assertEqual(self.backend.snapshot().outstanding_effect, command.command_id)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")
        self.assertEqual(self.store.recover_checkpoint().checkpoint, before)

    async def assert_native_witness_mismatch(self, key, value):
        await self.backend.execute_prompt(self.request())
        self.rpc.compact_native_overrides = {key: value}
        receipt = await self.backend.execute_context(self.compact_command())
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")
        self.assertEqual(
            self.store.recover_checkpoint().checkpoint.outstanding_effect, "compact-1"
        )
        self.assertNotIn(
            "CROSSED-SUMMARY", repr((receipt, self.backend.replay_events()))
        )
        self.assertNotIn("crossed-entry", repr((receipt, self.backend.replay_events())))

    async def test_compact_native_summary_must_match_witness(self):
        await self.assert_native_witness_mismatch("summary", "CROSSED-SUMMARY")

    async def test_compact_native_first_kept_entry_must_match_witness(self):
        await self.assert_native_witness_mismatch("firstKeptEntryId", "crossed-entry")

    async def test_compact_native_private_tokens_before_must_match_witness(self):
        await self.assert_native_witness_mismatch("tokensBefore", 999)

    async def test_rejected_compact_preserves_checkpoint_and_uncertain_fences(self):
        await self.backend.execute_prompt(self.request())
        before = self.store.recover_checkpoint().checkpoint
        rejected = await self.backend.execute_context(self.compact_command(tokens=1))
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(self.store.recover_checkpoint().checkpoint, before)
        self.assertIsNone(self.backend.snapshot().outstanding_effect)
        self.rpc.corrupt_compact = True
        uncertain = await self.backend.execute_context(
            self.compact_command("compact-2")
        )
        self.assertEqual(uncertain.status, "uncertain")
        self.assertFalse(self.rpc.acked)
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request("prompt-2"))


class TestPrimeBackendBeforeCreate(unittest.IsolatedAsyncioTestCase):
    create_session = False
    asyncSetUp = TestPrimeBackend.asyncSetUp
    asyncTearDown = TestPrimeBackend.asyncTearDown
    control = TestPrimeBackend.control
    request = TestPrimeBackend.request
    compact_command = TestPrimeBackend.compact_command

    async def test_effects_require_explicit_create_without_mutation(self):
        before = self.store.position
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request())
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_context(self.compact_command())
        self.assertEqual(self.store.position, before)
        self.assertEqual((self.rpc.opens, self.rpc.calls, self.rpc.compacts), (0, 0, 0))
        self.assertEqual(self.backend.replay_events(), ())


if __name__ == "__main__":
    unittest.main()
