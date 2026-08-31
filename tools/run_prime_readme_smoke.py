"""Start one bounded README-style Prime RLM smoke without checkpoint maintenance."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from tools.prime_native_rlm_experiment import (
    native_rlm_model_selector_digest,
    prepare_native_rlm_experiment,
    resolve_native_rlm_model,
    run_native_rlm_controlled_probe,
    run_native_rlm_experiment,
    run_owned_native_rlm_sidecar_probe,
)
from tools.verify_prime_loop import (
    _native_rlm_environment,
    _native_rlm_runtime_resources,
    verify_preflight,
)


def main() -> int:
    source_root = Path("3th-party/prime-agent")
    try:
        environment = _native_rlm_environment()
        reservation = prepare_native_rlm_experiment(
            None, max_cost_micros=None, deadline_ms=600_000, environ=environment
        )
        selection = resolve_native_rlm_model(environment)
        resources = _native_rlm_runtime_resources(
            source_root, verify_preflight(source_root)
        )
        root = Path(tempfile.mkdtemp(prefix="asterion-readme-rlm-", dir="/tmp"))
        root.chmod(0o700)

        async def runner(active: object) -> object:
            return await run_owned_native_rlm_sidecar_probe(
                active,
                selection,
                root,
                resources,
                environ=environment,
                probe=lambda sidecar: run_native_rlm_controlled_probe(
                    sidecar,
                    active,
                    root,
                    exercise_application=False,
                    exercise_checkpoint=False,
                    exercise_cancellation=False,
                    exercise_budget_probe=False,
                    expected_model_selector_digest=native_rlm_model_selector_digest(
                        selection
                    ),
                ),
            )

        result = asyncio.run(run_native_rlm_experiment(reservation, runner))
        print(json.dumps({"status": result["status"], "scenario": "readme-rlm-smoke"}))
        return 0
    except Exception:
        print(json.dumps({"status": "External-limited", "scenario": "readme-rlm-smoke"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
