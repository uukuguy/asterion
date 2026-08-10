from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityError,
    AuthorityLedger,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
)
from asterion.control.children import (
    ChildSessionError,
    ChildSessionService,
    ChildSessionStatus,
    ChildTerminalReceipt,
    derive_child_authority,
)
from asterion.control.execution import ActionExecutionFailure, ActionExecutionReceipt
from asterion.control.factory import (
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryContext,
    ControlPlaneFactoryRegistry,
)
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.journal import FileCanonicalJournal
from asterion.control.manager import ControlHost, ControlHostError
from asterion.control.system import AgentSystemPlan
from asterion.runtime.host import CancellationSignal
from tests.test_control_application_executor import _executor as _application_executor
from tests.test_control_host import ScriptedClient, _create_command, _session_events
from tests.test_control_system import _control_factories, _manifest, _provider


SENTINEL = "SENTINEL_SECRET"


class MutableSignal:
    def __init__(self) -> None:
        self.cancelled = False


class RecordingResolver:
    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        self.requests.append((reference, max_bytes))
        if reference == "missing-ref":
            raise RuntimeError(f"{SENTINEL} missing")
        return f"private {reference} {SENTINEL}"


class ChildWorkExecutor:
    def __init__(self, audit: list[str], *, fail: bool = False) -> None:
        self.audit = audit
        self.fail = fail

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        del signal
        self.audit.append("child.executor")
        if self.fail:
            raise ActionExecutionFailure("failed", "child-work-failed", "child-work")
        return ActionExecutionReceipt(
            action_id=str(proposal.payload["action_id"]),
            receipt_ref="child-work",
            usage=BudgetUsage(
                controller_tokens=0,
                application_tokens=17,
                child_tokens=0,
                aggregate_tokens=17,
                cost_micros=3,
            ),
        )


class WaitingChildClient:
    def __init__(
        self,
        manifest: ControlPlaneManifest,
        audit: list[str],
        *,
        close_fails: bool = False,
        terminal: str = "completed",
    ) -> None:
        self._manifest = manifest
        self.audit = audit
        self.close_fails = close_fails
        self.terminal = terminal
        self.sent: list[ControlCommand] = []
        self.messages: list[str] = []
        self.cancelled = False
        self.closed = False
        self._session_id: str | None = None
        self._goal_id: str | None = None
        self._events: list[ControlEvent] = []

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        self.audit.append(f"child.command.{command.type}")
        self.sent.append(command)
        if command.type == "session.create":
            self._session_id = command.session_id
            self._goal_id = str(command.payload["goal_id"])
            self._emit(
                "session.created",
                {
                    "goal_id": command.payload["goal_id"],
                    "authority_id": "child:child-1",
                    "authority_revision": 1,
                },
            )
            self._emit("session.running", {"reason_code": "started"})
            self._emit_child_work()
        elif command.type == "action.resolve":
            if command.payload["resolution"] == "succeeded":
                if self.terminal == "completed":
                    self._emit("goal.updated", {"goal_id": self._goal_id, "status": "completed"})
                    self._emit("session.completed", {"reason_code": "done"})
                elif self.terminal == "failed":
                    self._emit("session.failed", {"reason_code": "child-failed"})
                elif self.terminal == "cancelled":
                    self._emit("session.cancelled", {"reason_code": "child-cancelled"})
        elif command.type == "input.submit":
            self.messages.append(str(command.payload["input_id"]))
        elif command.type == "session.cancel":
            self.cancelled = True
            self._emit("session.cancelled", {"reason_code": command.payload["reason_code"]})

    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]:
        start = cursor.sequence if cursor is not None else 0
        return self._iterate(start)

    async def _iterate(self, start: int) -> AsyncIterator[ControlEvent]:
        index = start
        while True:
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.type in {
                    "session.budget-limited",
                    "session.cancelled",
                    "session.completed",
                    "session.failed",
                }:
                    return
            await asyncio.sleep(0)

    async def close(self) -> None:
        self.audit.append("child.close")
        if self.close_fails:
            raise RuntimeError(f"{SENTINEL} close")
        self.closed = True

    def _emit_child_work(self) -> None:
        self._emit(
            "action.proposed",
            {
                "action_id": "child-action-1",
                "authority_revision": 1,
                "idempotency_key": "child-idem-1",
                "kind": "application.invoke",
                "target": {
                    "kind": "application",
                    "provider_id": "example.provider",
                    "application_id": "alpha",
                    "version": "1.0.0",
                    "runtime_id": "fake.runtime",
                },
                "input_ref": "child-input",
                "expected_artifacts": (),
                "budget": {
                    "controller_tokens": 0,
                    "application_tokens": 17,
                    "child_tokens": 0,
                    "aggregate_tokens": 17,
                    "cost_micros": 3,
                    "deadline_ms": 1000,
                },
                "causal_parent_ids": ("goal-1",),
            },
        )

    def _emit(self, event_type: str, payload: Mapping[str, object]) -> None:
        if self._session_id is None:
            raise AssertionError("session missing")
        sequence = len(self._events) + 1
        self._events.append(
            ControlEvent(
                event_id=f"child-event-{sequence}",
                session_id=self._session_id,
                generation=1,
                sequence=sequence,
                emitted_at=f"2026-08-10T03:00:{sequence:02d}Z",
                type=event_type,
                payload=payload,
            )
        )


def _plan(root: Path) -> AgentSystemPlan:
    return cast(
        AgentSystemPlan,
        __import__("asterion.control.system", fromlist=["resolve_agent_system"]).resolve_agent_system(
            _manifest(),
            application_providers=(_provider(root),),
            control_factories=_control_factories([]),
            host_capabilities=("clock.monotonic", "storage.private"),
        ),
    )


def _child_proposal(
    *,
    action_id: str = "spawn-action-1",
    child_id: str = "child-1",
    budget: Mapping[str, object] | None = None,
    input_ref: str = "goal-ref-1",
) -> ControlEvent:
    return ControlEvent(
        event_id=f"event-{action_id}",
        session_id="session-1",
        generation=1,
        sequence=3,
        emitted_at="2026-08-10T03:00:00Z",
        type="action.proposed",
        payload={
            "action_id": action_id,
            "authority_revision": 1,
            "idempotency_key": f"idem-{action_id}",
            "kind": "child.spawn",
            "target": {"kind": "child", "child_id": child_id},
            "input_ref": input_ref,
            "expected_artifacts": (),
            "budget": budget
            or {
                "controller_tokens": 0,
                "application_tokens": 17,
                "child_tokens": 50,
                "aggregate_tokens": 50,
                "cost_micros": 10,
                "deadline_ms": 1000,
            },
            "causal_parent_ids": ("goal-1",),
        },
    )


def _child_envelope(**changes: object) -> AuthorityEnvelope:
    values = {
        "authority_id": "authority-1",
        "revision": 1,
        "allowed_portfolio": (
            PortfolioGrant(
                provider_id="example.provider",
                application_id="alpha",
                version="1.0.0",
                runtime_id="fake.runtime",
            ),
        ),
        "allowed_operations": ("application.invoke", "child.cancel", "child.message", "child.spawn"),
        "budget_limit": BudgetLimit(100, 100, 100, 300, 100),
        "expires_at_ms": 10_000,
        "max_action_deadline_ms": 2_000,
        "max_recursion_depth": 1,
        "max_concurrent_children": 1,
        "execution_domain": "trusted-local",
        "host_service_grants": ("storage.private",),
        "cancelled": False,
    }
    values.update(changes)
    return AuthorityEnvelope(**values)  # type: ignore[arg-type]


def _registry(
    audit: list[str],
    clients: list[WaitingChildClient],
    *,
    close_fails: bool = False,
    terminal: str = "completed",
    factory_failure: str | None = None,
) -> ControlPlaneFactoryRegistry:
    def factory(context: ControlPlaneFactoryContext) -> WaitingChildClient:
        audit.append("child.provider.create")
        if factory_failure == "known":
            raise ChildSessionError("known child create failure")
        if factory_failure == "unknown":
            raise RuntimeError(f"{SENTINEL} provider create")
        client = WaitingChildClient(
            _control_factories([]).select("fake.control", "1.0.0").manifest,
            audit,
            close_fails=close_fails,
            terminal=terminal,
        )
        clients.append(client)
        self_check = repr(context)
        if SENTINEL in self_check:
            raise AssertionError("private context leaked")
        return client

    return ControlPlaneFactoryRegistry(
        (
            ControlPlaneFactoryBinding(
                control_plane_id="fake.control",
                version="1.0.0",
                commands=_control_factories([]).select("fake.control", "1.0.0").commands,
                events=_control_factories([]).select("fake.control", "1.0.0").events,
                capabilities=("action-proposals",),
                continuation_media_type="application/vnd.asterion.control-capsule",
                checkpoint_version="1.0.0",
                compatibility_ids=("asterion.agent-control/v1",),
                factory=factory,
            ),
        )
    )


class TestChildAuthority(unittest.TestCase):
    def test_derive_child_authority_is_strict_subset_of_parent_reservation(self) -> None:
        parent = _child_envelope()
        proposal = _child_proposal()

        child = derive_child_authority(parent, proposal, "child-1", now_ms=1_000)

        self.assertEqual(child.authority_id, "child:child-1")
        self.assertEqual(child.revision, 1)
        self.assertEqual(child.allowed_portfolio, parent.allowed_portfolio)
        self.assertEqual(child.allowed_operations, parent.allowed_operations)
        self.assertEqual(child.budget_limit.controller_tokens, 50)
        self.assertEqual(child.budget_limit.application_tokens, 17)
        self.assertEqual(child.budget_limit.child_tokens, 50)
        self.assertEqual(child.budget_limit.aggregate_tokens, 50)
        self.assertEqual(child.expires_at_ms, 2_000)
        self.assertEqual(child.max_action_deadline_ms, 1_000)
        self.assertEqual(child.max_recursion_depth, 0)
        self.assertEqual(child.max_concurrent_children, parent.max_concurrent_children)

    def test_derive_child_authority_rejects_depth_zero_and_target_mismatch(self) -> None:
        with self.assertRaises(AuthorityError):
            derive_child_authority(
                replace(_child_envelope(), max_recursion_depth=0),
                _child_proposal(),
                "child-1",
                now_ms=1_000,
            )
        with self.assertRaises(AuthorityError):
            derive_child_authority(
                _child_envelope(),
                _child_proposal(child_id="child-2"),
                "child-1",
                now_ms=1_000,
            )

    def test_phase0_spawn_admission_uses_remaining_depth_not_exceeded_depth(self) -> None:
        ledger = AuthorityLedger(replace(_child_envelope(), max_recursion_depth=0))

        decision = ledger.evaluate(_child_proposal(), now_ms=1_000)

        self.assertEqual((decision.status, decision.reason), ("rejected", "recursion-depth-exceeded"))


class TestChildSessionService(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_close_waiters_share_shielded_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = ChildSessionService(
                plan=_plan(root), authority=_child_envelope(),
                control_factories=_registry([], []), private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor([]),
                clock_ms=lambda: 1_000,
            )
            first = asyncio.create_task(service.close())
            second = asyncio.create_task(service.close())
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            await second
            self.assertEqual(service.active_ids, ())
            with self.assertRaises(ChildSessionError):
                await service.spawn(_child_proposal(), MutableSignal())

    async def test_child_executor_factory_receives_nested_lifecycle_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            received: list[ChildSessionService] = []

            def factory(authority: AuthorityEnvelope, children: ChildSessionService) -> ChildWorkExecutor:
                del authority
                received.append(children)
                return ChildWorkExecutor(audit)

            service = ChildSessionService(
                plan=_plan(root), authority=_child_envelope(),
                control_factories=_registry(audit, []), private_root=root,
                content=RecordingResolver(), child_action_executor_factory=factory,
                clock_ms=lambda: 1_000,
            )
            await service.spawn(_child_proposal(), MutableSignal())
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].active_ids, ())

    async def test_message_transport_fault_is_uncertain_and_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []

            class BlockingExecutor(ChildWorkExecutor):
                async def execute(self, proposal: ControlEvent, signal: CancellationSignal) -> ActionExecutionReceipt:
                    await asyncio.sleep(0.05)
                    return await super().execute(proposal, signal)

            service = ChildSessionService(
                plan=_plan(root), authority=_child_envelope(),
                control_factories=_registry(audit, clients), private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: BlockingExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            task = asyncio.create_task(service.spawn(_child_proposal(), MutableSignal()))
            while not clients:
                await asyncio.sleep(0)

            async def fail_send(command: ControlCommand) -> None:
                del command
                raise RuntimeError(SENTINEL)

            clients[0].send = fail_send  # type: ignore[method-assign]
            with self.assertRaises(ActionExecutionFailure) as raised:
                await service.message(_child_message_proposal(), MutableSignal())
            self.assertEqual(raised.exception.status, "uncertain")
            self.assertEqual(service.status("child-1").status, "uncertain")
            self.assertNotIn(SENTINEL, str(raised.exception))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_prestart_cancellation_has_no_provider_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            service = ChildSessionService(
                plan=_plan(Path(directory)), authority=_child_envelope(),
                control_factories=_registry(audit, clients), private_root=Path(directory),
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            signal = MutableSignal()
            signal.cancelled = True

            with self.assertRaises(ActionExecutionFailure) as raised:
                await service.spawn(_child_proposal(), signal)

            self.assertEqual(raised.exception.status, "cancelled")
            self.assertEqual(clients, [])
            self.assertNotIn("child.provider.create", audit)

    async def test_hostile_option_mappings_are_redacted_at_construction(self) -> None:
        class HostileMapping(Mapping[str, str]):
            def __getitem__(self, key: str) -> str:
                raise RuntimeError(f"{SENTINEL}:{key}")

            def __iter__(self):
                raise RuntimeError(SENTINEL)

            def __len__(self) -> int:
                raise RuntimeError(SENTINEL)

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ChildSessionError) as raised:
                ChildSessionService(
                    plan=_plan(Path(directory)), authority=_child_envelope(),
                    control_factories=_registry([], []), private_root=Path(directory),
                    content=RecordingResolver(),
                    child_action_executor_factory=lambda authority: ChildWorkExecutor([]),
                    clock_ms=lambda: 1_000, control_options=HostileMapping(),
                )
            self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_spawn_persists_binding_before_provider_create_and_charges_verified_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            service = ChildSessionService(
                plan=plan,
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )

            receipt = await service.spawn(_child_proposal(), MutableSignal())

            self.assertTrue((root / "children" / "child-1" / "binding.json").is_file())
            self.assertEqual(receipt.usage, BudgetUsage(0, 0, 17, 17, 3))
            self.assertEqual(service.active_ids, ())
            self.assertEqual(
                service.status("child-1"),
                ChildSessionStatus(
                    child_id="child-1",
                    status="completed",
                    action_id="spawn-action-1",
                    receipt_ref="child-receipt-child-1",
                ),
            )
            self.assertTrue((root / "children" / "child-1").is_dir())
            self.assertEqual(oct((root / "children" / "child-1").stat().st_mode & 0o777), "0o700")

    async def test_completed_reopen_uses_durable_safe_receipt_without_provider_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            proposal = _child_proposal()

            first = await service.spawn(proposal, MutableSignal())
            terminal_path = root / "children" / "child-1" / "terminal.json"
            terminal_text = terminal_path.read_text()
            reopened = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            second = await reopened.spawn(proposal, MutableSignal())

            self.assertEqual(second, first)
            self.assertEqual(audit.count("child.provider.create"), 1)
            self.assertNotIn(SENTINEL, terminal_text)
            self.assertNotIn(str(root), terminal_text)
            terminal = json.loads(terminal_text)
            self.assertEqual(terminal["receipt"]["usage"]["child_tokens"], 17)
            self.assertEqual(terminal["receipt"]["artifact_ids"], [])
            self.assertEqual(terminal["receipt"]["media_types"], [])
            self.assertEqual(
                ChildTerminalReceipt.from_mapping(terminal["receipt"]).receipt,
                first,
            )

    async def test_child_durable_records_use_pinned_root_after_ancestor_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []

            def derive_options(
                base: Mapping[str, str],
                *,
                child_root: Path,
                child_session_id: str,
                child_authority: AuthorityEnvelope,
                generation: int,
            ) -> Mapping[str, str]:
                del child_root, child_session_id, child_authority, generation
                original_children = root / "children"
                original_children.rename(root / "children-original")
                replacement_child = root / "children" / "child-1"
                replacement_child.mkdir(parents=True, mode=0o700)
                replacement_child.chmod(0o700)
                return dict(base)

            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
                derive_control_options=derive_options,
            )

            receipt = await service.spawn(_child_proposal(), MutableSignal())
            await service.close()

            old_child = root / "children-original" / "child-1"
            replacement_child = root / "children" / "child-1"
            self.assertEqual(receipt.usage, BudgetUsage(0, 0, 17, 17, 3))
            self.assertTrue((old_child / "binding.json").is_file())
            self.assertTrue((old_child / "phase.json").is_file())
            self.assertTrue((old_child / "terminal.json").is_file())
            self.assertEqual(len(list(old_child.glob("journal-*.jsonl"))), 1)
            self.assertFalse((replacement_child / "binding.json").exists())
            self.assertFalse((replacement_child / "phase.json").exists())
            self.assertFalse((replacement_child / "terminal.json").exists())
            self.assertEqual(list(replacement_child.glob("journal-*.jsonl")), [])

    async def test_provider_create_started_without_terminal_is_uncertain_and_not_recreated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal = _child_proposal()
            child_root = ChildSessionService.prepare_child_root(root, "child-1")
            digest = ChildSessionService.persist_binding(
                child_root=child_root,
                child_id="child-1",
                action_id="spawn-action-1",
                session_id="child-session-child-1",
                authority_id="child:child-1",
                generation=1,
                proposal_digest=ChildSessionService.proposal_digest(proposal),
            )
            self.assertEqual(digest, ChildSessionService.proposal_digest(proposal))
            ChildSessionService.persist_phase(child_root=child_root, phase="provider-create-started")
            audit: list[str] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, []),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )

            with self.assertRaises(ActionExecutionFailure) as raised:
                await service.spawn(proposal, MutableSignal())

            self.assertEqual(raised.exception.status, "uncertain")
            self.assertEqual(raised.exception.reason_code, "child-progress-unknown")
            self.assertEqual(audit, [])

    async def test_child_factory_failure_after_the_durable_fence_is_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, [], factory_failure="known"),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )

            with self.assertRaises(ActionExecutionFailure) as raised:
                await service.spawn(_child_proposal(), MutableSignal())

            self.assertEqual(
                (raised.exception.status, raised.exception.reason_code),
                ("uncertain", "child-progress-unknown"),
            )
            self.assertNotIn(SENTINEL, repr(raised.exception))

    async def test_post_fence_executor_factory_fault_closes_created_client_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: (_ for _ in ()).throw(
                    RuntimeError("executor construction failed")
                ),
                clock_ms=lambda: 1_000,
            )

            with self.assertRaises(ActionExecutionFailure) as raised:
                await service.spawn(_child_proposal(), MutableSignal())

            self.assertEqual(raised.exception.status, "uncertain")
            self.assertEqual(audit.count("child.provider.create"), 1)
            self.assertEqual(audit.count("child.close"), 1)
            self.assertTrue(clients[0].closed)

    async def test_missing_private_goal_is_a_known_pre_fence_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, []),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )

            with self.assertRaises(ChildSessionError):
                await service.spawn(_child_proposal(input_ref="missing-ref"), MutableSignal())

            self.assertEqual(audit, [])
            self.assertIsNone(
                ChildSessionService.load_phase(root / "children" / "child-1")
            )

    async def test_child_terminal_failed_and_cancelled_map_to_safe_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for terminal, status, reason in (
                ("failed", "failed", "child-terminal-failed"),
                ("cancelled", "cancelled", "child-terminal-cancelled"),
            ):
                with self.subTest(terminal=terminal):
                    root = Path(directory) / terminal
                    root.mkdir(mode=0o700)
                    root.chmod(0o700)
                    audit: list[str] = []
                    clients: list[WaitingChildClient] = []
                    service = ChildSessionService(
                        plan=_plan(root),
                        authority=_child_envelope(),
                        control_factories=_registry(audit, clients, terminal=terminal),
                        private_root=root,
                        content=RecordingResolver(),
                        child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                        clock_ms=lambda: 1_000,
                    )
                    with self.assertRaises(ActionExecutionFailure) as raised:
                        await service.spawn(_child_proposal(), MutableSignal())
                    self.assertEqual((raised.exception.status, raised.exception.reason_code), (status, reason))
                    self.assertEqual(audit.count("child.executor"), 1)

    async def test_duplicate_equal_spawn_is_idempotent_and_conflicting_duplicate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            proposal = _child_proposal()

            first = await service.spawn(proposal, MutableSignal())
            second = await service.spawn(proposal, MutableSignal())

            self.assertEqual(first, second)
            self.assertEqual(audit.count("child.provider.create"), 1)
            with self.assertRaises(ChildSessionError):
                await service.spawn(_child_proposal(input_ref="other-goal-ref"), MutableSignal())

    async def test_concurrent_spawn_limit_is_enforced_before_second_provider_create(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []

            class BlockingExecutor(ChildWorkExecutor):
                async def execute(
                    self, proposal: ControlEvent, signal: CancellationSignal
                ) -> ActionExecutionReceipt:
                    await asyncio.sleep(0.05)
                    return await super().execute(proposal, signal)

            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: BlockingExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            first = asyncio.create_task(service.spawn(_child_proposal(), MutableSignal()))
            await asyncio.sleep(0)
            with self.assertRaises(ChildSessionError):
                await service.spawn(_child_proposal(action_id="spawn-action-2", child_id="child-2"), MutableSignal())
            await first

            self.assertEqual(audit.count("child.provider.create"), 1)

    async def test_message_and_cancel_require_exact_active_child_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []

            class BlockingExecutor(ChildWorkExecutor):
                async def execute(
                    self, proposal: ControlEvent, signal: CancellationSignal
                ) -> ActionExecutionReceipt:
                    await asyncio.sleep(0.05)
                    return await super().execute(proposal, signal)

            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: BlockingExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            spawn = asyncio.create_task(service.spawn(_child_proposal(), MutableSignal()))
            while not clients:
                await asyncio.sleep(0)
            message = _child_proposal(
                action_id="message-action-1",
                budget={
                    "controller_tokens": 0,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": 0,
                    "cost_micros": 0,
                    "deadline_ms": 1000,
                },
            )
            message = ControlEvent.from_mapping(
                {
                    **message.to_mapping(),
                    "payload": {
                        **message.payload,
                        "expected_artifacts": [],
                        "causal_parent_ids": ["goal-1"],
                        "kind": "child.message",
                        "target": {"kind": "child", "child_id": "child-1"},
                    },
                }
            )
            receipt = await service.message(message, MutableSignal())
            self.assertEqual(receipt.usage, BudgetUsage.zero())
            self.assertEqual(clients[0].messages, ["message-action-1"])

            wrong = ControlEvent.from_mapping(
                {
                    **message.to_mapping(),
                    "payload": {
                        **message.payload,
                        "expected_artifacts": [],
                        "causal_parent_ids": ["goal-1"],
                        "action_id": "message-action-2",
                        "idempotency_key": "idem-message-action-2",
                        "target": {"kind": "child", "child_id": "missing-child"},
                    },
                }
            )
            with self.assertRaises(ChildSessionError):
                await service.message(wrong, MutableSignal())
            await service.cancel(_cancel_proposal("child-1"), MutableSignal())
            self.assertTrue(clients[0].cancelled)
            with self.assertRaises(ActionExecutionFailure) as raised:
                await spawn
            self.assertEqual(raised.exception.status, "cancelled")

    async def test_cancel_all_precedes_close_and_close_failure_retains_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []

            class BlockingExecutor(ChildWorkExecutor):
                async def execute(
                    self, proposal: ControlEvent, signal: CancellationSignal
                ) -> ActionExecutionReceipt:
                    await asyncio.sleep(0.05)
                    return await super().execute(proposal, signal)

            service = ChildSessionService(
                plan=_plan(root),
                authority=replace(_child_envelope(), max_concurrent_children=2),
                control_factories=_registry(audit, clients, close_fails=True),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: BlockingExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            task = asyncio.create_task(service.spawn(_child_proposal(), MutableSignal()))
            while not clients:
                await asyncio.sleep(0)

            with self.assertRaises(ChildSessionError):
                await service.close()

            self.assertIn("child-1", service.active_ids)
            clients[0].close_fails = False
            await service.close()
            with self.assertRaises(ActionExecutionFailure) as raised:
                await task
            self.assertEqual(raised.exception.status, "cancelled")
            self.assertTrue(clients[0].closed)
            self.assertLess(audit.index("child.command.session.cancel"), audit.index("child.close"))
            self.assertEqual(audit.count("child.command.session.cancel"), 1)

    def test_root_safety_rejects_symlink_wrong_mode_and_conflicting_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "children").mkdir()
            os.symlink(root, root / "children" / "child-1")
            with self.assertRaises(ChildSessionError):
                ChildSessionService.prepare_child_root(root, "child-1")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_root = root / "children" / "child-1"
            child_root.mkdir(parents=True, mode=0o755)
            child_root.chmod(0o755)
            with self.assertRaises(ChildSessionError):
                ChildSessionService.prepare_child_root(root, "child-1")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_root = ChildSessionService.prepare_child_root(root, "child-1")
            ChildSessionService.persist_binding(
                child_root=child_root,
                child_id="child-1",
                action_id="action-1",
                session_id="session-a",
                authority_id="child:child-1",
                generation=1,
                proposal_digest="a" * 64,
            )
            with self.assertRaises(ChildSessionError):
                ChildSessionService.persist_binding(
                    child_root=child_root,
                    child_id="child-1",
                    action_id="action-2",
                    session_id="session-b",
                    authority_id="child:child-1",
                    generation=1,
                    proposal_digest="b" * 64,
                )

    async def test_reopen_adopts_exact_binding_and_file_journal_without_reexecuting_completed_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            service = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            proposal = _child_proposal()

            first = await service.spawn(proposal, MutableSignal())
            reopened = ChildSessionService(
                plan=_plan(root),
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            second = await reopened.spawn(proposal, MutableSignal())

            self.assertEqual(first, second)
            self.assertEqual(audit.count("child.provider.create"), 1)
            self.assertEqual(audit.count("child.executor"), 1)
            journal = FileCanonicalJournal.open(root / "children" / "child-1", "child-session-child-1")
            self.assertGreater(journal.position, 0)


class TestManagerChildIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_hostile_active_ids_fails_admission_without_leaking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)

            class HostileChildren:
                @property
                def active_ids(self):
                    raise RuntimeError(SENTINEL)

                async def cancel_all(self) -> None:
                    return None

                async def close(self) -> None:
                    return None

            proposal = ControlEvent.from_mapping(
                {**_child_proposal().to_mapping(), "sequence": 3, "event_id": "hostile-event"}
            )
            host = ControlHost(
                session_id="session-1", generation=1, plan=plan,
                authority=AuthorityLedger(_child_envelope()),
                journal=FileCanonicalJournal.open(root / "parent", "session-1"),
                client=ScriptedClient(plan.control_binding.manifest, _session_events(proposal)),
                action_executor=ChildWorkExecutor([]), clock_ms=lambda: 1_000,
                child_service=HostileChildren(),
            )
            with self.assertRaises(ControlHostError) as raised:
                await host.pump()
            self.assertEqual(str(raised.exception), "control child lifecycle is unavailable")
            self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_child_model_work_starts_only_after_parent_admission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []
            children = ChildSessionService(
                plan=plan,
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            executor, _, _, _ = _application_executor(
                root,
                audit=audit,
                child_service=children,
            )
            parent_proposal = ControlEvent.from_mapping(
                {**_child_proposal().to_mapping(), "sequence": 3, "event_id": "parent-event-3"}
            )
            client = ScriptedClient(
                plan.control_binding.manifest,
                _session_events(parent_proposal),
                audit=audit,
            )
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_child_envelope()),
                journal=FileCanonicalJournal.open(root / "parent", "session-1"),
                client=client,
                action_executor=executor,
                clock_ms=lambda: 1_000,
                child_service=children,
            )
            await host.dispatch(_create_command())
            audit.append("parent.provider.admitted")

            await host.pump()

            self.assertLess(audit.index("parent.provider.admitted"), audit.index("child.provider.create"))
            self.assertEqual(children.active_ids, ())
            self.assertGreater(host.snapshot().authority_usage.child_tokens, 0)

    async def test_parent_cancel_cascades_to_active_children_before_provider_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            audit: list[str] = []
            clients: list[WaitingChildClient] = []

            class BlockingExecutor(ChildWorkExecutor):
                async def execute(
                    self, proposal: ControlEvent, signal: CancellationSignal
                ) -> ActionExecutionReceipt:
                    await asyncio.sleep(0.05)
                    return await super().execute(proposal, signal)

            children = ChildSessionService(
                plan=plan,
                authority=_child_envelope(),
                control_factories=_registry(audit, clients),
                private_root=root,
                content=RecordingResolver(),
                child_action_executor_factory=lambda authority: BlockingExecutor(audit),
                clock_ms=lambda: 1_000,
            )
            task = asyncio.create_task(children.spawn(_child_proposal(), MutableSignal()))
            while not clients:
                await asyncio.sleep(0)
            client = ScriptedClient(plan.control_binding.manifest, audit=audit)
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_child_envelope()),
                journal=FileCanonicalJournal.open(root / "parent", "session-1"),
                client=client,
                action_executor=ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
                child_service=children,
            )

            await host.dispatch(
                ControlCommand(
                    command_id="parent-cancel-1",
                    session_id="session-1",
                    authority_revision=1,
                    type="session.cancel",
                    payload={"reason_code": "operator-cancelled"},
                )
            )
            with self.assertRaises(ActionExecutionFailure):
                await task

            await host.close()

            self.assertLess(audit.index("child.command.session.cancel"), audit.index("child.close"))
            self.assertLess(audit.index("child.close"), audit.index("provider.send"))
            self.assertLess(audit.index("child.close"), audit.index("provider.close"))

    async def test_child_close_failure_prevents_parent_cancel_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            audit: list[str] = []

            class FailingChildren:
                active_ids = ()

                async def cancel_all(self) -> None:
                    audit.append("child.cancel-all")

                async def close(self) -> None:
                    audit.append("child.close")
                    raise RuntimeError(SENTINEL)

            client = ScriptedClient(plan.control_binding.manifest, audit=audit)
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_child_envelope()),
                journal=FileCanonicalJournal.open(root / "parent", "session-1"),
                client=client,
                action_executor=ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
                child_service=FailingChildren(),
            )

            with self.assertRaisesRegex(
                ControlHostError, "control child cascade is unavailable"
            ) as raised:
                await host.dispatch(
                    ControlCommand(
                        command_id="parent-cancel-1",
                        session_id="session-1",
                        authority_revision=1,
                        type="session.cancel",
                        payload={"reason_code": "operator-cancelled"},
                    )
                )

            self.assertEqual(client.sent, [])
            self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_active_children_rejects_a_child_spawn_at_the_concurrency_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            audit: list[str] = []

            class ActiveChildren:
                active_ids = ("child-1",)

                async def cancel_all(self) -> None:
                    return None

                async def close(self) -> None:
                    return None

            proposal = ControlEvent.from_mapping(
                {**_child_proposal().to_mapping(), "sequence": 3, "event_id": "parent-event-3"}
            )
            client = ScriptedClient(
                plan.control_binding.manifest,
                _session_events(proposal),
                audit=audit,
            )
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_child_envelope()),
                journal=FileCanonicalJournal.open(root / "parent", "session-1"),
                client=client,
                action_executor=ChildWorkExecutor(audit),
                clock_ms=lambda: 1_000,
                child_service=ActiveChildren(),
            )

            await host.pump()

            resolution = next(
                command for command in client.sent if command.type == "action.resolve"
            )
            self.assertEqual(resolution.payload["resolution"], "rejected")
            self.assertEqual(resolution.payload["reason_code"], "child-concurrency-exceeded")


def _cancel_proposal(child_id: str) -> ControlEvent:
    proposal = _child_proposal(
        action_id="cancel-action-1",
        budget={
            "controller_tokens": 0,
            "application_tokens": 0,
            "child_tokens": 0,
            "aggregate_tokens": 0,
            "cost_micros": 0,
            "deadline_ms": 1000,
        },
    )
    return ControlEvent.from_mapping(
        {
            **proposal.to_mapping(),
            "payload": {
                **proposal.payload,
                "expected_artifacts": [],
                "causal_parent_ids": ["goal-1"],
                "kind": "child.cancel",
                "target": {"kind": "child", "child_id": child_id},
            },
        }
    )


def _child_message_proposal() -> ControlEvent:
    proposal = _cancel_proposal("child-1")
    return ControlEvent.from_mapping(
        {
            **proposal.to_mapping(),
            "payload": {
                **proposal.payload,
                "action_id": "message-action-1",
                "idempotency_key": "message-idempotency-1",
                "kind": "child.message",
                "input_ref": "goal-ref-1",
                "expected_artifacts": [],
                "causal_parent_ids": ["goal-1"],
            },
        }
    )


if __name__ == "__main__":
    unittest.main()
