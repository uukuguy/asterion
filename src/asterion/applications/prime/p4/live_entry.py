"""Installed-wheel entry for one fixed live P4 commit or recover invocation.

Commit requires a fresh, nonexistent ASTERION_PRIME_P4_PRIVATE_ROOT. Recover
uses that exact root in a second invocation. A new verification pair needs a
new root; this entry never removes or overwrites an existing user's run.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path

from asterion.applications.prime.live_model import LiveModelSession, resolve_live_model_launch
from asterion.applications.prime.p4.live import P4LiveError, run_live_round


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _run(environment):
    mode = environment.get("ASTERION_PRIME_P4_MODE")
    operator_root = environment.get("ASTERION_PRIME_OPERATOR_ROOT")
    private_root = environment.get("ASTERION_PRIME_P4_PRIVATE_ROOT")
    if mode not in {"commit", "recover"} or not operator_root or not private_root:
        raise P4LiveError()
    launch = resolve_live_model_launch(Path(operator_root), environment)

    def factory(mode, cwd):
        return LiveModelSession(command=launch.command, environment=launch.environment, cwd=cwd)

    return await run_live_round(
        mode=mode, private_root=Path(private_root), session_factory=factory,
        command_sha256=_digest(launch.command),
        binding_sha256=_digest({"binding": "prime.live-model", "tools": [], "extensions": []}),
    )


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
