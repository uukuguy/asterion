"""Operator-owned fixed model selection for the native P7 application."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import signal as signal_module
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
    P7ToolRegistry,
    Tool,
    _canonical_action,
    _observation_digest,
)
from asterion.applications.prime.p7.cognition import GameCognitionStore
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
    PrimeGameplayTrace,
    trace_identities_for as gameplay_trace_identities,
)
from asterion.applications.prime.p7.ipython_host import (
    PersistentIpythonHost,
    RestrictedPersistentIpythonWorker,
    p7_client_facade,
)
from asterion.applications.prime.p7.mechanics_prior import build_mechanics_prior
from asterion.applications.prime.p7.world_model import WorldModelStore
from asterion.applications.prime.p7 import live
from asterion.applications.prime.p7.model_selection import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    P7ModelSelectionError,
    declared_model_selection,
    resolve_model_selection,
    valid_selection_name,
)
from asterion.applications.prime.p7.private_trace import (
    P7PrivateTraceReceipt,
    P7_TRACE_IDENTITIES,
    trace_identities_for as solve_trace_identities,
)
from asterion.applications.prime.p7.playbook import (
    PlaybookKey,
    PlaybookSnapshot,
    branch_playbook,
    load_playbook,
    save_playbook,
)
from asterion.applications.prime.p7.replay import replay_arc_run
from asterion.applications.prime.p7.score import digest, replay_sha256
from asterion.applications.prime.p7.optimizer import (
    ActionExpectation,
    PlannerAction,
    RouteCandidate,
    RouteCompressionProof,
)
from asterion.applications.prime.p7.optimizer_arc import optimize_arc_route
from asterion.applications.prime.p7.prompt import (
    P7_LEGACY_SOLVE_PROMPT,
    P7_EXPLORE_APPENDIX,
    build_solve_prompt,
    build_strategy_prompt,
)
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
# The documented defaults. The operator environment may select another
# provider/model; see ``p7.model_selection``.
_PROVIDER = DEFAULT_PROVIDER
_MODEL = DEFAULT_MODEL
_MISSING = object()
UNBOUNDED_FIRST_ROUND_ENV = "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"
P7_HISTORY_VARIANT_ENV = "ASTERION_PRIME_P7_HISTORY_VARIANT"
P7_STRATEGY_ENV = "ASTERION_PRIME_P7_STRATEGY"
P7_OFFLINE_OPTIMIZATION_ENV = "ASTERION_PRIME_P7_OFFLINE_OPTIMIZATION"
PI_CODING_AGENT_DIR = "PI_CODING_AGENT_DIR"
_MAX_CALLBACKS = 128
_DEADLINE_MS = 3_600_000
_ROUTE_OPTIMIZER_CANDIDATE_BUDGET = 64
_ROUTE_OPTIMIZER_MAX_REMOVED = 3
_ROUTE_OPTIMIZER_TIME_BUDGET_SECONDS = 8.0
_BRIDGE_PROTOCOL = "asterion.prime-ipython/v1"
_BRIDGE_JOIN_SECONDS = 1.0
_LEVEL_WITNESS_ONLY = "LEVEL is only available with the P7 level-witness command"

class P7OperatorError(RuntimeError):
    """The fixed P7 model host is unavailable."""


class RouteAdoptionTracker:
    """Private evidence for whether P7 followed an injected route hypothesis."""

    __slots__ = ("_expected", "_expectations", "_target_level", "_cursor", "_divergence", "_reached_target")

    def __init__(self) -> None:
        self._expected: tuple[PlannerAction, ...] = ()
        self._expectations: tuple[ActionExpectation, ...] = ()
        self._target_level = 0
        self._cursor = 0
        self._divergence: dict[str, object] | None = None
        self._reached_target = False

    def arm(
        self,
        actions: tuple[PlannerAction, ...],
        *,
        target_level: int,
        expectations: tuple[ActionExpectation, ...] = (),
    ) -> None:
        if type(actions) is not tuple or not all(type(item) is PlannerAction for item in actions):
            raise ValueError("invalid route adoption actions")
        if type(expectations) is not tuple or (
            expectations and (
                len(expectations) != len(actions)
                or not all(type(item) is ActionExpectation for item in expectations)
            )
        ):
            raise ValueError("invalid route adoption expectations")
        self._expected = actions
        self._expectations = expectations
        self._target_level = target_level
        self._cursor = 0
        self._divergence = None
        self._reached_target = False

    def record(self, transitions: tuple[object, ...]) -> None:
        if not self._expected or self._divergence is not None:
            return
        for transition in transitions:
            levels_completed = getattr(transition, "levels_completed", 0)
            if type(levels_completed) is int and levels_completed >= self._target_level:
                self._reached_target = True
            if self._cursor >= len(self._expected):
                return
            actual = PlannerAction(
                getattr(transition, "action", ""),
                tuple(getattr(transition, "data", ()) or ()),
            )
            expected = self._expected[self._cursor]
            if actual != expected:
                self._divergence = {
                    "index": self._cursor,
                    "expected": expected.name,
                    "actual": actual.name,
                }
                return
            if self._expectations:
                witness = self._expectations[self._cursor]
                observed_hash = getattr(transition, "after_sha256", None)
                observed_level = getattr(transition, "levels_completed", None)
                if observed_hash != witness.after_state_sha256 or observed_level != witness.levels_completed:
                    self._divergence = {
                        "index": self._cursor,
                        "expected": expected.name,
                        "actual": actual.name,
                        "reason": "expectation-mismatch",
                    }
                    return
            self._cursor += 1

    def reject_witness(self) -> None:
        if self._divergence is None and self._cursor < len(self._expected):
            name = self._expected[self._cursor].name
            self._divergence = {"index": self._cursor, "expected": name, "actual": name, "reason": "expectation-mismatch"}

    def witnesses_for_plan(self, plan: object) -> tuple[ActionExpectation, ...]:
        if not self._expectations or self._divergence is not None or type(plan) is not list:
            return ()
        witnesses: list[ActionExpectation] = []
        for item, action, witness in zip(plan, self._expected[self._cursor:], self._expectations[self._cursor:]):
            if type(item) is not dict or item.get("action") != {"name": action.name, "data": dict(action.data)}:
                break
            witnesses.append(witness)
        return tuple(witnesses)

    def checked_plan(self) -> list[dict[str, object]]:
        if self._divergence is not None or not self._expectations:
            return []
        return [
            {"action": {"name": w.action, "data": dict(w.data)}, "expect": {"frame_sha256": w.after_frame_sha256}}
            for w in self._expectations[self._cursor:self._cursor + 20]
        ]

    def summary(self) -> dict[str, object]:
        return {
            "armed": bool(self._expected),
            "expected_actions": len(self._expected),
            "followed_actions": self._cursor,
            "first_divergence": None if self._divergence is None else dict(self._divergence),
            "reached_target": self._reached_target,
            "completed": bool(self._expected)
            and self._cursor == len(self._expected)
            and self._reached_target,
            "target_level": self._target_level,
        }


def _resolve_history_variant(
    environment: Mapping[str, str], game: P7GameSelection | ArcGameContract
) -> str:
    variant = environment.get(P7_HISTORY_VARIANT_ENV, "verified")
    if variant not in {"verified", "legacy"}:
        raise P7OperatorError("P7 history variant is unavailable")
    if variant == "legacy" and type(game) is ArcGameContract:
        raise P7OperatorError("P7 history variant is unavailable")
    return variant


def _offline_optimization_enabled(environment: Mapping[str, str]) -> bool:
    """Allow exact-route replay only for an explicit integration experiment.

    Capability runs default to pure P7 planning.  The optimizer remains
    available for separately-labelled replay/integration checks, but an absent
    or unknown value cannot enable route injection accidentally.
    """

    value = environment.get(P7_OFFLINE_OPTIMIZATION_ENV, "").strip().lower()
    return value in {"integration", "enabled", "true", "1"}


def _prompt_for_variant(variant: str, tool_registry: object = None) -> str:
    if variant == "verified":
        return build_solve_prompt(tool_registry)
    if variant == "legacy":
        return P7_LEGACY_SOLVE_PROMPT
    raise P7OperatorError("P7 history variant is unavailable")


def _resolve_strategy(environment: Mapping[str, str]) -> str:
    strategy = environment.get(P7_STRATEGY_ENV, "replay")
    if strategy not in {"replay", "explore"}:
        raise P7OperatorError("P7 route strategy is unavailable")
    return strategy


def _prompt_for_strategy(strategy: str, tool_registry: object = None) -> str:
    try:
        return build_strategy_prompt(tool_registry, strategy)
    except ValueError:
        raise P7OperatorError("P7 route strategy is unavailable") from None


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

    def __init__(
        self,
        channel: socket.socket,
        host: PersistentIpythonHost,
        client: object,
    ) -> None:
        self._channel = channel
        self._host = host
        self._client = p7_client_facade(client)
        self._method_calls: dict[str, int] = {}
        self._method_failures: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._started = False

    def __repr__(self) -> str:
        return "<_IpythonBridgeServer redacted>"

    def private_accounting(self) -> dict[str, int]:
        """Return bounded private counts for bridge dispatch diagnosis."""
        return {
            "method_calls_total": sum(self._method_calls.values()),
            **{f"method_calls_{name}": count for name, count in self._method_calls.items()},
            "method_failures_total": sum(self._method_failures.values()),
            **{
                f"method_failures_{name}": count
                for name, count in self._method_failures.items()
            },
        }

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
            if type(value) is not dict or value.get("protocol") != _BRIDGE_PROTOCOL:
                raise ValueError
            request_id = value.get("request_id")
            if type(request_id) is not str or not request_id:
                raise ValueError
            request_type = value.get("type")
            if request_type == "execute":
                if (
                    set(value) != {"code", "protocol", "request_id", "type"}
                    or type(value["code"]) is not str
                    or not value["code"]
                ):
                    raise ValueError
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
            elif request_type == "method_call":
                if (
                    type(value.get("method")) is not str
                    or (
                        "params" not in value
                        and value.get("method")
                        not in {"observe", "status", "mechanics_prior", "world_model", "cognition", "action_effects", "mechanism_candidates", "probe_plan", "simulator_status", "retrodiction_status"}
                    )
                    or type(value["method"]) is not str
                ):
                    raise ValueError
                response = self._dispatch_method_call(
                    request_id,
                    value["method"],
                    value.get("params", {}),
                )
            else:
                raise ValueError
        except BaseException:
            response = {
                "output": "",
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "error",
                "type": "result",
            }
        return json.dumps(response, separators=(",", ":"), sort_keys=True).encode()

    def _dispatch_method_call(
        self, request_id: str, method: str, params: object
    ) -> dict[str, object]:
        """Dispatch a non-code method invocation to the broker.

        The TypeScript extension registers each p7_client method as its
        own Pi tool. The model invokes the tool with JSON parameters and
        Pi serializes the call through this bridge with ``type ==
        "method_call"`` instead of going through the ipython cell-execution
        path.
        """
        self._method_calls[method] = min(5000, self._method_calls.get(method, 0) + 1)

        def error_response() -> dict[str, object]:
            return {
                "output": "",
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "error",
                "type": "method_result",
            }

        def ok_response(result: object) -> dict[str, object]:
            try:
                output = json.dumps(
                    result,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            except (TypeError, ValueError, OverflowError):
                self._method_failures[method] = min(
                    5000, self._method_failures.get(method, 0) + 1
                )
                return error_response()
            if len(output.encode("utf-8")) > 120 * 1024:
                self._method_failures[f"{method}_output_too_large"] = min(
                    5000,
                    self._method_failures.get(f"{method}_output_too_large", 0) + 1,
                )
            return {
                "output": output,
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "ok",
                "type": "method_result",
            }

        try:
            facade = self._client
            if method in {"observe", "status", "mechanics_prior"}:
                if params is not None and (type(params) is not dict or params):
                    return error_response()
                value = getattr(facade, method)()
            elif method in {"world_model", "cognition", "action_effects", "mechanism_candidates", "probe_plan", "simulator_status", "retrodiction_status", "model_search"}:
                if params is not None and (type(params) is not dict or params):
                    return error_response()
                value = getattr(facade, method)()
            elif method == "playbook":
                if params is not None and (type(params) is not int or params < 0):
                    return error_response()
                value = facade.playbook(params)
            elif method == "record_hypothesis":
                if (
                    type(params) is not dict
                    or set(params) != {"layer", "key", "value"}
                    or type(params["layer"]) is not str
                    or type(params["key"]) is not str
                    or not isinstance(params["value"], dict)
                ):
                    return error_response()
                value = facade.record_hypothesis(params["layer"], params["key"], params["value"])
            elif method == "promote_hypothesis":
                if (
                    type(params) is not dict
                    or set(params) != {"key", "evidence_kind"}
                    or type(params["key"]) is not str
                    or type(params["evidence_kind"]) is not str
                ):
                    return error_response()
                value = facade.promote_hypothesis(params["key"], params["evidence_kind"])
            elif method in {"tried_actions", "last_outcome_summary"}:
                if params is not None and (
                    type(params) is not int or params < 0
                ):
                    return error_response()
                value = getattr(facade, method)(params)
            elif method == "history":
                if (
                    type(params) is not dict
                    or set(params) != {"start", "limit"}
                    or type(params["start"]) is not int
                    or params["start"] < 0
                    or type(params["limit"]) is not int
                    or params["limit"] < 1
                ):
                    return error_response()
                value = facade.history(params["start"], params["limit"])
            elif method == "frame_at":
                if (
                    type(params) is not dict
                    or set(params) != {"sequence"}
                    or type(params["sequence"]) is not int
                    or params["sequence"] < 0
                ):
                    return error_response()
                value = facade.frame_at(params["sequence"])
            elif method == "act_checked":
                if (
                    type(params) is not dict
                    or set(params) != {"plan"}
                    or type(params["plan"]) is not list
                ):
                    return error_response()
                value = facade.act_checked(params["plan"])
            else:
                return error_response()
        except BaseException:
            self._method_failures[method] = min(
                5000, self._method_failures.get(method, 0) + 1
            )
            return error_response()
        return ok_response(value)


class _P7BrokerClient:
    """Worker-facing mapping adapter over the native ARC broker."""

    __slots__ = ("_broker", "_recorder", "_identities", "_variant", "_counts", "_route_adoption")

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
        self._route_adoption = RouteAdoptionTracker()
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

    def arm_route_adoption(
        self,
        actions: tuple[PlannerAction, ...],
        *,
        target_level: int,
        expectations: tuple[ActionExpectation, ...] = (),
    ) -> None:
        self._route_adoption.arm(actions, target_level=target_level, expectations=expectations)

    def route_adoption(self) -> dict[str, object]:
        return self._route_adoption.summary()

    def _observation_and_status(self) -> tuple[ArcObservation, ArcStatus]:
        """Serve the final immutable broker snapshot after terminal closure."""
        try:
            return self._broker.observe(), self._broker.status()
        except ArcBrokerError:
            snapshot = self._broker.terminal_snapshot()
            return snapshot.observation, snapshot.status

    def history(self, start: int, limit: int) -> list[dict[str, object]]:
        try:
            if type(start) is not int or type(limit) is not int or start < 0 or limit < 1:
                raise ValueError
            # The model-facing read surface is forgiving about a page size.
            # The broker remains strict, while an over-large model request is
            # reduced to the documented transport bound instead of consuming
            # a reasoning turn with an opaque host-service error.
            bounded_limit = min(limit, 32)
            try:
                page = self._broker.history(start, bounded_limit)
            except ArcBrokerError:
                # A guessed future cursor is an empty page, not a fatal host
                # failure.  This keeps paging read-only and lets the model
                # continue from the latest observed sequence.
                status = self._broker.status()
                latest = status.primitive_actions - 1
                if start > latest or latest < 0:
                    page = []
                else:
                    raise
            self._count("history_queries")
            self._count("history_records_returned", len(page))
            return page
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def mechanics_prior(self) -> dict[str, object]:
        """Return bounded, redacted mechanics evidence from broker history."""
        try:
            status = self._broker.status()
            latest = status.primitive_actions
            records: list[dict[str, object]] = []
            start = 0
            for _ in range(8):
                page = self._broker.history(start, 32)
                self._count("history_queries")
                self._count("history_records_returned", len(page))
                records.extend(json.loads(json.dumps(page, separators=(",", ":"))))
                if not page or page[-1].get("sequence") >= latest or len(page) < 32:
                    break
                next_sequence = page[-1].get("sequence")
                if type(next_sequence) is not int or next_sequence < start:
                    raise ArcBrokerError("unavailable")
                start = next_sequence + 1
            result = build_mechanics_prior(records, current_level=status.levels_completed)
            return self._cap_mechanics_prior(result)
        except Exception:
            try:
                status = self._broker.status()
            except Exception:
                try:
                    status = self._broker.terminal_snapshot().status
                except Exception:
                    status = ArcStatus(0, 0, 0, "unavailable")
            return {
                "available": False,
                "reason": "history-unavailable",
                **self._status_view(status),
            }

    @staticmethod
    def _cap_mechanics_prior(result: dict[str, object]) -> dict[str, object]:
        """Keep serialized evidence within the public host-service budget."""
        if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode()) <= 16384:
            return result
        capped = dict(result)
        for key in ("levels", "candidate_rules", "level_advances"):
            value = capped.get(key)
            if isinstance(value, list):
                capped[key] = value[:8]
            if len(json.dumps(capped, separators=(",", ":"), ensure_ascii=False).encode()) <= 16384:
                return capped
        return {
            key: capped[key]
            for key in ("available", "prefix_actions", "highest_verified_level", "current_level")
            if key in capped
        }

    def frame_at(self, sequence: int) -> list[list[int]]:
        try:
            if type(sequence) is not int:
                raise ValueError
            frame = self._broker.frame_at(sequence)
            self._count("frame_queries")
            return frame
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def world_model(self) -> dict[str, object]:
        try:
            snapshot = self._broker.world_model()
            if snapshot is None:
                return {"status": "unavailable"}
            return snapshot.projection(max_bytes=8192)
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def cognition(self) -> dict[str, object]:
        """Read advisory type cognition and exact-game experience."""

        try:
            return self._broker.cognition_projection()
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def action_effects(self) -> list[dict[str, object]]:
        try:
            value = list(self._broker.action_effects())
            encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            if len(encoded.encode()) > 8192:
                return value[-8:]
            return value
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def mechanism_candidates(self) -> list[dict[str, object]]:
        try:
            value = list(self._broker.mechanism_candidates())
            if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) > 8192:
                # Prefer current hypotheses and compiled proposals.  The
                # full signature is diagnostic only and can consume the
                # entire model-tool budget, so drop it from the bounded
                # fallback while retaining one complete compiled proposal.
                compact: list[dict[str, object]] = []
                ordered = sorted(
                    value,
                    key=lambda item: (
                        0 if item.get("status") == "hypothesis" else 1,
                        0 if "record_hypothesis" in item else 1,
                        0 if "compiled_mechanism" in item else 1,
                        -int(item.get("support_count", 0)),
                        str(item.get("key", "")),
                    ),
                )
                for item in ordered:
                    candidate = {
                        key: item[key]
                        for key in (
                            "key", "level", "action_family", "action",
                            "status", "support_count", "evidence_sequences",
                            "conflict_sequences", "source",
                        )
                        if key in item
                    }
                    if "compiled_mechanism" in item and not compact:
                        candidate["compiled_mechanism"] = item["compiled_mechanism"]
                    if "record_hypothesis" in item and not compact:
                        candidate["record_hypothesis"] = item["record_hypothesis"]
                        # The submission already contains the complete spec.
                        # Preserve it ahead of a duplicate model body.
                        if len(json.dumps(candidate, separators=(",", ":"), ensure_ascii=False).encode()) > 8190:
                            candidate.pop("compiled_mechanism", None)
                    compact.append(candidate)
                    if len(json.dumps(compact, separators=(",", ":"), ensure_ascii=False).encode()) > 8192:
                        compact.pop()
                        break
                return compact
            return value
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def probe_plan(self) -> dict[str, object]:
        try:
            return self._broker.probe_plan()
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def simulator_status(self) -> dict[str, object]:
        try:
            return self._broker.simulator_status()
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def playbook(self, level: int | None = None) -> dict[str, object]:
        if level is not None and (type(level) is not int or level < 0):
            raise P7OperatorError("P7 host services are unavailable")
        try:
            try:
                projection = self._broker.playbook_projection()
            except (ArcBrokerError, ValueError):
                projection = {}
            visual = list(self._broker.playbook_visual_hypotheses())
            if level is not None:
                visual = [item for item in visual if item["level"] < level]
                raw_experience = projection.get("experience_model", {})
                if not isinstance(raw_experience, Mapping):
                    raw_experience = {}
                experience = {
                    "effects": [
                        item for item in raw_experience.get("effects", [])
                        if isinstance(item, Mapping) and item.get("level") == level
                    ][-8:],
                    "candidates": [
                        item for item in raw_experience.get("candidates", [])
                        if isinstance(item, Mapping) and item.get("level") == level
                    ][-8:],
                    "simulator": list(raw_experience.get("simulator", []))[-1:],
                }
                value = {
                    "level": level,
                    "memory": [m for m in projection.get("level_memory", []) if m["level"] == level],
                    "experience": experience,
                }
            else:
                value = projection
            value["prior_visual_hypotheses"] = visual
            value["checked_plan"] = self._route_adoption.checked_plan()
            if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) > 8192:
                value = {
                    "status": "projection-capped",
                    "level": level,
                    "prior_visual_hypotheses": visual,
                    "experience": value.get("experience", {}),
                    "checked_plan": value["checked_plan"],
                }
                while len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) > 8192 and visual:
                    visual.pop()
            return value
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def retrodiction_status(self) -> dict[str, object]:
        snapshot = self._broker.world_model()
        result = self._broker.retrodiction_status()
        return {
            **result,
            "world_model_version": None if snapshot is None else snapshot.version,
            "conflict_count": 0 if snapshot is None else len(snapshot.conflicts),
        }

    def model_search(
        self,
        max_nodes: int = 512,
        max_depth: int = 24,
        strategy: str = "astar",
    ) -> dict[str, object]:
        if (
            type(max_nodes) is not int or type(max_depth) is not int
            or type(strategy) is not str
        ):
            raise P7OperatorError("P7 host services are unavailable")
        try:
            result = self._broker.model_search(
                max_nodes=max_nodes,
                max_depth=max_depth,
                strategy=strategy,
            )
            if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode()) > 8192:
                return {
                    "status": result.get("status", "unavailable"),
                    "reason": result.get("reason"),
                    "expanded_nodes": result.get("expanded_nodes", 0),
                    "generated_nodes": result.get("generated_nodes", 0),
                    "target_level": result.get("target_level"),
                    "candidate_action_count": result.get("candidate_action_count", 0),
                    "plan": [],
                }
            return result
        except Exception:
            raise P7OperatorError("P7 host services are unavailable") from None

    def record_hypothesis(self, layer: str, key: str, value: dict[str, object]) -> dict[str, object]:
        try:
            return self._broker.record_hypothesis(layer, key, value)
        except ArcBrokerError as error:
            # Keep the sealed worker API body-free on exceptions, but give
            # the model a safe machine-readable outcome so it does not retry
            # an unchanged malformed mechanism indefinitely.
            reason = str(error)
            if reason == "closed":
                safe_reason = "closed"
            elif reason == "uncertain":
                safe_reason = "uncertain"
            elif reason == "REPLAN_REQUIRED":
                safe_reason = "replan-required"
            else:
                safe_reason = "validation-failed"
            return {"status": "rejected", "reason": safe_reason}

    def promote_hypothesis(self, key: str, evidence_kind: str) -> dict[str, object]:
        return self._broker.promote_hypothesis(key, evidence_kind)

    def act_checked(self, plan: object) -> Mapping[str, object]:
        try:
            journal_start = len(self._broker.journal)
            dispatch_start = self._broker.status().primitive_actions
            try:
                result = self._broker.act_checked(
                    plan, replay_expectations=self._route_adoption.witnesses_for_plan(plan)
                )
            except Exception:
                committed = len(self._broker.journal) - journal_start
                if type(plan) is list and 1 <= len(plan) <= 20:
                    try:
                        dispatched = self._broker.status().primitive_actions
                    except ArcBrokerError:
                        dispatched = self._broker.terminal_snapshot().status.primitive_actions
                    dispatched -= dispatch_start
                    self._count("checked_plans")
                    self._count("checked_plan_errors")
                    self._count("matched_expectations", committed)
                    self._count("uncertain_items", dispatched - committed)
                    self._count("unexecuted_items", len(plan) - dispatched)
                raise
            finally:
                self._record_transitions(self._broker.journal[journal_start:])
            if result["stop_reason"] == "route-expectation-mismatch":
                self._route_adoption.reject_witness()
            self._count("checked_plans")
            self._count("matched_expectations", result["applied_count"])
            if result["mismatch"] is not None:
                self._count("mismatches")
                self._counts["matched_expectations"] -= min(1, result["applied_count"])
            self._count("unexecuted_items", result["unexecuted_count"])
            batch = result["batch"]
            observation = result["observation"]
            terminal = result["terminal"]
            learning_hint = self._broker.learning_hint()
            return {
                # Put the bounded cue before the full observation frame; the
                # worker output cap may truncate the latter.
                "learning_hint": learning_hint,
                "applied_count": result["applied_count"],
                "stop_reason": result["stop_reason"],
                "mismatch": result["mismatch"],
                "conflict": result.get("conflict"),
                "retrodiction": result.get("retrodiction", self._broker.retrodiction_status()),
                "no_effect_hint": result.get("no_effect_hint"),
                "unexecuted_count": result["unexecuted_count"],
                "available_actions": result["available_actions"],
                "invalid_action": result["invalid_action"],
                "feedback": result["feedback"],
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
        frame = observation.frame
        frame_truncated = False
        # Animated frames are useful for local visual analysis, but the model
        # bridge has a finite response budget. Preserve the settled frame when
        # the raw animation would exceed that budget and make the loss
        # explicit to the model.
        if len(json.dumps(frame, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 48 * 1024:
            frame = (frame[-1],)
            frame_truncated = True
        return {
            "available_actions": list(observation.available_actions),
            "frame": frame,
            "frame_truncated": frame_truncated,
            "levels_completed": observation.levels_completed,
            "state": observation.state,
            "win_levels": observation.win_levels,
        }

    def _status_view(self, status: ArcStatus) -> dict[str, object]:
        level_baseline = None
        game = self._broker.game
        if isinstance(game, P7GameSelection):
            level = min(status.levels_completed, game.win_levels - 1)
            level_baseline = game.baseline_actions[level]
        action_cap = getattr(game, "action_cap", status.actions_remaining)
        return {
            "actions_remaining": status.actions_remaining,
            "levels_completed": status.levels_completed,
            "primitive_actions": status.primitive_actions,
            "target_level": self._broker.game.target_level,
            "level_baseline": level_baseline,
            "action_cap": action_cap,
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
        self._route_adoption.record(transitions)
        for transition in transitions:
            self._recorder.append(
                "arc.action", self._identities, self._transition_view(transition)
            )

    def observe(self) -> Mapping[str, object]:
        observation, status = self._observation_and_status()
        # Auto-inject tried-summary so the model can see no-effect state on
        # every observe call, not only inside act_checked responses. Targets
        # the L3 failure mode where the model loops on the same (action,
        # position) without ever calling tried_actions().
        no_effects = self._broker.last_outcome_summary(observation.levels_completed)
        tried = self._broker.tried_actions(observation.levels_completed)
        top_tried = sorted(
            tried,
            key=lambda item: (
                -(item.get("count", 0) or 0),
                item.get("action", ""),
            ),
        )[:5]
        learning_hint = self._broker.learning_hint()
        view = self._observation_view(observation)
        return {
            # Keep the bounded semantic signal before the potentially large
            # frame so the worker bridge cannot truncate the only reusable
            # learning cue.
            "learning_hint": learning_hint,
            **view,
            "actions_remaining": status.actions_remaining,
            "primitive_actions": status.primitive_actions,
            "target_level": self._broker.game.target_level,
            "level_baseline": self._status_view(status)["level_baseline"],
            "action_cap": self._status_view(status)["action_cap"],
            "terminal_reason": status.terminal_reason,
            "tried_summary": {
                "attempts": no_effects.get("attempts", {}),
                "no_effect": no_effects.get("no_effect", {}),
                "top_repeated": top_tried,
            },
        }


    def status(self) -> Mapping[str, object]:
        _, status = self._observation_and_status()
        return {
            **self._status_view(status),
            # Keep the advisory learning signal on the small status surface;
            # an animated observe frame can exceed the bridge response cap.
            "learning_hint": self._broker.learning_hint(),
        }

    def tried_actions(self, level: int | None = None) -> list[dict[str, object]]:
        return self._broker.tried_actions(level)

    def last_outcome_summary(
        self, level: int | None = None
    ) -> Mapping[str, object]:
        return self._broker.last_outcome_summary(level)

    def components(
        self, level: int | None = None
    ) -> list[dict[str, object]]:
        """Connected-component analysis of the current settled grid.

        Returns a list of ``{value, bbox, size}`` entries — each one a
        4-connected region of non-background cells at the requested level.
        The model calls this to discover the structural layout
        (cart, markers, walls, etc.) without re-implementing flood fill.
        """
        return self._broker.components(level)

    def untried_clicks(
        self, level: int | None = None
    ) -> list[dict[str, object]]:
        """Components at ``level`` that have not been clicked yet.

        Combines :meth:`components` with :meth:`tried_actions` so the
        model sees structured component positions that are NOT in the
        tried set, with a suggested ``ACTION6`` action for each.
        """
        return self._broker.untried_clicks(level)

    def hypothesis(
        self, level: int, key: str, value: object = _MISSING
    ) -> object:
        """Persistent-kernel hypothesis storage.

        Call with ``value=_MISSING`` (or omit) to read; with any other
        ``value`` to write. The store lives in the IPython namespace so
        values survive compaction summaries.
        """
        from .hypothesis_store import hypothesis_store
        return hypothesis_store(level).getset(key, value)

    def act(self, actions: object, *, _trusted_prefix_replay: bool = False) -> Mapping[str, object]:
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
        try:
            result = self._broker.act(
                tuple(validated), _allow_guard_probe=_trusted_prefix_replay
            )
        except ArcBrokerError as error:
            if str(error) != "REPLAN_REQUIRED":
                raise P7OperatorError("P7 host services are unavailable") from None
            observation = self._broker.observe()
            status = self._broker.status()
            return {
                "applied_count": 0,
                "level_advanced": False,
                "levels_completed": prior_levels,
                "observation": self._observation_view(observation),
                "terminal": {
                    "actions_remaining": status.actions_remaining,
                    "levels_completed": status.levels_completed,
                    "primitive_actions": status.primitive_actions,
                    "target_level": self._broker.game.target_level,
                    "terminal_reason": status.terminal_reason,
                },
                "stop_reason": "REPLAN_REQUIRED",
                "transitions": [],
            }
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
            "observation": self._observation_view(observation),
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
    *,
    identities: Mapping[str, str] = P7_TRACE_IDENTITIES,
) -> None:
    """Re-execute a verified prefix into this run's broker and private trace."""

    if not transitions or any(type(item) is not ArcTransition for item in transitions):
        raise P7OperatorError("P7 saved prefix is unavailable")
    try:
        if len(broker.history(0, 1)) != 1 or broker.history(0, 1)[0]["sequence"] != 0:
            raise ValueError
        client = _P7BrokerClient(broker, recorder, identities, variant="verified")
        for expected in transitions:
            if (
                expected.sequence != len(broker.journal) + 1
                or _observation_digest(broker.observe()) != expected.before_sha256
            ):
                raise ValueError
            client.act(
                [{"name": expected.action, "data": dict(expected.data)}],
                _trusted_prefix_replay=True,
            )
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


def _summarize_prefix_mechanics(prefix: object) -> str:
    """Derive a short markdown summary of the prefix's action distribution.

    Used to auto-inject a "what worked in earlier levels" hint so the
    current retry can re-use patterns instead of re-discovering them.
    Targets the L3 failure mode where the model treats each new level as
    blank-slate and does not transfer the prior level's mechanics.
    """
    transitions = getattr(prefix, "transitions", None)
    if not transitions or not isinstance(transitions, tuple):
        return ""
    from collections import Counter
    by_level: dict[int, Counter[str]] = {}
    levels_completed: set[int] = set()
    for transition in transitions:
        levels_completed.add(int(getattr(transition, "levels_completed", 0)))
    last_level = max(levels_completed) if levels_completed else 0
    for transition in transitions:
        level = int(getattr(transition, "levels_completed", 0))
        action = str(getattr(transition, "action", ""))
        by_level.setdefault(level, Counter())[action] += 1
    if not by_level:
        return ""
    bullets: list[str] = []
    bullets.append(
        f"## Prior verified levels (auto-summary of saved prefix)\n"
        f"Highest verified level: {last_level}. "
        f"Use this to bootstrap hypotheses at level "
        f"{int(last_level) + 1}."
    )
    for level in sorted(by_level.keys()):
        c = by_level[level]
        total = sum(c.values())
        top = c.most_common(3)
        items = ", ".join(f"{name}={n}" for name, n in top)
        bullets.append(
            f"- L{level}: {total} actions. Top: {items}"
        )
    return "\n".join(bullets)


def _verified_route_transitions(prefix: object, *, target_level: int) -> tuple[object, ...]:
    """Select only the verified transitions that reach the requested level."""
    if target_level < 1 or getattr(prefix, "levels_completed", 0) < target_level:
        return ()
    transitions = getattr(prefix, "transitions", ())
    if not isinstance(transitions, tuple) or not transitions:
        return ()
    start = 0
    if target_level > 1:
        for index, transition in enumerate(transitions):
            if getattr(transition, "levels_completed", None) == target_level - 1:
                start = index + 1
                break
        else:
            return ()
    selected: list[object] = []
    for transition in transitions[start:]:
        levels = getattr(transition, "levels_completed", None)
        if type(levels) is not int or levels not in (target_level - 1, target_level):
            return ()
        selected.append(transition)
        if levels == target_level:
            break
    if not selected or getattr(selected[-1], "levels_completed", None) != target_level or len(selected) > 64:
        return ()
    return tuple(selected)


def _planner_actions_from_transitions(transitions: tuple[object, ...]) -> tuple[PlannerAction, ...]:
    """Convert sealed transitions to immutable, canonical optimizer actions."""
    actions: list[PlannerAction] = []
    for transition in transitions:
        action = getattr(transition, "action", None)
        data = getattr(transition, "data", ())
        if type(action) is not str or type(data) is not tuple:
            return ()
        try:
            canonical = _canonical_action(ArcAction(action, tuple(sorted(dict(data).items()))))
        except (TypeError, ValueError):
            return ()
        actions.append(PlannerAction(canonical.name, canonical.data))
    return tuple(actions)


def _route_source_matches_prefix(
    route_source: object, prefix: object, *, target_level: int
) -> bool:
    """Allow exact prefixes or same-game suffixes that will be freshly replayed."""

    if target_level <= 1:
        return route_source is not None
    if route_source is None or prefix is None:
        return False
    expected = getattr(prefix, "transitions", ())
    actual = getattr(route_source, "transitions", ())
    if (
        type(expected) is tuple
        and type(actual) is tuple
        and len(actual) >= len(expected)
        and actual[: len(expected)] == expected
    ):
        return True
    return (
        getattr(route_source, "game_id", None) == getattr(prefix, "game_id", None)
        and getattr(route_source, "seed", None) == getattr(prefix, "seed", None)
        and getattr(route_source, "win_levels", None) == getattr(prefix, "win_levels", None)
        and getattr(prefix, "levels_completed", 0) >= target_level - 1
        and getattr(route_source, "levels_completed", 0) >= target_level
    )


def _summarize_route_actions(
    actions: tuple[PlannerAction, ...], *, target_level: int, optimized: bool = False
) -> str:
    """Expose a bounded, generic route hypothesis for the model."""
    if not actions or len(actions) > 64:
        return ""
    encoded_actions: list[str] = []
    for item in actions:
        encoded_actions.append(json.dumps({"name": item.name, "data": dict(item.data)}, sort_keys=True))
    provenance = "Offline fresh-ARC replay verified" if optimized else "A prior sealed local run replayed"
    return (
        f"## Replay-verified L{target_level} route hypothesis\n"
        f"{provenance} this route to the selected level boundary. "
        "Treat its action count as an upper bound. Seek a shorter verified route "
        "when exploration is requested; otherwise dispatch one item at a time "
        "through p7_act_checked, verify each returned observation, and replan "
        "if the current state contradicts it.\n"
        + " -> ".join(encoded_actions)
    )


def _summarize_partial_route_actions(
    actions: tuple[PlannerAction, ...], *, target_level: int
) -> str:
    """Describe a replayed incomplete route without suggesting it solves a level."""
    if not actions or len(actions) > 64:
        return ""
    encoded = " -> ".join(
        json.dumps({"name": item.name, "data": dict(item.data)}, sort_keys=True)
        for item in actions
    )
    return (
        f"## Incomplete L{target_level} exploration checkpoint\n"
        "A prior incomplete attempt reached the same observed checkpoint after fresh replay. "
        "This route has not completed the level. Use it only as evidence for exploration; "
        "verify each observation and replan on mismatch.\n" + encoded
    )


def _summarize_route_proofs(
    proofs: tuple[RouteCompressionProof, ...], *, target_level: int
) -> str:
    """Expose bounded, replay-only route edit evidence without semantic claims."""

    if type(proofs) is not tuple or not proofs or len(proofs) > 8:
        return ""
    values: list[dict[str, object]] = []
    for proof in proofs:
        if type(proof) is not RouteCompressionProof:
            return ""
        values.append({
            "kind": proof.kind,
            "source_start": proof.source_start,
            "source_end": proof.source_end,
            "before": [
                {"name": action.name, "data": dict(action.data)}
                for action in proof.before
            ],
            "after": [
                {"name": action.name, "data": dict(action.data)}
                for action in proof.after
            ],
            "removed_indices": list(proof.removed_indices),
            "identity": {"game_id": proof.identity[0], "seed": proof.identity[1]},
            "baseline_action_count": proof.baseline_action_count,
            "candidate_action_count": proof.candidate_action_count,
            "source_digest": proof.source_digest,
            "candidate_digest": proof.candidate_digest,
            "prefix_digest": proof.prefix_digest,
            "suffix_digest": proof.suffix_digest,
            "terminal_state": proof.terminal_state,
            "target_level": proof.target_level,
            "warmup_digest": proof.warmup_digest,
            "candidate_witness": [
                {
                    "kind": witness.kind,
                    "action_index": witness.action_index,
                    "observation_sha256": witness.observation_sha256,
                    "levels_completed": witness.levels_completed,
                    "state": witness.state,
                }
                for witness in proof.candidate_witness
            ],
        })
    value = (
        f"## Route compression evidence for L{target_level}\n"
        "Each item is a joint route edit verified by fresh replay. It is not a semantic claim about any action. "
        "Use only if the current state and identity match; dispatch one action at a time through p7_act_checked, "
        "verify each observation, and abandon the edit on any mismatch.\n"
        + json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return value if len(value.encode("utf-8")) <= 16384 else ""


def _summarize_verified_route(prefix: object, *, target_level: int) -> str:
    """Expose a replay-verified route as a bounded hypothesis for the model."""
    transitions = _verified_route_transitions(prefix, target_level=target_level)
    return _summarize_route_actions(
        _planner_actions_from_transitions(transitions), target_level=target_level
    )


def _expectation_metadata(expectations: tuple[ActionExpectation, ...]) -> list[dict[str, object]]:
    """Serialize only bounded replay witnesses for private route adoption stats."""
    return [
        {
            "action": expectation.action,
            "data": dict(expectation.data),
            "prior_state_sha256": expectation.prior_state_sha256,
            "after_state_sha256": expectation.after_state_sha256,
            "after_frame_sha256": expectation.after_frame_sha256,
            "changed_cells": [list(cell) for cell in expectation.changed_cells],
            "levels_completed": expectation.levels_completed,
            "state": expectation.state,
        }
        for expectation in expectations
    ]


def _expectations_from_metadata(value: object) -> tuple[ActionExpectation, ...]:
    if type(value) is not list or len(value) > 256:
        return ()
    parsed: list[ActionExpectation] = []
    try:
        for item in value:
            if not isinstance(item, Mapping):
                return ()
            data = item.get("data", {})
            cells = item.get("changed_cells", [])
            if not isinstance(data, Mapping) or not isinstance(cells, list):
                return ()
            parsed.append(
                ActionExpectation(
                    action=item["action"],
                    data=tuple(sorted((str(k), int(v)) for k, v in data.items())),
                    prior_state_sha256=item["prior_state_sha256"],
                    after_state_sha256=item["after_state_sha256"],
                    after_frame_sha256=item["after_frame_sha256"],
                    changed_cells=tuple(tuple(int(part) for part in cell) for cell in cells),
                    levels_completed=item["levels_completed"],
                    state=item["state"],
                )
            )
    except (KeyError, TypeError, ValueError):
        return ()
    return tuple(parsed)


def _optimize_verified_route(
    prefix: object,
    *,
    game: object,
    arc_root: Path,
    target_level: int,
    warmup_prefix: object | None = None,
) -> tuple[str, dict[str, object]]:
    """Best-effort fresh-ARC shortening with a verified-route fallback.

    A route from an older sealed run may have a different completed-level
    prefix.  Its selected-level suffix is still a candidate, but the current
    prefix is always the warmup used by the fresh replay oracle.
    """
    transitions = _verified_route_transitions(prefix, target_level=target_level)
    baseline = _planner_actions_from_transitions(transitions)
    warmup: tuple[PlannerAction, ...] = ()
    if target_level > 1:
        all_transitions = getattr(
            warmup_prefix if warmup_prefix is not None else prefix,
            "transitions",
            (),
        )
        if isinstance(all_transitions, tuple):
            boundary = next(
                (
                    index + 1
                    for index, transition in enumerate(all_transitions)
                    if getattr(transition, "levels_completed", None) == target_level - 1
                ),
                None,
            )
            if boundary is not None:
                warmup = _planner_actions_from_transitions(all_transitions[:boundary])
    metadata: dict[str, object] = {
        "status": "no-route" if not baseline else "baseline-only",
        "baseline_actions": len(baseline),
        "optimized_actions": len(baseline),
        "candidates_replayed": 0,
        "removed_indices": [],
        "proofs": [],
        "warmup_actions": len(warmup),
        "elapsed_seconds": 0.0,
        "timed_out": False,
        "candidate_actions": [],
        "candidate_expectations": [],
    }
    baseline_hint = _summarize_route_actions(baseline, target_level=target_level)
    if not baseline_hint:
        return "", metadata
    try:
        candidate = optimize_arc_route(
            game=game,
            arc_root=arc_root,
            route=baseline,
            candidate_budget=_ROUTE_OPTIMIZER_CANDIDATE_BUDGET,
            max_removed=_ROUTE_OPTIMIZER_MAX_REMOVED,
            warmup=warmup,
            time_budget_seconds=_ROUTE_OPTIMIZER_TIME_BUDGET_SECONDS,
        )
        if not isinstance(candidate, RouteCandidate):
            raise ValueError("invalid optimizer result")
        metadata["candidates_replayed"] = candidate.candidates_replayed
        metadata["removed_indices"] = list(candidate.removed_indices)
        metadata["proofs"] = [proof.kind for proof in candidate.proofs]
        metadata["elapsed_seconds"] = candidate.elapsed_seconds
        metadata["timed_out"] = candidate.timed_out
        if (
            type(candidate.actions) is tuple
            and all(type(action) is PlannerAction for action in candidate.actions)
            and candidate.replay.success
            and candidate.replay.action_count == len(candidate.actions)
            and len(candidate.actions) < len(baseline)
            and candidate.replay.identity == (game.game_id, game.seed)
            and len(candidate.expectations) == len(candidate.actions)
        ):
            optimized_hint = _summarize_route_actions(
                candidate.actions, target_level=target_level, optimized=True
            )
            if optimized_hint:
                metadata["candidate_actions"] = [
                    {"name": action.name, "data": dict(action.data)}
                    for action in candidate.actions
                ]
                metadata["candidate_expectations"] = _expectation_metadata(candidate.expectations)
                proof_hint = _summarize_route_proofs(
                    candidate.proofs, target_level=target_level
                )
                metadata["status"] = "optimized"
                metadata["optimized_actions"] = len(candidate.actions)
                return "\n\n".join(
                    item for item in (optimized_hint, proof_hint) if item
                ), metadata
    except Exception as error:
        metadata["status"] = "fallback-error"
        metadata["error_type"] = type(error).__name__
    return baseline_hint, metadata


def _optimize_partial_attempt(
    attempt: object,
    *,
    prefix: object,
    game: object,
    arc_root: Path,
    target_level: int,
) -> tuple[str, dict[str, object]]:
    """Compress a verified failed attempt into an exploratory checkpoint hint."""
    prefix_transitions = getattr(prefix, "transitions", ())
    attempt_transitions = getattr(attempt, "transitions", ())
    if not isinstance(prefix_transitions, tuple) or not isinstance(attempt_transitions, tuple):
        return "", {"status": "no-partial-route"}
    if len(attempt_transitions) <= len(prefix_transitions) or attempt_transitions[:len(prefix_transitions)] != prefix_transitions:
        return "", {"status": "partial-prefix-mismatch"}
    route = _planner_actions_from_transitions(attempt_transitions[len(prefix_transitions):])
    warmup = _planner_actions_from_transitions(prefix_transitions)
    if not route or not warmup:
        return "", {"status": "no-partial-route"}
    try:
        candidate = optimize_arc_route(
            game=game, arc_root=arc_root, route=route, warmup=warmup,
            candidate_budget=_ROUTE_OPTIMIZER_CANDIDATE_BUDGET,
            max_removed=_ROUTE_OPTIMIZER_MAX_REMOVED,
            time_budget_seconds=_ROUTE_OPTIMIZER_TIME_BUDGET_SECONDS,
            preserve_terminal_observation=True,
        )
    except Exception as error:
        return "", {"status": "partial-optimizer-error", "error_type": type(error).__name__}
    metadata = {
        "status": "partial-optimized" if len(candidate.actions) < len(route) else "partial-baseline",
        "baseline_actions": len(route), "optimized_actions": len(candidate.actions),
        "candidates_replayed": candidate.candidates_replayed,
        "removed_indices": list(candidate.removed_indices),
        "proofs": [proof.kind for proof in candidate.proofs],
        "target_level": target_level,
        "candidate_actions": [
            {"name": action.name, "data": dict(action.data)}
            for action in candidate.actions
        ] if len(candidate.actions) < len(route) else [],
        "candidate_expectations": _expectation_metadata(candidate.expectations)
        if len(candidate.actions) < len(route) else [],
    }
    if not candidate.replay.replay_complete:
        return "", {**metadata, "status": "partial-replay-incomplete"}
    actions = candidate.actions if len(candidate.actions) < len(route) else route
    hint = _summarize_partial_route_actions(actions, target_level=target_level)
    if not hint:
        return "", metadata
    return hint, metadata


def _initial_game_context(client: object, *, include_prior: bool) -> str:
    """Inject one bounded broker snapshot before the model chooses tools."""

    observe = getattr(client, "observe", None)
    status = getattr(client, "status", None)
    if not callable(observe) or not callable(status):
        raise P7OperatorError("P7 host services are unavailable")
    observation = observe()
    broker_status = status()
    if not isinstance(observation, Mapping) or not isinstance(broker_status, Mapping):
        raise P7OperatorError("P7 host services are unavailable")
    raw_frame = observation.get("frame")
    frame = raw_frame
    frame_truncated = bool(observation.get("frame_truncated", False))
    if isinstance(raw_frame, (list, tuple)) and raw_frame:
        # Keep the settled frame in the initial context.  The previous
        # ``frame_summary`` placeholder was not emitted by observe(), which
        # silently deprived a fresh model turn of the board it must inspect.
        settled = raw_frame[-1]
        if len(json.dumps(settled, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 12 * 1024:
            frame = settled
        else:
            frame = None
            frame_truncated = True
    state = {
        "available_actions": observation.get("available_actions", ()),
        "frame": frame,
        "frame_truncated": frame_truncated,
        "levels_completed": observation.get("levels_completed"),
        "state": observation.get("state"),
        "win_levels": observation.get("win_levels"),
        "tried_summary": observation.get("tried_summary", {}),
        "learning_hint": observation.get("learning_hint", {}),
        "actions_remaining": broker_status.get("actions_remaining"),
        "primitive_actions": broker_status.get("primitive_actions"),
        "target_level": broker_status.get("target_level"),
        "terminal_reason": broker_status.get("terminal_reason"),
    }
    sections = [
        "## Initial broker state (application supplied; already observed)",
        "Use this snapshot as the starting fact set. If frame_truncated is true and frame is null, call p7_observe for the current board.",
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ]
    def fits(parts: list[str]) -> bool:
        return len("\n".join(parts).encode("utf-8")) <= 16384

    if not fits(sections):
        hint = state["learning_hint"]
        state["learning_hint"] = {
            "recommendation": hint.get("recommendation") if isinstance(hint, Mapping) else None,
            "projection_truncated": True,
        }
        sections[-1] = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not fits(sections):
        state["frame"] = None
        state["frame_truncated"] = True
        sections[-1] = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not fits(sections):
        raise P7OperatorError("P7 host services are unavailable")

    def add_projection(heading: str, instruction: str, projection: Mapping[str, object], tool: str) -> None:
        candidate = [
            heading, instruction,
            json.dumps(dict(projection), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ]
        if fits([*sections, *candidate]):
            sections.extend(candidate)
        else:
            sections.append(f"{heading}: omitted from initial context; call {tool} if needed.")

    world_model = getattr(client, "world_model", None)
    if callable(world_model):
        try:
            model_projection = world_model()
        except Exception:
            model_projection = {}
        if isinstance(model_projection, Mapping):
            add_projection(
                "## Same-game world model (visual candidates are hypotheses)",
                "Use confirmed facts directly. Treat visual candidates as observations to test; do not treat a candidate role as a confirmed wall, floor, object, or goal.",
                model_projection, "p7_world_model",
            )
    cognition = getattr(client, "cognition", None)
    if callable(cognition):
        try:
            cognition_projection = cognition()
        except Exception:
            cognition_projection = {}
        if isinstance(cognition_projection, Mapping):
            add_projection(
                "## Persistent game cognition (advisory; no execution authority)",
                "Type-level knowledge is prior-only. Exact-game experience is useful only after current observations and prefix checks agree; never treat this section as a route.",
                cognition_projection, "p7_cognition",
            )
    if include_prior:
        mechanics_prior = getattr(client, "mechanics_prior", None)
        if not callable(mechanics_prior):
            raise P7OperatorError("P7 host services are unavailable")
        prior = mechanics_prior()
        if not isinstance(prior, Mapping):
            raise P7OperatorError("P7 host services are unavailable")
        add_projection(
            "## Cross-level mechanics evidence (application supplied; use as a prior)",
            "Treat this as evidence for a distinguishing probe, not as a route.",
            prior, "p7_mechanics_prior",
        )
    value = "\n".join(sections)
    if len(value.encode("utf-8")) > 16384:
        raise P7OperatorError("P7 host services are unavailable")
    return value


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
            evidence.identities,
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
            evidence.identities,
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
            or not valid_selection_name(self.provider)
            or not valid_selection_name(self.model)
            or type(self.max_actions) is not int
            or not 1 <= self.max_actions <= 5000
            or type(self.unbounded_first_round) is not bool
            or (self.max_callbacks, self.deadline_ms) != (
                (None, None) if self.unbounded_first_round else (_MAX_CALLBACKS, _DEADLINE_MS)
            )
        ):
            raise P7OperatorError("P7 runtime selection is invalid")

    @classmethod
    def fixed(
        cls,
        game: P7GameSelection | ArcGameContract = DEFAULT_GAME,
        provider: str = DEFAULT_PROVIDER,
        model: str = DEFAULT_MODEL,
    ) -> P7RuntimeSelection:
        if not valid_selection_name(provider) or not valid_selection_name(model):
            raise P7OperatorError("P7 runtime selection is invalid")
        value = object.__new__(cls)
        object.__setattr__(value, "runtime_id", _RUNTIME_ID)
        object.__setattr__(value, "provider", provider)
        object.__setattr__(value, "model", model)
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


def resolve_pi_provider(
    environment: Mapping[str, str], *, model: str | None = None
) -> str:
    """Resolve the operator-selected model host from its environment."""

    try:
        selection = resolve_model_selection(environment)
        if model is not None and model != selection.model:
            raise P7ModelSelectionError("P7 model selection is invalid")
    except Exception:
        raise P7OperatorError("P7 model host is unavailable") from None
    return selection.provider


def resolve_p7_runtime(
    environment: Mapping[str, str], game: P7GameSelection | ArcGameContract = DEFAULT_GAME
) -> P7RuntimeSelection:
    """Resolve the operator-selected model/runtime preset without tuning knobs."""

    try:
        selected = resolve_model_selection(environment)
    except P7ModelSelectionError:
        raise P7OperatorError("P7 model host is unavailable") from None
    provider = selected.provider
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
        model=selected.model,
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
            P7RuntimeSelection.fixed(game, selection.provider, selection.model),
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
        "model": runtime_options.get("model", _MODEL),
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
    cognition_store: GameCognitionStore | None = None,
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
            if name not in {
                "ARC_API_KEY", "ARC_BASE_URL", "OPERATION_MODE",
                P7_HISTORY_VARIANT_ENV, P7_STRATEGY_ENV,
            }
        }
        if environment.get("ASTERION_PRIME_DEBUG_TRANSCRIPT") == "1":
            provider_environment["ASTERION_PRIME_DEBUG_TRANSCRIPT"] = "1"
            provider_environment["ASTERION_PRIME_DEBUG_TRANSCRIPT_PATH"] = str(
                private_trace_root.parent / "debug-transcript.jsonl"
            )
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
        broker = ArcBroker(
            engine=engine,
            game=game,
            world_model=WorldModelStore(game.game_id, game.seed, game.win_levels),
            cognition_store=cognition_store,
        )
        history_run_id = private_trace_root.parent.name
        if (
            type(history_run_id) is not str or not history_run_id
            or not history_run_id.isascii()
            or (run_id is not None and run_id != history_run_id)
        ):
            raise ValueError
        broker.bind_history(history_run_id)
        official = type(game) is ArcGameContract
        identities = (
            gameplay_trace_identities(selection.model)
            if official
            else solve_trace_identities(selection.model)
        )
        prediction_client = _P7BrokerClient(
            broker,
            trace,
            identities,
            variant=variant,
        )
        ipython = PersistentIpythonHost(
            worker=worker,
            p7_client=p7_client_facade(prediction_client),
        )
        private_trace = (
            PrimeGameplayTrace(broker, trace, engine.guid, identities)
            if official else P7PrivateTraceReceipt(broker, trace, identities)
        )
        bridge = _IpythonBridgeServer(parent, ipython, prediction_client)
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
    game = resolve_game_selection(selection_environment, arc_root)
    if mode == "witness":
        # A level witness is an efficiency experiment, so its hard ceiling
        # must be the human baseline through the requested level.  The
        # previous fallback of 500 actions made an explicit L1 witness spend
        # far beyond the level's useful budget and obscured the real stop
        # reason.  Full solves and the separately supervised sweep keep their
        # own caps.
        prefix = None
        route_source = None
        if game.target_level > 1:
            from .solutions import load_best_prefix

            try:
                expected_model = declared_model_selection(resolved_environment).model
                prefix = load_best_prefix(
                    arc_root,
                    Path(resolved_environment[live.OPERATOR_ROOT_ENV])
                    / ".asterion-private"
                    / "prime-p7-live",
                    game.game_id,
                    game.seed,
                    max_level=game.target_level - 1,
                    expected_model_id=expected_model,
                )
                if _offline_optimization_enabled(resolved_environment):
                    route_source = load_best_prefix(
                        arc_root,
                        Path(resolved_environment[live.OPERATOR_ROOT_ENV])
                        / ".asterion-private"
                        / "prime-p7-live",
                        game.game_id,
                        game.seed,
                        max_level=game.target_level,
                        expected_model_id=expected_model,
                    )
            except (KeyError, OSError, P7ModelSelectionError):
                prefix = None
                route_source = None
        game = _bound_witness_level_actions(game, prefix, route_source=route_source)
    return game


def _verified_level_action_count(prefix: object, target_level: int) -> int | None:
    """Return the actions in one level of a verified prefix, if complete."""

    transitions = getattr(prefix, "transitions", None)
    if type(target_level) is not int or target_level <= 1 or not isinstance(transitions, tuple):
        return None
    start = next(
        (
            index
            for index, transition in enumerate(transitions, start=1)
            if getattr(transition, "levels_completed", -1) >= target_level - 1
        ),
        None,
    )
    boundary = next(
        (
            index
            for index, transition in enumerate(transitions, start=1)
            if getattr(transition, "levels_completed", -1) >= target_level
        ),
        None,
    )
    if start is None or boundary is None or boundary <= start:
        return None
    count = boundary - start
    return count if count > 0 else None


def _bound_witness_level_actions(
    game: P7GameSelection,
    prefix: object | None,
    *,
    route_source: object | None = None,
) -> P7GameSelection:
    """Bound a witness to the current level, excluding replayed prior levels."""

    if type(game) is not P7GameSelection or game.action_cap_override is not None:
        raise P7OperatorError("P7 witness selection is unavailable")
    current = _verified_level_action_count(
        route_source if route_source is not None else prefix,
        game.target_level,
    )
    transitions = getattr(prefix, "transitions", ())
    prefix_actions = len(transitions)
    if any(
        getattr(transition, "levels_completed", -1) >= game.target_level
        for transition in transitions
    ):
        prefix_actions = next(
            index
            for index, transition in enumerate(transitions, start=1)
            if getattr(transition, "levels_completed", -1) >= game.target_level - 1
        )
    if current is None:
        if prefix_actions > 0:
            return replace(
                game,
                action_cap_override=prefix_actions + game.baseline_actions[game.target_level - 1],
            )
        return replace(game, action_cap_override=sum(game.baseline_actions[: game.target_level]))
    if prefix_actions == 0:
        source_transitions = getattr(route_source, "transitions", ())
        prefix_actions = next(
            index
            for index, transition in enumerate(source_transitions, start=1)
            if getattr(transition, "levels_completed", -1) >= game.target_level - 1
        )
    baselines = list(game.baseline_actions)
    baselines[game.target_level - 1] = current
    return replace(
        game,
        _metadata_baseline_actions=tuple(baselines),
        action_cap_override=prefix_actions + current,
    )


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
        if P7_STRATEGY_ENV in environment:
            resolved[P7_STRATEGY_ENV] = _resolve_strategy(environment)
        agent_dir = live.resolve_pi_agent_dir(resolved)
        resolved[PI_CODING_AGENT_DIR] = str(agent_dir)
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


async def run_live(
    invocation: P7Invocation,
    run_id: str,
    *,
    cancellation_signal: object | None = None,
) -> live.P7LiveExecution:
    """Run the one fixed solve and seal its private evidence.

    Recovered from the removed driver's live body, with the orchestration order
    unchanged: preflight every host service, run the composed application, seal
    and replay the broker, verify the sealed trace, then compare, and always
    release. Only the value sources differ; see
    :mod:`asterion.applications.prime.p7.live`.
    """

    from .solutions import load_best_prefix, load_verified_attempt

    variant = _resolve_history_variant(invocation.environment, invocation.game)
    run_signal = live.NeverCancelled() if cancellation_signal is None else cancellation_signal
    if type(getattr(run_signal, "cancelled", None)) is not bool:
        raise P7OperatorError("P7 cancellation signal is unavailable")

    root = invocation.operator_root
    playbook_snapshot: PlaybookSnapshot | None = None
    playbook_loaded = False
    playbook_saved = False
    try:
        playbook_snapshot = load_playbook(
            root, PlaybookKey(invocation.game.game_id, invocation.game.seed, invocation.game.win_levels)
        )
        playbook_loaded = playbook_snapshot is not None
    except (OSError, ValueError):
        # A malformed private playbook cannot grant authority; use baseline.
        playbook_snapshot = None
    # Build the application-level tool registry. The framework prompt
    # carries only general principles; this is where P7 surfaces its
    # own tools (retrodict query APIs, no-effect hint, etc.) to the model.
    tool_registry = P7ToolRegistry()
    tool_registry.register(Tool(
        name="tried_actions",
        description=(
            "Enumerate every (level, action_name, position) tuple you have "
            "dispatched this run, with counts. Position is {\"x\": int, \"y\": int} "
            "for ACTION6 clicks and None for direction/interact actions. Call this "
            "before dispatching a probe you are unsure about; if the same "
            "(action, position) tuple already has a non-zero count at this "
            "level, the broker has already observed its outcome."
        ),
        signature="p7_client.tried_actions(level=None)",
        category="retrodict",
    ))
    tool_registry.register(Tool(
        name="last_outcome_summary",
        description=(
            "Aggregate per-action counts for the current run, split into "
            "{\"attempts\": {action: count}, \"no_effect\": {action: count}}. "
            "Useful for spotting an action that has been attempted many times "
            "at this level with no observed frame change."
        ),
        signature="p7_client.last_outcome_summary(level=None)",
        category="retrodict",
    ))
    tool_registry.register(Tool(
        name="act_checked_hint",
        description=(
            "When act_checked returns stop_reason 'observation-no-change' the "
            "response also carries a no_effect_hint field with this same "
            "action and position plus a no-effect count; read it in-band "
            "instead of recomputing."
        ),
        signature="result['no_effect_hint'] (when stop_reason='observation-no-change')",
        category="retrodict",
    ))
    tool_registry.register(Tool(
        name="world_model",
        description="Read the bounded same-game confirmed model projection; hypotheses remain unconfirmed until action evidence promotes them.",
        signature="p7_client.world_model()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="cognition",
        description=(
            "Read persistent game-type priors and exact-game experience. Type priors are "
            "advisory only; exact-game memory is reusable only after the current prefix "
            "and observations are checked. This query never grants route execution authority."
        ),
        signature="p7_client.cognition()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="action_effects",
        description="Read bounded effects extracted from settled transitions in this run; this is evidence, not a route or execution authority.",
        signature="p7_client.action_effects()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="mechanism_candidates",
        description="Read automatically induced mechanism candidates, support evidence, and conflict status.",
        signature="p7_client.mechanism_candidates()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="probe_plan",
        description="Suggest one current-state information-bearing probe without dispatching it; stale coordinates are rejected.",
        signature="p7_client.probe_plan()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="simulator_status",
        description="Read simulator effect coverage, unknown diagnostics, and certificate status.",
        signature="p7_client.simulator_status()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="playbook",
        description="Read the bounded same-game Playbook projection, persisted visual hypotheses, and level memory; hypotheses remain unconfirmed and malformed private state falls back to baseline.",
        signature="p7_client.playbook(level=None)",
        category="model",
    ))
    tool_registry.register(Tool(
        name="retrodiction_status",
        description="Read scalar transition-model verification status before using a batch or route hypothesis.",
        signature="p7_client.retrodiction_status()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="model_search",
        description=(
            "Run bounded BFS/A* over the same-game mechanism only after it has been "
            "retrodicted and certified. Returns a checked plan but never dispatches "
            "actions; pass that plan unchanged to p7_client.act_checked."
        ),
        signature="p7_client.model_search()",
        category="model",
    ))
    tool_registry.register(Tool(
        name="record_hypothesis",
        description="Submit one canonical mechanism hypothesis and exactly one distinguishing probe; the broker attaches current evidence and controls promotion.",
        signature="p7_client.record_hypothesis(layer, key, value)",
        category="model",
    ))
    tool_registry.register(Tool(
        name="promote_hypothesis",
        description=(
            "Promote a current-level visual component hypothesis only after the latest action changed a settled cell inside its recorded bounds. "
            "Use evidence_kind='changed_cell_in_bounds'; failed or no-effect probes are rejected."
        ),
        signature="p7_client.promote_hypothesis(key, evidence_kind)",
        category="model",
    ))
    strategy = _resolve_strategy(invocation.environment)
    if variant == "legacy":
        prompt = _prompt_for_variant(variant, tool_registry)
        if strategy == "explore":
            prompt += P7_EXPLORE_APPENDIX
    else:
        prompt = _prompt_for_strategy(strategy, tool_registry)
    prefix = load_best_prefix(
        invocation.arc_root,
        root / ".asterion-private" / "prime-p7-live",
        invocation.game.game_id,
        invocation.game.seed,
        max_level=invocation.game.target_level - 1
        if invocation.game.target_level > 1
        else None,
        expected_model_id=declared_model_selection(invocation.environment).model,
    )
    if prefix is not None and len(prefix.transitions) > 0:
        summary = _summarize_prefix_mechanics(prefix)
        if summary:
            prompt = prompt + "\n\n" + summary
    offline_optimization_enabled = _offline_optimization_enabled(invocation.environment)
    if offline_optimization_enabled:
        route_source = load_best_prefix(
            invocation.arc_root,
            root / ".asterion-private" / "prime-p7-live",
            invocation.game.game_id,
            invocation.game.seed,
            max_level=invocation.game.target_level,
            expected_model_id=declared_model_selection(invocation.environment).model,
        )
        if _route_source_matches_prefix(
            route_source, prefix, target_level=invocation.game.target_level
        ):
            route_hint, route_optimization = _optimize_verified_route(
                route_source,
                game=invocation.game,
                arc_root=invocation.arc_root,
                target_level=invocation.game.target_level,
                warmup_prefix=prefix,
            )
        else:
            route_hint, route_optimization = "", {
                "status": "prefix-mismatch",
                "baseline_actions": 0,
                "optimized_actions": 0,
                "candidates_replayed": 0,
                "removed_indices": [],
                "proofs": [],
                "warmup_actions": 0,
                "elapsed_seconds": 0.0,
                "timed_out": False,
            }
        if not route_hint and invocation.game.target_level > 1 and prefix is not None:
            attempt = load_verified_attempt(
                invocation.arc_root,
                root / ".asterion-private" / "prime-p7-live",
                invocation.game.game_id,
                invocation.game.seed,
                expected_model_id=declared_model_selection(invocation.environment).model,
            )
            if attempt is not None:
                route_hint, route_optimization = _optimize_partial_attempt(
                    attempt,
                    prefix=prefix,
                    game=invocation.game,
                    arc_root=invocation.arc_root,
                    target_level=invocation.game.target_level,
                )
    else:
        route_hint, route_optimization = "", {
            "status": "disabled",
            "baseline_actions": 0,
            "optimized_actions": 0,
            "candidates_replayed": 0,
            "removed_indices": [],
            "proofs": [],
            "warmup_actions": 0,
            "elapsed_seconds": 0.0,
            "timed_out": False,
        }
    if route_hint:
        prompt = prompt + "\n\n" + route_hint
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
        cognition_store=GameCognitionStore(root),
    )
    broker_for_playbook = resources_.host_services.get("prime.arc-broker")
    if isinstance(broker_for_playbook, ArcBroker) and playbook_snapshot is not None:
        try:
            broker_for_playbook.load_playbook(playbook_snapshot)
        except (OSError, ValueError, TypeError):
            playbook_snapshot = None
            playbook_loaded = False
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
    diagnostics["budget"] = {
        "target_level": invocation.game.target_level,
        "level_baseline": invocation.game.baseline_actions[invocation.game.target_level - 1],
        "action_cap": invocation.game.action_cap,
    }
    diagnostics["route_optimization"] = route_optimization
    diagnostics["offline_optimization_enabled"] = offline_optimization_enabled
    diagnostics["playbook_loaded"] = playbook_loaded
    diagnostics["playbook_saved"] = False
    diagnostics["replayed_prefix_actions"] = 0 if prefix is None else len(prefix.transitions)
    if invocation.sweep_mode:
        diagnostics["sweep"] = {
            "scope": "offline-research",
            "target_level": invocation.game.target_level,
            "prefix_actions": 0 if prefix is None else len(prefix.transitions),
            "level_action_cap": invocation.game.baseline_actions[invocation.game.target_level - 1],
            "run_action_cap": invocation.game.action_cap,
        }
    broker_status = None
    runtime: object | None = None
    prediction_client: object | None = None
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
                _apply_saved_prefix(
                    broker, evidence.runtime_recorder, prefix.transitions,
                    identities=evidence.identities,
                )
                if broker.status().levels_completed != prefix.levels_completed:
                    raise P7OperatorError("P7 saved prefix is unavailable")
        prediction_client = getattr(resources_, "_prediction_client", None)
        if (
            isinstance(prediction_client, _P7BrokerClient)
            and offline_optimization_enabled
            and route_optimization.get("status") in {"optimized", "partial-optimized"}
        ):
            candidate_actions = route_optimization.get("candidate_actions", [])
            if isinstance(candidate_actions, list):
                parsed_actions = tuple(
                    PlannerAction(
                        item["name"],
                        tuple(sorted(item.get("data", {}).items())),
                    )
                    for item in candidate_actions
                    if isinstance(item, Mapping)
                    and type(item.get("name")) is str
                    and isinstance(item.get("data", {}), dict)
                )
                if len(parsed_actions) == len(candidate_actions):
                    parsed_expectations = _expectations_from_metadata(
                        route_optimization.get("candidate_expectations", [])
                    )
                    if len(parsed_expectations) != len(parsed_actions):
                        parsed_expectations = ()
                    prediction_client.arm_route_adoption(
                        parsed_actions,
                        target_level=invocation.game.target_level,
                        expectations=parsed_expectations,
                    )
        if prediction_client is not None:
            prompt = prompt + "\n\n" + _initial_game_context(
                prediction_client,
                include_prior=prefix is not None and prefix.levels_completed > 0,
            )
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
            input_text=prompt,
            host_services=resources_.host_services,
            implementation_packages={CAPABILITY_REF: PACKAGE_REF},
            signal=run_signal,
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
    except asyncio.CancelledError as error:
        # asyncio.CancelledError inherits BaseException, so handle supervisor
        # cancellation explicitly to let the finally block seal verified work.
        failure = error
        reason = "P7 live solve cancelled"
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
                    world_snapshot = broker_value.world_model()
                    retrodiction = broker_value.retrodiction_status()
                    diagnostics["world_model_version"] = (
                        None if world_snapshot is None else world_snapshot.version
                    )
                    diagnostics["retrodiction_status"] = retrodiction["status"]
                    diagnostics["retrodiction_reasons"] = list(retrodiction.get("reasons", ()))
                    diagnostics["experience"] = broker_value.experience_diagnostics()
                    diagnostics["conflict_count"] = (
                        0 if world_snapshot is None else len(world_snapshot.conflicts)
                    )
                    if world_snapshot is not None:
                        diagnostics["world_model_facts"] = {
                            "current_level": world_snapshot.current_level,
                            "version": world_snapshot.version,
                            "confirmed": {
                                layer: len(getattr(world_snapshot, layer))
                                for layer in ("mechanics", "entities", "relations")
                            },
                            "hypotheses": len(world_snapshot.hypotheses),
                            "conflicts": len(world_snapshot.conflicts),
                        }
                    diagnostics.setdefault("playbook_loaded", False)
                    diagnostics.setdefault("playbook_saved", False)
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
                if sealed_trace and replay_verified:
                    try:
                        snapshot = broker_value.export_playbook(successful=failure is None)
                    except (OSError, ValueError) as error:
                        playbook_saved = False
                        # Keep only the exception class in private diagnostics.
                        # The operator must remain body-free while making a
                        # persistence failure distinguishable from an
                        # unverified trace during live-run diagnosis.
                        diagnostics["playbook_save_error"] = f"export:{type(error).__name__}"
                    else:
                        try:
                            save_playbook(root, snapshot)
                            playbook_saved = True
                        except (OSError, ValueError) as error:
                            playbook_saved = False
                            diagnostics["playbook_save_error"] = f"write:{type(error).__name__}"
                elif failure is not None:
                    try:
                        if isinstance(broker_value, ArcBroker):
                            baseline = broker_value.export_playbook(successful=False)
                        else:
                            baseline = playbook_snapshot or PlaybookSnapshot(PlaybookKey(invocation.game.game_id, invocation.game.seed, invocation.game.win_levels))
                            baseline = branch_playbook(baseline, "run-unverified")
                    except (OSError, ValueError) as error:
                        playbook_saved = False
                        diagnostics["playbook_save_error"] = f"export:{type(error).__name__}"
                    else:
                        try:
                            save_playbook(root, baseline)
                            playbook_saved = True
                        except (OSError, ValueError) as error:
                            playbook_saved = False
                            diagnostics["playbook_save_error"] = f"write:{type(error).__name__}"
                diagnostics["playbook_saved"] = playbook_saved
            # Keep the operator-only Pi stderr tail in private evidence. The
            # public receipt remains body-free, but extension-registration
            # failures otherwise collapse into an indistinguishable generic
            # ApplicationRunError.
            rpc_session = getattr(
                getattr(runtime, "_session", None), "_rpc_session", None
            )
            stderr = getattr(rpc_session, "stderr", b"")
            if type(stderr) is bytes:
                diagnostics["pi_stderr"] = live.safe_stderr_summary(stderr)
            last_failure = getattr(rpc_session, "last_failure", None)
            if type(last_failure) is str and last_failure:
                diagnostics["pi_last_failure"] = last_failure[:256]
            private_diagnostics = getattr(rpc_session, "private_diagnostics", None)
            if callable(private_diagnostics):
                diagnostics["pi_rpc_private"] = private_diagnostics()
            event_summary = getattr(
                getattr(runtime, "_session", None), "native_event_summary", ()
            )
            if type(event_summary) is tuple:
                diagnostics["native_event_summary"] = [
                    dict(item) for item in event_summary if isinstance(item, Mapping)
                ]
            bridge = getattr(resources_, "_bridge", None)
            bridge_accounting = getattr(bridge, "private_accounting", None)
            if callable(bridge_accounting):
                diagnostics["bridge_method_failures"] = bridge_accounting()
            route_adoption = getattr(bridge, "route_adoption", None)
            if callable(route_adoption):
                diagnostics["route_adoption"] = route_adoption()
            elif isinstance(prediction_client, _P7BrokerClient):
                diagnostics["route_adoption"] = prediction_client.route_adoption()
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
            diagnostics["failure_classification"] = classify_failure_cause(
                failure=failure,
                broker_status=diagnostics.get("broker_status"),
                pi_private=diagnostics.get("pi_rpc_private"),
                bridge_method_failures=diagnostics.get("bridge_method_failures"),
                cleanup_failed=cleanup_failed,
            )
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


def classify_failure_cause(
    *,
    failure: BaseException | None,
    broker_status: Mapping[str, object] | None,
    pi_private: Mapping[str, object] | None,
    bridge_method_failures: Mapping[str, object] | None,
    cleanup_failed: bool,
) -> Mapping[str, object]:
    """Classify one failed live run using only bounded private evidence."""
    status = {} if broker_status is None else dict(broker_status)
    private = {} if pi_private is None else dict(pi_private)
    evidence: dict[str, object] = {}
    if failure is None:
        return {"category": "none", "evidence": {}}
    if isinstance(failure, asyncio.CancelledError):
        evidence = {
            key: private[key]
            for key in ("cancel_requested", "process_returncode")
            if key in private
        }
        if cleanup_failed:
            evidence["cleanup_failed"] = True
        return {"category": "external_cancel", "evidence": evidence}
    if cleanup_failed:
        return {"category": "cleanup_failure", "evidence": {"cleanup_failed": True}}
    error_events = private.get("error_events")
    if isinstance(error_events, list) and error_events:
        return {
            "category": "model_rpc_error",
            "evidence": {"error_event_count": len(error_events)},
        }
    failures = {} if bridge_method_failures is None else bridge_method_failures
    actual_failures = {
        key: value
        for key, value in failures.items()
        if key.startswith("method_failures_")
        and key not in {"method_failures_total"}
        and not key.endswith("_output_too_large")
        and isinstance(value, int)
        and value > 0
    }
    output_warnings = {
        key: value
        for key, value in failures.items()
        if key.endswith("_output_too_large")
        and isinstance(value, int)
        and value > 0
    }
    if (
        status.get("terminal_reason") == "human-baseline"
        and status.get("actions_remaining") == 0
    ):
        return {
            "category": "action_cap",
            "evidence": {
                key: status[key]
                for key in ("terminal_reason", "actions_remaining")
                if key in status
            } | ({"output_size_warnings": output_warnings} if output_warnings else {}),
        }
    if actual_failures:
        return {"category": "tool_error", "evidence": {"method_failures": dict(failures)}}
    returncode = private.get("process_returncode")
    if isinstance(returncode, int) and returncode != 0:
        return {"category": "process_exit", "evidence": {"process_returncode": returncode}}
    return {"category": "application_failure", "evidence": {}}


def classify_live_result(
    result: live.P7LiveExecution,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> Mapping[str, object]:
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
        provider=provider,
        model=model,
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
    provider: str | None = None,
    model: str | None = None,
) -> Mapping[str, object]:
    """Build the one public receipt; private evidence never crosses this line."""

    source = {} if receipt is None else receipt
    safe: dict[str, object] = {
        "schema": "asterion.prime.p7-live-receipt/v1",
        "application_id": "prime.arc-agi-3-solving",
        "runtime_id": "asterion.prime",
        "provider": provider or _PROVIDER,
        "model": model or _MODEL,
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


def _run_live_with_process_signals(invocation: P7Invocation, run_id: str) -> live.P7LiveExecution:
    """Translate supervisor termination into cooperative evidence-preserving cancellation."""

    cancellation = live.ProcessCancellation()
    previous: dict[int, object] = {}

    def request_cancel(_signum: int, _frame: object) -> None:
        cancellation.cancel()

    try:
        for signum in (signal_module.SIGTERM, signal_module.SIGINT):
            previous[signum] = signal_module.signal(signum, request_cancel)
        return asyncio.run(
            run_live(invocation, run_id, cancellation_signal=cancellation)
        )
    finally:
        for signum, handler in previous.items():
            signal_module.signal(signum, handler)


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
        receipt_selection = declared_model_selection(
            getattr(invocation, "environment", {})
        )
    except P7ModelSelectionError:
        receipt_selection = None
    receipt_provider = None if receipt_selection is None else receipt_selection.provider
    receipt_model = None if receipt_selection is None else receipt_selection.model
    try:
        result = classify_live_result(
            _run_live_with_process_signals(invocation, run_id),
            provider=receipt_provider,
            model=receipt_model,
        )
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
                    provider=receipt_provider,
                    model=receipt_model,
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
