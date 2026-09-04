"""Sealed P7 ARC-AGI-3 one-game restricted-worker adapter."""

from __future__ import annotations

import json

from asterion.applications.prime_agent.operator.arc_agi_3_completion import (
    ArcAgi3CompletionError,
    canonical_arc_agi_3_completion_bytes,
    parse_arc_agi_3_completion,
)
from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_ROLE_ID,
    P7_ARC_AGI_3_SCENARIO_ID,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioAdapter,
    RestrictedScenarioEngine,
    RestrictedScenarioWorker,
)


def _parse(raw: bytes) -> bool:
    try:
        completion = parse_arc_agi_3_completion(json.loads(raw.decode("utf-8")))
        return raw == canonical_arc_agi_3_completion_bytes(completion)
    except (ArcAgi3CompletionError, UnicodeDecodeError, json.JSONDecodeError):
        return False


P7_ARC_AGI_3_ADAPTER = RestrictedScenarioAdapter(
    P7_ARC_AGI_3_SCENARIO_ID,
    P7_ARC_AGI_3_ROLE_ID,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
    "/usr/local/bin/prime-arc-agi-3.mjs",
    "prime-arc-agi-3",
    300,
    4096,
    _parse,
)


class ArcAgi3Worker(RestrictedScenarioWorker):
    def __init__(self, *, image_digest: str, engine: RestrictedScenarioEngine) -> None:
        super().__init__(
            image_digest=image_digest, engine=engine, adapter=P7_ARC_AGI_3_ADAPTER
        )
