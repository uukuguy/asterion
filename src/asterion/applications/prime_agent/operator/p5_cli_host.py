"""Private P5 CLI assembly helpers.

Route registration deliberately remains outside this module.  The installed
host supplies the already-admitted gateway, image worker, and provider ports.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import re

from .p5_development_host import PrimeP5DevelopmentTrace

P5_CLI_DEADLINE_SECONDS = 300
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PrimeP5CliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 CLI host is unavailable")


async def run_p5_cli_once(
    lifecycle: Callable[[], Awaitable[object]],
) -> PrimeP5DevelopmentTrace:
    """Enforce the one-shot outer deadline and expose only the trace digest."""

    if not callable(lifecycle):
        raise PrimeP5CliHostError()
    task = asyncio.create_task(lifecycle())
    try:
        async with asyncio.timeout(P5_CLI_DEADLINE_SECONDS):
            value = await task
        if (
            type(value) is not PrimeP5DevelopmentTrace
            or _DIGEST.fullmatch(value.trace_sha256) is None
        ):
            raise ValueError
        return value
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise PrimeP5CliHostError() from None


__all__ = ("P5_CLI_DEADLINE_SECONDS", "PrimeP5CliHostError", "run_p5_cli_once")
