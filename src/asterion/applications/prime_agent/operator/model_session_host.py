"""Prime-owned private configuration and lease factory for model sessions.

This module does not construct a provider client or perform a network
operation. It verifies operator-private readiness and issues revocable opaque
leases to the generic host-service boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from asterion.services.bounded_model_session import (
    BoundedModelSessionLease,
    BoundedModelSessionReceipt,
    BoundedModelSessionRequest,
    BoundedModelSessionService,
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


class PrimeModelSessionHostError(ValueError):
    """Raised without private configuration details at the Prime host boundary."""


@dataclass(frozen=True, repr=False)
class _PrivatePrimeModelConfig:
    api_key: str
    model_id: str

    def __repr__(self) -> str:
        return "_PrivatePrimeModelConfig(redacted)"


@dataclass(repr=False)
class _PrimeBoundedModelSessionService(BoundedModelSessionService):
    """Lease issuer which retains private provider configuration host-side."""

    _config: _PrivatePrimeModelConfig
    _next_session: int = 0
    _active: dict[str, BoundedModelSessionLease] = field(default_factory=dict)

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
        api_key = values.get("PRIME_MODEL_API_KEY")
        model_id = values.get("PRIME_MODEL_ID")
        if (
            type(api_key) is not str
            or not api_key.strip()
            or type(model_id) is not str
            or not model_id.strip()
        ):
            raise ValueError
        return _PrivatePrimeModelConfig(api_key=api_key, model_id=model_id)
    except (OSError, TypeError, ValueError):
        raise PrimeModelSessionHostError("prime model session is unavailable") from None


__all__ = (
    "PrimeModelSessionHostError",
    "create_bounded_model_session_factory",
    "create_host_service_factory",
)
