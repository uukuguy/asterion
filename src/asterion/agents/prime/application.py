"""Independent Prime application ownership without discovery or launch effects.

These are process-local inputs, not an additional serialized protocol. Operator
preflight owns paths, credentials, model selection and verified price evidence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, fields
import math
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from asterion.agents.prime import _launch
from asterion.agents.prime._text_model import (
    LiveModelReply, LiveModelSession, LiveModelUsage, _TextUsage,
)
from asterion.agents.prime.backend import PrimeAttachment
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
from asterion.runtime.host import AgentRuntimeClient, CancellationSignal
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

    def __post_init__(self) -> None:
        for path in (self.executable, self.cwd):
            _path(path)
        if self.entry is not None:
            _path(self.entry)
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
    async def call(self, request_id: str, method: str, params: Mapping[str, object],
                   signal: CancellationSignal) -> Mapping[str, object]: ...
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


class PrimeApplication:
    """Resource owner with fixed authorization; construction never launches Pi."""

    __slots__ = ('_spec', '_operator', '_authorization', '_state',
                 '_text_limits_by_key', '_cleanup', '_text_sessions', '_text_closed_keys',
                 '_text_usage')

    def __init__(self, spec: PrimeApplicationSpec, operator: PrimeOperatorContext, *,
                 authorization: PrimeTextLimits | AsterionPrimeLimits | PrimeBackendSpec):
        if type(spec) is not PrimeApplicationSpec or type(operator) is not PrimeOperatorContext:
            _invalid()
        if spec.profile == 'text-only':
            if type(authorization) is not PrimeTextLimits:
                _invalid()
        elif type(authorization) not in (AsterionPrimeLimits, PrimeBackendSpec):
            _invalid()
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
        self._admit_runtime_limits(limits)
        raise ProtocolError('Prime application runtime profile is not assembled')

    async def open_backend(self, *, spec: PrimeBackendSpec,
                           services: PrimeApplicationServices) -> PrimeAttachment:
        self._require_available()
        raise ProtocolError('Prime application backend profile is not assembled')

    async def close(self) -> PrimeApplicationCleanup:
        if self._cleanup is not None and self._cleanup.complete:
            return self._cleanup
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
        self._cleanup = PrimeApplicationCleanup(model_closed, model_closed, True, True, True)
        if self._cleanup.complete:
            self._state = 'closed'
        return self._cleanup


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
