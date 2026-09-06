"""Fail-closed installed host seam for P7 development verification."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import (
    PrimeP7DevelopmentHostService,
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryContext


_APPLICATION_ID = "prime.arc-agi-3"
_APPLICATION_VERSION = "1.0.0"
_CAPABILITY_ID = "prime.arc-agi-3-development"
_PROVIDER_ID = "prime-agent"


class PrimeP7CliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 CLI host is unavailable")


class PrimeP7DevelopmentService(PrimeP7DevelopmentHostService):
    """Reserve P7's public host contract until its operator lifecycle is wired."""

    async def verify(
        self,
        request: PrimeSmallVerificationRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimeSmallVerificationResult:
        del signal
        if type(request) is not PrimeSmallVerificationRequest:
            raise PrimeP7CliHostError()
        raise PrimeP7CliHostError()


def create_prime_p7_cli_factory(*, repo_root: Path) -> HostServiceFactoryBinding:
    del repo_root

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        yield PrimeP7DevelopmentService()

    return HostServiceFactoryBinding(_CAPABILITY_ID, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p7_cli_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        raise PrimeP7CliHostError()


__all__ = (
    "PrimeP7CliHostError",
    "PrimeP7DevelopmentService",
    "create_host_service_factory",
    "create_prime_p7_cli_factory",
)
