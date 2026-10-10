"""Fixed installed-wheel entry point for the real P3 model preset."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Mapping

from asterion.applications.prime.live_model import bounded_text_limits, resolve_live_model_context
from asterion.agents.prime.application import PrimeApplicationSpec, prepare_prime_application
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.p3.live import run_live_verification


class P3LiveEntryError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P3 live verification failed")


async def run_live_preset(environment: Mapping[str, str]):
    """Resolve operator resources and run one bounded, fresh P3 invocation."""
    try:
        operator_value = environment["ASTERION_PRIME_OPERATOR_ROOT"]
        private_value = environment["ASTERION_PRIME_P3_PRIVATE_ROOT"]
        if not operator_value or not private_value:
            raise ValueError
        operator_root = Path(operator_value).resolve(strict=True)
        private_base = Path(private_value).resolve()
        private_base.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_root = private_base / ("live-" + secrets.token_hex(12))
        limits = bounded_text_limits()
        deadline = TaskDeadline(deadline_monotonic=time.monotonic() + limits.deadline_seconds,
                                deadline_epoch=time.time() + limits.deadline_seconds)
        context = resolve_live_model_context(Path(operator_root), environment, task_deadline=deadline)
        prime = prepare_prime_application(
            PrimeApplicationSpec("prime.recursive-workflow", "1.0.0", "text-only"),
            context, authorization=limits,
        )
        return await run_live_verification(prime=prime, private_root=private_root, limits=limits)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise P3LiveEntryError() from None

def main() -> int:
    try:
        result = asyncio.run(run_live_preset(dict(os.environ)))
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
        return 0 if result.status == "completed" else 1
    except Exception:
        print("P3 live verification failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
