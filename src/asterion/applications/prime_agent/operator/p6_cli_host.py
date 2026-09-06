"""Unavailable seam for the future P6 continual-improvement CLI host."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
)


_CAPABILITY_ID = "prime.continual-improvement-development"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.continual-improvement"
_APPLICATION_VERSION = "1.0.0"


class PrimeP6CliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P6 CLI host is unavailable")


@asynccontextmanager
async def _open_host(
    context: HostServiceFactoryContext,
) -> AsyncIterator[object]:
    if (
        context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or context.options
    ):
        raise PrimeP6CliHostError()
    raise PrimeP6CliHostError()
    yield object()


def create_host_service_factory() -> HostServiceFactoryBinding:
    """Expose P6's identity-bound host seam without a lifecycle implementation."""
    return HostServiceFactoryBinding(
        capability_id=_CAPABILITY_ID,
        option_names=(),
        factory=_open_host,
    )


__all__ = ("PrimeP6CliHostError", "create_host_service_factory")
