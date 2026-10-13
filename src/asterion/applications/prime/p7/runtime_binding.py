"""P7-owned binding for the Prime runtime application seam."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
import json
from pathlib import Path
import sys
from typing import cast

from asterion.agents.prime.execution import (
    ASTERION_PRIME_LIMITS,
    ASTERION_PRIME_RESEARCH_LIMITS,
    AsterionPrimeLimits,
    PrimeRoundDiagnostic,
    PrimePromptRecovery,
)
from asterion.applications.prime.p7.action_journal import ActionJournal
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError, ArcStatus
from asterion.applications.prime.p7.ipython_host import PersistentIpythonHost
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
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
    P7_LEGACY_TOOL_REGISTRY,
    P7_TOOL_CAPABILITY_ID,
    P7_TOOL_MODULE_ID,
)
from asterion.applications.prime.p7.frame_analysis import summarize_frame
from asterion.runtime.factory import (
    RuntimeFactoryContext,
    RuntimeFactoryError,
)
from asterion.runtime.host import RunEvent, RunRequest
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


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


def _p7_round_diagnostic(trace_adapter: object):
    """Publish one bounded P7 round signal and retain private evidence."""

    def record(diagnostic: PrimeRoundDiagnostic) -> None:
        signals = "、".join(diagnostic.output_signals) if diagnostic.output_signals else "无"
        print(
            f"[p7] P7推理轮次：第 {diagnostic.round_index + 1} 轮；模型输出信号={signals}。",
            file=sys.stderr,
            flush=True,
        )
        try:
            getattr(trace_adapter, "record_model_round")(diagnostic)
        except Exception:
            # Private evidence must never stop the gameplay loop.
            pass

    return record


def _p7_terminal(broker: ArcBroker) -> bool:
    """Recoverable level failure stays open; RESET is always the actor's choice."""
    try:
        status = broker.status()
    except ArcBrokerError:
        status = broker.terminal_snapshot().status
    return status.terminal_reason not in {"active", "reset-required"}


def _p7_recovery_effects_settled(ipython, broker) -> bool:
    """Expose only application receipt/worker facts to Prime admission."""
    try:
        engine = broker._engine
        journal = getattr(engine, "action_journal", None)
        if (type(journal) is not ActionJournal or journal.has_unresolved
                or broker._processing_blocked
                or ipython._closed or ipython._lost):
            return False
        if type(ipython) is P7ResearchRuntime:
            status = ipython.kernel.status()
            return (not status["lost"] and not status["closed"]
                    and not ipython.kernel._lock.locked()
                    and not ipython.solver.current_context()["processing_blocked"])
        return type(ipython) is PersistentIpythonHost and not ipython._lock.locked()
    except Exception:
        return False


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


class _P7SolveEventProjector:
    """Project native tool traffic into the fixed P7 receipt-only stream."""

    __slots__ = ("_trace", "_monitor")

    def __init__(self, trace: P7PrivateTraceReceipt, monitor=None) -> None:
        self._trace = trace
        self._monitor = monitor

    async def __call__(
        self, request: RunRequest, events: AsyncIterator[RunEvent]
    ) -> AsyncIterator[RunEvent]:
        sequence = 0
        async for event in events:
            if self._monitor is not None:
                self._monitor.event(event.type, event.payload)
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
                    self._trace.record_usage(**event.payload)
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
                    self._trace.record_usage(**event.payload)
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


def build_p7_direct_runtime(host_services, options, *, services=None, gameplay=False):
    """Apply P7 policy to its local Prime owner, without provider discovery."""
    from asterion.agents.prime.application import PrimeApplication, PrimeRunHooks
    from .model_selection import DEFAULT_PROVIDER, DEFAULT_MODEL
    from .tool_dispatch import P7ToolDispatch
    owner = host_services.get('prime.launch')
    ipython = host_services.get('prime.ipython')
    broker = host_services.get('prime.arc-broker')
    trace_adapter = host_services.get('prime.arc-run-evidence' if gameplay else 'prime.private-trace')
    expected_trace = PrimeGameplayTrace if gameplay else P7PrivateTraceReceipt
    application_id = 'prime.arc-agi-3-gameplay' if gameplay else 'prime.arc-agi-3-solving'
    if type(owner) is not PrimeApplication or type(broker) is not ArcBroker:
        raise RuntimeFactoryError(_ERROR)
    try:
        authorization = owner.authorized_limits
        if type(authorization) is not AsterionPrimeLimits:
            raise ValueError
        limits = AsterionPrimeLimits(authorization.model_callbacks,
                                    authorization.tool_callbacks, authorization.deadline_ms)
    except (AttributeError, TypeError, ValueError):
        raise RuntimeFactoryError(_ERROR) from None
    supervised = type(broker.game) is P7GameSelection and broker.game.supervised_research
    first_round = (type(broker.game) is P7GameSelection and not supervised
                   and broker.game.action_cap_override is not None
                   and limits == AsterionPrimeLimits(None, None, None))
    unbounded = supervised or first_round
    autonomy = type(limits) is AsterionPrimeLimits and limits.deadline_ms == 5_400_000
    research = type(ipython) is P7ResearchRuntime
    trace = getattr(trace_adapter, 'runtime_recorder', None)
    expected_options = {
        'provider': DEFAULT_PROVIDER, 'model': DEFAULT_MODEL,
        'deadline_ms': 'none' if unbounded else str(limits.deadline_ms),
        'max_callbacks': 'none' if unbounded else str(limits.model_callbacks),
        'max_tool_callbacks': 'none' if unbounded else str(limits.tool_callbacks),
        'max_actions': 'none' if broker.game.action_cap is None else str(broker.game.action_cap),
    }
    if unbounded:
        valid_limits = limits == AsterionPrimeLimits(None, None, None)
    elif autonomy:
        valid_limits = limits == ASTERION_PRIME_RESEARCH_LIMITS
    elif limits.deadline_ms == 900_000:
        valid_limits = limits == AsterionPrimeLimits(128, 500, 900_000)
    else:
        valid_limits = limits.deadline_ms == ASTERION_PRIME_LIMITS.deadline_ms
    checks = {
        'identity': owner.identity == (application_id, '1.0.0', DEFAULT_PROVIDER, DEFAULT_MODEL),
        'host_services': set(host_services) == (_GAMEPLAY_HOST_CAPABILITIES if gameplay else _HOST_CAPABILITIES),
        'tool_registry': owner.tool_registry.matches(P7_TOOL_MODULE_ID, P7_TOOL_CAPABILITY_ID),
        'allowlist': owner.tool_registry.allowed_tool_names == (P7_APPLICATION_TOOL_NAMES if research else P7_LEGACY_TOOL_REGISTRY.allowed_tool_names),
        'ipython_type': type(ipython) in (PersistentIpythonHost, P7ResearchRuntime),
        'ipython_open': not getattr(ipython, '_closed', True) and not getattr(ipython, '_lost', True),
        'options': dict(options) == expected_options,
        'trace': type(trace_adapter) is expected_trace and type(trace) is PrimeTraceRecorder,
        'trace_broker': type(trace_adapter) is expected_trace and trace_adapter.matches_runtime_broker(broker),
        'trace_ready': trace is not None and trace._seal is None and trace._trace_fd is not None
            and (gameplay or type(trace_adapter) is P7PrivateTraceReceipt and trace_adapter.runtime_ready()),
        'limits': type(limits) is AsterionPrimeLimits and valid_limits,
        'deadline': unbounded or owner.task_deadline is not None,
    }
    if gameplay:
        checks['gameplay'] = (getattr(broker.game, 'is_full_game', False)
                              and limits == ASTERION_PRIME_LIMITS
                              and broker.status() == ArcStatus(0, 0, broker.game.action_cap, 'active'))
    elif supervised:
        checks['supervised'] = (research and broker.game.action_cap is None
                                and limits == AsterionPrimeLimits(None, None, None)
                                and owner.task_deadline is None)
    elif first_round:
        checks['unbounded'] = type(broker.game) is P7GameSelection and broker.game.action_cap_override is not None
    elif autonomy:
        checks['autonomy'] = (research and broker.game.target_level == 6 and broker.game.action_cap == 1000
                              and broker.game.action_cap_reason == 'action-cap')
    if not all(checks.values()):
        raise RuntimeFactoryError(_ERROR + ': ' + ','.join(k for k, v in checks.items() if not v))
    services = owner.services if services is None else services
    if type(services) is not P7ToolDispatch or services._host is not ipython:
        raise RuntimeFactoryError(_ERROR)
    if getattr(services, '_runtime_client', None) is not None:
        if owner.services is not services:
            raise RuntimeFactoryError(_ERROR)
        return services._runtime_client
    controller = None
    if autonomy:
        from asterion.agents.prime.continuation import PrimeContinuationBudget, PrimeContinuationController
        controller = PrimeContinuationController(PrimeContinuationBudget(owner.task_deadline.deadline_monotonic, 6))

    async def outer_admission(round_index, signal):
        if controller is not None and not await controller.admit(round_index, signal):
            return False
        return await ipython.admit_round(round_index, signal)

    recovery = (PrimePromptRecovery(lambda: _p7_recovery_effects_settled(ipython, broker),
                                   deadline_monotonic=owner.task_deadline.deadline_monotonic)
                if not unbounded and type(getattr(broker._engine, 'action_journal', None)) is ActionJournal else None)
    hooks = PrimeRunHooks(
        completion_predicate=lambda: (_p7_gameplay_terminal(broker) if gameplay else _p7_terminal(broker)),
        continuation_prompt=ipython.continuation_prompt if research else lambda i: _p7_continuation_prompt(broker, i),
        round_admission=outer_admission if research else None,
        reusable_session=autonomy, prompt_recovery=recovery,
        round_diagnostic=_p7_round_diagnostic(trace_adapter),
        failure_diagnostic=getattr(trace_adapter, 'record_failure', None))
    runtime = owner.runtime(services=services, limits=limits, hooks=hooks)
    monitor = getattr(ipython, 'research_monitor', None)
    services._runtime_client = AsterionPrimeRuntimeClient(
        runtime, event_projector=(_P7GameplayEventProjector(trace_adapter) if gameplay
                                 else _P7SolveEventProjector(trace_adapter, monitor)))
    return services._runtime_client


def _compat_runtime(context, *, gameplay):
    if (type(context) is not RuntimeFactoryContext or context.provider_id != 'prime-applications'
            or context.application_id != ('prime.arc-agi-3-gameplay' if gameplay else 'prime.arc-agi-3-solving')
            or context.application_version != '1.0.0' or context.runtime_id != 'asterion.prime'):
        raise RuntimeFactoryError(_ERROR)
    try:
        return build_p7_direct_runtime(context.host_services, context.options, gameplay=gameplay)
    except RuntimeFactoryError:
        raise
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None


def build_p7_runtime(context):
    return _compat_runtime(context, gameplay=False)


def build_p7_gameplay_runtime(context):
    return _compat_runtime(context, gameplay=True)


__all__ = ('build_p7_runtime', 'build_p7_gameplay_runtime', 'build_p7_direct_runtime',
           '_P7SolveEventProjector', '_p7_gameplay_terminal')


def compose_p7_application(*, gameplay=False):
    """Resolve this application's explicit local assembly using the existing composer."""
    from asterion.applications.provider import InstalledApplication, InstalledAssembly
    from asterion.assembly.protocol import resolve_assembly
    from asterion.capabilities.catalog import discover_capabilities
    from asterion.runtime.host import RuntimeManifest
    if gameplay:
        from asterion.capabilities.prime_arc_agi_3_gameplay.provider import create_prime_arc_agi_3_gameplay_package
        package = create_prime_arc_agi_3_gameplay_package()
    else:
        from asterion.capabilities.prime_arc_agi_3_solver.provider import create_prime_arc_agi_3_solver_package
        package = create_prime_arc_agi_3_solver_package()
    name = 'prime-arc-agi-3-gameplay' if gameplay else 'prime-arc-agi-3-solving'
    path = Path(__file__).resolve().parent.parent / 'assemblies' / (name + '.json')
    material = json.loads(path.read_text())
    plan = resolve_assembly(material, catalog=discover_capabilities(package.catalog_roots),
                            runtime_manifest=RuntimeManifest('asterion.prime', ('prime.tool.ipython',)).to_mapping())
    return InstalledApplication(material['application_id'], '1.0.0', (path,),
        (package.package_ref,), ('asterion.prime',), (package,),
        (InstalledAssembly('asterion.prime', path, plan),))
