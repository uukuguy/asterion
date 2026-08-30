from __future__ import annotations

import asyncio
import json
import re
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from asterion.control.authority import BudgetLimit
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.providers.native.model import NativeEventDraft
from asterion.control.journal import JournalCursor, MemoryCanonicalJournal
from asterion.control.protocol import (
    CONTROL_COMMAND_FIELDS,
    CONTROL_EVENT_FIELDS,
    ControlProtocolError,
)
from tests.test_native_control_conformance import (
    OperationRecorder,
    checkpoint_command,
    collect_events,
    create_command,
    draft,
    input_command,
    make_native_client,
    observation_mapping,
    proposal_draft,
    remaining_budget,
    reason_command,
    send,
    sync,
)
from tests.test_native_control_host import close_host, make_host_with_native
from tests.test_prime_verified_loop import EXPECTED_IDS, run_prime_loop_scenarios


DIFFERENTIAL_CASES = (
    "action-causality",
    "budget-monotonicity",
    "checkpoint-identity",
    "lifecycle-order",
    "replay-suffix",
)
CASE_TO_PRIME_SCENARIO = {
    "action-causality": "prime-loop-application",
    "budget-monotonicity": "prime-loop-budget",
    "checkpoint-identity": "prime-loop-checkpoint",
    "lifecycle-order": "prime-loop-detach-attach",
    "replay-suffix": "prime-loop-detach-attach",
}
_APPROVED_JOURNAL_FIELDS = frozenset({"kind", "payload"})
_APPROVED_RECORD_KINDS = frozenset({"event.accepted", "command.accepted"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRIME_APPLICATION_ACTION_ID = "action-92c0ff0271237ad1ff9df4f009c420e3c00d5301"
_PRIME_CHILD_ACTION_ID = "action-7a181ee25e9f10b2687a7ef2089f9893f18d4a7f"
_PRIME_BUDGET_ACTION_ID = "action-cc0b999096c360568a9e5d3ce629d9fc4c86d3dc"
_PRIME_CHECKPOINT_ACTION_ID = "action-7e41756b87c5f300dcef2b20d44d32d80e0c2007"


@dataclass(frozen=True)
class FoundationalProjection:
    lifecycle_order: tuple[str, ...]
    action_causality: tuple[tuple[str, str], ...]
    replay_suffix: tuple[str, ...]
    cumulative_usage: tuple[tuple[int, int, int, int, int], ...]
    checkpoint_shape: tuple[str, int, bool, bool] | None


def normalize(
    *,
    public_events: Sequence[Mapping[str, object]],
    public_commands: Sequence[Mapping[str, object]],
    replay_after_sequence: int,
) -> FoundationalProjection:
    if (
        isinstance(replay_after_sequence, bool)
        or not isinstance(replay_after_sequence, int)
        or replay_after_sequence < 0
    ):
        raise AssertionError("replay cursor is malformed")
    events = tuple(_event(event) for event in public_events)
    commands = tuple(_command(command) for command in public_commands)
    proposed_ids = tuple(
        str(event["payload"]["action_id"])  # type: ignore[index]
        for event in events
        if event["type"] == "action.proposed"
    )
    resolutions = tuple(
        (
            str(command["payload"]["action_id"]),  # type: ignore[index]
            str(command["payload"]["resolution"]),  # type: ignore[index]
        )
        for command in commands
        if command["type"] == "action.resolve"
    )
    proposed = set(proposed_ids)
    action_causality = tuple(item for item in resolutions if item[0] in proposed)
    usage = tuple(
        _usage_tuple(cast(Mapping[str, object], event["payload"]))
        for event in events
        if event["type"] == "budget.reported"
    )
    checkpoints = tuple(event for event in events if event["type"] == "checkpoint.created")
    checkpoint_shape = None
    if len(checkpoints) > 1:
        raise AssertionError("checkpoint projection is not singular")
    if checkpoints:
        payload = cast(Mapping[str, object], checkpoints[0]["payload"])
        checkpoint_shape = (
            str(payload["checkpoint_version"]),
            _int(payload["covered_sequence"]),
            _SHA256.fullmatch(str(payload["capsule_digest"])) is not None,
            _opaque(str(payload["storage_ref"])),
        )
    return FoundationalProjection(
        lifecycle_order=tuple(str(event["type"]) for event in events),
        action_causality=action_causality,
        replay_suffix=tuple(
            str(event["type"])
            for event in events
            if _int(event["sequence"]) > replay_after_sequence
        ),
        cumulative_usage=usage,
        checkpoint_shape=checkpoint_shape,
    )


def _event(value: Mapping[str, object]) -> Mapping[str, object]:
    if set(value) != CONTROL_EVENT_FIELDS:
        raise AssertionError("public event contains unapproved fields")
    try:
        return ControlEvent.from_mapping(value).to_mapping()
    except ControlProtocolError as error:
        raise AssertionError("public event is malformed") from error


def _command(value: Mapping[str, object]) -> Mapping[str, object]:
    if set(value) != CONTROL_COMMAND_FIELDS:
        raise AssertionError("public command contains unapproved fields")
    try:
        return ControlCommand.from_mapping(value).to_mapping()
    except ControlProtocolError as error:
        raise AssertionError("public command is malformed") from error


def _usage_tuple(payload: Mapping[str, object]) -> tuple[int, int, int, int, int]:
    return (
        _int(payload["controller_tokens"]),
        _int(payload["application_tokens"]),
        _int(payload["child_tokens"]),
        _int(payload["aggregate_tokens"]),
        _int(payload["cost_micros"]),
    )


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssertionError("projection integer is malformed")
    return value


def _opaque(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and " " not in value


@lru_cache(maxsize=1)
def _prime_results() -> tuple[object, ...]:
    results = run_prime_loop_scenarios(fake_prime=True)
    identities = tuple(getattr(result, "scenario_id") for result in results)
    if identities != EXPECTED_IDS:
        raise AssertionError("locked Prime scenario identities diverged")
    if any(getattr(result, "status") != "PASS" for result in results):
        raise AssertionError("locked Prime scenario did not pass")
    if sum(int(getattr(result, "provider_operations")) for result in results) != 0:
        raise AssertionError("locked Prime oracle used model provider operations")
    return results


async def observe_prime(case_id: str) -> FoundationalProjection:
    scenario_id = CASE_TO_PRIME_SCENARIO[case_id]
    results = await asyncio.to_thread(_prime_results)
    selected = tuple(
        result for result in results if getattr(result, "scenario_id") == scenario_id
    )
    if len(selected) != 1:
        raise AssertionError("Prime differential scenario selection is invalid")
    result = selected[0]
    if int(getattr(result, "application_operations")) != 0 and scenario_id != "prime-loop-application":
        raise AssertionError("Prime provider-free scenario performed applications")
    serialized = json.loads(str(getattr(result, "serialized_observations")))
    journal = cast(Sequence[Mapping[str, object]], serialized["journal"])
    public_events: list[Mapping[str, object]] = []
    public_commands: list[Mapping[str, object]] = []
    for record in journal:
        if set(record) != _APPROVED_JOURNAL_FIELDS:
            raise AssertionError("Prime journal record contains unapproved fields")
        kind = str(record["kind"])
        if kind not in _APPROVED_RECORD_KINDS:
            continue
        payload = cast(Mapping[str, object], record["payload"])
        if kind == "event.accepted":
            public_events.append(cast(Mapping[str, object], payload["event"]))
        elif kind == "command.accepted":
            public_commands.append(cast(Mapping[str, object], payload["command"]))
    return normalize(
        public_events=public_events,
        public_commands=public_commands,
        replay_after_sequence=2 if case_id == "replay-suffix" else 0,
    )


async def observe_native(case_id: str) -> FoundationalProjection:
    if case_id == "action-causality":
        return await _observe_native_action_causality()
    if case_id == "budget-monotonicity":
        return await _observe_native_budget()
    if case_id == "checkpoint-identity":
        return await _observe_native_checkpoint()
    if case_id in {"lifecycle-order", "replay-suffix"}:
        return await _observe_native_attach(case_id)
    raise AssertionError("unknown differential case")


async def _observe_native_action_causality() -> FoundationalProjection:
    journal = MemoryCanonicalJournal("session-1")
    host, _, _ = make_host_with_native(
        {
            "input:content-ref-action": (
                proposal_draft(_PRIME_APPLICATION_ACTION_ID),
            ),
            f"action:{_PRIME_APPLICATION_ACTION_ID}:succeeded": (
                proposal_draft(_PRIME_CHILD_ACTION_ID),
            ),
            f"action:{_PRIME_CHILD_ACTION_ID}:succeeded": _terminal_drafts(),
        },
        journal=journal,
    )
    try:
        await host.dispatch(host.client_command(
            command_id="command-create",
            command_type="session.create",
            payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
        ))
        await host.dispatch(input_command("command-input", "content-ref-action", input_id="input-1"))
        await asyncio.wait_for(host.pump(until_terminal=True), timeout=3)
        return _normalize_journal(journal, replay_after_sequence=0)
    finally:
        await close_host(host)


async def _observe_native_budget() -> FoundationalProjection:
    journal = MemoryCanonicalJournal("session-1")
    host, _, _ = make_host_with_native(
        {
            "input:content-ref-action": (
                proposal_draft(_PRIME_BUDGET_ACTION_ID),
            ),
            f"action:{_PRIME_BUDGET_ACTION_ID}:rejected": (),
        },
        authority_kwargs={"budget_limit": BudgetLimit(100, 0, 100, 100, 100_000)},
        journal=journal,
    )
    try:
        await host.dispatch(host.client_command(
            command_id="command-create",
            command_type="session.create",
            payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
        ))
        await host.dispatch(input_command("command-input", "content-ref-action", input_id="input-1"))
        await asyncio.wait_for(host.pump(), timeout=3)
        return _normalize_journal(journal, replay_after_sequence=0)
    finally:
        await close_host(host)


async def _observe_native_checkpoint() -> FoundationalProjection:
    journal = MemoryCanonicalJournal("session-1")
    host, _, _ = make_host_with_native(
        {
            "input:content-ref-checkpoint": (
                proposal_draft(_PRIME_CHECKPOINT_ACTION_ID),
            ),
            f"action:{_PRIME_CHECKPOINT_ACTION_ID}:succeeded": (
                draft("session.recovery-required", {"reason_code": "checkpoint-required"}),
            ),
        },
        journal=journal,
    )
    try:
        await host.dispatch(host.client_command(
            command_id="command-create",
            command_type="session.create",
            payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
        ))
        await host.dispatch(input_command("command-input", "content-ref-checkpoint", input_id="input-1"))
        await asyncio.wait_for(host.pump(), timeout=3)
        await host.dispatch(host.client_command(
            command_id="command-resume",
            command_type="session.resume",
            payload={"reason_code": "recovered"},
        ))
        await host.dispatch(checkpoint_command())
        await asyncio.wait_for(host.pump(), timeout=3)
        return _normalize_journal(journal, replay_after_sequence=0)
    finally:
        await close_host(host)


async def _observe_native_attach(case_id: str) -> FoundationalProjection:
    run = make_native_client(
        {
            "input:content-ref-life": (
                draft("session.recovery-required", {"reason_code": "operator-request"}),
            )
        }
    )
    try:
        await send(run.client, create_command())
        await sync(run.client, remaining_budget())
        await send(run.client, input_command("command-input", "content-ref-life", input_id="input-1"))
        await collect_events(run.client, EventCursor(1, 2))
        await send(run.client, reason_command("command-resume", "session.resume", "recovered"))
        events = await collect_events(run.client)
        return normalize(
            public_events=tuple(event.to_mapping() for event in events),
            public_commands=(create_command().to_mapping(),),
            replay_after_sequence=2 if case_id == "replay-suffix" else 0,
        )
    finally:
        await run.close()


def _terminal_drafts() -> tuple[NativeEventDraft, ...]:
    return (
        draft("goal.updated", {"goal_id": "goal-1", "status": "completed"}),
        draft("session.completed", {"reason_code": "goal-accepted"}),
    )


def _normalize_journal(
    journal: MemoryCanonicalJournal,
    *,
    replay_after_sequence: int,
) -> FoundationalProjection:
    public_events: list[Mapping[str, object]] = []
    public_commands: list[Mapping[str, object]] = []
    for entry in journal.replay(JournalCursor(0)):
        if entry.record.kind == "event.accepted":
            public_events.append(_public_mapping(entry.record.payload["event"]))
        elif entry.record.kind == "command.accepted":
            public_commands.append(_public_mapping(entry.record.payload["command"]))
    return normalize(
        public_events=public_events,
        public_commands=public_commands,
        replay_after_sequence=replay_after_sequence,
    )


def _public_mapping(value: object) -> Mapping[str, object]:
    """Project mappingproxy/tuple internals back to serialized public JSON."""

    return cast(Mapping[str, object], json.loads(json.dumps(_plain_json(value))))


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain_json(item) for item in value]
    return value


async def run_native_prime_differential_observations() -> tuple[Mapping[str, object], ...]:
    observations: list[Mapping[str, object]] = []
    for case_id in sorted(DIFFERENTIAL_CASES):
        recorder = OperationRecorder()
        prime = await observe_prime(case_id)
        native = await observe_native(case_id)
        observations.append(
            observation_mapping(
                "case_id",
                case_id,
                recorder,
                status="PASS" if native == prime else "FAIL",
            )
        )
    return tuple(observations)


class TestNativePrimeDifferential(unittest.IsolatedAsyncioTestCase):
    async def test_normalize_rejects_unknown_or_malformed_public_records(self) -> None:
        valid = create_command().to_mapping()
        with self.assertRaises(AssertionError):
            normalize(
                public_events=(),
                public_commands=({**valid, "private_bytes": "forbidden"},),
                replay_after_sequence=0,
            )
        with self.assertRaises(AssertionError):
            normalize(
                public_events=(),
                public_commands=({**valid, "authority_revision": True},),
                replay_after_sequence=0,
            )

    async def test_native_matches_pinned_prime_foundational_projections(self) -> None:
        for case_id in DIFFERENTIAL_CASES:
            with self.subTest(case_id=case_id):
                prime = await observe_prime(case_id)
                native = await observe_native(case_id)
                self.assertEqual(native, prime)

    async def test_differential_observations_are_closed_sorted_and_provider_free(self) -> None:
        observations = await run_native_prime_differential_observations()

        self.assertEqual(
            tuple(item["case_id"] for item in observations),
            tuple(sorted(DIFFERENTIAL_CASES)),
        )
        for item in observations:
            self.assertEqual(
                set(item),
                {
                    "case_id",
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
            self.assertEqual(
                (
                    item["provider_operations"],
                    item["model_operations"],
                    item["credential_reads"],
                    item["network_operations"],
                    item["application_operations"],
                    item["upload_operations"],
                ),
                (0, 0, 0, 0, 0, 0),
            )


if __name__ == "__main__":
    unittest.main()
