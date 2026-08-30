from __future__ import annotations

import asyncio
import contextvars
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from asterion.control.authority import (
    AuthorityEnvelope,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
    RemainingBudget,
)
from asterion.control.factory import ControlPlaneFactoryContext
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.protocol import validate_control_event_stream
from asterion.control.providers.native.factory import (
    NATIVE_CONTROL_PLANE_ID,
    NATIVE_CONTROL_PLANE_VERSION,
    build_native_control_plane_client,
)
from asterion.control.providers.native.model import (
    NativeEventDraft,
    NativeTurnRequest,
    NativeTurnResult,
)
from asterion.control.providers.native.turn import _turn_script_key
from asterion.control.testing import REQUIRED_PHASE0_SCENARIOS, ConformanceReport


SESSION_ID = "session-1"
GENERATION = 1
AUTHORITY_ID = "authority-1"
AUTHORITY_REVISION = 1
ZERO_COUNTER_FIELDS = (
    "provider_operations",
    "model_operations",
    "credential_reads",
    "network_operations",
    "application_operations",
    "upload_operations",
)
_ACTIVE_RECORDER: contextvars.ContextVar[OperationRecorder | None]


@dataclass
class OperationRecorder:
    provider_operations: int = 0
    model_operations: int = 0
    credential_reads: int = 0
    network_operations: int = 0
    application_operations: int = 0
    upload_operations: int = 0
    turn_adapter_calls: int = 0
    executor_calls: int = 0

    def closed_counts(self) -> Mapping[str, int]:
        return {
            "provider_operations": self.provider_operations,
            "model_operations": self.model_operations,
            "credential_reads": self.credential_reads,
            "network_operations": self.network_operations,
            "application_operations": self.application_operations,
            "upload_operations": self.upload_operations,
        }


_ACTIVE_RECORDER = contextvars.ContextVar("native_task8_recorder", default=None)


class ScriptedNativeTurnAdapter:
    adapter_id = "native.task8-script/v1"

    def __init__(
        self,
        scripts: Mapping[str, tuple[NativeEventDraft, ...] | BaseException],
        recorder: OperationRecorder,
    ) -> None:
        self._scripts = dict(scripts)
        self._recorder = recorder
        self.requests: list[NativeTurnRequest] = []

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        self._recorder.turn_adapter_calls += 1
        self.requests.append(request)
        key = _turn_script_key(request)
        try:
            script = self._scripts[key]
        except KeyError as error:
            raise AssertionError(f"missing native turn script for {key}") from error
        if isinstance(script, BaseException):
            raise script
        return NativeTurnResult(
            request.turn_id,
            tuple(script),
            _usage(controller_tokens=_script_controller_usage(script)),
        )


@dataclass(frozen=True)
class NativeRun:
    client: object
    adapter: ScriptedNativeTurnAdapter
    recorder: OperationRecorder
    private_root: Path
    directory: tempfile.TemporaryDirectory[str] | None

    async def close(self) -> None:
        await cast(object, self.client).close()  # type: ignore[attr-defined]
        if self.directory is not None:
            self.directory.cleanup()


def native_authority(
    *,
    budget_limit: BudgetLimit | None = None,
    allowed_portfolio: tuple[PortfolioGrant, ...] | None = None,
    allowed_operations: tuple[str, ...] = ("application.invoke", "child.spawn"),
    cancelled: bool = False,
) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        authority_id=AUTHORITY_ID,
        revision=AUTHORITY_REVISION,
        allowed_portfolio=allowed_portfolio
        or (
            PortfolioGrant(
                provider_id="example.provider",
                application_id="alpha",
                version="1.0.0",
                runtime_id="fake.runtime",
            ),
        ),
        allowed_operations=allowed_operations,
        budget_limit=budget_limit or BudgetLimit(1000, 1000, 1000, 3000, 100_000),
        expires_at_ms=100_000,
        max_action_deadline_ms=20_000,
        max_recursion_depth=2,
        max_concurrent_children=2,
        execution_domain="restricted",
        host_service_grants=("artifact.write", "native-turn-adapter"),
        cancelled=cancelled,
    )


def make_native_client(
    scripts: Mapping[str, tuple[NativeEventDraft, ...] | BaseException],
    *,
    authority: AuthorityEnvelope | None = None,
    private_root: Path | None = None,
    directory: tempfile.TemporaryDirectory[str] | None = None,
    max_turns_per_poll: int = 10,
    max_events_per_poll: int = 20,
) -> NativeRun:
    if private_root is None:
        if directory is not None:
            raise AssertionError("native private root cannot be inferred from directory")
        directory = tempfile.TemporaryDirectory()
        private_root = Path(directory.name)
        private_root.chmod(0o700)
    recorder = _ACTIVE_RECORDER.get() or OperationRecorder()
    adapter = ScriptedNativeTurnAdapter(scripts, recorder)
    client = build_native_control_plane_client(
        ControlPlaneFactoryContext(
            system_id="research.system",
            system_version="1.0.0",
            control_plane_id=NATIVE_CONTROL_PLANE_ID,
            control_plane_version=NATIVE_CONTROL_PLANE_VERSION,
            private_root=private_root,
            options={
                "session_id": SESSION_ID,
                "generation": str(GENERATION),
                "max_turns_per_poll": str(max_turns_per_poll),
                "max_events_per_poll": str(max_events_per_poll),
                "max_record_bytes": "65536",
                "max_capsule_bytes": "65536",
                "max_total_private_bytes": "1048576",
            },
            authority=authority or native_authority(),
            host_services={"native-turn-adapter": adapter},
        )
    )
    return NativeRun(client, adapter, recorder, private_root, directory)


def _command(
    command_id: str,
    command_type: str,
    payload: Mapping[str, object],
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id=SESSION_ID,
        authority_revision=AUTHORITY_REVISION,
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
    command_id: str,
    content_ref: str,
    *,
    input_id: str,
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


def reason_command(command_id: str, command_type: str, reason_code: str) -> ControlCommand:
    return _command(command_id, command_type, {"reason_code": reason_code})


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


def checkpoint_command(command_id: str = "command-checkpoint") -> ControlCommand:
    return _command(command_id, "checkpoint.request", {"checkpoint_id": "checkpoint-1"})


def remaining_budget(**overrides: int) -> RemainingBudget:
    values = {
        "controller_tokens": 1000,
        "application_tokens": 1000,
        "child_tokens": 1000,
        "aggregate_tokens": 3000,
        "cost_micros": 100_000,
        "deadline_ms": 20_000,
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
    values["aggregate_tokens"] = values["controller_tokens"]
    return BudgetUsage(**values)


def _script_controller_usage(script: tuple[NativeEventDraft, ...]) -> int:
    for draft in script:
        if draft.type == "budget.reported":
            value = draft.payload["controller_tokens"]
            if isinstance(value, bool) or not isinstance(value, int):
                raise AssertionError("native script usage is malformed")
            return value
    return 0


def draft(event_type: str, payload: Mapping[str, object]) -> NativeEventDraft:
    return NativeEventDraft(event_type, payload)


def budget_draft(controller_tokens: int) -> NativeEventDraft:
    return draft(
        "budget.reported",
        {
            "controller_tokens": controller_tokens,
            "application_tokens": 0,
            "child_tokens": 0,
            "aggregate_tokens": controller_tokens,
            "cost_micros": 0,
        },
    )


def proposal_draft(
    action_id: str = "action-1",
    *,
    application_id: str = "alpha",
    action_kind: str = "application.invoke",
) -> NativeEventDraft:
    target: Mapping[str, object]
    if action_kind == "application.invoke":
        target = {
            "kind": "application",
            "provider_id": "example.provider",
            "application_id": application_id,
            "version": "1.0.0" if application_id == "alpha" else "2.0.0",
            "runtime_id": "fake.runtime",
        }
    elif action_kind == "checkpoint.create":
        target = {"kind": "checkpoint", "checkpoint_id": "checkpoint-1"}
    elif action_kind == "goal.complete":
        target = {"kind": "goal", "goal_id": "goal-1"}
    else:
        raise AssertionError("unsupported proposal kind")
    return draft(
        "action.proposed",
        {
            "action_id": action_id,
            "authority_revision": AUTHORITY_REVISION,
            "idempotency_key": f"idempotency-{action_id}",
            "kind": action_kind,
            "target": target,
            "input_ref": f"input-ref-{action_id}",
            "expected_artifacts": ("report.alpha",),
            "budget": {
                "controller_tokens": 0,
                "application_tokens": 10,
                "child_tokens": 0,
                "aggregate_tokens": 10,
                "cost_micros": 500,
                "deadline_ms": 10_000,
            },
            "causal_parent_ids": ("goal-1",),
        },
    )


def complete_drafts(tokens: int = 1) -> tuple[NativeEventDraft, ...]:
    return (
        budget_draft(tokens),
        draft("goal.updated", {"goal_id": "goal-1", "status": "completed"}),
        draft("session.completed", {"reason_code": "goal-accepted"}),
    )


async def collect_events(client: object, cursor: EventCursor | None = None) -> tuple[ControlEvent, ...]:
    result: list[ControlEvent] = []
    async for event in cast(object, client).events(cursor):  # type: ignore[attr-defined]
        result.append(event)
    return tuple(result)


async def send(client: object, command: ControlCommand) -> None:
    await cast(object, client).send(command)  # type: ignore[attr-defined]


async def sync(client: object, budget: RemainingBudget | None = None) -> None:
    await cast(object, client).sync_authority_snapshot(budget or remaining_budget())  # type: ignore[attr-defined]


def validate_complete_events(events: tuple[ControlEvent, ...]) -> None:
    validate_control_event_stream(tuple(event.to_mapping() for event in events))


def observation_mapping(
    identity_field: str,
    identity: str,
    recorder: OperationRecorder,
    *,
    status: str = "PASS",
) -> Mapping[str, object]:
    return {
        identity_field: identity,
        "status": status,
        **recorder.closed_counts(),
    }


async def scenario_complete() -> None:
    run = make_native_client({"input:content-ref-complete": complete_drafts(1)})
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, input_command("command-input", "content-ref-complete", input_id="input-1"))
        validate_complete_events(await collect_events(run.client))
    finally:
        await run.close()


async def scenario_pause_resume() -> None:
    run = make_native_client({"input:content-ref-complete": complete_drafts(1)})
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, reason_command("command-pause", "session.pause", "operator-request"))
        await send(run.client, reason_command("command-resume", "session.resume", "resumed"))
        await send(run.client, input_command("command-input", "content-ref-complete", input_id="input-1"))
        events = await collect_events(run.client)
        validate_complete_events(events)
        self_order = tuple(event.type for event in events)
        if self_order[2:4] != ("session.paused", "session.running"):
            raise AssertionError("pause/resume order diverged")
    finally:
        await run.close()


async def scenario_fault_recovery() -> None:
    run = make_native_client(
        {
            "input:content-ref-fault": RuntimeError("SENTINEL_SECRET"),
            "input:content-ref-complete": complete_drafts(1),
        },
        max_turns_per_poll=1,
    )
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, input_command("command-fault", "content-ref-fault", input_id="input-fault"))
        recovery = await collect_events(run.client, EventCursor(GENERATION, 2))
        if tuple(event.type for event in recovery) != ("fault.raised", "session.recovery-required"):
            raise AssertionError("native recovery events diverged")
        await send(run.client, reason_command("command-resume", "session.resume", "recovered"))
        await send(run.client, input_command("command-complete", "content-ref-complete", input_id="input-complete"))
        validate_complete_events(await collect_events(run.client))
    finally:
        await run.close()


async def scenario_checkpoint() -> None:
    run = make_native_client({"input:content-ref-complete": complete_drafts(1)})
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, checkpoint_command())
        checkpoint_events = await collect_events(run.client, EventCursor(GENERATION, 2))
        if tuple(event.type for event in checkpoint_events) != ("checkpoint.created",):
            raise AssertionError("native checkpoint event missing")
        checkpoint = checkpoint_events[0]
        if checkpoint.payload["covered_sequence"] != 2:
            raise AssertionError("native checkpoint covered sequence diverged")
        await send(run.client, input_command("command-input", "content-ref-complete", input_id="input-1"))
        validate_complete_events(await collect_events(run.client))
    finally:
        await run.close()


async def scenario_budget_limited() -> None:
    run = make_native_client({"input:content-ref-budget": complete_drafts(1)})
    try:
        await send(run.client, create_command())
        await sync(run.client, remaining_budget(controller_tokens=0, aggregate_tokens=0, deadline_ms=20_000))
        await send(run.client, input_command("command-budget", "content-ref-budget", input_id="input-budget"))
        events = await collect_events(run.client)
        validate_complete_events(events)
        if run.recorder.turn_adapter_calls != 0:
            raise AssertionError("budget-limited turn invoked adapter")
        if events[-1].type != "session.budget-limited":
            raise AssertionError("budget limit did not terminate session")
    finally:
        await run.close()


async def scenario_cancel() -> None:
    run = make_native_client({})
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, reason_command("command-cancel", "session.cancel", "operator-request"))
        events = await collect_events(run.client)
        validate_complete_events(events)
        if events[-1].type != "session.cancelled":
            raise AssertionError("cancel terminal event missing")
    finally:
        await run.close()


async def scenario_attach_replay() -> None:
    run = make_native_client({"input:content-ref-complete": complete_drafts(1)})
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, reason_command("command-detach", "session.detach", "operator-request"))
        await send(run.client, _command("command-attach", "session.attach", {"cursor": {"generation": GENERATION, "sequence": 2}}))
        await send(run.client, input_command("command-input", "content-ref-complete", input_id="input-1"))
        events = await collect_events(run.client)
        validate_complete_events(events)
        suffix = await collect_events(run.client, EventCursor(GENERATION, 2))
        if tuple(event.sequence for event in suffix) != tuple(range(3, len(events) + 1)):
            raise AssertionError("native replay suffix diverged")
    finally:
        await run.close()


async def scenario_command_idempotency() -> None:
    run = make_native_client({})
    try:
        command = create_command()
        await send(run.client, command)
        await send(run.client, command)
        before = await collect_events(run.client)
        divergent = replace(
            command,
            payload={**command.payload, "goal_ref": "goal-ref-2"},
        )
        try:
            await send(run.client, divergent)
        except Exception:
            pass
        else:
            raise AssertionError("divergent command replay was accepted")
        after = await collect_events(run.client)
        if after != before:
            raise AssertionError("divergent replay mutated native state")
    finally:
        await run.close()


async def scenario_input_delivery() -> None:
    scripts = {
        "input:content-ref-direct": (budget_draft(1),),
        "input:content-ref-steer": (budget_draft(2),),
        "input:content-ref-follow": complete_drafts(3),
    }
    run = make_native_client(scripts)
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, input_command("command-direct", "content-ref-direct", input_id="input-direct", delivery="direct"))
        await send(run.client, input_command("command-steer", "content-ref-steer", input_id="input-steer", delivery="steer"))
        await send(run.client, input_command("command-follow", "content-ref-follow", input_id="input-follow", delivery="follow_up"))
        events = await collect_events(run.client)
        validate_complete_events(events)
        deliveries = tuple(request.inputs[0].delivery for request in run.adapter.requests)
        if deliveries != ("direct", "steer", "follow_up"):
            raise AssertionError("native input deliveries diverged")
        rendered = repr(run.adapter.requests)
        if "SENTINEL_SECRET" in rendered or "prompt" in rendered:
            raise AssertionError("native input delivery leaked private content")
    finally:
        await run.close()


async def scenario_proposal_admission() -> None:
    run = make_native_client(
        {
            "input:content-ref-propose": (proposal_draft(),),
            "action:action-1:succeeded": complete_drafts(1),
        }
    )
    try:
        await send(run.client, create_command())
        await sync(run.client)
        await send(run.client, input_command("command-propose", "content-ref-propose", input_id="input-propose"))
        first = await collect_events(run.client, EventCursor(GENERATION, 2))
        if tuple(event.type for event in first) != ("action.proposed",):
            raise AssertionError("native proposal was not command-driven")
        await send(run.client, action_resolution_command("command-admit", "admitted"))
        await send(run.client, action_resolution_command("command-terminal", "succeeded", reason_code="executed", receipt_ref="receipt-1"))
        events = await collect_events(run.client)
        validate_complete_events(events)
    finally:
        await run.close()


NATIVE_SCENARIOS = {
    "attach-replay": scenario_attach_replay,
    "budget-limited": scenario_budget_limited,
    "cancel": scenario_cancel,
    "checkpoint": scenario_checkpoint,
    "command-idempotency": scenario_command_idempotency,
    "complete": scenario_complete,
    "fault-recovery": scenario_fault_recovery,
    "input-delivery": scenario_input_delivery,
    "pause-resume": scenario_pause_resume,
    "proposal-admission": scenario_proposal_admission,
}


async def run_native_conformance() -> ConformanceReport:
    if frozenset(NATIVE_SCENARIOS) != REQUIRED_PHASE0_SCENARIOS:
        raise AssertionError("native scenario identities diverged")
    passed: list[str] = []
    failed: list[str] = []
    for scenario_id in sorted(REQUIRED_PHASE0_SCENARIOS):
        try:
            await asyncio.wait_for(NATIVE_SCENARIOS[scenario_id](), timeout=3)
        except Exception as error:
            failed.append(f"{scenario_id}:{type(error).__name__}")
        else:
            passed.append(scenario_id)
    return ConformanceReport(tuple(passed), tuple(failed))


async def run_native_conformance_observations() -> tuple[Mapping[str, object], ...]:
    if frozenset(NATIVE_SCENARIOS) != REQUIRED_PHASE0_SCENARIOS:
        raise AssertionError("native scenario identities diverged")
    observations: list[Mapping[str, object]] = []
    for scenario_id in sorted(REQUIRED_PHASE0_SCENARIOS):
        recorder = OperationRecorder()
        token = _ACTIVE_RECORDER.set(recorder)
        try:
            await asyncio.wait_for(NATIVE_SCENARIOS[scenario_id](), timeout=3)
            status = "PASS"
        except Exception:
            status = "FAIL"
        finally:
            _ACTIVE_RECORDER.reset(token)
        observations.append(observation_mapping("scenario_id", scenario_id, recorder, status=status))
    return tuple(observations)


class TestNativeControlConformance(unittest.IsolatedAsyncioTestCase):
    async def test_native_provider_passes_every_phase0_scenario(self) -> None:
        report = await run_native_conformance()

        self.assertEqual(report.failed, ())
        self.assertEqual(report.passed, tuple(sorted(REQUIRED_PHASE0_SCENARIOS)))

    async def test_native_conformance_observations_are_closed_sorted_and_provider_free(
        self,
    ) -> None:
        observations = await run_native_conformance_observations()

        self.assertEqual(
            tuple(item["scenario_id"] for item in observations),
            tuple(sorted(REQUIRED_PHASE0_SCENARIOS)),
        )
        for item in observations:
            self.assertEqual(
                set(item),
                {
                    "scenario_id",
                    "status",
                    "provider_operations",
                    "model_operations",
                    "credential_reads",
                    "network_operations",
                    "application_operations",
                    "upload_operations",
                },
            )
            self.assertEqual(item["status"], "PASS")
            self.assertEqual(tuple(item[field] for field in ZERO_COUNTER_FIELDS), (0, 0, 0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
