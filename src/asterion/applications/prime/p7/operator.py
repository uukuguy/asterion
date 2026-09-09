"""Operator-owned fixed model selection for the native P7 application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


_RUNTIME_ID = "asterion.prime"
_PROVIDER = "deepseek"
_MODEL = "deepseek-v4-flash"
_MAX_ACTIONS = 500
_MAX_CALLBACKS = 128
_DEADLINE_MS = 3_600_000


class P7OperatorError(RuntimeError):
    """The fixed P7 model host is unavailable."""


@dataclass(frozen=True, slots=True)
class P7RuntimeSelection:
    runtime_id: str
    provider: str
    model: str
    max_actions: int
    max_callbacks: int
    deadline_ms: int

    def __post_init__(self) -> None:
        if self != P7RuntimeSelection.fixed():
            raise P7OperatorError("P7 runtime selection is invalid")

    @classmethod
    def fixed(cls) -> P7RuntimeSelection:
        value = object.__new__(cls)
        object.__setattr__(value, "runtime_id", _RUNTIME_ID)
        object.__setattr__(value, "provider", _PROVIDER)
        object.__setattr__(value, "model", _MODEL)
        object.__setattr__(value, "max_actions", _MAX_ACTIONS)
        object.__setattr__(value, "max_callbacks", _MAX_CALLBACKS)
        object.__setattr__(value, "deadline_ms", _DEADLINE_MS)
        return value


def resolve_pi_provider(environment: Mapping[str, str], *, model: str) -> str:
    """Resolve only the fixed DeepSeek host from passed operator environment."""

    try:
        available = (
            isinstance(environment, Mapping)
            and model == _MODEL
            and bool(environment.get("DEEPSEEK_API_KEY", "").strip())
        )
    except Exception:
        available = False
    if not available:
        raise P7OperatorError("P7 model host is unavailable") from None
    return _PROVIDER


def resolve_p7_runtime(environment: Mapping[str, str]) -> P7RuntimeSelection:
    """Resolve the one fixed model/runtime preset without exposing tuning knobs."""

    provider = resolve_pi_provider(environment, model=_MODEL)
    return P7RuntimeSelection(
        runtime_id=_RUNTIME_ID,
        provider=provider,
        model=_MODEL,
        max_actions=_MAX_ACTIONS,
        max_callbacks=_MAX_CALLBACKS,
        deadline_ms=_DEADLINE_MS,
    )


def p7_runtime_options(selection: P7RuntimeSelection) -> Mapping[str, str]:
    """Return immutable private factory options for the fixed selection."""

    if type(selection) is not P7RuntimeSelection or selection != P7RuntimeSelection.fixed():
        raise P7OperatorError("P7 runtime selection is invalid")
    return MappingProxyType(
        {
            "deadline_ms": str(selection.deadline_ms),
            "max_actions": str(selection.max_actions),
            "max_callbacks": str(selection.max_callbacks),
            "model": selection.model,
            "provider": selection.provider,
        }
    )


__all__ = (
    "P7OperatorError",
    "P7RuntimeSelection",
    "p7_runtime_options",
    "resolve_p7_runtime",
    "resolve_pi_provider",
)
