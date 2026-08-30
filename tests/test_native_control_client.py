from __future__ import annotations

import asyncio
import traceback
import unittest
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import cast

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.protocol import CONTROL_COMMAND_TYPES, CONTROL_EVENT_TYPES
from asterion.control.providers.native.capsule import MemoryNativeCapsuleStore
from asterion.control.providers.native.client import (
    NativeControlError,
    NativeControlPlaneClient,
)
from asterion.control.providers.native.controller import NativeController
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeEventDraft,
    NativeTurnRequest,
    NativeTurnResult,
)
from asterion.control.providers.native.store import (
    MemoryNativeSessionStore,
    MemoryNativeStorageOwner,
)
from asterion.control.providers.native.turn import NativeTurnAdapter


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


def _manifest() -> ControlPlaneManifest:
    return ControlPlaneManifest(
        control_plane_id="asterion.native",
        version="0.1.0",
        commands=tuple(sorted(CONTROL_COMMAND_TYPES)),
        events=tuple(sorted(CONTROL_EVENT_TYPES)),
        capabilities=(
            "action-proposals",
            "checkpointing",
            "event-replay",
            "session-lifecycle",
        ),
        continuation_media_type="application/vnd.asterion.native-capsule+json",
        checkpoint_version="1.0.0",
        compatibility_ids=(
            "asterion.agent-control/v1",
            "asterion.native-controller/v1",
        ),
    )


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
) -> ControlCommand:
    return _command(
        command_id,
        "input.submit",
        {
            "input_id": input_id,
            "delivery": "direct",
            "content_ref": content_ref,
        },
    )


def lifecycle_command(command_id: str, command_type: str, reason: str) -> ControlCommand:
    return _command(command_id, command_type, {"reason_code": reason})


def action_resolution_command(
    command_id: str,
    resolution: str,
    *,
    action_id: str = "action-1",
    receipt_ref: str | None = None,
) -> ControlCommand:
    return _command(
        command_id,
        "action.resolve",
        {
            "action_id": action_id,
            "resolution": resolution,
            "reason_code": "ok",
            "receipt_ref": receipt_ref,
        },
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
        if self._values:
            return self._values.pop(0)
        return f"generated-{self.calls}"


class FixedClock:
    def __init__(self, value: str = EMITTED_AT) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


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


class BlockingAdapter:
    adapter_id = "native.blocking-turn/v1"

    def __init__(self, result: NativeTurnResult) -> None:
        self.result = result
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        if self.result.turn_id == "copy-request-turn":
            return replace(self.result, turn_id=request.turn_id)
        return self.result


class HostileManifest(ControlPlaneManifest):
    def to_mapping(self) -> Mapping[str, object]:
        raise AssertionError("SENTINEL_SECRET")


class HostileCursor(EventCursor):
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


class Fixture:
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
            "event-extra",
        ),
        turn_ids: Iterable[str] = ("turn-1", "turn-2", "turn-3"),
        max_turns_per_poll: int = 10,
        max_events_per_poll: int = 10,
    ) -> None:
        self.owner = MemoryNativeStorageOwner(maximum_bytes=1_000_000)
        self.store = MemoryNativeSessionStore(self.owner, max_record_bytes=65_536)
        self.capsules = MemoryNativeCapsuleStore(self.owner, max_capsule_bytes=65_536)
        self.event_factory = SequenceFactory(event_ids)
        self.turn_factory = SequenceFactory(turn_ids)
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
            capsule_id_factory=SequenceFactory(("capsule-1",)),
            clock=FixedClock(),
        )
        self.client = NativeControlPlaneClient(
            manifest=_manifest(),
            controller=self.controller,
            max_turns_per_poll=max_turns_per_poll,
            max_events_per_poll=max_events_per_poll,
        )

    async def create(self, budget: RemainingBudget | None = None) -> None:
        await self.client.send(create_command())
        await self.client.sync_authority_snapshot(budget or _budget())


async def _collect_events(
    client: NativeControlPlaneClient,
    cursor: EventCursor | None = None,
) -> tuple[ControlEvent, ...]:
    result: list[ControlEvent] = []
    async for event in client.events(cursor):
        result.append(event)
    return tuple(result)


class TestNativeControlClient(unittest.IsolatedAsyncioTestCase):
    async def test_send_is_durable_before_return_and_equal_retry_is_idempotent(
        self,
    ) -> None:
        fixture = Fixture()
        command = create_command()

        await fixture.client.send(command)
        committed = fixture.store.position
        await fixture.client.send(command)

        self.assertEqual(fixture.store.position, committed)
        self.assertEqual(
            [event.type for event in fixture.controller.replay_events(None)],
            ["session.created", "session.running"],
        )

    async def test_sync_authority_snapshot_equal_retry_is_idempotent(self) -> None:
        fixture = Fixture()
        await fixture.client.send(create_command())
        budget = _budget(controller_tokens=23, aggregate_tokens=23)

        await fixture.client.sync_authority_snapshot(budget)
        committed = fixture.store.position
        await fixture.client.sync_authority_snapshot(budget)

        self.assertEqual(fixture.store.position, committed)
        self.assertEqual(fixture.controller.state.remaining_budget, budget)

    async def test_event_iterator_releases_lock_while_host_sends_resolution(
        self,
    ) -> None:
        fixture = Fixture(
            adapter=CountingAdapter(
                NativeTurnResult(
                    "copy-request-turn",
                    (proposal_draft(),),
                    _usage(controller_tokens=3, aggregate_tokens=3),
                )
            ),
            turn_ids=("turn-propose", "turn-resolution"),
        )
        await fixture.create()
        await fixture.client.send(input_command())
        seen: list[str] = []

        async for event in fixture.client.events(EventCursor(1, 2)):
            seen.append(event.type)
            if event.type == "action.proposed":
                await asyncio.wait_for(
                    fixture.client.send(
                        action_resolution_command("command-action-admitted", "admitted")
                    ),
                    timeout=1,
                )

        self.assertIn("action.proposed", seen)
        self.assertEqual(
            fixture.controller.state.action_statuses["action-1"],
            "admitted",
        )

    async def test_adapter_await_releases_lock_for_concurrent_send(self) -> None:
        adapter = BlockingAdapter(
            NativeTurnResult(
                "copy-request-turn",
                (proposal_draft(),),
                _usage(controller_tokens=1, aggregate_tokens=1),
            )
        )
        fixture = Fixture(adapter=adapter)
        await fixture.create()
        await fixture.client.send(input_command())
        events_task = asyncio.create_task(_collect_events(fixture.client, EventCursor(1, 2)))

        await asyncio.wait_for(adapter.started.wait(), timeout=1)
        await asyncio.wait_for(
            fixture.client.send(
                lifecycle_command("command-cancel", "session.cancel", "operator-cancel")
            ),
            timeout=1,
        )
        adapter.release.set()
        events = await asyncio.wait_for(events_task, timeout=1)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual([event.type for event in events], ["session.cancelled"])
        self.assertEqual(
            [event.type for event in fixture.controller.state.events],
            ["session.created", "session.running", "session.cancelled"],
        )

    async def test_cancel_during_adapter_await_fences_late_result_without_recovery(
        self,
    ) -> None:
        adapter = BlockingAdapter(
            NativeTurnResult(
                "copy-request-turn",
                (proposal_draft(),),
                _usage(controller_tokens=1, aggregate_tokens=1),
            )
        )
        fixture = Fixture(adapter=adapter, turn_ids=("turn-race",))
        await fixture.create()
        await fixture.client.send(input_command())
        events_task = asyncio.create_task(_collect_events(fixture.client, EventCursor(1, 2)))

        await asyncio.wait_for(adapter.started.wait(), timeout=1)
        started_turn = fixture.controller.state.pending_turn
        self.assertIsNotNone(started_turn)
        await fixture.client.send(
            lifecycle_command("command-cancel", "session.cancel", "operator-cancel")
        )
        adapter.release.set()
        await asyncio.wait_for(events_task, timeout=1)

        self.assertEqual(fixture.controller.state.lifecycle, "cancelled")
        self.assertIsNotNone(started_turn)
        assert started_turn is not None
        self.assertIn(started_turn.turn_id, fixture.controller.state.fenced_turn_ids)
        self.assertEqual(
            [event.type for event in fixture.controller.state.events],
            ["session.created", "session.running", "session.cancelled"],
        )
        self.assertFalse(fixture.controller.state.recovery_required_turn_ids)
        self.assertEqual(
            [entry.record.kind for entry in fixture.store.replay()].count(
                "turn.committed"
            ),
            0,
        )

    async def test_budget_limited_turn_commits_without_invoking_adapter(self) -> None:
        adapter = CountingAdapter(NativeTurnResult("copy-request-turn", (), _usage()))
        fixture = Fixture(adapter=adapter)
        await fixture.create(_budget(controller_tokens=0, aggregate_tokens=0))
        await fixture.client.send(input_command())

        events = await _collect_events(fixture.client, EventCursor(1, 2))

        self.assertEqual(adapter.calls, 0)
        self.assertEqual(
            [event.type for event in events],
            ["budget.reported", "session.budget-limited"],
        )
        self.assertFalse(fixture.store.replay()[-1].record.payload["adapter_invoked"])

    async def test_adapter_failure_and_invalid_result_commit_one_recovery(self) -> None:
        cases: tuple[tuple[str, NativeTurnResult | BaseException], ...] = (
            ("exception", RuntimeError("SENTINEL_SECRET")),
            ("wrong-turn", NativeTurnResult("other-turn", (), _usage())),
            (
                "over-budget",
                NativeTurnResult(
                    "copy-request-turn",
                    (),
                    _usage(controller_tokens=101, aggregate_tokens=101),
                ),
            ),
        )
        for label, result in cases:
            with self.subTest(label=label):
                fixture = Fixture(adapter=CountingAdapter(result))
                await fixture.create()
                await fixture.client.send(
                    input_command(f"command-input-{label}", f"content-ref-{label}")
                )

                events = await _collect_events(fixture.client, EventCursor(1, 2))

                self.assertEqual(
                    [event.type for event in events],
                    ["fault.raised", "session.recovery-required"],
                )
                self.assertEqual(
                    [entry.record.kind for entry in fixture.store.replay()].count(
                        "turn.recovery-required"
                    ),
                    1,
                )

    async def test_turn_and_event_limits_bound_each_poll_without_duplicates(self) -> None:
        fixture = Fixture(
            adapter=CountingAdapter(
                NativeTurnResult(
                    "copy-request-turn",
                    (
                        NativeEventDraft(
                            "budget.reported",
                            {
                                "controller_tokens": 0,
                                "application_tokens": 0,
                                "child_tokens": 0,
                                "aggregate_tokens": 0,
                                "cost_micros": 0,
                            },
                        ),
                    ),
                    _usage(),
                )
            ),
            max_turns_per_poll=1,
            max_events_per_poll=3,
        )
        await fixture.create()
        await fixture.client.send(input_command("command-input-a", "content-ref-a"))
        await fixture.client.send(
            input_command("command-input-b", "content-ref-b", input_id="input-2")
        )

        first = await _collect_events(fixture.client)
        second = await _collect_events(
            fixture.client,
            EventCursor(GENERATION, first[-1].sequence),
        )

        self.assertEqual([event.sequence for event in first], [1, 2, 3])
        self.assertEqual([event.sequence for event in second], [4])
        self.assertEqual(
            len({event.sequence for event in (*first, *second)}),
            len((*first, *second)),
        )

    async def test_cursor_bounds_and_conflicts_fail_closed_without_leaking_context(
        self,
    ) -> None:
        fixture = Fixture()
        await fixture.create()

        for cursor in (EventCursor(2, 0), EventCursor(1, 3)):
            with self.subTest(cursor=cursor):
                with self.assertRaises(NativeControlError) as caught:
                    await _collect_events(fixture.client, cursor)
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn("SENTINEL_SECRET", str(caught.exception))

    async def test_close_is_idempotent_and_post_close_operations_reject(self) -> None:
        fixture = Fixture()
        iterator = fixture.client.events()

        await fixture.client.close()
        await fixture.client.close()

        for operation in (
            lambda: fixture.client.send(create_command()),
            lambda: fixture.client.sync_authority_snapshot(_budget()),
            lambda: _collect_events(fixture.client),
            lambda: iterator.__anext__(),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(NativeControlError) as caught:
                    await operation()
                self.assertIsNone(caught.exception.__context__)
                self.assertIsNone(caught.exception.__cause__)

    async def test_exact_types_are_rejected_before_hostile_methods_or_properties(
        self,
    ) -> None:
        fixture = Fixture()
        hostile_cursor = HostileCursor(1, 0)
        hostile_manifest = HostileManifest(
            control_plane_id=_manifest().control_plane_id,
            version=_manifest().version,
            commands=_manifest().commands,
            events=_manifest().events,
            capabilities=_manifest().capabilities,
            continuation_media_type=_manifest().continuation_media_type,
            checkpoint_version=_manifest().checkpoint_version,
            compatibility_ids=_manifest().compatibility_ids,
        )

        with self.assertRaises(NativeControlError):
            NativeControlPlaneClient(
                manifest=hostile_manifest,
                controller=fixture.controller,
                max_turns_per_poll=1,
                max_events_per_poll=1,
            )

        with self.assertRaises(NativeControlError):
            NativeControlPlaneClient(
                manifest=_manifest(),
                controller=cast(NativeController, object()),
                max_turns_per_poll=1,
                max_events_per_poll=1,
            )

        with self.assertRaises(NativeControlError):
            fixture.client.events(hostile_cursor)
        self.assertEqual(hostile_cursor.attribute_reads, 0)

        with self.assertRaises(NativeControlError):
            await fixture.client.send(cast(ControlCommand, object()))

        with self.assertRaises(NativeControlError):
            await fixture.client.sync_authority_snapshot(cast(RemainingBudget, object()))

        for label, turns, events in (
            ("zero-turns", 0, 1),
            ("zero-events", 1, 0),
            ("bool", cast(int, True), 1),
            ("unsafe", MAX_SAFE_JSON_INTEGER + 1, 1),
        ):
            with self.subTest(label=label), self.assertRaises(NativeControlError):
                NativeControlPlaneClient(
                    manifest=_manifest(),
                    controller=fixture.controller,
                    max_turns_per_poll=turns,
                    max_events_per_poll=events,
                )

    async def test_transport_uncertainty_from_pending_mismatch_fails_closed(
        self,
    ) -> None:
        adapter = BlockingAdapter(
            NativeTurnResult("copy-request-turn", (), _usage())
        )
        fixture = Fixture(adapter=adapter)
        await fixture.create()
        await fixture.client.send(input_command())
        events_task = asyncio.create_task(_collect_events(fixture.client, EventCursor(1, 2)))

        await asyncio.wait_for(adapter.started.wait(), timeout=1)
        request = fixture.controller.state.pending_turn
        self.assertIsNotNone(request)
        assert request is not None
        object.__setattr__(
            fixture.controller,
            "_state",
            replace(fixture.controller.state, pending_turn=replace(request, turn_id="turn-other")),
        )
        adapter.release.set()

        with self.assertRaises(NativeControlError):
            await asyncio.wait_for(events_task, timeout=1)

    async def test_native_control_error_is_fixed_and_unchained(self) -> None:
        try:
            try:
                raise RuntimeError("SENTINEL_SECRET")
            except RuntimeError:
                raise NativeControlError("ignored")
        except NativeControlError as error:
            error.__context__ = None
            message = str(error)
            formatted = "".join(
                traceback.format_exception_only(NativeControlError, error)
            )

        self.assertIn("NativeControlError", formatted)
        self.assertEqual(message, "native control is unavailable")
