"""CLI adapter for an explicitly injected :class:`AgentClient`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import TextIO

from asterion.client.interactive import ClientInteractiveError, run_headless, run_interactive
from asterion.client.sdk import AgentClient


class ClientCliError(ValueError):
    """Raised when the client CLI was not explicitly wired by its host."""


def add_client_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("client", help="render one injected client session")
    parser.add_argument("--mode", choices=("interactive", "json", "text"), default="interactive")
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024)


async def run_client_command(
    args: argparse.Namespace, *, client_factory: Callable[[], AgentClient] | None,
    stdout: TextIO,
) -> int:
    if not callable(client_factory):
        raise ClientCliError("client factory is required")
    try:
        client = client_factory()
    except Exception:
        raise ClientCliError("client factory is unavailable") from None
    if not isinstance(client, AgentClient):
        raise ClientCliError("client factory is invalid")
    try:
        if args.mode == "interactive":
            await run_interactive(client, stdout=stdout, max_output_bytes=args.max_output_bytes)
        else:
            await run_headless(client, mode=args.mode, stdout=stdout, max_output_bytes=args.max_output_bytes)
    except ClientInteractiveError:
        raise ClientCliError("client command failed") from None
    return 0
