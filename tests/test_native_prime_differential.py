from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import cast

from asterion.control.authority import BudgetLimit
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.journal import JournalCursor, MemoryCanonicalJournal
from asterion.control.protocol import (
    CONTROL_COMMAND_FIELDS,
    CONTROL_EVENT_FIELDS,
    ControlProtocolError,
)
from asterion.control.providers.native.model import NativeEventDraft
from tests.test_native_control_conformance import (
    _ACTIVE_RECORDER,
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
from tests.test_prime_verified_loop import (
    EXPECTED_IDS,
    SCENARIO_FIXTURE,
    PrimeLoopScenarioResult,
    _load_scenarios,
    run_prime_loop_scenarios,
)
from tools.setup_prime_agent import (
    ECOSYSTEM_MODULE_LOCK_FORMAT,
    HARNESS_MODULE_LOCK_FORMAT,
    LOCK_FORMAT,
    PINNED_PRIME_COMMIT,
    default_ecosystem_module_lock_path,
    default_harness_module_lock_path,
    default_lock_path,
    load_prime_artifact_lock,
    load_prime_ecosystem_module_lock,
    load_prime_harness_module_lock,
)


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
_VERIFIED_LOOP_SCENARIO_FIXTURE_SHA256 = (
    "429169c3411b4c38b42ddfa68e973e67e0356d9e9e621b2a6d7e953c9198c790"
)
_EXTERNAL_COUNTER_FIELDS = (
    "provider_operations",
    "model_operations",
    "credential_reads",
    "network_operations",
    "application_operations",
    "upload_operations",
)
_PRIME_DAEMON_APPLICATION_OPERATIONS = {
    "prime-loop-application": 1,
    "prime-loop-child": 0,
    "prime-loop-detach-attach": 0,
    "prime-loop-checkpoint": 0,
    "prime-loop-gateway-crash": 0,
    "prime-loop-supervisor-crash": 0,
    "prime-loop-worker-crash": 1,
    "prime-loop-cancel": 1,
    "prime-loop-budget": 1,
    "prime-loop-redaction": 0,
}


@dataclass(frozen=True)
class FoundationalProjection:
    lifecycle_order: tuple[str, ...]
    action_causality: tuple[tuple[str, str], ...]
    replay_suffix: tuple[str, ...]
    cumulative_usage: tuple[tuple[int, int, int, int, int], ...]
    checkpoint_shape: tuple[str, int, bool, bool] | None


@dataclass(frozen=True)
class PrimeOracleLockIdentity:
    source_commit: str
    artifact_lock_sha256: str
    harness_module_lock_sha256: str
    ecosystem_module_lock_sha256: str
    ecosystem_bundle_sha256: str


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
    action_causality = _action_causality(events, commands)
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


def _action_causality(
    events: tuple[Mapping[str, object], ...],
    commands: tuple[Mapping[str, object], ...],
) -> tuple[tuple[str, str], ...]:
    proposed_ids: list[str] = []
    seen_proposals: set[str] = set()
    for event in events:
        if event["type"] != "action.proposed":
            continue
        payload = cast(Mapping[str, object], event["payload"])
        action_id = str(payload["action_id"])
        if action_id in seen_proposals:
            raise AssertionError("action proposal is ambiguous")
        seen_proposals.add(action_id)
        proposed_ids.append(action_id)

    resolutions: dict[str, list[str]] = {action_id: [] for action_id in proposed_ids}
    action_causality: list[tuple[str, str]] = []
    terminal_resolutions = {"rejected", "succeeded", "failed", "cancelled", "uncertain"}
    for command in commands:
        if command["type"] != "action.resolve":
            continue
        payload = cast(Mapping[str, object], command["payload"])
        action_id = str(payload["action_id"])
        resolution = str(payload["resolution"])
        if action_id not in resolutions:
            raise AssertionError("action resolution references unknown proposal")
        prior = tuple(resolutions[action_id])
        if resolution == "admitted":
            if prior:
                raise AssertionError("action admission order is ambiguous")
        elif resolution == "rejected":
            if prior:
                raise AssertionError("action rejection order is ambiguous")
        elif resolution in terminal_resolutions:
            if prior != ("admitted",):
                raise AssertionError("action terminal resolution is unordered")
        else:
            raise AssertionError("action resolution is malformed")
        resolutions[action_id].append(resolution)
        action_causality.append((action_id, resolution))

    for action_id in proposed_ids:
        sequence = tuple(resolutions[action_id])
        if not sequence or sequence == ("admitted",):
            raise AssertionError("action resolution pairing is incomplete")
    return tuple(action_causality)


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


def _prime_results() -> tuple[PrimeLoopScenarioResult, ...]:
    return _prime_results_for_identity(_validate_prime_oracle_lock_identity())


@lru_cache(maxsize=1)
def _prime_results_for_identity(
    identity: PrimeOracleLockIdentity,
) -> tuple[PrimeLoopScenarioResult, ...]:
    if identity.source_commit != PINNED_PRIME_COMMIT:
        raise AssertionError("Prime oracle lock identity is invalid")
    _validate_prime_scenario_matrix()
    results = run_prime_loop_scenarios(
        fake_prime=True,
        execution_identity=identity,
        prime_source_root=_prime_source_root(),
    )
    identities = tuple(getattr(result, "scenario_id") for result in results)
    if identities != EXPECTED_IDS:
        raise AssertionError("locked Prime scenario identities diverged")
    if any(getattr(result, "status") != "PASS" for result in results):
        raise AssertionError("locked Prime scenario did not pass")
    for result in results:
        _validate_prime_result_identity(result, identity)
        _prime_external_counter_observation(result)
    return cast(tuple[PrimeLoopScenarioResult, ...], results)


def _validate_prime_oracle_lock_identity(
    *,
    artifact_lock_path: Path | None = None,
    harness_module_lock_path: Path | None = None,
    ecosystem_module_lock_path: Path | None = None,
    ecosystem_bundle_path: Path | None = None,
) -> PrimeOracleLockIdentity:
    try:
        artifact_path = artifact_lock_path or default_lock_path()
        harness_path = harness_module_lock_path or default_harness_module_lock_path()
        ecosystem_path = ecosystem_module_lock_path or default_ecosystem_module_lock_path()
        bundle_path = ecosystem_bundle_path or ecosystem_path.with_name(
            "prime-ecosystem-module.mjs"
        )
        artifact = load_prime_artifact_lock(artifact_path)
        harness = load_prime_harness_module_lock(harness_path)
        ecosystem = load_prime_ecosystem_module_lock(ecosystem_path)
        artifact_json = json.loads(artifact_path.read_text(encoding="utf-8"))
        harness_json = json.loads(harness_path.read_text(encoding="utf-8"))
        ecosystem_json = json.loads(ecosystem_path.read_text(encoding="utf-8"))
        artifact_lock_sha256 = _sha256_bytes(artifact_path.read_bytes())
        harness_module_lock_sha256 = _sha256_bytes(harness_path.read_bytes())
        ecosystem_module_lock_sha256 = _sha256_bytes(ecosystem_path.read_bytes())
        ecosystem_bundle_sha256 = _sha256_bytes(bundle_path.read_bytes())
        if (
            artifact_json.get("format") != LOCK_FORMAT
            or harness_json.get("format") != HARNESS_MODULE_LOCK_FORMAT
            or ecosystem_json.get("format") != ECOSYSTEM_MODULE_LOCK_FORMAT
            or artifact.source_commit != PINNED_PRIME_COMMIT
            or harness.source_commit != PINNED_PRIME_COMMIT
            or ecosystem.source_commit != PINNED_PRIME_COMMIT
            or ecosystem.artifact_lock_sha256 != artifact_lock_sha256
            or ecosystem.bundle_sha256 != ecosystem_bundle_sha256
        ):
            raise AssertionError("Prime oracle lock identity is invalid")
        for relative_path, digest in {
            **dict(harness.source_files),
            **dict(harness.built_modules),
        }.items():
            if artifact.files.get(relative_path) != digest:
                raise AssertionError("Prime harness module lock drifted")
        for module in ecosystem.modules:
            if (
                artifact.files.get(module.source_path) is None
                or artifact.files.get(module.built_path) != module.sha256
            ):
                raise AssertionError("Prime ecosystem module lock drifted")
        return PrimeOracleLockIdentity(
            source_commit=artifact.source_commit,
            artifact_lock_sha256=artifact_lock_sha256,
            harness_module_lock_sha256=harness_module_lock_sha256,
            ecosystem_module_lock_sha256=ecosystem_module_lock_sha256,
            ecosystem_bundle_sha256=ecosystem_bundle_sha256,
        )
    except Exception as error:
        if isinstance(error, AssertionError):
            raise
        raise AssertionError("Prime oracle lock identity is invalid") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prime_source_root() -> Path:
    return Path(__file__).resolve().parents[1] / "3th-party/prime-agent"


def _prime_oracle_identity_mapping(
    identity: PrimeOracleLockIdentity,
) -> Mapping[str, str]:
    return cast(Mapping[str, str], asdict(identity))


def _prime_oracle_identity_digest(identity: PrimeOracleLockIdentity) -> str:
    return _sha256_text(
        json.dumps(_prime_oracle_identity_mapping(identity), sort_keys=True)
    )


def _validate_prime_result_identity(
    result: PrimeLoopScenarioResult,
    identity: PrimeOracleLockIdentity,
) -> None:
    serialized = json.loads(result.serialized_observations)
    if result.evidence_id != f"evidence.phase1.{_sha256_text(result.serialized_observations)}":
        raise AssertionError("Prime result evidence digest diverged")
    identity_mapping = _prime_oracle_identity_mapping(identity)
    identity_digest = _prime_oracle_identity_digest(identity)
    if (
        serialized.get("execution_identity") != identity_mapping
        or serialized.get("execution_identity_sha256") != identity_digest
        or result.execution_identity_sha256 != identity_digest
    ):
        raise AssertionError("Prime result execution identity diverged")


def _validate_prime_scenario_matrix() -> Mapping[str, Mapping[str, object]]:
    if _sha256_bytes(SCENARIO_FIXTURE.read_bytes()) != _VERIFIED_LOOP_SCENARIO_FIXTURE_SHA256:
        raise AssertionError("Prime scenario fixture drifted")
    rows = _load_scenarios()
    if tuple(str(row["scenario_id"]) for row in rows) != EXPECTED_IDS:
        raise AssertionError("Prime scenario matrix identities diverged")
    matrix = {str(row["scenario_id"]): row for row in rows}
    if len(matrix) != len(rows):
        raise AssertionError("Prime scenario matrix identities diverged")
    return matrix


def _selected_prime_result(scenario_id: str) -> PrimeLoopScenarioResult:
    selected = tuple(result for result in _prime_results() if result.scenario_id == scenario_id)
    if len(selected) != 1:
        raise AssertionError("Prime differential scenario selection is invalid")
    return selected[0]


def _prime_external_counter_observation(
    result: PrimeLoopScenarioResult,
) -> Mapping[str, int]:
    matrix = _validate_prime_scenario_matrix()
    row = matrix.get(result.scenario_id)
    if row is None:
        raise AssertionError("Prime result scenario is not locked")
    serialized = json.loads(result.serialized_observations)
    daemon = cast(Mapping[str, object], serialized["daemon"])
    expected_model_provider = _int(row["model_provider_operations"])
    expected_application_semantic = _int(row["application_operations"])
    expected_daemon_application = _PRIME_DAEMON_APPLICATION_OPERATIONS.get(
        result.scenario_id
    )
    if expected_daemon_application is None:
        raise AssertionError("Prime result scenario is not locked")
    daemon_model_provider = _int(daemon["modelProviderOperations"])
    daemon_application_semantic = _int(daemon["applicationOperations"])
    if (
        result.provider_operations != expected_model_provider
        or daemon_model_provider != expected_model_provider
        or result.application_operations != expected_application_semantic
        or daemon_application_semantic != expected_daemon_application
    ):
        raise AssertionError("Prime result operation evidence diverged")
    if result.provider_operations != 0 or daemon_model_provider != 0:
        raise AssertionError("Prime oracle used a model provider")
    if any(not _local_process_count(key, value) for key, value in result.process_counts.items()):
        raise AssertionError("Prime oracle process evidence is malformed")
    if result.process_counts != row["process_counts"]:
        raise AssertionError("Prime oracle process evidence diverged")
    external_effects = cast(Mapping[str, object], serialized["external_effects"])
    if set(external_effects) != {
        "application_operations",
        "local_application_operations",
    }:
        raise AssertionError("Prime external application evidence is malformed")
    external_application_operations = _int(external_effects["application_operations"])
    local_application_operations = _int(external_effects["local_application_operations"])
    if (
        result.external_application_operations != external_application_operations
        or local_application_operations != result.application_operations
    ):
        raise AssertionError("Prime external application evidence diverged")
    return {
        "provider_operations": result.provider_operations,
        "model_operations": daemon_model_provider,
        "credential_reads": 0,
        "network_operations": 0,
        "application_operations": external_application_operations,
        "upload_operations": 0,
    }


def _local_process_count(key: str, value: object) -> bool:
    return (
        key in {"fake_daemon", "gateway", "worker"}
        and not isinstance(value, bool)
        and isinstance(value, int)
        and value >= 0
    )


async def observe_prime(case_id: str) -> FoundationalProjection:
    scenario_id = CASE_TO_PRIME_SCENARIO[case_id]
    results = await asyncio.to_thread(_prime_results)
    selected = tuple(result for result in results if result.scenario_id == scenario_id)
    if len(selected) != 1:
        raise AssertionError("Prime differential scenario selection is invalid")
    result = selected[0]
    _prime_external_counter_observation(result)
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
        prime = await observe_prime(case_id)
        result = await asyncio.to_thread(
            _selected_prime_result, CASE_TO_PRIME_SCENARIO[case_id]
        )
        observations.append(await native_differential_observation(case_id, prime, prime_result=result))
    return tuple(observations)


async def native_differential_observation(
    case_id: str,
    prime: FoundationalProjection,
    *,
    prime_result: PrimeLoopScenarioResult | None = None,
    recorder: OperationRecorder | None = None,
) -> Mapping[str, object]:
    native_recorder = recorder or OperationRecorder()
    token = _ACTIVE_RECORDER.set(native_recorder)
    try:
        native = await observe_native(case_id)
    finally:
        _ACTIVE_RECORDER.reset(token)
    result = prime_result or await asyncio.to_thread(
        _selected_prime_result, CASE_TO_PRIME_SCENARIO[case_id]
    )
    prime_counts = _prime_external_counter_observation(result)
    native_counts = observation_mapping("case_id", case_id, native_recorder)
    return {
        "case_id": case_id,
        "status": "PASS" if native == prime else "FAIL",
        **{
            field: _int(prime_counts[field]) + _int(native_counts[field])
            for field in _EXTERNAL_COUNTER_FIELDS
        },
    }


def _action_event(action_id: str, *, sequence: int) -> Mapping[str, object]:
    return ControlEvent(
        event_id=f"event-{sequence}",
        session_id="session-1",
        generation=1,
        sequence=sequence,
        emitted_at="2026-08-30T00:00:00Z",
        type="action.proposed",
        payload=proposal_draft(action_id).payload,
    ).to_mapping()


def _action_command(
    command_id: str,
    action_id: str,
    resolution: str,
) -> Mapping[str, object]:
    return ControlCommand(
        command_id=command_id,
        session_id="session-1",
        authority_revision=1,
        type="action.resolve",
        payload={
            "action_id": action_id,
            "resolution": resolution,
            "reason_code": "test",
            "receipt_ref": "receipt-1" if resolution == "succeeded" else None,
        },
    ).to_mapping()


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

    async def test_normalize_rejects_unknown_unordered_duplicate_or_missing_action_resolution(
        self,
    ) -> None:
        proposed = _action_event("action-1", sequence=1)
        admitted = _action_command("resolve-admit", "action-1", "admitted")
        succeeded = _action_command("resolve-succeeded", "action-1", "succeeded")

        cases = (
            ("unknown", (), (_action_command("resolve-unknown", "missing", "admitted"),)),
            ("unordered", (proposed,), (succeeded, admitted)),
            ("duplicate-proposal", (proposed, _action_event("action-1", sequence=2)), (admitted, succeeded)),
            ("duplicate-resolution", (proposed,), (admitted, admitted, succeeded)),
            ("missing-terminal", (proposed,), (admitted,)),
        )
        for label, events, commands in cases:
            with self.subTest(label=label):
                with self.assertRaises(AssertionError):
                    normalize(
                        public_events=events,
                        public_commands=commands,
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

    async def test_differential_native_observations_derive_counts_from_active_recorder(
        self,
    ) -> None:
        recorder = OperationRecorder(provider_operations=7)
        observation = await native_differential_observation(
            "lifecycle-order",
            FoundationalProjection(
                lifecycle_order=(
                    "session.created",
                    "session.running",
                    "session.recovery-required",
                    "session.running",
                ),
                action_causality=(),
                replay_suffix=(
                    "session.created",
                    "session.running",
                    "session.recovery-required",
                    "session.running",
                ),
                cumulative_usage=(),
                checkpoint_shape=None,
            ),
            recorder=recorder,
        )

        self.assertEqual(observation["provider_operations"], 7)

    async def test_prime_counter_validation_rejects_tampered_result_evidence(
        self,
    ) -> None:
        result = await asyncio.to_thread(_selected_prime_result, "prime-loop-application")
        counts = _prime_external_counter_observation(result)
        daemon = json.loads(result.serialized_observations)["daemon"]
        self.assertEqual(result.application_operations, 1)
        self.assertEqual(daemon["applicationOperations"], 1)
        self.assertEqual(
            json.loads(result.serialized_observations)["external_effects"],
            {"application_operations": 0, "local_application_operations": 1},
        )
        self.assertEqual(counts["application_operations"], 0)
        self.assertEqual(result.external_application_operations, 0)
        with self.assertRaises(AssertionError):
            _prime_external_counter_observation(
                replace(result, provider_operations=1),
            )
        with self.assertRaises(AssertionError):
            _prime_external_counter_observation(
                replace(result, application_operations=0),
            )
        tampered_serialized = json.dumps(
            {
                **json.loads(result.serialized_observations),
                "daemon": {
                    **json.loads(result.serialized_observations)["daemon"],
                    "applicationOperations": 0,
                },
            },
            sort_keys=True,
        )
        with self.assertRaises(AssertionError):
            _prime_external_counter_observation(
                replace(result, serialized_observations=tampered_serialized),
            )
        with self.assertRaises(AssertionError):
            _prime_external_counter_observation(
                replace(result, external_application_operations=1),
            )
        external_tampered_serialized = json.dumps(
            {
                **json.loads(result.serialized_observations),
                "external_effects": {
                    **json.loads(result.serialized_observations)["external_effects"],
                    "application_operations": 1,
                },
            },
            sort_keys=True,
        )
        with self.assertRaises(AssertionError):
            _prime_external_counter_observation(
                replace(result, serialized_observations=external_tampered_serialized),
            )

    async def test_prime_oracle_results_are_bound_to_executed_pinned_source_identity(
        self,
    ) -> None:
        identity = _validate_prime_oracle_lock_identity()
        results = await asyncio.to_thread(
            run_prime_loop_scenarios,
            fake_prime=True,
            execution_identity=identity,
            prime_source_root=_prime_source_root(),
        )
        identity_mapping = _prime_oracle_identity_mapping(identity)
        identity_digest = _prime_oracle_identity_digest(identity)
        for result in results:
            with self.subTest(scenario_id=result.scenario_id):
                serialized = json.loads(result.serialized_observations)
                self.assertEqual(serialized["execution_identity"], identity_mapping)
                self.assertEqual(serialized["execution_identity_sha256"], identity_digest)
                self.assertEqual(
                    result.evidence_id,
                    f"evidence.phase1.{_sha256_text(result.serialized_observations)}",
                )
                self.assertEqual(result.execution_identity_sha256, identity_digest)
                _validate_prime_result_identity(result, identity)
                with self.assertRaises(AssertionError):
                    _validate_prime_result_identity(
                        replace(result, execution_identity_sha256="0" * 64),
                        identity,
                    )
                with self.assertRaises(AssertionError):
                    _validate_prime_result_identity(
                        replace(
                            result,
                            serialized_observations=json.dumps(
                                {
                                    **serialized,
                                    "execution_identity_sha256": "0" * 64,
                                },
                                sort_keys=True,
                            ),
                        ),
                        identity,
                    )
                with self.assertRaises(AssertionError):
                    _validate_prime_result_identity(
                        replace(result, evidence_id="evidence.phase1." + ("0" * 64)),
                        identity,
                    )
                with self.assertRaises(AssertionError):
                    _validate_prime_result_identity(
                        replace(
                            result,
                            serialized_observations=json.dumps(
                                {
                                    **serialized,
                                    "otherwise_benign_top_level_tamper": True,
                                },
                                sort_keys=True,
                            ),
                        ),
                        identity,
                    )

    async def test_valid_adjacent_locks_cannot_bless_unrelated_executed_prime_source(
        self,
    ) -> None:
        identity = _validate_prime_oracle_lock_identity()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(("git", "init", "--quiet"), cwd=root, check=True)
            subprocess.run(("git", "config", "user.name", "Asterion Test"), cwd=root, check=True)
            subprocess.run(("git", "config", "user.email", "asterion@example.invalid"), cwd=root, check=True)
            subprocess.run(("git", "add", "."), cwd=root, check=True)
            subprocess.run(("git", "commit", "--quiet", "-m", "unrelated"), cwd=root, check=True)

            with self.assertRaises(AssertionError):
                await asyncio.to_thread(
                    run_prime_loop_scenarios,
                    fake_prime=True,
                    execution_identity=identity,
                    prime_source_root=root,
                )

    async def test_prime_oracle_lock_identity_rejects_commit_artifact_and_module_drift(
        self,
    ) -> None:
        _validate_prime_oracle_lock_identity()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "prime-artifact-lock.json"
            harness = root / "prime-harness-module-lock.json"
            ecosystem = root / "prime-ecosystem-module-lock.json"
            artifact.write_bytes(default_lock_path().read_bytes())
            harness.write_bytes(default_harness_module_lock_path().read_bytes())
            ecosystem.write_bytes(default_ecosystem_module_lock_path().read_bytes())
            bundle = root / "prime-ecosystem-module.mjs"
            bundle.write_bytes(default_ecosystem_module_lock_path().with_name("prime-ecosystem-module.mjs").read_bytes())

            self._mutate_json(artifact, {"source_commit": "0" * 40})
            with self.assertRaises(AssertionError):
                _validate_prime_oracle_lock_identity(
                    artifact_lock_path=artifact,
                    harness_module_lock_path=harness,
                    ecosystem_module_lock_path=ecosystem,
                    ecosystem_bundle_path=bundle,
                )

            artifact.write_bytes(default_lock_path().read_bytes())
            self._mutate_json(ecosystem, {"artifact_lock_sha256": "0" * 64})
            with self.assertRaises(AssertionError):
                _validate_prime_oracle_lock_identity(
                    artifact_lock_path=artifact,
                    harness_module_lock_path=harness,
                    ecosystem_module_lock_path=ecosystem,
                    ecosystem_bundle_path=bundle,
                )

            ecosystem.write_bytes(default_ecosystem_module_lock_path().read_bytes())
            value = json.loads(ecosystem.read_text(encoding="utf-8"))
            value["modules"][0]["sha256"] = "0" * 64
            ecosystem.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AssertionError):
                _validate_prime_oracle_lock_identity(
                    artifact_lock_path=artifact,
                    harness_module_lock_path=harness,
                    ecosystem_module_lock_path=ecosystem,
                    ecosystem_bundle_path=bundle,
                )

    def _mutate_json(self, path: Path, updates: Mapping[str, object]) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(updates)
        path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
