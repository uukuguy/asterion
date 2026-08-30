from __future__ import annotations

import json
import traceback
import unittest
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import cast

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlCommand, EventCursor
from asterion.control.providers.native.capsule import MemoryNativeCapsuleStore
from asterion.control.providers.native.controller import (
    NativeController,
    NativeControllerError,
)
from asterion.control.providers.native.model import (
    NativeCapsuleMetadata,
    NativeEntry,
    NativeEventDraft,
    NativeRecord,
    NativeTurnRequest,
    NativeTurnResult,
)
from asterion.control.providers.native.state import (
    reduce_native_entries,
    session_bound_record,
)
from asterion.control.providers.native.store import (
    MemoryNativeSessionStore,
    MemoryNativeStorageOwner,
    NativeStoreError,
    NativeStorageOwner,
)
from asterion.control.providers.native.turn import (
    DeterministicNativeTurnAdapter,
    NativeTurnAdapter,
    NativeTurnError,
    _turn_script_key,
)


SESSION_ID = "session-1"
GENERATION = 1
AUTHORITY_REVISION = 1
EMITTED_AT = "2026-08-30T00:00:00Z"


def _budget(**overrides: int) -> RemainingBudget:
    values = {
        "controller_tokens": 100,
        "application_tokens": 0,
        "child_tokens": 0,
        "aggregate_tokens": 100,
        "cost_micros": 10_000,
        "deadline_ms": 60_000,
    }
    values.update(overrides)
    return RemainingBudget(**values)


def _usage(**overrides: int) -> BudgetUsage:
    values = {
        "controller_tokens": 0,
        "application_tokens": 0,
        "child_tokens": 0,
        "aggregate_tokens": 0,
        "cost_micros": 0,
    }
    values.update(overrides)
    return BudgetUsage(**values)


def _command(
    command_id: str,
    command_type: str,
    payload: Mapping[str, object],
    *,
    authority_revision: int = AUTHORITY_REVISION,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id=SESSION_ID,
        authority_revision=authority_revision,
        type=command_type,
        payload=payload,
    )


def create_command(command_id: str = "command-create") -> ControlCommand:
    return _command(
        command_id,
        "session.create",
        {
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def input_command(
    command_id: str = "command-input-1",
    content_ref: str = "content-ref-1",
    *,
    input_id: str = "input-1",
    delivery: str = "direct",
) -> ControlCommand:
    return _command(
        command_id,
        "input.submit",
        {
            "input_id": input_id,
            "delivery": delivery,
            "content_ref": content_ref,
        },
    )


def lifecycle_command(command_id: str, command_type: str, reason: str) -> ControlCommand:
    return _command(command_id, command_type, {"reason_code": reason})


def attach_command(command_id: str, sequence: int = 0) -> ControlCommand:
    return _command(
        command_id,
        "session.attach",
        {"cursor": {"generation": GENERATION, "sequence": sequence}},
    )


def checkpoint_command(command_id: str, checkpoint_id: str) -> ControlCommand:
    return _command(command_id, "checkpoint.request", {"checkpoint_id": checkpoint_id})


def action_resolution_command(
    command_id: str,
    resolution: str,
    *,
    action_id: str = "action-1",
    reason_code: str = "ok",
    receipt_ref: str | None = None,
) -> ControlCommand:
    return _command(
        command_id,
        "action.resolve",
        {
            "action_id": action_id,
            "resolution": resolution,
            "reason_code": reason_code,
            "receipt_ref": receipt_ref,
        },
    )


def terminal_resolution_command(
    action_id: str = "action-1",
    receipt_ref: str = "receipt-1",
) -> ControlCommand:
    return action_resolution_command(
        "command-action-terminal",
        "succeeded",
        action_id=action_id,
        receipt_ref=receipt_ref,
    )


def proposal_draft(action_id: str = "action-1") -> NativeEventDraft:
    return NativeEventDraft(
        "action.proposed",
        {
            "action_id": action_id,
            "authority_revision": AUTHORITY_REVISION,
            "idempotency_key": f"idempotency-{action_id}",
            "kind": "application.invoke",
            "target": {
                "kind": "application",
                "provider_id": "example.provider",
                "application_id": "alpha",
                "version": "1.0.0",
                "runtime_id": "fake.runtime",
            },
            "input_ref": "input-ref-1",
            "expected_artifacts": ("report.alpha", "report.zeta"),
            "budget": {
                "controller_tokens": 0,
                "application_tokens": 10,
                "child_tokens": 0,
                "aggregate_tokens": 10,
                "cost_micros": 500,
                "deadline_ms": 10_000,
            },
            "causal_parent_ids": ("goal-1", "task-1"),
        },
    )


class SequenceFactory:
    def __init__(self, values: Iterable[str]) -> None:
        self._values = list(values)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if not self._values:
            return f"generated-{self.calls}"
        return self._values.pop(0)


class FixedClock:
    def __init__(self, value: str = EMITTED_AT) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.value


class HostileControlCommand(ControlCommand):
    mapping_calls: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping_calls", 0)

    def to_mapping(self) -> Mapping[str, object]:
        object.__setattr__(self, "mapping_calls", self.mapping_calls + 1)
        raise AssertionError("SENTINEL_SECRET")


class HostileEventCursor(EventCursor):
    attribute_reads: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "attribute_reads", 0)

    def __getattribute__(self, name: str) -> object:
        if name in {"generation", "sequence"}:
            object.__setattr__(
                self,
                "attribute_reads",
                object.__getattribute__(self, "attribute_reads") + 1,
            )
            raise AssertionError("SENTINEL_SECRET")
        return super().__getattribute__(name)


class HostileTurnRequest(NativeTurnRequest):
    comparisons: int
    attribute_reads: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "comparisons", 0)
        object.__setattr__(self, "attribute_reads", 0)

    def __eq__(self, other: object) -> bool:
        object.__setattr__(self, "comparisons", self.comparisons + 1)
        raise AssertionError("SENTINEL_SECRET")

    def __getattribute__(self, name: str) -> object:
        if name in {
            "turn_id",
            "session_id",
            "generation",
            "authority_revision",
            "causal_command_ids",
            "inputs",
            "action_results",
            "budget",
        }:
            object.__setattr__(
                self,
                "attribute_reads",
                object.__getattribute__(self, "attribute_reads") + 1,
            )
            raise AssertionError("SENTINEL_SECRET")
        return super().__getattribute__(name)


class HostileTurnResult(NativeTurnResult):
    attribute_reads: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "attribute_reads", 0)

    def __getattribute__(self, name: str) -> object:
        if name in {"turn_id", "events", "usage"}:
            object.__setattr__(
                self,
                "attribute_reads",
                object.__getattribute__(self, "attribute_reads") + 1,
            )
            raise AssertionError("SENTINEL_SECRET")
        return super().__getattribute__(name)


class HostileRemainingBudget(RemainingBudget):
    attribute_reads: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "attribute_reads", 0)

    def __getattribute__(self, name: str) -> object:
        if name in {
            "controller_tokens",
            "application_tokens",
            "child_tokens",
            "aggregate_tokens",
            "cost_micros",
            "deadline_ms",
        }:
            object.__setattr__(
                self,
                "attribute_reads",
                object.__getattribute__(self, "attribute_reads") + 1,
            )
            raise AssertionError("SENTINEL_SECRET")
        return super().__getattribute__(name)


class CountingAdapter:
    adapter_id = "native.counting-turn/v1"

    def __init__(self, result: NativeTurnResult | BaseException) -> None:
        self.result = result
        self.calls = 0

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        if self.result.turn_id == "copy-request-turn":
            return replace(self.result, turn_id=request.turn_id)
        return self.result


class TrackingSessionStore(MemoryNativeSessionStore):
    def __init__(self, owner: MemoryNativeStorageOwner, close_order: list[str]) -> None:
        super().__init__(owner, max_record_bytes=65_536)
        self.close_order = close_order

    def close(self) -> None:
        self.close_order.append("journal")
        super().close()


class FailOnceTrackingSessionStore(TrackingSessionStore):
    def __init__(
        self,
        owner: MemoryNativeStorageOwner,
        close_order: list[str],
        failing_kind: str,
    ) -> None:
        super().__init__(owner, close_order)
        self.failing_kind = failing_kind
        self.failures_remaining = 1

    def append(self, expected_position: int, record: NativeRecord) -> NativeEntry:
        if record.kind == self.failing_kind and self.failures_remaining:
            self.failures_remaining -= 1
            raise NativeStoreError
        return super().append(expected_position, record)


class TrackingCapsuleStore(MemoryNativeCapsuleStore):
    def __init__(self, owner: MemoryNativeStorageOwner, close_order: list[str]) -> None:
        super().__init__(owner, max_capsule_bytes=65_536)
        self.close_order = close_order
        self.sealed_payloads: dict[str, bytes] = {}

    def seal(
        self,
        *,
        capsule_id: str,
        payload: bytes,
        covered_position: int,
        covered_sequence: int,
    ) -> NativeCapsuleMetadata:
        metadata = super().seal(
            capsule_id=capsule_id,
            payload=payload,
            covered_position=covered_position,
            covered_sequence=covered_sequence,
        )
        self.sealed_payloads[capsule_id] = payload
        return metadata

    def close(self) -> None:
        self.close_order.append("capsule")
        super().close()


class ControllerFixture:
    def __init__(
        self,
        *,
        adapter: NativeTurnAdapter | None = None,
        event_ids: Iterable[str] = (
            "event-created",
            "event-running",
            "event-budget",
            "event-action",
            "event-fault",
            "event-recovery",
            "event-terminal",
            "event-checkpoint",
        ),
        turn_ids: Iterable[str] = ("turn-1", "turn-2", "turn-3"),
        capsule_ids: Iterable[str] = ("capsule-1", "capsule-2"),
        store_factory: Callable[
            [MemoryNativeStorageOwner, list[str]], TrackingSessionStore
        ] = TrackingSessionStore,
    ) -> None:
        self.close_order: list[str] = []
        self.owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        original_close = self.owner.close

        def tracked_close() -> None:
            self.close_order.append("owner")
            original_close()

        self.owner.close = tracked_close  # type: ignore[method-assign]
        self.store = store_factory(self.owner, self.close_order)
        self.capsules = TrackingCapsuleStore(self.owner, self.close_order)
        self.event_factory = SequenceFactory(event_ids)
        self.turn_factory = SequenceFactory(turn_ids)
        self.capsule_factory = SequenceFactory(capsule_ids)
        self.clock = FixedClock()
        self.adapter: NativeTurnAdapter = adapter if adapter is not None else CountingAdapter(
            NativeTurnResult("copy-request-turn", (), _usage())
        )
        self.controller = NativeController(
            owner=self.owner,
            session_store=self.store,
            capsule_store=self.capsules,
            turn_adapter=self.adapter,
            provider_id="native",
            provider_version="0.1.0",
            system_id="research.system",
            system_version="1.0.0",
            session_id=SESSION_ID,
            generation=GENERATION,
            checkpoint_version="1.0.0",
            authority_id="authority-1",
            authority_revision=AUTHORITY_REVISION,
            event_id_factory=self.event_factory,
            turn_id_factory=self.turn_factory,
            capsule_id_factory=self.capsule_factory,
            clock=self.clock,
        )

    async def create(self, budget: RemainingBudget | None = None) -> None:
        await self.controller.accept(create_command())
        self.controller.sync_authority(budget or _budget())

    def reopen(self) -> NativeController:
        return NativeController(
            owner=self.owner,
            session_store=self.store,
            capsule_store=self.capsules,
            turn_adapter=self.adapter,
            provider_id="native",
            provider_version="0.1.0",
            system_id="research.system",
            system_version="1.0.0",
            session_id=SESSION_ID,
            generation=GENERATION,
            checkpoint_version="1.0.0",
            authority_id="authority-1",
            authority_revision=AUTHORITY_REVISION,
            event_id_factory=self.event_factory,
            turn_id_factory=self.turn_factory,
            capsule_id_factory=self.capsule_factory,
            clock=self.clock,
        )


class TestNativeControlController(unittest.IsolatedAsyncioTestCase):
    async def test_create_emits_exact_created_and_running_once_and_duplicate_is_idempotent(
        self,
    ) -> None:
        fixture = ControllerFixture()
        controller = fixture.controller

        await controller.accept(create_command())
        await controller.accept(create_command())
        with self.assertRaises(NativeControllerError):
            await controller.accept(
                replace(
                    create_command(),
                    payload={**create_command().payload, "goal_id": "goal-2"},
                )
            )

        state = controller.state
        self.assertEqual(state.lifecycle, "running")
        self.assertEqual(state.goal_status, "active")
        self.assertEqual([event.type for event in state.events], ["session.created", "session.running"])
        self.assertNotIn("goal.updated", [event.type for event in state.events])
        self.assertEqual(fixture.store.position, 2)

    async def test_partial_first_create_retries_missing_command_without_duplicate_bound(
        self,
    ) -> None:
        fixture = ControllerFixture(
            store_factory=lambda owner, order: FailOnceTrackingSessionStore(
                owner,
                order,
                "command.committed",
            )
        )
        with self.assertRaises(NativeStoreError):
            await fixture.controller.accept(create_command())
        self.assertEqual(fixture.store.position, 1)
        self.assertEqual(fixture.controller.state.lifecycle, "bound")

        reopened = fixture.reopen()
        with self.assertRaises(NativeControllerError):
            await reopened.accept(input_command("command-not-create", "content-ref-x"))
        await reopened.accept(create_command())

        state = reopened.state
        self.assertEqual(fixture.store.position, 2)
        self.assertEqual([entry.record.kind for entry in fixture.store.replay()], ["session.bound", "command.committed"])
        self.assertEqual([event.sequence for event in state.events], [1, 2])
        self.assertEqual([event.type for event in state.events], ["session.created", "session.running"])

    async def test_partial_first_create_mismatch_matrix_fails_closed(self) -> None:
        cases = (
            (
                "controller-system",
                {"system_id": "other.system", "system_version": "1.0.0"},
                {"system_id": "research.system", "system_version": "1.0.0"},
            ),
            (
                "command-system-version",
                {"system_id": "research.system", "system_version": "1.0.0"},
                {"system_id": "research.system", "system_version": "2.0.0"},
            ),
        )
        for label, bound_ids, command_ids in cases:
            with self.subTest(label=label):
                fixture = ControllerFixture()
                fixture.store.append(
                    0,
                    session_bound_record(
                        provider_id="native",
                        provider_version="0.1.0",
                        system_id=str(bound_ids["system_id"]),
                        system_version=str(bound_ids["system_version"]),
                        session_id=SESSION_ID,
                        generation=GENERATION,
                        checkpoint_version="1.0.0",
                        authority_id="authority-1",
                        authority_revision=AUTHORITY_REVISION,
                        initial_create_command=replace(
                            create_command(),
                            payload={
                                **create_command().payload,
                                "system_id": bound_ids["system_id"],
                                "system_version": bound_ids["system_version"],
                            },
                        ),
                    ),
                )
                if label == "controller-system":
                    with self.assertRaises(NativeControllerError):
                        NativeController(
                            owner=fixture.owner,
                            session_store=fixture.store,
                            capsule_store=fixture.capsules,
                            turn_adapter=fixture.adapter,
                            provider_id="native",
                            provider_version="0.1.0",
                            system_id="research.system",
                            system_version="1.0.0",
                            session_id=SESSION_ID,
                            generation=GENERATION,
                            checkpoint_version="1.0.0",
                            authority_id="authority-1",
                            authority_revision=AUTHORITY_REVISION,
                            event_id_factory=fixture.event_factory,
                            turn_id_factory=fixture.turn_factory,
                            capsule_id_factory=fixture.capsule_factory,
                            clock=fixture.clock,
                        )
                    continue
                matching = NativeController(
                    owner=fixture.owner,
                    session_store=fixture.store,
                    capsule_store=fixture.capsules,
                    turn_adapter=fixture.adapter,
                    provider_id="native",
                    provider_version="0.1.0",
                    system_id="research.system",
                    system_version="1.0.0",
                    session_id=SESSION_ID,
                    generation=GENERATION,
                    checkpoint_version="1.0.0",
                    authority_id="authority-1",
                    authority_revision=AUTHORITY_REVISION,
                    event_id_factory=fixture.event_factory,
                    turn_id_factory=fixture.turn_factory,
                    capsule_id_factory=fixture.capsule_factory,
                    clock=fixture.clock,
                )
                bad = replace(
                    create_command(),
                    payload={**create_command().payload, **command_ids},
                )
                with self.assertRaises(NativeControllerError):
                    await matching.accept(bad)
                with self.assertRaises(NativeControllerError):
                    await matching.accept(input_command("command-not-create", "ref"))

    async def test_partial_first_create_binds_original_command_identity_before_retry(
        self,
    ) -> None:
        for label, command in (
            ("command-id", create_command("command-create-drift")),
            (
                "goal-id",
                replace(
                    create_command(),
                    payload={**create_command().payload, "goal_id": "goal-2"},
                ),
            ),
            (
                "goal-ref",
                replace(
                    create_command(),
                    payload={**create_command().payload, "goal_ref": "goal-ref-2"},
                ),
            ),
            ("authority", replace(create_command(), authority_revision=2)),
        ):
            with self.subTest(label=label):
                fixture = ControllerFixture(
                    store_factory=lambda owner, order: FailOnceTrackingSessionStore(
                        owner,
                        order,
                        "command.committed",
                    )
                )
                with self.assertRaises(NativeStoreError):
                    await fixture.controller.accept(create_command())
                before = fixture.store.position

                reopened = fixture.reopen()
                with self.assertRaises(NativeControllerError):
                    await reopened.accept(command)
                self.assertEqual(fixture.store.position, before)
                self.assertEqual(reopened.state.command_digests, {})

                await reopened.accept(create_command())
                self.assertEqual(fixture.store.position, before + 1)
                await reopened.accept(create_command())
                self.assertEqual(fixture.store.position, before + 1)

    async def test_turn_commits_result_and_events_before_replay(self) -> None:
        adapter = CountingAdapter(
            NativeTurnResult(
                "copy-request-turn",
                (
                    NativeEventDraft(
                        "budget.reported",
                        {
                            "controller_tokens": 3,
                            "application_tokens": 0,
                            "child_tokens": 0,
                            "aggregate_tokens": 3,
                            "cost_micros": 0,
                        },
                    ),
                    proposal_draft(),
                ),
                _usage(controller_tokens=3, aggregate_tokens=3),
            )
        )
        fixture = ControllerFixture(adapter=adapter)
        controller = fixture.controller
        await fixture.create()
        await controller.accept(input_command())

        request = controller.begin_ready_turn()
        self.assertIsNotNone(request)
        assert request is not None
        result = await controller.execute_turn(request)
        controller.commit_turn(request, result)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(request.inputs[0].content_ref, "content-ref-1")
        events = controller.replay_events(EventCursor(1, 2))
        self.assertEqual(
            [event.type for event in events],
            ["budget.reported", "action.proposed"],
        )
        self.assertEqual(controller.state.action_statuses["action-1"], "proposed")

    async def test_deterministic_adapter_uses_journal_ordered_turn_keys_and_redacts_refs(
        self,
    ) -> None:
        fixture = ControllerFixture()
        await fixture.create()
        await fixture.controller.accept(input_command("command-input-2", "content-ref-2"))
        request = fixture.controller.begin_ready_turn()
        self.assertIsNotNone(request)
        assert request is not None
        result = NativeTurnResult(request.turn_id, (), _usage())
        adapter = DeterministicNativeTurnAdapter({"input:content-ref-2": result})

        self.assertEqual(_turn_script_key(request), "input:content-ref-2")
        self.assertEqual(await adapter.execute(request), result)
        self.assertNotIn("content-ref-2", repr(request))
        self.assertNotIn("content-ref-2", repr(request.inputs[0]))
        with self.assertRaises(NativeTurnError):
            await DeterministicNativeTurnAdapter({}).execute(request)
        with self.assertRaises(NativeTurnError):
            _turn_script_key(replace(request, inputs=(), action_results=()))

    async def test_turn_adapter_rejects_hostile_subclasses_before_reads(self) -> None:
        request = NativeTurnRequest(
            turn_id="turn-hostile",
            session_id=SESSION_ID,
            generation=GENERATION,
            authority_revision=AUTHORITY_REVISION,
            causal_command_ids=(),
            inputs=(),
            action_results=(),
            budget=_budget(),
        )
        hostile_request = HostileTurnRequest(
            turn_id=request.turn_id,
            session_id=request.session_id,
            generation=request.generation,
            authority_revision=request.authority_revision,
            causal_command_ids=request.causal_command_ids,
            inputs=request.inputs,
            action_results=request.action_results,
            budget=request.budget,
        )
        hostile_result = HostileTurnResult("turn-hostile", (), _usage())

        with self.assertRaises(NativeTurnError) as script_error:
            DeterministicNativeTurnAdapter({"input:content-ref": hostile_result})
        self.assertEqual(hostile_result.attribute_reads, 0)
        self.assertIsNone(script_error.exception.__context__)
        self.assertNotIn("SENTINEL_SECRET", str(script_error.exception))

        adapter = DeterministicNativeTurnAdapter({"input:content-ref": NativeTurnResult("turn-hostile", (), _usage())})
        with self.assertRaises(NativeTurnError) as key_error:
            _turn_script_key(hostile_request)
        self.assertEqual(hostile_request.attribute_reads, 0)
        self.assertIsNone(key_error.exception.__context__)
        with self.assertRaises(NativeTurnError):
            await adapter.execute(hostile_request)
        self.assertEqual(hostile_request.attribute_reads, 0)

    async def test_action_cannot_advance_without_host_terminal_resolution(self) -> None:
        fixture = ControllerFixture(
            adapter=CountingAdapter(
                NativeTurnResult("copy-request-turn", (proposal_draft(),), _usage())
            )
        )
        await fixture.create()
        await fixture.controller.accept(input_command())
        request = fixture.controller.begin_ready_turn()
        assert request is not None
        fixture.controller.commit_turn(request, await fixture.controller.execute_turn(request))

        self.assertIsNone(fixture.controller.begin_ready_turn())
        await fixture.controller.accept(
            action_resolution_command("command-action-admitted", "admitted")
        )
        self.assertIsNone(fixture.controller.begin_ready_turn())

    async def test_terminal_host_resolution_becomes_next_durable_turn_input(self) -> None:
        fixture = ControllerFixture(
            adapter=CountingAdapter(
                NativeTurnResult("copy-request-turn", (proposal_draft(),), _usage())
            ),
            turn_ids=("turn-propose", "turn-resolved"),
        )
        await fixture.create()
        await fixture.controller.accept(input_command())
        request = fixture.controller.begin_ready_turn()
        assert request is not None
        fixture.controller.commit_turn(request, await fixture.controller.execute_turn(request))

        await fixture.controller.accept(terminal_resolution_command("action-1", "receipt-1"))
        next_request = fixture.controller.begin_ready_turn()
        self.assertIsNotNone(next_request)
        assert next_request is not None
        self.assertEqual(next_request.action_results[0].receipt_ref, "receipt-1")
        self.assertEqual(_turn_script_key(next_request), "action:action-1:succeeded")

    async def test_pause_resume_detach_attach_and_cancel_legality_matrix(self) -> None:
        fixture = ControllerFixture()
        controller = fixture.controller
        await fixture.create()

        await controller.accept(lifecycle_command("command-pause", "session.pause", "operator-request"))
        self.assertEqual(controller.state.lifecycle, "paused")
        self.assertIsNone(controller.begin_ready_turn())
        await controller.accept(lifecycle_command("command-resume", "session.resume", "operator-return"))
        self.assertEqual(controller.state.lifecycle, "running")
        await controller.accept(attach_command("command-attach", sequence=2))
        await controller.accept(lifecycle_command("command-detach", "session.detach", "operator-away"))
        self.assertEqual(controller.state.lifecycle, "running")

        await controller.accept(input_command("command-input-cancel", "content-ref-cancel"))
        started = controller.begin_ready_turn()
        self.assertIsNotNone(started)
        assert started is not None
        await controller.accept(lifecycle_command("command-cancel", "session.cancel", "operator-cancel"))
        self.assertEqual(controller.state.lifecycle, "cancelled")
        self.assertIn(started.turn_id, controller.state.fenced_turn_ids)
        with self.assertRaises(NativeControllerError):
            controller.commit_turn(started, NativeTurnResult(started.turn_id, (), _usage()))
        with self.assertRaises(NativeControllerError):
            await controller.accept(input_command("command-after-cancel", "content-ref-after"))

    async def test_budget_limited_path_never_invokes_adapter_and_is_unique(self) -> None:
        adapter = CountingAdapter(NativeTurnResult("copy-request-turn", (), _usage()))
        fixture = ControllerFixture(adapter=adapter)
        await fixture.create(_budget(controller_tokens=0, aggregate_tokens=0))
        await fixture.controller.accept(input_command())

        request = fixture.controller.begin_ready_turn()
        self.assertIsNotNone(request)
        assert request is not None
        self.assertTrue(fixture.controller.turn_is_budget_limited(request))
        fixture.controller.commit_budget_limited_turn(request)
        with self.assertRaises(NativeControllerError):
            fixture.controller.commit_budget_limited_turn(request)

        self.assertEqual(adapter.calls, 0)
        self.assertEqual(
            [event.type for event in fixture.controller.state.events[-2:]],
            ["budget.reported", "session.budget-limited"],
        )
        self.assertFalse(fixture.store.replay()[-1].record.payload["adapter_invoked"])

    async def test_invalid_over_budget_and_exception_results_fence_through_recovery_only(
        self,
    ) -> None:
        cases = (
            (
                "wrong-turn",
                NativeTurnResult("other-turn", (), _usage()),
                "native-turn-result-invalid",
            ),
            (
                "over-budget",
                NativeTurnResult(
                    "copy-request-turn",
                    (),
                    _usage(controller_tokens=101, aggregate_tokens=101),
                ),
                "native-turn-result-invalid",
            ),
            ("exception", NativeControllerError("SENTINEL_SECRET"), "native-turn-failed"),
        )
        for label, adapter_result, reason_code in cases:
            with self.subTest(label=label):
                fixture = ControllerFixture(adapter=CountingAdapter(adapter_result))
                await fixture.create()
                await fixture.controller.accept(input_command(f"command-input-{label}", f"content-ref-{label}"))
                request = fixture.controller.begin_ready_turn()
                assert request is not None

                try:
                    result = await fixture.controller.execute_turn(request)
                    fixture.controller.commit_turn(request, result)
                except NativeControllerError:
                    fixture.controller.fail_turn(request, reason_code)

                event_types = [event.type for event in fixture.controller.state.events]
                self.assertEqual(event_types[-2:], ["fault.raised", "session.recovery-required"])
                self.assertNotIn("budget.reported", event_types[2:])
                self.assertNotIn("action.proposed", event_types[2:])
                formatted = "".join(
                    traceback.format_exception_only(
                        NativeControllerError,
                        NativeControllerError("SENTINEL_SECRET"),
                    )
                )
                self.assertIn("native controller is unavailable", formatted)

    async def test_checkpoint_seals_before_event_and_retries_close_once(self) -> None:
        fixture = ControllerFixture(event_ids=("event-created", "event-running", "event-checkpoint"))
        await fixture.create()

        event = fixture.controller.checkpoint("checkpoint-1")
        retry = fixture.controller.checkpoint("checkpoint-1")
        self.assertEqual(event, retry)
        self.assertEqual(event.type, "checkpoint.created")
        self.assertEqual(event.sequence, 3)
        self.assertEqual(fixture.store.position, 4)
        self.assertNotIn("covered_position", event.payload)
        self.assertRegex(str(event.payload["capsule_digest"]), r"^[0-9a-f]{64}$")
        checkpoint = fixture.controller.state.checkpoint
        self.assertIsNotNone(checkpoint)
        fixture.capsules.verify(cast(NativeCapsuleMetadata, checkpoint))

    async def test_checkpoint_capsule_payload_is_exact_replay_prefix(self) -> None:
        fixture = ControllerFixture()
        await fixture.create()
        await fixture.controller.accept(input_command("command-input-prefix", "content-ref-prefix"))
        request = fixture.controller.begin_ready_turn()
        self.assertIsNotNone(request)
        before_entries = fixture.store.replay()
        before_state = fixture.controller.state

        event = fixture.controller.checkpoint("checkpoint-prefix")

        payload = json.loads(
            fixture.capsules.sealed_payloads[str(event.payload["capsule_id"])].decode("utf-8")
        )
        self.assertEqual(payload["format"], "asterion.native-controller-capsule/v1")
        self.assertEqual(payload["checkpoint_id"], "checkpoint-prefix")
        self.assertNotIn("body", json.dumps(payload, sort_keys=True))
        self.assertNotIn("/Users/", json.dumps(payload, sort_keys=True))
        rebuilt = tuple(
            NativeEntry(
                int(item["position"]),
                None if item["previous_digest"] is None else str(item["previous_digest"]),
                NativeRecord(
                    str(item["record"]["record_id"]),
                    str(item["record"]["kind"]),
                    cast(Mapping[str, object], item["record"]["payload"]),
                ),
            )
            for item in payload["journal_prefix"]
        )
        self.assertEqual(rebuilt, before_entries)
        self.assertEqual(reduce_native_entries(rebuilt), before_state)
        self.assertEqual(len(rebuilt), fixture.store.position - 1)

    async def test_checkpoint_capsule_coverage_changes_for_budget_and_input_refs(
        self,
    ) -> None:
        async def capsule_for(
            *,
            budget: RemainingBudget,
            content_ref: str,
            delivery: str = "direct",
        ) -> tuple[str, bytes]:
            fixture = ControllerFixture()
            await fixture.create(budget)
            await fixture.controller.accept(
                input_command(
                    "command-input-covered",
                    content_ref,
                    delivery=delivery,
                )
            )
            event = fixture.controller.checkpoint("checkpoint-covered")
            capsule_id = str(event.payload["capsule_id"])
            return capsule_id, fixture.capsules.sealed_payloads[capsule_id]

        base_id, base_payload = await capsule_for(
            budget=_budget(controller_tokens=100, aggregate_tokens=100),
            content_ref="content-ref-covered-a",
        )
        budget_id, budget_payload = await capsule_for(
            budget=_budget(controller_tokens=99, aggregate_tokens=99),
            content_ref="content-ref-covered-a",
        )
        input_id, input_payload = await capsule_for(
            budget=_budget(controller_tokens=100, aggregate_tokens=100),
            content_ref="content-ref-covered-b",
        )
        delivery_id, delivery_payload = await capsule_for(
            budget=_budget(controller_tokens=100, aggregate_tokens=100),
            content_ref="content-ref-covered-a",
            delivery="steer",
        )

        for label, capsule_id, payload in (
            ("budget", budget_id, budget_payload),
            ("input", input_id, input_payload),
            ("delivery", delivery_id, delivery_payload),
        ):
            with self.subTest(label=label):
                self.assertNotEqual(capsule_id, base_id)
                self.assertNotEqual(payload, base_payload)

    async def test_checkpoint_retry_after_capsule_publish_is_deterministic_and_charged_once(
        self,
    ) -> None:
        fixture = ControllerFixture(
            event_ids=("event-created", "event-running", "event-failed", "event-retry"),
            capsule_ids=("fresh-capsule-a", "fresh-capsule-b"),
            store_factory=lambda owner, order: FailOnceTrackingSessionStore(
                owner,
                order,
                "checkpoint.committed",
            ),
        )
        await fixture.create()
        before = fixture.owner.budget.used_bytes
        with self.assertRaises(NativeStoreError):
            fixture.controller.checkpoint("checkpoint-retry")
        after_failed_publish = fixture.owner.budget.used_bytes
        self.assertGreater(after_failed_publish, before)

        reopened = fixture.reopen()
        event = reopened.checkpoint("checkpoint-retry")
        checkpoint = reopened.state.checkpoint
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None

        self.assertEqual(event.payload["capsule_id"], checkpoint.capsule_id)
        self.assertEqual(fixture.capsule_factory.calls, 0)
        self.assertEqual(
            [entry.record.kind for entry in fixture.store.replay()][-1],
            "checkpoint.committed",
        )
        used_after_checkpoint_record = fixture.owner.budget.used_bytes
        self.assertGreater(used_after_checkpoint_record, after_failed_publish)
        self.assertEqual(reopened.checkpoint("checkpoint-retry"), event)
        self.assertEqual(fixture.owner.budget.used_bytes, used_after_checkpoint_record)

    async def test_checkpoint_request_retry_rejects_state_drift_after_command_commit(
        self,
    ) -> None:
        fixture = ControllerFixture(
            event_ids=("event-created", "event-running", "event-failed"),
            store_factory=lambda owner, order: FailOnceTrackingSessionStore(
                owner,
                order,
                "checkpoint.committed",
            ),
        )
        await fixture.create()
        command = checkpoint_command("command-checkpoint", "checkpoint-drift")
        with self.assertRaises(NativeStoreError):
            await fixture.controller.accept(command)

        drifted = fixture.reopen()
        await drifted.accept(input_command("command-after-checkpoint", "content-ref-after"))
        with self.assertRaises(NativeControllerError):
            await drifted.accept(command)

    async def test_checkpoint_request_rejects_poison_before_append_and_retry_survives(
        self,
    ) -> None:
        unresolved = ControllerFixture(
            event_ids=("event-created", "event-running", "event-unresolved"),
            store_factory=lambda owner, order: FailOnceTrackingSessionStore(
                owner,
                order,
                "checkpoint.committed",
            ),
        )
        await unresolved.create()
        original = checkpoint_command("command-checkpoint-original", "checkpoint-shared")
        with self.assertRaises(NativeStoreError):
            await unresolved.controller.accept(original)
        before = unresolved.store.position

        reopened = unresolved.reopen()
        poison = checkpoint_command("command-checkpoint-poison", "checkpoint-shared")
        with self.assertRaises(NativeControllerError):
            await reopened.accept(poison)
        self.assertEqual(unresolved.store.position, before)
        self.assertNotIn(poison.command_id, reopened.state.command_digests)

        await reopened.accept(original)
        self.assertEqual(unresolved.store.position, before + 1)
        self.assertIn(original.command_id, reopened.state.command_digests)

        resolved = ControllerFixture(
            event_ids=("event-created", "event-running", "event-resolved")
        )
        await resolved.create()
        await resolved.controller.accept(original)
        before_resolved = resolved.store.position
        with self.assertRaises(NativeControllerError):
            await resolved.controller.accept(poison)
        self.assertEqual(resolved.store.position, before_resolved)
        self.assertNotIn(poison.command_id, resolved.controller.state.command_digests)

    async def test_checkpoint_command_replay_after_later_events_is_noop(self) -> None:
        fixture = ControllerFixture(
            event_ids=(
                "event-created",
                "event-running",
                "event-checkpoint",
                "event-paused",
            )
        )
        await fixture.create()
        command = checkpoint_command("command-checkpoint-replay", "checkpoint-replay")
        await fixture.controller.accept(command)
        checkpoint_event = fixture.controller.state.events[-1]
        await fixture.controller.accept(
            lifecycle_command("command-pause-after-checkpoint", "session.pause", "pause")
        )
        before = fixture.store.position

        await fixture.controller.accept(command)

        self.assertEqual(fixture.store.position, before)
        self.assertIn(checkpoint_event, fixture.controller.state.events)

    async def test_replay_cursor_bounds_reopen_reducer_and_started_turn_recovery(self) -> None:
        fixture = ControllerFixture(turn_ids=("turn-stable",))
        await fixture.create()
        await fixture.controller.accept(input_command())
        request = fixture.controller.begin_ready_turn()
        self.assertIsNotNone(request)
        assert request is not None

        reopened = fixture.reopen()
        replayed = reopened.begin_ready_turn()
        self.assertEqual(replayed, request)
        self.assertEqual(
            reduce_native_entries(fixture.store.replay()),
            reopened.state,
        )
        self.assertEqual(
            [event.type for event in reopened.replay_events(EventCursor(1, 1))],
            ["session.running"],
        )
        for cursor in (EventCursor(2, 0), EventCursor(1, 99)):
            with self.subTest(cursor=cursor), self.assertRaises(NativeControllerError):
                reopened.replay_events(cursor)

    async def test_turn_id_is_stable_from_causal_identity_not_factory(self) -> None:
        first = ControllerFixture(turn_ids=("factory-a",))
        await first.create()
        await first.controller.accept(input_command("command-input-stable", "content-ref-stable"))
        first_request = first.controller.begin_ready_turn()
        self.assertIsNotNone(first_request)
        assert first_request is not None

        reopened = first.reopen()
        replayed = reopened.begin_ready_turn()
        self.assertEqual(replayed, first_request)
        self.assertEqual(first.turn_factory.calls, 0)

        second = ControllerFixture(turn_ids=("factory-b",))
        await second.create()
        await second.controller.accept(input_command("command-input-stable", "content-ref-stable"))
        second_request = second.controller.begin_ready_turn()
        self.assertIsNotNone(second_request)
        assert second_request is not None
        self.assertEqual(second_request.turn_id, first_request.turn_id)
        self.assertEqual(second.turn_factory.calls, 0)

        changed = ControllerFixture(turn_ids=("factory-c",))
        await changed.create()
        await changed.controller.accept(input_command("command-input-other", "content-ref-stable"))
        changed_request = changed.controller.begin_ready_turn()
        self.assertIsNotNone(changed_request)
        assert changed_request is not None
        self.assertNotEqual(changed_request.turn_id, first_request.turn_id)

        action_fixture = ControllerFixture(
            adapter=CountingAdapter(
                NativeTurnResult("copy-request-turn", (proposal_draft(),), _usage())
            )
        )
        await action_fixture.create()
        await action_fixture.controller.accept(input_command())
        proposal_request = action_fixture.controller.begin_ready_turn()
        assert proposal_request is not None
        action_fixture.controller.commit_turn(
            proposal_request,
            await action_fixture.controller.execute_turn(proposal_request),
        )
        await action_fixture.controller.accept(terminal_resolution_command("action-1", "receipt-stable"))
        action_request = action_fixture.controller.begin_ready_turn()
        self.assertIsNotNone(action_request)
        assert action_request is not None
        self.assertNotEqual(action_request.turn_id, first_request.turn_id)

    async def test_close_order_use_after_close_redaction_and_hostile_types(self) -> None:
        fixture = ControllerFixture()
        await fixture.create()

        fixture.controller.close()
        self.assertEqual(fixture.close_order, ["capsule", "journal", "owner"])
        with self.assertRaises(NativeStoreError):
            fixture.controller.replay_events(None)
        with self.assertRaises(NativeControllerError) as caught:
            NativeController(
                owner=cast(NativeStorageOwner, object()),
                session_store=fixture.store,
                capsule_store=fixture.capsules,
                turn_adapter=fixture.adapter,
                provider_id="native",
                provider_version="0.1.0",
                system_id="research.system",
                system_version="1.0.0",
                session_id=SESSION_ID,
                generation=GENERATION,
                checkpoint_version="1.0.0",
                authority_id="authority-1",
                authority_revision=AUTHORITY_REVISION,
                event_id_factory=lambda: "/tmp/SENTINEL_SECRET",
                turn_id_factory=lambda: "turn-1",
                capsule_id_factory=lambda: "capsule-1",
                clock=lambda: "2026-08-30T00:00:00Z",
            )
        self.assertNotIn("SENTINEL_SECRET", str(caught.exception))

    async def test_public_values_are_exact_type_checked_before_effects(self) -> None:
        fixture = ControllerFixture()
        hostile_command = HostileControlCommand(
            command_id="command-hostile",
            session_id=SESSION_ID,
            authority_revision=AUTHORITY_REVISION,
            type="session.create",
            payload=create_command().payload,
        )
        with self.assertRaises(NativeControllerError) as command_error:
            await fixture.controller.accept(hostile_command)
        self.assertEqual(hostile_command.mapping_calls, 0)
        self.assertNotIn("SENTINEL_SECRET", str(command_error.exception))

        await fixture.create()
        hostile_budget = HostileRemainingBudget(1, 0, 0, 1, 0, 1)
        with self.assertRaises(NativeControllerError):
            fixture.controller.sync_authority(hostile_budget)
        self.assertEqual(hostile_budget.attribute_reads, 0)

        await fixture.controller.accept(input_command())
        request = fixture.controller.begin_ready_turn()
        assert request is not None
        hostile_request = HostileTurnRequest(
            turn_id=request.turn_id,
            session_id=request.session_id,
            generation=request.generation,
            authority_revision=request.authority_revision,
            causal_command_ids=request.causal_command_ids,
            inputs=request.inputs,
            action_results=request.action_results,
            budget=request.budget,
        )
        with self.assertRaises(NativeControllerError):
            fixture.controller.commit_budget_limited_turn(hostile_request)
        self.assertEqual(hostile_request.comparisons, 0)

        hostile_result = HostileTurnResult(request.turn_id, (), _usage())
        with self.assertRaises(NativeControllerError):
            fixture.controller.commit_turn(request, hostile_result)
        self.assertEqual(hostile_result.attribute_reads, 0)

        hostile_cursor = HostileEventCursor(GENERATION, 0)
        with self.assertRaises(NativeControllerError):
            fixture.controller.replay_events(hostile_cursor)
        self.assertEqual(hostile_cursor.attribute_reads, 0)


if __name__ == "__main__":
    unittest.main()  # pragma: no cover
