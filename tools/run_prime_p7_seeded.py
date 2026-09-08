"""Run the one explicitly seeded P7 integration-chain verification."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from asterion.applications.prime_agent.operator.p7_solving_cli_host import (
    PrimeP7SolvingCliHostError,
    _preflight,
    _run_lifecycle,
)
from asterion.applications.prime_agent.operator.p7_solving_host import (
    P7SolvingReceiptStore,
    PrimeP7SolvingHostError,
)
from asterion.applications.prime_agent.operator.p7_solving_prompt import (
    P7_SEEDED_INTEGRATION_PROMPT,
)
from asterion.services.presentation import TextHostPresentationSink
from asterion.services.progress import TextHostProgressReporter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    try:
        resources = _preflight(Path.cwd())
        receipt = asyncio.run(_run_lifecycle(
            resources, arguments.run_id, receipt_store=P7SolvingReceiptStore(),
            progress=TextHostProgressReporter(sys.stderr),
            presentation=TextHostPresentationSink(sys.stderr),
            prompt=P7_SEEDED_INTEGRATION_PROMPT, mode="seeded",
        ))
        print(json.dumps({
            "mode": "seeded",
            "purpose": "integration chain verification",
            "completed_level_count": receipt.completed_level_count,
            "primitive_action_count": receipt.primitive_action_count,
            "partial_game_score": receipt.partial_game_score,
            "receipt_sha256": receipt.receipt_sha256,
            "run_id": receipt.run_id,
        }, allow_nan=False, separators=(",", ":"), sort_keys=True))
        return 0
    except (PrimeP7SolvingCliHostError, PrimeP7SolvingHostError):
        print("prime P7 seeded integration is unavailable", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
