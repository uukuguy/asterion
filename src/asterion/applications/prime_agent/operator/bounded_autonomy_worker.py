"""Sealed P5 restricted-worker adapter."""

from __future__ import annotations

import json

from asterion.applications.prime_agent.operator.bounded_autonomy_completion import (
    BoundedAutonomyCompletionError,
    canonical_bounded_autonomy_completion_bytes,
    parse_bounded_autonomy_completion,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_ROLE_ID,
    P5_BOUNDED_AUTONOMY_SCENARIO_ID,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioAdapter,
    RestrictedScenarioEngine,
    RestrictedScenarioWorker,
)


def _parse(raw: bytes) -> bool:
    try:
        completion = parse_bounded_autonomy_completion(json.loads(raw.decode("utf-8")))
        return raw == canonical_bounded_autonomy_completion_bytes(completion)
    except (BoundedAutonomyCompletionError, UnicodeDecodeError, json.JSONDecodeError):
        return False


P5_BOUNDED_AUTONOMY_ADAPTER = RestrictedScenarioAdapter(
    P5_BOUNDED_AUTONOMY_SCENARIO_ID,
    P5_BOUNDED_AUTONOMY_ROLE_ID,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
    "/usr/local/bin/prime-bounded-autonomy.mjs",
    "prime-bounded-autonomy",
    300,
    4096,
    _parse,
)


class BoundedAutonomyWorker(RestrictedScenarioWorker):
    def __init__(self, *, image_digest: str, engine: RestrictedScenarioEngine) -> None:
        super().__init__(
            image_digest=image_digest, engine=engine, adapter=P5_BOUNDED_AUTONOMY_ADAPTER
        )
