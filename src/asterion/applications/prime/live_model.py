"""Transitional application adapter to Prime's private bounded text engine.

Only this operator integration resolves checkout configuration. Core receives
preflighted data; old launch/factory shapes remain until consumers migrate.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path

from asterion.agents.prime import _launch
from asterion.agents.prime._text_model import (
    LiveModelError, LiveModelReply, LiveModelSession as _PrimeTextSession, LiveModelUsage,
)
from asterion.agents.prime.application import PrimeApplicationSpec, PrimeOperatorContext, PrimeTextLimits
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.operator_config import load_operator_environment, resolve_pi_effort


def bounded_text_limits() -> PrimeTextLimits:
    """The existing operator-approved bounded live preset and exact catalog price."""
    return PrimeTextLimits(120.0, 4, 8192, 32768, 16000, 8000, 3000, 512,
                           ModelPrice(300000, 1200000))


class LiveModelSession(_PrimeTextSession):
    """Preserve unmigrated application factories without a second session engine."""
    def __init__(self, *, command: tuple[str, ...], environment: Mapping[str, str], cwd: Path):
        super().__init__(command=command, environment=environment, cwd=cwd,
                         limits=bounded_text_limits(), provider='deepseek', model='deepseek-flash')


@dataclass(frozen=True, slots=True, repr=False)
class LiveModelLaunch:
    command: tuple[str, ...]
    environment: Mapping[str, str]
    cwd: Path

    def __repr__(self) -> str:
        return '<LiveModelLaunch redacted>'


def resolve_live_model_context(
    operator_root: Path, environment: Mapping[str, str], *,
    task_deadline: TaskDeadline | None = None,
) -> PrimeOperatorContext:
    """Preflight the fixed, no-tool Pi launch from operator-owned inputs.

    This is an application integration boundary. It reads only the operator
    root's `.env`, never framework configuration or a neighboring source tree.
    """

    import asterion

    try:
        if not isinstance(operator_root, Path) or not isinstance(environment, Mapping):
            raise ValueError
        root = operator_root.resolve(strict=True)
        package = Path(str(asterion.__file__)).resolve(strict=True)
        if (
            not root.is_dir()
            or package.is_relative_to(root)
            or "site-packages" not in package.parts
        ):
            raise ValueError
        merged = load_operator_environment(root, environment)
        effort = resolve_pi_effort(merged, default="off")
        credential = merged.get("DEEPSEEK_API_KEY", "")
        if (
            type(credential) is not str
            or not credential.strip()
            or any(character in credential for character in "\x00\r\n")
        ):
            raise ValueError
        executable_paths = []
        for name in ("ASTERION_PRIME_NODE", "ASTERION_PRIME_PI_ENTRY"):
            value = merged.get(name)
            if type(value) is not str or not value.strip():
                raise ValueError
            path = Path(value).resolve(strict=True)
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ValueError
            executable_paths.append(str(path))
        approved_environment = {"DEEPSEEK_API_KEY": credential}
        for name in ("PATH", "LANG", "LC_ALL"):
            value = environment.get(name)
            if type(value) is str and value and "\x00" not in value:
                approved_environment[name] = value
        return PrimeOperatorContext(
            executable=Path(executable_paths[0]), entry=Path(executable_paths[1]),
            cwd=root, provider='deepseek', model='deepseek-flash', effort=effort,
            environment=approved_environment, task_deadline=task_deadline,
        )
    except Exception:
        raise LiveModelError() from None



def resolve_live_model_launch(operator_root: Path, environment: Mapping[str, str]) -> LiveModelLaunch:
    operator = resolve_live_model_context(operator_root, environment)
    spec = PrimeApplicationSpec('prime.compat.text', '1.0.0', 'text-only')
    return LiveModelLaunch(_launch.text_command(operator, spec), operator.environment, operator.cwd)


__all__ = (
    'LiveModelError', 'LiveModelLaunch', 'LiveModelReply', 'LiveModelSession', 'LiveModelUsage',
    'bounded_text_limits', 'resolve_live_model_context', 'resolve_live_model_launch',
)
