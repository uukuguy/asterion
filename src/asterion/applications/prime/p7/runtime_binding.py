"""P7-owned binding for the Prime runtime application seam."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import cast

from asterion.agents.prime.session import AsterionPrimeSession
from asterion.agents.prime.execution import ASTERION_PRIME_LIMITS, AsterionPrimeLimits
from asterion.agents.prime.tool_registry import PrimeApplicationToolRegistry
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcStatus
from asterion.applications.prime.p7.ipython_host import PersistentIpythonHost
from asterion.applications.prime.p7.model_selection import valid_selection_name
from asterion.applications.prime.p7.private_trace import (
    P7PrivateTraceReceipt,
    P7PrivateTraceReceiptError,
)
from asterion.applications.prime.p7.gameplay_trace import (
    PrimeGameplayTrace,
    PrimeGameplayTraceError,
)
from asterion.applications.prime.p7.tool_registry import (
    P7_APPLICATION_TOOL_NAMES,
    P7_TOOL_CAPABILITY_ID,
    P7_TOOL_MODULE_ID,
)
from asterion.applications.prime.p7.frame_analysis import summarize_frame
from asterion.runtime.factory import (
    RuntimeFactoryContext,
    RuntimeFactoryError,
)
from asterion.runtime.host import AgentRuntimeClient, RunEvent, RunRequest
from asterion.runtime.native_rpc import build_rpc_session
from asterion.runtime.pinned_extension import ExtensionBinding, ExtensionLease
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient
from asterion.immutable import RedactedImmutableMapping
from asterion.services.diagnostics import MemoryDiagnosticSink


_HOST_CAPABILITIES = frozenset(
    {
        "prime.arc-broker",
        "prime.ipython",
        "prime.launch",
        "prime.private-trace",
    }
)
_RUNTIME_OPTIONS = {
    "deadline_ms": "3600000",
    "max_callbacks": "128",
}
_ERROR = "Asterion-prime runtime configuration is invalid"
_RECEIPT_ARTIFACT = "prime.p7-solving.receipt"
_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p7-solving-receipt+json"
_GAMEPLAY_HOST_CAPABILITIES = frozenset(
    {"prime.arc-broker", "prime.arc-run-evidence", "prime.ipython", "prime.launch"}
)
_GAMEPLAY_OPTIONS = {
    "deadline_ms": "3600000",
    "max_callbacks": "128",
}
_GAMEPLAY_ARTIFACT = "prime.p7-gameplay-run.evidence"
_GAMEPLAY_MEDIA_TYPE = "application/vnd.asterion.prime.p7-gameplay-run+json"


def _launch_selection(command: object) -> tuple[str, str] | None:
    """Return the one provider/model pair the approved launch declares."""

    if type(command) is not tuple or not command:
        return None
    declared: dict[str, str] = {}
    for flag in ("--provider", "--model"):
        positions = [index for index, part in enumerate(command) if part == flag]
        if len(positions) != 1:
            return None
        value = command[positions[0] + 1 : positions[0] + 2]
        if len(value) != 1 or not valid_selection_name(value[0]):
            return None
        declared[flag] = value[0]
    return declared["--provider"], declared["--model"]


def _p7_terminal(broker: ArcBroker) -> bool:
    """Stop model continuation once the broker can no longer accept actions."""

    try:
        broker.seal()
    except Exception:
        return False
    return True


def _p7_gameplay_terminal(broker: ArcBroker) -> bool:
    """Keep official gameplay open while the current level requires RESET."""

    try:
        return broker.status().terminal_reason not in {"active", "reset-required"}
    except Exception:
        return True


def _p7_continuation_prompt(broker: ArcBroker, round_index: int) -> str:
    """Carry the latest settled state into every model continuation round."""

    if (
        type(round_index) is not int
        or round_index < 1
        or not callable(getattr(broker, "status", None))
        or not callable(getattr(broker, "observe", None))
        or not hasattr(getattr(broker, "game", None), "target_level")
    ):
        raise RuntimeFactoryError(_ERROR)
    status = broker.status()
    observation = broker.observe()
    tried_summary: Mapping[str, object] = {}
    tried_actions = getattr(broker, "tried_actions", None)
    last_outcome_summary = getattr(broker, "last_outcome_summary", None)
    if callable(tried_actions) and callable(last_outcome_summary):
        tried = tried_actions(observation.levels_completed)
        top_repeated = sorted(
            (
                item
                for item in tried
                if isinstance(item, Mapping)
                and type(item.get("count")) is int
                and not isinstance(item.get("count"), bool)
            ),
            key=lambda item: (-item["count"], str(item.get("action", ""))),
        )[:5]
        outcome = last_outcome_summary(observation.levels_completed)
        tried_summary = {
            "attempts": outcome.get("attempts", {}) if isinstance(outcome, Mapping) else {},
            "no_effect": outcome.get("no_effect", {}) if isinstance(outcome, Mapping) else {},
            "top_repeated": top_repeated,
        }
    top_count = max(
        (
            item.get("count", 0)
            for item in tried_summary.get("top_repeated", ())
            if isinstance(item, Mapping)
        ),
        default=0,
    )
    action_guard = (
        "force-replan-after-repeated-action"
        if top_count >= 10
        else "no-repetition-threshold"
    )
    state = {
        "available_actions": list(observation.available_actions),
        "frame_summary": summarize_frame(observation.frame),
        "levels_completed": observation.levels_completed,
        "state": observation.state,
        "win_levels": observation.win_levels,
        "actions_remaining": status.actions_remaining,
        "primitive_actions": status.primitive_actions,
        "target_level": broker.game.target_level,
        "terminal_reason": status.terminal_reason,
        "tried_summary": tried_summary,
        "action_guard": action_guard,
    }
    return (
        f"Continue Round {round_index} from this application-supplied settled state. "
        "Treat it as authoritative. Before another read-only query, perform one "
        "falsifiable gameplay action or RESET that distinguishes the current "
        "hypothesis; record the expected changed region and stop condition. "
        "If action_guard is force-replan-after-repeated-action, stop repeating "
        "that action and RESET or switch to one different probe.\n"
        + json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


@dataclass(frozen=True, repr=False, slots=True)
class PrimeLaunch:
    """Plain-data launch material crossing the application-runtime seam.

    Carries only operator-owned authorization (command argv, environment) and
    the extension resource's plain identity plus its already-acquired pinned
    file descriptors. The only live object is the transferable ``ExtensionLease``
    itself: it is the single owner of the pinned descriptors, and dropping it in
    favour of a plain snapshot would force a path re-resolution (TOCTOU) or a
    second descriptor owner. See ``runtime/pinned_extension.py``.
    """

    approved_command: tuple[str, ...]
    working_directory: Path
    extension_id: str
    extension_path: Path
    extension_capabilities: tuple[str, ...]
    binding_inherited_fds: tuple[int, ...]
    binding_environment: Mapping[str, str]
    extension_lease: ExtensionLease
    deadline_seconds: float | None
    tool_registry: PrimeApplicationToolRegistry
    compact_events: bool = True
    approved_environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        lease = self.extension_lease
        valid = (
            type(lease) is ExtensionLease
            and type(self.approved_command) is tuple
            and bool(self.approved_command)
            and all(type(part) is str and part for part in self.approved_command)
            and isinstance(self.working_directory, Path)
            and type(self.extension_id) is str
            and self.extension_id == "prime.ipython"
            and isinstance(self.extension_path, Path)
            and type(self.extension_capabilities) is tuple
            and self.extension_capabilities == ("prime.tool.ipython",)
            and type(self.binding_inherited_fds) is tuple
            and isinstance(self.binding_environment, Mapping)
            and (self.deadline_seconds is None or (
                type(self.deadline_seconds) is float and self.deadline_seconds > 0
            ))
            and type(self.compact_events) is bool
            and type(self.tool_registry) is PrimeApplicationToolRegistry
            and not lease.closed
        )
        if not valid:
            if type(lease) is ExtensionLease:
                lease.close()
            raise RuntimeFactoryError(_ERROR)
        try:
            environment = (
                dict(lease.environment)
                if self.approved_environment is None
                else dict(self.approved_environment)
            )
        except (TypeError, ValueError):
            lease.close()
            raise RuntimeFactoryError(_ERROR) from None
        if any(
            environment.get(name) != value for name, value in lease.environment.items()
        ):
            lease.close()
            raise RuntimeFactoryError(_ERROR)
        object.__setattr__(
            self, "approved_environment", RedactedImmutableMapping(environment)
        )

    def __repr__(self) -> str:
        return "<PrimeLaunch redacted>"


class _P7SolveEventProjector:
    """Project native tool traffic into the fixed P7 receipt-only stream."""

    __slots__ = ("_trace",)

    def __init__(self, trace: P7PrivateTraceReceipt) -> None:
        self._trace = trace

    async def __call__(
        self, request: RunRequest, events: AsyncIterator[RunEvent]
    ) -> AsyncIterator[RunEvent]:
        sequence = 0
        async for event in events:
            if event.type == "run.started":
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    event.type,
                    cast(Mapping[str, object], event.to_mapping()["payload"]),
                )
                continue
            if event.type == "run.failed":
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    event.type,
                    cast(Mapping[str, object], event.to_mapping()["payload"]),
                )
                continue
            if event.type == "usage.reported":
                try:
                    self._trace.record_usage(
                        input_tokens=cast(int, event.payload["input_tokens"]),
                        output_tokens=cast(int, event.payload["output_tokens"]),
                    )
                except (KeyError, P7PrivateTraceReceiptError):
                    sequence += 1
                    yield RunEvent(
                        request.run_id,
                        sequence,
                        "run.failed",
                        {
                            "code": "p7_usage_invalid",
                            "message": "P7 usage evidence is invalid.",
                        },
                    )
                    return
                continue
            if event.type != "run.completed":
                continue
            if event.payload != {"status": "completed"}:
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    event.type,
                    cast(Mapping[str, object], event.to_mapping()["payload"]),
                )
                continue
            try:
                receipt_sha256 = self._trace.expected_receipt_sha256(
                    run_id=request.run_id
                )
            except P7PrivateTraceReceiptError:
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    "run.failed",
                    {
                        "code": "p7_level_not_completed",
                        "message": "P7 level was not completed.",
                    },
                )
                continue
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "artifact.created",
                {
                    "artifact": {
                        "artifact_id": _RECEIPT_ARTIFACT,
                        "kind": "p7-solving",
                        "media_type": _RECEIPT_MEDIA_TYPE,
                        "sha256": receipt_sha256.removeprefix("sha256:"),
                    }
                },
            )
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                event.type,
                cast(Mapping[str, object], event.to_mapping()["payload"]),
            )


class _P7GameplayEventProjector:
    """Project native tool traffic into one private gameplay evidence artifact."""

    __slots__ = ("_trace",)

    def __init__(self, trace: PrimeGameplayTrace) -> None:
        self._trace = trace

    async def __call__(
        self, request: RunRequest, events: AsyncIterator[RunEvent]
    ) -> AsyncIterator[RunEvent]:
        sequence = 0
        async for event in events:
            if event.type in {"run.started", "run.failed"}:
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    event.type,
                    cast(Mapping[str, object], event.to_mapping()["payload"]),
                )
                continue
            if event.type == "usage.reported":
                try:
                    self._trace.record_usage(
                        input_tokens=cast(int, event.payload["input_tokens"]),
                        output_tokens=cast(int, event.payload["output_tokens"]),
                    )
                except (KeyError, PrimeGameplayTraceError):
                    sequence += 1
                    yield RunEvent(
                        request.run_id,
                        sequence,
                        "run.failed",
                        {"code": "p7_usage_invalid", "message": "P7 usage evidence is invalid."},
                    )
                    return
                continue
            if event.type != "run.completed":
                continue
            if event.payload != {"status": "completed"}:
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    event.type,
                    cast(Mapping[str, object], event.to_mapping()["payload"]),
                )
                continue
            try:
                evidence_sha256 = self._trace.expected_evidence_sha256(
                    run_id=request.run_id
                )
            except PrimeGameplayTraceError:
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    "run.failed",
                    {"code": "p7_gameplay_unavailable", "message": "P7 gameplay evidence is unavailable."},
                )
                return
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "artifact.created",
                {
                    "artifact": {
                        "artifact_id": _GAMEPLAY_ARTIFACT,
                        "kind": "p7-gameplay-run",
                        "media_type": _GAMEPLAY_MEDIA_TYPE,
                        "sha256": evidence_sha256.removeprefix("sha256:"),
                    }
                },
            )
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                event.type,
                cast(Mapping[str, object], event.to_mapping()["payload"]),
            )


def build_p7_runtime(
    context: RuntimeFactoryContext,
) -> AgentRuntimeClient:
    """Assemble P7 from its exact host-preflighted resources."""

    if type(context) is not RuntimeFactoryContext:
        raise RuntimeFactoryError(_ERROR)
    launch_value = context.host_services.get("prime.launch")
    launch = launch_value if type(launch_value) is PrimeLaunch else None
    try:
        ipython = context.host_services.get("prime.ipython")
        broker = context.host_services.get("prime.arc-broker")
        trace_service = context.host_services.get("prime.private-trace")
        trace_adapter = (
            trace_service if type(trace_service) is P7PrivateTraceReceipt else None
        )
        trace = None if trace_adapter is None else trace_adapter.runtime_recorder
        unbounded = launch is not None and launch.deadline_seconds is None
        declared = None if launch is None else _launch_selection(launch.approved_command)
        expected_options = dict(_RUNTIME_OPTIONS)
        provider = context.options.get("provider")
        model = context.options.get("model")
        if (
            type(provider) is not str or not provider
            or type(model) is not str or not model
            or not provider.isascii() or not model.isascii()
        ):
            raise RuntimeFactoryError(_ERROR)
        expected_options.update(provider=provider, model=model)
        if unbounded:
            # The operator validates OFFLINE authorization before stripping ARC
            # configuration from the model subprocess environment. This seam
            # consumes that injected launch and its local sweep action cap.
            environment = launch.approved_environment or {}
            if (
                type(broker) is not ArcBroker
                or type(broker.game) is not P7GameSelection
                or broker.game.action_cap_override is None
                or environment.get("ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND") != "1"
                or environment.get("ASTERION_PRIME_P7_RUN_MODE") != "sweep"
            ):
                raise RuntimeFactoryError(_ERROR)
            expected_options.update(deadline_ms="none", max_callbacks="none")
        checks = {
            "provider_id": context.provider_id == "prime-applications",
            "application_id": context.application_id == "prime.arc-agi-3-solving",
            "application_version": context.application_version == "1.0.0",
            "runtime_id": context.runtime_id == "asterion.prime",
            "host_services": set(context.host_services) == _HOST_CAPABILITIES,
            "launch": launch is not None,
            "selection": declared == (provider, model),
            "tool_registry": launch is not None and launch.tool_registry.matches(P7_TOOL_MODULE_ID, P7_TOOL_CAPABILITY_ID),
            "allowlist": launch is not None and launch.tool_registry.allowed_tool_names == P7_APPLICATION_TOOL_NAMES,
            "ipython_type": type(ipython) is PersistentIpythonHost,
            "ipython_open": not getattr(ipython, "_closed", True),
            "ipython_lost": not getattr(ipython, "_lost", True),
            "broker_type": type(broker) is ArcBroker,
            "options": type(broker) is ArcBroker and dict(context.options) == {**expected_options, "max_actions": str(broker.game.action_cap)},
            "trace_service": trace_adapter is not None,
            "trace": trace is not None,
            "trace_broker": trace_adapter is not None and trace_adapter.matches_runtime_broker(broker),
            "trace_ready": trace_adapter is not None and trace_adapter.runtime_ready(),
            "trace_type": type(trace) is PrimeTraceRecorder,
            "trace_sealed": trace is not None and trace._seal is None,
            "trace_fd": trace is not None and trace._trace_fd is not None,
        }
        if not all(checks.values()):
            failed = ",".join(name for name, passed in checks.items() if not passed)
            raise RuntimeFactoryError(f"{_ERROR}: {failed}")
        # Reconstruct the framework-owned launch objects from plain data. The
        # pinned extension is already acquired (fd + digest) by the operator;
        # this factory consumes those exact descriptors without re-resolving
        # the extension source by path.
        binding = ExtensionBinding(
            extension_id=launch.extension_id,
            path=launch.extension_path,
            capabilities=launch.extension_capabilities,
            inherited_fds=launch.binding_inherited_fds,
            environment=launch.binding_environment,
        )
        if binding.binding_fingerprint != launch.extension_lease.binding_fingerprint:
            raise RuntimeFactoryError(_ERROR)
        diagnostic_sink = MemoryDiagnosticSink()
        rpc_session = build_rpc_session(
            command=launch.approved_command,
            cwd=launch.working_directory,
            environment=launch.approved_environment or {},
            deadline_seconds=launch.deadline_seconds,
            inherited_fds=launch.extension_lease.inherited_fds,
            compact_events=launch.compact_events,
            diagnostics=diagnostic_sink,
        )
        session = AsterionPrimeSession(
            rpc_session=rpc_session,
            extension_binding=binding,
            extension_lease=launch.extension_lease,
            approved_command=launch.approved_command,
            approved_environment=launch.approved_environment,
            limits=AsterionPrimeLimits(None, None, None) if unbounded else ASTERION_PRIME_LIMITS,
            completion_predicate=lambda: _p7_terminal(broker),
            continuation_prompt=lambda round_index: _p7_continuation_prompt(broker, round_index),
            round_diagnostic=getattr(trace_adapter, "record_model_round", None),
            failure_diagnostic=getattr(trace_adapter, "record_failure", None),
            allowed_tool_names=launch.tool_registry.allowed_tool_names,
        )
        launch = None
        return AsterionPrimeRuntimeClient(
            session, event_projector=_P7SolveEventProjector(trace_adapter)
        )
    except RuntimeFactoryError:
        raise
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None
    finally:
        if launch is not None:
            launch.extension_lease.close()


def build_p7_gameplay_runtime(context: RuntimeFactoryContext) -> AgentRuntimeClient:
    """Assemble the scoreless official gameplay route."""
    if type(context) is not RuntimeFactoryContext:
        raise RuntimeFactoryError(_ERROR)
    launch_value = context.host_services.get("prime.launch")
    launch = launch_value if type(launch_value) is PrimeLaunch else None
    try:
        provider = context.options.get("provider")
        model = context.options.get("model")
        if (
            type(provider) is not str or not provider
            or type(model) is not str or not model
            or not provider.isascii() or not model.isascii()
        ):
            raise RuntimeFactoryError(_ERROR)
        ipython = context.host_services.get("prime.ipython")
        broker = context.host_services.get("prime.arc-broker")
        trace_value = context.host_services.get("prime.arc-run-evidence")
        trace_adapter = trace_value if type(trace_value) is PrimeGameplayTrace else None
        trace = None if trace_adapter is None else trace_adapter.runtime_recorder
        declared = None if launch is None else _launch_selection(launch.approved_command)
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.arc-agi-3-gameplay"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(context.host_services) != _GAMEPLAY_HOST_CAPABILITIES
            or launch is None
            or declared != (provider, model)
            or not launch.tool_registry.matches(P7_TOOL_MODULE_ID, P7_TOOL_CAPABILITY_ID)
            or launch.tool_registry.allowed_tool_names != P7_APPLICATION_TOOL_NAMES
            or type(ipython) is not PersistentIpythonHost
            or getattr(ipython, "_closed", True)
            or getattr(ipython, "_lost", True)
            or type(broker) is not ArcBroker
            or not getattr(broker.game, "is_full_game", False)
            or dict(context.options) != {
                **_GAMEPLAY_OPTIONS,
                "provider": provider,
                "model": model,
                "max_actions": str(broker.game.action_cap),
            }
            or broker.status() != ArcStatus(0, 0, broker.game.action_cap, "active")
            or trace_adapter is None
            or trace is None
            or not trace_adapter.matches_runtime_broker(broker)
            or type(trace) is not PrimeTraceRecorder
            or trace._seal is not None
            or trace._trace_fd is None
        ):
            raise RuntimeFactoryError(_ERROR)
        binding = ExtensionBinding(
            extension_id=launch.extension_id,
            path=launch.extension_path,
            capabilities=launch.extension_capabilities,
            inherited_fds=launch.binding_inherited_fds,
            environment=launch.binding_environment,
        )
        if binding.binding_fingerprint != launch.extension_lease.binding_fingerprint:
            raise RuntimeFactoryError(_ERROR)
        rpc_session = build_rpc_session(
            command=launch.approved_command,
            cwd=launch.working_directory,
            environment=launch.approved_environment or {},
            deadline_seconds=launch.deadline_seconds,
            inherited_fds=launch.extension_lease.inherited_fds,
            compact_events=launch.compact_events,
        )
        session = AsterionPrimeSession(
            rpc_session=rpc_session,
            extension_binding=binding,
            extension_lease=launch.extension_lease,
            approved_command=launch.approved_command,
            approved_environment=launch.approved_environment,
            completion_predicate=lambda: _p7_gameplay_terminal(broker),
            allowed_tool_names=launch.tool_registry.allowed_tool_names,
        )
        launch = None
        return AsterionPrimeRuntimeClient(
            session, event_projector=_P7GameplayEventProjector(trace_adapter)
        )
    except RuntimeFactoryError:
        raise
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None
    finally:
        if launch is not None:
            launch.extension_lease.close()


__all__ = (
    "PrimeLaunch",
    "build_p7_runtime",
    "build_p7_gameplay_runtime",
    "_P7SolveEventProjector",
    "_p7_gameplay_terminal",
)
