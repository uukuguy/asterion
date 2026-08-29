"""Deterministic provider fake and reusable control conformance scenarios."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneClient,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.protocol import validate_control_event_stream


REQUIRED_PHASE0_SCENARIOS = frozenset(
    {
        "attach-replay",
        "budget-limited",
        "cancel",
        "checkpoint",
        "command-idempotency",
        "complete",
        "fault-recovery",
        "input-delivery",
        "pause-resume",
        "proposal-admission",
    }
)

class ControlProviderConformanceError(RuntimeError):
    """Raised by the deterministic provider when conformance fails closed."""


@dataclass(frozen=True)
class ConformanceReport:
    passed: tuple[str, ...]
    failed: tuple[str, ...]


class ControlConformanceDriver(ControlPlaneClient, Protocol):
    @property
    def command_log(self) -> tuple[ControlCommand, ...]:
        """Return persisted safe commands in acceptance order."""
        ...

    def emit_goal_status(self, status: str) -> ControlEvent:
        """Drive a deterministic goal transition for the scenario harness."""
        ...

    def emit_session_status(
        self, status: str, *, reason_code: str
    ) -> ControlEvent:
        """Drive a deterministic terminal session transition."""
        ...

    def emit_fault(
        self, code: str, *, recoverable: bool
    ) -> tuple[ControlEvent, ...]:
        """Inject one public-safe deterministic provider fault."""
        ...

    def emit_application_proposal(self) -> ControlEvent:
        """Emit one deterministic application proposal."""
        ...


class FakeControlPlaneClient:
    """In-memory provider with persisted command/event logs and exact replay."""

    def __init__(self, *, disconnect_after_sequence: int | None = None) -> None:
        self._manifest = ControlPlaneManifest(
            control_plane_id="fake.control",
            version="1.0.0",
            commands=(
                "action.resolve",
                "checkpoint.request",
                "input.submit",
                "session.attach",
                "session.cancel",
                "session.create",
                "session.detach",
                "session.pause",
                "session.resume",
            ),
            events=(
                "action.proposed",
                "budget.reported",
                "checkpoint.created",
                "fault.raised",
                "goal.updated",
                "session.budget-limited",
                "session.cancelled",
                "session.completed",
                "session.created",
                "session.failed",
                "session.paused",
                "session.recovery-required",
                "session.running",
            ),
            capabilities=(
                "action-proposals",
                "checkpointing",
                "event-replay",
                "session-lifecycle",
            ),
            continuation_media_type="application/vnd.asterion.control-capsule",
            checkpoint_version="1.0.0",
            compatibility_ids=("asterion.agent-control/v1", "fake-control/v1"),
        )
        self._commands: dict[str, ControlCommand] = {}
        self._events: list[ControlEvent] = []
        self._session_id: str | None = None
        self._generation = 1
        self._closed = False
        self.disconnect_after_sequence = disconnect_after_sequence

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    @property
    def command_log(self) -> tuple[ControlCommand, ...]:
        return tuple(self._commands.values())

    async def send(self, command: ControlCommand) -> None:
        if self._closed or not isinstance(command, ControlCommand):
            raise ControlProviderConformanceError("fake provider command is invalid")
        existing = self._commands.get(command.command_id)
        if existing is not None:
            if existing != command:
                raise ControlProviderConformanceError(
                    "fake provider command replay conflicts"
                )
            return
        if self._session_id is not None and command.session_id != self._session_id:
            raise ControlProviderConformanceError(
                "fake provider session identity mismatches"
            )
        self._commands[command.command_id] = command
        if command.type == "session.create":
            if self._session_id is not None:
                raise ControlProviderConformanceError(
                    "fake provider session creation conflicts"
                )
            self._session_id = command.session_id
            self._emit(
                "session.created",
                {
                    "goal_id": command.payload["goal_id"],
                    "authority_id": "authority-1",
                    "authority_revision": command.authority_revision,
                },
            )
            self._emit("session.running", {"reason_code": "started"})
        elif command.type == "session.pause":
            self._emit("session.paused", {"reason_code": command.payload["reason_code"]})
        elif command.type == "session.resume":
            self._emit("session.running", {"reason_code": command.payload["reason_code"]})
        elif command.type == "session.detach":
            return
        elif command.type == "session.cancel":
            self._emit(
                "session.cancelled", {"reason_code": command.payload["reason_code"]}
            )
        elif command.type == "checkpoint.request":
            checkpoint_id = str(command.payload["checkpoint_id"])
            self._emit(
                "checkpoint.created",
                {
                    "checkpoint_id": checkpoint_id,
                    "capsule_id": f"capsule-{checkpoint_id}",
                    "capsule_digest": "a" * 64,
                    "control_plane_id": "fake.control",
                    "control_plane_version": "1.0.0",
                    "checkpoint_version": "1.0.0",
                    "covered_sequence": len(self._events),
                    "storage_ref": f"storage-{checkpoint_id}",
                },
            )

    def events(
        self, cursor: EventCursor | None = None
    ) -> AsyncIterator[ControlEvent]:
        if self._closed:
            raise ControlProviderConformanceError("fake provider is closed")
        start = 0
        if cursor is not None:
            if (
                not isinstance(cursor, EventCursor)
                or cursor.generation != self._generation
                or cursor.sequence > len(self._events)
            ):
                raise ControlProviderConformanceError(
                    "fake provider replay cursor conflicts"
                )
            start = cursor.sequence
        return self._iterate(start)

    async def _iterate(self, start: int) -> AsyncIterator[ControlEvent]:
        for event in tuple(self._events[start:]):
            yield event
            if self.disconnect_after_sequence == event.sequence:
                raise ControlProviderConformanceError(
                    "fake provider injected disconnect"
                )

    async def close(self) -> None:
        self._closed = True

    def emit_goal_status(self, status: str) -> ControlEvent:
        return self._emit("goal.updated", {"goal_id": "goal-1", "status": status})

    def emit_session_status(
        self, status: str, *, reason_code: str
    ) -> ControlEvent:
        event_type = {
            "completed": "session.completed",
            "failed": "session.failed",
            "budget_limited": "session.budget-limited",
        }.get(status)
        if event_type is None:
            raise ControlProviderConformanceError("fake session status is invalid")
        return self._emit(event_type, {"reason_code": reason_code})

    def emit_fault(self, code: str, *, recoverable: bool) -> tuple[ControlEvent, ...]:
        fault = self._emit(
            "fault.raised",
            {
                "code": code,
                "recoverable": recoverable,
                "evidence_ref": "evidence-fault-1",
            },
        )
        events = [fault]
        if recoverable:
            events.append(
                self._emit(
                    "session.recovery-required",
                    {"reason_code": code},
                )
            )
        return tuple(events)

    def emit_application_proposal(self) -> ControlEvent:
        return self._emit(
            "action.proposed",
            {
                "action_id": "action-1",
                "authority_revision": 1,
                "idempotency_key": "idempotency-1",
                "kind": "application.invoke",
                "target": {
                    "kind": "application",
                    "provider_id": "example.provider",
                    "application_id": "alpha",
                    "version": "1.0.0",
                    "runtime_id": "fake.runtime",
                },
                "input_ref": "input-ref-1",
                "expected_artifacts": ("report.alpha",),
                "budget": {
                    "controller_tokens": 0,
                    "application_tokens": 100,
                    "child_tokens": 0,
                    "aggregate_tokens": 100,
                    "cost_micros": 5_000,
                    "deadline_ms": 10_000,
                },
                "causal_parent_ids": ("goal-1",),
            },
        )

    def _emit(self, event_type: str, payload: dict[str, object]) -> ControlEvent:
        if self._session_id is None:
            raise ControlProviderConformanceError("fake provider session is absent")
        sequence = len(self._events) + 1
        event = ControlEvent(
            event_id=f"event-{sequence}",
            session_id=self._session_id,
            generation=self._generation,
            sequence=sequence,
            emitted_at=f"2026-08-09T15:00:{sequence:02d}Z",
            type=event_type,
            payload=payload,
        )
        self._events.append(event)
        return event


async def run_control_provider_conformance(
    factory: Callable[[], ControlConformanceDriver],
) -> ConformanceReport:
    """Run the provider-independent Phase 0 scenarios against a fresh client each."""

    scenarios = {
        "attach-replay": _scenario_attach_replay,
        "budget-limited": _scenario_budget_limited,
        "cancel": _scenario_cancel,
        "checkpoint": _scenario_checkpoint,
        "command-idempotency": _scenario_command_idempotency,
        "complete": _scenario_complete,
        "fault-recovery": _scenario_fault_recovery,
        "input-delivery": _scenario_input_delivery,
        "pause-resume": _scenario_pause_resume,
        "proposal-admission": _scenario_proposal_admission,
    }
    passed: list[str] = []
    failed: list[str] = []
    for scenario_id in sorted(scenarios):
        try:
            client = factory()
            await scenarios[scenario_id](client)
        except Exception as error:
            failed.append(f"{scenario_id}:{type(error).__name__}")
        else:
            passed.append(scenario_id)
    return ConformanceReport(tuple(passed), tuple(failed))


def _create_command(command_id: str = "command-1") -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


async def _collect(
    client: ControlConformanceDriver, cursor: EventCursor | None = None
) -> tuple[ControlEvent, ...]:
    return tuple([event async for event in client.events(cursor)])


def _validate_complete(events: tuple[ControlEvent, ...]) -> None:
    validate_control_event_stream(tuple(event.to_mapping() for event in events))


def _terminal_complete(client: ControlConformanceDriver) -> None:
    client.emit_goal_status("completed")
    client.emit_session_status("completed", reason_code="goal-accepted")


async def _scenario_complete(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    _terminal_complete(client)
    _validate_complete(await _collect(client))


async def _scenario_pause_resume(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    await client.send(_reason_command("command-2", "session.pause", "operator-request"))
    await client.send(_reason_command("command-3", "session.resume", "resumed"))
    _terminal_complete(client)
    _validate_complete(await _collect(client))


async def _scenario_fault_recovery(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    client.emit_fault("provider-disconnected", recoverable=True)
    await client.send(_reason_command("command-2", "session.resume", "recovered"))
    _terminal_complete(client)
    _validate_complete(await _collect(client))


async def _scenario_checkpoint(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    await client.send(
        ControlCommand(
            command_id="command-2",
            session_id="session-1",
            authority_revision=1,
            type="checkpoint.request",
            payload={"checkpoint_id": "checkpoint-1"},
        )
    )
    _terminal_complete(client)
    _validate_complete(await _collect(client))


async def _scenario_cancel(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    await client.send(_reason_command("command-2", "session.cancel", "operator-request"))
    _validate_complete(await _collect(client))


async def _scenario_budget_limited(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    client.emit_session_status("budget_limited", reason_code="budget-exhausted")
    _validate_complete(await _collect(client))


async def _scenario_attach_replay(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    _terminal_complete(client)
    suffix = await _collect(client, EventCursor(generation=1, sequence=2))
    if tuple(event.sequence for event in suffix) != (3, 4):
        raise ControlProviderConformanceError("attach replay suffix is invalid")


async def _scenario_command_idempotency(client: ControlConformanceDriver) -> None:
    command = _create_command()
    await client.send(command)
    await client.send(command)
    _terminal_complete(client)
    if len(client.command_log) != 1:
        raise ControlProviderConformanceError("command replay duplicated")
    _validate_complete(await _collect(client))


async def _scenario_input_delivery(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    for index, delivery in enumerate(("direct", "steer", "follow_up"), start=2):
        await client.send(
            ControlCommand(
                command_id=f"command-{index}",
                session_id="session-1",
                authority_revision=1,
                type="input.submit",
                payload={
                    "input_id": f"input-{index}",
                    "delivery": delivery,
                    "content_ref": f"content-ref-{index}",
                },
            )
        )
    _terminal_complete(client)
    _validate_complete(await _collect(client))


async def _scenario_proposal_admission(client: ControlConformanceDriver) -> None:
    await client.send(_create_command())
    client.emit_application_proposal()
    await client.send(
        ControlCommand(
            command_id="command-2",
            session_id="session-1",
            authority_revision=1,
            type="action.resolve",
            payload={
                "action_id": "action-1",
                "resolution": "admitted",
                "reason_code": "authorized",
                "receipt_ref": None,
            },
        )
    )
    _terminal_complete(client)
    _validate_complete(await _collect(client))


def _reason_command(command_id: str, command_type: str, reason: str) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id="session-1",
        authority_revision=1,
        type=command_type,
        payload={"reason_code": reason},
    )
