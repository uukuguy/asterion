"""Asterion operator configuration loading for Prime integrations.

This is the configuration boundary between an operator checkout and a Prime
application.  Leaf integrations receive the resolved mapping and never read
``.env`` themselves.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values


def load_operator_environment(
    operator_root: Path,
    process_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Load the operator ``.env`` and overlay the invoking environment.

    Process values have precedence so an explicit invocation can override the
    repository defaults.  No Prime or provider-specific validation happens at
    this boundary; the selected application validates the values it consumes.
    """

    process = os.environ if process_environment is None else process_environment
    dotenv = {
        name: value
        for name, value in dotenv_values(Path(operator_root) / ".env").items()
        if value is not None
    }
    return {**dotenv, **dict(process)}


__all__ = ("load_operator_environment",)
