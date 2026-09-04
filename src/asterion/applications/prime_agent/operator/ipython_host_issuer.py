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


async def _issue_production_ipython_host_live_run(
    *,
    capability: object,
    signal: CancellationSignal | None = None,
) -> IpythonHostLiveRun:
    """Consume only a production run authority; live execution is not wired yet."""
    from asterion.applications.prime_agent.operator.production_host import (
        _consume_production_authority,
    )

    del signal
    try:
        _consume_production_authority(capability)
    except BaseException:
        _reject()
    # This slice deliberately stops before Docker/model execution.  The consumed
    # authority cannot be replayed when the live integration is added.
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
    del signal
    _reject()


def _reject() -> NoReturn:
    raise PrimeModelBrokerError("prime model broker is unavailable")
