"""Production-only P1 issuer boundary.

Provider-free code may validate a redacted lifecycle trace, but it cannot
issue a public successful completion. A later operator integration must
install an exact production host capability before this boundary can connect
the Docker worker and model broker.
"""

from __future__ import annotations

from typing import NoReturn

from asterion.applications.prime_agent.operator.ipython_host_orchestrator import (
    IpythonHostLiveRun,
)
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerError
from asterion.runtime.host import CancellationSignal


__all__: tuple[()] = ()


class _ProductionIpythonHostCapability:
    """Nominal future capability; no provider-free construction exists."""

    __slots__ = ()


def _issue_production_ipython_host_live_run(
    *,
    capability: object,
    signal: CancellationSignal | None = None,
) -> IpythonHostLiveRun:
    """Reserved for the exact operator-owned production host integration."""
    del signal
    if type(capability) is not _ProductionIpythonHostCapability:
        _reject()
    # The production capability and its Docker/provider invocation are not
    # implemented in this provider-free slice.
    _reject()


def _issue_docker_model_live_run(
    *,
    service: object,
    lease: object,
    identity: object,
    broker: object,
    signal: CancellationSignal | None = None,
) -> IpythonHostLiveRun:
    """Compatibility-shaped private entry point that fails until production exists."""
    del service, lease, identity, broker
    return _issue_production_ipython_host_live_run(capability=None, signal=signal)


def _reject() -> NoReturn:
    raise PrimeModelBrokerError("prime model broker is unavailable")
