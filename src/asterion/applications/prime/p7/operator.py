"""Operator-owned fixed model selection for the native P7 application."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import socket
import sys
import threading
from types import MappingProxyType
from typing import cast

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime import create_prime_arc_agi_3_solving_provider
from asterion.applications.prime.p7.broker import (
    ArcAction,
    ArcBroker,
    ArcBrokerError,
    ArcObservation,
    ArcRunReceipt,
    ArcStatus,
    ArcTransition,
    _observation_digest,
)
from asterion.applications.prime.p7.diagnostics import analyze_trace
from asterion.applications.prime.p7.game import (
    ArcGameContract,
    DEFAULT_GAME,
    P7GameSelection,
    P7GameSelectionError,
    TARGET_LEVEL_ENV,
    resolve_game_selection,
)
from asterion.applications.prime.p7.gameplay_trace import (
    GAMEPLAY_TRACE_IDENTITIES,
    PrimeGameplayTrace,
)
from asterion.applications.prime.p7.ipython_host import (
    PersistentIpythonHost,
    RestrictedPersistentIpythonWorker,
    p7_client_facade,
)
from asterion.applications.prime.p7 import live
from asterion.applications.prime.p7.private_trace import (
    P7PrivateTraceReceipt,
    P7_TRACE_IDENTITIES,
)
from asterion.applications.prime.p7.replay import replay_arc_run
from asterion.applications.prime.p7.score import digest, replay_sha256
from asterion.applications.prime.p7.prompt import P7_LEGACY_SOLVE_PROMPT, P7_SOLVE_PROMPT
from asterion.applications.prime.runtime_binding import PrimeLaunch
from asterion.applications.provider import InstalledApplication, resolve_installed_provider
from asterion.capabilities.prime_arc_agi_3_solver.provider import (
    CAPABILITY_REF,
    PACKAGE_REF,
    create_prime_arc_agi_3_solver_package,
)
from asterion.runner.composed import run_composed_application
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext
from asterion.runtime.pinned_extension import ExtensionBinding, ExtensionLease


_RUNTIME_ID = "asterion.prime"
_PROVIDER = "deepseek"
_MODEL = "deepseek-v4-flash"
UNBOUNDED_FIRST_ROUND_ENV = "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"
P7_HISTORY_VARIANT_ENV = "ASTERION_PRIME_P7_HISTORY_VARIANT"
_MAX_CALLBACKS = 128
_DEADLINE_MS = 3_600_000
_BRIDGE_PROTOCOL = "asterion.prime-ipython/v1"
_BRIDGE_JOIN_SECONDS = 1.0
_LEVEL_WITNESS_ONLY = "LEVEL is only available with the P7 level-witness command"

class P7OperatorError(RuntimeError):
    """The fixed P7 model host is unavailable."""


def _resolve_history_variant(
    environment: Mapping[str, str], game: P7GameSelection | ArcGameContract
) -> str:
    variant = environment.get(P7_HISTORY_VARIANT_ENV, "verified")
    if variant not in {"verified", "legacy"}:
        raise P7OperatorError("P7 history variant is unavailable")
    if variant == "legacy" and type(game) is ArcGameContract:
        raise P7OperatorError("P7 history variant is unavailable")
    return variant


def _prompt_for_variant(variant: str) -> str:
    if variant == "verified":
        return P7_SOLVE_PROMPT
    if variant == "legacy":
        return P7_LEGACY_SOLVE_PROMPT
    raise P7OperatorError("P7 history variant is unavailable")


class P7LiveAttemptFailure(live.P7LiveSolveError):
    """Public-safe evidence retained when a live attempt does not pass."""

    def __init__(
        self,
        *,
        primitive_actions: int | None,
        levels_completed: int | None,
        target_level: int,
        terminal_reason: str | None,
        replay_verified: bool,
        sealed_trace: bool,
        cleanup_complete: bool,
    ) -> None:
        reason = (
            "game over before the target level was completed"
            if terminal_reason == "game-over"
            and levels_completed is not None
            and levels_completed < target_level
            else "P7 live solve unsuccessful"
        )
        super().__init__(reason)
        self.primitive_actions = primitive_actions
        self.levels_completed = levels_completed
        self.target_level = target_level
        self.terminal_reason = terminal_reason
        self.replay_verified = replay_verified
        self.sealed_trace = sealed_trace
        self.cleanup_complete = cleanup_complete


class _BridgeSignal:
    @property
    def cancelled(self) -> bool:
        return False


class _IpythonBridgeServer:
    """Operator-owned duplex adapter between the Pi extension and host."""

    def __init__(self, channel: socket.socket, host: PersistentIpythonHost) -> None:
        self._channel = channel
        self._host = host
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._started = False

    def __repr__(self) -> str:
        return "<_IpythonBridgeServer redacted>"

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def close(self) -> None:
        self._stop.set()
        try:
            self._channel.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._channel.close()
        if self._started:
            self._thread.join(_BRIDGE_JOIN_SECONDS)

    def _serve(self) -> None:
        pending = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self._channel.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            pending.extend(chunk)
            while b"\n" in pending:
                raw, _, trailing = pending.partition(b"\n")
                pending = bytearray(trailing)
                response = self._dispatch(bytes(raw))
                try:
                    self._channel.sendall(response + b"\n")
                except OSError:
                    return

    def _dispatch(self, raw: bytes) -> bytes:
        request_id = "invalid"
        try:
            value = json.loads(raw.decode("utf-8", "strict"))
            if (
                type(value) is not dict
                or set(value) != {"code", "protocol", "request_id", "type"}
                or value["protocol"] != _BRIDGE_PROTOCOL
                or value["type"] != "execute"
                or type(value["request_id"]) is not str
                or not value["request_id"]
                or type(value["code"]) is not str
                or not value["code"]
            ):
                raise ValueError
            request_id = value["request_id"]
            result = asyncio.run(
                self._host.execute(request_id, value["code"], _BridgeSignal())
            )
            output = ""
            if result.status == "ok" and result.content:
                candidate = result.content[0].get("text")
                if type(candidate) is str:
                    output = candidate
            response = {
                "output": output,
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": result.status,
                "type": "result",
            }
        except BaseException:
            response = {
                "output": "",
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "error",
                "type": "result",
            }
        return json.dumps(response, separators=(",", ":"), sort_keys=True).encode()


class _P7BrokerClient:
    """Worker-facing mapping adapter over the native ARC broker."""

    __slots__ = ("_broker", "_recorder", "_identities", "_variant", "_counts")

    def __init__(
        self,
        broker: ArcBroker,
        recorder: PrimeTraceRecorder,
        identities: Mapping[str, str] = P7_TRACE_IDENTITIES,
        variant: str = "verified",
    ) -> None:
        if variant not in {"legacy", "verified"}:
            raise P7OperatorError("P7 host services are unavailable")
        self._broker = broker
        self._recorder = recorder
        self._identities = identities
        self._variant = variant
        self._counts = {
            "history_queries": 0, "history_records_returned": 0, "frame_queries": 0,
            "checked_plans": 0, "matched_expectations": 0, "mismatches": 0,
            "unexecuted_items": 0, "checked_plan_errors": 0, "uncertain_items": 0,
        }

    def _count(self, name: str, increment: int = 1) -> None:
        self._counts[name] = min(5000, self._counts[name] + increment)

    def private_accounting(self) -> dict[str, int]:
        """Return bounded scalar diagnostics without exposing frames or predictions."""
        return {**self._counts, "first_sequence": 0, "last_sequence": len(self._broker.journal)}

    def history(self, start: int, limit: int) -> list[dict[str, object]]:
        try:
            if type(start) is not int or type(limit) is not int:
                raise ValueError
            page = self._broker.history(start, limit)
            self._count("history_queries")
            self._count("history_records_returned", len(page))
            return page
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def frame_at(self, sequence: int) -> list[list[int]]:
        try:
            if type(sequence) is not int:
                raise ValueError
            frame = self._broker.frame_at(sequence)
            self._count("frame_queries")
            return frame
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def act_checked(self, plan: object) -> Mapping[str, object]:
        try:
            journal_start = len(self._broker.journal)
            try:
                result = self._broker.act_checked(plan)
            except Exception:
                committed = len(self._broker.journal) - journal_start
                if type(plan) is list and 1 <= len(plan) <= 20:
                    self._count("checked_plans")
                    self._count("checked_plan_errors")
                    self._count("matched_expectations", committed)
                    self._count("uncertain_items", len(plan) - committed)
                raise
            finally:
                self._record_transitions(self._broker.journal[journal_start:])
            self._count("checked_plans")
            self._count("matched_expectations", result["applied_count"])
            if result["mismatch"] is not None:
                self._count("mismatches")
                self._counts["matched_expectations"] -= 1
            self._count("unexecuted_items", result["unexecuted_count"])
            batch = result["batch"]
            observation = result["observation"]
            terminal = result["terminal"]
            return {
                "applied_count": result["applied_count"],
                "stop_reason": result["stop_reason"],
                "mismatch": result["mismatch"],
                "unexecuted_count": result["unexecuted_count"],
                "observation": self._observation_view(observation),
                "terminal": self._status_view(terminal),
                "batch": {
                    "applied_count": batch.applied_count,
                    "levels_completed": batch.levels_completed,
                    "transitions": [self._transition_view(item) for item in batch.transitions],
                },
            }
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    @staticmethod
    def _observation_view(observation: ArcObservation) -> dict[str, object]:
        return {
            "available_actions": list(observation.available_actions),
            "frame": observation.frame,
            "levels_completed": observation.levels_completed,
            "state": observation.state,
            "win_levels": observation.win_levels,
        }

    def _status_view(self, status: ArcStatus) -> dict[str, object]:
        return {
            "actions_remaining": status.actions_remaining,
            "levels_completed": status.levels_completed,
            "primitive_actions": status.primitive_actions,
            "target_level": self._broker.game.target_level,
            "terminal_reason": status.terminal_reason,
        }

    @staticmethod
    def _transition_view(transition: ArcTransition) -> dict[str, object]:
        return {
            "action": transition.action,
            "after_sha256": transition.after_sha256,
            "before_sha256": transition.before_sha256,
            "levels_completed": transition.levels_completed,
            "sequence": transition.sequence,
            **({"data": dict(transition.data)} if transition.data else {}),
        }

    def _record_transitions(self, transitions: tuple[ArcTransition, ...]) -> None:
        for transition in transitions:
            self._recorder.append(
                "arc.action", self._identities, self._transition_view(transition)
            )

    def observe(self) -> Mapping[str, object]:
        observation = self._broker.observe()
        return {
            "available_actions": list(observation.available_actions),
            "frame": observation.frame,
            "levels_completed": observation.levels_completed,
            "state": observation.state,
            "win_levels": observation.win_levels,
        }


    def status(self) -> Mapping[str, object]:
        status = self._broker.status()
        return {
            "actions_remaining": status.actions_remaining,
            "levels_completed": status.levels_completed,
            "primitive_actions": status.primitive_actions,
            "target_level": self._broker.game.target_level,
            "terminal_reason": status.terminal_reason,
        }

    def act(self, actions: object) -> Mapping[str, object]:
        if type(actions) is not list or not actions:
            raise P7OperatorError("P7 host services are unavailable")
        if self._variant == "verified" and len(actions) != 1:
            raise P7OperatorError("P7 host services are unavailable")
        validated: list[ArcAction] = []
        for action in actions:
            if (
                type(action) is not dict
                or set(action) != {"data", "name"}
                or type(action.get("name")) is not str
                or type(action.get("data")) is not dict
            ):
                raise P7OperatorError("P7 host services are unavailable")
            name = action["name"]
            data = action["data"]
            if name == "ACTION6":
                if (
                    set(data) != {"x", "y"}
                    or any(type(data[coordinate]) is not int or not 0 <= data[coordinate] <= 63 for coordinate in ("x", "y"))
                ):
                    raise P7OperatorError("P7 host services are unavailable")
                canonical_data = (("x", data["x"]), ("y", data["y"]))
            elif data == {}:
                canonical_data = ()
            else:
                raise P7OperatorError("P7 host services are unavailable")
            validated.append(ArcAction(name, canonical_data))
        prior_levels = self._broker.status().levels_completed
        result = self._broker.act(tuple(validated))
        self._record_transitions(result.transitions)
        try:
            observation = self._broker.observe()
            status = self._broker.status()
        except ArcBrokerError:
            snapshot = self._broker.terminal_snapshot()
            observation, status = snapshot.observation, snapshot.status
        return {
            "applied_count": result.applied_count,
            "level_advanced": result.levels_completed > prior_levels,
            "levels_completed": result.levels_completed,
            "observation": {
                "available_actions": list(observation.available_actions),
                "frame": observation.frame,
                "levels_completed": observation.levels_completed,
                "state": observation.state,
                "win_levels": observation.win_levels,
            },
            "terminal": {
                "actions_remaining": status.actions_remaining,
                "levels_completed": status.levels_completed,
                "primitive_actions": status.primitive_actions,
                "target_level": self._broker.game.target_level,
                "terminal_reason": status.terminal_reason,
            },
            "transitions": [
                {
                    "action": transition.action,
                    "after_sha256": transition.after_sha256,
                    "before_sha256": transition.before_sha256,
                    "levels_completed": transition.levels_completed,
                    "sequence": transition.sequence,
                    **({"data": dict(transition.data)} if transition.data else {}),
                }
                for transition in result.transitions
            ],
        }


def _apply_saved_prefix(
    broker: ArcBroker,
    recorder: PrimeTraceRecorder,
    transitions: tuple[ArcTransition, ...],
) -> None:
    """Re-execute a verified prefix into this run's broker and private trace."""

    if not transitions or any(type(item) is not ArcTransition for item in transitions):
        raise P7OperatorError("P7 saved prefix is unavailable")
    try:
        if len(broker.history(0, 1)) != 1 or broker.history(0, 1)[0]["sequence"] != 0:
            raise ValueError
        client = _P7BrokerClient(broker, recorder, variant="verified")
        for expected in transitions:
            if (
                expected.sequence != len(broker.journal) + 1
                or _observation_digest(broker.observe()) != expected.before_sha256
            ):
                raise ValueError
            client.act([{"name": expected.action, "data": dict(expected.data)}])
            if broker.journal[-1] != expected:
                raise ValueError
            record = broker.history(expected.sequence, 1)[0]
            if (
                record["sequence"] != expected.sequence
                or record["before_state_sha256"] != expected.before_sha256
                or record["after_state_sha256"] != expected.after_sha256
                or record["levels_completed"] != expected.levels_completed
                or broker.frame_at(expected.sequence)
                != [list(row) for row in broker.observe().frame[-1]]
            ):
                raise ValueError
        if broker.history(transitions[-1].sequence, 1)[0]["sequence"] != len(transitions):
            raise ValueError
        if broker.status().levels_completed != transitions[-1].levels_completed:
            raise ValueError
    except Exception:
        raise P7OperatorError("P7 saved prefix is unavailable") from None


def _seal_verified_partial_run(
    broker: ArcBroker,
    evidence: P7PrivateTraceReceipt,
    arc_root: Path,
    private: Path,
) -> dict[str, object] | None:
    """Retain completed levels when a later solve step fails."""

    if not evidence.matches_runtime_broker(broker):
        return None
    try:
        journal = broker.journal
        recorded_actions = tuple(
            entry.payload
            for entry in evidence.runtime_recorder.snapshot()
            if entry.kind == "arc.action"
        )
        if len(recorded_actions) != len(journal) or any(
            row.get("sequence") != item.sequence
            or row.get("action") != item.action
            or row.get("before_sha256") != item.before_sha256
            or row.get("after_sha256") != item.after_sha256
            or row.get("levels_completed") != item.levels_completed
            or row.get("data", {}) != dict(item.data)
            for row, item in zip(recorded_actions, journal)
        ):
            return None
        level = max(item.levels_completed for item in journal)
        if not 0 < level < broker.game.win_levels:
            return None
        stop = next(index for index, item in enumerate(journal, 1) if item.levels_completed == level)
        prefix = journal[:stop]
        game = replace(broker.game, target_level=level)
        receipt = ArcRunReceipt(
            game.game_id,
            game.seed,
            len(prefix),
            level,
            "level-completed",
            replay_sha256(prefix, terminal_reason="level-completed"),
        )
        replay_arc_run(
            prefix,
            receipt,
            lambda: live.ArcadeEngine(
                arc_root=arc_root,
                recordings_dir=private / "prefix-replay-recordings",
                game=game,
            ),
            game=game,
        )
        payload = {
            "game_id": receipt.game_id,
            "seed": receipt.seed,
            "win_levels": game.win_levels,
            "levels_completed": receipt.levels_completed,
            "primitive_actions": receipt.primitive_actions,
            "replay_sha256": receipt.replay_sha256,
            "terminal_reason": receipt.terminal_reason,
        }
        evidence.runtime_recorder.append(
            "arc.run.partial",
            P7_TRACE_IDENTITIES,
            payload,
        )
        evidence.runtime_recorder.seal()
        return payload
    except Exception:
        return None


def _seal_replay_verified_first_level_failure(
    broker: ArcBroker,
    evidence: P7PrivateTraceReceipt,
    receipt: ArcRunReceipt,
) -> bool:
    """Seal a replayed terminal failure without publishing reusable progress."""

    if not evidence.matches_runtime_broker(broker):
        return False
    try:
        journal = broker.journal
        recorded_actions = tuple(
            entry.payload
            for entry in evidence.runtime_recorder.snapshot()
            if entry.kind == "arc.action"
        )
        if (
            broker.game.target_level != 1
            or receipt != broker.seal()
            or receipt.levels_completed != 0
            or receipt.terminal_reason
            not in {"action-cap", "game-over", "human-baseline"}
            or len(recorded_actions) != len(journal)
            or any(
                row.get("sequence") != item.sequence
                or row.get("action") != item.action
                or row.get("before_sha256") != item.before_sha256
                or row.get("after_sha256") != item.after_sha256
                or row.get("levels_completed") != item.levels_completed
                or row.get("data", {}) != dict(item.data)
                for row, item in zip(recorded_actions, journal)
            )
        ):
            return False
        evidence.runtime_recorder.append(
            "arc.run.failed",
            P7_TRACE_IDENTITIES,
            {
                "game_id": receipt.game_id,
                "seed": receipt.seed,
                "win_levels": broker.game.win_levels,
                "levels_completed": receipt.levels_completed,
                "primitive_actions": receipt.primitive_actions,
                "replay_sha256": receipt.replay_sha256,
                "terminal_reason": receipt.terminal_reason,
            },
        )
        evidence.runtime_recorder.seal()
        return True
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class P7RuntimeSelection:
    runtime_id: str
    provider: str
    model: str
    max_actions: int
    max_callbacks: int | None
    deadline_ms: int | None
    unbounded_first_round: bool = False

    def __post_init__(self) -> None:
        if (
            self.runtime_id != _RUNTIME_ID
            or self.provider != _PROVIDER
            or self.model != _MODEL
            or type(self.max_actions) is not int
            or not 1 <= self.max_actions <= 5000
            or type(self.unbounded_first_round) is not bool
            or (self.max_callbacks, self.deadline_ms) != (
                (None, None) if self.unbounded_first_round else (_MAX_CALLBACKS, _DEADLINE_MS)
            )
        ):
            raise P7OperatorError("P7 runtime selection is invalid")

    @classmethod
    def fixed(cls, game: P7GameSelection | ArcGameContract = DEFAULT_GAME) -> P7RuntimeSelection:
        value = object.__new__(cls)
        object.__setattr__(value, "runtime_id", _RUNTIME_ID)
        object.__setattr__(value, "provider", _PROVIDER)
        object.__setattr__(value, "model", _MODEL)
        object.__setattr__(value, "max_actions", game.action_cap)
        object.__setattr__(value, "max_callbacks", _MAX_CALLBACKS)
        object.__setattr__(value, "deadline_ms", _DEADLINE_MS)
        object.__setattr__(value, "unbounded_first_round", False)
        return value


@dataclass(frozen=True, repr=False, slots=True)
class P7OperatorResources:
    """Concrete preflighted resources owned by one operator invocation."""

    host_services: Mapping[str, object]
    runtime_options: Mapping[str, str]
    _bridge: _IpythonBridgeServer
    _prediction_client: _P7BrokerClient | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "host_services", MappingProxyType(dict(self.host_services))
        )
        object.__setattr__(
            self, "runtime_options", MappingProxyType(dict(self.runtime_options))
        )

    def __repr__(self) -> str:
        return "<P7OperatorResources redacted>"

    async def close(self) -> None:
        """Boundedly release all resources retained by the operator."""

        ipython = cast(PersistentIpythonHost, self.host_services["prime.ipython"])
        trace = self.host_services.get("prime.private-trace") or self.host_services.get("prime.arc-run-evidence")
        launch = cast(PrimeLaunch, self.host_services["prime.launch"])
        try:
            self._bridge.close()
        finally:
            try:
                await ipython.close()
            finally:
                try:
                    if trace is None:
                        raise P7OperatorError("P7 host services are unavailable")
                    trace.close()
                finally:
                    launch.extension_lease.close()


def resolve_pi_provider(environment: Mapping[str, str], *, model: str) -> str:
    """Resolve only the fixed DeepSeek host from passed operator environment."""

    try:
        available = (
            isinstance(environment, Mapping)
            and model == _MODEL
            and bool(environment.get("DEEPSEEK_API_KEY", "").strip())
        )
    except Exception:
        available = False
    if not available:
        raise P7OperatorError("P7 model host is unavailable") from None
    return _PROVIDER


def resolve_p7_runtime(
    environment: Mapping[str, str], game: P7GameSelection | ArcGameContract = DEFAULT_GAME
) -> P7RuntimeSelection:
    """Resolve the one fixed model/runtime preset without exposing tuning knobs."""

    provider = resolve_pi_provider(environment, model=_MODEL)
    unbounded = UNBOUNDED_FIRST_ROUND_ENV in environment
    if unbounded and (
        environment[UNBOUNDED_FIRST_ROUND_ENV] != "1"
        or environment.get("ASTERION_PRIME_P7_RUN_MODE") != "sweep"
        or environment.get("OPERATION_MODE", "").lower() != "offline"
        or type(game) is not P7GameSelection
        or game.action_cap_override is None
    ):
        raise P7OperatorError("P7 first-round runtime mode is invalid")
    return P7RuntimeSelection(
        runtime_id=_RUNTIME_ID,
        provider=provider,
        model=_MODEL,
        max_actions=game.action_cap,
        max_callbacks=None if unbounded else _MAX_CALLBACKS,
        deadline_ms=None if unbounded else _DEADLINE_MS,
        unbounded_first_round=unbounded,
    )


def p7_runtime_options(
    selection: P7RuntimeSelection, game: P7GameSelection | ArcGameContract = DEFAULT_GAME
) -> Mapping[str, str]:
    """Return immutable private factory options for the fixed selection."""

    if (
        type(selection) is not P7RuntimeSelection
        or selection != replace(
            P7RuntimeSelection.fixed(game),
            max_callbacks=None if selection.unbounded_first_round else _MAX_CALLBACKS,
            deadline_ms=None if selection.unbounded_first_round else _DEADLINE_MS,
            unbounded_first_round=selection.unbounded_first_round,
        )
        or (selection.unbounded_first_round and (
            type(game) is not P7GameSelection or game.action_cap_override is None
        ))
    ):
        raise P7OperatorError("P7 runtime selection is invalid")
    return MappingProxyType(
        {
            "deadline_ms": "none" if selection.deadline_ms is None else str(selection.deadline_ms),
            "max_actions": str(selection.max_actions),
            "max_callbacks": "none" if selection.max_callbacks is None else str(selection.max_callbacks),
            "model": selection.model,
            "provider": selection.provider,
        }
    )


def _private_experiment(
    variant: str, game: P7GameSelection, runtime_options: Mapping[str, str]
) -> dict[str, object]:
    """Project the selected runtime controls into private scalar evidence."""
    deadline = runtime_options.get("deadline_ms")
    return {
        "prediction_variant": variant,
        "model": _MODEL,
        "game_id": game.game_id,
        "seed": game.seed,
        "target_level": game.target_level,
        "action_cap": game.action_cap,
        "deadline_ms": int(deadline) if deadline is not None and deadline.isdecimal() else None,
        "stall_seconds": None,
    }


def build_p7_operator_resources(
    *,
    environment: Mapping[str, str],
    pi_base_command: tuple[str, ...],
    extension_path: Path,
    working_directory: Path,
    worker: RestrictedPersistentIpythonWorker,
    engine: object,
    private_trace_root: Path,
    game: P7GameSelection | ArcGameContract = DEFAULT_GAME,
    run_id: str | None = None,
) -> P7OperatorResources:
    """Preflight the exact native P7 host-service closure from injected edges."""

    lease: ExtensionLease | None = None
    parent: socket.socket | None = None
    child: socket.socket | None = None
    trace: PrimeTraceRecorder | None = None
    bridge: _IpythonBridgeServer | None = None
    try:
        variant = _resolve_history_variant(environment, game)
        selection = resolve_p7_runtime(environment, game)
        # The ARC credential belongs only to the SDK session. The Pi model
        # subprocess needs the model host key, never the scorecard key.
        provider_environment = {
            name: value for name, value in environment.items()
            if name not in {"ARC_API_KEY", "ARC_BASE_URL", "OPERATION_MODE", P7_HISTORY_VARIANT_ENV}
        }
        if (
            type(pi_base_command) is not tuple
            or not pi_base_command
            or any(
                type(part) is not str or not part or "\x00" in part
                for part in pi_base_command
            )
            or any(
                option in pi_base_command
                for option in ("--extension", "--model", "--provider")
            )
            or not isinstance(extension_path, Path)
            or extension_path.resolve(strict=True) != extension_path
            or not isinstance(working_directory, Path)
            or working_directory.resolve(strict=True) != working_directory
            or not working_directory.is_dir()
            or not isinstance(private_trace_root, Path)
            or private_trace_root.resolve(strict=True) != private_trace_root
            or not private_trace_root.is_dir()
            or any(
                type(name) is not str
                or not name
                or "\x00" in name
                or type(value) is not str
                or "\x00" in value
                for name, value in provider_environment.items()
            )
        ):
            raise ValueError
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        descriptor = child.fileno()
        binding = ExtensionBinding(
            extension_id="prime.ipython",
            path=extension_path,
            capabilities=("prime.tool.ipython",),
            inherited_fds=(descriptor,),
            environment={"ASTERION_PRIME_IPYTHON_FD": str(descriptor)},
        )
        lease = binding.preflight()
        child.close()
        child = None
        if set(provider_environment).intersection(lease.environment):
            raise ValueError
        approved_environment = {**provider_environment, **dict(lease.environment)}
        command = (
            *pi_base_command,
            "--provider",
            selection.provider,
            "--model",
            selection.model,
            *lease.command_args(),
        )
        launch = PrimeLaunch(
            approved_command=command,
            working_directory=working_directory,
            extension_id=binding.extension_id,
            extension_path=extension_path,
            extension_capabilities=binding.capabilities,
            binding_inherited_fds=binding.inherited_fds,
            binding_environment=dict(binding.environment),
            extension_lease=lease,
            deadline_seconds=None if selection.deadline_ms is None else selection.deadline_ms / 1000,
            compact_events=True,
            approved_environment=approved_environment,
        )
        trace = PrimeTraceRecorder(private_trace_root)
        broker = ArcBroker(engine=engine, game=game)
        history_run_id = private_trace_root.parent.name
        if (
            type(history_run_id) is not str or not history_run_id
            or not history_run_id.isascii()
            or (run_id is not None and run_id != history_run_id)
        ):
            raise ValueError
        broker.bind_history(history_run_id)
        official = type(game) is ArcGameContract
        prediction_client = _P7BrokerClient(
            broker,
            trace,
            GAMEPLAY_TRACE_IDENTITIES if official else P7_TRACE_IDENTITIES,
            variant=variant,
        )
        ipython = PersistentIpythonHost(
            worker=worker,
            p7_client=p7_client_facade(prediction_client),
        )
        private_trace = (
            PrimeGameplayTrace(broker, trace, engine.guid)
            if official else P7PrivateTraceReceipt(broker, trace)
        )
        bridge = _IpythonBridgeServer(parent, ipython)
        bridge.start()
        parent = None
        return P7OperatorResources(
            host_services={
                "prime.arc-broker": broker,
                "prime.ipython": ipython,
                "prime.launch": launch,
                (
                    "prime.arc-run-evidence" if official else "prime.private-trace"
                ): private_trace,
            },
            runtime_options=p7_runtime_options(selection, game),
            _bridge=bridge,
            _prediction_client=prediction_client,
        )
    except Exception:
        if bridge is not None:
            bridge.close()
        if trace is not None:
            trace.close()
        if child is not None:
            child.close()
        if parent is not None:
            parent.close()
        if lease is not None:
            lease.close()
        raise P7OperatorError("P7 host services are unavailable") from None


@dataclass(frozen=True, slots=True)
class P7Invocation:
    """Every operator-owned value one preset invocation resolves to."""

    operator_root: Path
    environment: Mapping[str, str]
    arc_root: Path
    pi_base_command: tuple[str, ...]
    extension_path: Path
    game: P7GameSelection
    sweep_mode: bool = False


def _select_game_for_mode(
    process_environment: Mapping[str, str],
    resolved_environment: Mapping[str, str],
    arc_root: Path,
) -> P7GameSelection:
    """Use only an explicitly forwarded level; otherwise solve the full game."""

    mode = process_environment.get("ASTERION_PRIME_P7_RUN_MODE", "solve")
    if mode not in {"solve", "witness", "sweep"}:
        raise P7OperatorError("P7 run mode is unavailable")
    if mode == "witness" and TARGET_LEVEL_ENV not in process_environment:
        raise P7OperatorError("P7 level witness requires explicit LEVEL")
    if mode == "sweep" and TARGET_LEVEL_ENV not in process_environment:
        raise P7OperatorError("P7 sweep requires explicit LEVEL")
    selection_environment = dict(resolved_environment)
    if TARGET_LEVEL_ENV in process_environment:
        selection_environment[TARGET_LEVEL_ENV] = process_environment[TARGET_LEVEL_ENV]
    else:
        selection_environment.pop(TARGET_LEVEL_ENV, None)
    return resolve_game_selection(selection_environment, arc_root)


def _preflight(environment: Mapping[str, str]) -> P7Invocation:
    """Refuse source execution, then resolve every operator-owned input.

    Mirrors the P1 operator contract: the operator root is the mounted
    checkout, and the running distribution must be installed outside it so a
    source tree can never be executed in its place. The ARC root, node
    executable and Pi entry are operator-owned values the preset exports, so
    nothing here derives a path from a sibling checkout layout.
    """

    import asterion

    root = Path(environment[live.OPERATOR_ROOT_ENV]).resolve(strict=True)
    package = Path(str(asterion.__file__)).resolve(strict=True)
    if package.is_relative_to(root) or "site-packages" not in package.parts:
        raise P7OperatorError("P7 operator root is invalid")
    if not root.is_dir():
        raise P7OperatorError("P7 operator root is invalid")
    try:
        resolved = dict(live.load_operator_environment(root))
        resolved.pop(UNBOUNDED_FIRST_ROUND_ENV, None)
        if UNBOUNDED_FIRST_ROUND_ENV in environment:
            if (
                environment[UNBOUNDED_FIRST_ROUND_ENV] != "1"
                or environment.get("ASTERION_PRIME_P7_RUN_MODE") != "sweep"
                or environment.get("OPERATION_MODE", "").lower() != "offline"
            ):
                raise P7OperatorError("P7 first-round runtime mode is invalid")
            resolved[UNBOUNDED_FIRST_ROUND_ENV] = "1"
            resolved["ASTERION_PRIME_P7_RUN_MODE"] = "sweep"
            resolved["OPERATION_MODE"] = "offline"
        arc_root = live.resolve_arc_root(resolved)
        return P7Invocation(
            operator_root=root,
            environment=resolved,
            arc_root=arc_root,
            pi_base_command=live.pi_base_command(
                node=live.resolve_node(resolved),
                pi_entry=live.resolve_pi_entry(resolved),
            ),
            extension_path=live.extension_path(),
            game=_select_game_for_mode(environment, resolved, arc_root),
            sweep_mode=environment.get("ASTERION_PRIME_P7_RUN_MODE") == "sweep",
        )
    except (live.P7LiveSolveError, P7GameSelectionError, P7OperatorError) as error:
        raise P7OperatorError(str(error)) from None


def _resolve_p7_application() -> InstalledApplication:
    """Resolve only P7 against the one package this live route owns."""

    provider = resolve_installed_provider(
        create_prime_arc_agi_3_solving_provider(),
        runtime_factories=default_runtime_factory_registry(),
        installed_packages=(create_prime_arc_agi_3_solver_package(),),
    )
    return provider.applications[0]


def _sweep_game(game: P7GameSelection, prefix: object) -> P7GameSelection:
    """Bound one OFFLINE attempt to the next level's human action baseline."""

    from .solutions import VerifiedPrefix

    if game.action_cap_override is not None:
        raise P7OperatorError("P7 sweep selection is unavailable")
    if game.target_level == 1:
        if prefix is not None:
            raise P7OperatorError("P7 sweep prefix is unavailable")
        prefix_actions = 0
    elif (
        type(prefix) is VerifiedPrefix
        and prefix.game_id == game.game_id
        and prefix.seed == game.seed
        and prefix.win_levels == game.win_levels
        and prefix.levels_completed == game.target_level - 1
    ):
        prefix_actions = len(prefix.transitions)
    else:
        raise P7OperatorError("P7 sweep prefix is unavailable")
    action_cap = prefix_actions + game.baseline_actions[game.target_level - 1]
    if action_cap > 5000:
        raise P7OperatorError("P7 sweep action budget is unavailable")
    return replace(game, action_cap_override=action_cap)


async def run_live(invocation: P7Invocation, run_id: str) -> live.P7LiveExecution:
    """Run the one fixed solve and seal its private evidence.

    Recovered from the removed driver's live body, with the orchestration order
    unchanged: preflight every host service, run the composed application, seal
    and replay the broker, verify the sealed trace, then compare, and always
    release. Only the value sources differ; see
    :mod:`asterion.applications.prime.p7.live`.
    """

    from .solutions import load_best_prefix

    variant = _resolve_history_variant(invocation.environment, invocation.game)

    root = invocation.operator_root
    prefix = (
        load_best_prefix(
            invocation.arc_root,
            root / ".asterion-private" / "prime-p7-live",
            invocation.game.game_id,
            invocation.game.seed,
            max_level=invocation.game.target_level - 1,
        )
        if invocation.game.target_level > 1 else None
    )
    if invocation.sweep_mode:
        invocation = replace(invocation, game=_sweep_game(invocation.game, prefix))
    private = live.private_root(root, run_id)
    trace_root = private / "trace"
    trace_root.mkdir(mode=0o700)
    worker = live.SubprocessPythonWorker(root=private)
    engine = live.ArcadeEngine(
        arc_root=invocation.arc_root,
        recordings_dir=private / "recordings",
        game=invocation.game,
    )
    print("[asterion-prime-p7] preflight", file=sys.stderr, flush=True)
    resources_ = build_p7_operator_resources(
        environment=invocation.environment,
        pi_base_command=invocation.pi_base_command,
        extension_path=invocation.extension_path,
        working_directory=root,
        worker=worker,
        engine=engine,
        private_trace_root=trace_root,
        game=invocation.game,
        run_id=run_id,
    )
    receipt: Mapping[str, object] = {}
    broker_receipt: ArcRunReceipt | None = None
    replay_verified = False
    sealed_trace = False
    cleanup_complete = False
    comparison_report: Path | None = None
    reason: str | None = None
    failure: BaseException | None = None
    diagnostics: dict[str, object] = {}
    diagnostics["prediction_variant"] = variant
    if invocation.sweep_mode:
        diagnostics["sweep"] = {
            "scope": "offline-research",
            "target_level": invocation.game.target_level,
            "prefix_actions": 0 if prefix is None else len(prefix.transitions),
            "level_action_cap": invocation.game.baseline_actions[invocation.game.target_level - 1],
            "run_action_cap": invocation.game.action_cap,
        }
    broker_status = None
    completed_prefix: dict[str, object] | None = None
    try:
        if invocation.game.target_level > 1:
            if prefix is not None:
                broker = resources_.host_services["prime.arc-broker"]
                evidence = resources_.host_services["prime.private-trace"]
                if (
                    type(broker) is not ArcBroker
                    or type(evidence) is not P7PrivateTraceReceipt
                    or prefix.game_id != invocation.game.game_id
                    or prefix.seed != invocation.game.seed
                    or prefix.win_levels != invocation.game.win_levels
                    or not 0 < prefix.levels_completed < invocation.game.target_level
                ):
                    raise P7OperatorError("P7 saved prefix is unavailable")
                _apply_saved_prefix(broker, evidence.runtime_recorder, prefix.transitions)
                if broker.status().levels_completed != prefix.levels_completed:
                    raise P7OperatorError("P7 saved prefix is unavailable")
        print("[asterion-prime-p7] live-run", file=sys.stderr, flush=True)
        application = _resolve_p7_application()
        assembly = application.assemblies[0]
        runtime = assembly.runtime_binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=assembly.path,
                options=resources_.runtime_options,
                host_services=resources_.host_services,
            )
        )
        result = await run_composed_application(
            assembly.plan,
            implementations=application.implementations,
            runtime=runtime,
            run_id=run_id,
            input_text=_prompt_for_variant(variant),
            host_services=resources_.host_services,
            implementation_packages={CAPABILITY_REF: PACKAGE_REF},
            signal=live.NeverCancelled(),
        )
        receipt = live.receipt_value(result.artifacts)
        broker = resources_.host_services["prime.arc-broker"]
        if not isinstance(broker, ArcBroker):
            raise live.P7LiveSolveError("P7 broker is unavailable")
        broker_receipt = broker.seal()
        broker.replay(
            lambda: live.ArcadeEngine(
                arc_root=invocation.arc_root,
                recordings_dir=private / "replay-recordings",
                game=invocation.game,
            )
        )
        replay_verified = True
        analyze_trace(live.read_trace_entries(trace_root))
        sealed_trace = True
        comparison_report = live.compare_if_available(root, trace_root, private)
    except Exception as error:
        failure = error
        reason = (
            str(error)
            if isinstance(error, live.P7LiveSolveError)
            else "P7 live solve unsuccessful"
        )
    finally:
        try:
            broker_value = resources_.host_services.get("prime.arc-broker")
            if isinstance(broker_value, ArcBroker):
                try:
                    try:
                        status = broker_value.status()
                    except ArcBrokerError:
                        status = broker_value.terminal_snapshot().status
                    broker_status = status
                    diagnostics["broker_status"] = {
                        "actions_remaining": status.actions_remaining,
                        "levels_completed": status.levels_completed,
                        "primitive_actions": status.primitive_actions,
                        "target_level": invocation.game.target_level,
                        "terminal_reason": status.terminal_reason,
                    }
                except Exception:
                    pass
                if broker_receipt is None:
                    try:
                        broker_receipt = broker_value.seal()
                    except Exception:
                        pass
                if broker_receipt is not None and not replay_verified:
                    try:
                        broker_value.replay(
                            lambda: live.ArcadeEngine(
                                arc_root=invocation.arc_root,
                                recordings_dir=private / "replay-recordings",
                                game=invocation.game,
                            )
                        )
                        replay_verified = True
                    except Exception:
                        pass
                evidence_value = resources_.host_services.get("prime.private-trace")
                if (
                    failure is not None
                    and not sealed_trace
                    and type(evidence_value) is P7PrivateTraceReceipt
                ):
                    completed_prefix = _seal_verified_partial_run(
                        broker_value, evidence_value, invocation.arc_root, private
                    )
                    if completed_prefix is not None:
                        replay_verified = True
                        sealed_trace = True
                    elif (
                        replay_verified
                        and broker_receipt is not None
                        and _seal_replay_verified_first_level_failure(
                            broker_value, evidence_value, broker_receipt
                        )
                    ):
                        sealed_trace = True
            # The launch seam carries plain data only, so there is no live Pi
            # session object left to read a failure or an stderr tail from.
            diagnostics["worker_cell_count"] = live.worker_cell_count(private)
            cleanup_failed = False
            try:
                await resources_.close()
            except Exception as error:
                cleanup_failed = True
                if failure is None:
                    failure = error
                    reason = "P7 live solve unsuccessful"
            try:
                engine.close()
            except Exception as error:
                cleanup_failed = True
                if failure is None:
                    failure = error
                    reason = "P7 live solve unsuccessful"
            cleanup_complete = worker.closed and not cleanup_failed
        finally:
            live.write_summary(
                root,
                private,
                run_id=run_id,
                receipt=receipt,
                broker_receipt=broker_receipt,
                game=invocation.game,
                replay_verified=replay_verified,
                sealed_trace=sealed_trace,
                cleanup_complete=cleanup_complete,
                comparison_report=comparison_report,
                reason=reason,
                failure=failure,
                diagnostics=diagnostics,
                completed_prefix=completed_prefix,
                experiment=_private_experiment(variant, invocation.game, resources_.runtime_options),
                prediction_accounting=(
                    resources_._prediction_client.private_accounting()
                    if isinstance(resources_, P7OperatorResources)
                    and resources_._prediction_client is not None
                    else None
                ),
            )
    if failure is not None:
        raise P7LiveAttemptFailure(
            primitive_actions=None if broker_status is None else broker_status.primitive_actions,
            levels_completed=None if broker_status is None else broker_status.levels_completed,
            target_level=invocation.game.target_level,
            terminal_reason=(
                broker_receipt.terminal_reason
                if broker_receipt is not None
                else None if broker_status is None else broker_status.terminal_reason
            ),
            replay_verified=replay_verified,
            sealed_trace=sealed_trace,
            cleanup_complete=cleanup_complete,
        ) from None
    return live.P7LiveExecution(
        run_id=run_id,
        completed_level_count=int(receipt.get("completed_level_count", 0)),
        primitive_action_count=int(receipt.get("primitive_action_count", 0)),
        replay_verified=replay_verified,
        sealed_trace=sealed_trace,
        cleanup_complete=cleanup_complete,
        trace_root=trace_root,
        receipt=receipt,
        comparison_report=comparison_report,
        game=invocation.game,
        broker_replay_sha256=broker_receipt.replay_sha256,
        terminal_reason=broker_receipt.terminal_reason,
    )


def classify_live_result(result: live.P7LiveExecution) -> Mapping[str, object]:
    """Project one completed solve into the public receipt, or fail closed."""

    if result.completed_level_count != result.game.target_level:
        raise live.P7LiveSolveError("target level completion was not observed")
    if not 1 <= result.primitive_action_count <= result.game.action_cap:
        raise live.P7LiveSolveError("primitive action count is invalid")
    if result.game.is_full_game and result.terminal_reason != "game-won":
        raise live.P7LiveSolveError("full-game WIN was not observed")
    if not result.replay_verified:
        raise live.P7LiveSolveError("replay verification did not pass")
    if not result.sealed_trace:
        raise live.P7LiveSolveError("sealed trace was not verified")
    if not result.cleanup_complete:
        raise live.P7LiveSolveError("cleanup did not complete")
    return _public_receipt(
        "PASS",
        result.run_id,
        receipt=result.receipt,
        completed_level_count=result.completed_level_count,
        primitive_action_count=result.primitive_action_count,
        replay_verified=result.replay_verified,
        sealed_trace=result.sealed_trace,
        cleanup_complete=result.cleanup_complete,
        comparison_report=result.comparison_report,
        game=result.game,
        broker_replay_sha256=result.broker_replay_sha256,
    )


def _public_receipt(
    status: str,
    run_id: str,
    *,
    receipt: Mapping[str, object] | None = None,
    completed_level_count: int | None = None,
    primitive_action_count: int | None = None,
    replay_verified: bool = False,
    sealed_trace: bool = False,
    cleanup_complete: bool = False,
    comparison_report: Path | None = None,
    reason: str | None = None,
    terminal_reason: str | None = None,
    game: P7GameSelection = DEFAULT_GAME,
    broker_replay_sha256: str | None = None,
) -> Mapping[str, object]:
    """Build the one public receipt; private evidence never crosses this line."""

    source = {} if receipt is None else receipt
    safe: dict[str, object] = {
        "schema": "asterion.prime.p7-live-receipt/v1",
        "application_id": "prime.arc-agi-3-solving",
        "runtime_id": "asterion.prime",
        "provider": _PROVIDER,
        "model": _MODEL,
        "game_id": game.game_id,
        "seed": game.seed,
        "target_level": game.target_level,
        "win_levels": game.win_levels,
        "completion_scope": "full-game" if game.is_full_game else "level-witness",
        "status": status,
        "run_id": run_id,
        "completed_level_count": completed_level_count,
        "primitive_action_count": primitive_action_count,
        "replay_verified": replay_verified,
        "sealed_trace": sealed_trace,
        "cleanup_complete": cleanup_complete,
    }
    for name in ("partial_game_score", "receipt_sha256", "promotion", "scope"):
        if name in source:
            safe[name] = source[name]
    if status == "PASS":
        capability_digest = source.get("receipt_sha256")
        if (
            type(capability_digest) is not str
            or type(broker_replay_sha256) is not str
        ):
            raise live.P7LiveSolveError("P7 receipt identity is unavailable")
        safe["selection_receipt_sha256"] = digest(
            {
                "game_id": game.game_id,
                "seed": game.seed,
                "target_level": game.target_level,
                "win_levels": game.win_levels,
                "capability_receipt_sha256": capability_digest,
                "broker_replay_sha256": broker_replay_sha256,
            }
        )
    if comparison_report is not None:
        safe["comparison_report"] = "available"
    if reason is not None:
        safe["reason"] = reason
    if terminal_reason is not None:
        safe["terminal_reason"] = terminal_reason
    return safe


def _reject(*, reason: str | None = None) -> int:
    public = {"status": "preflight-rejected"}
    if reason == _LEVEL_WITNESS_ONLY:
        public["reason"] = _LEVEL_WITNESS_ONLY
    print(json.dumps(public, separators=(",", ":"), sort_keys=True))
    return 2


def main(argv: list[str] | None = None) -> int:
    """The only external input is the literal Make preset invocation."""

    invocation: P7Invocation | None = None
    preflight_reason: str | None = None
    try:
        if sys.argv[1:] if argv is None else argv:
            raise P7OperatorError("P7 operator arguments are rejected")
        invocation = _preflight(os.environ)
    except P7OperatorError as error:
        if str(error) == _LEVEL_WITNESS_ONLY:
            preflight_reason = _LEVEL_WITNESS_ONLY
    except BaseException:
        pass
    if invocation is None:
        return _reject(reason=preflight_reason)
    run_id = live.safe_run_id()
    try:
        result = classify_live_result(asyncio.run(run_live(invocation, run_id)))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        reason = (
            str(error)
            if isinstance(error, live.P7LiveSolveError)
            else "P7 live solve unsuccessful"
        )
        failure_evidence = {}
        if isinstance(error, P7LiveAttemptFailure):
            failure_evidence = {
                "completed_level_count": error.levels_completed,
                "primitive_action_count": error.primitive_actions,
                "terminal_reason": error.terminal_reason,
                "replay_verified": error.replay_verified,
                "sealed_trace": error.sealed_trace,
                "cleanup_complete": error.cleanup_complete,
            }
        print(
            json.dumps(
                _public_receipt(
                    "unsuccessful", run_id, reason=reason, game=invocation.game,
                    **failure_evidence,
                ),
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        print("[asterion-prime-p7] unsuccessful", file=sys.stderr, flush=True)
        return 1
    print(
        json.dumps(
            result, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
    )
    print("[asterion-prime-p7] PASS", file=sys.stderr, flush=True)
    return 0


def _entrypoint() -> None:
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if status == 1:
        # Python joins default-executor threads again during interpreter exit.
        # A failed owner cannot regain an unbounded wait after public failure.
        os._exit(status)
    raise SystemExit(status)


if __name__ == "__main__":
    _entrypoint()


__all__ = (
    "P7OperatorError",
    "P7OperatorResources",
    "P7RuntimeSelection",
    "P7Invocation",
    "build_p7_operator_resources",
    "classify_live_result",
    "main",
    "p7_runtime_options",
    "resolve_p7_runtime",
    "resolve_pi_provider",
    "run_live",
)
