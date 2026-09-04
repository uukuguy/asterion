"""Sealed P6 restricted-worker adapter."""

from __future__ import annotations

import json

from asterion.applications.prime_agent.operator.continual_improvement_completion import (
    ContinualImprovementCompletionError,
    canonical_continual_improvement_completion_bytes,
    parse_continual_improvement_completion,
)
from asterion.applications.prime_agent.operator.continual_improvement_workload import (
    P6_CONTINUAL_IMPROVEMENT_ROLE_ID,
    P6_CONTINUAL_IMPROVEMENT_SCENARIO_ID,
    P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioAdapter,
    RestrictedScenarioEngine,
    RestrictedScenarioWorker,
)


def _parse(raw: bytes) -> bool:
    try:
        completion = parse_continual_improvement_completion(
            json.loads(raw.decode("utf-8"))
        )
        return raw == canonical_continual_improvement_completion_bytes(completion)
    except (
        ContinualImprovementCompletionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return False


P6_CONTINUAL_IMPROVEMENT_ADAPTER = RestrictedScenarioAdapter(
    P6_CONTINUAL_IMPROVEMENT_SCENARIO_ID,
    P6_CONTINUAL_IMPROVEMENT_ROLE_ID,
    P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST,
    "/usr/local/bin/prime-continual-improvement.mjs",
    "prime-continual-improvement",
    600,
    4096,
    _parse,
)


class ContinualImprovementWorker(RestrictedScenarioWorker):
    def __init__(self, *, image_digest: str, engine: RestrictedScenarioEngine) -> None:
        super().__init__(
            image_digest=image_digest,
            engine=engine,
            adapter=P6_CONTINUAL_IMPROVEMENT_ADAPTER,
        )
