"""Installed-wheel entry for one fixed live P4 commit or recover invocation.

Commit requires a fresh, nonexistent ASTERION_PRIME_P4_PRIVATE_ROOT. Recover
uses that exact root in a second invocation. A new verification pair needs a
new root; this entry never removes or overwrites an existing user's run.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
import json
import os
from pathlib import Path

from asterion.applications.prime.live_model import bounded_text_limits, resolve_live_model_context
from asterion.agents.prime.application import PrimeApplicationSpec, prepare_prime_application
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.p4.live import P4LiveError, run_live_round


async def _run(environment):
    mode = environment.get("ASTERION_PRIME_P4_MODE")
    operator_root = environment.get("ASTERION_PRIME_OPERATOR_ROOT")
    private_root = environment.get("ASTERION_PRIME_P4_PRIVATE_ROOT")
    if mode not in {"commit", "recover"} or not operator_root or not private_root:
        raise P4LiveError()
    limits = bounded_text_limits()
    deadline = TaskDeadline(deadline_monotonic=time.monotonic() + limits.deadline_seconds,
                            deadline_epoch=time.time() + limits.deadline_seconds)
    context = resolve_live_model_context(Path(operator_root), environment, task_deadline=deadline)
    prime = prepare_prime_application(
        PrimeApplicationSpec("prime.long-session-continuity", "1.0.0", "text-only"),
        context, authorization=limits,
    )
    return await run_live_round(mode=mode, private_root=Path(private_root), prime=prime, limits=limits)


def main() -> int:
    try:
        result = asyncio.run(_run(dict(os.environ)))
        print(json.dumps(asdict(result), separators=(",", ":")), flush=True)
        return 0 if result.status in {"committed", "recovered"} else 2
    except BaseException:
        print('{"status":"protocol-failure","private_root_redacted":true}', flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
