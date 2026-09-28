"""Operator-owned model selection for the native P7 applications.

``ASTERION_PRIME_PROVIDER`` and ``ASTERION_PRIME_MODEL`` are the only model
controls for P7. They are operator-owned values that reach the operator through
its merged environment (``.env`` plus the process environment); framework
modules never read them. This module is the single place that reads, default-
applies and validates that selection, so the operator, the runtime factories
and the trace identities cannot drift apart.

Validation is fail closed:

* the provider must exist in the Pi profile's ``models-store.json`` catalog;
* the model must be listed for that provider;
* the provider must have a credential in the profile's ``auth.json`` or in one
  of its declared operator environment variables.

Every failure surfaces as :class:`P7ModelSelectionError` with a body-free
message; callers translate it into their own public-safe error.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

DEFAULT_PROVIDER = "openai-codex"
DEFAULT_MODEL = "gpt-6-sol"
PROVIDER_ENV = "ASTERION_PRIME_PROVIDER"
MODEL_ENV = "ASTERION_PRIME_MODEL"

_MAX_NAME_CHARACTERS = 128
_MODELS_STORE = "models-store.json"
_AUTH = "auth.json"

# Provider -> the operator-owned environment variables the Pi host reads for
# that provider's credential. ``auth.json`` remains the primary source; these
# names are the operator's environment fallback, so a provider whose key is not
# declared here fails closed instead of silently starting unauthenticated.
_PROVIDER_CREDENTIAL_ENVIRONMENT: Mapping[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "huggingface": ("HF_TOKEN", "HUGGINGFACE_API_KEY"),
    "minimax": ("MINIMAX_API_KEY",),
    "moonshotai": ("MOONSHOT_API_KEY",),
    "moonshotai-cn": ("MOONSHOT_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openai-codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
}


class P7ModelSelectionError(RuntimeError):
    """The operator-declared P7 model selection is unusable."""


def valid_selection_name(value: object) -> bool:
    """Accept only a bounded, printable, ASCII provider or model name."""

    return (
        type(value) is str
        and 0 < len(value) <= _MAX_NAME_CHARACTERS
        and value.isascii()
        and all(ord(character) > 32 and ord(character) != 127 for character in value)
    )


@dataclass(frozen=True, slots=True)
class P7ModelSelection:
    """The one provider/model pair the native P7 applications may run."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        if not valid_selection_name(self.provider) or not valid_selection_name(self.model):
            raise P7ModelSelectionError("P7 model selection is invalid")


def declared_model_selection(environment: Mapping[str, str]) -> P7ModelSelection:
    """Read the operator-declared selection, applying the documented defaults.

    Shape validation only: this never touches the Pi profile, so an operator
    that is merely reporting what it was asked to run can use it without
    claiming the selection is usable.
    """

    try:
        if not isinstance(environment, Mapping):
            raise P7ModelSelectionError("P7 model selection is invalid")
        provider = environment.get(PROVIDER_ENV, DEFAULT_PROVIDER)
        model = environment.get(MODEL_ENV, DEFAULT_MODEL)
        return P7ModelSelection(provider=provider, model=model)
    except P7ModelSelectionError:
        raise
    except Exception:
        raise P7ModelSelectionError("P7 model selection is invalid") from None


def resolve_model_selection(environment: Mapping[str, str]) -> P7ModelSelection:
    """Resolve one usable selection from the operator environment."""

    selection = declared_model_selection(environment)
    try:
        agent_dir = _agent_dir(environment)
        catalog = _catalog(agent_dir)
        models = _provider_models(catalog, selection.provider)
        if selection.model not in models:
            raise P7ModelSelectionError("P7 model selection is unlisted")
        if not _has_credential(agent_dir, environment, selection.provider):
            raise P7ModelSelectionError("P7 model selection is unauthenticated")
    except P7ModelSelectionError:
        raise
    except Exception:
        raise P7ModelSelectionError("P7 model selection is unavailable") from None
    return selection


def trace_model_id(environment: Mapping[str, str]) -> str:
    """Return the model identity a trace must record for this environment."""

    return declared_model_selection(environment).model


def _agent_dir(environment: Mapping[str, str]) -> Path:
    from asterion.applications.prime.p7 import live

    return live.resolve_pi_agent_dir(environment)


def _catalog(agent_dir: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads((agent_dir / _MODELS_STORE).read_text(encoding="utf-8"))
    except Exception:
        raise P7ModelSelectionError("P7 model selection is unavailable") from None
    if not isinstance(raw, Mapping):
        raise P7ModelSelectionError("P7 model selection is unavailable")
    return raw


def _provider_models(catalog: Mapping[str, Any], provider: str) -> tuple[str, ...]:
    """Return the model ids the catalog lists for one provider."""

    entry = catalog.get(provider)
    if not isinstance(entry, Mapping):
        raise P7ModelSelectionError("P7 model selection is unlisted")
    models = entry.get("models", ())
    identifiers: list[str] = []
    if isinstance(models, Mapping):
        identifiers = [name for name in models if valid_selection_name(name)]
    elif isinstance(models, (list, tuple)):
        for item in models:
            identifier = item.get("id") if isinstance(item, Mapping) else item
            if valid_selection_name(identifier):
                identifiers.append(identifier)
    return tuple(identifiers)


def _has_credential(
    agent_dir: Path, environment: Mapping[str, str], provider: str
) -> bool:
    """Require a stored credential or a declared operator environment key."""

    try:
        stored = json.loads((agent_dir / _AUTH).read_text(encoding="utf-8"))
    except Exception:
        stored = None
    if isinstance(stored, Mapping):
        entry = stored.get(provider)
        if isinstance(entry, Mapping) and entry:
            return True
        if type(entry) is str and entry.strip():
            return True
    for name in _PROVIDER_CREDENTIAL_ENVIRONMENT.get(provider, ()):
        value = environment.get(name)
        if type(value) is str and value.strip():
            return True
    return False


__all__ = (
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "MODEL_ENV",
    "PROVIDER_ENV",
    "P7ModelSelection",
    "P7ModelSelectionError",
    "declared_model_selection",
    "resolve_model_selection",
    "trace_model_id",
    "valid_selection_name",
)
