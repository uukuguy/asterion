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


EFFORT_ENV = "ASTERION_PRIME_EFFORT"
PI_EFFORTS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def resolve_pi_effort(environment: Mapping[str, str], *, default: str) -> str:
    """Resolve an explicit Prime effort or retain the launcher's existing default.

    Values are concrete selectors accepted by the operator-installed Pi CLI.
    This reads only the injected mapping and never configuration files.
    """

    effort = environment.get(EFFORT_ENV, default)
    if type(effort) is not str or effort not in PI_EFFORTS:
        raise ValueError("Prime reasoning effort is invalid")
    return effort


def apply_pi_effort(command: tuple[str, ...], environment: Mapping[str, str]) -> tuple[str, ...]:
    """Bind explicit operator effort to the approved argv without mutating it."""

    if EFFORT_ENV not in environment:
        return command
    effort = resolve_pi_effort(environment, default="medium")
    positions = [index for index, part in enumerate(command) if part == "--thinking"]
    if len(positions) > 1 or (positions and positions[0] + 1 >= len(command)):
        raise ValueError("Prime reasoning effort is invalid")
    if not positions:
        return (*command, "--thinking", effort)
    index = positions[0] + 1
    return (*command[:index], effort, *command[index + 1:])


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
    *,
    file_owned_keys: tuple[str, ...] = (EFFORT_ENV,),
) -> dict[str, str]:
    """Load the operator ``.env`` and overlay the invoking environment.

    Process values have precedence except for configuration-owned selections:
    an explicit file value wins over stale terminal exports. Prime effort is
    configuration-owned; integrations may declare their existing model keys
    the same way. The selected launcher validates the values it consumes.
    """

    process = os.environ if process_environment is None else process_environment
    path = Path(operator_root) / ".env"
    loaded = _dotenv_values(path) if _dotenv_values is not None else _fallback_dotenv_values(path)
    dotenv = {name: value for name, value in loaded.items() if value is not None}
    values = {**dotenv, **dict(process)}
    for name in file_owned_keys:
        if name in dotenv:
            values[name] = dotenv[name]
    return values


__all__ = ("EFFORT_ENV", "PI_EFFORTS", "apply_pi_effort", "load_operator_environment", "resolve_pi_effort")
