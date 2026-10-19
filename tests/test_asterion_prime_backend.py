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
    _PRIME_PROMPT_BYTES,
    PrimeBackendError,
    PrimePromptRequest,
    PrimeSessionBackend,
)
from asterion.agents.prime.execution import PrimeExecutionKernel
from asterion.agents.prime.compaction_budget import (
    CompactionReservationQuote, ModelPrice, PrimeCompactionPolicy,
)
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.control.authority import (
    BudgetRequest, RemainingBudget, SessionContextDecision, session_context_command_digest,
)
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
from asterion.services.diagnostics import LimitDiagnostic, MemoryDiagnosticSink
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
        self.compact_instructions = None
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
        self.compact_decisions = []
        self.compact_limit = None
        self.compact_abort_unknown = False
        self.compact_proposal_overrides = {}
        self.compact_summary_override = None

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

    async def compact(self, *, signal, on_event, custom_instructions=None):
        self.compact_signal = signal
        self.compact_instructions = custom_instructions
        self.compacts += 1
        arm = await receive(self.peer)
        from asterion.agents.prime.code_summary import is_dedicated_code_summary

        if is_dedicated_code_summary(custom_instructions):
            proposal, persisted = material(
                custom_instructions=custom_instructions,
                summary_text=self.compact_summary_override or custom_instructions,
                from_hook=True,
            )
        else:
            proposal, persisted = material()
        for frame in (proposal, persisted):
            frame["command_nonce"] = arm["command_nonce"]
            frame["authority_sha256"] = arm["authority_sha256"]
        proposal.update(self.compact_proposal_overrides)
        if self.compact_limit is not None:
            await send(self.peer, {key: proposal[key] for key in
                ("protocol", "launch_nonce", "command_nonce", "authority_sha256")} |
                {"phase": "limit", "limit_diagnostic": asdict(self.compact_limit)})
            decision = {"status": "reject"}
        else:
            await send(self.peer, proposal)
            decision = await receive(self.peer)
        self.compact_decisions.append(decision["status"])
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
        # `_compact_rpc_event` redacts a response to its identity and outcome
        # (`compact_events` is transport event redaction), so these are the only
        # response fields the stream carries.
        response = {"id": "compact-rpc", "success": approved}
        if approved:
            end["result"] = body
        else:
            end["errorSeverity"] = "error"
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
            "completed" if approved or self.compact_abort_unknown else "aborted",
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
                {**asdict(limits), "aggregate_tokens": 64000, "cost_micros": 500000,
                 "compaction_policy": asdict(PrimeCompactionPolicy()),
                 "compaction_policy_source": "framework-default"}
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
            compaction_instructions={"note-1": "KERNEL-NOTE-TEXT"},
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

    async def test_changed_policy_or_source_rejects_existing_backend_identity(self):
        for changes in ({'compaction_policy': PrimeCompactionPolicy(max_total_tokens=48000)},
                {'compaction_policy_source': 'application'}):
            with self.subTest(changes=changes):
                backend = self.backend
                with self.assertRaises(PrimeBackendError):
                    PrimeSessionBackend(identity=self.identity, store=self.store,
                        rpc_session=self.rpc, extension_binding=backend._binding,
                        extension_lease=self.lease, approved_command=backend._approved_command,
                        limits=backend._limits, aggregate_tokens=64000, cost_micros=500000,
                        **changes)
                self.assertEqual(self.rpc.opens, 0)

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

    async def test_prompt_failure_records_private_diagnostic_and_safe_id(self):
        sink = MemoryDiagnosticSink()
        self.backend._diagnostics = sink
        self.rpc.failure = RuntimeError("PRIVATE-PROMPT-PAYLOAD")
        with self.assertRaises(PrimeBackendError) as caught:
            await self.backend.execute_prompt(self.request())
        self.assertEqual(str(caught.exception), "Prime backend recovery required")
        diagnostic_id = caught.exception.diagnostic_id
        self.assertIsNotNone(diagnostic_id)
        record = sink.get(diagnostic_id)
        self.assertEqual(record.stage, "prime.prompt")
        self.assertEqual(record.exception_type, "PrimeBackendError")
        self.assertNotIn("PRIVATE-PROMPT-PAYLOAD", repr(record))

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
        self.request(text="x" * 200_000)
        for text in ("\ud800PRIVATE", "x" * (_PRIME_PROMPT_BYTES + 1)):
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
        from asterion.agents.prime import backend as backend_module

        self.assertTrue(
            hasattr(backend_module, "PrimeBackendBudgetError"),
            "typed pre-dispatch budget rejection is missing",
        )
        error_type = backend_module.PrimeBackendBudgetError
        for index, budget in enumerate(
            (
                RemainingBudget(10, 0, 0, 10, 10, 1000),
                RemainingBudget(10, 10, 0, 0, 10, 1000),
                RemainingBudget(10, 10, 0, 10, 0, 1000),
                RemainingBudget(10, 10, 0, 10, 10, 0),
            )
        ):
            with self.subTest(budget=budget):
                self.backend.sync_authority_snapshot(budget, authority_revision=1)
                before = self.store.position
                with self.assertRaises(error_type):
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
        command = self.compact_command()
        self.backend.sync_authority_snapshot(
            RemainingBudget(0, 0, 0, 0, 0, 500000), authority_revision=1,
            admitted_context=self.admission(command),
        )
        self.assertEqual(self.backend._budget.aggregate_tokens, 0)
        with self.assertRaises(PrimeBackendError):
            await self.backend.execute_prompt(self.request("prompt-blocked"))
        receipt = await self.backend.execute_context(command)
        self.assertEqual(receipt.status, "succeeded")
        self.assertIsNone(self.backend._context_admission)
        self.assertIs(await self.backend.execute_context(command), receipt)

    def admission(self, command):
        return SessionContextDecision(command.command_id, command.idempotency_key,
            "authority-1", command.authority_revision, command.operation,
            session_context_command_digest(command), "admitted", "admitted",
            BudgetRequest.from_mapping(command.payload["budget"]))

    async def test_compact_grant_is_exact_consumed_once_and_cleared_by_plain_sync(self):
        await self.backend.execute_prompt(self.request())
        command = self.compact_command()
        empty = RemainingBudget(0, 0, 0, 0, 0, 500000)
        decision = self.admission(command)
        for changes in ({"command_id": "other-command"}, {"command_digest": "0" * 64},
                        {"idempotency_key": "other-key"},
                        {"reservation": replace(decision.reservation, aggregate_tokens=16001)}):
            with self.subTest(changes=changes):
                self.backend.sync_authority_snapshot(empty, admitted_context=replace(decision, **changes))
                with self.assertRaises(PrimeBackendError):
                    await self.backend.execute_context(command)
                self.assertIsNone(self.backend._context_admission)
                self.assertEqual(self.rpc.compacts, 0)
        for changes in ({"authority_revision": 2}, {"authority_id": "authority-other"},
                        {"status": "rejected", "reservation": None}):
            with self.subTest(changes=changes), self.assertRaises(PrimeBackendError):
                self.backend.sync_authority_snapshot(empty, admitted_context=replace(decision, **changes))
        self.backend.sync_authority_snapshot(empty, admitted_context=decision)
        self.backend.sync_authority_snapshot(empty)
        self.assertIsNone(self.backend._context_admission)
        rejected = await self.backend.execute_context(command)
        self.assertEqual((rejected.status, rejected.reason_code), ("rejected", "prime-parent-token-limit"))

    async def test_compact_resolves_the_instruction_reference_for_the_rpc(self):
        await self.backend.execute_prompt(self.request())
        callbacks = self.backend._kernel.model_callbacks
        receipt = await self.backend.execute_context(
            self.compact_command(instructions_ref="note-1")
        )
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(self.backend._kernel.model_callbacks, callbacks + 2)
        self.assertEqual(self.rpc.compact_instructions, "KERNEL-NOTE-TEXT")
        # The reference is what the canonical command carries; the text is not.
        self.assertNotIn("KERNEL-NOTE-TEXT", json.dumps(receipt.to_mapping()))

    async def test_code_aware_instruction_is_the_persisted_summary(self):
        from asterion.agents.prime.code_summary import (
            KernelBinding,
            build_code_aware_summary,
            is_native_generic_summary,
        )

        summary = build_code_aware_summary(
            (
                KernelBinding("AffineAccumulator", "class"),
                KernelBinding("accumulator", "callable"),
            ),
            keep_recent_tokens=256,
        )
        await self.backend.execute_prompt(self.request())
        self.backend.bind_compaction_instruction("note-1", summary.text)
        callbacks = self.backend._kernel.model_callbacks
        receipt = await self.backend.execute_context(
            self.compact_command(instructions_ref="note-1")
        )
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(self.backend._kernel.model_callbacks, callbacks)
        self.assertEqual(self.rpc.compact_instructions, summary.text)
        self.assertEqual(receipt.payload["result"]["summary_sha256"], summary.sha256)
        self.assertEqual(self.backend._summary, summary.text.encode())
        self.assertFalse(is_native_generic_summary(summary.text))
        self.assertNotIn("## Goal", summary.text)
        self.assertNotIn(summary.text, json.dumps(receipt.to_mapping()))

    async def test_native_template_on_a_code_aware_compact_is_refused(self):
        from asterion.agents.prime.code_summary import (
            KernelBinding,
            build_code_aware_summary,
        )
        from asterion.agents.prime.summarization import SUMMARY_INITIAL_TEMPLATE

        summary = build_code_aware_summary(
            (KernelBinding("AffineAccumulator", "class"),),
            keep_recent_tokens=256,
        )
        await self.backend.execute_prompt(self.request())
        self.backend.bind_compaction_instruction("note-1", summary.text)
        callbacks = self.backend._kernel.model_callbacks
        self.rpc.compact_summary_override = SUMMARY_INITIAL_TEMPLATE
        receipt = await self.backend.execute_context(
            self.compact_command(command_id="compact-native", instructions_ref="note-1")
        )
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(receipt.reason_code, "recovery-required")
        self.assertEqual(self.backend._kernel.model_callbacks, callbacks)
        self.assertIsNone(self.backend._summary)
        self.assertNotIn("## Goal", self.rpc.compact_instructions)

    async def test_unresolvable_instruction_reference_is_refused(self):
        await self.backend.execute_prompt(self.request())
        receipt = await self.backend.execute_context(
            self.compact_command(instructions_ref="note-absent")
        )
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(receipt.reason_code, "instructions-unavailable")
        self.assertEqual(self.rpc.compacts, 0)
        self.assertIsNone(self.rpc.compact_instructions)

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

    def compact_command(
        self, command_id="compact-1", tokens=16000, instructions_ref=None
    ):
        return SessionContextCommand(
            command_id,
            "session-1",
            1,
            1,
            command_id,
            "session.compact",
            {
                "continuation_id": "continuation-1",
                "instructions_ref": instructions_ref,
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

    async def test_compact_authority_refusals_precede_reservation_and_approval(self):
        await self.backend.execute_prompt(self.request())
        sink = MemoryDiagnosticSink()
        self.backend._diagnostics = sink
        rows = (
            ("quote-token", 48001, 125000, {}, {}, "compaction-token-limit", 48000, "estimate"),
            ("quote-cost", 48000, 125001, {}, {}, "compaction-cost-limit", 125000, "estimate"),
            ("session-token", 48000, 125000, {"aggregate_tokens": 16001}, {}, "prime-session-token-limit", 47999, "exact"),
            ("session-cost", 48000, 125000, {"cost_micros": 375001}, {}, "prime-session-cost-limit", 124999, "exact"),
            ("parent-controller", 48000, 125000, {}, {"controller_tokens": 47999}, "prime-parent-token-limit", 47999, "exact"),
            ("parent-aggregate", 48000, 125000, {}, {"aggregate_tokens": 47999}, "prime-parent-token-limit", 47999, "exact"),
            ("parent-cost", 48000, 125000, {}, {"cost_micros": 124999}, "prime-parent-cost-limit", 124999, "exact"),
            ("parent-controller-zero", 48000, 125000, {}, {"controller_tokens": 0}, "prime-parent-token-limit", 0, "exact"),
            ("parent-aggregate-zero", 48000, 125000, {}, {"aggregate_tokens": 0}, "prime-parent-token-limit", 0, "exact"),
            ("parent-cost-zero", 48000, 125000, {}, {"cost_micros": 0}, "prime-parent-cost-limit", 0, "exact"),
        )
        initial_usage = self.backend.usage
        for name, quoted_tokens, quoted_cost, used, parent, code, available, measurement in rows:
            with self.subTest(name=name):
                self.backend._usage = initial_usage
                grant = replace(RemainingBudget(64000, 64000, 0, 64000, 500000, 600000), **parent)
                self.backend.sync_authority_snapshot(grant)
                self.backend._usage = replace(initial_usage, **used)
                before_usage = self.backend.usage
                callbacks = self.backend._kernel.model_callbacks
                command = self.compact_command(name, tokens=48000)
                quote = CompactionReservationQuote(quoted_tokens, quoted_cost, ())
                with patch("asterion.agents.prime.context.quote_compaction_reservation", return_value=quote):
                    receipt = await self.backend.execute_context(command)
                self.assertEqual((receipt.status, receipt.reason_code), ("rejected", code))
                diagnostic = self.backend._witness.last_refusal
                self.assertEqual((diagnostic.limit_code, diagnostic.limit, diagnostic.measurement,
                                  diagnostic.config_source), (code, available, measurement, "authority"))
                self.assertEqual(self.backend.usage, before_usage)
                self.assertEqual(self.backend._kernel.model_callbacks, callbacks)
                self.assertEqual(self.rpc.compact_decisions[-1], "reject")
                self.assertFalse(any(record.kind == "context-reservation" for record in self.store.records()))
                self.assertEqual(self.backend.snapshot().phase, "open")
                self.assertEqual(sink.get(next(reversed(sink._records))).limit_diagnostic, diagnostic)

    async def test_compact_parent_consumption_since_snapshot_is_subtracted(self):
        await self.backend.execute_prompt(self.request())
        for field, code in (("controller_tokens", "prime-parent-token-limit"),
                            ("aggregate_tokens", "prime-parent-token-limit"),
                            ("cost_micros", "prime-parent-cost-limit")):
            with self.subTest(field=field):
                self.backend.sync_authority_snapshot(RemainingBudget(64000, 64000, 0, 64000, 500000, 600000))
                requested = 125000 if field == "cost_micros" else 48000
                consumed = (500000 if field == "cost_micros" else 64000) - requested + 1
                self.backend._usage = replace(self.backend.usage, **{field: getattr(self.backend.usage, field) + consumed})
                # Keep the session cap ample, independently of the parent grant.
                self.backend._token_cap = 1000000
                self.backend._cost_cap = 1000000
                receipt = await self.backend.execute_context(self.compact_command(field, tokens=48000))
                self.assertEqual((receipt.status, receipt.reason_code), ("rejected", code))
                self.assertEqual(self.backend._witness.last_refusal.limit, requested - 1)

    async def test_compact_exact_remaining_authority_admits_before_approve(self):
        await self.backend.execute_prompt(self.request())
        self.backend.sync_authority_snapshot(RemainingBudget(48000, 0, 0, 48000, 125000, 600000))
        self.backend._token_cap = self.backend.usage.aggregate_tokens + 48000
        self.backend._cost_cap = self.backend.usage.cost_micros + 125000
        quote = CompactionReservationQuote(48000, 125000, ())
        with patch("asterion.agents.prime.context.quote_compaction_reservation", return_value=quote):
            receipt = await self.backend.execute_context(self.compact_command(tokens=48000))
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(self.rpc.compact_decisions, ["approve"])
        self.assertIsNone(self.backend._witness.last_refusal)

    async def test_compact_callback_refusal_retains_zero_and_one_authority(self):
        await self.backend.execute_prompt(self.request())
        for remaining in (0, 1):
            with self.subTest(remaining=remaining):
                self.backend._kernel.model_callbacks = self.backend._limits.model_callbacks - remaining
                usage = self.backend.usage
                receipt = await self.backend.execute_context(self.compact_command(f"callbacks-{remaining}"))
                self.assertEqual((receipt.status, receipt.reason_code), ("rejected", "compaction-callback-limit"))
                self.assertEqual(self.backend._witness.last_refusal.limit, remaining)
                self.assertEqual(self.backend.usage, usage)
                self.assertEqual(self.backend._kernel.model_callbacks, 8 - remaining)
                self.assertEqual(self.rpc.compact_decisions[-1], "reject")

    async def test_known_peer_limit_waits_for_native_abort_and_allows_next_effect(self):
        await self.backend.execute_prompt(self.request())
        usage = self.backend.usage
        callbacks = self.backend._kernel.model_callbacks
        diagnostic = LimitDiagnostic("witness-frame-limit", "admission", "rejected",
            16777217, 16777216, "bytes", "exact", "framework-default")
        self.rpc.compact_limit = diagnostic
        receipt = await self.backend.execute_context(self.compact_command())
        self.assertEqual((receipt.status, receipt.reason_code), ("rejected", diagnostic.limit_code))
        self.assertEqual(self.backend._witness.last_refusal, diagnostic)
        self.assertEqual(self.backend.usage, usage)
        self.assertEqual(self.backend._kernel.model_callbacks, callbacks)
        self.assertEqual(self.backend.snapshot().phase, "open")
        self.assertIsNone(self.backend.snapshot().outstanding_effect)
        self.assertFalse(any(record.kind == "context-reservation" for record in self.store.records()))
        self.assertIsNone(self.rpc.pending_abort)
        self.rpc.compact_limit = None
        await self.backend.execute_prompt(self.request("prompt-2"))
        followup = await self.backend.execute_context(self.compact_command("compact-2"))
        self.assertEqual(followup.status, "succeeded")
        self.assertIsNone(self.backend._witness.last_refusal)

    async def test_peer_limit_without_matching_native_abort_still_fences(self):
        await self.backend.execute_prompt(self.request())
        usage = self.backend.usage
        self.rpc.compact_limit = LimitDiagnostic("witness-frame-limit", "admission", "rejected",
            16777217, 16777216, "bytes", "exact", "framework-default")
        self.rpc.compact_abort_unknown = True
        receipt = await self.backend.execute_context(self.compact_command())
        self.assertEqual((receipt.status, receipt.reason_code), ("uncertain", "recovery-required"))
        self.assertEqual(self.backend.usage, usage)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_unknown_after_approval_retains_reservation_and_callbacks(self):
        await self.backend.execute_prompt(self.request())
        usage = self.backend.usage
        callbacks = self.backend._kernel.model_callbacks
        self.rpc.corrupt_compact = True
        receipt = await self.backend.execute_context(self.compact_command(tokens=48000))
        self.assertEqual((receipt.status, receipt.reason_code), ("uncertain", "recovery-required"))
        self.assertEqual(self.backend.usage.aggregate_tokens, usage.aggregate_tokens + 48000)
        self.assertEqual(self.backend.usage.cost_micros, usage.cost_micros + 125000)
        self.assertEqual(self.backend._kernel.model_callbacks, callbacks + 2)
        self.assertEqual(self.backend.snapshot().phase, "recovery-required")

    async def test_expired_compact_authority_is_typed_before_rpc_or_reservation(self):
        await self.backend.execute_prompt(self.request())
        self.backend.sync_authority_snapshot(RemainingBudget(64000, 64000, 0, 64000, 500000, 0))
        usage = self.backend.usage
        receipt = await self.backend.execute_context(self.compact_command())
        self.assertEqual((receipt.status, receipt.reason_code), ("rejected", "compaction-deadline"))
        self.assertEqual(self.rpc.compacts, 0)
        self.assertEqual(self.backend.usage, usage)
        self.assertFalse(any(record.kind == "context-reservation" for record in self.store.records()))

    async def test_reserve_limit_and_failed_alarm_sink_keep_original_reason(self):
        from asterion.services.diagnostics import ResourceLimitExceeded
        from asterion.applications.prime.resource_alarms import ResourceAlarmSink
        await self.backend.execute_prompt(self.request())
        class BrokenSink:
            def record(self, _record):
                raise RuntimeError("PRIVATE-ALARM-SINK")
        diagnostic = LimitDiagnostic("prime-parent-cost-limit", "admission", "rejected",
            125000, 7, "cost-micros", "exact", "authority")
        original = self.backend._append
        def refuse(record_id, kind, payload):
            if kind == "context-reservation":
                raise ResourceLimitExceeded(diagnostic)
            return original(record_id, kind, payload)
        visible = []
        alarm_sink = ResourceAlarmSink(self.root / 'resource-alarms.jsonl', emit=visible.append)
        usage = self.backend.usage
        for index, sink in enumerate((None, BrokenSink(), alarm_sink)):
            with self.subTest(sink=type(sink).__name__):
                self.backend._diagnostics = sink
                with patch.object(self.backend, "_append", side_effect=refuse):
                    receipt = await self.backend.execute_context(self.compact_command(f'limit-{index}'))
                self.assertEqual((receipt.status, receipt.reason_code), ("rejected", diagnostic.limit_code))
                self.assertEqual(self.backend._witness.last_refusal, diagnostic)
                self.assertEqual(self.backend.usage, usage)
                self.assertEqual(self.rpc.compact_decisions[-1], "reject")
        self.assertEqual(len(visible), 1)
        self.assertEqual(alarm_sink.alarms[0]['configuration'], 'RemainingBudget.cost_micros')

    async def test_malformed_compact_proposal_retains_protocol_fence_without_charge(self):
        await self.backend.execute_prompt(self.request())
        self.rpc.compact_proposal_overrides = {"extra": "PRIVATE-PROPOSAL"}
        usage = self.backend.usage
        callbacks = self.backend._kernel.model_callbacks
        receipt = await self.backend.execute_context(self.compact_command())
        self.assertEqual((receipt.status, receipt.reason_code), ("uncertain", "recovery-required"))
        self.assertIsNone(self.backend._witness.last_refusal)
        self.assertEqual(self.backend.usage, usage)
        self.assertEqual(self.backend._kernel.model_callbacks, callbacks)
        self.assertEqual(self.rpc.compact_decisions, [])
        self.assertFalse(any(record.kind == "context-reservation" for record in self.store.records()))
        self.assertNotIn("PRIVATE-PROPOSAL", repr(receipt.to_mapping()))

    async def test_nonzero_application_or_child_compact_authority_is_malformed(self):
        await self.backend.execute_prompt(self.request())
        for field in ("application_tokens", "child_tokens"):
            with self.subTest(field=field):
                command = self.compact_command(field)
                command = replace(command, payload={**command.payload,
                    "budget": {**command.payload["budget"], field: 1}})
                usage = self.backend.usage
                receipt = await self.backend.execute_context(command)
                self.assertEqual((receipt.status, receipt.reason_code), ("rejected", "context-not-admitted"))
                self.assertIsNone(self.backend._witness.last_refusal)
                self.assertEqual(self.backend.usage, usage)
                self.assertEqual(self.rpc.compact_decisions[-1], "reject")
                self.assertFalse(any(record.kind == "context-reservation" for record in self.store.records()))


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


class TestPiCompactTerminalContract(unittest.TestCase):
    """`PiSession.compact()` aborts first, so a settled event leads the stream.

    That abort is Pi's own opening step rather than an extra event, so the three
    events the contract is about follow it with their sequences intact. A live
    run failed here because the check required exactly three events.
    """

    # Pi's compact result is exactly these keys at both of its terminals.
    BODY = {
        "summary": "a summary",
        "firstKeptEntryId": "entry-1",
        "tokensBefore": 10,
        "estimatedTokensAfter": 4,
        "usage": {"input": 3, "output": 1},
        "details": {},
    }

    def _result(self, *kinds: str):
        from asterion.runtimes.pi_rpc import PiRpcCompactResult, PiRpcEvent

        payloads = {
            "agent_settled": {},
            "compaction_start": {"reason": "manual"},
            "compaction_end": {
                "reason": "manual",
                "result": self.BODY,
                "aborted": False,
                "willRetry": False,
                "customInstructions": None,
            },
            # `_compact_rpc_event` projects a response to identity and outcome
            # before the validator sees it; `command` and the echoed `data` are
            # stripped. Modelling the raw stream here is what let the validator
            # require fields the running path can never deliver.
            "response": {
                "id": "compact-rpc",
                "success": True,
            },
        }
        return PiRpcCompactResult(
            "compact-rpc",
            "compact",
            tuple(
                PiRpcEvent(index, kind, payloads.get(kind, {}))
                for index, kind in enumerate(kinds, 1)
            ),
            b"",
        )

    def test_the_aborts_settled_event_is_accepted(self) -> None:
        from asterion.runtimes.pi_rpc import validate_pi_compact_result

        validate_pi_compact_result(
            self._result(
                "agent_settled", "compaction_start", "compaction_end", "response"
            )
        )

    def test_the_three_event_stream_is_still_accepted(self) -> None:
        from asterion.runtimes.pi_rpc import validate_pi_compact_result

        validate_pi_compact_result(
            self._result("compaction_start", "compaction_end", "response")
        )

    def test_an_unknown_result_field_is_still_refused(self) -> None:
        # Widening the result set to Pi's real keys must not turn it into an
        # accept-anything: an unmodelled field is exactly the drift it catches.
        from asterion.runtimes.pi_rpc import (
            PiRpcCompactResult,
            PiRpcEvent,
            validate_pi_compact_result,
        )

        events = (
            PiRpcEvent(1, "compaction_start", {"reason": "manual"}),
            PiRpcEvent(
                2,
                "compaction_end",
                {
                    "reason": "manual",
                    "result": {**self.BODY, "surprise": 1},
                    "aborted": False,
                    "willRetry": False,
                },
            ),
            PiRpcEvent(3, "response", {"id": "compact-rpc", "success": True}),
        )
        with self.assertRaises(ValueError):
            validate_pi_compact_result(
                PiRpcCompactResult("compact-rpc", "compact", events, b"")
            )

    def test_the_unreduced_response_shape_is_refused(self) -> None:
        # The projection is the contract. A response still carrying the raw
        # `command` and echoed `data` did not come through `_compact_rpc_event`,
        # so accepting it would validate a shape the running path never delivers.
        from asterion.runtimes.pi_rpc import (
            PiRpcCompactResult,
            PiRpcEvent,
            validate_pi_compact_result,
        )

        events = (
            PiRpcEvent(1, "compaction_start", {"reason": "manual"}),
            PiRpcEvent(
                2,
                "compaction_end",
                {
                    "reason": "manual",
                    "result": self.BODY,
                    "aborted": False,
                    "willRetry": False,
                },
            ),
            PiRpcEvent(
                3,
                "response",
                {
                    "id": "compact-rpc",
                    "command": "compact",
                    "success": True,
                    "data": self.BODY,
                },
            ),
        )
        with self.assertRaises(ValueError):
            validate_pi_compact_result(
                PiRpcCompactResult("compact-rpc", "compact", events, b"")
            )

    def test_other_leading_events_are_still_refused(self) -> None:
        from asterion.runtimes.pi_rpc import validate_pi_compact_result

        for kinds in (
            ("agent_start", "compaction_start", "compaction_end", "response"),
            (
                "agent_settled",
                "agent_settled",
                "compaction_start",
                "compaction_end",
                "response",
            ),
        ):
            with self.subTest(kinds=kinds):
                with self.assertRaises(ValueError):
                    validate_pi_compact_result(self._result(*kinds))

    def test_a_truncated_stream_is_still_refused(self) -> None:
        from asterion.runtimes.pi_rpc import validate_pi_compact_result

        with self.assertRaises(ValueError):
            validate_pi_compact_result(self._result("compaction_start", "response"))


if __name__ == "__main__":
    unittest.main()


class TestPrimeOwnedBackend(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, *, compaction_policy=PrimeCompactionPolicy(),
                      compaction_policy_source='framework-default', environment=None, diagnostics=None,
                      bridge_output_bytes=None):
        import time
        from asterion.agents.prime.application import (
            PrimeApplicationSpec, PrimeOperatorContext, PrimeBackendSpec,
            PrimeToolModuleArtifact, prepare_prime_application,
        )
        from asterion.agents.prime.deadline import TaskDeadline
        from asterion.agents.prime.tool_registry import CORE_TOOL_REGISTRY
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        extension = root / 'extension.mjs'
        extension.write_text('export default function extension() {}\n')
        private = root / 'backend'
        private.mkdir(mode=0o700)
        self.spec = PrimeBackendSpec('owner-session', 1, private, 'continue-one',
            AsterionPrimeLimits(8, 4, 600000), 64000, 500000,
            ModelPrice(300000, 1200000), 'authority-1', {},
            compat_provider_id='prime-applications', compaction_policy=compaction_policy,
            compaction_policy_source=compaction_policy_source)
        operator = PrimeOperatorContext(Path('/usr/bin/true'), None, root,
            'deepseek', 'deepseek-flash', 'off', {} if environment is None else environment,
            TaskDeadline(deadline_monotonic=time.monotonic()+60, deadline_epoch=time.time()+60),
            diagnostics=diagnostics)
        self.app = prepare_prime_application(
            PrimeApplicationSpec('prime.ipython-coding', '1.0.0', 'persistent-code-tools',
                                 tools=PrimeToolModuleArtifact(extension, CORE_TOOL_REGISTRY)),
            operator, authorization=self.spec)
        self.addAsyncCleanup(self.app.close)
        self.executor = FakeToolExecutor()
        if bridge_output_bytes is not None:
            self.executor.bridge_output_bytes = bridge_output_bytes
        self.executor.execute = lambda *args: None
        self.executor.call = lambda *args: None
        self.executor.request_stop = lambda: None
        def rpc(**kwargs):
            kwargs.pop('diagnostics', None)
            kwargs.pop('private_failure_sink', None)
            self.rpc = FakeReusablePi(PiRpcConfig(**kwargs))
            self.rpc.stop = lambda: setattr(self.rpc, 'stopped', True)
            return self.rpc
        with patch('asterion.runtime.native_rpc.build_rpc_session', side_effect=rpc):
            self.attachment = await self.app.open_backend(spec=self.spec, services=self.executor)

    async def test_injected_output_capacity_reaches_launch_and_python_bridge(self):
        capacity = 2 * 1024 * 1024
        await self.fixture(bridge_output_bytes=capacity)
        resource = self.app._persistent
        self.assertEqual(resource.environment.get('ASTERION_PRIME_IPYTHON_OUTPUT_BYTES'), str(capacity))
        self.assertEqual(getattr(resource.bridge, '_max_output_bytes', None), capacity)
        self.assertEqual(getattr(resource.bridge, '_max_line_bytes', None), 6 * capacity + 8192)

    async def test_injected_policy_bootstrap_and_identity_resume_mismatch(self):
        selected = PrimeCompactionPolicy(max_total_tokens=48000, max_frame_bytes=20000,
            max_material_bytes=10000)
        await self.fixture(compaction_policy=selected, compaction_policy_source='application')
        resource = self.app._persistent
        bootstrap = resource.environment['ASTERION_PRIME_IPYTHON_COMPACTION_POLICY']
        self.assertLessEqual(len(bootstrap.encode()), 512)
        self.assertEqual(json.loads(bootstrap), {**asdict(selected), 'config_source': 'application'})
        identity = self.attachment.snapshot().identity
        expected = {**asdict(self.spec.limits), 'aggregate_tokens': self.spec.aggregate_tokens,
            'cost_micros': self.spec.cost_micros, 'compaction_policy': asdict(selected),
            'compaction_policy_source': 'application'}
        self.assertEqual(identity.ceilings_sha256, digest(expected))
        old = replace(identity, ceilings_sha256=digest({**expected,
            'compaction_policy': asdict(PrimeCompactionPolicy())}))
        self.assertNotEqual(old.ceilings_sha256, identity.ceilings_sha256)
        resource.store.close()
        from asterion.agents.prime.store import PrimeStoreError
        with self.assertRaises(PrimeStoreError):
            FilePrimeSessionStore(self.spec.private_root, old)
        self.assertEqual(self.rpc.opens, 0)

    async def test_operator_cannot_replace_trusted_policy_transport(self):
        from asterion.runtime.protocol import ProtocolError
        with patch('asterion.runtime.native_rpc.build_rpc_session') as build:
            with self.assertRaises(ProtocolError):
                await self.fixture(environment={
                    'ASTERION_PRIME_IPYTHON_COMPACTION_POLICY': 'private-sentinel'})
            build.assert_not_called()

    async def test_complete_arm_is_checked_before_rpc_process_construction(self):
        from asterion.runtime.protocol import ProtocolError
        from asterion.services.diagnostics import limit_diagnostic
        from asterion.agents.prime.context import _encode
        from asterion.agents.prime.summarization import build_summarization_material
        sink = MemoryDiagnosticSink()
        size = len(_encode(build_summarization_material()))
        cap = size + 100
        with patch('asterion.runtime.native_rpc.build_rpc_session') as build:
            with self.assertRaises(ProtocolError) as failure:
                await self.fixture(compaction_policy=PrimeCompactionPolicy(
                    max_frame_bytes=cap, max_material_bytes=size),
                    compaction_policy_source='application', diagnostics=sink)
            build.assert_not_called()
        diagnostic = limit_diagnostic(failure.exception)
        self.assertIsNotNone(diagnostic)
        self.assertEqual(diagnostic.limit_code, 'witness-frame-limit')
        self.assertEqual((diagnostic.limit, diagnostic.phase, diagnostic.action),
            (cap, 'admission', 'rejected'))
        self.assertEqual(diagnostic.config_source, 'application')
        self.assertGreater(diagnostic.observed, cap)
        self.assertEqual(len(sink._records), 1)
        record = next(iter(sink._records.values()))
        self.assertEqual(record.stage, 'prime.backend.startup')
        self.assertEqual(record.limit_diagnostic, diagnostic)
        self.assertEqual(record.subject_sha256, hashlib.sha256(self.spec.session_id.encode()).hexdigest())
        self.assertNotIn(str(self.spec.private_root), repr(record))
        self.assertTrue(self.executor.closed)

    async def test_attachment_close_keeps_owner_and_generation_without_model_effect(self):
        await self.fixture()
        identity = self.attachment.snapshot().identity
        self.assertEqual(self.rpc.opens, 0)
        self.assertEqual((self.rpc.config.expected_provider, self.rpc.config.expected_model),
                         ('deepseek', 'deepseek-flash'))
        await self.attachment.close()
        again = self.app.attach_backend(identity)
        self.assertEqual(again.snapshot().identity.generation, identity.generation)
        self.assertFalse(self.executor.closed)
        with self.assertRaises(Exception):
            self.app.attach_backend(replace(identity, generation=2))
        self.assertTrue((await self.app.close()).complete)
        self.assertTrue(self.executor.closed)

    async def test_authority_snapshot_cannot_renew_absolute_task_deadline(self):
        await self.fixture()
        self.attachment.sync_authority_snapshot(
            RemainingBudget(64000, 64000, 0, 64000, 500000, 600000), authority_revision=1)
        await self.attachment.accept_control(ControlCommand(
            'create-one', self.spec.session_id, 1, 'session.create',
            {'system_id': 'prime.ipython-coding', 'system_version': '1.0.0',
             'goal_id': 'goal-one', 'goal_ref': 'goal-ref'}))
        with patch.object(self.app.task_deadline, 'remaining_seconds', return_value=0):
            with self.assertRaises(PrimeBackendError):
                await self.attachment.execute_prompt(
                    PrimePromptRequest('prompt-one', self.spec.session_id, 1, 'private task'))
        self.assertEqual(self.rpc.opens, 0)

    async def test_rpc_close_failure_still_reaps_and_closes_independent_resources(self):
        await self.fixture()
        async def fail():
            raise RuntimeError('private-close-failure')
        self.rpc.close = fail
        receipt = await self.app.close()
        self.assertTrue(self.rpc.stopped)
        self.assertTrue(self.executor.closed)
        self.assertTrue(receipt.extension_closed)
        self.assertTrue(receipt.bridge_closed)
        self.assertFalse(receipt.complete)

    async def test_failed_backend_construction_closes_acquired_owners(self):
        from asterion.runtime.protocol import ProtocolError
        with patch('asterion.agents.prime.application.PrimeSessionBackend',
                   side_effect=ValueError('private-sentinel')):
            with self.assertRaises(ProtocolError) as failure:
                await self.fixture()
        self.assertNotIn('private-sentinel', str(failure.exception))
        self.assertTrue(self.executor.closed)
        self.assertTrue(self.rpc.stopped)
        self.assertTrue(self.app._persistent.lease.closed)

    async def test_control_factory_accepts_exact_owner_and_rejects_authority_mismatch(self):
        from tests.test_asterion_prime_control import authority, remaining_budget
        from asterion.control.factory import ControlPlaneFactoryContext, ControlPlaneFactoryError
        from asterion.control.providers.asterion_prime import build_asterion_prime_control_plane_client
        await self.fixture()
        self.attachment.sync_authority_snapshot(remaining_budget(), authority_revision=1)
        context = ControlPlaneFactoryContext(
            system_id='prime.ipython-coding', system_version='1.0.0',
            control_plane_id='asterion.prime-control', control_plane_version='1.0.0',
            private_root=self.spec.private_root,
            options={'generation': '1', 'session_id': self.spec.session_id},
            authority=authority(), host_services={'prime.session-backend': self.app})
        client = build_asterion_prime_control_plane_client(context)
        await client.close()
        self.assertFalse(self.executor.closed)
        bad = replace(context, authority=replace(authority(), authority_id='wrong-authority'))
        with self.assertRaises(ControlPlaneFactoryError):
            build_asterion_prime_control_plane_client(bad)
