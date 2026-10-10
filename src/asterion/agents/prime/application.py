"""Independent Prime application ownership without discovery or launch effects.

These are process-local inputs, not an additional serialized protocol. Operator
preflight owns paths, credentials, model selection and verified price evidence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
import asyncio
import re
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from asterion.agents.prime import _launch
from asterion.agents.prime._workspace_owner import WorkspaceOwner
from asterion.agents.prime._text_model import (
    LiveModelReply, LiveModelSession, LiveModelUsage, _TextUsage, _cost,
)
from asterion.agents.prime.backend import PrimeAttachment, PrimeSessionBackend
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.agents.prime.ipython import (
    KernelBootstrap, KernelExport, KernelLimits, PersistentIpythonHost,
)
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.deadline import TaskDeadline
from asterion.agents.prime.execution import (
    AsterionPrimeLimits,
    PrimePromptRecovery,
    PrimeRoundDiagnostic,
)
from asterion.agents.prime.tool_registry import PrimeApplicationToolRegistry
from asterion.agents.prime.tools import PrimeToolResult
from asterion.capabilities.protocol import SEMANTIC_VERSION
from asterion.runtime.host import AgentRuntimeClient, CancellationSignal, RunRequest
from asterion.runtime.protocol import IDENTIFIER, ProtocolError
from asterion.services.diagnostics import (
    DiagnosticSink,
    FailureDiagnostic,
    PrivateFailureSink,
)


def _invalid() -> None:
    raise ProtocolError('Prime application material is invalid')


def _identifier(value: object) -> None:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        _invalid()


def _path(value: object) -> None:
    if not isinstance(value, Path) or not value.is_absolute():
        _invalid()


def _strings(value: object) -> Mapping[str, str]:
    try:
        if not isinstance(value, Mapping):
            _invalid()
        copied = dict(value)
        if any(type(k) is not str or not k or '\x00' in k or '=' in k
               or type(v) is not str or '\x00' in v for k, v in copied.items()):
            _invalid()
        return MappingProxyType(copied)
    except Exception:
        raise ProtocolError('Prime application material is invalid') from None


@dataclass(frozen=True, slots=True, repr=False)
class PrimeOperatorContext:
    executable: Path
    entry: Path | None
    cwd: Path
    provider: str
    model: str
    effort: str
    environment: Mapping[str, str]
    task_deadline: TaskDeadline | None
    diagnostics: DiagnosticSink | None = None
    private_failure_sink: PrivateFailureSink | None = None
    private_root: Path | None = None

    def __post_init__(self) -> None:
        for path in (self.executable, self.cwd):
            _path(path)
        if self.entry is not None:
            _path(self.entry)
        if self.private_root is not None:
            _path(self.private_root)
        _identifier(self.provider)
        _identifier(self.model)
        if type(self.effort) is not str or self.effort not in (
            'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'
        ):
            _invalid()
        if self.task_deadline is not None and type(self.task_deadline) is not TaskDeadline:
            _invalid()
        object.__setattr__(self, 'environment', _strings(self.environment))

    def __repr__(self) -> str:
        return '<PrimeOperatorContext redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class PrimeToolModuleArtifact:
    path: Path
    registry: PrimeApplicationToolRegistry

    def __post_init__(self) -> None:
        _path(self.path)
        if type(self.registry) is not PrimeApplicationToolRegistry:
            _invalid()
        self.registry.__post_init__()

    def __repr__(self) -> str:
        return '<PrimeToolModuleArtifact redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class PrimeApplicationSpec:
    application_id: str
    application_version: str
    profile: Literal['text-only', 'persistent-code-tools']
    system_prompt: str | None = None
    tools: PrimeToolModuleArtifact | None = None

    def __post_init__(self) -> None:
        _identifier(self.application_id)
        if (type(self.application_version) is not str
                or SEMANTIC_VERSION.fullmatch(self.application_version) is None):
            _invalid()
        if type(self.profile) is not str or self.profile not in (
            'text-only', 'persistent-code-tools'
        ):
            _invalid()
        if self.system_prompt is not None:
            if type(self.system_prompt) is not str:
                _invalid()
            try:
                self.system_prompt.encode('utf-8')
            except UnicodeError:
                raise ProtocolError('Prime application material is invalid') from None
        if self.profile == 'text-only':
            if self.tools is not None:
                _invalid()
        elif type(self.tools) is not PrimeToolModuleArtifact:
            _invalid()

    def __repr__(self) -> str:
        return '<PrimeApplicationSpec redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class PrimeTextLimits:
    deadline_seconds: float
    max_prompts: int | None = None
    max_input_bytes: int | None = None
    max_output_bytes: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_micros: int | None = None
    provider_output_tokens: int | None = None
    price: ModelPrice | None = None

    def __post_init__(self) -> None:
        if (type(self.deadline_seconds) not in (float, int)
                or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0):
            _invalid()
        for field in fields(self):
            if field.name in ('deadline_seconds', 'price'):
                continue
            value = getattr(self, field.name)
            if value is not None and (type(value) is not int or value <= 0):
                _invalid()
        if self.price is not None and type(self.price) is not ModelPrice:
            _invalid()
        if self.max_cost_micros is not None and self.price is None:
            _invalid()

    def __repr__(self) -> str:
        return '<PrimeTextLimits redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class PrimeRunHooks:
    completion_predicate: Callable[[], bool] | None = None
    continuation_prompt: Callable[[int], str] | None = None
    round_admission: Callable[[int, CancellationSignal], Awaitable[bool]] | None = None
    round_diagnostic: Callable[[PrimeRoundDiagnostic], None] | None = None
    failure_diagnostic: Callable[[FailureDiagnostic | None], None] | None = None
    prompt_recovery: PrimePromptRecovery | None = None
    reusable_session: bool = False

    def __post_init__(self) -> None:
        for name in ('completion_predicate', 'continuation_prompt', 'round_admission',
                     'round_diagnostic', 'failure_diagnostic'):
            value = getattr(self, name)
            if value is not None and not callable(value):
                _invalid()
        if (type(self.reusable_session) is not bool
                or self.prompt_recovery is not None
                and type(self.prompt_recovery) is not PrimePromptRecovery):
            _invalid()

    def __repr__(self) -> str:
        return '<PrimeRunHooks redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class PrimeBackendSpec:
    session_id: str
    generation: int
    private_root: Path
    continuation_policy_id: str
    limits: AsterionPrimeLimits
    aggregate_tokens: int
    cost_micros: int
    model_price: ModelPrice | None
    authority_id: str | None
    compaction_instructions: Mapping[str, str] | None
    compat_provider_id: str | None = None

    def __post_init__(self) -> None:
        # Existing backend session/authority IDs allow opaque mixed-case IDs.
        from asterion.control.protocol import OPAQUE_ID

        if (type(self.session_id) is not str
                or OPAQUE_ID.fullmatch(self.session_id) is None):
            _invalid()
        for value in (self.generation, self.aggregate_tokens, self.cost_micros):
            if type(value) is not int or not 1 <= value <= (1 << 53) - 1:
                _invalid()
        _path(self.private_root)
        if (type(self.continuation_policy_id) is not str
                or OPAQUE_ID.fullmatch(self.continuation_policy_id) is None):
            _invalid()
        if type(self.limits) is not AsterionPrimeLimits:
            _invalid()
        if self.model_price is not None and type(self.model_price) is not ModelPrice:
            _invalid()
        for value in (self.authority_id, self.compat_provider_id):
            if value is not None and (
                type(value) is not str or OPAQUE_ID.fullmatch(value) is None
            ):
                _invalid()
        if self.compaction_instructions is not None:
            if not isinstance(self.compaction_instructions, Mapping):
                _invalid()
            instructions = dict(self.compaction_instructions)
            if any(type(key) is not str or OPAQUE_ID.fullmatch(key) is None
                   or type(text) is not str or not text
                   for key, text in instructions.items()):
                _invalid()
            object.__setattr__(self, 'compaction_instructions', MappingProxyType(instructions))

    def __repr__(self) -> str:
        return '<PrimeBackendSpec redacted>'


class PrimeModelView(Protocol):
    async def prompt(self, text: str, *, signal: CancellationSignal) -> LiveModelReply: ...


class PrimeApplicationServices(Protocol):
    """Domain execution only; the core owns transport and process startup."""

    @property
    def identity_sha256(self) -> str: ...
    def validate_lifecycle(self) -> object: ...
    async def execute(self, request_id: str, code: str,
                      signal: CancellationSignal) -> PrimeToolResult: ...
    async def call(self, request_id: str, method: str, params: object,
                   signal: CancellationSignal, *, params_present: bool = True) -> Mapping[str, object]: ...
    def request_stop(self) -> None: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PrimeApplicationCleanup:
    effects_stopped: bool
    model_closed: bool
    extension_closed: bool
    bridge_closed: bool
    workspace_closed: bool

    def __post_init__(self) -> None:
        if any(type(getattr(self, field.name)) is not bool for field in fields(self)):
            _invalid()

    @property
    def complete(self) -> bool:
        return all(getattr(self, field.name) for field in fields(self))


class _PrimeModelView:
    __slots__ = ('_owner', '_key')

    def __init__(self, owner: PrimeApplication, key: str):
        self._owner, self._key = owner, key

    def __repr__(self) -> str:
        return '<PrimeModelView redacted>'

    async def prompt(self, text: str, *, signal: CancellationSignal) -> LiveModelReply:
        return await self._owner._prompt_text(self._key, text, signal=signal)


@dataclass(frozen=True, slots=True, repr=False)
class _PrimeTextIdentitySummary:
    command_sha256: str
    binding_sha256: str

    def __repr__(self) -> str:
        return '<Prime text identity redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class _PrimeTextUsageSummary:
    prompts: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    unknown_effect: bool
    blocked: bool

    def __repr__(self) -> str:
        return '<Prime text usage redacted>'


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class PrimeApplication:
    """Resource owner with fixed authorization; construction never launches Pi."""

    __slots__ = ('_spec', '_operator', '_authorization', '_state',
                 '_text_limits_by_key', '_cleanup', '_text_sessions', '_text_closed_keys',
                 '_text_usage', '_runtime_client', '_runtime_material', '_persistent',
                 '_services', '_workspace_owner', '_metrics_root', '_run_claimed', '_backend')

    def __init__(self, spec: PrimeApplicationSpec, operator: PrimeOperatorContext, *,
                 authorization: PrimeTextLimits | AsterionPrimeLimits | PrimeBackendSpec):
        if type(spec) is not PrimeApplicationSpec or type(operator) is not PrimeOperatorContext:
            _invalid()
        if spec.profile == 'text-only':
            if type(authorization) is not PrimeTextLimits:
                _invalid()
        elif type(authorization) not in (AsterionPrimeLimits, PrimeBackendSpec):
            _invalid()
        self._runtime_client = self._runtime_material = self._persistent = self._services = None
        self._backend = None
        self._workspace_owner = WorkspaceOwner()
        self._metrics_root = operator.private_root
        self._run_claimed = False
        self._spec = spec
        self._operator = operator
        self._authorization = authorization
        self._state = 'prepared'
        self._text_limits_by_key: dict[str, PrimeTextLimits] = {}
        self._cleanup: PrimeApplicationCleanup | None = None
        self._text_sessions: dict[str, LiveModelSession] = {}
        self._text_closed_keys: set[str] = set()
        self._text_usage = (_TextUsage(authorization, operator.task_deadline)
                            if type(authorization) is PrimeTextLimits else None)

    def __repr__(self) -> str:
        return '<PrimeApplication redacted>'

    def _text_identity_summary(self) -> _PrimeTextIdentitySummary:
        if self._spec.profile != 'text-only':
            _invalid()
        return _PrimeTextIdentitySummary(
            _digest(_launch.text_command(self._operator, self._spec)),
            _digest({'profile': 'text-only', 'tools': (), 'extensions': (),
                     'provider': self._operator.provider, 'model': self._operator.model}),
        )

    def _text_usage_summary(self) -> _PrimeTextUsageSummary:
        usage = self._text_usage
        if usage is None:
            _invalid()
        return _PrimeTextUsageSummary(
            usage.prompts, usage.input_tokens, usage.output_tokens,
            _cost(usage.input_tokens, usage.output_tokens, self._authorization.price),
            usage.unknown_effect, usage.blocked,
        )

    @property
    def state(self) -> Literal['prepared', 'active', 'closing', 'closed']:
        return self._state

    def _require_available(self) -> None:
        if self._state not in ('prepared', 'active'):
            raise ProtocolError('Prime application is closed')

    def _activate(self) -> None:
        self._require_available()
        self._state = 'active'

    def _admit_text_limits(self, key: str, limits: PrimeTextLimits) -> None:
        self._require_available()
        _identifier(key)
        approved = self._authorization
        if type(approved) is not PrimeTextLimits or type(limits) is not PrimeTextLimits:
            _invalid()
        for field in fields(limits):
            value, ceiling = getattr(limits, field.name), getattr(approved, field.name)
            if field.name == 'price':
                if value != ceiling:
                    _invalid()
            elif ceiling is not None and (value is None or value > ceiling):
                _invalid()
        existing = self._text_limits_by_key.get(key)
        if existing is not None and existing != limits:
            raise ProtocolError('Prime application text key limits are fixed')
        self._text_limits_by_key[key] = limits

    def _admit_runtime_limits(self, limits: AsterionPrimeLimits) -> None:
        self._require_available()
        if self._spec.profile != 'persistent-code-tools' or type(limits) is not AsterionPrimeLimits:
            _invalid()
        approved = self._authorization
        if type(approved) is PrimeBackendSpec:
            approved = approved.limits
        if type(approved) is not AsterionPrimeLimits:
            _invalid()
        for field in fields(limits):
            value, ceiling = getattr(limits, field.name), getattr(approved, field.name)
            if ceiling is not None and (value is None or value > ceiling):
                _invalid()

    def text_model(self, *, key: str, limits: PrimeTextLimits) -> PrimeModelView:
        self._admit_text_limits(key, limits)
        if key in self._text_closed_keys:
            raise ProtocolError('Prime application text key is closed')
        return _PrimeModelView(self, key)

    async def text_once(self, *, key: str, text: str, limits: PrimeTextLimits,
                        signal: CancellationSignal) -> LiveModelReply:
        view = self.text_model(key=key, limits=limits)
        try:
            return await view.prompt(text, signal=signal)
        finally:
            self._text_closed_keys.add(key)
            session = self._text_sessions.get(key)
            if session is not None:
                await session.close()

    async def _prompt_text(self, key: str, text: str, *, signal: CancellationSignal) -> LiveModelReply:
        usage = self._text_usage
        if usage is None:
            _invalid()
        async with usage.lock:
            self._require_available()
            if key in self._text_closed_keys:
                raise ProtocolError('Prime application text key is closed')
            limits = self._text_limits_by_key[key]
            usage.remaining(limits)
            session = self._text_sessions.get(key)
            try:
                if session is None:
                    session = LiveModelSession(
                        command=_launch.text_command(self._operator, self._spec),
                        environment=self._operator.environment, cwd=self._operator.cwd,
                        provider=self._operator.provider, model=self._operator.model,
                        limits=limits, usage=usage,
                    )
                    self._text_sessions[key] = session
                    self._activate()
                    await session.open(signal=signal)
                return await session.prompt(text, signal=signal)
            except BaseException:
                self._text_closed_keys.add(key)
                raise

    def runtime(self, *, services: PrimeApplicationServices, limits: AsterionPrimeLimits,
                hooks: PrimeRunHooks) -> AgentRuntimeClient:
        if type(self._authorization) is PrimeBackendSpec:
            raise ProtocolError('Prime durable owner already fixes the execution view')
        self._admit_runtime_limits(limits)
        if (type(hooks) is not PrimeRunHooks or any(not callable(getattr(services, name, None))
                for name in ('execute', 'call', 'request_stop', 'close', 'validate_lifecycle'))
                or type(getattr(services, 'identity_sha256', None)) is not str
                or re.fullmatch(r'[0-9a-f]{64}', services.identity_sha256) is None):
            _invalid()
        try:
            services.validate_lifecycle()
        except Exception:
            _invalid()
        if self._runtime_client is not None:
            if self._services is not services or self._runtime_material != (limits, hooks):
                raise ProtocolError('Prime runtime view is fixed')
            return self._runtime_client
        self._services = services
        self._runtime_material = (limits, hooks)
        from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient
        self._runtime_client = AsterionPrimeRuntimeClient(_OwnedRuntimeSession(self))
        return self._runtime_client

    @property
    def services(self) -> PrimeApplicationServices | None:
        return self._services

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self._spec.application_id, self._spec.application_version,
                self._operator.provider, self._operator.model)

    @property
    def tool_registry(self) -> PrimeApplicationToolRegistry | None:
        return self._spec.tools.registry if self._spec.tools is not None else None

    @property
    def authorized_limits(self) -> PrimeTextLimits | AsterionPrimeLimits:
        return self._authorization.limits if type(self._authorization) is PrimeBackendSpec else self._authorization

    @property
    def task_deadline(self) -> TaskDeadline | None:
        return self._operator.task_deadline

    def create_workspace(
        self, bootstrap: KernelBootstrap, limits: KernelLimits, *, python: Path | None = None,
        observer: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> PersistentIpythonHost:
        self._require_available()
        if self._spec.profile != 'persistent-code-tools':
            _invalid()
        workspace = self._workspace_owner.create_workspace(bootstrap, limits, python=python,
                                                           observer=observer)
        return workspace

    async def restore_workspace(
        self, previous: PersistentIpythonHost, source_exports: tuple[KernelExport, ...],
        data_exports: Mapping[str, KernelExport], signal: CancellationSignal,
    ) -> PersistentIpythonHost:
        self._require_available()
        return await self._workspace_owner.restore_workspace(previous, source_exports, data_exports, signal)

    def runtime_observation(self):
        """Private, body-free accounting without exposing a transport handle."""
        from hashlib import sha256
        resource = self._persistent
        if resource is None:
            return {}
        stderr = resource.rpc.stderr
        return {'stderr_bytes': len(stderr), 'stderr_sha256': sha256(stderr).hexdigest(),
                'model_failed': bool(resource.rpc.last_failure),
                'native_event_summary': resource.session.native_event_summary}

    def context_view_metrics(self):
        resource = self._persistent
        return resource.metrics.read() if resource is not None and resource.metrics else {'status': 'unavailable'}

    def provider_prefix_metrics(self):
        resource = self._persistent
        return resource.prefix_metrics.read() if resource is not None and resource.prefix_metrics else {'status': 'unavailable'}

    async def open_backend(self, *, spec: PrimeBackendSpec,
                           services: PrimeApplicationServices) -> PrimeAttachment:
        self._require_available()
        if (type(spec) is not PrimeBackendSpec or type(self._authorization) is not PrimeBackendSpec
                or spec != self._authorization or self._runtime_client is not None
                or spec.model_price is None or self._operator.task_deadline is None
                or self._operator.task_deadline.expired()):
            _invalid()
        self._admit_runtime_limits(spec.limits)
        if self._backend is not None:
            if services is not self._services:
                _invalid()
            return self.attach_backend(self._backend.identity)
        if (any(not callable(getattr(services, name, None))
                for name in ('execute', 'call', 'request_stop', 'close', 'validate_lifecycle'))
                or type(getattr(services, 'identity_sha256', None)) is not str
                or re.fullmatch(r'[0-9a-f]{64}', services.identity_sha256) is None):
            _invalid()
        services.validate_lifecycle()
        self._services = services
        try:
            resource = _launch.persistent_launch(
                self._operator, self._spec, services, spec.limits, PrimeRunHooks(), durable=True)
            self._persistent = resource
            identity = PrimeBackendIdentity(
                spec.session_id, spec.generation, spec.compat_provider_id or 'prime.direct',
                self._spec.application_id, self._spec.application_version, 'asterion.prime',
                _digest(resource.command), resource.binding.binding_fingerprint,
                services.identity_sha256, spec.continuation_policy_id,
                private_root_identity(spec.private_root),
                _digest({**asdict(spec.limits), 'aggregate_tokens': spec.aggregate_tokens,
                         'cost_micros': spec.cost_micros}),
            )
            resource.store = FilePrimeSessionStore(spec.private_root, identity)
            self._backend = PrimeSessionBackend(
                identity=identity, store=resource.store, rpc_session=resource.rpc,
                extension_binding=resource.binding, extension_lease=resource.lease,
                approved_command=resource.command, approved_environment=resource.environment,
                limits=spec.limits, aggregate_tokens=spec.aggregate_tokens, cost_micros=spec.cost_micros,
                model_price=spec.model_price, witness=resource.witness, tool_executor=services,
                compaction_instructions=spec.compaction_instructions, authority_id=spec.authority_id,
                diagnostics=self._operator.diagnostics, task_deadline=self._operator.task_deadline,
            )
            resource.bridge.start()
            self._activate()
            return self.attach_backend(identity)
        except BaseException as error:
            await self.close()
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise ProtocolError('Prime durable application is unavailable') from None

    def attach_backend(self, identity: PrimeBackendIdentity) -> PrimeAttachment:
        self._require_available()
        if self._backend is None:
            _invalid()
        return self._backend.attach(identity)

    def _backend_snapshot(self):
        if self._backend is None:
            _invalid()
        return self._backend.snapshot()

    def _backend_authority_id(self):
        if self._backend is None:
            _invalid()
        return self._authorization.authority_id

    def _backend_checkpoint(self):
        if self._backend is None:
            _invalid()
        recovered = self._persistent.store.recover_checkpoint()
        return None if recovered is None else recovered.checkpoint

    def _backend_prompt_usage(self, command_id: str) -> tuple[int, int]:
        from asterion.runtime.native_rpc import normalize_usage
        if self._backend is None:
            _invalid()
        recovered = self._persistent.store.recover_checkpoint()
        if recovered is None:
            _invalid()
        incoming = outgoing = 0
        for turn in json.loads(recovered.transcript):
            if turn['command_id'] == command_id:
                for event in turn['events']:
                    if event['type'] == 'message_end':
                        usage = normalize_usage(event['payload'])
                        if usage is not None:
                            incoming += usage['input_tokens']
                            outgoing += usage['output_tokens']
        return incoming, outgoing

    def _validate_backend_resources(self) -> None:
        self._require_available()
        if self._backend is None:
            _invalid()
        self._services.validate_lifecycle()
        self._persistent.lease.validate_launch()

    async def _close_backend(self) -> PrimeApplicationCleanup:
        """Reap independent owners before waiting on the durable effect lock."""
        resource = self._persistent
        self._state = 'closing'
        if self._backend is not None:
            self._backend._request_stop()
        effects = model = extension = bridge = workspace = True
        try:
            self._services.request_stop()
        except Exception:
            effects = False
        workspace = await self._workspace_owner.close()
        try:
            await self._services.close()
        except Exception:
            workspace = False
        try:
            await _launch.force_close_rpc(resource.rpc)
        except Exception:
            model = False
        try:
            await asyncio.to_thread(resource.bridge.close)
        except Exception:
            bridge = False
        try:
            if resource.witness is not None:
                resource.witness.close()
            resource.close_descriptors()
        except Exception:
            extension = False
        # A stuck backend cannot prevent the independent reap above. Its task
        # remains cancelled/fenced and no successful cleanup receipt is issued.
        if self._backend is not None:
            task = asyncio.create_task(self._backend.close())
            task.add_done_callback(_consume_cleanup_result)
            done, _ = await asyncio.wait((task,), timeout=0.1)
            if task not in done:
                task.cancel()
                effects = False
            else:
                try:
                    receipt = task.result()
                    effects = effects and receipt.complete
                    workspace = workspace and receipt.application_closed
                except BaseException:
                    effects = False
        try:
            if resource.store is not None:
                resource.store.close()
        except Exception:
            effects = False
        self._cleanup = PrimeApplicationCleanup(effects, model, extension, bridge, workspace)
        if self._cleanup.complete:
            self._state = 'closed'
        return self._cleanup

    async def close(self) -> PrimeApplicationCleanup:
        if self._cleanup is not None and self._cleanup.complete:
            return self._cleanup
        if type(self._authorization) is PrimeBackendSpec and self._persistent is not None:
            return await self._close_backend()
        self._state = 'closing'
        self._text_closed_keys.update(self._text_limits_by_key)
        model_closed = True
        usage = self._text_usage
        async def close_sessions() -> None:
            nonlocal model_closed
            for session in self._text_sessions.values():
                try:
                    await session.close()
                except Exception:
                    model_closed = False
        if usage is not None:
            async with usage.lock:
                await close_sessions()
        else:
            await close_sessions()
        # stop() reaps independently of an active RPC command's asyncio lock.
        effects_stopped = bridge_closed = extension_closed = True
        resource = self._persistent
        if self._services is not None:
            try:
                self._services.request_stop()
            except Exception:
                effects_stopped = False
        # Owned workers must stop before a domain close waits on a cell lock.
        workspace_closed = await self._workspace_owner.close()
        if resource is not None:
            try:
                await asyncio.to_thread(resource.rpc.stop)
                await asyncio.wait_for(resource.rpc.close(), timeout=6)
            except Exception:
                model_closed = False
            try:
                await asyncio.to_thread(resource.bridge.close)
            except Exception:
                bridge_closed = False
            try:
                resource.close_descriptors()
            except Exception:
                extension_closed = False
        elif self._services is not None:
            try:
                await self._services.close()
            except Exception:
                bridge_closed = False
        self._cleanup = PrimeApplicationCleanup(effects_stopped, model_closed, extension_closed,
                                               bridge_closed, workspace_closed)
        if self._cleanup.complete:
            self._state = 'closed'
        return self._cleanup


def _consume_cleanup_result(task):
    try:
        task.exception()
    except BaseException:
        pass


class _OwnerSignal:
    def __init__(self, owner, parent):
        self.owner, self.parent = owner, parent

    @property
    def cancelled(self):
        deadline = self.owner.task_deadline
        return (self.owner.state in ('closing', 'closed')
                or bool(getattr(self.parent, 'cancelled', False))
                or deadline is not None and deadline.expired())


class _OwnedRuntimeSession:
    """Lazy resource acquisition followed by the existing session's sole run loop."""
    def __init__(self, owner):
        self._owner = owner

    @property
    def last_diagnostic(self):
        resource = self._owner._persistent
        return resource.session.last_diagnostic if resource is not None else None

    @property
    def last_diagnostic_id(self):
        diagnostic = self.last_diagnostic
        return diagnostic.diagnostic_id if diagnostic is not None else None

    async def run(self, request, *, signal=None):
        if type(request) is not RunRequest:
            raise ProtocolError("Asterion-prime request is invalid")
        request.to_mapping()
        owner = self._owner
        owner._require_available()
        if owner._run_claimed:
            raise ProtocolError('Prime runtime authority was already consumed')
        owner._run_claimed = True
        combined = _OwnerSignal(owner, signal)
        if combined.cancelled:
            from asterion.runtime.host import RunEvent
            yield RunEvent(request.run_id, 1, 'run.started', {'capabilities': ['prime.tool.ipython']})
            yield RunEvent(request.run_id, 2, 'run.completed', {'status': 'cancelled'})
            return
        limits, hooks = owner._runtime_material
        try:
            owner._services.validate_lifecycle()
            owner._persistent = _launch.persistent_launch(owner._operator, owner._spec, owner._services,
                                                          limits, hooks, metrics_root=owner._metrics_root)
        except BaseException as error:
            await owner.close()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ProtocolError('Prime runtime preparation failed') from None
        owner._activate()
        async for event in owner._persistent.session.run(request, signal=combined):
            yield event


def prepare_prime_application(spec: PrimeApplicationSpec, operator: PrimeOperatorContext, *,
                              authorization: PrimeTextLimits | AsterionPrimeLimits | PrimeBackendSpec
                              ) -> PrimeApplication:
    return PrimeApplication(spec, operator, authorization=authorization)


__all__ = (
    'LiveModelReply', 'LiveModelUsage', 'PrimeApplication', 'PrimeApplicationCleanup',
    'PrimeApplicationServices', 'PrimeApplicationSpec', 'PrimeBackendSpec',
    'PrimeModelView', 'PrimeOperatorContext', 'PrimeRunHooks', 'PrimeTextLimits',
    'PrimeToolModuleArtifact', 'prepare_prime_application',
)
