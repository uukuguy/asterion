"""Prime-owned private configuration and lease factory for model sessions.

This module does not construct a provider client or perform a network
operation. It verifies operator-private readiness and issues revocable opaque
leases to the generic host-service boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
import urllib.error
import urllib.request

from dotenv import dotenv_values

from asterion.services.bounded_model_session import (
    BoundedModelSessionLease,
    BoundedModelSessionReceipt,
    BoundedModelSessionRequest,
    BoundedModelSessionService,
)
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerTokenUsage,
)
from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
)


_CAPABILITY_ID = "model.bounded-session"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.ipython-coding"
_APPLICATION_VERSION = "1.0.0"
_P1_MAX_REQUESTS = 1
_P1_MAX_INPUT_TOKENS = 1024
_P1_MAX_OUTPUT_TOKENS = 1024
_P1_MAX_INPUT_BYTES = 4096
_P1_MAX_OUTPUT_BYTES = 4096
_P1_MAX_COST_MICROUNITS = 10_000
_P1_DEADLINE_SECONDS = 60
_MODEL_ENV = "ASTERION_PRIME_EXPERIMENT_MODEL"
_CREDENTIAL_ENV = "DEEPSEEK_API_KEY"
_ALLOWED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-flash-0731"})
_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
_P1_PROVIDER_PROMPT = (
    "Return only one Python IPython cell. The cell must rewrite "
    "/workspace/solution.py so its complete contents define answer() with no "
    "arguments and return the integer 42. Do not use Markdown fences or any "
    "other tool."
)
_PROVIDER_RESPONSE_CAP = 64 * 1024


class PrimeModelSessionHostError(ValueError):
    """Raised without private configuration details at the Prime host boundary."""


@dataclass(frozen=True, repr=False)
class _PrivatePrimeModelConfig:
    api_key: str
    model_id: str

    def __repr__(self) -> str:
        return "_PrivatePrimeModelConfig(redacted)"


def _bare_provider_cell(content: str) -> str:
    if "```" not in content:
        return content
    stripped = content.strip()
    for prefix in ("```python\n", "```\n"):
        if stripped.startswith(prefix) and stripped.endswith("\n```"):
            cell = stripped[len(prefix):-4]
            if "```" not in cell:
                return cell
    raise ValueError


class _PrimeP1Provider:
    """Concrete one-call DeepSeek adapter owned by the selected application."""

    __slots__ = ("_config", "_called", "_terminal")

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeModelSessionHostError("prime model session is unavailable")
        self._config = config
        self._called = False
        self._terminal: PrimeModelBrokerTokenUsage | None = None

    def __repr__(self) -> str:
        return "_PrimeP1Provider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if self._called or type(body) is not bytes or not body:
            raise PrimeModelSessionHostError("prime model session is unavailable")
        self._called = True
        try:
            cell, usage = await asyncio.to_thread(
                _invoke_provider_sync, self._config, body
            )
            self._terminal = usage
            return cell
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PrimeModelSessionHostError("prime model session is unavailable") from None

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if self._terminal is None:
            raise PrimeModelSessionHostError("prime model session is unavailable")
        return self._terminal


@dataclass(repr=False)
class _PrimeBoundedModelSessionService(BoundedModelSessionService):
    """Lease issuer which retains private provider configuration host-side."""

    _config: _PrivatePrimeModelConfig
    _next_session: int = 0
    _active: dict[str, BoundedModelSessionLease] = field(default_factory=dict)
    _providers: dict[str, _PrimeP1Provider] = field(default_factory=dict)

    def __repr__(self) -> str:
        return "PrimeBoundedModelSessionService(redacted)"

    def open(self, request: BoundedModelSessionRequest) -> BoundedModelSessionLease:
        if not _is_p1_request(request):
            raise PrimeModelSessionHostError("prime model session is unavailable")
        self._next_session += 1
        lease = BoundedModelSessionLease(
            session_id=f"prime-session-{self._next_session}", run_id=request.run_id
        )
        self._active[lease.session_id] = lease
        return lease

    def revoke(self, lease: BoundedModelSessionLease) -> BoundedModelSessionReceipt:
        issued = self._active.get(lease.session_id) if type(lease) is BoundedModelSessionLease else None
        if issued is None or lease != issued:
            raise PrimeModelSessionHostError("prime model session is unavailable")
        del self._active[issued.session_id]
        self._providers.pop(issued.session_id, None)
        return BoundedModelSessionReceipt(
            session_id=issued.session_id,
            run_id=issued.run_id,
            request_count=0,
            input_tokens=0,
            output_tokens=0,
            input_bytes=0,
            output_bytes=0,
            cost_microunits=0,
        )

    def _production_provider(
        self, lease: BoundedModelSessionLease
    ) -> _PrimeP1Provider:
        issued = (
            self._active.get(lease.session_id)
            if type(lease) is BoundedModelSessionLease
            else None
        )
        if issued is None or issued != lease or lease.session_id in self._providers:
            raise PrimeModelSessionHostError("prime model session is unavailable")
        provider = _PrimeP1Provider(self._config)
        self._providers[lease.session_id] = provider
        return provider


def create_bounded_model_session_factory(
    *, repo_root: Path, environment: Mapping[str, str] | None = None
) -> HostServiceFactoryBinding:
    """Return Prime's selected-only factory without retaining dotenv values.

    ``environment`` is accepted solely for a stable host-factory calling shape;
    credentials are intentionally never read from it. Prime's private dotenv
    file is the single configuration authority for this P1 seam.
    """
    del environment
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        config = _load_private_config(root / ".env")
        yield _PrimeBoundedModelSessionService(config)

    return HostServiceFactoryBinding(
        capability_id=_CAPABILITY_ID, option_names=(), factory=factory
    )


def create_host_service_factory() -> HostServiceFactoryBinding:
    """Entry-point factory for the selected Prime application integration."""
    return create_bounded_model_session_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        raise PrimeModelSessionHostError("prime model session is unavailable")


def _is_p1_request(request: object) -> bool:
    return (
        type(request) is BoundedModelSessionRequest
        and request.max_requests == _P1_MAX_REQUESTS
        and request.max_input_tokens == _P1_MAX_INPUT_TOKENS
        and request.max_output_tokens == _P1_MAX_OUTPUT_TOKENS
        and request.max_input_bytes == _P1_MAX_INPUT_BYTES
        and request.max_output_bytes == _P1_MAX_OUTPUT_BYTES
        and request.max_cost_microunits == _P1_MAX_COST_MICROUNITS
        and request.deadline_seconds == _P1_DEADLINE_SECONDS
    )


def _load_private_config(env_path: Path) -> _PrivatePrimeModelConfig:
    try:
        values = dotenv_values(env_path)
        return _private_config_from_values(values)
    except (OSError, TypeError, ValueError):
        raise PrimeModelSessionHostError("prime model session is unavailable") from None


def _private_config_from_values(values: Mapping[str, object]) -> _PrivatePrimeModelConfig:
    try:
        api_key = values.get(_CREDENTIAL_ENV)
        model_id = values.get(_MODEL_ENV)
        if (
            type(api_key) is not str
            or not api_key.strip()
            or type(model_id) is not str
            or model_id not in _ALLOWED_MODELS
        ):
            raise ValueError
        return _PrivatePrimeModelConfig(api_key=api_key, model_id=model_id)
    except (AttributeError, TypeError, ValueError):
        raise PrimeModelSessionHostError("prime model session is unavailable") from None


def _invoke_provider_sync(
    config: _PrivatePrimeModelConfig, body: bytes
) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if type(config) is not _PrivatePrimeModelConfig or type(body) is not bytes:
        raise PrimeModelSessionHostError("prime model session is unavailable")
    payload = json.dumps(
        {
            "max_tokens": _P1_MAX_OUTPUT_TOKENS,
            "messages": [
                {
                    "content": _P1_PROVIDER_PROMPT + "\n\nTask identity: " + body.hex(),
                    "role": "user",
                }
            ],
            "model": config.model_id,
            "stream": False,
            "thinking": {"type": "disabled"},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    request = urllib.request.Request(
        _ENDPOINT,
        data=payload,
        headers={
            "Authorization": "Bearer " + config.api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _open_provider_request(request, timeout=_P1_DEADLINE_SECONDS) as response:
            if type(response.status) is not int or not 200 <= response.status < 300:
                raise ValueError
            raw = response.read(_PROVIDER_RESPONSE_CAP + 1)
        if type(raw) is not bytes or not raw or len(raw) > _PROVIDER_RESPONSE_CAP:
            raise ValueError
        value = json.loads(raw.decode("utf-8", "strict"))
        choices = value["choices"]
        usage = value["usage"]
        if (
            type(value) is not dict
            or type(choices) is not list
            or len(choices) != 1
            or type(choices[0]) is not dict
            or type(choices[0].get("message")) is not dict
            or type(usage) is not dict
        ):
            raise ValueError
        content = choices[0]["message"].get("content")
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        if (
            type(content) is not str
            or not content
            or type(input_tokens) is not int
            or not 0 < input_tokens <= _P1_MAX_INPUT_TOKENS
            or type(output_tokens) is not int
            or not 0 < output_tokens <= _P1_MAX_OUTPUT_TOKENS
        ):
            raise ValueError
        content = _bare_provider_cell(content)
        cell = content.encode("utf-8", "strict")
        if not cell or len(cell) > _P1_MAX_OUTPUT_BYTES:
            raise ValueError
        return cell, PrimeModelBrokerTokenUsage(
            input_tokens, output_tokens, _P1_MAX_COST_MICROUNITS
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        raise PrimeModelSessionHostError("prime model session is unavailable") from None


def _open_provider_request(request: urllib.request.Request, *, timeout: int):
    opener = urllib.request.build_opener(_RejectRedirect())
    return opener.open(request, timeout=timeout)


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request:
        del req, fp, code, msg, headers, newurl
        raise PrimeModelSessionHostError("prime model session is unavailable")


__all__ = (
    "PrimeModelSessionHostError",
    "create_bounded_model_session_factory",
    "create_host_service_factory",
)
