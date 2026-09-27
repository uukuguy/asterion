"""Asterion operator configuration loading for Prime integrations.

This is the configuration boundary between an operator checkout and a Prime
application.  Leaf integrations receive the resolved mapping and never read
``.env`` themselves.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
import shlex

try:
    from dotenv import dotenv_values as _dotenv_values
except ModuleNotFoundError:  # pragma: no cover - exercised by installed-wheel smoke tests
    _dotenv_values = None


def _fallback_dotenv_values(path: Path) -> dict[str, str]:
    """Parse the small operator ``.env`` subset without an optional dependency."""

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        name, raw = stripped.split("=", 1)
        name = name.strip()
        if (
            not name
            or not name.isascii()
            or not name.replace("_", "a").isalnum()
            or name[0].isdigit()
        ):
            continue
        try:
            parsed = shlex.split(raw, comments=True, posix=True)
        except ValueError:
            continue
        values[name] = parsed[0] if parsed else ""
    return values


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
    path = Path(operator_root) / ".env"
    loaded = _dotenv_values(path) if _dotenv_values is not None else _fallback_dotenv_values(path)
    dotenv = {name: value for name, value in loaded.items() if value is not None}
    return {**dotenv, **dict(process)}


__all__ = ("load_operator_environment",)
